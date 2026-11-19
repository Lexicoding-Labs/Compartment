"""Create a private local configuration without overwriting operator settings."""

import os
import secrets
from pathlib import Path


def configure():
    path = Path(".env")
    with os.fdopen(
        os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "w"
    ) as stream:
        for name in (
            "POSTGRES_PASSWORD",
            "OPERATOR_TOKEN",
            "WORKER_TOKEN",
            "TICKET_TOKEN",
            "AUDIT_KEY",
        ):
            stream.write(name + "=" + secrets.token_hex(32) + "\n")
        stream.write("COMPARTMENT_BIND=127.0.0.1\nCOMPARTMENT_PORT=8080\n")
    print(
        "Created .env with owner-only permissions. Read OPERATOR_TOKEN there to sign in."
    )


if __name__ == "__main__":
    configure()
