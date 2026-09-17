import json
import os
import pathlib
import shutil
import subprocess
import sys
import time

INPUT_ROOT = pathlib.Path("/kaggle/input")
LOCAL_MODELS = pathlib.Path("/kaggle/working/ollama-models")
BASE_MODEL_DIR = LOCAL_MODELS / "manifests" / "registry.ollama.ai" / "library" / "llama3.1"
BASE_TAG = "8b-instruct-q4_K_M"


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

    for src in blob_sources:
        dst = blobs_dir / src.name
        if dst.exists() or dst.is_symlink():
            dst.unlink()
        dst.symlink_to(src)

    shutil.copy2(manifest_src, BASE_MODEL_DIR / BASE_TAG)
    os.environ["OLLAMA_MODELS"] = str(LOCAL_MODELS)
    print(f"MODEL_CACHE_ROOT={cache_root}", flush=True)
    print(f"MODEL_CACHE_STAGE: PASS blobs={len(blob_sources)}", flush=True)


stage_persistent_cache()

import worker  # noqa: E402

ACTIVITY_FILE = worker.WORK / "last_inference_activity"
INFLIGHT_DIR = worker.WORK / "inflight_requests"
INFLIGHT_DIR.mkdir(parents=True, exist_ok=True)


def ensure_model_from_cache() -> None:
    # Strict cache-only path: do not run `ollama pull` here.
    subprocess.run(["ollama", "show", worker.BASE_MODEL], check=True)

    modelfile = worker.WORK / "Modelfile.hermes64k"
    modelfile.write_text(
        f"FROM {worker.BASE_MODEL}\nPARAMETER num_ctx 65536\n",
        encoding="utf-8",
    )
    subprocess.run(["ollama", "create", worker.MODEL, "-f", str(modelfile)], check=True)

    response = worker.requests.post(
        f"{worker.OLLAMA_URL}/api/chat",
        json={
            "model": worker.MODEL,
            "messages": [{"role": "user", "content": "Reply exactly WORKER_READY"}],
            "stream": False,
        },
        timeout=300,
    )
    response.raise_for_status()
    print("MODEL_CACHE_HIT: PASS", flush=True)
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


def main_with_idle_shutdown() -> None:
    cfg = worker.load_runtime_config()
    generation = int(cfg["generation"])
    max_runtime = int(cfg.get("max_runtime_seconds", 21600))
    idle_timeout = int(cfg.get("idle_timeout_seconds", 300))
    startup_grace = int(cfg.get("startup_grace_seconds", 480))

    initial = worker.get_remote_state()
    if initial.get("desired") != "RUN" or int(initial.get("generation", -1)) != generation:
        print("CONTROL_STATE_NOT_RUN: EXIT", flush=True)
        return

    github_token = worker.get_github_token()
    cloudflared = worker.install_runtime()
    ollama_proc = worker.start_ollama()
    worker.ensure_model()

    api_key = worker.secrets.token_urlsafe(40)
    proxy_proc = worker.start_proxy(api_key)
    tunnel_proc, tunnel_url = worker.start_tunnel(cloudflared)
    if not worker.validate_public_health(tunnel_url, api_key):
        raise RuntimeError("PUBLIC_TUNNEL_HEALTH_FAILED")
    worker.sync_github_secrets(github_token, f"{tunnel_url}/v1", api_key)

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

        # Never stop while an authenticated inference request is in flight.
        # Health probes do not create markers or refresh last activity.
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
            if worker.validate_public_health(tunnel_url, api_key):
                worker.sync_github_secrets(github_token, f"{tunnel_url}/v1", api_key)
            else:
                raise RuntimeError("TUNNEL_RESTART_HEALTH_FAILED")

        time.sleep(30)
    else:
        print("MAX_RUNTIME_REACHED: EXIT", flush=True)


worker.ensure_model = ensure_model_from_cache
worker.start_proxy = start_proxy_with_activity

if __name__ == "__main__":
    main_with_idle_shutdown()
