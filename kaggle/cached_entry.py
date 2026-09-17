import os
import pathlib
import shutil
import subprocess

CACHE_ROOT = pathlib.Path("/kaggle/input/hermes-ollama-cache")
LOCAL_MODELS = pathlib.Path("/kaggle/working/ollama-models")
BASE_MODEL_DIR = LOCAL_MODELS / "manifests" / "registry.ollama.ai" / "library" / "llama3.1"
BASE_TAG = "8b-instruct-q4_K_M"


def stage_persistent_cache() -> None:
    if not CACHE_ROOT.exists():
        raise RuntimeError(f"MODEL_CACHE_DATASET_MISSING:{CACHE_ROOT}")

    manifest_src = CACHE_ROOT / "base-manifest.json"
    blob_sources = sorted(CACHE_ROOT.glob("sha256-*"))
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
    print(f"MODEL_CACHE_STAGE: PASS blobs={len(blob_sources)}", flush=True)


stage_persistent_cache()

import worker  # noqa: E402


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


worker.ensure_model = ensure_model_from_cache

if __name__ == "__main__":
    worker.main()
