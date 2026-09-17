import atexit
import base64
import json
import os
import pathlib
import re
import secrets
import shutil
import signal
import subprocess
import sys
import time
from typing import Optional

# Installed at runtime if an image does not already contain them.
subprocess.run(
    [sys.executable, "-m", "pip", "install", "-q", "requests", "fastapi", "uvicorn", "httpx", "pynacl"],
    check=True,
)

import httpx
import requests
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import Response
from nacl import encoding, public

MODEL = "llama3.1-hermes"
BASE_MODEL = "llama3.1:8b-instruct-q4_K_M"
OLLAMA_URL = "http://127.0.0.1:11434"
PROXY_PORT = 8000
GITHUB_OWNER = "nazofobi-gpt"
GITHUB_REPO = "hermes-kaggle-runner"
CONTROL_URL = f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/main/control/kaggle_state.json"
WORK = pathlib.Path("/kaggle/working")
WORK.mkdir(parents=True, exist_ok=True)

# FastAPI app imported by uvicorn in a child process.
app = FastAPI()


def _require_auth(authorization: Optional[str]) -> None:
    key = os.environ.get("PROXY_API_KEY", "")
    if not key or authorization != f"Bearer {key}":
        raise HTTPException(status_code=401, detail="unauthorized")


@app.get("/health")
async def health(authorization: Optional[str] = Header(default=None)):
    _require_auth(authorization)
    return {"ok": True, "model": MODEL}


@app.api_route("/v1/{path:path}", methods=["GET", "POST"])
async def openai_proxy(path: str, request: Request, authorization: Optional[str] = Header(default=None)):
    _require_auth(authorization)
    body = await request.body()
    headers = {"content-type": request.headers.get("content-type", "application/json")}
    if path == "chat/completions" and body:
        try:
            payload = json.loads(body)
            # Quick Tunnel pilot is intentionally non-streaming for reliability.
            payload["stream"] = False
            body = json.dumps(payload).encode("utf-8")
        except Exception:
            pass
    async with httpx.AsyncClient(timeout=650.0) as client:
        upstream = await client.request(request.method, f"{OLLAMA_URL}/v1/{path}", content=body, headers=headers)
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type", "application/json"),
    )


children: list[subprocess.Popen] = []


def start_process(args, *, env=None, stdout=None, stderr=None):
    p = subprocess.Popen(args, env=env, stdout=stdout, stderr=stderr, text=True)
    children.append(p)
    return p


def cleanup():
    for p in reversed(children):
        if p.poll() is None:
            try:
                p.terminate()
            except Exception:
                pass
    deadline = time.time() + 5
    for p in reversed(children):
        if p.poll() is None:
            try:
                p.wait(timeout=max(0.1, deadline - time.time()))
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass


atexit.register(cleanup)
signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
signal.signal(signal.SIGINT, lambda *_: sys.exit(0))


def wait_http(url: str, *, timeout=90, headers=None) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.get(url, headers=headers, timeout=5)
            if 200 <= r.status_code < 300:
                return True
        except Exception:
            pass
        time.sleep(2)
    return False


def install_runtime():
    print("RUNTIME_INSTALL_BEGIN", flush=True)
    if shutil.which("zstd") is None:
        subprocess.run(
            ["bash", "-lc", "apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq zstd"],
            check=True,
        )
        print("RUNTIME_ZSTD_BOOTSTRAP=PASS", flush=True)
    subprocess.run(["bash", "-lc", "curl -fsSL https://ollama.com/install.sh | sh"], check=True)
    cloudflared = WORK / "cloudflared"
    if not cloudflared.exists():
        subprocess.run(
            [
                "curl", "-fsSL",
                "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64",
                "-o", str(cloudflared),
            ],
            check=True,
        )
        cloudflared.chmod(0o755)
    print("RUNTIME_INSTALL_PASS", flush=True)
    return cloudflared


def start_ollama():
    env = os.environ.copy()
    env.update({"OLLAMA_HOST": "127.0.0.1:11434", "OLLAMA_KEEP_ALIVE": "-1", "OLLAMA_NUM_PARALLEL": "1"})
    log = open(WORK / "ollama.log", "a", buffering=1)
    p = start_process(["ollama", "serve"], env=env, stdout=log, stderr=subprocess.STDOUT)
    if not wait_http(f"{OLLAMA_URL}/api/tags", timeout=90):
        raise RuntimeError("OLLAMA_START_FAILED")
    return p


def ensure_model():
    subprocess.run(["ollama", "pull", BASE_MODEL], check=True)
    modelfile = WORK / "Modelfile.hermes64k"
    modelfile.write_text(f"FROM {BASE_MODEL}\nPARAMETER num_ctx 65536\n", encoding="utf-8")
    subprocess.run(["ollama", "create", MODEL, "-f", str(modelfile)], check=True)
    r = requests.post(
        f"{OLLAMA_URL}/api/chat",
        json={
            "model": MODEL,
            "messages": [{"role": "user", "content": "Reply exactly WORKER_READY"}],
            "stream": False,
        },
        timeout=300,
    )
    r.raise_for_status()
    print("LOCAL_MODEL_READY", flush=True)


def start_proxy(api_key: str):
    env = os.environ.copy()
    env["PROXY_API_KEY"] = api_key
    log = open(WORK / "proxy.log", "a", buffering=1)
    p = start_process(
        [sys.executable, "-m", "uvicorn", "worker:app", "--host", "127.0.0.1", "--port", str(PROXY_PORT)],
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    if not wait_http(
        f"http://127.0.0.1:{PROXY_PORT}/health",
        timeout=60,
        headers={"Authorization": f"Bearer {api_key}"},
    ):
        raise RuntimeError("PROXY_START_FAILED")
    return p


def start_tunnel(cloudflared: pathlib.Path):
    log_path = WORK / "cloudflared.log"
    log = open(log_path, "w", buffering=1)
    p = start_process(
        [str(cloudflared), "tunnel", "--url", f"http://127.0.0.1:{PROXY_PORT}", "--no-autoupdate"],
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    deadline = time.time() + 60
    pattern = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
    while time.time() < deadline:
        if p.poll() is not None:
            raise RuntimeError("CLOUDFLARED_EXITED")
        try:
            text = log_path.read_text(encoding="utf-8", errors="ignore")
            m = pattern.search(text)
            if m:
                return p, m.group(0)
        except FileNotFoundError:
            pass
        time.sleep(1)
    raise RuntimeError("TUNNEL_URL_TIMEOUT")


def get_github_token() -> str:
    from kaggle_secrets import UserSecretsClient
    token = UserSecretsClient().get_secret("GITHUB_SYNC_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_SYNC_TOKEN_NOT_ATTACHED")
    return token


def encrypt_secret(public_key_b64: str, value: str) -> str:
    key = public.PublicKey(public_key_b64.encode("utf-8"), encoding.Base64Encoder())
    encrypted = public.SealedBox(key).encrypt(value.encode("utf-8"))
    return base64.b64encode(encrypted).decode("utf-8")


def sync_github_secrets(github_token: str, base_url: str, api_key: str):
    headers = {
        "Authorization": f"Bearer {github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    root = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/actions/secrets"
    pk = requests.get(f"{root}/public-key", headers=headers, timeout=30)
    pk.raise_for_status()
    key_info = pk.json()
    for name, value in {"KAGGLE_BASE_URL": base_url, "KAGGLE_API_KEY": api_key}.items():
        r = requests.put(
            f"{root}/{name}",
            headers=headers,
            json={
                "encrypted_value": encrypt_secret(key_info["key"], value),
                "key_id": key_info["key_id"],
            },
            timeout=30,
        )
        r.raise_for_status()
    print("GITHUB_ENDPOINT_SECRET_SYNC: PASS", flush=True)


def get_remote_state():
    r = requests.get(CONTROL_URL, params={"t": str(time.time_ns())}, timeout=15, headers={"Cache-Control": "no-cache"})
    r.raise_for_status()
    return r.json()


def load_runtime_config():
    path = pathlib.Path(__file__).with_name("runtime_config.json")
    if not path.exists():
        raise RuntimeError("RUNTIME_CONFIG_MISSING")
    return json.loads(path.read_text(encoding="utf-8"))


def validate_public_health(tunnel_url: str, api_key: str) -> bool:
    return wait_http(
        f"{tunnel_url}/health",
        timeout=45,
        headers={"Authorization": f"Bearer {api_key}"},
    )


def main():
    cfg = load_runtime_config()
    generation = int(cfg["generation"])
    max_runtime = int(cfg.get("max_runtime_seconds", 21600))

    initial = get_remote_state()
    if initial.get("desired") != "RUN" or int(initial.get("generation", -1)) != generation:
        print("CONTROL_STATE_NOT_RUN: EXIT", flush=True)
        return

    github_token = get_github_token()
    cloudflared = install_runtime()
    ollama_proc = start_ollama()
    ensure_model()

    api_key = secrets.token_urlsafe(40)
    proxy_proc = start_proxy(api_key)
    tunnel_proc, tunnel_url = start_tunnel(cloudflared)
    if not validate_public_health(tunnel_url, api_key):
        raise RuntimeError("PUBLIC_TUNNEL_HEALTH_FAILED")
    sync_github_secrets(github_token, f"{tunnel_url}/v1", api_key)

    print(f"WORKER_GENERATION={generation}", flush=True)
    print("KAGGLE_GPU_WORKER: READY", flush=True)
    started = time.time()

    while time.time() - started < max_runtime:
        try:
            state = get_remote_state()
            if state.get("desired") != "RUN" or int(state.get("generation", -1)) != generation:
                print("CONTROL_STOP_OR_REPLACED: EXIT", flush=True)
                break
        except Exception as exc:
            print(f"CONTROL_POLL_WARNING={type(exc).__name__}", flush=True)

        # Keep local services alive.
        if ollama_proc.poll() is not None:
            print("OLLAMA_WATCHDOG_RESTART", flush=True)
            ollama_proc = start_ollama()
        if proxy_proc.poll() is not None:
            print("PROXY_WATCHDOG_RESTART", flush=True)
            proxy_proc = start_proxy(api_key)

        # Quick Tunnels are ephemeral. If one dies, create a new one and refresh GitHub secrets.
        if tunnel_proc.poll() is not None:
            print("TUNNEL_WATCHDOG_RESTART", flush=True)
            tunnel_proc, tunnel_url = start_tunnel(cloudflared)
            if validate_public_health(tunnel_url, api_key):
                sync_github_secrets(github_token, f"{tunnel_url}/v1", api_key)
            else:
                raise RuntimeError("TUNNEL_RESTART_HEALTH_FAILED")

        time.sleep(30)
    else:
        print("MAX_RUNTIME_REACHED: EXIT", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"KAGGLE_GPU_WORKER_FATAL={type(exc).__name__}:{exc}", flush=True)
        raise
