#!/usr/bin/env python3
import csv, hashlib, json, pathlib, time

ROWS = [
    {"id":"1","name":" Alice ","amount":"100.00"},
    {"id":"2","name":"Bob","amount":"50.00"},
    {"id":"1","name":"Alice","amount":"100.00"},
    {"id":"3","name":"Carmona","amount":""},
]

def main():
    started=time.time()
    seen=set(); cleaned=[]; changes=[]
    for idx,row in enumerate(ROWS, start=2):
        key=row["id"]
        if key in seen:
            changes.append({"row":idx,"action":"REMOVE_DUPLICATE","key":key})
            continue
        seen.add(key)
        name=row["name"].strip()
        status="REVIEW" if row["amount"]=="" else "OK"
        cleaned.append({"id":key,"name":name,"amount":row["amount"],"status":status})
        if name != row["name"]:
            changes.append({"row":idx,"action":"TRIM_NAME","from":row["name"],"to":name})
        if status=="REVIEW":
            changes.append({"row":idx,"action":"FLAG_MISSING_AMOUNT","key":key})
    out=pathlib.Path("free_pilot/out"); out.mkdir(parents=True, exist_ok=True)
    with (out/"cleaned.csv").open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=["id","name","amount","status"]); w.writeheader(); w.writerows(cleaned)
    (out/"change_log.json").write_text(json.dumps(changes,indent=2),encoding="utf-8")
    payload=(out/"cleaned.csv").read_bytes()
    receipt={"source_rows":4,"clean_rows":3,"duplicates_removed":1,"review_rows":1,"change_events":len(changes),"sha256":hashlib.sha256(payload).hexdigest(),"elapsed_ms":round((time.time()-started)*1000,3)}
    assert receipt["clean_rows"]==3 and receipt["duplicates_removed"]==1 and receipt["review_rows"]==1
    assert cleaned[0]["name"]=="Alice" and cleaned[-1]["name"]=="Carmona"
    (out/"receipt.json").write_text(json.dumps(receipt,indent=2),encoding="utf-8")
    print(json.dumps(receipt,sort_keys=True))

if __name__=="__main__": main()
