#!/usr/bin/env python3
"""SKILL-043 1.1 deterministic frontend-delivery gate."""
from __future__ import annotations
import argparse, json, re, shutil, statistics, tempfile, time
from html.parser import HTMLParser
from pathlib import Path

class P(HTMLParser):
    def __init__(self):
        super().__init__(); self.viewport=False; self.ids=set(); self.labels=set(); self.inputs={}; self.live=False; self.external=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=="meta" and a.get("name")=="viewport": self.viewport=True
        if a.get("id"): self.ids.add(a["id"])
        if tag=="label" and a.get("for"): self.labels.add(a["for"])
        if tag=="input" and a.get("id"): self.inputs[a["id"]]=a
        if a.get("aria-live"): self.live=True
        if tag=="script" and a.get("src","").startswith(("http://","https://","//")): self.external.append(a["src"])

def verify(site):
    site=Path(site); html=(site/"index.html").read_text(); css=(site/"styles.css").read_text(); js=(site/"app.js").read_text()
    p=P(); p.feed(html); e=[]
    if not p.viewport:e.append("missing_viewport")
    for x in {"hero","dashboard","lead-form","form-status"}:
        if x not in p.ids:e.append("missing_id:"+x)
    email=p.inputs.get("email")
    if not email or email.get("type")!="email" or "email" not in p.labels:e.append("unlabelled_email")
    if not p.live:e.append("missing_aria_live")
    if p.external:e.append("external_script_dependency")
    if "@media" not in css:e.append("missing_responsive_media_query")
    if not re.search(r'addEventListener\(\s*["\']submit["\']',js):e.append("missing_submit_interception")
    if re.search(r"\b(fetch|XMLHttpRequest|WebSocket)\b",js):e.append("unexpected_network_code")
    return sorted(e)

def mutate_test(site,old,new,filename,expected):
    with tempfile.TemporaryDirectory() as td:
        dst=Path(td)/"site"; shutil.copytree(site,dst); p=dst/filename; p.write_text(p.read_text().replace(old,new))
        assert expected in verify(dst)

def selftest(site):
    site=Path(site); assert verify(site)==[]
    mutate_test(site,'<meta name="viewport" content="width=device-width, initial-scale=1">\n',"","index.html","missing_viewport")
    mutate_test(site,'for="email"','for="other"',"index.html","unlabelled_email")
    mutate_test(site,"</body>",'<script src="https://cdn.example.test/x.js"></script></body>',"index.html","external_script_dependency")
    mutate_test(site,'})();','fetch("https://example.test");\n})();',"app.js","unexpected_network_code")
    print(json.dumps({"tests":5,"pass":True},sort_keys=True))

def benchmark(site,n=5000):
    samples=[]
    for _ in range(n):
        t=time.perf_counter_ns(); assert verify(site)==[]; samples.append((time.perf_counter_ns()-t)/1e6)
    samples.sort()
    print(json.dumps({"runs":n,"median_ms":round(statistics.median(samples),6),"p95_ms":round(samples[int(n*.95)-1],6),"mean_ms":round(statistics.fmean(samples),6),"network_calls":0,"model_api_calls":0},sort_keys=True))

def main():
    p=argparse.ArgumentParser(); p.add_argument("cmd",choices=["verify","selftest","benchmark"]); p.add_argument("--site",type=Path,default=Path(__file__).parent/"frontend_delivery"); p.add_argument("--runs",type=int,default=5000); a=p.parse_args()
    if a.cmd=="verify":
        e=verify(a.site); print(json.dumps({"errors":e,"pass":not e},sort_keys=True)); raise SystemExit(0 if not e else 1)
    if a.cmd=="selftest": selftest(a.site)
    else: benchmark(a.site,a.runs)
if __name__=="__main__":main()
