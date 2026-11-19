"""Promote a local playbook after verified operation evidence and matching regression results."""

import argparse
import hashlib
import json
import zipfile
from pathlib import Path

from .evaluate import ARMS, CASES
from .store import digest, require


def promote(playbook, bundle, evaluation, destination):
    candidate = json.loads(playbook.read_text())
    fingerprint = digest(candidate)
    results = json.loads(evaluation.read_text())
    require(
        results["playbook_digest"] == fingerprint,
        "Evaluation belongs to another playbook",
    )
    rows = [r for r in results["records"] if r["arm"] == ARMS[2]]
    require(
        {r["case"] for r in rows} == {c[0] for c in CASES}
        and all(r["accepted"] for r in rows),
        "Assurance regression suite must pass",
    )
    with zipfile.ZipFile(bundle) as z:
        manifest = json.loads(z.read("manifest.json"))
        nodes = {n["id"]: n for n in manifest["nodes"]}
        run = nodes[manifest["run"]]
        require(
            run["body"]["status"] == "accepted"
            and run["body"]["playbook_digest"] == fingerprint,
            "Accepted run for this version required",
        )
        require(
            nodes[run["body"]["acceptance"]]["kind"] == "acceptance",
            "Missing operator acceptance",
        )
        history = {}
        for n in nodes.values():
            if n["kind"] == "evidence":
                raw = z.read("evidence/" + n["id"] + ".json")
                require(
                    hashlib.sha256(raw).hexdigest() == n["body"]["sha256"],
                    "Evidence integrity failure",
                )
            elif n["kind"] == "task":
                history[n["body"]["step"]] = n["body"]
        require(
            history["verify"]["owner"] != history["correct"]["owner"],
            "Independent review required",
        )
        require(
            json.loads(z.read("evidence/" + history["verify"]["artifact"] + ".json"))[
                "pass"
            ]
            is True,
            "Verification failed",
        )
    entry = {
        "version": candidate["version"],
        "digest": fingerprint,
        "operation": run["id"],
        "evaluation": results["metrics"],
        "operator_invoked_promotion": True,
    }
    with zipfile.ZipFile(destination, "x", zipfile.ZIP_DEFLATED) as out:
        out.write(playbook, "playbook.json")
        out.write(bundle, "reference-evidence.zip")
        out.write(evaluation, "evaluation.json")
        out.writestr("promotion.json", json.dumps(entry, indent=2))
    return entry


if __name__ == "__main__":
    cli = argparse.ArgumentParser()
    for name in ("playbook", "bundle", "evaluation", "destination"):
        cli.add_argument(name, type=Path)
    args = cli.parse_args()
    print(json.dumps(promote(**vars(args)), indent=2))
