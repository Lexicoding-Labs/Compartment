"""Transactional object and lineage store. Mutating service calls serialize at the control-plane gate."""

import hashlib
import hmac
import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

DDL = [
    "CREATE TABLE IF NOT EXISTS schema_versions (version INTEGER PRIMARY KEY)",
    "CREATE TABLE IF NOT EXISTS control_gate (id INTEGER PRIMARY KEY)",
    """CREATE TABLE IF NOT EXISTS nodes (
        id TEXT PRIMARY KEY, kind TEXT NOT NULL, run TEXT NOT NULL, access TEXT NOT NULL,
        origin TEXT NOT NULL, created DOUBLE PRECISION NOT NULL, body TEXT NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS nodes_run_kind ON nodes(run,kind)",
    """CREATE TABLE IF NOT EXISTS edges (
        src TEXT REFERENCES nodes(id), dst TEXT REFERENCES nodes(id), reason TEXT NOT NULL,
        PRIMARY KEY(src,dst,reason))""",
    "CREATE INDEX IF NOT EXISTS edges_dst ON edges(dst)",
    """CREATE TABLE IF NOT EXISTS journal (
        seq BIGINT PRIMARY KEY, stamp DOUBLE PRECISION NOT NULL, actor TEXT NOT NULL,
        action TEXT NOT NULL, subject TEXT NOT NULL, digest TEXT NOT NULL, signature TEXT NOT NULL)""",
]


def uid():
    return str(uuid.uuid4())


def canonical(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class Fault(Exception):
    def __init__(self, message, code=409):
        super().__init__(message)
        self.code = code


def require(condition, message, code=409):
    if not condition:
        raise Fault(message, code)


class Store:
    def __init__(self, url, artifacts, key):
        self.url, self.directory, self.key = url, Path(artifacts), key.encode()
        self.pg = url.startswith(("postgresql://", "postgres://"))
        self.directory.mkdir(parents=True, exist_ok=True)

    def connect(self):
        if self.pg:
            import psycopg
            from psycopg.rows import dict_row

            return psycopg.connect(self.url, row_factory=dict_row)
        db = sqlite3.connect(self.url, isolation_level=None, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def initialize(self):
        with self.transaction(migrate=True) as tx:
            for statement in DDL:
                tx.sql(statement)
            tx.sql("INSERT INTO control_gate VALUES (1) ON CONFLICT DO NOTHING")
            tx.sql("INSERT INTO schema_versions VALUES (1) ON CONFLICT DO NOTHING")

    @contextmanager
    def transaction(self, *, write=True, migrate=False):
        db = self.connect()
        try:
            tx = Tx(self, db)
            if self.pg:
                if migrate:
                    tx.sql("SELECT pg_advisory_xact_lock(930871)")
                elif write:
                    tx.sql("SELECT id FROM control_gate WHERE id=1 FOR UPDATE")
                else:
                    tx.sql("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            else:
                tx.sql("BEGIN IMMEDIATE" if write else "BEGIN")
            yield tx
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()


class Tx:
    def __init__(self, store, db):
        self.store, self.db = store, db

    def sql(self, sql, args=()):
        return self.db.execute(sql.replace("?", "%s") if self.store.pg else sql, args)

    @staticmethod
    def decode(row):
        return {**dict(row), "body": json.loads(row["body"])}

    def get(self, id, kind=None):
        row = self.sql("SELECT * FROM nodes WHERE id=?", (id,)).fetchone()
        require(
            row and (kind is None or row["kind"] == kind), "Record unavailable", 404
        )
        return self.decode(row)

    def all(self, kind=None, run=None):
        filters, args = [], []
        for name, val in (("kind", kind), ("run", run)):
            if val is not None:
                filters.append(name + "=?")
                args.append(val)
        where = " WHERE " + " AND ".join(filters) if filters else ""
        return [
            self.decode(r)
            for r in self.sql(
                "SELECT * FROM nodes" + where + " ORDER BY created,id", args
            )
        ]

    def add(
        self,
        kind,
        body,
        *,
        run="",
        origin="control",
        access="org",
        id=None,
        parent=None,
        reason="contains",
    ):
        id = id or uid()
        self.sql(
            "INSERT INTO nodes VALUES (?,?,?,?,?,?,?)",
            (id, kind, run, access, origin, time.time(), canonical(body)),
        )
        if parent:
            self.link(parent, id, reason)
        self.audit(origin, "create." + kind, id, body)
        return id

    def change(self, id, actor, **fields):
        node = self.get(id)
        body = {**node["body"], **fields}
        self.sql("UPDATE nodes SET body=? WHERE id=?", (canonical(body), id))
        self.audit(actor, "update." + node["kind"], id, body)
        return body

    def link(self, src, dst, reason):
        inserted = self.sql(
            "INSERT INTO edges VALUES (?,?,?) ON CONFLICT DO NOTHING",
            (src, dst, reason),
        )
        if inserted.rowcount:
            self.audit(
                "control",
                "lineage.link",
                digest([src, dst, reason]),
                [src, dst, reason],
            )

    def audit(self, actor, action, subject, body):
        prev = self.sql(
            "SELECT seq,signature FROM journal ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        seq, previous = (prev["seq"] + 1, prev["signature"]) if prev else (1, "")
        row = [seq, time.time(), actor, action, subject, digest(body)]
        sig = hmac.new(
            self.store.key, canonical([previous, *row]).encode(), "sha256"
        ).hexdigest()
        self.sql("INSERT INTO journal VALUES (?,?,?,?,?,?,?)", (*row, sig))

    def verify_journal(self):
        previous = ""
        expected_nodes = {}
        known_edges = set()
        for i, r in enumerate(self.sql("SELECT * FROM journal ORDER BY seq"), 1):
            row = [
                r[k] for k in ("seq", "stamp", "actor", "action", "subject", "digest")
            ]
            expected = hmac.new(
                self.store.key, canonical([previous, *row]).encode(), "sha256"
            ).hexdigest()
            require(
                r["seq"] == i and hmac.compare_digest(expected, r["signature"]),
                "Audit integrity failure",
            )
            previous = expected
            if r["action"].startswith(("create.", "update.")):
                expected_nodes[r["subject"]] = r["digest"]
            elif r["action"] in ("delete.memory", "expire.memory"):
                expected_nodes.pop(r["subject"], None)
            elif r["action"] == "lineage.link":
                known_edges.add(r["subject"])
        actual = {
            row["id"]: digest(json.loads(row["body"]))
            for row in self.sql("SELECT id,body FROM nodes")
        }
        require(
            expected_nodes == actual, "Stored record differs from its audit history"
        )
        for e in self.sql("SELECT src,dst,reason FROM edges"):
            require(
                digest([e["src"], e["dst"], e["reason"]]) in known_edges,
                "Unrecorded lineage edge",
            )
        return previous

    def artifact(self, run, task, actor, name, content, access="org"):
        data = canonical(content).encode()
        checksum = hashlib.sha256(data).hexdigest()
        path = self.store.directory / checksum
        if not path.exists():
            tmp = self.store.directory / uid()
            with tmp.open("xb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        return self.add(
            "evidence",
            {"name": name, "sha256": checksum, "bytes": len(data)},
            run=run,
            origin=actor,
            access=access,
            parent=task,
            reason="produced evidence",
        )

    def read_artifact(self, id):
        meta = self.get(id, "evidence")["body"]
        raw = (self.store.directory / meta["sha256"]).read_bytes()
        require(
            hashlib.sha256(raw).hexdigest() == meta["sha256"],
            "Artifact integrity failure",
        )
        return raw
