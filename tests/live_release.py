"""Attended reference-path smoke test on native PostgreSQL, real HTTP, Chromium, and a configured model.
Run from the repository root. pgserver is a test-only dependency. Uses private temporary databases.
"""

import argparse
import hashlib
import io
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

import httpx
from pgserver import get_server

from compartment.backup import backup, restore
from compartment.store import Store


def port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return str(sock.getsockname()[1])


def run_test(out, chromium, endpoint, model, exercise_fallback=False):
    out.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parents[1]
    summary = {"fixture": "inventory-v2", "model": model, "gates": {}}
    with tempfile.TemporaryDirectory(prefix="cpt-", dir="/tmp") as temp:
        tmp = Path(temp)
        env = {
            **os.environ,
            "PYTHONPATH": str(root),
            "ARTIFACT_DIR": str(tmp / "artifacts"),
            "AUDIT_KEY": secrets.token_hex(24),
            "OPERATOR_TOKEN": secrets.token_hex(24),
            "WORKER_TOKEN": secrets.token_hex(24),
            "TICKET_TOKEN": secrets.token_hex(24),
            "TICKET_DB": str(tmp / "tickets.db"),
            "CHROMIUM": chromium,
            "LAB_PORT": port(),
            "MODEL_ROUTES": json.dumps(
                [
                    {
                        "name": "local",
                        "model": model,
                        "charge": 0,
                        "capabilities": ["meeting", "advice"],
                    }
                ]
            ),
            "MODEL_ENDPOINTS": json.dumps({"local": {"url": endpoint}}),
        }
        env["CRASH_MARKER"] = str(tmp / "hold-response")
        env["LAB_URL"] = "http://127.0.0.1:" + env["LAB_PORT"]
        env["CONTROL_URL"] = "http://127.0.0.1:" + port()
        env["TICKET_URL"] = "http://127.0.0.1:" + port()
        if exercise_fallback:
            # The lab has no model endpoint. Its HTTP 404 exercises a real failed call.
            routes = json.loads(env["MODEL_ROUTES"])
            routes.insert(
                0,
                {
                    "name": "unavailable-test-route",
                    "model": "unavailable",
                    "charge": 0,
                    "capabilities": ["advice"],
                    "agents": ["research-s2"],
                },
            )
            env["MODEL_ROUTES"] = json.dumps(routes)
            env["MODEL_ENDPOINTS"] = json.dumps(
                {
                    "unavailable-test-route": {"url": env["LAB_URL"] + "/v1"},
                    "local": {"url": endpoint},
                }
            )
        processes = []
        servers = []

        def start(args, name):
            with (tmp / (name + ".log")).open("ab") as log:
                p = subprocess.Popen(
                    [sys.executable, *args], cwd=root, env=env, stdout=log, stderr=log
                )
            processes.append(p)
            return p

        def healthy(url, p):
            for _ in range(150):
                if p.poll() is not None:
                    raise RuntimeError("Service exited: " + str(p.returncode))
                try:
                    if httpx.get(
                        url + "/health", timeout=1, trust_env=False
                    ).is_success:
                        return
                except httpx.HTTPError:
                    pass
                time.sleep(0.1)
            raise RuntimeError("Service readiness timeout")

        def stop(p):
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(10)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait()

        def start_control():
            ctl = start(
                [
                    "-m",
                    "uvicorn",
                    "compartment.api:app",
                    "--port",
                    env["CONTROL_URL"].split(":")[-1],
                    "--no-access-log",
                ],
                "control",
            )
            healthy(env["CONTROL_URL"], ctl)
            return ctl

        def plane():
            ctl = start_control()
            w = start(["-m", "compartment.worker"], "worker")
            return ctl, w

        def audit(client, keep):
            run = client.post("/api/v1/runs", json={}).raise_for_status().json()["id"]
            end = time.monotonic() + 300
            while time.monotonic() < end:
                d = client.get("/api/v1/runs/" + run).raise_for_status().json()
                tasks = [n for n in d["nodes"] if n["kind"] == "task"]
                if any(t["body"]["state"] == "failed" for t in tasks):
                    raise RuntimeError(
                        str(
                            [(t["body"]["step"], t["body"].get("error")) for t in tasks]
                        )
                    )
                case = next(
                    (
                        n
                        for n in d["nodes"]
                        if n["kind"] == "pushback"
                        and n["body"]["category"] == "incompatible requirements"
                        and n["body"]["status"] == "open"
                    ),
                    None,
                )
                met = next(
                    (
                        n
                        for n in d["nodes"]
                        if n["kind"] == "meeting" and n["body"]["status"] == "closed"
                    ),
                    None,
                )
                if (
                    case
                    and met
                    and any(
                        t["body"]["step"] == "inspect"
                        and t["body"]["state"] == "completed"
                        for t in tasks
                    )
                ):
                    client.post(
                        "/api/v1/pushback/" + case["id"] + "/resolve",
                        json={"choice": "request_ticket"},
                    ).raise_for_status()
                for t in tasks:
                    if t["body"]["state"] == "pending approval":
                        client.post(
                            "/api/v1/approvals/" + t["id"], json=t["body"]["action"]
                        ).raise_for_status()
                if d["run"]["body"]["status"] == "awaiting acceptance":
                    client.post("/api/v1/runs/" + run + "/accept").raise_for_status()
                    break
                time.sleep(0.3)
            else:
                raise RuntimeError(
                    "Audit deadline exceeded: "
                    + str(
                        [
                            (
                                t["body"]["step"],
                                t["body"]["state"],
                                t["body"].get("error"),
                            )
                            for t in tasks
                        ]
                    )
                )
            raw = (
                client.get("/api/v1/runs/" + run + "/bundle").raise_for_status().content
            )
            with zipfile.ZipFile(io.BytesIO(raw)) as z:
                manifest = json.loads(z.read("manifest.json"))
                nodes = manifest["nodes"]
                assert any(n["kind"] == "acceptance" for n in nodes)
                m = next(n for n in nodes if n["kind"] == "meeting")["body"]["minutes"]
                assert (
                    m["dissent"]
                    and m["actions"]
                    and all(
                        p["model"] and "fixture" not in p["model"]
                        for p in m["proposals"]
                    )
                )
                for step, expected in [("review", False), ("verify", True)]:
                    t = next(
                        n
                        for n in nodes
                        if n["kind"] == "task" and n["body"]["step"] == step
                    )
                    evidence = json.loads(
                        z.read("evidence/" + t["body"]["artifact"] + ".json")
                    )
                    assert evidence["pass"] == expected
                for n in nodes:
                    if n["kind"] == "evidence":
                        assert (
                            hashlib.sha256(
                                z.read("evidence/" + n["id"] + ".json")
                            ).hexdigest()
                            == n["body"]["sha256"]
                        )
                if keep:
                    (out / "reference-evidence.zip").write_bytes(raw)
                    summary.update(
                        run=run,
                        nodes=len(nodes),
                        edges=len(manifest["edges"]),
                        meeting_positions=m["proposals"],
                    )
            return run

        try:
            for name in ["original", "restored"]:
                (tmp / name).mkdir()
                servers.append(get_server(tmp / name))
            env["DATABASE_URL"] = servers[0].get_uri()
            original = Store(env["DATABASE_URL"], env["ARTIFACT_DIR"], env["AUDIT_KEY"])
            lab = start(
                [
                    "-m",
                    "uvicorn",
                    "compartment.lab:app",
                    "--port",
                    env["LAB_PORT"],
                    "--no-access-log",
                ],
                "lab",
            )
            healthy(env["LAB_URL"], lab)
            tickets = start(
                [
                    "-m",
                    "uvicorn",
                    "tests.lagged_ticket:app",
                    "--port",
                    env["TICKET_URL"].split(":")[-1],
                    "--no-access-log",
                ],
                "tickets",
            )
            healthy(env["TICKET_URL"], tickets)
            ctl, w = plane()
            with httpx.Client(
                base_url=env["CONTROL_URL"],
                headers={"Authorization": "Bearer " + env["OPERATOR_TOKEN"]},
                trust_env=False,
                timeout=20,
            ) as client:
                assert client.get("/").status_code == 200
                assert len(client.get("/api/v1/agents").json()) == 25
                rid = audit(client, True)
                if exercise_fallback:
                    with original.transaction(write=False) as tx:
                        reservations = tx.all("reservation", rid)
                        assert any(
                            r["body"]["provider"] == "unavailable-test-route"
                            and r["body"]["status"] == "unknown"
                            for r in reservations
                        )
                        peer = next(
                            t
                            for t in tx.all("task", rid)
                            if t["body"]["step"] == "peer"
                        )
                        assert (
                            peer["body"]["attempt"] == 2
                            and peer["body"]["state"] == "completed"
                        )
                    summary["provider_failover"] = (
                        "unavailable HTTP endpoint to live local model passed"
                    )
                if os.environ.get("PLAYWRIGHT_MODULE"):
                    subprocess.run(
                        ["node", "tests/console.cjs"],
                        env=env,
                        cwd=root,
                        timeout=240,
                        check=True,
                    )
                    summary["browser_console"] = "pass"
                from tests.crash_gate import exercise

                ctl, summary["crash_recovery"] = exercise(
                    client, env, original, ctl, w, stop, start_control
                )
                stop(ctl)
                backup(original, tmp / "backup.zip")
                env["DATABASE_URL"] = servers[1].get_uri()
                env["ARTIFACT_DIR"] = str(tmp / "restored-artifacts")
                second = Store(
                    env["DATABASE_URL"], env["ARTIFACT_DIR"], env["AUDIT_KEY"]
                )
                restore(second, tmp / "backup.zip")
                with (
                    original.transaction(write=False) as a,
                    second.transaction(write=False) as b,
                ):
                    assert a.all(run=rid) == b.all(run=rid)
                    for n in a.all("evidence", rid):
                        assert a.read_artifact(n["id"]) == b.read_artifact(n["id"])
                    summary["postgres"] = a.sql("SELECT version() AS v").fetchone()["v"]
                ctl, w = plane()
                summary["restored_new_run"] = audit(client, False)
                summary["gates"] = {
                    "live_model_meeting": "pass",
                    "independent_reproduction": "pass",
                    "approval_and_ticket": "pass",
                    "authenticated_export": "pass",
                    "second_postgres_restore_and_new_run": "pass",
                }
            (out / "live-verification.json").write_text(json.dumps(summary, indent=2))
            print(json.dumps(summary["gates"]), flush=True)
        except Exception:
            for name in ("control", "worker", "lab"):
                path = tmp / (name + ".log")
                if path.exists():
                    print(name, path.read_text()[-2400:], file=sys.stderr)
            raise
        finally:
            for p in reversed(processes):
                stop(p)
            for server in servers:
                server.cleanup()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--chromium", required=True)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--exercise-fallback", action="store_true")
    args = parser.parse_args()
    run_test(
        args.output, args.chromium, args.endpoint, args.model, args.exercise_fallback
    )
