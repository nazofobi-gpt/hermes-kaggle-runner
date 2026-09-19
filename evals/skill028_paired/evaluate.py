import json, pathlib, sys
ROOT=pathlib.Path(__file__).resolve().parent

def baseline(c):
    # Frozen no-skill baseline from lifecycle record: local/manual-first, no dedicated provider/fallback policy.
    if c.get("account_action"): return "user_required"
    if c["kind"]=="batch" and not c.get("laptop_off"): return "local"
    if c["kind"]=="ml" and c.get("gpu"): return "local"
    if c["kind"]=="browser": return "local"
    return "unresolved"

def candidate(c):
    if c.get("account_action"): return "user_required"
    if c.get("paid_without_approval"): return "approval_required"
    if c.get("quick_tunnel"): return "unsafe_remote_block"
    if c.get("requested_provider")=="kaggle" and c["kind"]=="always_on": return "policy_block"
    if not c["public_safe"]: return "private_execution_required"
    if c.get("primary_unavailable"): return "portable_container"
    if c["kind"]=="always_on" and c.get("strict_zero"): return "no_verified_zero_fit"
    if c["kind"]=="ml" and c.get("gpu"): return "kaggle_bounded"
    if c["kind"]=="scheduled" and c.get("laptop_off"): return "serverless_zero_tier"
    if c["kind"]=="browser" and c.get("laptop_off"): return "github_actions_playwright"
    if c["kind"]=="batch" and c.get("laptop_off"): return "github_actions"
    return "local"

def evaluate():
    cases=json.loads((ROOT/"fixtures.json").read_text())
    rows=[]
    for c in cases:
        expected=c["expected"]; b=baseline(c); w=candidate(c)
        rows.append({"id":c["id"],"expected":expected,"baseline":b,"candidate":w,
                     "baseline_pass":b==expected,"candidate_pass":w==expected})
    return {"cases":rows,"baseline_pass":sum(r["baseline_pass"] for r in rows),
            "candidate_pass":sum(r["candidate_pass"] for r in rows),"total":len(rows)}

if __name__=="__main__":
    result=evaluate()
    print(json.dumps(result,indent=2,sort_keys=True))
    if result["candidate_pass"] != result["total"]: sys.exit(1)
