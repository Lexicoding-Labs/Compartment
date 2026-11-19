import time

from .org import capable, holder
from .store import require

KINDS = {"ADVICE", "ASSIST", "DELEGATE", "REVIEW", "ESCALATE"}


def handoff(
    tx, task_id, sender, recipient, kind, scope, output, seconds, tools=(), parent=None
):
    task = tx.get(task_id, "task")
    run = task["run"]
    require(
        kind in KINDS and 0 < seconds <= 86400 and scope.strip() and output.strip(),
        "Invalid handoff contract",
        422,
    )
    tx.get(sender, "agent")
    tx.get(recipient, "agent")
    p = tx.get("policy")["body"]
    path = [sender]
    allowed = set(tx.get(sender)["body"]["tools"])
    require(
        sender == task["body"]["owner"] or parent,
        "Sender does not own this assignment",
        403,
    )
    if parent:
        old = tx.get(parent, "request")
        require(
            old["run"] == run
            and old["body"]["task"] == task_id
            and old["body"]["recipient"] == sender
            and old["body"]["status"] in ("sent", "received"),
            "Handoff outside active request",
            403,
        )
        path = old["body"]["path"]
        allowed = set(old["body"]["tools"])
    siblings = [
        r
        for r in tx.all("request", run)
        if r["body"]["task"] == task_id
        and r["body"]["sender"] == sender
        and r["body"]["parent"] == parent
    ]
    issue = None
    if recipient in path:
        issue = "Circular delegation"
    elif len(path) > p["depth"] or len(siblings) >= p["fanout"]:
        issue = "Delegation limit exceeded"
    if not issue and kind in ("ASSIST", "DELEGATE", "REVIEW"):
        waiting = {}
        for request in tx.all("request", run):
            rb = request["body"]
            if rb["type"] in ("ASSIST", "DELEGATE", "REVIEW") and rb["status"] in (
                "received",
                "sent",
            ):
                waiting.setdefault(rb["sender"], set()).add(rb["recipient"])
        stack = [recipient]
        seen = set()
        while stack:
            identity = stack.pop()
            if identity == sender:
                issue = "Circular delegation"
                break
            if identity not in seen:
                seen.add(identity)
                stack.extend(waiting.get(identity, ()))
    if issue:
        return tx.add(
            "pushback",
            {
                "category": "circular delegation"
                if issue == "Circular delegation"
                else "resource conflict",
                "status": "open",
                "severity": "high",
                "affected": [task_id],
                "question": issue,
                "path": [*path, recipient],
                "alternatives": ["drop_handoff", "cancel_operation"],
                "authority": "operator",
            },
            run=run,
            parent=task_id,
            reason="escalates bounded handoff",
        )
    require(
        set(tools) <= allowed and all(capable(tx, recipient, t) for t in tools),
        "Permission expansion denied",
        403,
    )
    a, b = (tx.get(i)["body"]["department"] for i in (sender, recipient))
    via = (
        []
        if a == b
        else [holder(tx, a + "-rep", time.time()), holder(tx, b + "-rep", time.time())]
    )
    require(
        all(tx.get(i)["body"]["available"] for i in via),
        "Department liaison unavailable",
    )
    return tx.add(
        "request",
        {
            "type": kind,
            "sender": sender,
            "recipient": recipient,
            "task": task_id,
            "scope": scope,
            "output": output,
            "tools": sorted(tools),
            "via": via,
            "parent": parent,
            "path": [*path, recipient],
            "status": "sent",
            "deadline": time.time() + seconds,
            "seconds": seconds,
        },
        run=run,
        parent=parent or task_id,
        origin=sender,
        reason=kind.lower(),
    )


def reply(tx, request, agent, status, answer):
    b = tx.get(request, "request")["body"]
    require(agent == b["recipient"], "Only the recipient can answer", 403)
    require(
        time.time() <= b["deadline"]
        and (b["status"], status)
        in {("sent", "received"), ("received", "answered"), ("received", "declined")},
        "Request closed or invalid transition",
    )
    return tx.change(request, agent, status=status, response=answer)


def expire(tx):
    now = time.time()
    for req in tx.all("request"):
        b = req["body"]
        if b["status"] in ("received", "sent") and b["deadline"] < now:
            tx.change(req["id"], "clock", status="timed_out")
            tx.add(
                "escalation",
                {"reason": "Request timed out", "task": b["task"]},
                run=req["run"],
                parent=req["id"],
            )


def meeting(tx, run, task, participants, agenda, context, trigger):
    require(
        2 <= len(participants) <= 25 and len(set(participants)) == len(participants),
        "Choose distinct attendees",
        422,
    )
    agents = [tx.get(i, "agent") for i in participants]
    departments = sorted({a["body"]["department"] for a in agents})
    require(
        len(departments) >= 2 and all(a["body"]["available"] for a in agents),
        "Two available departments required",
    )
    for ref in context:
        n = tx.get(ref)
        require(
            n["run"] == run
            and n["access"] == "org"
            and n["kind"] in ("requirement", "evidence", "pushback"),
            "Pre-read unavailable to all attendees",
            403,
        )
    require(tx.get(task, "task")["run"] == run, "Wrong originating task")
    now = time.time()
    mid = tx.add(
        "meeting",
        {
            "purpose": "Resolve an operational dependency",
            "agenda": agenda,
            "originating_task": task,
            "participants": participants,
            "departments": departments,
            "chair": participants[0],
            "context": context,
            "visibility": "approved run context",
            "trigger": trigger,
            "scheduled": now,
            "started": now,
            "ends_by": now + 1800,
            "turn_limit": len(participants),
            "token_limit": 256 * len(participants),
            "turns": [],
            "status": "open",
        },
        run=run,
        parent=task,
        reason="convened",
    )
    tx.add(
        "meeting_event",
        {"type": "MEETING_REQUEST", "meeting": mid, "invited": participants},
        run=run,
        parent=mid,
        origin=participants[0],
    )
    return mid


def close_meeting(tx, mid, conflicts, actions):
    m = tx.get(mid, "meeting")
    b = m["body"]
    if b["status"] == "closed":
        return b["minutes"]
    require(
        len(b["turns"]) == len(b["participants"]) or time.time() >= b["ends_by"],
        "Meeting still has pending rounds",
    )
    decisions = (
        ["Assign independent verification within the existing department quota."]
        if any(t["position"] == "commitment" for t in b["turns"])
        else []
    )
    minutes = {
        "evidence": b["context"],
        "proposals": b["turns"],
        "agreements": decisions,
        "dissent": [t for t in b["turns"] if t["position"] == "dissent"],
        "outstanding": conflicts,
        "actions": actions,
        "ended": time.time(),
    }
    for event, items in [
        ("MEETING_DECISION", decisions),
        ("MEETING_ACTION", actions),
        ("MEETING_ESCALATE", conflicts),
    ]:
        for item in items:
            tx.add(
                "meeting_event",
                {"type": event, "item": item},
                run=m["run"],
                parent=mid,
                origin=b["chair"],
            )
    for a in actions:
        tx.link(mid, a["task"], "assigned follow-up")
    tx.change(mid, "control", status="closed", minutes=minutes, ended=minutes["ended"])
    return minutes
