#!/usr/bin/env bash
set -euo pipefail

echo 'G077_PROVIDER_PILOT_START'
echo "UTC: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "Kernel: $(uname -a)"
echo "CPU cores: $(nproc)"
echo 'Memory:'
free -h
python3 tools/g077_free_tier_pilot.py --rows 100000 --repeats 3 --out artifact
python3 - <<'PY'
import json
r=json.load(open("artifact/receipt.json",encoding="utf-8"))
assert r["task_success"] is True
assert r["input_rows"] == 100000
assert r["unique_rows"] == 80000
assert r["secret_inputs"] == 0
assert r["production_credentials_used"] is False
print("G077_PROVIDER_PILOT_PASS")
print(json.dumps(r,sort_keys=True))
PY
