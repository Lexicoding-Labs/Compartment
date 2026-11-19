"""Release-test fixture: hold an HTTP response after the sandbox has committed it."""

import asyncio
import os
from pathlib import Path

from compartment.tickets import app


@app.middleware("http")
async def hold_response(request, call_next):
    response = await call_next(request)
    marker = Path(os.environ["CRASH_MARKER"])
    if request.method == "PUT" and response.status_code == 200 and marker.exists():
        marker.with_suffix(".committed").touch()
        while marker.exists():
            await asyncio.sleep(0.02)
    return response
