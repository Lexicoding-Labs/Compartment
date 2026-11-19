import json
import os
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from uuid import UUID

import httpx
from fastapi import Depends, FastAPI, Header
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import chat, coordination, engine, org, runtime
from . import governance as gov
from .store import Fault, Store, require


class Rule(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    when: Literal["finding", "review"]
    effect: Literal["open", "hold"]


class ChatInput(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    client_id: UUID


class NewRun(BaseModel):
    objective: str = Field(
        default=engine.PLAYBOOK["objective"], min_length=1, max_length=2000
    )
    rules: list[Rule] | None = Field(default=None, max_length=20)
    missing_ticket: Literal["ask", "omit"] = "ask"


class Decision(BaseModel):
    choice: Literal[
        "omit_ticket",
        "request_ticket",
        "use_audit_scope",
        "cancel_operation",
        "recheck_policy",
        "drop_handoff",
    ]


class Command(BaseModel):
    command: Literal["pause", "resume", "cancel", "retry", "reassign", "checkpoint"]
    task: str | None = None
    agent: str | None = None


class Lease(BaseModel):
    lease: str


class Result(Lease):
    result: dict


class Failure(Lease):
    error: str


class Worker(BaseModel):
    worker: str = Field(max_length=128)


class Handoff(BaseModel):
    task: str
    sender: str
    recipient: str
    kind: Literal["ADVICE", "ASSIST", "DELEGATE", "REVIEW", "ESCALATE"]
    scope: str = Field(min_length=1, max_length=2000)
    output: str = Field(min_length=1, max_length=2000)
    seconds: int = Field(ge=1, le=86400)
    tools: list[str] = []
    parent: str | None = None


class Meeting(BaseModel):
    participants: list[str]
    agenda: str = Field(min_length=1, max_length=2000)
    context: list[str] = []


class Memory(BaseModel):
    scope: str
    owner: str = ""
    claim: str = Field(max_length=4000)
    source: str = Field(max_length=2000)
    confidence: str
    ttl: int = 86400


class Schedule(BaseModel):
    kind: str = "operation"
    interval: int
    due: float
    run: str | None = None


class Policy(BaseModel):
    workers: int = Field(ge=1, le=25)
    model_slots: int = Field(ge=1, le=25)
    budget_microusd: int = Field(ge=0, le=10**10)
    disabled_tools: list[str]
    stopped: bool


class AgentEdit(BaseModel):
    instructions: str = Field(min_length=1, max_length=4000)
    available: bool
    tools: list[str]


class Appointment(BaseModel):
    position: str
    acting: str
    until: float


def create_app(
    store=None, accounts=None, worker_key=None, providers=None, adapter=None
):
    @asynccontextmanager
    async def lifespan(app):
        nonlocal store, accounts, worker_key, providers
        if store is None:
            store = Store(
                os.environ["DATABASE_URL"],
                os.environ["ARTIFACT_DIR"],
                os.environ["AUDIT_KEY"],
            )
        if accounts is None:
            accounts = json.loads(os.environ.get("OPERATORS", "[]"))
            accounts += [
                {
                    "name": "operator",
                    "project": "operator",
                    "role": "admin",
                    "token": os.environ["OPERATOR_TOKEN"],
                }
            ]
        worker_key = worker_key or os.environ["WORKER_TOKEN"]
        keys = [a["token"] for a in accounts] + [worker_key]
        require(
            all(len(k) >= 24 for k in keys) and len(keys) == len(set(keys)),
            "Use distinct credentials of at least 24 characters",
        )
        providers = (
            providers
            if providers is not None
            else json.loads(os.environ.get("MODEL_ROUTES", "[]"))
        )
        for p in providers:
            require(
                isinstance(p.get("charge"), int)
                and p["charge"] >= 0
                and isinstance(p.get("capabilities"), list)
                and type(p.get("budget_microusd", 0)) is int
                and p.get("budget_microusd", 0) >= 0
                and p.get("model")
                and p.get("name"),
                "Invalid model route",
            )
        store.initialize()
        with store.transaction() as tx:
            org.seed(tx)
        yield

    app = FastAPI(title="Compartment", version="0.2.0", lifespan=lifespan)

    @app.exception_handler(Fault)
    async def fault(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=exc.code)

    @app.middleware("http")
    async def response_headers(request, call_next):
        if int(request.headers.get("content-length", "0")) > 262144:
            return Response(status_code=413)
        res = await call_next(request)
        res.headers["X-Content-Type-Options"] = "nosniff"
        res.headers["Referrer-Policy"] = "no-referrer"
        res.headers["Cache-Control"] = "no-store"
        return res

    def identity(authorization: str = Header(default="")):
        for a in accounts:
            if secrets.compare_digest(authorization, "Bearer " + a["token"]):
                return a
        raise Fault("Operator authentication required", 401)

    def editor(who=Depends(identity)):
        require(who["role"] in ("admin", "operator"), "Operator role required", 403)
        return who

    def admin(who=Depends(editor)):
        require(who["role"] == "admin", "Administrator role required", 403)
        return who

    def internal(authorization: str = Header(default="")):
        require(
            secrets.compare_digest(authorization, "Bearer " + worker_key),
            "Worker authentication required",
            401,
        )

    def check(tx, who, id, kind):
        n = tx.get(id, kind)
        require(gov.may_read(tx, who, n), "Record unavailable", 404)
        return n

    def effect(method, key, params=None):
        if adapter:
            return adapter(method, key, params)
        res = httpx.request(
            method,
            os.environ["TICKET_URL"] + "/tickets/" + key,
            json=params,
            headers={"Authorization": "Bearer " + os.environ["TICKET_TOKEN"]},
            timeout=8,
            trust_env=False,
        )
        if res.status_code == 404 and method == "GET":
            return None
        res.raise_for_status()
        return res.json()

    @app.get("/health")
    def health():
        with store.transaction(write=False) as tx:
            tx.get("policy")
        return {"status": "ready", "version": "0.2.0"}

    @app.get("/api/v1/overview")
    def overview(who=Depends(identity)):
        with store.transaction(write=False) as tx:
            return {
                "identity": {k: who[k] for k in ("name", "role", "project")},
                "departments": tx.all("department"),
                "inbox": chat.previews(tx, who),
                "agents": tx.all("agent"),
                "tools": tx.all("tool"),
                "policy": tx.get("policy")["body"],
                "mode": "live" if providers else "fixture",
                "runs": [
                    r
                    for r in tx.all("run")
                    if gov.may_read(tx, who, r) and "chat_owner" not in r["body"]
                ],
                "schedules": [
                    s for s in tx.all("schedule") if gov.may_read(tx, who, s)
                ],
            }

    @app.get("/api/v1/representatives/{rep}/messages")
    def messages(rep: str, who=Depends(identity)):
        with store.transaction(write=False) as tx:
            return chat.conversation(tx, who, rep)

    @app.post("/api/v1/representatives/{rep}/messages", status_code=202)
    def send_message(rep: str, body: ChatInput, who=Depends(editor)):
        with store.transaction() as tx:
            return {
                "id": chat.post(
                    tx,
                    who,
                    rep,
                    body.message,
                    body.client_id,
                    "live" if providers else "fixture",
                )
            }

    @app.post("/api/v1/runs", status_code=201)
    def start(payload: NewRun, who=Depends(editor)):
        with store.transaction() as tx:
            return {
                "id": engine.start(
                    tx,
                    who["project"],
                    payload.objective,
                    None
                    if payload.rules is None
                    else [r.model_dump() for r in payload.rules],
                    "live" if providers else "fixture",
                    payload.missing_ticket,
                )
            }

    @app.get("/api/v1/runs/{rid}")
    def detail(rid: str, who=Depends(identity)):
        with store.transaction(write=False) as tx:
            data = gov.view(tx, who, rid)
            data["metrics"] = gov.metrics(data["nodes"])
            return data

    @app.post("/api/v1/pushback/{id}/resolve")
    def resolve(id: str, data: Decision, who=Depends(editor)):
        with store.transaction() as tx:
            n = check(tx, who, id, "pushback")
            require(tx.get(n["run"])["body"]["status"] == "active", "Run inactive")
            engine.resolve(tx, id, who["name"], data.choice)
            engine.close_ready(tx, n["run"])
        return {"ok": True}

    @app.post("/api/v1/approvals/{tid}")
    def approval(tid: str, action: dict, who=Depends(editor)):
        with store.transaction() as tx:
            check(tx, who, tid, "task")
            return {"id": engine.approve(tx, tid, who["name"], action)}

    @app.post("/api/v1/runs/{rid}/accept")
    def accept(rid: str, who=Depends(editor)):
        with store.transaction() as tx:
            check(tx, who, rid, "run")
            engine.accept(tx, rid, who["name"])
        return {"ok": True}

    @app.get("/api/v1/runs/{rid}/bundle")
    def bundle(rid: str, who=Depends(identity)):
        with store.transaction(write=False) as tx:
            check(tx, who, rid, "run")
            data = engine.bundle(
                tx, rid, lambda n: gov.may_read(tx, who, n) and n["kind"] != "memory"
            )
        return Response(
            data,
            media_type="application/zip",
            headers={
                "Content-Disposition": "attachment; filename=compartment-evidence.zip"
            },
        )

    @app.get("/api/v1/evidence/{id}")
    def evidence(id: str, who=Depends(identity)):
        with store.transaction(write=False) as tx:
            check(tx, who, id, "evidence")
            return Response(tx.read_artifact(id), media_type="application/json")

    @app.post("/api/v1/runs/{rid}/intervene")
    def intervene(rid: str, body: Command, who=Depends(editor)):
        with store.transaction() as tx:
            check(tx, who, rid, "run")
            runtime.intervene(tx, rid, who["name"], body.command, body.task, body.agent)
        return {"ok": True}

    @app.post("/api/v1/requests")
    def request_work(body: Handoff, who=Depends(editor)):
        with store.transaction() as tx:
            check(tx, who, body.task, "task")
            id = runtime.assign_peer(
                tx,
                body.task,
                body.recipient,
                body.kind,
                body.scope,
                body.output,
                body.seconds,
                body.tools,
                body.parent,
                sender=body.sender,
            )
            tx.audit(who["name"], "operator.request", id, {})
            return {"id": id, "kind": tx.get(id)["kind"]}

    @app.post("/api/v1/requests/{id}/reply")
    def answer(id: str, data: dict, who=Depends(editor)):
        with store.transaction() as tx:
            check(tx, who, id, "request")
            require(
                all(
                    isinstance(data.get(k), str)
                    for k in ("recipient", "status", "answer")
                ),
                "Invalid response",
                422,
            )
            tx.audit(who["name"], "operator.facilitated_reply", id, {})
            return coordination.reply(
                tx, id, data["recipient"], data["status"], data["answer"]
            )

    @app.post("/api/v1/runs/{rid}/meetings")
    def meet(rid: str, body: Meeting, who=Depends(editor)):
        with store.transaction() as tx:
            check(tx, who, rid, "run")
            return {
                "id": gov.extra_meeting(
                    tx, rid, body.participants, body.agenda, body.context, "ad hoc"
                )
            }

    @app.post("/api/v1/runs/{rid}/memory")
    def remember(rid: str, body: Memory, who=Depends(editor)):
        with store.transaction() as tx:
            return {"id": gov.memory(tx, who, rid, **body.model_dump())}

    @app.get("/api/v1/runs/{rid}/search")
    def search(rid: str, q: str = "", who=Depends(identity)):
        with store.transaction(write=False) as tx:
            return [
                n
                for n in gov.view(tx, who, rid)["nodes"]
                if n["kind"] in ("memory", "decision", "meeting", "pushback")
                and q.casefold() in json.dumps(n["body"]).casefold()
            ]

    @app.delete("/api/v1/memory/{id}")
    def forget(id: str, who=Depends(editor)):
        with store.transaction() as tx:
            check(tx, who, id, "memory")
            tx.sql("DELETE FROM edges WHERE src=? OR dst=?", (id, id))
            tx.sql("DELETE FROM nodes WHERE id=?", (id,))
            tx.audit(who["name"], "delete.memory", id, {})
        return {"ok": True}

    @app.post("/api/v1/schedules")
    def schedule(body: Schedule, who=Depends(editor)):
        with store.transaction() as tx:
            return {"id": gov.schedule(tx, who, **body.model_dump())}

    @app.post("/api/v1/triggers/{key}")
    def trigger(key: str, who=Depends(editor)):
        with store.transaction() as tx:
            return {
                "id": gov.trigger(
                    tx,
                    who["project"],
                    "webhook/" + key,
                    "live" if providers else "fixture",
                )
            }

    @app.put("/api/v1/policy")
    def policy(body: Policy, who=Depends(admin)):
        with store.transaction() as tx:
            if body.stopped:
                for r in tx.all("run"):
                    if r["body"]["status"] == "active":
                        runtime.intervene(tx, r["id"], who["name"], "pause")
            return tx.change("policy", who["name"], **body.model_dump())

    @app.put("/api/v1/agents/{id}")
    def config(id: str, body: AgentEdit, who=Depends(admin)):
        with store.transaction() as tx:
            n = tx.get(id, "agent")
            require(
                set(body.tools) <= set(org.TOOLS.values()), "Unregistered tool", 422
            )
            return tx.change(
                id, who["name"], version=n["body"]["version"] + 1, **body.model_dump()
            )

    @app.post("/api/v1/appointments")
    def appoint(body: Appointment, who=Depends(admin)):
        with store.transaction() as tx:
            return {
                "id": org.appoint(
                    tx, body.position, body.acting, body.until, time.time(), who["name"]
                )
            }

    @app.post("/api/v1/pushback/{id}/adjudicate")
    def adjudicate(id: str, data: dict, who=Depends(editor)):
        with store.transaction() as tx:
            n = check(tx, who, id, "pushback")
            require(
                data.get("consent_local_atlas") is True
                and data.get("classification")
                in ("correct detection", "false positive", "missed conflict"),
                "Explicit local consent and an adjudication required",
                422,
            )
            require(
                all(
                    isinstance(data.get(k), str) and 0 < len(data[k]) <= 2000
                    for k in ("root_cause", "regression", "resolution")
                ),
                "Describe the observed cause, resolution and regression",
                422,
            )
            return {
                "id": tx.add(
                    "atlas_case",
                    {
                        "category": n["body"]["category"],
                        "classification": data["classification"],
                        "root_cause": data["root_cause"],
                        "regression": data["regression"],
                        "resolution": data["resolution"],
                        "source": "operator-adjudicated",
                        "consent": "local only",
                    },
                    run=n["run"],
                    parent=id,
                    origin=who["name"],
                    reason="consented failure or resolution",
                )
            }

    @app.patch("/api/v1/schedules/{id}")
    def toggle_schedule(id: str, data: dict, who=Depends(editor)):
        with store.transaction() as tx:
            check(tx, who, id, "schedule")
            require(isinstance(data.get("enabled"), bool), "Specify enabled", 422)
            return tx.change(id, who["name"], enabled=data["enabled"])

    @app.put("/api/v1/departments/{id}")
    def configure_department(id: str, data: dict, who=Depends(admin)):
        with store.transaction() as tx:
            tx.get(id, "department")
            require(
                all(
                    isinstance(data.get(k), str) and 0 < len(data[k]) <= 2000
                    for k in ("name", "mission", "escalation")
                )
                and isinstance(data.get("quota"), int)
                and 1 <= data["quota"] <= 25,
                "Invalid department configuration",
                422,
            )
            return tx.change(
                id,
                who["name"],
                **{k: data[k] for k in ("name", "mission", "escalation", "quota")},
            )

    @app.get("/api/v1/audit/integrity")
    def integrity(who=Depends(admin)):
        with store.transaction(write=False) as tx:
            return {"head": tx.verify_journal()}

    @app.post("/internal/tool-access")
    def tool_access(data: dict):
        require(
            all(isinstance(data.get(k), str) for k in ("task", "lease", "tool")),
            "Missing scoped capability",
            403,
        )
        with store.transaction() as tx:
            t = runtime.leased(tx, data["task"], data["lease"])
            b = t["body"]
            tool = org.TOOLS[b["step"]]
            spec = tx.get("tool/" + tool)["body"]
            require(
                spec["adapter"] == data["tool"]
                and tool in ("contract.read", "contract.verify"),
                "Capability does not authorize this tool",
                403,
            )
            recent = [
                n
                for n in tx.all("tool_access")
                if n["origin"] == b["owner"]
                and n["body"]["tool"] == tool
                and n["created"] > time.time() - 60
            ]
            require(
                len(recent) < spec["calls_per_minute"], "Tool rate limit reached", 429
            )
            tx.add(
                "tool_access",
                {
                    "task": t["id"],
                    "tool": tool,
                    "version": spec["version"],
                    "adapter": spec["adapter"],
                    "lease_expiry": b["lease_until"],
                },
                run=t["run"],
                parent=t["id"],
                origin=b["owner"],
                reason="authorized tool invocation",
            )
            return {"granted": True}

    @app.post("/internal/claim", dependencies=[Depends(internal)])
    def claim(body: Worker):
        with store.transaction() as tx:
            gov.tick(tx, "live" if providers else "fixture")
            return runtime.claim(tx, body.worker, providers)

    @app.post("/internal/tasks/{tid}/requests", dependencies=[Depends(internal)])
    def agent_request(tid: str, data: dict):
        with store.transaction() as tx:
            t = runtime.leased(tx, tid, data.get("lease"))
            require(
                t["body"]["step"] in ("draft", "peer"),
                "This assignment cannot request additional work",
                403,
            )
            require(
                data.get("kind") in coordination.KINDS
                and isinstance(data.get("seconds"), int)
                and all(
                    isinstance(data.get(k), str) and 0 < len(data[k]) <= 2000
                    for k in ("scope", "output", "recipient")
                ),
                "Invalid bounded request",
                422,
            )
            rid = runtime.assign_peer(
                tx,
                tid,
                data["recipient"],
                data["kind"],
                data["scope"],
                data["output"],
                data["seconds"],
                wait=data.get("wait") is True,
            )
            return {"id": rid, "kind": tx.get(rid)["kind"]}

    @app.post("/internal/tasks/{tid}/finish", dependencies=[Depends(internal)])
    def finish(tid: str, body: Result):
        with store.transaction() as tx:
            runtime.finish(tx, tid, body.lease, body.result)
        return {"ok": True}

    @app.post("/internal/tasks/{tid}/fail", dependencies=[Depends(internal)])
    def fail(tid: str, body: Failure):
        with store.transaction() as tx:
            runtime.failure(tx, tid, body.lease, body.error)
        return {"ok": True}

    @app.post("/internal/tasks/{tid}/dispatch", dependencies=[Depends(internal)])
    def dispatch(tid: str, body: Lease):
        with store.transaction() as tx:
            t = runtime.leased(tx, tid, body.lease)
            require(
                t["body"]["step"] == "ticket" and engine.authorized(tx, t, time.time()),
                "Dispatch denied",
                403,
            )
            n = tx.get(t["body"]["intent"], "intent")
            if n["body"]["status"] == "confirmed":
                return n["body"]["receipt"]
            require(n["body"]["status"] == "prepared", "Review intent before retry")
            # The transaction gate fences policy edits and cancellation during the bounded call.
            receipt = effect("PUT", tid, n["body"]["action"]["parameters"])
            tx.change(n["id"], "adapter", status="confirmed", receipt=receipt)
            return receipt

    @app.post("/api/v1/tasks/{tid}/reconcile")
    def reconcile(tid: str, who=Depends(editor)):
        with store.transaction() as tx:
            t = check(tx, who, tid, "task")
            b = t["body"]
            require(b["state"] == "blocked" and b.get("intent"), "No uncertain intent")
            receipt = effect("GET", tid)
            if receipt:
                tx.change(b["intent"], who["name"], status="confirmed", receipt=receipt)
                aid = tx.artifact(
                    t["run"], tid, who["name"], "reconciled receipt", receipt
                )
                tx.link(b["intent"], aid, "reconciled against external receipt")
                tx.change(tid, who["name"], state="completed", artifact=aid)
            else:
                tx.change(
                    b["intent"], who["name"], status="absent in idempotent sandbox"
                )
                tx.change(
                    tid,
                    who["name"],
                    state="pending approval",
                    intent=None,
                    approval=None,
                )
            for case in tx.all("pushback", t["run"]):
                if (
                    case["body"]["category"] == "unsafe/irreversible action"
                    and case["body"]["status"] == "open"
                    and tid in case["body"]["affected"]
                ):
                    tx.change(
                        case["id"],
                        who["name"],
                        status="resolved",
                        resolved_at=time.time(),
                        resolution="Reconciled against the sandbox",
                    )
            if tx.get(t["run"])["body"]["status"] == "active":
                engine.close_ready(tx, t["run"])
            return {"found": bool(receipt)}

    resources = {
        "atlas": "atlas_case",
        "tools": "tool",
        "departments": "department",
        "agents": "agent",
        "assignments": "assignment",
        "tasks": "task",
        "requests": "request",
        "meetings": "meeting",
        "pushback": "pushback",
        "approvals": "approval",
        "schedules": "schedule",
        "runs": "run",
        "evidence": "evidence",
    }

    @app.get("/api/v1/{resource}")
    def listing(resource: str, who=Depends(identity)):
        require(resource in resources, "Unknown resource", 404)
        with store.transaction(write=False) as tx:
            result = [
                n for n in tx.all(resources[resource]) if gov.may_read(tx, who, n)
            ]
            for n in result:
                n["body"].pop("lease", None)
            return result

    static = Path(
        os.environ.get("WEB_DIR", Path(__file__).resolve().parents[1] / "web/dist")
    )
    if static.is_dir():
        app.mount("/", StaticFiles(directory=static, html=True))
    return app


app = create_app()
