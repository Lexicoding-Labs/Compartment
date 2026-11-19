"""Interrupt the actual HTTP control process on both sides of a real sandbox effect."""

import concurrent.futures
import sqlite3
import time
from pathlib import Path

import httpx


def exercise(client, env, store, control, worker, stop, start_control):
    run = client.post("/api/v1/runs", json={}).raise_for_status().json()["id"]
    until = time.monotonic() + 150
    while time.monotonic() < until:
        d = client.get("/api/v1/runs/" + run).raise_for_status().json()
        tasks = [n for n in d["nodes"] if n["kind"] == "task"]
        if (
            tasks
            and any(t["body"]["step"] == "verify" for t in tasks)
            and all(
                t["body"]["state"] == "completed"
                for t in tasks
                if t["body"]["step"] != "ticket"
            )
        ):
            break
        time.sleep(0.2)
    else:
        raise AssertionError("Timed out preparing crash fixture")
    stop(worker)
    c = next(
        n
        for n in d["nodes"]
        if n["kind"] == "pushback"
        and n["body"]["category"] == "incompatible requirements"
    )
    t = next(t for t in tasks if t["body"]["step"] == "ticket")
    client.post(
        "/api/v1/pushback/" + c["id"] + "/resolve", json={"choice": "request_ticket"}
    ).raise_for_status()
    with httpx.Client(
        base_url=env["CONTROL_URL"],
        headers={"Authorization": "Bearer " + env["WORKER_TOKEN"]},
        timeout=12,
        trust_env=False,
    ) as w:
        for stage in ("before dispatch", "after external commit"):
            client.post(
                "/api/v1/approvals/" + t["id"], json=t["body"]["action"]
            ).raise_for_status()
            job = (
                w.post("/internal/claim", json={"worker": "crash-gate"})
                .raise_for_status()
                .json()
            )
            assert job["step"] == "ticket"
            pool = None
            marker = Path(env["CRASH_MARKER"])
            if stage == "after external commit":
                marker.touch()
                pool = concurrent.futures.ThreadPoolExecutor(1)
                inflight = pool.submit(
                    w.post,
                    "/internal/tasks/" + t["id"] + "/dispatch",
                    json={"lease": job["lease"]},
                )
                deadline = time.monotonic() + 6
                while not marker.with_suffix(".committed").exists():
                    if time.monotonic() > deadline:
                        raise AssertionError("External commit did not occur")
                    time.sleep(0.02)
            control.kill()
            control.wait(10)
            if pool:
                marker.unlink()
                try:
                    inflight.result(3)
                except httpx.RequestError:
                    pass
                pool.shutdown()
            # Advance only the lease deadline so this test needs no three-minute sleep.
            with store.transaction() as tx:
                tx.change(t["id"], "release-test-clock", lease_until=0)
            control = start_control()
            assert (
                w.post("/internal/claim", json={"worker": "recovered"})
                .raise_for_status()
                .json()
                is None
            )
            result = (
                client.post("/api/v1/tasks/" + t["id"] + "/reconcile")
                .raise_for_status()
                .json()
            )
            assert result["found"] == (stage == "after external commit")
    with sqlite3.connect(env["TICKET_DB"]) as external:
        assert (
            external.execute(
                "SELECT count(*) FROM tickets WHERE key=?", (t["id"],)
            ).fetchone()[0]
            == 1
        )
    client.post("/api/v1/runs/" + run + "/accept").raise_for_status()
    return control, {
        "before_dispatch": "pass",
        "after_external_commit_before_control_commit": "pass",
        "automatic_redispatches": 0,
        "external_tickets": 1,
        "lease_expiry": "advanced by test clock",
    }
