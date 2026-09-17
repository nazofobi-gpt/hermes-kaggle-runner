import base64
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time

subprocess.run([sys.executable, "-m", "pip", "install", "-q", "requests", "pynacl"], check=True)

import requests
from nacl.public import PrivateKey, SealedBox
from nacl.secret import SecretBox

INPUT_ROOT = pathlib.Path("/kaggle/input")
WORK = pathlib.Path("/kaggle/working")
LOCAL_MODELS = WORK / "ollama-models"
MODEL = "llama3.1-hermes"
BASE_MODEL = "llama3.1:8b-instruct-q4_K_M"
BASE_MODEL_DIR = LOCAL_MODELS / "manifests" / "registry.ollama.ai" / "library" / "llama3.1"
ALIAS_MODEL_DIR = LOCAL_MODELS / "manifests" / "registry.ollama.ai" / "library" / "llama3.1-hermes"
BASE_TAG = "8b-instruct-q4_K_M"
ALIAS_TAG = "latest"
OLLAMA_URL = "http://127.0.0.1:11434"
CONTEXT_LENGTH = 32768
MAX_RESULT_CHARS = 50000

# GitHub Actions replaces this exact placeholder in its temporary checkout.
# The committed repository never contains plaintext task content.
EMBEDDED_GPU_REQUEST = None


def discover_model_cache() -> pathlib.Path:
    preferred = [
        INPUT_ROOT / "hermes-ollama-cache",
        INPUT_ROOT / "datasets" / "nazofobigpt" / "hermes-ollama-cache",
    ]
    for root in preferred:
        if (root / "base-manifest.json").is_file() and list(root.glob("sha256-*")):
            return root
    candidates = []
    if INPUT_ROOT.exists():
        for manifest in INPUT_ROOT.rglob("base-manifest.json"):
            root = manifest.parent
            if list(root.glob("sha256-*")):
                candidates.append(root)
    if len(candidates) != 1:
        raise RuntimeError("MODEL_CACHE_DISCOVERY_FAILED")
    return candidates[0]


def discover_private_key() -> pathlib.Path:
    candidates = list(INPUT_ROOT.rglob("private_key.b64")) if INPUT_ROOT.exists() else []
    if len(candidates) != 1:
        raise RuntimeError("TRANSPORT_PRIVATE_KEY_DISCOVERY_FAILED")
    return candidates[0]


def stage_model_cache() -> None:
    cache_root = discover_model_cache()
    manifest_src = cache_root / "base-manifest.json"
    blob_sources = sorted(cache_root.glob("sha256-*"))
    if not blob_sources:
        raise RuntimeError("MODEL_CACHE_EMPTY")

    blobs_dir = LOCAL_MODELS / "blobs"
    blobs_dir.mkdir(parents=True, exist_ok=True)
    BASE_MODEL_DIR.mkdir(parents=True, exist_ok=True)
    ALIAS_MODEL_DIR.mkdir(parents=True, exist_ok=True)

    for src in blob_sources:
        dst = blobs_dir / src.name
        if dst.exists() or dst.is_symlink():
            dst.unlink()
        dst.symlink_to(src)

    shutil.copy2(manifest_src, BASE_MODEL_DIR / BASE_TAG)
    shutil.copy2(manifest_src, ALIAS_MODEL_DIR / ALIAS_TAG)
    os.environ["OLLAMA_MODELS"] = str(LOCAL_MODELS)
    os.environ["OLLAMA_CONTEXT_LENGTH"] = str(CONTEXT_LENGTH)
    print(f"GPU_TASK_MODEL_CACHE=PASS blobs={len(blob_sources)}", flush=True)


def install_runtime() -> None:
    if shutil.which("zstd") is None:
        subprocess.run(
            ["bash", "-lc", "apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq zstd"],
            check=True,
        )
        print("GPU_TASK_ZSTD=PASS", flush=True)
    subprocess.run(["bash", "-lc", "curl -fsSL https://ollama.com/install.sh | sh"], check=True)
    print("GPU_TASK_OLLAMA_INSTALL=PASS", flush=True)


def start_ollama() -> subprocess.Popen:
    env = os.environ.copy()
    env.update({
        "OLLAMA_HOST": "127.0.0.1:11434",
        "OLLAMA_KEEP_ALIVE": "-1",
        "OLLAMA_NUM_PARALLEL": "1",
        "OLLAMA_MODELS": str(LOCAL_MODELS),
        "OLLAMA_CONTEXT_LENGTH": str(CONTEXT_LENGTH),
    })
    log = open(WORK / "gpu-task-ollama.log", "a", buffering=1)
    proc = subprocess.Popen(["ollama", "serve"], env=env, stdout=log, stderr=subprocess.STDOUT, text=True)
    deadline = time.time() + 90
    while time.time() < deadline:
        try:
            r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=4)
            if r.ok:
                return proc
        except Exception:
            pass
        time.sleep(2)
    proc.terminate()
    raise RuntimeError("OLLAMA_START_FAILED")


def validate_request() -> dict:
    req = EMBEDDED_GPU_REQUEST
    if not isinstance(req, dict):
        raise RuntimeError("GPU_REQUEST_MISSING")
    task_id = str(req.get("task_id") or "")
    if not re.fullmatch(r"[A-Za-z0-9._-]{8,96}", task_id):
        raise RuntimeError("GPU_TASK_ID_INVALID")
    for field in ("wrapped_key_b64", "prompt_box_b64"):
        value = req.get(field)
        if not isinstance(value, str) or not value or len(value) > 1500000:
            raise RuntimeError(f"GPU_REQUEST_FIELD_INVALID:{field}")
    return req


def decrypt_prompt(req: dict) -> tuple[bytes, str]:
    private_key_raw = base64.b64decode(discover_private_key().read_text(encoding="utf-8").strip(), validate=True)
    private_key = PrivateKey(private_key_raw)
    session_key = SealedBox(private_key).decrypt(base64.b64decode(req["wrapped_key_b64"], validate=True))
    if len(session_key) != SecretBox.KEY_SIZE:
        raise RuntimeError("SESSION_KEY_LENGTH_INVALID")
    prompt = SecretBox(session_key).decrypt(base64.b64decode(req["prompt_box_b64"], validate=True)).decode("utf-8")
    if not prompt.strip() or len(prompt) > 500000:
        raise RuntimeError("GPU_PROMPT_INVALID")
    return session_key, prompt


def run_model(prompt: str) -> str:
    subprocess.run(["ollama", "show", BASE_MODEL], check=True, stdout=subprocess.DEVNULL)
    subprocess.run(["ollama", "show", MODEL], check=True, stdout=subprocess.DEVNULL)
    payload = {
        "model": MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a one-shot computation worker. Complete the supplied task accurately. "
                    "Return only the useful result. Do not claim to have used external tools, sent messages, "
                    "changed files, or performed real-world actions."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "options": {
            "num_ctx": CONTEXT_LENGTH,
            "num_predict": 4096,
            "temperature": 0.2,
        },
    }
    r = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=720)
    r.raise_for_status()
    result = ((r.json().get("message") or {}).get("content") or "").strip()
    if not result:
        raise RuntimeError("GPU_MODEL_EMPTY_RESULT")
    if len(result) > MAX_RESULT_CHARS:
        result = result[:MAX_RESULT_CHARS]
    return result


def main() -> None:
    WORK.mkdir(parents=True, exist_ok=True)
    req = validate_request()
    task_id = req["task_id"]
    print(f"GPU_TASK_ID={task_id}", flush=True)

    session_key, prompt = decrypt_prompt(req)
    print("GPU_TASK_DECRYPT=PASS", flush=True)

    stage_model_cache()
    install_runtime()
    ollama_proc = start_ollama()
    try:
        result = run_model(prompt)
        encrypted = SecretBox(session_key).encrypt(result.encode("utf-8"))
        result_b64 = base64.b64encode(bytes(encrypted)).decode("ascii")
        print(f"GPU_TASK_RESULT_B64={result_b64}", flush=True)
        print("GPU_TASK_PASS=1", flush=True)
    finally:
        if ollama_proc.poll() is None:
            ollama_proc.terminate()
            try:
                ollama_proc.wait(timeout=5)
            except Exception:
                ollama_proc.kill()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"GPU_TASK_FATAL={type(exc).__name__}:{exc}", flush=True)
        raise
