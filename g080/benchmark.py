import json, statistics, time
from api_adapter import fetch_all_pages
from coding_feature import normalize_job_config

def one_page_transport(method, url, payload, headers, timeout):
    return 200, {"items":[{"id":"1"}],"next":None}

def bench(fn, n):
    samples=[]
    for _ in range(n):
        t0=time.perf_counter_ns()
        fn()
        samples.append((time.perf_counter_ns()-t0)/1_000_000)
    s=sorted(samples)
    return {
        "n":n,
        "median_ms":round(statistics.median(s),6),
        "p95_ms":round(s[max(0,int(n*0.95)-1)],6),
        "mean_ms":round(statistics.fmean(s),6),
        "max_ms":round(max(s),6),
    }

coding=bench(lambda: normalize_job_config(
    {"project_id":"P-42","timeout_s":45,"retries":1,"tags":["api","qa"]}
), 10000)
api=bench(lambda: fetch_all_pages(
    one_page_transport, "https://example.invalid/items"
), 5000)
print(json.dumps({"coding_config":coding,"api_one_page":api}, sort_keys=True))
