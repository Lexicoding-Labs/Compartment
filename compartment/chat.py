"""Private operator-to-representative turns, executed by the existing bounded worker queue."""

import time
from uuid import NAMESPACE_URL, uuid5

from .org import capable, holder
from .store import canonical, require


def conversation(tx, who, rep):
    agent = tx.get(rep, "agent")
    require(
        agent["body"]["role"] == "Representative",
        "Choose a department Representative",
        422,
    )
    runs = [
        r
        for r in tx.all("run")
        if r["body"].get("chat_owner") == who["name"]
        and r["body"]["operator"] == who["project"]
        and r["body"].get("representative") == rep
    ]
    turns = []
    for r in runs:
        b = r["body"]
        t = tx.get(b["task"], "task")["body"]
        state = t["state"] if b["status"] == "active" else b["status"]
        turns.append(
            {
                "id": r["id"],
                "created": r["created"],
                "message": b["message"],
                "reply": b.get("reply"),
                "state": state,
                "model": b.get("model"),
                "error": t.get("error"),
                "speaker": b.get("speaker", rep),
            }
        )
    return turns


def post(tx, who, rep, message, client_id, mode):
    message = message.strip()
    require(message, "Enter a message", 422)
    history = conversation(tx, who, rep)
    rid = str(
        uuid5(
            NAMESPACE_URL, canonical([who["project"], who["name"], rep, str(client_id)])
        )
    )
    prior = next((r for r in history if r["id"] == rid), None)
    if prior:
        require(prior["message"] == message, "Message identifier already used")
        return rid
    require(not tx.get("policy")["body"]["stopped"], "Emergency stop active")
    require(
        capable(tx, holder(tx, rep, time.time()), "request.reply"),
        "Representative unavailable or reply permission disabled",
    )
    require(
        not any(r["state"] in ("queued", "running", "waiting") for r in history),
        "Wait for the pending reply",
    )
    tid = str(uuid5(NAMESPACE_URL, rid + "/reply"))
    access = "operator/" + who["name"]
    tx.add(
        "run",
        {
            "operator": who["project"],
            "chat_owner": who["name"],
            "representative": rep,
            "objective": "Department conversation",
            "status": "active",
            "model_mode": mode,
            "message": message,
            "task": tid,
        },
        id=rid,
        run=rid,
        origin=who["name"],
        access=access,
    )
    tx.add(
        "task",
        {
            "step": "chat",
            "owner": rep,
            "state": "queued",
            "dependencies": [],
            "priority": 50,
            "deadline": time.time() + 600,
            "attempt": 0,
            "input": "Reply to the operator",
            "expected": "Bounded textual advice",
            "acceptance": "Reply from the department liaison",
            "agent_version": tx.get(rep)["body"]["version"],
        },
        id=tid,
        run=rid,
        parent=rid,
        origin=who["name"],
        access=access,
    )
    return rid


def inputs(tx, run, owner):
    rep = run["representative"]
    agent = tx.get(owner)["body"]
    dept = tx.get(agent["department"])["body"]
    turns = conversation(
        tx, {"name": run["chat_owner"], "project": run["operator"]}, rep
    )
    history = [
        {"message": r["message"][:1600], "reply": r["reply"][:1600]}
        for r in turns
        if r["reply"]
    ][-6:]
    return {
        "mode": run["model_mode"],
        "department": dept["name"],
        "mission": dept["mission"],
        "instructions": agent["instructions"],
        "message": run["message"],
        "history": history,
    }


def previews(tx, who):
    previews = {}
    for r in tx.all("run"):
        b = r["body"]
        if b.get("chat_owner") == who["name"] and b["operator"] == who["project"]:
            previews[b["representative"]] = {
                "text": (b.get("reply") or b["message"])[:100],
                "created": r["created"],
            }
    return previews
