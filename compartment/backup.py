"""Portable authenticated snapshot. Restore requires a fresh database and the source audit key."""

import argparse
import hashlib
import hmac
import json
import os
import zipfile
from pathlib import Path

from .store import Store, canonical, require

TABLES = {
    "schema_versions": ["version"],
    "nodes": ["id", "kind", "run", "access", "origin", "created", "body"],
    "edges": ["src", "dst", "reason"],
    "journal": ["seq", "stamp", "actor", "action", "subject", "digest", "signature"],
}


def backup(store, path):
    with store.transaction(write=False) as tx:
        head = tx.verify_journal()
        rows = {t: [dict(r) for r in tx.sql("SELECT * FROM " + t)] for t in TABLES}
        manifest = canonical({"format": 1, "head": head, "tables": rows}).encode()
        with zipfile.ZipFile(path, "x", zipfile.ZIP_DEFLATED) as z:
            z.writestr("snapshot.json", manifest)
            z.writestr("signature", hmac.new(store.key, manifest, "sha256").hexdigest())
            seen = set()
            for n in tx.all("evidence"):
                checksum = n["body"]["sha256"]
                if checksum not in seen:
                    z.writestr("artifacts/" + checksum, tx.read_artifact(n["id"]))
                    seen.add(checksum)


def restore(store, path):
    store.initialize()
    with zipfile.ZipFile(path) as z, store.transaction() as tx:
        require(
            not tx.all() and not tx.sql("SELECT 1 FROM journal").fetchone(),
            "Restore target must be empty",
        )
        raw = z.read("snapshot.json")
        require(
            hmac.compare_digest(
                z.read("signature").decode(),
                hmac.new(store.key, raw, "sha256").hexdigest(),
            ),
            "Invalid snapshot signature",
        )
        data = json.loads(raw)
        require(
            data["format"] == 1
            and data["tables"]["schema_versions"] == [{"version": 1}],
            "Unsupported snapshot",
        )
        for name in ("nodes", "edges", "journal"):
            cols = TABLES[name]
            q = (
                "INSERT INTO "
                + name
                + " ("
                + ",".join(cols)
                + ") VALUES ("
                + ",".join("?" for _ in cols)
                + ")"
            )
            for row in data["tables"][name]:
                tx.sql(q, [row[c] for c in cols])
        require(tx.verify_journal() == data["head"], "Audit head mismatch")
        for n in tx.all("evidence"):
            checksum = n["body"]["sha256"]
            raw = z.read("artifacts/" + checksum)
            require(
                hashlib.sha256(raw).hexdigest() == checksum, "Artifact digest mismatch"
            )
            dest = store.directory / checksum
            dest.write_bytes(raw)
        from .runtime import intervene

        for r in tx.all("run"):
            if r["body"]["status"] == "active":
                intervene(tx, r["id"], "restore", "pause")
        for s in tx.all("schedule"):
            if s["body"]["enabled"]:
                tx.change(s["id"], "restore", enabled=False)
        tx.audit("restore", "snapshot.verified", "policy", {"head": data["head"]})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["backup", "restore"])
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    store = Store(
        os.environ["DATABASE_URL"], os.environ["ARTIFACT_DIR"], os.environ["AUDIT_KEY"]
    )
    (backup if args.action == "backup" else restore)(store, args.archive)


if __name__ == "__main__":
    main()
