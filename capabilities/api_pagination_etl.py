#!/usr/bin/env python3
"""SKILL-040 1.1 public-safe API pagination/ETL fixture."""
from __future__ import annotations
import argparse, csv, json, os, statistics, tempfile, time
import urllib.error, urllib.parse, urllib.request
from pathlib import Path

class TransientFetchError(RuntimeError): pass
class PermanentFetchError(RuntimeError): pass

def collect(fetch_page, start=1, id_field="id", max_pages=100, max_retries=2):
    if max_pages < 1 or max_retries < 0: raise ValueError("invalid_limits")
    records, rejected, seen_ids, seen_tokens = [], [], set(), set()
    pages = retries = duplicates = 0
    token = start
    while token is not None:
        tk = json.dumps(token, sort_keys=True, default=str)
        if tk in seen_tokens: raise PermanentFetchError("pagination_cycle")
        if pages >= max_pages: raise PermanentFetchError("max_pages_exceeded")
        seen_tokens.add(tk)
        attempts = 0
        while True:
            try:
                page = fetch_page(token); break
            except TransientFetchError:
                if attempts >= max_retries: raise
                attempts += 1; retries += 1
        if not isinstance(page, dict) or not isinstance(page.get("items"), list):
            raise PermanentFetchError("malformed_page")
        pages += 1
        for row in page["items"]:
            if not isinstance(row, dict) or id_field not in row or row[id_field] in (None, ""):
                rejected.append(("schema", row)); continue
            key = str(row[id_field])
            if key in seen_ids:
                duplicates += 1; rejected.append(("duplicate_id", row)); continue
            seen_ids.add(key); records.append(row)
        token = page.get("next")
    return {"records": records, "rejected": rejected, "pages": pages, "retries": retries, "duplicates": duplicates}

def write_csv(records, path):
    records = list(records)
    if not records: Path(path).write_text("", encoding="utf-8"); return
    fields = sorted({k for row in records for k in row})
    with Path(path).open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(records)

def http_fetcher(url_template, bearer_env=None, timeout=15):
    if "{page}" not in url_template: raise ValueError("missing_page_placeholder")
    parsed = urllib.parse.urlparse(url_template.replace("{page}", "1"))
    if parsed.scheme not in {"http","https"} or not parsed.netloc: raise ValueError("absolute_http_url_required")
    if parsed.username or parsed.password: raise ValueError("credentials_in_url_forbidden")
    def fetch(page):
        headers={"Accept":"application/json","User-Agent":"g080-api-etl/1"}
        if bearer_env:
            token=os.environ.get(bearer_env)
            if not token: raise PermanentFetchError("missing_bearer_env")
            headers["Authorization"]="Bearer "+token
        req=urllib.request.Request(url_template.format(page=urllib.parse.quote(str(page),safe="")),headers=headers)
        try:
            with urllib.request.urlopen(req,timeout=timeout) as resp: raw=resp.read()
        except urllib.error.HTTPError as e:
            if e.code==429 or e.code>=500: raise TransientFetchError("http_"+str(e.code)) from e
            raise PermanentFetchError("http_"+str(e.code)) from e
        except (urllib.error.URLError,TimeoutError) as e: raise TransientFetchError(type(e).__name__) from e
        try: data=json.loads(raw)
        except json.JSONDecodeError as e: raise PermanentFetchError("invalid_json") from e
        if not isinstance(data,dict): raise PermanentFetchError("json_root_not_object")
        return data
    return fetch

def fixture_fetcher(data):
    calls={}
    def fetch(token):
        key=str(token); calls[key]=calls.get(key,0)+1
        if calls[key] <= data.get("transient_failures",{}).get(key,0): raise TransientFetchError("fixture")
        return data["pages"][key]
    return fetch

def selftest():
    fixture={"pages":{"1":{"items":[{"id":1},{"id":2}],"next":2},"2":{"items":[{"id":2},{"bad":1},{"id":3}],"next":3},"3":{"items":[{"id":4}],"next":None}},"transient_failures":{"2":1}}
    r=collect(fixture_fetcher(fixture))
    assert [x["id"] for x in r["records"]]==[1,2,3,4] and r["retries"]==1 and r["duplicates"]==1 and len(r["rejected"])==2
    try: collect(lambda _: (_ for _ in ()).throw(TransientFetchError("x")),max_retries=2); raise AssertionError("retry")
    except TransientFetchError: pass
    cyc={1:{"items":[{"id":1}],"next":2},2:{"items":[{"id":2}],"next":1}}
    try: collect(lambda t:cyc[t]); raise AssertionError("cycle")
    except PermanentFetchError as e: assert str(e)=="pagination_cycle"
    try: collect(lambda _:{"items":"bad","next":None}); raise AssertionError("malformed")
    except PermanentFetchError as e: assert str(e)=="malformed_page"
    try: collect(lambda t:{"items":[{"id":t}],"next":t+1},max_pages=2); raise AssertionError("limit")
    except PermanentFetchError as e: assert str(e)=="max_pages_exceeded"
    try: http_fetcher("https://user:pass@example.test/x?page={page}"); raise AssertionError("url_creds")
    except ValueError as e: assert str(e)=="credentials_in_url_forbidden"
    with tempfile.TemporaryDirectory() as td:
        p=Path(td)/"x.csv"; write_csv(r["records"],p); assert p.read_text().splitlines()==["id","1","2","3","4"]
    print(json.dumps({"tests":7,"pass":True},sort_keys=True))

def benchmark(n=5000):
    samples=[]
    data={"pages":{"1":{"items":[{"id":1},{"id":2}],"next":2},"2":{"items":[{"id":2},{"bad":1},{"id":3}],"next":3},"3":{"items":[{"id":4}],"next":None}},"transient_failures":{"2":1}}
    for _ in range(n):
        t=time.perf_counter_ns(); r=collect(fixture_fetcher(data)); assert len(r["records"])==4
        samples.append((time.perf_counter_ns()-t)/1e6)
    samples.sort()
    print(json.dumps({"runs":n,"median_ms":round(statistics.median(samples),6),"p95_ms":round(samples[int(n*.95)-1],6),"mean_ms":round(statistics.fmean(samples),6),"network_calls":0,"model_api_calls":0},sort_keys=True))

def main():
    p=argparse.ArgumentParser(); sub=p.add_subparsers(dest="cmd",required=True)
    sub.add_parser("selftest"); b=sub.add_parser("benchmark"); b.add_argument("--runs",type=int,default=5000)
    f=sub.add_parser("fixture"); f.add_argument("--input",type=Path,required=True); f.add_argument("--output",type=Path,required=True)
    l=sub.add_parser("live"); l.add_argument("--url-template",required=True); l.add_argument("--output",type=Path,required=True); l.add_argument("--bearer-env"); l.add_argument("--start",default="1"); l.add_argument("--max-pages",type=int,default=100)
    a=p.parse_args()
    if a.cmd=="selftest": selftest(); return
    if a.cmd=="benchmark": benchmark(a.runs); return
    if a.cmd=="fixture": data=json.loads(a.input.read_text()); r=collect(fixture_fetcher(data))
    else: r=collect(http_fetcher(a.url_template,a.bearer_env),start=a.start,max_pages=a.max_pages)
    write_csv(r["records"],a.output)
    print(json.dumps({k:(len(v) if isinstance(v,list) else v) for k,v in r.items() if k!="records"}|{"records":len(r["records"])},sort_keys=True))
if __name__=="__main__": main()
