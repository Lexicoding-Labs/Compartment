"""Pure contract checker used by the isolated reference integration."""

import json
import sys


def compare(spec, sample):
    types = {"string": str, "integer": int, "boolean": bool, "number": (int, float)}
    findings = []
    for field in spec["required"]:
        if field not in sample:
            findings.append({"field": field, "error": "missing"})
        elif not isinstance(sample[field], types[spec["types"][field]]) or (
            isinstance(sample[field], bool) and spec["types"][field] != "boolean"
        ):
            findings.append(
                {
                    "field": field,
                    "error": "wrong type",
                    "expected": spec["types"][field],
                    "observed": type(sample[field]).__name__,
                }
            )
    return findings


if __name__ == "__main__":
    payload = json.load(sys.stdin)
    print(json.dumps(compare(payload["contract"], payload["sample"])))
