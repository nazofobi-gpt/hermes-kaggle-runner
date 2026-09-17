#!/usr/bin/env bash
set -euo pipefail

: "${KAGGLE_BASE_URL:?KAGGLE_BASE_URL is required}"
: "${KAGGLE_API_KEY:?KAGGLE_API_KEY is required}"

TASK_FILE="${1:-requests/hermes_task.txt}"
if [[ ! -f "$TASK_FILE" ]]; then
  echo "TASK_FILE_MISSING: $TASK_FILE" >&2
  exit 2
fi

TASK=$(cat "$TASK_FILE")
if [[ -z "${TASK//[[:space:]]/}" ]]; then
  echo "TASK_EMPTY" >&2
  exit 2
fi

export PATH="$HOME/.local/bin:$PATH"
export HERMES_HOME="$RUNNER_TEMP/hermes-home"
export NO_COLOR=1
mkdir -p "$HERMES_HOME"
chmod 700 "$HERMES_HOME"

printf '%s\n' '=== Install Hermes Agent ==='
curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash -s -- \
  --skip-setup \
  --skip-browser \
  --skip-computer-use \
  --no-skills \
  --non-interactive

export PATH="$HOME/.local/bin:$PATH"
command -v hermes
hermes --version || true

printf '%s\n' '=== Configure Kaggle custom endpoint ==='
python3 - <<'PY'
import json, os, pathlib
home = pathlib.Path(os.environ['HERMES_HOME'])
home.mkdir(parents=True, exist_ok=True)
config = {
    "model": {
        "default": "llama3.1-hermes",
        "provider": "custom",
        "base_url": os.environ["KAGGLE_BASE_URL"].rstrip("/"),
        "api_key": os.environ["KAGGLE_API_KEY"],
        "context_length": 65536,
    },
    "terminal": {
        "backend": "local",
        "cwd": os.environ.get("GITHUB_WORKSPACE", "."),
        "timeout": 120,
    },
}
path = home / "config.yaml"
path.write_text(json.dumps(config, indent=2), encoding="utf-8")
path.chmod(0o600)
print("HERMES_CONFIG_WRITTEN")
print("MODEL=llama3.1-hermes")
print("CONTEXT_LENGTH=65536")
print("Secrets were not printed.")
PY

TASK_SHA=$(printf '%s' "$TASK" | sha256sum | awk '{print $1}')
echo "TASK_SHA256=$TASK_SHA"

# Public-repo guardrail: the agent may use normal workspace tools, but must never
# inspect or print runner secrets, environment variables, or Hermes credentials.
SAFE_PREFIX='PUBLIC RUNNER SECURITY RULES: Do not inspect, print, copy, enumerate, or expose environment variables, GitHub Actions secrets, API keys, tokens, ~/.hermes, HERMES_HOME, credential files, or authentication headers. Do not run env, printenv, set, export, or commands intended to discover secrets. Work only on the requested non-sensitive task and ordinary files in the checked-out repository. If the task asks for secrets or private data, refuse that part.'
FULL_TASK="$SAFE_PREFIX

USER TASK:
$TASK"

printf '%s\n' '=== Hermes task execution ==='
set +e
OUTPUT=$(timeout 600s hermes chat -q "$FULL_TASK" 2>&1)
RC=$?
set -e

printf '%s\n' 'HERMES_TASK_OUTPUT_BEGIN'
printf '%s\n' "$OUTPUT"
printf '%s\n' 'HERMES_TASK_OUTPUT_END'

if [[ "$RC" -ne 0 ]]; then
  echo "HERMES_TASK: FAIL rc=$RC"
  exit "$RC"
fi

echo 'HERMES_TASK: PASS'
