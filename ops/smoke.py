"""Run one synthetic attended audit against a running deployment using an operator credential."""

import argparse
import hashlib
import io
import json
import os
import time
from urllib.request import Request, urlopen
from zipfile import ZipFile


def smoke(url, token):
    def call(path, data=None):
        request = Request(
            url.rstrip("/") + "/api/v1/" + path,
            data=json.dumps(data).encode() if data is not None else None,
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + token,
            },
        )
        with urlopen(request, timeout=20) as res:
            return res.read() if path.endswith("/bundle") else json.load(res)

    begin = time.monotonic()
    org = call("overview")
    assert len(org["agents"]) == 25 and len(org["departments"]) == 5
    rid = call("runs", {})["id"]
    path = "runs/" + rid
    while time.monotonic() - begin < 300:
        detail = call(path)
        tasks = [n for n in detail["nodes"] if n["kind"] == "task"]
        failures = [t for t in tasks if t["body"]["state"] == "failed"]
        if failures:
            raise RuntimeError(
                [(t["body"]["step"], t["body"].get("error")) for t in failures]
            )
        case = next(
            (
                n
                for n in detail["nodes"]
                if n["kind"] == "pushback"
                and n["body"]["category"] == "incompatible requirements"
                and n["body"]["status"] == "open"
            ),
            None,
        )
        inspected = any(
            t["body"]["step"] == "inspect" and t["body"]["state"] == "completed"
            for t in tasks
        )
        met = any(
            n["kind"] == "meeting" and n["body"]["status"] == "closed"
            for n in detail["nodes"]
        )
        if case and inspected and met:
            call("pushback/" + case["id"] + "/resolve", {"choice": "request_ticket"})
        for t in tasks:
            if t["body"]["state"] == "pending approval":
                call("approvals/" + t["id"], t["body"]["action"])
        if detail["run"]["body"]["status"] == "awaiting acceptance":
            call(path + "/accept", {})
            break
        time.sleep(0.4)
    else:
        raise RuntimeError(
            "Deadline exceeded: "
            + str([(t["body"]["step"], t["body"]["state"]) for t in tasks])
        )
    with ZipFile(io.BytesIO(call(path + "/bundle"))) as z:
        manifest = json.loads(z.read("manifest.json"))
        nodes = manifest["nodes"]
        minutes = next(n["body"]["minutes"] for n in nodes if n["kind"] == "meeting")
        assert minutes["dissent"] and minutes["actions"] and minutes["outstanding"]
        for n in nodes:
            if n["kind"] == "evidence":
                raw = z.read("evidence/" + n["id"] + ".json")
                assert hashlib.sha256(raw).hexdigest() == n["body"]["sha256"]
        assert any(
            n["kind"] == "intent" and n["body"]["status"] == "confirmed" for n in nodes
        )
        assert any(
            n["kind"] == "request"
            and n["body"]["type"] == "ADVICE"
            and n["body"]["status"] == "answered"
            for n in nodes
        )
        for step, passed in (("review", False), ("verify", True)):
            t = next(
                n for n in nodes if n["kind"] == "task" and n["body"]["step"] == step
            )
            assert (
                json.loads(z.read("evidence/" + t["body"]["artifact"] + ".json"))[
                    "pass"
                ]
                is passed
            )
    return {
        "run": rid,
        "identities": 25,
        "departments": 5,
        "model_mode": org["mode"],
        "status": "accepted",
        "lineage_nodes": len(nodes),
        "lineage_edges": len(manifest["edges"]),
        "elapsed_s": round(time.monotonic() - begin, 2),
        "audit_integrity": bool(call("audit/integrity")["head"]),
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="http://127.0.0.1:8080")
    args = p.parse_args()
    print(json.dumps(smoke(args.url, os.environ["OPERATOR_TOKEN"]), indent=2))
