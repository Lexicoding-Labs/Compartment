"""Idempotent external fixture, isolated from browser and model workers."""

import json
import os
import secrets
import sqlite3

from fastapi import FastAPI, Header, HTTPException

app = FastAPI(title="Compartment sandbox ticket service", docs_url=None)


@app.get("/health")
def health():
    return {"ok": True}


def ticket_db(auth):
    secret = os.environ.get("TICKET_TOKEN", "")
    if not secret or not secrets.compare_digest(auth, "Bearer " + secret):
        raise HTTPException(403)
    db = sqlite3.connect(os.environ["TICKET_DB"])
    db.execute(
        "CREATE TABLE IF NOT EXISTS tickets (key TEXT PRIMARY KEY, params TEXT NOT NULL)"
    )
    return db


@app.put("/tickets/{key}")
def ticket(key: str, body: dict, authorization: str = Header(default="")):
    db = ticket_db(authorization)
    try:
        raw = json.dumps(body, sort_keys=True)
        with db:
            db.execute("INSERT OR IGNORE INTO tickets VALUES (?,?)", (key, raw))
            if (
                db.execute("SELECT params FROM tickets WHERE key=?", (key,)).fetchone()[
                    0
                ]
                != raw
            ):
                raise HTTPException(409, "Idempotency key mismatch")
        return {"id": key, "status": "open", "target": "sandbox/integration-tickets"}
    finally:
        db.close()


@app.get("/tickets/{key}")
def lookup(key: str, authorization: str = Header(default="")):
    db = ticket_db(authorization)
    try:
        if not db.execute("SELECT 1 FROM tickets WHERE key=?", (key,)).fetchone():
            raise HTTPException(404)
        return {"id": key, "status": "open", "target": "sandbox/integration-tickets"}
    finally:
        db.close()
