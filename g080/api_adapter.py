"""Synthetic G-080 REST adapter fixture.

No network, no credentials, standard-library only. The caller supplies a transport
so contract behavior is deterministic and testable.
"""
from __future__ import annotations

RETRYABLE = {429, 500, 502, 503, 504}

def _call_with_retry(transport, method, url, *, payload=None, headers=None,
                     timeout_s=10, max_retries=2):
    attempts = 0
    while True:
        status, response = transport(method, url, payload or {}, headers or {}, timeout_s)
        if status in RETRYABLE and attempts < max_retries:
            attempts += 1
            continue
        if status < 200 or status >= 300:
            raise RuntimeError(f"api status {status}")
        if not isinstance(response, dict):
            raise ValueError("response must be an object")
        return response, attempts + 1

def fetch_all_pages(transport, endpoint: str, *, timeout_s=10, max_pages=10,
                    max_retries=2):
    if not endpoint.startswith("https://"):
        raise ValueError("https endpoint required")
    cursor = None
    seen = set()
    items = []
    calls = 0
    for _ in range(max_pages):
        url = endpoint if cursor is None else f"{endpoint}?cursor={cursor}"
        body, used = _call_with_retry(
            transport, "GET", url, timeout_s=timeout_s, max_retries=max_retries
        )
        calls += used
        page_items = body.get("items")
        next_cursor = body.get("next")
        if not isinstance(page_items, list):
            raise ValueError("items must be a list")
        if next_cursor is not None and not isinstance(next_cursor, str):
            raise ValueError("next must be string or null")
        items.extend(page_items)
        if next_cursor is None:
            return {"items": items, "calls": calls}
        if next_cursor in seen:
            raise RuntimeError("pagination cursor loop")
        seen.add(next_cursor)
        cursor = next_cursor
    raise RuntimeError("max_pages exceeded")

def post_json(transport, endpoint: str, payload: dict, *, idempotency_key: str,
              timeout_s=10, max_retries=2):
    if not endpoint.startswith("https://"):
        raise ValueError("https endpoint required")
    if not isinstance(payload, dict):
        raise TypeError("payload must be object")
    if not isinstance(idempotency_key, str) or not idempotency_key.strip():
        raise ValueError("idempotency_key required")
    headers = {
        "Content-Type": "application/json",
        "Idempotency-Key": idempotency_key.strip(),
    }
    body, calls = _call_with_retry(
        transport, "POST", endpoint, payload=payload, headers=headers,
        timeout_s=timeout_s, max_retries=max_retries
    )
    if not isinstance(body.get("id"), str) or not body["id"]:
        raise ValueError("response id required")
    return {"id": body["id"], "calls": calls}
