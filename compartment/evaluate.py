"""Local, synthetic decision replay. All arms receive the same evidence, two turns and token ceilings."""

import argparse
import json
import os
import time
from pathlib import Path

import httpx

from .engine import PLAYBOOK, conflicting_pair
from .probe import compare
from .store import digest

ARMS = ("single agent", "multi-agent without Pushback", "Compartment assurance")
CASES = [
    (
        "type drift with conflict",
        {"sku": "P-104", "available": "12"},
        ["open", "hold"],
        False,
        True,
    ),
    (
        "compatible without conflict",
        {"sku": "P-104", "available": 12},
        ["hold"],
        True,
        False,
    ),
    ("missing field without conflict", {"sku": "P-104"}, ["hold"], False, False),
    (
        "compatible with conflict",
        {"sku": "P-104", "available": 0},
        ["open", "hold"],
        True,
        True,
    ),
]


def query(client, model, messages):
    response = client.post(
        "/chat/completions",
        json={
            "model": model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": 192,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "audit_decision",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "compatible": {"type": "boolean"},
                            "ask_operator": {"type": "boolean"},
                        },
                        "required": ["compatible", "ask_operator"],
                        "additionalProperties": False,
                    },
                },
            },
        },
    )
    response.raise_for_status()
    data = response.json()
    text = data["choices"][0]["message"]["content"]
    try:
        parsed = json.loads(text)
        if not all(type(parsed.get(k)) is bool for k in ("compatible", "ask_operator")):
            parsed = None
    except (ValueError, AttributeError):
        parsed = None
    return parsed, data.get("usage", {})


def run(endpoint, model, output):
    records = []
    headers = {}
    if os.environ.get("EVAL_API_KEY"):
        headers["Authorization"] = "Bearer " + os.environ["EVAL_API_KEY"]
    with httpx.Client(
        base_url=endpoint.rstrip("/") + "/",
        headers=headers,
        timeout=90,
        trust_env=False,
    ) as client:
        for index, (name, sample, effects, gold_ok, gold_conflict) in enumerate(CASES):
            rules = [
                next(r for r in PLAYBOOK["rules"] if r["effect"] == e) for e in effects
            ]
            primary = {
                "contract": PLAYBOOK["contract"],
                "sample": sample,
                "instructions": [r["text"] for r in rules],
            }
            # Rotate execution order to reduce systematic warm-up effects.
            for arm in ARMS[index % 3 :] + ARMS[: index % 3]:
                start = time.monotonic()
                prompt = "Decide from the supplied inventory contract, sample and ticket instructions. Return JSON with boolean compatible and ask_operator. Ask when two instructions conflict. Every external write requires separate approval."
                first, u1 = query(
                    client,
                    model,
                    [
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": json.dumps(primary)},
                    ],
                )
                instruction = (
                    "Recheck your previous decision."
                    if arm == ARMS[0]
                    else "You are a different reviewer. Independently adjudicate the primary evidence."
                )
                final, u2 = query(
                    client,
                    model,
                    [
                        {"role": "system", "content": prompt + " " + instruction},
                        {
                            "role": "user",
                            "content": json.dumps(
                                {
                                    "evidence": primary,
                                    "prior": first if arm == ARMS[0] else None,
                                }
                            ),
                        },
                    ],
                )
                applied = []
                observed = final
                if arm == ARMS[2] and final is not None:
                    observed = {
                        "compatible": not compare(primary["contract"], sample),
                        "ask_operator": bool(conflicting_pair(rules)),
                    }
                    applied = [
                        "reproduced contract check",
                        "structured requirement comparison",
                    ]
                correct = (
                    observed is not None
                    and observed["compatible"] == gold_ok
                    and observed["ask_operator"] == gold_conflict
                )
                records.append(
                    {
                        "case": name,
                        "arm": arm,
                        "primary": primary,
                        "model": model,
                        "first": first,
                        "second": final,
                        "controls": applied,
                        "decision": observed,
                        "expected": {
                            "compatible": gold_ok,
                            "ask_operator": gold_conflict,
                        },
                        "accepted": correct,
                        "usage": [u1, u2],
                        "latency_s": round(time.monotonic() - start, 3),
                    }
                )
    metrics = {}
    for arm in ARMS:
        rows = [r for r in records if r["arm"] == arm]
        tp = sum(
            bool(
                r["decision"]
                and r["decision"]["ask_operator"]
                and r["expected"]["ask_operator"]
            )
            for r in rows
        )
        fp = sum(
            bool(
                r["decision"]
                and r["decision"]["ask_operator"]
                and not r["expected"]["ask_operator"]
            )
            for r in rows
        )
        positives = sum(r["expected"]["ask_operator"] for r in rows)
        metrics[arm] = {
            "accepted": sum(r["accepted"] for r in rows),
            "cases": len(rows),
            "conflict_precision": tp / (tp + fp) if tp + fp else None,
            "conflict_recall": tp / positives,
            "false_positive_rate": fp / (len(rows) - positives),
            "model_calls": len(rows) * 2,
            "tokens": sum(u.get("total_tokens", 0) for r in rows for u in r["usage"]),
        }
    report = {
        "format": 1,
        "playbook_digest": digest(PLAYBOOK),
        "source": "synthetic decision replay",
        "model": model,
        "method": "Four controlled fixtures. Two calls per arm per fixture, 192 output tokens per call. Fresh contexts for independent reviewers. Only the assurance arm applies deterministic checks. This measures decision correctness on these fixtures; tools have no external side effects.",
        "metrics": metrics,
        "records": records,
    }
    output.write_text(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    cli = argparse.ArgumentParser()
    cli.add_argument("--endpoint", required=True)
    cli.add_argument("--model", required=True)
    cli.add_argument("--output", type=Path, required=True)
    args = cli.parse_args()
    print(json.dumps(run(args.endpoint, args.model, args.output)["metrics"], indent=2))
