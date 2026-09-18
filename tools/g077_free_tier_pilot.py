#!/usr/bin/env python3
import argparse, csv, hashlib, json, os, statistics, tempfile, time
from pathlib import Path

def sha256(path):
    h=hashlib.sha256()
    with open(path,"rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()

def pct95(xs):
    s=sorted(xs)
    if len(s)==1: return s[0]
    pos=(len(s)-1)*0.95
    lo=int(pos); hi=min(lo+1,len(s)-1); frac=pos-lo
    return s[lo]*(1-frac)+s[hi]*frac

def make_input(path, rows):
    unique=max(1,int(rows*0.8))
    with open(path,"w",newline="",encoding="utf-8") as f:
        w=csv.writer(f); w.writerow(["record_id","name","email","amount_eur","city"])
        for i in range(rows):
            j=i%unique
            name=(f"  client {j}  " if i%2==0 else f"CLIENT {j}")
            email=(f"USER{j}@Example.COM " if i%3==0 else f"user{j}@example.com")
            amount=(f"{(j%500)+0.25:.2f}" if i%4 else f" {(j%500)+0.25:.2f} ")
            city=(" bremen " if j%2==0 else "LOHNE")
            w.writerow([j,name,email,amount,city])

def clean(inp,out):
    seen={}
    with open(inp,newline="",encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key=row["email"].strip().lower()
            if key in seen: continue
            seen[key]={
                "record_id":int(row["record_id"]),
                "name":" ".join(row["name"].strip().split()).title(),
                "email":key,
                "amount_eur":f"{float(row['amount_eur'].strip()):.2f}",
                "city":" ".join(row["city"].strip().split()).title(),
            }
    with open(out,"w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=["record_id","name","email","amount_eur","city"])
        w.writeheader()
        for k in sorted(seen,key=lambda x:int(x.split("user",1)[1].split("@",1)[0])):
            w.writerow(seen[k])
    return len(seen), round(sum(float(v["amount_eur"]) for v in seen.values()),2)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--rows",type=int,default=100000)
    ap.add_argument("--repeats",type=int,default=3)
    ap.add_argument("--out",default="artifact")
    a=ap.parse_args()
    outdir=Path(a.out); outdir.mkdir(parents=True,exist_ok=True)
    expected=max(1,int(a.rows*0.8))
    samples=[]; last={}
    for n in range(a.repeats):
        with tempfile.TemporaryDirectory() as td:
            inp=Path(td)/"input.csv"; out=Path(td)/"cleaned.csv"
            t0=time.perf_counter()
            make_input(inp,a.rows)
            unique,total=clean(inp,out)
            elapsed=time.perf_counter()-t0
            assert unique==expected,(unique,expected)
            samples.append(elapsed)
            last={"input_sha256":sha256(inp),"output_sha256":sha256(out),"unique_rows":unique,"total_amount_eur":total}
            if n==a.repeats-1:
                (outdir/"cleaned.csv").write_bytes(out.read_bytes())
    receipt={
        "provider":"github-actions-hosted-ubuntu",
        "workload":"synthetic-csv-clean-dedup-report",
        "input_rows":a.rows,
        "expected_unique_rows":expected,
        "repeats":a.repeats,
        "samples_sec":[round(x,6) for x in samples],
        "median_sec":round(statistics.median(samples),6),
        "p95_sec":round(pct95(samples),6),
        "task_success":True,
        "secret_inputs":0,
        "network_calls_by_workload":0,
        "production_credentials_used":False,
        "marginal_compute_cost_eur":0,
        **last,
    }
    (outdir/"receipt.json").write_text(json.dumps(receipt,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps(receipt,sort_keys=True))

if __name__=="__main__":
    main()
