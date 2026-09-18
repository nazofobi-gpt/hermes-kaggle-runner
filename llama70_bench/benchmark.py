import ast
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time
import traceback

subprocess.run([sys.executable, "-m", "pip", "install", "-q", "requests"], check=True)
import requests

INPUT_ROOT = pathlib.Path("/kaggle/input")
WORK = pathlib.Path("/kaggle/working")
LOCAL_MODELS = WORK / "llama70-ollama-models"
BASE_MODEL = "llama3.1:70b-instruct-q2_K"
OLLAMA_URL = "http://127.0.0.1:11434"
CONTEXT = 4096


def run(cmd, **kwargs):
    return subprocess.run(cmd, check=True, text=True, **kwargs)


def wait_http(url, timeout=120):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if requests.get(url, timeout=3).ok:
                return True
        except Exception:
            pass
        time.sleep(2)
    return False


def discover_cache_root():
    print("LLAMA70_INPUT_DIRS=" + json.dumps(sorted(str(p) for p in INPUT_ROOT.iterdir())), flush=True)
    for index_path in INPUT_ROOT.rglob("cache-index.json"):
        try:
            data = json.loads(index_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if data.get("base_model") == BASE_MODEL:
            root = index_path.parent
            if (root / "base-manifest.json").is_file() and list(root.glob("sha256-*")):
                print(f"LLAMA70_CACHE_ROOT={root}", flush=True)
                return root
    candidates = []
    for manifest in INPUT_ROOT.rglob("base-manifest.json"):
        root = manifest.parent
        if list(root.glob("sha256-*")):
            candidates.append(root)
    if len(candidates) == 1:
        print(f"LLAMA70_CACHE_ROOT={candidates[0]}", flush=True)
        return candidates[0]
    raise RuntimeError(f"LLAMA70_CACHE_DISCOVERY_FAILED:{[str(p) for p in candidates]}")


def stage_cache():
    root = discover_cache_root()
    blobs = sorted(root.glob("sha256-*"))
    manifest_src = root / "base-manifest.json"
    if not blobs or not manifest_src.is_file():
        raise RuntimeError("LLAMA70_CACHE_INCOMPLETE")

    blobs_dir = LOCAL_MODELS / "blobs"
    manifest_dir = LOCAL_MODELS / "manifests" / "registry.ollama.ai" / "library" / "llama3.1"
    blobs_dir.mkdir(parents=True, exist_ok=True)
    manifest_dir.mkdir(parents=True, exist_ok=True)
    for src in blobs:
        dst = blobs_dir / src.name
        if dst.exists() or dst.is_symlink():
            dst.unlink()
        dst.symlink_to(src)
    shutil.copy2(manifest_src, manifest_dir / "70b-instruct-q2_K")
    print(f"LLAMA70_CACHE_STAGE=PASS blobs={len(blobs)}", flush=True)
    print("LLAMA70_NO_PULL_NO_CREATE=PASS", flush=True)


def install_ollama():
    if shutil.which("zstd") is None:
        run(["bash", "-lc", "apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq zstd"])
    run(["bash", "-lc", "curl -fsSL https://ollama.com/install.sh | sh"])


def start_ollama():
    env = os.environ.copy()
    env.update({
        "OLLAMA_MODELS": str(LOCAL_MODELS),
        "OLLAMA_HOST": "127.0.0.1:11434",
        "OLLAMA_KEEP_ALIVE": "-1",
        "OLLAMA_NUM_PARALLEL": "1",
        "OLLAMA_CONTEXT_LENGTH": str(CONTEXT),
        "OLLAMA_FLASH_ATTENTION": "1",
        "OLLAMA_KV_CACHE_TYPE": "q8_0",
        "CUDA_VISIBLE_DEVICES": "0,1",
    })
    log = open(WORK / "llama70_ollama.log", "w", buffering=1)
    proc = subprocess.Popen(["ollama", "serve"], env=env, stdout=log, stderr=subprocess.STDOUT, text=True)
    if not wait_http(f"{OLLAMA_URL}/api/tags", 120):
        raise RuntimeError("OLLAMA_START_FAILED")
    return proc, env


def chat(payload, timeout=600):
    payload = dict(payload)
    options = dict(payload.get("options") or {})
    options["num_ctx"] = CONTEXT
    payload["options"] = options
    r = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=timeout)
    r.raise_for_status()
    return r.json()


def tps(resp):
    count = float(resp.get("eval_count") or 0)
    dur = float(resp.get("eval_duration") or 0)
    return count / (dur / 1e9) if count and dur else 0.0


def exact_content(resp):
    return ((resp.get("message") or {}).get("content") or "").strip()


def extract_python(text):
    m = re.search(r"```(?:python)?\s*(.*?)```", text, re.S | re.I)
    return (m.group(1) if m else text).strip()


def code_acceptance(code_text):
    code = extract_python(code_text)
    tree = ast.parse(code)
    funcs = [n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    if "merge_intervals" not in funcs:
        return False, "missing-function"
    ns = {}
    exec(compile(tree, "<model-code>", "exec"), {"__builtins__": __builtins__}, ns)
    fn = ns.get("merge_intervals")
    cases = [
        ([(1, 3), (2, 6), (8, 10), (15, 18)], [(1, 6), (8, 10), (15, 18)]),
        ([], []),
        ([(1, 4), (4, 5)], [(1, 5)]),
        ([(5, 7), (1, 2), (2, 4)], [(1, 4), (5, 7)]),
    ]
    for inp, expected in cases:
        got = fn(list(inp))
        normalized = [tuple(x) for x in got]
        if normalized != expected:
            return False, f"case-failed:{inp}:{normalized}"
    return True, "ok"


def gpu_snapshot():
    rows = subprocess.check_output([
        "nvidia-smi",
        "--query-gpu=index,name,memory.used,memory.total,utilization.gpu",
        "--format=csv,noheader,nounits",
    ], text=True).strip().splitlines()
    return rows


def main():
    result = {
        "model": BASE_MODEL,
        "context": CONTEXT,
        "cache_only": True,
        "reasoning_trials": 3,
        "tool_trials": 5,
    }

    stage_cache()
    install_ollama()
    proc, env = start_ollama()
    try:
        run(["ollama", "show", BASE_MODEL], env=env, stdout=subprocess.DEVNULL)
        print("LLAMA70_MODEL_SHOW=PASS", flush=True)
        print(f"LLAMA70_CONTEXT={CONTEXT}", flush=True)

        started = time.time()
        basic = chat({
            "model": BASE_MODEL,
            "messages": [{"role": "user", "content": "Reply exactly LLAMA70_BASIC_PASS"}],
            "stream": False,
            "options": {"temperature": 0},
        })
        result["basic_seconds"] = round(time.time() - started, 3)
        result["basic_tps"] = round(tps(basic), 2)
        result["basic_ok"] = exact_content(basic) == "LLAMA70_BASIC_PASS"
        print(f"LLAMA70_BASIC={'PASS' if result['basic_ok'] else 'FAIL'}", flush=True)

        reasoning_prompts = [
            ("A server processes 18 tasks per minute for 25 minutes, then 24 tasks per minute for 15 minutes. How many tasks total? Reply only with the integer.", "810"),
            ("All C objects are D objects. No D object is an E object. Can any object be both C and E? Reply exactly YES or NO.", "NO"),
            ("Mira is older than Lena. Lena is older than Ada. Ada is older than Noor. Who is second-oldest? Reply only with the name.", "Lena"),
        ]
        reasoning_successes = 0
        reasoning = []
        for i, (prompt, expected) in enumerate(reasoning_prompts, 1):
            t0 = time.time()
            resp = chat({
                "model": BASE_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "options": {"temperature": 0},
            })
            got = exact_content(resp)
            ok = got.casefold() == expected.casefold()
            reasoning_successes += int(ok)
            reasoning.append({"trial": i, "expected": expected, "got": got, "seconds": round(time.time()-t0, 3), "tps": round(tps(resp), 2), "ok": ok})
            print(f"LLAMA70_REASONING_TRIAL_{i}={'PASS' if ok else 'FAIL'} got={json.dumps(got)}", flush=True)
        result["reasoning"] = reasoning
        result["reasoning_successes"] = reasoning_successes
        print(f"LLAMA70_REASONING={reasoning_successes}/3", flush=True)

        tools_schema = [
            {
                "type": "function",
                "function": {
                    "name": "terminal_echo",
                    "description": "Echo an exact token in a terminal.",
                    "parameters": {
                        "type": "object",
                        "properties": {"token": {"type": "string"}},
                        "required": ["token"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "calculator",
                    "description": "Evaluate an arithmetic expression.",
                    "parameters": {
                        "type": "object",
                        "properties": {"expression": {"type": "string"}},
                        "required": ["expression"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "read_text",
                    "description": "Read a UTF-8 text file from an exact path.",
                    "parameters": {
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                        "required": ["path"],
                    },
                },
            },
        ]
        tool_cases = [
            ("Call terminal_echo exactly once with token L70_TOOL_1. Do not answer in prose.", "terminal_echo", {"token": "L70_TOOL_1"}),
            ("Call calculator exactly once with expression 19*23. Do not answer in prose.", "calculator", {"expression": "19*23"}),
            ("Call read_text exactly once with path /tmp/llama70_fixture.txt. Do not answer in prose.", "read_text", {"path": "/tmp/llama70_fixture.txt"}),
            ("Call terminal_echo exactly once with token L70_TOOL_4. Do not answer in prose.", "terminal_echo", {"token": "L70_TOOL_4"}),
            ("Call calculator exactly once with expression (144/12)+7. Do not answer in prose.", "calculator", {"expression": "(144/12)+7"}),
        ]
        tool_successes = 0
        tool_results = []
        for i, (prompt, exp_name, exp_args) in enumerate(tool_cases, 1):
            t0 = time.time()
            resp = chat({
                "model": BASE_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "tools": tools_schema,
                "stream": False,
                "options": {"temperature": 0},
            })
            calls = (resp.get("message") or {}).get("tool_calls") or []
            got_name, got_args = None, None
            if len(calls) == 1:
                fn = calls[0].get("function") or {}
                got_name = fn.get("name")
                got_args = fn.get("arguments") or {}
                if isinstance(got_args, str):
                    try:
                        got_args = json.loads(got_args)
                    except Exception:
                        got_args = {}
            ok = len(calls) == 1 and got_name == exp_name and got_args == exp_args
            tool_successes += int(ok)
            tool_results.append({
                "trial": i,
                "ok": ok,
                "expected_name": exp_name,
                "expected_args": exp_args,
                "got_name": got_name,
                "got_args": got_args,
                "content": exact_content(resp),
                "seconds": round(time.time()-t0, 3),
                "tps": round(tps(resp), 2),
            })
            print(f"LLAMA70_TOOL_TRIAL_{i}={'PASS' if ok else 'FAIL'} name={got_name} args={json.dumps(got_args, sort_keys=True)}", flush=True)
        result["tool_successes"] = tool_successes
        result["tool_results"] = tool_results
        print(f"LLAMA70_TOOL_CALLS={tool_successes}/5", flush=True)

        t0 = time.time()
        code_resp = chat({
            "model": BASE_MODEL,
            "messages": [{
                "role": "user",
                "content": (
                    "Return only Python code. Implement merge_intervals(intervals). "
                    "Input is a list of (start,end) integer pairs in arbitrary order. "
                    "Merge overlapping or touching intervals, return sorted list of tuples. "
                    "Do not use third-party libraries."
                ),
            }],
            "stream": False,
            "options": {"temperature": 0},
        })
        code_text = exact_content(code_resp)
        try:
            code_ok, code_detail = code_acceptance(code_text)
        except Exception as exc:
            code_ok, code_detail = False, f"{type(exc).__name__}:{exc}"
        result["code_ok"] = code_ok
        result["code_detail"] = code_detail
        result["code_seconds"] = round(time.time()-t0, 3)
        result["code_tps"] = round(tps(code_resp), 2)
        print(f"LLAMA70_CODE={'PASS' if code_ok else 'FAIL'} detail={code_detail}", flush=True)

        gpu = gpu_snapshot()
        result["gpu"] = gpu
        active_gpu_count = 0
        for row in gpu:
            print(f"LLAMA70_GPU={row}", flush=True)
            parts = [p.strip() for p in row.split(",")]
            try:
                if int(parts[2]) > 1000:
                    active_gpu_count += 1
            except Exception:
                pass
        result["active_gpu_count"] = active_gpu_count
        print(f"LLAMA70_ACTIVE_GPU_COUNT={active_gpu_count}", flush=True)

        try:
            ps = subprocess.check_output(["ollama", "ps"], env=env, text=True).strip()
        except Exception as exc:
            ps = f"ERROR:{type(exc).__name__}"
        result["ollama_ps"] = ps
        print("LLAMA70_OLLAMA_PS=" + json.dumps(ps), flush=True)

        passed = bool(
            result["basic_ok"]
            and reasoning_successes == 3
            and tool_successes == 5
            and code_ok
            and active_gpu_count >= 2
        )
        result["pass"] = passed
        (WORK / "llama70_benchmark.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(f"LLAMA70_BENCHMARK={'PASS' if passed else 'FAIL'}", flush=True)
        if not passed:
            raise SystemExit(2)
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except Exception:
                proc.kill()


if __name__ == "__main__":
    try:
        main()
    except BaseException as exc:
        failure = {
            "error_type": type(exc).__name__,
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }
        (WORK / "llama70_failure.json").write_text(json.dumps(failure, indent=2) + "\n", encoding="utf-8")
        print(f"LLAMA70_FATAL={type(exc).__name__}:{exc}", flush=True)
        raise
