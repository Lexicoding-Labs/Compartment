import json
import time

from . import chat
from . import coordination as coord
from .contracts import validate
from .engine import (
    PLAYBOOK,
    allocate,
    artifact_data,
    authorized,
    block_case,
    by_step,
    close_ready,
    target,
    task,
)
from .org import TOOLS, capable, holder
from .probe import compare
from .store import require, uid


def assign_peer(
    tx,
    tid,
    recipient,
    kind,
    scope,
    output,
    seconds,
    tools=(),
    parent=None,
    wait=False,
    sender=None,
):
    t = tx.get(tid, "task")
    b = t["body"]
    require(tx.get(t["run"])["body"]["status"] == "active", "Run inactive")
    sender = sender or b["owner"]
    if b["step"] == "peer":
        parent = b["reply_to"]
        tid = tx.get(parent)["body"]["task"]
    rid = coord.handoff(
        tx, tid, sender, recipient, kind, scope, output, seconds, tools, parent
    )
    if tx.get(rid)["kind"] == "pushback":
        return rid
    child = tx.add(
        "task",
        {
            "step": "peer",
            "owner": recipient,
            "priority": b["priority"] + 1,
            "dependencies": [],
            "state": "queued",
            "deadline": time.time() + seconds,
            "input": scope,
            "expected": output,
            "acceptance": output,
            "attempt": 0,
            "agent_version": tx.get(recipient)["body"]["version"],
            "reply_to": rid,
            "return_to": t["id"] if wait else None,
        },
        run=t["run"],
        parent=rid,
        reason="recipient owes response",
    )
    tx.add(
        "assignment",
        {"agent": recipient, "task": child, "scope": scope},
        run=t["run"],
        parent=child,
        origin=sender,
    )
    if wait:
        tx.change(t["id"], sender, state="waiting", lease="", waiting_for=rid)
    return rid


def sweep(tx):
    now = time.time()
    coord.expire(tx)
    for t in tx.all("task"):
        b = t["body"]
        if b["state"] == "running" and b["lease_until"] <= now:
            uncertain = b["step"] == "ticket" and b.get("intent")
            if uncertain:
                block_case(
                    tx,
                    t,
                    "unsafe/irreversible action",
                    "Dispatch outcome is unknown. Inspect the task and reconcile its ticket intent.",
                    [],
                    "operator reconciliation",
                )
            tx.change(
                t["id"],
                "recovery",
                state="blocked" if uncertain else "queued",
                lease="",
                recovered_leases=b.get("recovered_leases", 0) + 1,
                error="Reconcile outstanding intent"
                if uncertain
                else "Lease expired; safe retry",
            )
            if b.get("reservation"):
                tx.change(b["reservation"], "recovery", status="unknown")
        elif b["state"] == "queued" and b["deadline"] <= now:
            tx.change(t["id"], "clock", state="failed", error="Task deadline exceeded")
        if b["state"] == "waiting" and b.get("waiting_for"):
            req = tx.get(b["waiting_for"])["body"]
            if req["status"] in ("timed_out", "declined"):
                tx.change(
                    t["id"],
                    "clock",
                    state="blocked",
                    error="Requested peer response unavailable",
                )
    for n in tx.all("memory"):
        if n["body"]["expires"] <= now:
            tx.sql("DELETE FROM edges WHERE src=? OR dst=?", (n["id"], n["id"]))
            tx.sql("DELETE FROM nodes WHERE id=?", (n["id"],))
            tx.audit("clock", "expire.memory", n["id"], {})


def claim(tx, worker, providers=()):
    sweep(tx)
    p = tx.get("policy")["body"]
    tasks = tx.all("task")
    active = [t for t in tasks if t["body"]["state"] == "running"]
    if p["stopped"] or len(active) >= p["workers"]:
        return None
    for t in sorted(tasks, key=lambda n: (-n["body"]["priority"], n["created"])):
        b = t["body"]
        if (
            b["state"] != "queued"
            or b.get("after", 0) > time.time()
            or any(tx.get(d)["body"]["state"] != "completed" for d in b["dependencies"])
        ):
            continue
        run = tx.get(t["run"])["body"]
        if run["status"] != "active":
            continue
        step = b["step"]
        meeting = None
        if step == "meeting":
            meeting = tx.get(b["meeting"])["body"]
            if time.time() >= meeting["ends_by"]:
                coord.close_meeting(
                    tx,
                    b["meeting"],
                    [
                        n["id"]
                        for n in tx.all("pushback", t["run"])
                        if n["body"]["status"] == "open"
                    ],
                    [],
                )
                tx.change(t["id"], "clock", state="failed", error="Meeting timed out")
                continue
            owner = meeting["participants"][len(meeting["turns"])]
        else:
            owner = holder(tx, b["owner"], time.time())
        if not capable(tx, owner, TOOLS[step]):
            block_case(
                tx,
                t,
                "policy violation",
                "An available identity with the required tool permission is needed. Recheck the current policy?",
                ["recheck_policy", "cancel_operation"],
            )
            tx.change(
                t["id"],
                "policy",
                state="blocked",
                error="Agent unavailable or tool permission denied",
            )
            continue
        dept = tx.get(owner)["body"]["department"]
        if (
            sum(
                tx.get(x["body"]["owner"])["body"]["department"] == dept for x in active
            )
            >= tx.get(dept)["body"]["quota"]
        ):
            continue
        if step == "ticket" and not authorized(tx, t, time.time()):
            tx.change(
                t["id"],
                "policy",
                state="pending approval",
                error="Fresh exact-action approval required",
            )
            continue
        inputs = chat.inputs(tx, run, owner) if step == "chat" else {}
        if b.get("peer_evidence"):
            inputs["advice"] = json.loads(tx.read_artifact(b["peer_evidence"]))
        if step == "peer":
            request = tx.get(b["reply_to"])["body"]
            if request["status"] == "sent":
                coord.reply(
                    tx, b["reply_to"], owner, "received", "Bounded request received"
                )
            elif request["status"] != "received":
                tx.change(
                    t["id"],
                    "control",
                    state="failed",
                    error="Request expired or closed",
                )
                continue
            inputs.update(
                scope=request["scope"],
                output=request["output"],
                kind=request["type"],
                mode=run["model_mode"],
            )
        if step in ("draft", "review", "correct", "verify"):
            inputs["primary"] = artifact_data(tx, by_step(tx, t["run"], "inspect"))
        if step in ("review", "verify"):
            src = by_step(tx, t["run"], "draft" if step == "review" else "correct")
            require(src["body"]["owner"] != owner, "Reviewer must be independent")
            inputs["report"] = artifact_data(tx, src)
        if step == "correct":
            inputs["review"] = artifact_data(tx, by_step(tx, t["run"], "review"))
        route = None
        reserve = None
        if meeting:
            inputs.update(
                agenda=meeting["agenda"],
                previous_speakers=[
                    {"actor": v["actor"], "statement": v["statement"][:500]}
                    for v in meeting["turns"][-3:]
                ],
                role=tx.get(owner)["body"]["role"],
                instructions=tx.get(owner)["body"]["instructions"],
                requirements=[
                    tx.get(i)["body"].get("text", "Approved context reference")
                    for i in meeting["context"]
                ],
                round=len(meeting["turns"]),
                mode=run["model_mode"],
            )
        if meeting or step in ("peer", "chat"):
            if run["model_mode"] == "live":
                routes = [
                    r
                    for r in providers
                    if ("meeting" if meeting else "advice") in r["capabilities"]
                    and (not r.get("agents") or owner in r["agents"])
                ]
                attempt = b.get("route_index", 0)
                if attempt >= len(routes):
                    tx.change(
                        t["id"],
                        "router",
                        state="failed",
                        error="No approved provider route available",
                    )
                    continue
                route = routes[attempt]
                reservations = tx.all("reservation")
                if (
                    sum(r["body"]["status"] == "active" for r in reservations)
                    >= p["model_slots"]
                ):
                    continue
                held = sum(r["body"]["amount"] for r in reservations)
                per_run = sum(
                    r["body"]["amount"] for r in reservations if r["run"] == t["run"]
                )
                provider_total = sum(
                    r["body"]["amount"]
                    for r in reservations
                    if r["body"]["provider"] == route["name"]
                )
                if (
                    provider_total + route["charge"]
                    > route.get("budget_microusd", p["budget_microusd"])
                    or held + route["charge"] > p["budget_microusd"]
                    or per_run + route["charge"] > PLAYBOOK["cost_envelope_microusd"]
                ):
                    block_case(
                        tx,
                        t,
                        "resource conflict",
                        "The next model reservation exceeds its ceiling. Recheck the configured budget?",
                        ["recheck_policy", "cancel_operation"],
                    )
                    tx.change(
                        t["id"],
                        "budget",
                        state="blocked",
                        error="Model spending ceiling reached",
                    )
                    continue
                reserve = tx.add(
                    "reservation",
                    {
                        "amount": route["charge"],
                        "status": "active",
                        "provider": route["name"],
                        "model": route["model"],
                    },
                    run=t["run"],
                    parent=t["id"],
                )
        if meeting:
            events = tx.all("meeting_event", t["run"])
            if not any(
                e["body"].get("meeting") == b["meeting"]
                and e["origin"] == owner
                and e["body"]["type"] == "MEETING_JOIN"
                for e in events
            ):
                for event in ("MEETING_ACCEPT", "MEETING_JOIN"):
                    tx.add(
                        "meeting_event",
                        {"type": event, "meeting": b["meeting"], "participant": owner},
                        run=t["run"],
                        origin=owner,
                        parent=b["meeting"],
                    )
        lease = uid()
        intent = None
        if step == "ticket":
            intent = tx.add(
                "intent",
                {"action": target(tx, t["id"]), "key": t["id"], "status": "prepared"},
                run=t["run"],
                parent=b["approval"],
                reason="authorized dispatch",
            )
        if b.get("request"):
            req = tx.get(b["request"])["body"]
            if req["status"] == "sent":
                coord.reply(
                    tx,
                    b["request"],
                    req["recipient"],
                    "received",
                    "Accepted bounded assignment",
                )
            elif req["status"] not in ("received", "answered"):
                tx.change(
                    t["id"],
                    "control",
                    state="blocked",
                    error="Handoff expired or declined",
                )
                continue
        tx.change(
            t["id"],
            worker,
            state="running",
            owner=owner,
            lease=lease,
            lease_until=time.time() + 180,
            worker=worker,
            attempt=b["attempt"] + 1,
            intent=intent,
            reservation=reserve,
            agent_version=tx.get(owner)["body"]["version"],
        )
        return dict(
            id=t["id"],
            run=t["run"],
            step=step,
            agent=owner,
            lease=lease,
            inputs=inputs,
            route=route,
        )
    return None


def leased(tx, tid, lease):
    t = tx.get(tid, "task")
    b = t["body"]
    require(
        b["state"] == "running"
        and b["lease"] == lease
        and time.time() < b["lease_until"],
        "Lease expired or superseded",
    )
    require(
        tx.get(t["run"])["body"]["status"] == "active"
        and not tx.get("policy")["body"]["stopped"],
        "Operation suspended",
    )
    require(
        capable(tx, b["owner"], TOOLS[b["step"]]),
        "Current policy denies execution",
        403,
    )
    return t


def finish(tx, tid, lease, result):
    t = leased(tx, tid, lease)
    b = t["body"]
    run, step, actor = t["run"], b["step"], b["owner"]
    require(len(json.dumps(result)) <= 131072, "Result exceeds size limit", 422)
    if step in ("review", "verify"):
        source = artifact_data(tx, by_step(tx, run, "inspect"))
        report = artifact_data(
            tx, by_step(tx, run, "draft" if step == "review" else "correct")
        )
        expected = compare(source["contract"], source["sample"])
        independently_matches = (
            result.get("source_matches") is True and result.get("findings") == expected
        )
        require(independently_matches, "Reviewer must reproduce the primary evidence")
        verdict = (
            report.get("compatible") == (not expected)
            and report.get("findings") == expected
        )
        require(
            result.get("pass") is verdict,
            "Reviewer verdict contradicts the reproduced check",
        )
    if step == "ticket":
        require(
            b.get("intent") and tx.get(b["intent"])["body"]["status"] == "confirmed",
            "Dispatch receipt required",
        )
        result = tx.get(b["intent"])["body"]["receipt"]
    validate(TOOLS[step], result)
    if step == "chat":
        tx.change(
            run,
            actor,
            reply=result["statement"],
            model=result["model"],
            speaker=actor,
            status="completed",
        )
        tx.change(tid, actor, state="completed", lease="")
        if b.get("reservation"):
            tx.change(b["reservation"], "router", status="consumed")
        return
    artifact = tx.artifact(run, tid, actor, step + " result", result)
    version = tx.add(
        "execution",
        {
            "agent": actor,
            "agent_version": b["agent_version"],
            "tool": TOOLS[step],
            "tool_version": "1",
            "model": result.get("model"),
            "attempt": b["attempt"],
        },
        run=run,
        parent=tid,
        reason="executed by",
    )
    tx.link(version, artifact, "produced")
    for acl in tx.all("tool_access", run):
        if acl["body"].get("task") == tid:
            tx.link(acl["id"], version, "permitted bounded execution")
    if b.get("reservation"):
        tx.link(b["reservation"], version, "funded model turn")
    if step == "ticket":
        tx.link(b["intent"], artifact, "returned receipt")
    if step in ("review", "verify"):
        source = by_step(tx, run, "inspect")["body"]["artifact"]
        tx.link(source, artifact, "independently checked primary evidence")
        claim = tx.add(
            "claim",
            {
                "statement": "Inventory v2 response satisfies its declared JSON contract",
                "supported": not bool(result["findings"]),
                "source": source,
                "method": result["method"],
                "confidence": "verified",
                "errors": result["findings"],
            },
            run=run,
            parent=artifact,
            origin=actor,
            reason="verified claim",
        )
        tx.link(source, claim, "primary source")
    if step == "correct":
        tx.link(
            by_step(tx, run, "draft")["body"]["artifact"], artifact, "revised report"
        )

    if step == "peer":
        require(
            isinstance(result.get("statement"), str) and result["statement"].strip(),
            "Peer response required",
        )
        coord.reply(tx, b["reply_to"], actor, "answered", artifact)
        if b.get("reservation"):
            tx.change(b["reservation"], "router", status="consumed")
        if b.get("return_to"):
            parent = tx.get(b["return_to"])
            if (
                parent["body"]["state"] == "waiting"
                and parent["body"].get("waiting_for") == b["reply_to"]
            ):
                tx.change(
                    parent["id"],
                    "control",
                    state="queued",
                    waiting_for=None,
                    peer_evidence=artifact,
                )
                tx.link(artifact, parent["id"], "returns scoped advice")
    if step == "plan":
        allocate(tx, run, tid)
    if step == "meeting":
        mid = b["meeting"]
        m = tx.get(mid)["body"]
        require(
            result.get("position") in ("proposal", "dissent", "commitment")
            and isinstance(result.get("statement"), str),
            "Invalid meeting response",
            422,
        )
        turn = {k: result.get(k) for k in ("position", "statement", "model")}
        indices = result.get("conflict_indices", [])
        if (
            isinstance(indices, list)
            and len(indices) == 2
            and all(type(i) is int and 0 <= i < len(m["context"]) for i in indices)
            and indices[0] != indices[1]
        ):
            refs = [tx.get(m["context"][i]) for i in indices]
            ticket = by_step(tx, run, "ticket")
            known = any(
                set(n["body"].get("requirements", [])) == {n["id"] for n in refs}
                for n in tx.all("pushback", run)
            )
            if (
                not known
                and all(n["kind"] == "requirement" for n in refs)
                and ticket["body"]["state"] in ("pending approval", "queued", "blocked")
            ):
                cid = block_case(
                    tx,
                    ticket,
                    "semantic disagreement",
                    "A meeting participant identified conflicting ticket instructions. Request a reviewed ticket or omit it?",
                    ["request_ticket", "omit_ticket"],
                )
                tx.change(
                    cid,
                    actor,
                    quotes=[n["body"]["text"] for n in refs],
                    requirements=[n["id"] for n in refs],
                    model_proposal=result["statement"],
                )
                tx.link(artifact, cid, "proposed semantic challenge")
                tx.change(ticket["id"], "control", state="blocked", approval=None)
        turn.update(actor=actor, evidence=artifact)
        turns = [*m["turns"], turn]
        tx.change(mid, actor, turns=turns)
        if b.get("reservation"):
            tx.change(b["reservation"], "router", status="consumed")
        if len(turns) < m["turn_limit"]:
            tx.change(
                tid,
                actor,
                state="queued",
                lease="",
                reservation=None,
                route_index=0,
                failures=0,
            )
            return
        all_tasks = tx.all("task", run)
        correction = next(
            (n for n in all_tasks if n["body"]["step"] == "correct"), None
        )
        verification = next(
            (n for n in all_tasks if n["body"]["step"] == "verify"), None
        )
        if verification:
            follow = verification["id"]
        else:
            dependency = correction or by_step(tx, run, "review")
            follow = task(
                tx,
                run,
                "verify",
                mid,
                [dependency["id"]],
                state="queued" if correction else "waiting",
            )
        verify = tx.get(follow)["body"]
        coord.close_meeting(
            tx,
            mid,
            [n["id"] for n in tx.all("pushback", run) if n["body"]["status"] == "open"],
            [
                {
                    "task": follow,
                    "owner": verify["owner"],
                    "deadline": verify["deadline"],
                    "verify": verify["acceptance"],
                    "dependencies": verify["dependencies"],
                }
            ],
        )
    if step == "review":
        require(isinstance(result.get("pass"), bool), "Invalid QA verdict", 422)
        if not result["pass"]:
            case = block_case(
                tx,
                t,
                "evidence disagreement",
                "The report conflicts with the independent reproduction. Correct and verify the finding.",
                [],
                "independent reviewer",
            )
            tx.link(artifact, case, "documents disagreement")
        correct = task(tx, run, "correct", tid, [tid])
        for v in tx.all("task", run):
            if v["body"]["step"] == "verify":
                tx.change(v["id"], "control", dependencies=[correct], state="queued")
                tx.link(correct, v["id"], "requires independent reproduction")
        tx.link(artifact, correct, "review requires revision")
    if step == "verify" and not result.get("pass"):
        tx.change(
            tid,
            actor,
            state="failed",
            artifact=artifact,
            lease="",
            error="Independent verification failed",
        )
        return
    if step == "verify" and result.get("pass"):
        for case in tx.all("pushback", run):
            if (
                case["body"]["category"] == "evidence disagreement"
                and case["body"]["status"] == "open"
            ):
                tx.change(
                    case["id"],
                    actor,
                    status="resolved",
                    resolution="Independent reproduction passed",
                    resolved_at=time.time(),
                )
                tx.link(artifact, case["id"], "resolved by independent verification")
    for d in b["dependencies"]:
        source = tx.get(d)["body"].get("artifact")
        if source:
            tx.link(source, artifact, "used as input")
    if b.get("request"):
        req = tx.get(b["request"])["body"]
        if req["status"] == "received":
            coord.reply(tx, b["request"], req["recipient"], "answered", artifact)
    tx.change(tid, actor, state="completed", artifact=artifact, lease="")
    close_ready(tx, run)


def failure(tx, tid, lease, error):
    t = leased(tx, tid, lease)
    b = t["body"]
    if b.get("reservation"):
        tx.change(b["reservation"], "router", status="unknown")
    failures = b.get("failures", 0) + 1
    retry = failures < 3 and b["step"] != "ticket"
    tx.change(
        tid,
        "worker",
        state="queued" if retry else ("blocked" if b.get("intent") else "failed"),
        lease="",
        failures=failures,
        after=time.time() + min(30, 2**failures),
        error=error[:256],
        route_index=b.get("route_index", 0) + (1 if b.get("reservation") else 0),
    )


def intervene(tx, run, actor, command, tid=None, agent=None):
    r = tx.get(run, "run")["body"]
    require(r["status"] not in ("accepted", "cancelled"), "Operation already closed")
    if command == "checkpoint":
        return tx.add(
            "checkpoint",
            {"states": {n["id"]: n["body"]["state"] for n in tx.all("task", run)}},
            run=run,
            parent=run,
            origin=actor,
        )
    if command in ("pause", "cancel", "resume"):
        require(
            command != "resume" or not tx.get("policy")["body"]["stopped"],
            "Clear emergency stop before resuming",
        )
        require(
            command != "resume" or r["status"] == "paused",
            "Only paused runs can resume",
        )
        for t in tx.all("task", run):
            b = t["body"]
            if (
                command in ("pause", "cancel")
                and b["state"] == "running"
                and b.get("reservation")
            ):
                tx.change(b["reservation"], actor, status="unknown")
            if (
                command in ("pause", "cancel")
                and b["state"] == "running"
                and b.get("intent")
            ):
                tx.change(
                    t["id"],
                    actor,
                    state="blocked",
                    lease="",
                    error="Reconciliation required",
                )
            elif command == "cancel" and b["state"] != "completed":
                tx.change(t["id"], actor, state="cancelled", lease="")
            elif command == "pause" and b["state"] == "running":
                tx.change(t["id"], actor, state="queued", lease="")
        tx.change(
            run,
            actor,
            status={"resume": "active", "pause": "paused", "cancel": "cancelled"}[
                command
            ],
        )
        if command == "resume":
            close_ready(tx, run)
        return
    t = tx.get(tid, "task")
    b = t["body"]
    require(
        t["run"] == run
        and b["state"] in ("failed", "blocked", "queued", "waiting")
        and not b.get("intent"),
        "Task requires reconciliation or is unavailable",
    )
    require(
        not any(
            n["body"]["status"] == "open" and tid in n["body"]["affected"]
            for n in tx.all("pushback", run)
        ),
        "Resolve blocking Pushback first",
    )
    require(command in ("retry", "reassign"), "Unknown intervention", 422)
    if command == "reassign":
        require(
            capable(tx, agent, TOOLS[b["step"]])
            and tx.get(agent)["body"]["department"]
            == tx.get(b["owner"])["body"]["department"],
            "Ineligible replacement",
            403,
        )
        tx.change(tid, actor, owner=agent)
    tx.change(tid, actor, state="queued", after=0, route_index=0, failures=0)
