import json
import os
import pathlib
import shutil
import subprocess
import sys
import time
import urllib.request

INPUT_ROOT = pathlib.Path("/kaggle/input")
SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
WORK = pathlib.Path("/kaggle/working")
LOCAL_MODELS = WORK / "ollama-models"
BASE_MODEL_DIR = LOCAL_MODELS / "manifests" / "registry.ollama.ai" / "library" / "llama3.1"
ALIAS_MODEL_DIR = LOCAL_MODELS / "manifests" / "registry.ollama.ai" / "library" / "llama3.1-hermes"
BASE_TAG = "8b-instruct-q4_K_M"
ALIAS_TAG = "latest"
GITHUB_OWNER = "nazofobi-gpt"
GITHUB_REPO = "hermes-kaggle-runner"
CONTEXT_LENGTH = 65536

# GitHub Actions replaces these exact placeholders only in its temporary
# checkout before pushing the private Kaggle kernel. Neither value is committed.
EMBEDDED_RUNTIME_CONFIG = None
EMBEDDED_PROXY_API_KEY = None


def discover_cache_root() -> pathlib.Path:
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
    if len(candidates) == 1:
        return candidates[0]
    raise RuntimeError(f"MODEL_CACHE_DISCOVERY_FAILED:{[str(p) for p in candidates]}")


def stage_persistent_cache() -> None:
    cache_root = discover_cache_root()
    manifest_src = cache_root / "base-manifest.json"
    blob_sources = sorted(cache_root.glob("sha256-*"))
    if not manifest_src.exists() or not blob_sources:
        raise RuntimeError("MODEL_CACHE_INCOMPLETE")

    blobs_dir = LOCAL_MODELS / "blobs"
    blobs_dir.mkdir(parents=True, exist_ok=True)
    BASE_MODEL_DIR.mkdir(parents=True, exist_ok=True)
    ALIAS_MODEL_DIR.mkdir(parents=True, exist_ok=True)

    for src in blob_sources:
        dst = blobs_dir / src.name
        if dst.exists() or dst.is_symlink():
            dst.unlink()
        dst.symlink_to(src)

    # Manifests are writable local copies; multi-GB model blobs stay read-only
    # symlinks to the persistent private Kaggle Dataset. No model pull/create.
    shutil.copy2(manifest_src, BASE_MODEL_DIR / BASE_TAG)
    shutil.copy2(manifest_src, ALIAS_MODEL_DIR / ALIAS_TAG)
    os.environ["OLLAMA_MODELS"] = str(LOCAL_MODELS)
    os.environ["OLLAMA_CONTEXT_LENGTH"] = str(CONTEXT_LENGTH)
    print(f"MODEL_CACHE_ROOT={cache_root}", flush=True)
    print(f"MODEL_CACHE_STAGE: PASS blobs={len(blob_sources)}", flush=True)
    print("MODEL_CACHE_NO_PULL_NO_CREATE: PASS", flush=True)


def load_bootstrap_config() -> dict:
    if isinstance(EMBEDDED_RUNTIME_CONFIG, dict) and int(EMBEDDED_RUNTIME_CONFIG.get("generation", 0)) > 0:
        return dict(EMBEDDED_RUNTIME_CONFIG)
    path = SCRIPT_DIR / "runtime_config.json"
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    raise RuntimeError("RUNTIME_CONFIG_MISSING")


def get_embedded_api_key() -> str:
    if not isinstance(EMBEDDED_PROXY_API_KEY, str) or len(EMBEDDED_PROXY_API_KEY) < 32:
        raise RuntimeError("EMBEDDED_PROXY_API_KEY_MISSING")
    return EMBEDDED_PROXY_API_KEY


def download_text_file(url: str, target: pathlib.Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "hermes-kaggle-worker/1"})
    with urllib.request.urlopen(req, timeout=30) as response:
        data = response.read()
    if not data:
        raise RuntimeError(f"RUNTIME_SOURCE_EMPTY:{target.name}")
    target.write_bytes(data)


def prepare_runtime_sources() -> None:
    cfg = load_bootstrap_config()
    source_ref = str(cfg.get("source_ref") or "main")
    WORK.mkdir(parents=True, exist_ok=True)
    for name in ("worker.py", "proxy_app.py"):
        url = f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/{source_ref}/kaggle/{name}"
        download_text_file(url, WORK / name)
    (WORK / "runtime_config.json").write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    os.chdir(WORK)
    if str(WORK) not in sys.path:
        sys.path.insert(0, str(WORK))
    print(f"RUNTIME_SOURCE_REF={source_ref}", flush=True)
    print("RUNTIME_SOURCE_STAGE: PASS", flush=True)


stage_persistent_cache()
prepare_runtime_sources()

import worker  # noqa: E402

ACTIVITY_FILE = worker.WORK / "last_inference_activity"
INFLIGHT_DIR = worker.WORK / "inflight_requests"
INFLIGHT_DIR.mkdir(parents=True, exist_ok=True)


def ensure_model_from_cache() -> None:
    subprocess.run(["ollama", "show", worker.BASE_MODEL], check=True)
    subprocess.run(["ollama", "show", worker.MODEL], check=True)

    response = worker.requests.post(
        f"{worker.OLLAMA_URL}/api/chat",
        json={
            "model": worker.MODEL,
            "messages": [{"role": "user", "content": "Reply exactly WORKER_READY"}],
            "stream": False,
            "options": {"num_ctx": CONTEXT_LENGTH, "temperature": 0},
        },
        timeout=300,
    )
    response.raise_for_status()
    text = ((response.json().get("message") or {}).get("content") or "").strip()
    if "WORKER_READY" not in text:
        raise RuntimeError("MODEL_WARMUP_TOKEN_MISMATCH")
    print("MODEL_CACHE_HIT: PASS", flush=True)
    print(f"MODEL_CONTEXT={CONTEXT_LENGTH}", flush=True)
    print("LOCAL_MODEL_READY", flush=True)


def clear_stale_inflight() -> None:
    INFLIGHT_DIR.mkdir(parents=True, exist_ok=True)
    for marker in INFLIGHT_DIR.iterdir():
        try:
            marker.unlink()
        except Exception:
            pass


def start_proxy_with_activity(api_key: str):
    clear_stale_inflight()
    env = os.environ.copy()
    env["PROXY_API_KEY"] = api_key
    old_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(WORK) + ((":" + old_pythonpath) if old_pythonpath else "")
    log = open(worker.WORK / "proxy.log", "a", buffering=1)
    proc = worker.start_process(
        [sys.executable, "-m", "uvicorn", "proxy_app:app", "--host", "127.0.0.1", "--port", str(worker.PROXY_PORT)],
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    if not worker.wait_http(
        f"http://127.0.0.1:{worker.PROXY_PORT}/health",
        timeout=60,
        headers={"Authorization": f"Bearer {api_key}"},
    ):
        raise RuntimeError("PROXY_START_FAILED")
    return proc


def read_last_activity(default: float) -> float:
    try:
        return float(ACTIVITY_FILE.read_text(encoding="utf-8").strip())
    except Exception:
        return default


def has_inflight_requests() -> bool:
    try:
        return any(INFLIGHT_DIR.iterdir())
    except Exception:
        return False


def announce_tunnel(tunnel_url: str) -> None:
    # URL is not an authentication credential. The bearer key is never printed.
    print(f"KAGGLE_TUNNEL_URL={tunnel_url}", flush=True)


def main_with_idle_shutdown() -> None:
    cfg = worker.load_runtime_config()
    generation = int(cfg["generation"])
    max_runtime = int(cfg.get("max_runtime_seconds", 21600))
    idle_timeout = int(cfg.get("idle_timeout_seconds", 300))
    startup_grace = int(cfg.get("startup_grace_seconds", 120))

    initial = worker.get_remote_state()
    if initial.get("desired") != "RUN" or int(initial.get("generation", -1)) != generation:
        print("CONTROL_STATE_NOT_RUN: EXIT", flush=True)
        return

    api_key = get_embedded_api_key()
    cloudflared = worker.install_runtime()
    ollama_proc = worker.start_ollama()
    worker.ensure_model()

    proxy_proc = worker.start_proxy(api_key)
    tunnel_proc, tunnel_url = worker.start_tunnel(cloudflared)
    if not worker.validate_public_health(tunnel_url, api_key):
        raise RuntimeError("PUBLIC_TUNNEL_HEALTH_FAILED")

    announce_tunnel(tunnel_url)
    print(f"WORKER_GENERATION={generation}", flush=True)
    print(f"GPU_IDLE_POLICY=startup_grace:{startup_grace}s idle:{idle_timeout}s hard_max:{max_runtime}s", flush=True)
    print("KAGGLE_GPU_WORKER: READY", flush=True)

    started = time.time()
    ready_at = started
    ACTIVITY_FILE.write_text(str(ready_at), encoding="utf-8")

    while time.time() - started < max_runtime:
        now = time.time()
        try:
            state = worker.get_remote_state()
            if state.get("desired") != "RUN" or int(state.get("generation", -1)) != generation:
                print("CONTROL_STOP_OR_REPLACED: EXIT", flush=True)
                break
        except Exception as exc:
            print(f"CONTROL_POLL_WARNING={type(exc).__name__}", flush=True)

        if now - ready_at >= startup_grace and not has_inflight_requests():
            idle_for = now - read_last_activity(ready_at)
            if idle_for >= idle_timeout:
                print(f"GPU_IDLE_TIMEOUT_REACHED={int(idle_for)}s: EXIT", flush=True)
                break

        if ollama_proc.poll() is not None:
            print("OLLAMA_WATCHDOG_RESTART", flush=True)
            ollama_proc = worker.start_ollama()
        if proxy_proc.poll() is not None:
            print("PROXY_WATCHDOG_RESTART", flush=True)
            proxy_proc = worker.start_proxy(api_key)

        if tunnel_proc.poll() is not None:
            print("TUNNEL_WATCHDOG_RESTART", flush=True)
            tunnel_proc, tunnel_url = worker.start_tunnel(cloudflared)
            if not worker.validate_public_health(tunnel_url, api_key):
                raise RuntimeError("TUNNEL_RESTART_HEALTH_FAILED")
            announce_tunnel(tunnel_url)

        time.sleep(30)
    else:
        print("MAX_RUNTIME_REACHED: EXIT", flush=True)


worker.ensure_model = ensure_model_from_cache
worker.start_proxy = start_proxy_with_activity

if __name__ == "__main__":
    main_with_idle_shutdown()
