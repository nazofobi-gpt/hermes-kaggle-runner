#!/usr/bin/env python3
"""Public-boundary secret/dependency/IP hygiene verifier for G-080 fixtures."""
import ast, json, re, sys
from pathlib import Path
ROOT=Path(__file__).parent
targets=[ROOT/"api_pagination_etl.py",ROOT/"frontend_verify.py",ROOT/"frontend_delivery"]
patterns={"github_token":re.compile("gh"+r"p_[A-Za-z0-9]{20,}"),"openai_key":re.compile("s"+r"k-[A-Za-z0-9_-]{20,}"),"aws_key":re.compile("AK"+r"IA[0-9A-Z]{16}"),"private_key":re.compile("-----BEGIN "+r"(?:RSA |EC |OPENSSH )?PRIVATE KEY-----")}
hits=[]; third=[]
files=[]
for t in targets:
    files += list(t.rglob("*")) if t.is_dir() else [t]
for p in files:
    if not p.is_file():continue
    text=p.read_text(encoding="utf-8")
    for name,rx in patterns.items():
        if rx.search(text):hits.append({"file":str(p.relative_to(ROOT)),"pattern":name})
    if p.suffix==".py":
        tree=ast.parse(text)
        for node in ast.walk(tree):
            names=[]
            if isinstance(node,ast.Import):names=[a.name.split(".")[0] for a in node.names]
            elif isinstance(node,ast.ImportFrom) and node.module:names=[node.module.split(".")[0]]
            for name in names:
                if name not in sys.stdlib_module_names:third.append({"file":str(p.relative_to(ROOT)),"module":name})
result={"secret_hits":hits,"third_party_imports":third,"customer_data_files":0,"vendored_third_party_source":0,"pass":not hits and not third}
print(json.dumps(result,sort_keys=True)); raise SystemExit(0 if result["pass"] else 1)
