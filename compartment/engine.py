"""Control-plane state machine for the versioned audit playbook."""

import io
import json
import time
import zipfile
from pathlib import Path

from . import coordination as coord
from .org import OWNERS, capable
from .store import canonical, digest, require, uid

PLAYBOOK = json.loads(
    (
        Path(__file__).resolve().parents[1] / "playbooks/integration-audit.json"
    ).read_text()
)
STATES = {
    "queued",
    "running",
    "waiting",
    "blocked",
    "pending approval",
    "completed",
    "failed",
    "cancelled",
}
CHECKS = {
    "plan": "Record scoped assignments",
    "inspect": "Capture the versioned contract and response",
    "meeting": "Record all attributed positions and assigned verification",
    "draft": "Produce a compatibility verdict",
    "review": "Reproduce the contract check from source",
    "correct": "Correct the original report against the reproduced error",
    "verify": "Independently reproduce the corrected verdict",
    "ticket": "Record the authorized sandbox receipt or operator waiver",
}


def task(tx, run, step, parent, deps=(), state="queued", **extra):
    owner = OWNERS[step]
    settings = tx.get(owner)["body"]
    body = dict(
        step=step,
        owner=owner,
        priority=50,
        dependencies=list(deps),
        state=state,
        deadline=time.time() + 86400,
        input=PLAYBOOK["scope"],
        expected=CHECKS[step],
        acceptance=CHECKS[step],
        attempt=0,
        agent_version=settings["version"],
        **extra,
    )
    tid = tx.add("task", body, run=run, parent=parent, reason="requires work")
    assignment = tx.add(
        "assignment",
        {"agent": owner, "task": tid, "scope": body["input"]},
        run=run,
        parent=tid,
        origin="planning-director",
        reason="allocated to identity",
    )
    tx.link(owner, assignment, "owns")
    for dep in deps:
        tx.link(dep, tid, "must finish before")
    return tid


def start(tx, actor, objective=None, rules=None, mode="fixture", missing_ticket="ask"):
    require(not tx.get("policy")["body"]["stopped"], "Emergency stop active")
    rid = uid()
    tx.add(
        "run",
        {
            "objective": objective or PLAYBOOK["objective"],
            "operator": actor,
            "status": "active",
            "playbook": PLAYBOOK["version"],
            "playbook_digest": digest(PLAYBOOK),
            "model_mode": mode,
            "missing_ticket": missing_ticket,
        },
        id=rid,
        run=rid,
        origin=actor,
    )
    for rule in PLAYBOOK["rules"] if rules is None else rules:
        require(
            rule["effect"] in ("open", "hold")
            and rule["when"] in ("finding", "review")
            and rule["text"].strip(),
            "Invalid structured requirement",
            422,
        )
        tx.add("requirement", rule, run=rid, parent=rid, origin=actor, reason="defines")
    plan = task(tx, rid, "plan", rid)
    # With a single executable playbook, an unmatched objective needs a human scope decision.
    if objective and objective.strip().casefold() != PLAYBOOK["objective"].casefold():
        tx.change(plan, "scope", state="blocked")
        tx.add(
            "pushback",
            {
                "category": "clarification needed",
                "severity": "high",
                "status": "open",
                "affected": [plan],
                "quotes": [objective, PLAYBOOK["scope"]],
                "question": "Does the supplied Inventory v2 audit scope satisfy this objective?",
                "alternatives": ["use_audit_scope", "cancel_operation"],
                "authority": "operator",
            },
            run=rid,
            parent=plan,
            reason="requires explicit scope match",
        )
    return rid


def by_step(tx, run, step):
    return next(t for t in tx.all("task", run) if t["body"]["step"] == step)


def conflicting_pair(rules):
    for i, a in enumerate(rules):
        for j in range(i + 1, len(rules)):
            b = rules[j]
            if a["when"] == b["when"] and a["effect"] != b["effect"]:
                return i, j
    return None


def allocate(tx, run, plan):
    reqs = tx.all("requirement", run)
    pair = conflicting_pair([r["body"] for r in reqs])
    conflicting = [reqs[i] for i in pair] if pair else []
    inspect = task(tx, run, "inspect", plan)
    draft = task(tx, run, "draft", plan, [inspect])
    review = task(tx, run, "review", plan, [draft])
    ticket = task(
        tx,
        run,
        "ticket",
        plan,
        [review],
        "blocked" if conflicting else "pending approval",
    )
    for src, dst, kind in [
        (plan, inspect, "DELEGATE"),
        (inspect, draft, "ASSIST"),
        (draft, review, "REVIEW"),
    ]:
        sender = tx.get(src)["body"]["owner"]
        recipient = tx.get(dst)["body"]["owner"]
        req = coord.handoff(
            tx,
            src,
            sender,
            recipient,
            kind,
            CHECKS[tx.get(dst)["body"]["step"]],
            "Return primary evidence or an attributed result",
            3600,
        )
        tx.link(req, dst, "delivers assignment")
        tx.change(dst, "control", request=req)
    if conflicting:
        ids = [n["id"] for n in conflicting]
        case = tx.add(
            "pushback",
            {
                "category": "incompatible requirements",
                "severity": "high",
                "status": "open",
                "affected": [ticket],
                "requirements": ids,
                "quotes": [n["body"]["text"] for n in conflicting],
                "question": "After independent review, should Compartment request permission to open one sandbox ticket or omit the ticket?",
                "alternatives": ["request_ticket", "omit_ticket"],
                "authority": "operator",
            },
            run=run,
            parent=ticket,
            reason="blocks only this action",
        )
        for req in ids:
            tx.link(req, case, "conflicts at the same decision")
    else:
        ids = [n["id"] for n in reqs]
    if not reqs:
        if tx.get(run)["body"]["missing_ticket"] == "omit":
            tx.add(
                "assumption",
                {
                    "category": "resolvable assumption",
                    "basis": "operator-authorized default",
                    "decision": "Omit an unspecified external ticket",
                },
                run=run,
                parent=ticket,
            )
            tx.change(
                ticket,
                "policy",
                state="completed",
                result="omitted by operator default",
            )
        else:
            block_case(
                tx,
                tx.get(ticket),
                "clarification needed",
                "Should this audit request approval for a sandbox ticket or omit it?",
                ["request_ticket", "omit_ticket"],
            )
            tx.change(ticket, "scope", state="blocked")
    participants = ["planning-rep", "execution-rep", "quality-director"]
    mid = coord.meeting(
        tx,
        run,
        plan,
        participants,
        "Resolve ticket timing and assign independent verification.",
        ids,
        "conflict" if conflicting else "intake",
    )
    meeting_task = task(tx, run, "meeting", mid, meeting=mid)
    tx.change(ticket, "control", dependencies=[review, meeting_task])
    tx.link(meeting_task, ticket, "finish deliberation before dispatch")


def target(tx, tid):
    t = tx.get(tid, "task")
    return {
        "tool": "ticket.create",
        "version": "1",
        "target": "sandbox/integration-tickets",
        "scope": t["run"],
        "parameters": {
            "title": "Inventory v2 contract discrepancy",
            "run": t["run"],
            "task": tid,
        },
    }


def block_case(tx, t, category, question, alternatives, authority="operator"):
    existing = next(
        (
            n
            for n in tx.all("pushback", t["run"])
            if n["body"]["status"] == "open"
            and n["body"]["category"] == category
            and t["id"] in n["body"]["affected"]
        ),
        None,
    )
    if existing:
        return existing["id"]
    return tx.add(
        "pushback",
        {
            "category": category,
            "severity": "high",
            "status": "open",
            "affected": [t["id"]],
            "question": question,
            "alternatives": alternatives,
            "authority": authority,
        },
        run=t["run"],
        parent=t["id"],
        reason="requires resolution",
    )


def resolve(tx, case, actor, choice):
    n = tx.get(case, "pushback")
    b = n["body"]
    require(
        b["status"] == "open" and choice in b.get("alternatives", []),
        "Unavailable resolution",
    )
    tid = b["affected"][0]
    tx.change(
        case, actor, status="resolved", resolution=choice, resolved_at=time.time()
    )
    if choice == "cancel_operation":
        from .runtime import intervene

        intervene(tx, n["run"], actor, "cancel")
    elif choice in ("use_audit_scope", "recheck_policy"):
        tx.change(tid, actor, state="queued")
    elif choice in ("request_ticket", "omit_ticket"):
        tx.change(
            tid,
            actor,
            state="pending approval" if choice == "request_ticket" else "completed",
            result=choice,
        )
    else:
        require(choice == "drop_handoff", "Unknown resolution", 422)
    tx.add(
        "decision",
        {"choice": choice, "authority": "intent clarification"},
        run=n["run"],
        parent=case,
        origin=actor,
    )


def pending_decision(tx, task):
    return any(
        n["body"]["status"] == "open" and task["id"] in n["body"]["affected"]
        for n in tx.all("pushback", task["run"])
    )


def approve(tx, tid, actor, action):
    n = tx.get(tid, "task")
    require(
        n["body"]["step"] == "ticket"
        and n["body"]["state"] == "pending approval"
        and not pending_decision(tx, n)
        and action == target(tx, tid),
        "Approval does not match pending action",
    )
    require(
        tx.get(n["run"])["body"]["status"] == "active"
        and capable(tx, n["body"]["owner"], "ticket.create"),
        "Policy denied",
        403,
    )
    aid = tx.add(
        "approval",
        {
            "action": action,
            "fingerprint": digest(action),
            "expires": time.time() + 3600,
        },
        run=n["run"],
        parent=tid,
        origin=actor,
        reason="authorizes exact intent",
    )
    tx.change(tid, actor, state="queued", approval=aid)
    return aid


def authorized(tx, t, now):
    a = t["body"].get("approval")
    if not a or pending_decision(tx, t):
        return False
    b = tx.get(a, "approval")["body"]
    return (
        b["expires"] > now
        and b["fingerprint"] == digest(target(tx, t["id"]))
        and capable(tx, t["body"]["owner"], "ticket.create")
    )


def artifact_data(tx, t):
    return json.loads(tx.read_artifact(t["body"]["artifact"]))


def close_ready(tx, run):
    tasks = tx.all("task", run)
    if (
        tasks
        and not any(n["body"]["status"] == "open" for n in tx.all("pushback", run))
        and all(t["body"]["state"] == "completed" for t in tasks)
        and any(t["body"]["step"] == "verify" for t in tasks)
    ):
        tx.change(run, "control", status="awaiting acceptance")


def accept(tx, run, actor):
    require(
        tx.get(run, "run")["body"]["status"] == "awaiting acceptance",
        "Run is not ready for acceptance",
    )
    v = by_step(tx, run, "verify")
    require(
        artifact_data(tx, v)["pass"]
        and v["body"]["owner"] != by_step(tx, run, "correct")["body"]["owner"],
        "Independent verification required",
    )
    aid = tx.add(
        "acceptance",
        {"verdict": "accepted"},
        run=run,
        parent=v["id"],
        origin=actor,
        reason="operator accepted verified result",
    )
    for e in tx.all("evidence", run):
        if e["id"] == v["body"]["artifact"] or e["body"]["name"] in (
            "ticket result",
            "reconciled receipt",
        ):
            tx.link(e["id"], aid, "supports operator acceptance")
    tx.change(run, actor, status="accepted", acceptance=aid)


def bundle(tx, run, visible):
    require(
        tx.get(run, "run")["body"]["status"] == "accepted",
        "Accept the run before exporting",
    )
    nodes = [n for n in tx.all(run=run) if visible(n)]
    ids = {n["id"] for n in nodes}
    edges = [
        dict(e)
        for e in tx.sql("SELECT * FROM edges ORDER BY src,dst,reason")
        if e["src"] in ids and e["dst"] in ids
    ]
    for n in nodes:
        n["body"].pop("lease", None)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(
            "manifest.json",
            canonical({"format": 1, "run": run, "nodes": nodes, "edges": edges}),
        )
        for n in nodes:
            if n["kind"] == "evidence":
                z.writestr("evidence/" + n["id"] + ".json", tx.read_artifact(n["id"]))
    return buf.getvalue()
