import os
import time
import uuid

import worker
from fastapi import Request

app = worker.app
ACTIVITY_FILE = worker.WORK / "last_inference_activity"
INFLIGHT_DIR = worker.WORK / "inflight_requests"
INFLIGHT_DIR.mkdir(parents=True, exist_ok=True)


def touch_activity() -> None:
    tmp = ACTIVITY_FILE.with_name(f".{ACTIVITY_FILE.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(str(time.time()), encoding="utf-8")
    tmp.replace(ACTIVITY_FILE)


@app.middleware("http")
async def track_authenticated_inference(request: Request, call_next):
    # Health probes must never keep a GPU session alive. Only authenticated
    # /v1 traffic counts as real use.
    key = os.environ.get("PROXY_API_KEY", "")
    authenticated_v1 = (
        request.url.path.startswith("/v1/")
        and bool(key)
        and request.headers.get("authorization") == f"Bearer {key}"
    )
    if not authenticated_v1:
        return await call_next(request)

    marker = INFLIGHT_DIR / f"{os.getpid()}-{uuid.uuid4().hex}"
    marker.write_text("1", encoding="utf-8")
    touch_activity()
    try:
        return await call_next(request)
    finally:
        touch_activity()
        try:
            marker.unlink()
        except FileNotFoundError:
            pass
