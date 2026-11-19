from .contracts import OUTPUTS
from .store import require

DEPARTMENTS = {
    "planning": (
        "Planning & Coordination",
        "Intake, dependencies, scheduling and escalation",
        ["Intake", "Dependency planning", "Scheduling"],
    ),
    "research": (
        "Research & Intelligence",
        "Discovery, primary sources and challenge",
        ["Discovery", "Source verification", "Synthesis"],
    ),
    "execution": (
        "Execution & Integrations",
        "Bounded integration and computer operations",
        ["Integration testing", "API compatibility", "Ticket operations"],
    ),
    "quality": (
        "Quality & Assurance",
        "Independent reproduction and acceptance",
        ["Independent testing", "Evidence review", "Regression"],
    ),
    "reliability": (
        "Reliability & Operations",
        "Recovery, resource supervision and knowledge hygiene",
        ["Recovery", "Capacity", "Knowledge hygiene"],
    ),
}
TOOLS = {
    "peer": "request.reply",
    "chat": "request.reply",
    "inspect": "contract.read",
    "draft": "report.write",
    "review": "contract.verify",
    "correct": "report.write",
    "verify": "contract.verify",
    "ticket": "ticket.create",
    "meeting": "meeting.speak",
    "plan": "assignment.plan",
}
OWNERS = {
    "plan": "planning-director",
    "inspect": "research-s1",
    "meeting": "planning-rep",
    "draft": "execution-s1",
    "review": "quality-s1",
    "correct": "execution-s1",
    "verify": "quality-s1",
    "ticket": "execution-s3",
}


def seed(tx):
    if not tx.all("policy"):
        tx.add(
            "policy",
            {
                "stopped": False,
                "workers": 3,
                "model_slots": 2,
                "budget_microusd": 1000000,
                "fanout": 5,
                "depth": 4,
                "disabled_tools": [],
            },
            id="policy",
        )
    registered = {n["id"] for n in tx.all("tool")}
    for name in sorted(set(TOOLS.values())):
        if "tool/" + name in registered:
            continue
        adapter = {
            "contract.read": "inventory.inspect",
            "contract.verify": "inventory.verify",
            "ticket.create": "sandbox.ticket.put",
        }.get(name, "control.bounded")
        tx.add(
            "tool",
            {
                "name": name,
                "version": "1",
                "adapter": adapter,
                "input_contract": "Assigned fixture scope",
                "output_contract": OUTPUTS[name].model_json_schema(),
                "calls_per_minute": 20,
                "sensitive": name == "ticket.create",
            },
            id="tool/" + name,
        )
    for key, (name, mission, specs) in DEPARTMENTS.items():
        if any(x["id"] == key for x in tx.all("department")):
            continue
        tx.add(
            "department",
            {"name": name, "mission": mission, "quota": 2, "escalation": "operator"},
            id=key,
        )
        for suffix, title in zip(
            ["director", "rep", "s1", "s2", "s3"],
            ["Director", "Representative", *specs],
        ):
            identity = key + "-" + suffix
            tools = {
                tool for step, tool in TOOLS.items() if OWNERS.get(step) == identity
            }
            tools.update(("meeting.speak", "request.reply"))
            tx.add(
                "agent",
                {
                    "department": key,
                    "role": {"director": "Director", "rep": "Representative"}.get(
                        suffix, "Specialist"
                    ),
                    "title": title,
                    "instructions": title + " for " + mission,
                    "version": 1,
                    "tools": sorted(tools),
                    "available": True,
                },
                id=identity,
                parent=key,
                reason="staffs",
            )


def capable(tx, agent, tool):
    a = tx.get(agent, "agent")["body"]
    p = tx.get("policy")["body"]
    return a["available"] and tool in a["tools"] and tool not in p["disabled_tools"]


def holder(tx, agent, now):
    if tx.get(agent, "agent")["body"]["available"]:
        return agent
    for item in reversed(tx.all("appointment")):
        b = item["body"]
        if (
            b["position"] == agent
            and b["until"] > now
            and tx.get(b["acting"])["body"]["available"]
        ):
            return b["acting"]
    return agent


def appoint(tx, position, acting, until, now, actor):
    p, a = (tx.get(i, "agent")["body"] for i in (position, acting))
    require(
        position != acting
        and p["department"] == a["department"]
        and p["role"] in ("Director", "Representative")
        and a["available"]
        and now < until <= now + 86400 * 30,
        "Invalid acting appointment",
    )
    return tx.add(
        "appointment",
        dict(position=position, acting=acting, until=until),
        origin=actor,
        parent=position,
        reason="covers absence",
    )
