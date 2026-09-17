import json
import os
import pathlib
import shutil
import subprocess
import time
import traceback

import requests

INPUT_ROOT = pathlib.Path('/kaggle/input')
WORK = pathlib.Path('/kaggle/working')
LOCAL_MODELS = WORK / 'qwen14-ollama-models'
BASE_MODEL = 'qwen2.5-coder:14b-instruct-q4_K_M'
TEST_MODEL = 'qwen14-hermes-bench'
OLLAMA_URL = 'http://127.0.0.1:11434'


def run(cmd, **kwargs):
    return subprocess.run(cmd, check=True, text=True, **kwargs)


def wait_http(url, timeout=90):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if requests.get(url, timeout=3).ok:
                return True
        except Exception:
            pass
        time.sleep(2)
    return False


def discover_cache_root() -> pathlib.Path:
    if not INPUT_ROOT.exists():
        raise RuntimeError(f'KAGGLE_INPUT_MISSING:{INPUT_ROOT}')

    top = sorted(str(p) for p in INPUT_ROOT.iterdir())
    print('QWEN14_INPUT_DIRS=' + json.dumps(top), flush=True)

    # Primary discovery: identify our cache by its own index, independent of
    # whatever mount directory name Kaggle assigns to the dataset.
    for index_path in INPUT_ROOT.rglob('cache-index.json'):
        try:
            data = json.loads(index_path.read_text(encoding='utf-8'))
        except Exception:
            continue
        if data.get('base_model') == BASE_MODEL:
            root = index_path.parent
            manifest = root / 'base-manifest.json'
            blobs = list(root.glob('sha256-*'))
            if manifest.is_file() and blobs:
                print(f'QWEN14_CACHE_ROOT={root}', flush=True)
                return root

    # Defensive fallback for a cache produced by an older builder without an
    # index file. Only accept an unambiguous manifest+blob directory.
    candidates = []
    for manifest in INPUT_ROOT.rglob('base-manifest.json'):
        root = manifest.parent
        if list(root.glob('sha256-*')):
            candidates.append(root)
    if len(candidates) == 1:
        print(f'QWEN14_CACHE_ROOT={candidates[0]}', flush=True)
        return candidates[0]

    discovered = sorted(str(p) for p in INPUT_ROOT.rglob('cache-index.json'))
    raise RuntimeError(
        'QWEN14_CACHE_DISCOVERY_FAILED:'
        f'indexes={discovered}:candidates={[str(p) for p in candidates]}'
    )


def stage_cache():
    cache_root = discover_cache_root()
    manifest_src = cache_root / 'base-manifest.json'
    blobs = sorted(cache_root.glob('sha256-*'))
    if not manifest_src.exists() or not blobs:
        raise RuntimeError('CACHE_INCOMPLETE')

    blobs_dir = LOCAL_MODELS / 'blobs'
    manifest_dir = LOCAL_MODELS / 'manifests' / 'registry.ollama.ai' / 'library' / 'qwen2.5-coder'
    blobs_dir.mkdir(parents=True, exist_ok=True)
    manifest_dir.mkdir(parents=True, exist_ok=True)

    for src in blobs:
        dst = blobs_dir / src.name
        if dst.exists() or dst.is_symlink():
            dst.unlink()
        dst.symlink_to(src)
    shutil.copy2(manifest_src, manifest_dir / '14b-instruct-q4_K_M')
    print(f'QWEN14_CACHE_STAGE: PASS blobs={len(blobs)}', flush=True)


def install_ollama():
    # Kaggle images can vary. zstd is needed by the Ollama installer on some
    # images, so install it only when absent.
    if shutil.which('zstd') is None:
        run(['bash', '-lc', 'apt-get update -qq && apt-get install -y -qq zstd'])
    run(['bash', '-lc', 'curl -fsSL https://ollama.com/install.sh | sh'])


def start_ollama():
    env = os.environ.copy()
    env.update({
        'OLLAMA_MODELS': str(LOCAL_MODELS),
        'OLLAMA_HOST': '127.0.0.1:11434',
        'OLLAMA_KEEP_ALIVE': '-1',
        'OLLAMA_NUM_PARALLEL': '1',
    })
    log = open(WORK / 'qwen14_ollama.log', 'w', buffering=1)
    proc = subprocess.Popen(['ollama', 'serve'], env=env, stdout=log, stderr=subprocess.STDOUT, text=True)
    if not wait_http(f'{OLLAMA_URL}/api/tags', 90):
        raise RuntimeError('OLLAMA_START_FAILED')
    return proc, env


def create_test_model(env):
    # Strict cache-only validation: no `ollama pull` is allowed here.
    run(['ollama', 'show', BASE_MODEL], env=env, stdout=subprocess.DEVNULL)
    print('QWEN14_MODEL_SHOW: PASS', flush=True)
    modelfile = WORK / 'Modelfile.qwen14'
    modelfile.write_text(f'FROM {BASE_MODEL}\nPARAMETER num_ctx 16384\n', encoding='utf-8')
    run(['ollama', 'create', TEST_MODEL, '-f', str(modelfile)], env=env)


def chat(payload, timeout=300):
    r = requests.post(f'{OLLAMA_URL}/api/chat', json=payload, timeout=timeout)
    r.raise_for_status()
    return r.json()


def tps(resp):
    count = float(resp.get('eval_count') or 0)
    dur = float(resp.get('eval_duration') or 0)
    return count / (dur / 1e9) if count and dur else 0.0


def main():
    result = {
        'model': TEST_MODEL,
        'base_model': BASE_MODEL,
        'context': 16384,
        'tool_trials': 5,
    }
    stage_cache()
    install_ollama()
    proc, env = start_ollama()
    try:
        create_test_model(env)

        warm = chat({
            'model': TEST_MODEL,
            'messages': [{'role': 'user', 'content': 'Reply exactly QWEN14_BASIC_PASS'}],
            'stream': False,
            'options': {'temperature': 0},
        })
        text = (warm.get('message') or {}).get('content', '').strip()
        basic_ok = 'QWEN14_BASIC_PASS' in text
        result['basic_ok'] = basic_ok
        result['basic_seconds'] = round((warm.get('total_duration') or 0) / 1e9, 3)
        result['basic_tps'] = round(tps(warm), 2)
        print(f'QWEN14_BASIC: {"PASS" if basic_ok else "FAIL"}', flush=True)

        tool_schema = [{
            'type': 'function',
            'function': {
                'name': 'terminal_echo',
                'description': 'Echo one exact test token in a terminal.',
                'parameters': {
                    'type': 'object',
                    'properties': {'token': {'type': 'string'}},
                    'required': ['token'],
                },
            },
        }]
        successes = 0
        tool_seconds = []
        tool_tps = []
        for i in range(1, 6):
            token = f'QWEN_TOOL_PASS_{i}'
            started = time.time()
            resp = chat({
                'model': TEST_MODEL,
                'messages': [{
                    'role': 'user',
                    'content': f'Use the terminal_echo tool exactly once with token {token}. Do not answer in prose.',
                }],
                'tools': tool_schema,
                'stream': False,
                'options': {'temperature': 0},
            })
            elapsed = time.time() - started
            tool_seconds.append(round(elapsed, 3))
            tool_tps.append(round(tps(resp), 2))
            calls = (resp.get('message') or {}).get('tool_calls') or []
            ok = False
            if len(calls) == 1:
                fn = calls[0].get('function') or {}
                args = fn.get('arguments') or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = {}
                ok = fn.get('name') == 'terminal_echo' and args.get('token') == token
            successes += int(ok)
            print(f'QWEN14_TOOL_TRIAL_{i}: {"PASS" if ok else "FAIL"}', flush=True)

        result['tool_successes'] = successes
        result['tool_seconds'] = tool_seconds
        result['tool_tps'] = tool_tps
        print(f'QWEN14_TOOL_CALLS={successes}/5', flush=True)
        print(f'QWEN14_TOOL_CALLING: {"PASS" if successes == 5 else "FAIL"}', flush=True)

        code = chat({
            'model': TEST_MODEL,
            'messages': [{
                'role': 'user',
                'content': 'Return only Python code for a function named dedupe_keep_order(items) that removes duplicates while preserving first occurrence order.',
            }],
            'stream': False,
            'options': {'temperature': 0},
        })
        code_text = (code.get('message') or {}).get('content', '')
        code_ok = 'def dedupe_keep_order' in code_text and ('set(' in code_text or 'seen' in code_text)
        result['code_ok'] = code_ok
        result['code_seconds'] = round((code.get('total_duration') or 0) / 1e9, 3)
        result['code_tps'] = round(tps(code), 2)
        print(f'QWEN14_CODE: {"PASS" if code_ok else "FAIL"}', flush=True)

        try:
            smi = subprocess.check_output([
                'nvidia-smi', '--query-gpu=index,name,memory.used,memory.total,utilization.gpu',
                '--format=csv,noheader,nounits'
            ], text=True).strip().splitlines()
            result['gpu'] = smi
            for line in smi:
                print(f'QWEN14_GPU={line}', flush=True)
        except Exception as exc:
            result['gpu_error'] = type(exc).__name__

        passed = bool(basic_ok and code_ok and successes == 5)
        result['pass'] = passed
        (WORK / 'qwen14_benchmark.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
        print(f'QWEN14_BENCHMARK: {"PASS" if passed else "FAIL"}', flush=True)
        if not passed:
            raise SystemExit(2)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()


if __name__ == '__main__':
    try:
        main()
    except BaseException as exc:
        failure = {
            'error_type': type(exc).__name__,
            'error': str(exc),
            'traceback': traceback.format_exc(),
        }
        (WORK / 'qwen14_failure.json').write_text(json.dumps(failure, indent=2) + '\n', encoding='utf-8')
        print(f'QWEN14_FATAL={type(exc).__name__}:{exc}', flush=True)
        raise
