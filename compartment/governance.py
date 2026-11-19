import time

from . import coordination, engine
from .store import require


def may_read(tx, who, n):
    if n["kind"] in ("policy", "agent", "department", "appointment"):
        return True
    run = n["run"]
    if run:
        owner = tx.get(run, "run")["body"]
        if owner["operator"] != who["project"] or "chat_owner" in owner:
            return False
    if n["kind"] in ("schedule", "trigger") and n["body"]["project"] != who["project"]:
        return False
    label = n["access"]
    if label == "org":
        return True
    if label == "operator/" + who["name"]:
        return True
    return (
        label == "department/" + who.get("department", "")
        or label == "agent/" + who.get("agent", "")
        or (label.startswith("task/") and label[5:] in who.get("tasks", []))
    )


def memory(tx, who, run, scope, owner, claim, source, confidence, ttl):
    require(
        scope in ("task", "agent", "department", "org")
        and confidence in ("verified", "assumption", "conclusion", "correction"),
        "Invalid memory classification",
        422,
    )
    require(
        source.strip() and claim.strip() and 0 < ttl <= 31536000,
        "Source, claim and bounded retention required",
        422,
    )
    require(
        tx.get(run, "run")["body"]["operator"] == who["project"], "Run unavailable", 404
    )
    label = "org" if scope == "org" else scope + "/" + owner
    if scope == "task":
        require(tx.get(owner, "task")["run"] == run, "Task outside run", 403)
    elif scope in ("agent", "department"):
        tx.get(owner, scope)
    require(
        may_read(tx, who, {"run": run, "kind": "memory", "body": {}, "access": label}),
        "Outside namespace",
        403,
    )
    return tx.add(
        "memory",
        {
            "claim": claim,
            "source": source,
            "confidence": confidence,
            "expires": time.time() + ttl,
        },
        access=label,
        run=run,
        origin=who["name"],
        parent=run,
    )


def schedule(tx, who, kind, interval, due, run=None):
    require(
        kind in ("operation", "meeting") and 60 <= interval <= 31536000,
        "Invalid schedule",
        422,
    )
    require(
        kind == "meeting" or run is None,
        "Only meeting schedules take a target run",
        422,
    )
    if kind == "meeting":
        require(run and may_read(tx, who, tx.get(run, "run")), "Run unavailable", 404)
    return tx.add(
        "schedule",
        {
            "project": who["project"],
            "type": kind,
            "interval": interval,
            "due": due,
            "target": run,
            "enabled": True,
        },
        origin=who["name"],
        access="org",
    )


def extra_meeting(tx, run, participants, agenda, context, trigger):
    require(tx.get(run, "run")["body"]["status"] == "active", "Run closed")
    require(
        "chat_owner" not in tx.get(run)["body"],
        "This run is a representative conversation",
        422,
    )
    plan = engine.by_step(tx, run, "plan")["id"]
    mid = coordination.meeting(tx, run, plan, participants, agenda, context, trigger)
    engine.task(tx, run, "meeting", mid, meeting=mid)
    return mid


def trigger(tx, project, key, mode, target=None):
    old = [
        n
        for n in tx.all("trigger")
        if n["body"]["project"] == project and n["body"]["key"] == key
    ]
    if old:
        return old[0]["body"]["result"]
    if target:
        require(
            tx.get(target, "run")["body"]["operator"] == project, "Run unavailable", 404
        )
        rid = extra_meeting(
            tx,
            target,
            ["planning-rep", "quality-rep"],
            "Review the current audit dependency.",
            [],
            "schedule",
        )
    else:
        rid = engine.start(tx, project, mode=mode)
    tx.add("trigger", {"project": project, "key": key, "result": rid}, parent=rid)
    return rid


def tick(tx, mode):
    if tx.get("policy")["body"]["stopped"]:
        return
    now = time.time()
    for s in tx.all("schedule"):
        b = s["body"]
        if b["enabled"] and b["due"] <= now:
            target = b["target"]
            if target and tx.get(target)["body"]["status"] != "active":
                tx.change(s["id"], "clock", enabled=False, error="Target run closed")
                continue
            trigger(tx, b["project"], s["id"] + "/" + str(b["due"]), mode, target)
            # Coalesce missed intervals into one run and preserve the original cadence.
            next_due = (
                b["due"] + (1 + int((now - b["due"]) // b["interval"])) * b["interval"]
            )
            tx.change(s["id"], "clock", due=next_due)


def view(tx, who, run):
    r = tx.get(run, "run")
    require(may_read(tx, who, r), "Run unavailable", 404)
    nodes = [
        n
        for n in tx.all(run=run)
        if may_read(tx, who, n)
        and not (n["kind"] == "memory" and n["body"]["expires"] <= time.time())
    ]
    for n in nodes:
        if n["kind"] == "task":
            n["body"].pop("lease", None)
            if n["body"]["step"] == "ticket":
                n["body"]["action"] = engine.target(tx, n["id"])
    ids = {n["id"] for n in nodes}
    edges = [
        dict(e)
        for e in tx.sql(
            "SELECT e.* FROM edges e JOIN nodes n ON n.id=e.src WHERE n.run=?", (run,)
        )
        if e["src"] in ids and e["dst"] in ids
    ]
    return {"run": r, "nodes": nodes, "edges": edges}


def metrics(nodes):
    tasks = [n for n in nodes if n["kind"] == "task"]
    reviews = [
        n
        for n in tasks
        if n["body"]["step"] in ("review", "verify") and n["body"].get("artifact")
    ]
    run = next(n for n in nodes if n["kind"] == "run")
    accepted = next((n for n in nodes if n["kind"] == "acceptance"), None)
    requests = [n for n in nodes if n["kind"] == "request" and n["body"]["via"]]
    resolved = [
        n for n in nodes if n["kind"] == "pushback" and n["body"].get("resolved_at")
    ]
    reserved = sum(n["body"]["amount"] for n in nodes if n["kind"] == "reservation")
    rejected = sum(
        n["kind"] == "pushback" and n["body"]["category"] == "evidence disagreement"
        for n in nodes
    )
    return {
        "tasks": len(tasks),
        "verified_report_error_rate": rejected / len(reviews) if reviews else None,
        "reserved_cost_per_accepted_run_microusd": reserved if accepted else None,
        "acceptance_latency_s": accepted["created"] - run["created"]
        if accepted
        else None,
        "handoff_success_rate": sum(r["body"]["status"] == "answered" for r in requests)
        / len(requests)
        if requests
        else None,
        "mean_conflict_resolution_s": sum(
            n["body"]["resolved_at"] - n["created"] for n in resolved
        )
        / len(resolved)
        if resolved
        else None,
        "active_model_reservations": sum(
            n["kind"] == "reservation" and n["body"]["status"] == "active"
            for n in nodes
        ),
        "running": sum(n["body"]["state"] == "running" for n in tasks),
        "completed": sum(n["body"]["state"] == "completed" for n in tasks),
        "retries": sum(
            n["body"].get("failures", 0) + n["body"].get("recovered_leases", 0)
            for n in tasks
        ),
        "open_conflicts": sum(
            n["kind"] == "pushback" and n["body"]["status"] == "open" for n in nodes
        ),
        "reserved_microusd": sum(
            n["body"]["amount"] for n in nodes if n["kind"] == "reservation"
        ),
        "reviews": len(reviews),
        "human_decisions": sum(
            n["kind"] in ("decision", "approval", "acceptance") for n in nodes
        ),
    }
