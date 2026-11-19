import concurrent.futures
import io
import json
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from compartment import coordination, engine, governance, org, runtime
from compartment.api import create_app
from compartment.backup import backup, restore
from compartment.lab import PRIMARY
from compartment.probe import compare
from compartment.store import Fault, Store
from compartment.worker import perform

ADMIN = {
    "name": "pilot",
    "project": "pilot",
    "role": "admin",
    "token": "a" * 32,
    "department": "planning",
}
VIEW = {"name": "reader", "project": "pilot", "role": "viewer", "token": "b" * 32}
OTHER = {"name": "other", "project": "other", "role": "operator", "token": "c" * 32}
WORKER = "w" * 32


def fixture(name):
    return (
        PRIMARY
        if name == "inventory.inspect"
        else {
            "primary": PRIMARY,
            "findings": compare(PRIMARY["contract"], PRIMARY["sample"]),
        }
    )


class Harness(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.store = Store(str(root / "db"), root / "files", "test integrity key")
        self.tickets = {}

        def adapter(method, key, params):
            if method == "PUT":
                self.tickets.setdefault(key, {"id": key, "status": "open"})
            return self.tickets.get(key)

        self.api = TestClient(
            create_app(self.store, [ADMIN, VIEW, OTHER], WORKER, [], adapter)
        )
        self.api.__enter__()
        self.addCleanup(self.api.__exit__, None, None, None)
        self.api.headers["Authorization"] = "Bearer " + ADMIN["token"]
        self.worker = {"Authorization": "Bearer " + WORKER}
        self.run = self.post("/api/v1/runs", {})["id"]

    def post(self, path, data, worker=False):
        res = self.api.post(path, json=data, headers=self.worker if worker else {})
        self.assertLess(res.status_code, 300, res.text)
        return res.json()

    def claim(self):
        return self.post("/internal/claim", {"worker": "w"}, True)

    def complete(self, j):
        prefix = "/internal/tasks/" + j["id"]
        result = (
            self.post(prefix + "/dispatch", {"lease": j["lease"]}, True)
            if j["step"] == "ticket"
            else perform(j, fixture)
        )
        self.post(prefix + "/finish", {"lease": j["lease"], "result": result}, True)

    def drain(self):
        for _ in range(40):
            j = self.claim()
            if not j:
                return
            self.complete(j)
        self.fail("Worker did not quiesce")

    def detail(self):
        return self.api.get("/api/v1/runs/" + self.run).json()

    def one(self, kind, step=None):
        return next(
            n
            for n in self.detail()["nodes"]
            if n["kind"] == kind and (not step or n["body"].get("step") == step)
        )

    def authorize(self):
        self.post(
            "/api/v1/pushback/" + self.one("pushback")["id"] + "/resolve",
            {"choice": "request_ticket"},
        )
        t = self.one("task", "ticket")
        self.post("/api/v1/approvals/" + t["id"], t["body"]["action"])
        return t["id"]

    def test_end_to_end_and_bundle(self):
        self.drain()
        self.assertEqual(self.one("task", "ticket")["body"]["state"], "blocked")
        self.assertEqual(self.one("task", "inspect")["body"]["state"], "completed")
        case = self.one("pushback")
        self.assertEqual(
            case["body"]["quotes"], [r["text"] for r in engine.PLAYBOOK["rules"]]
        )
        minutes = self.one("meeting")["body"]["minutes"]
        self.assertEqual(len(minutes["proposals"]), 3)
        self.assertTrue(
            minutes["actions"] and minutes["dissent"] and minutes["outstanding"]
        )
        for step, verdict in [("review", False), ("verify", True)]:
            task = self.one("task", step)
            raw = self.api.get("/api/v1/evidence/" + task["body"]["artifact"]).json()
            self.assertIs(raw["pass"], verdict)
        t = self.authorize()
        self.drain()
        self.assertEqual(list(self.tickets), [t])
        self.post("/api/v1/runs/" + self.run + "/accept", {})
        res = self.api.get("/api/v1/runs/" + self.run + "/bundle")
        self.assertEqual(res.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(res.content)) as z:
            manifest = json.loads(z.read("manifest.json"))
            self.assertTrue(manifest["edges"])
            for n in manifest["nodes"]:
                if n["kind"] == "evidence":
                    import hashlib

                    self.assertEqual(
                        hashlib.sha256(
                            z.read("evidence/" + n["id"] + ".json")
                        ).hexdigest(),
                        n["body"]["sha256"],
                    )
        self.assertTrue(self.api.get("/api/v1/audit/integrity").json()["head"])

    def test_reseed_and_concurrent_claims(self):
        rows = self.api.get("/api/v1/agents").json()
        self.assertEqual(len(rows), 25)
        self.api.put(
            "/api/v1/agents/planning-director",
            json={
                "instructions": "Retain me",
                "available": True,
                "tools": ["assignment.plan"],
            },
        ).raise_for_status()
        with self.store.transaction() as tx:
            org.seed(tx)
        self.assertEqual(
            self.api.get("/api/v1/agents").json()[0]["body"]["instructions"],
            "Retain me",
        )
        with concurrent.futures.ThreadPoolExecutor(4) as pool:
            jobs = list(pool.map(lambda _: self.claim(), range(4)))
        self.assertEqual(sum(bool(j) for j in jobs), 1)

    def test_handoffs_and_timeout(self):
        tid = self.one("task", "plan")["id"]
        with self.store.transaction() as tx:
            for kind in ["ADVICE", "ASSIST", "DELEGATE", "REVIEW", "ESCALATE"]:
                rid = coordination.handoff(
                    tx,
                    tid,
                    "planning-director",
                    "research-s2",
                    kind,
                    "Compare",
                    "Memo",
                    60,
                )
                coordination.reply(tx, rid, "research-s2", "received", "reading")
                if kind == "DELEGATE":
                    cycle = coordination.handoff(
                        tx,
                        tid,
                        "research-s2",
                        "planning-director",
                        kind,
                        "Again",
                        "Memo",
                        60,
                        parent=rid,
                    )
                    self.assertEqual(tx.get(cycle)["kind"], "pushback")
                if kind == "ESCALATE":
                    tx.change(rid, "clock", deadline=0)
                    coordination.expire(tx)
                    self.assertEqual(tx.get(rid)["body"]["status"], "timed_out")
                else:
                    coordination.reply(tx, rid, "research-s2", "answered", "Done")
            limit = coordination.handoff(
                tx,
                tid,
                "planning-director",
                "research-s1",
                "ADVICE",
                "Compare",
                "Memo",
                60,
            )
            self.assertEqual(tx.get(limit)["kind"], "pushback")
        self.assertTrue(self.one("escalation"))

    def test_approval_fencing(self):
        self.drain()
        case = self.one("pushback")
        self.post(
            "/api/v1/pushback/" + case["id"] + "/resolve", {"choice": "request_ticket"}
        )
        t = self.one("task", "ticket")
        self.assertIsNone(self.claim())
        wrong = {**t["body"]["action"], "target": "another project"}
        self.assertEqual(
            self.api.post("/api/v1/approvals/" + t["id"], json=wrong).status_code, 409
        )
        self.assertEqual(
            self.api.post(
                "/api/v1/approvals/" + t["id"],
                json=t["body"]["action"],
                headers=self.worker,
            ).status_code,
            401,
        )
        self.post("/api/v1/approvals/" + t["id"], t["body"]["action"])
        j = self.claim()
        with self.store.transaction() as tx:
            tx.change("policy", "admin", disabled_tools=["ticket.create"])
        res = self.api.post(
            "/internal/tasks/" + j["id"] + "/dispatch",
            headers=self.worker,
            json={"lease": j["lease"]},
        )
        self.assertEqual(res.status_code, 403)
        self.assertFalse(self.tickets)

    def test_crashes_before_and_after_effect(self):
        self.drain()
        tid = self.authorize()
        for after in (False, True):
            self.claim()
            if after:
                # Adapter committed just before the control process lost its transaction.
                self.tickets[tid] = {"id": tid, "status": "open"}
            with self.store.transaction() as tx:
                tx.change(tid, "clock", lease_until=0)
            self.assertIsNone(self.claim())
            self.assertEqual(self.one("task", "ticket")["body"]["state"], "blocked")
            self.assertEqual(
                self.post("/api/v1/tasks/" + tid + "/reconcile", {})["found"], after
            )
            if not after:
                self.assertIsNone(self.claim())
                self.post(
                    "/api/v1/approvals/" + tid,
                    self.one("task", "ticket")["body"]["action"],
                )
        self.assertEqual(self.detail()["run"]["body"]["status"], "awaiting acceptance")

    def test_visibility_and_retention(self):
        path = "/api/v1/runs/" + self.run
        secret = self.post(
            path + "/memory",
            {
                "scope": "department",
                "owner": "planning",
                "claim": "private plan",
                "source": "operator review",
                "confidence": "correction",
            },
        )["id"]
        viewer = {"Authorization": "Bearer " + VIEW["token"]}
        self.assertFalse(
            self.api.get(path + "/search?q=private", headers=viewer).json()
        )
        self.assertNotIn(secret, self.api.get(path, headers=viewer).text)
        self.assertEqual(
            self.api.get(
                path, headers={"Authorization": "Bearer " + OTHER["token"]}
            ).status_code,
            404,
        )
        self.assertEqual(
            self.api.post("/api/v1/runs", json={}, headers=viewer).status_code, 403
        )
        self.assertEqual(
            self.api.post(
                path + "/meetings",
                json={
                    "agenda": "Discuss",
                    "participants": ["planning-rep", "execution-rep"],
                    "context": [secret],
                },
            ).status_code,
            403,
        )
        with self.store.transaction() as tx:
            tx.change(secret, "clock", expires=0)
            runtime.sweep(tx)
        self.assertFalse(self.api.get(path + "/search?q=private").json())
        removable = self.post(
            path + "/memory",
            {
                "scope": "org",
                "claim": "removable decision",
                "source": "operator correction",
                "confidence": "correction",
            },
        )["id"]
        self.api.delete("/api/v1/memory/" + removable).raise_for_status()
        self.assertFalse(self.api.get(path + "/search?q=removable").json())
        self.assertNotIn(removable, self.api.get(path).text)

    def test_schedule_and_meeting_deduplication(self):
        self.assertEqual(
            self.post("/api/v1/triggers/repeat", {})["id"],
            self.post("/api/v1/triggers/repeat", {})["id"],
        )
        self.post("/api/v1/schedules", {"interval": 60, "due": time.time() - 122})
        with self.store.transaction() as tx:
            governance.tick(tx, "fixture")
            governance.tick(tx, "fixture")
            self.assertEqual(len(tx.all("run")), 3)
        self.drain()
        m = self.one("meeting")
        with self.store.transaction() as tx:
            before = len(tx.all("task", self.run))
            self.assertEqual(
                coordination.close_meeting(tx, m["id"], [], []), m["body"]["minutes"]
            )
            self.assertEqual(before, len(tx.all("task", self.run)))

    def test_backup_restore_and_tamper(self):
        self.drain()
        path = Path(self.tmp.name) / "snapshot.zip"
        backup(self.store, path)
        second = Store(
            str(Path(self.tmp.name) / "second"),
            Path(self.tmp.name) / "secondfiles",
            "test integrity key",
        )
        restore(second, path)
        with self.store.transaction(write=False) as x, second.transaction() as y:
            self.assertEqual(
                [n["id"] for n in x.all("task")], [n["id"] for n in y.all("task")]
            )
            for n in x.all("evidence"):
                self.assertEqual(x.read_artifact(n["id"]), y.read_artifact(n["id"]))
            y.sql("UPDATE journal SET digest='tampered' WHERE seq=1")
            with self.assertRaises(Fault):
                y.verify_journal()
        with self.assertRaises(Fault):
            restore(second, path)

    def test_model_caps_and_independent_slots(self):
        with self.store.transaction() as tx:
            tx.change(self.run, "test", model_mode="live")
        self.complete(self.claim())
        with self.store.transaction() as tx:
            tx.change("policy", "admin", budget_microusd=5)
            route = {
                "name": "p",
                "model": "m",
                "charge": 6,
                "capabilities": ["meeting"],
            }
            for _ in range(5):
                j = runtime.claim(tx, "w", [route])
                if not j:
                    break
            self.assertEqual(
                engine.by_step(tx, self.run, "meeting")["body"]["state"], "blocked"
            )
            self.assertFalse(tx.all("reservation"))
            self.assertLessEqual(
                sum(t["body"]["state"] == "running" for t in tx.all("task")), 3
            )

    def test_worker_requests_advice_and_resumes(self):
        while True:
            job = self.claim()
            if job["step"] == "draft":
                break
            self.complete(job)
        req = self.post(
            "/internal/tasks/" + job["id"] + "/requests",
            {
                "lease": job["lease"],
                "recipient": "research-s2",
                "kind": "ADVICE",
                "scope": "Which types matter?",
                "output": "One scoped check",
                "seconds": 60,
                "wait": True,
            },
            True,
        )
        self.assertEqual(self.one("task", "draft")["body"]["state"], "waiting")
        child = self.claim()
        self.assertEqual(child["step"], "peer")
        self.complete(child)
        self.assertEqual(self.one("task", "draft")["body"]["state"], "queued")
        with self.store.transaction(write=False) as tx:
            self.assertEqual(tx.get(req["id"])["body"]["status"], "answered")

    def test_model_routing_and_slot_reservations(self):
        self.complete(self.claim())
        with self.store.transaction() as tx:
            tx.change(self.run, "test", model_mode="live")
            tx.change("policy", "admin", model_slots=1, workers=6)
            all_tasks = tx.all("task", self.run)
            for t in all_tasks:
                if t["body"]["step"] not in ("meeting", "plan"):
                    tx.change(t["id"], "test", state="waiting")
            governance.extra_meeting(
                tx,
                self.run,
                ["research-rep", "reliability-rep"],
                "Check evidence",
                [],
                "ad hoc",
            )
            routes = [
                {"name": k, "model": k, "charge": 10, "capabilities": ["meeting"]}
                for k in ("primary", "fallback")
            ]
            first = runtime.claim(tx, "worker-a", routes)
            self.assertEqual(first["route"]["name"], "primary")
            self.assertIsNone(runtime.claim(tx, "worker-b", routes))
            runtime.failure(tx, first["id"], first["lease"], "Provider timeout")
            tx.change(first["id"], "clock", after=0)
            second = runtime.claim(tx, "worker-b", routes)
            self.assertEqual(second["route"]["name"], "fallback")
            self.assertEqual(second["id"], first["id"])
            self.assertEqual(
                sum(r["body"]["amount"] for r in tx.all("reservation")), 20
            )

    def test_tool_boundary_rates_and_intervention(self):
        self.complete(self.claim())
        job = self.claim()
        self.assertEqual(job["step"], "inspect")
        tool = {"task": job["id"], "lease": job["lease"], "tool": "inventory.inspect"}
        self.assertEqual(
            self.api.post(
                "/internal/tool-access", json={**tool, "tool": "inventory.verify"}
            ).status_code,
            403,
        )
        with self.store.transaction() as tx:
            tx.change("tool/contract.read", "admin", calls_per_minute=1)
        self.post("/internal/tool-access", tool)
        self.assertEqual(
            self.api.post("/internal/tool-access", json=tool).status_code, 429
        )
        policy = self.api.get("/api/v1/overview").json()["policy"]
        self.api.put(
            "/api/v1/policy", json={**policy, "stopped": True}
        ).raise_for_status()
        self.assertEqual(self.detail()["run"]["body"]["status"], "paused")
        self.assertEqual(
            self.api.post("/internal/tool-access", json=tool).status_code, 409
        )
        self.assertIsNone(self.claim())
        self.api.put(
            "/api/v1/policy", json={**policy, "stopped": False}
        ).raise_for_status()
        self.post("/api/v1/runs/" + self.run + "/intervene", {"command": "resume"})
        self.post("/api/v1/runs/" + self.run + "/intervene", {"command": "checkpoint"})
        self.assertTrue(self.one("checkpoint"))

    def test_time_limited_acting_identity_has_own_permissions(self):
        with self.store.transaction() as tx:
            pos = "planning-director"
            agent = "planning-s2"
            tx.change(pos, "operator", available=False)
            org.appoint(tx, pos, agent, time.time() + 60, time.time(), "pilot")
            self.assertEqual(org.holder(tx, pos, time.time()), agent)
            self.assertEqual(org.holder(tx, pos, time.time() + 100), pos)
            self.assertIsNone(runtime.claim(tx, "worker"))
            self.assertEqual(
                engine.by_step(tx, self.run, "plan")["body"]["state"], "blocked"
            )
            with self.assertRaises(Fault):
                coordination.handoff(
                    tx,
                    engine.by_step(tx, self.run, "plan")["id"],
                    pos,
                    agent,
                    "DELEGATE",
                    "write a ticket",
                    "receipt",
                    30,
                    ["ticket.create"],
                )

    def test_scope_decision_and_local_atlas(self):
        r = self.post("/api/v1/runs", {"objective": "Update a different integration."})[
            "id"
        ]
        detail = self.api.get("/api/v1/runs/" + r).json()
        case = next(n for n in detail["nodes"] if n["kind"] == "pushback")
        self.post(
            "/api/v1/pushback/" + case["id"] + "/resolve",
            {"choice": "cancel_operation"},
        )
        self.assertEqual(
            self.api.get("/api/v1/runs/" + r).json()["run"]["body"]["status"],
            "cancelled",
        )
        data = {
            "classification": "correct detection",
            "root_cause": "Named target outside playbook",
            "regression": "Retain scope hold",
            "resolution": "Operator cancelled",
        }
        url = "/api/v1/pushback/" + case["id"] + "/adjudicate"
        self.assertEqual(self.api.post(url, json=data).status_code, 422)
        self.post(url, {**data, "consent_local_atlas": True})
        self.assertEqual(len(self.api.get("/api/v1/atlas").json()), 1)

    def test_operator_default_for_missing_instruction(self):
        rid = self.post("/api/v1/runs", {"rules": [], "missing_ticket": "omit"})["id"]
        with self.store.transaction() as tx:
            plan = engine.by_step(tx, rid, "plan")
            engine.allocate(tx, rid, plan["id"])
            self.assertEqual(
                engine.by_step(tx, rid, "ticket")["body"]["state"], "completed"
            )
            self.assertEqual(
                tx.all("assumption", rid)[0]["body"]["basis"],
                "operator-authorized default",
            )

    def test_semantic_challenge_holds_only_ticket(self):
        with self.store.transaction() as tx:
            first = tx.all("requirement", self.run)[0]
            tx.change(first["id"], "test", effect="hold")
        self.complete(self.claim())
        while True:
            job = self.claim()
            if job["step"] == "meeting":
                self.post(
                    "/internal/tasks/" + job["id"] + "/finish",
                    {
                        "lease": job["lease"],
                        "result": {
                            "model": "bounded reviewer",
                            "position": "dissent",
                            "statement": "Timing requirements conflict",
                            "conflict_indices": [0, 1],
                        },
                    },
                    True,
                )
                break
            self.complete(job)
        challenge = next(
            n
            for n in self.detail()["nodes"]
            if n["kind"] == "pushback"
            and n["body"]["category"] == "semantic disagreement"
        )
        self.assertEqual(len(challenge["body"]["quotes"]), 2)
        self.assertEqual(self.one("task", "ticket")["body"]["state"], "blocked")
        self.drain()
        self.assertEqual(self.one("task", "verify")["body"]["state"], "completed")

    def test_cross_task_wait_cycle_and_depth(self):
        self.complete(self.claim())
        with self.store.transaction() as tx:
            # The producer already owes a response to Research. A reciprocal wait would deadlock.
            draft = engine.by_step(tx, self.run, "draft")
            cyc = coordination.handoff(
                tx,
                draft["id"],
                draft["body"]["owner"],
                "research-s1",
                "ASSIST",
                "Check",
                "Findings",
                60,
            )
            self.assertEqual(tx.get(cyc)["body"]["question"], "Circular delegation")
            tx.change("policy", "test", depth=1)
            tid = engine.by_step(tx, self.run, "plan")["id"]
            req = coordination.handoff(
                tx,
                tid,
                "planning-director",
                "research-s2",
                "ADVICE",
                "Scope",
                "Memo",
                60,
            )
            limit = coordination.handoff(
                tx,
                tid,
                "research-s2",
                "quality-s2",
                "ADVICE",
                "Scope",
                "Memo",
                60,
                parent=req,
            )
            self.assertEqual(
                tx.get(limit)["body"]["question"], "Delegation limit exceeded"
            )

    def test_representative_chat_private_durable_and_idempotent(self):
        import uuid

        url = "/api/v1/representatives/planning-rep/messages"
        body = {"message": "Who handles intake?", "client_id": str(uuid.uuid4())}
        rid = self.post(url, body)["id"]
        self.assertEqual(self.post(url, body)["id"], rid)
        self.assertEqual(
            self.api.post(url, json={**body, "message": "Changed"}).status_code, 409
        )
        self.assertEqual(
            self.api.post(
                url, json={**body, "client_id": str(uuid.uuid4())}
            ).status_code,
            409,
        )
        self.assertEqual(
            self.api.post(
                url.replace("planning-rep", "planning-director"), json=body
            ).status_code,
            422,
        )
        self.assertEqual(
            self.api.post(
                url, json=body, headers={"Authorization": "Bearer " + VIEW["token"]}
            ).status_code,
            403,
        )
        self.drain()
        turn = self.api.get(url).json()[0]
        self.assertEqual(turn["state"], "completed")
        self.assertEqual(turn["speaker"], "planning-rep")
        self.assertIn("Planning & Coordination", turn["reply"])
        self.assertEqual(
            self.api.get(
                url, headers={"Authorization": "Bearer " + VIEW["token"]}
            ).json(),
            [],
        )
        self.assertEqual(
            self.api.get(url.replace("planning-rep", "quality-rep")).json(), []
        )
        self.assertNotIn(
            rid, [r["id"] for r in self.api.get("/api/v1/overview").json()["runs"]]
        )
        self.assertEqual(
            self.api.get(
                "/api/v1/runs/" + rid,
                headers={"Authorization": "Bearer " + VIEW["token"]},
            ).status_code,
            404,
        )
        self.assertIn("planning-rep", self.api.get("/api/v1/overview").json()["inbox"])
        self.assertFalse(
            self.api.get(
                "/api/v1/overview", headers={"Authorization": "Bearer " + VIEW["token"]}
            ).json()["inbox"]
        )

    def test_record_tamper_is_detected(self):
        with self.store.transaction() as tx:
            tx.sql("UPDATE nodes SET body='{}' WHERE id='policy'")
            with self.assertRaisesRegex(Fault, "differs"):
                tx.verify_journal()


if __name__ == "__main__":
    unittest.main()
