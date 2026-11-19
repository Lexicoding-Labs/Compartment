"""Controlled integration target. No operator, provider or database credentials."""

import html
import json
import os
import subprocess
import sys
import tempfile
from html.parser import HTMLParser
from pathlib import Path

import httpx
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse

from .engine import PLAYBOOK

app = FastAPI(title="Compartment integration sandbox", docs_url=None)
PRIMARY = {k: PLAYBOOK[k] for k in ("contract", "sample")}


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/spec")
def spec():
    return PRIMARY["contract"]


@app.get("/inventory")
def inventory():
    return PRIMARY["sample"]


@app.get("/inspect", response_class=HTMLResponse)
def page():
    return (
        '<title>Inventory contract fixture</title><pre id="snapshot">'
        + html.escape(json.dumps(PRIMARY))
        + "</pre>"
    )


class Snapshot(HTMLParser):
    def __init__(self):
        super().__init__()
        self.active = False
        self.content = ""

    def handle_starttag(self, tag, attrs):
        if tag == "pre" and dict(attrs).get("id") == "snapshot":
            self.active = True

    def handle_endtag(self, tag):
        if tag == "pre":
            self.active = False

    def handle_data(self, data):
        if self.active:
            self.content += data


def inspect_browser():
    binary = os.environ.get("CHROMIUM", "/usr/bin/chromium")
    with tempfile.TemporaryDirectory() as profile:
        args = [
            binary,
            "--headless",
            "--disable-gpu",
            "--disable-background-networking",
            "--disable-extensions",
            "--disable-dev-shm-usage",
            "--no-first-run",
            "--user-data-dir=" + profile,
            "--dump-dom",
            "http://127.0.0.1:" + os.environ.get("LAB_PORT", "8091") + "/inspect",
        ]
        if os.environ.get("CONTAINER_BROWSER") == "1":
            args.insert(1, "--no-sandbox")
        proc = subprocess.run(args, timeout=30, capture_output=True, check=True)
    parser = Snapshot()
    parser.feed(proc.stdout.decode())
    return json.loads(parser.content)


@app.post("/mcp")
def mcp(
    body: dict,
    x_task: str = Header(default=""),
    authorization: str = Header(default=""),
):
    method = body.get("method")
    rid = body.get("id")
    if method == "initialize":
        result = {
            "protocolVersion": "2025-03-26",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "inventory-lab", "version": "1"},
        }
    elif method == "notifications/initialized":
        from fastapi.responses import Response

        return Response(status_code=202)
    elif method == "tools/list":
        result = {
            "tools": [
                {
                    "name": n,
                    "description": d,
                    "inputSchema": {
                        "type": "object",
                        "properties": {},
                        "additionalProperties": False,
                    },
                }
                for n, d in [
                    ("inventory.inspect", "Read the authorized browser fixture"),
                    (
                        "inventory.verify",
                        "Reproduce the contract check in an isolated Python process",
                    ),
                ]
            ]
        }
    elif method == "tools/call" and not body.get("params", {}).get("arguments"):
        name = body.get("params", {}).get("name")
        decision = httpx.post(
            os.environ["CONTROL_URL"] + "/internal/tool-access",
            json={
                "task": x_task,
                "lease": authorization.removeprefix("Bearer "),
                "tool": name,
            },
            timeout=5,
            trust_env=False,
        )
        if decision.status_code != 200:
            raise HTTPException(403, "Execution capability denied")
        if name == "inventory.inspect":
            output = inspect_browser()
        elif name == "inventory.verify":
            proc = subprocess.run(
                [sys.executable, "-I", str(Path(__file__).with_name("probe.py"))],
                input=json.dumps(PRIMARY),
                capture_output=True,
                text=True,
                timeout=5,
                check=True,
                env={"PATH": "/usr/bin:/bin"},
                cwd=tempfile.gettempdir(),
            )
            output = {"primary": PRIMARY, "findings": json.loads(proc.stdout)}
        else:
            raise HTTPException(400, "Unregistered tool")
        result = {
            "content": [{"type": "text", "text": json.dumps(output)}],
            "isError": False,
        }
    else:
        return {
            "jsonrpc": "2.0",
            "id": rid,
            "error": {"code": -32601, "message": "Unsupported method"},
        }
    return {"jsonrpc": "2.0", "id": rid, "result": result}
