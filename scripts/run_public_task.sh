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

# Runtime proof that cannot be guessed from the prompt. A successful task must
# actually invoke the terminal tool and read this file.
PROOF="HERMES_RUN_PROOF_$(python3 - <<'PY'
import secrets
print(secrets.token_hex(16).upper())
PY
)"
printf '%s\n' "$PROOF" > .hermes-run-proof
chmod 600 .hermes-run-proof

SAFE_PREFIX='PUBLIC RUNNER SECURITY RULES: Do not inspect, print, copy, enumerate, or expose environment variables, GitHub Actions secrets, API keys, tokens, ~/.hermes, HERMES_HOME, credential files, or authentication headers. Do not run env, printenv, set, export, or commands intended to discover secrets. Work only on the requested non-sensitive task and ordinary files in the checked-out repository. If the task asks for secrets or private data, refuse that part.'
PROOF_RULE='EXECUTION PROOF: Before giving the final answer, you MUST actually call the terminal tool and read the file .hermes-run-proof with a terminal command. Do not print a tool-call JSON as text. Include the exact file contents in the final answer. The proof value is not present in this prompt, so it cannot be guessed.'
FULL_TASK="$SAFE_PREFIX

USER TASK:
$TASK

$PROOF_RULE"

printf '%s\n' '=== Hermes task execution ==='
set +e
OUTPUT=$(timeout 600s hermes chat -q "$FULL_TASK" 2>&1)
RC=$?
set -e

printf '%s\n' 'HERMES_TASK_OUTPUT_BEGIN'
printf '%s\n' "$OUTPUT"
printf '%s\n' 'HERMES_TASK_OUTPUT_END'

rm -f .hermes-run-proof

if [[ "$RC" -ne 0 ]]; then
  echo "HERMES_TASK: FAIL rc=$RC"
  exit "$RC"
fi

if ! grep -Fq "$PROOF" <<<"$OUTPUT"; then
  echo 'HERMES_TASK: FAIL terminal proof missing'
  exit 1
fi

if ! grep -Eq 'Messages:.*[1-9][0-9]* tool calls' <<<"$OUTPUT"; then
  echo 'HERMES_TASK: FAIL no real tool call recorded'
  exit 1
fi

echo 'HERMES_TASK_TERMINAL_PROOF: PASS'
echo 'HERMES_TASK: PASS'
