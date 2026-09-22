"""Deterministic baseline-vs-guarded mechanism comparison for G-080."""
from api_adapter import fetch_all_pages, post_json
from coding_feature import normalize_job_config

def naive_config(raw):
    out={"timeout_s":30,"retries":2,"tags":[]}
    out.update(raw)
    return out

def naive_fetch(transport, endpoint):
    status, body = transport("GET", endpoint, {}, {}, 10)
    if status != 200:
        raise RuntimeError(status)
    return body.get("items", [])

class QueueTransport:
    def __init__(self, responses):
        self.responses=list(responses)
        self.calls=[]
    def __call__(self, method, url, payload, headers, timeout):
        self.calls.append((method,url,payload,dict(headers),timeout))
        return self.responses.pop(0)

def coding_baseline_errors():
    errors=0
    # Unsafe baseline accepts unknown execution key.
    if "shell" in naive_config({"project_id":"P","shell":"danger"}):
        errors += 1
    # Unsafe baseline accepts invalid timeout/retry.
    if naive_config({"project_id":"P","timeout_s":0})["timeout_s"] == 0:
        errors += 1
    if naive_config({"project_id":"P","retries":99})["retries"] == 99:
        errors += 1
    return errors

def coding_guarded_errors():
    errors=0
    for payload in (
        {"project_id":"P","shell":"danger"},
        {"project_id":"P","timeout_s":0},
        {"project_id":"P","retries":99},
    ):
        try:
            normalize_job_config(payload)
            errors += 1
        except ValueError:
            pass
    return errors

def api_baseline_errors():
    errors=0
    # 429 is not recovered.
    try:
        naive_fetch(QueueTransport([(429,{}),(200,{"items":[1],"next":None})]),
                    "https://example.invalid/items")
        errors += 1
    except RuntimeError:
        pass
    # Pagination is silently truncated.
    got=naive_fetch(QueueTransport([(200,{"items":[1],"next":"p2"})]),
                    "https://example.invalid/items")
    if got == [1]:
        errors += 1
    # No cursor-loop, schema, HTTPS or idempotency enforcement in baseline.
    errors += 4
    return errors

def api_guarded_errors():
    errors=0
    t=QueueTransport([(429,{}),(200,{"items":[1],"next":None})])
    if fetch_all_pages(t,"https://example.invalid/items")["items"] != [1]:
        errors += 1
    t=QueueTransport([(503,{}),(201,{"id":"x"})])
    if post_json(t,"https://example.invalid/crm",{},idempotency_key="k")["id"]!="x":
        errors += 1
    for fn in (
        lambda: fetch_all_pages(QueueTransport([(200,{"items":[],"next":"a"}),(200,{"items":[],"next":"a"})]),"https://example.invalid/items"),
        lambda: fetch_all_pages(QueueTransport([(200,{"items":"bad","next":None})]),"https://example.invalid/items"),
        lambda: fetch_all_pages(QueueTransport([]),"http://example.invalid/items"),
        lambda: post_json(QueueTransport([]),"https://example.invalid/crm",{},idempotency_key=""),
    ):
        try:
            fn()
            errors += 1
        except (ValueError, RuntimeError):
            pass
    return errors

if __name__=="__main__":
    result={
        "coding":{"baseline_errors":coding_baseline_errors(),"guarded_errors":coding_guarded_errors()},
        "api":{"baseline_errors":api_baseline_errors(),"guarded_errors":api_guarded_errors()},
    }
    print(result)
    assert result["coding"] == {"baseline_errors":3,"guarded_errors":0}
    assert result["api"] == {"baseline_errors":6,"guarded_errors":0}
