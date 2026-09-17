#!/usr/bin/env bash
set -euo pipefail

: "${KAGGLE_BASE_URL:?KAGGLE_BASE_URL is required}"
: "${KAGGLE_API_KEY:?KAGGLE_API_KEY is required}"

TASK_FILE="${1:-requests/hermes_task.txt}"
if [[ ! -f "$TASK_FILE" ]]; then
  echo "TASK_FILE_MISSING: $TASK_FILE" >&2
  exit 2
fi

RAW_TASK=$(cat "$TASK_FILE")
if [[ -z "${RAW_TASK//[[:space:]]/}" ]]; then
  echo "TASK_EMPTY" >&2
  exit 2
fi

MODE="auto"
EXPECT=""
TASK="$RAW_TASK"
if grep -q '^---$' "$TASK_FILE"; then
  MODE=$(sed -n 's/^MODE:[[:space:]]*//p' "$TASK_FILE" | head -n1)
  EXPECT=$(sed -n 's/^EXPECT:[[:space:]]*//p' "$TASK_FILE" | head -n1)
  TASK=$(sed '1,/^---$/d' "$TASK_FILE")
  MODE="${MODE:-auto}"
fi

case "$MODE" in
  auto|chat|terminal) ;;
  *) echo "TASK_MODE_INVALID: $MODE" >&2; exit 2 ;;
esac

if [[ -z "${TASK//[[:space:]]/}" ]]; then
  echo "TASK_BODY_EMPTY" >&2
  exit 2
fi

echo "TASK_MODE=$MODE"
if [[ -n "$EXPECT" ]]; then
  echo "TASK_EXPECTATION_CONFIGURED=yes"
else
  echo "TASK_EXPECTATION_CONFIGURED=no"
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
config_path = home / "config.yaml"
config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
config_path.chmod(0o600)

soul = """You are running inside a PUBLIC GitHub Actions runner.
Security rules are mandatory:
- Never inspect, enumerate, copy, reveal, or print environment variables, GitHub Actions secrets, API keys, tokens, authentication headers, credential files, ~/.hermes, HERMES_HOME contents, or config.yaml.
- Never run env, printenv, set, export, or commands whose purpose is secret discovery.
- Work only on the non-sensitive task and ordinary checked-out repository files.
- If asked for secrets, credentials, private user data, or hidden runner configuration, refuse that part.
- You may use normal terminal tools on the repository workspace when needed.
"""
soul_path = home / "SOUL.md"
soul_path.write_text(soul, encoding="utf-8")
soul_path.chmod(0o600)

print("HERMES_CONFIG_WRITTEN")
print("HERMES_SOUL_GUARDRAIL_WRITTEN")
print("MODEL=llama3.1-hermes")
print("CONTEXT_LENGTH=65536")
print("Secrets were not printed.")
PY

# Credentials are needed only to create Hermes' protected configuration.
# Remove them from the agent-controlled child process environment.
unset KAGGLE_API_KEY
unset KAGGLE_BASE_URL

TASK_SHA=$(printf '%s' "$TASK" | sha256sum | awk '{print $1}')
echo "TASK_SHA256=$TASK_SHA"

# Phase A: independent proof that this runner/model combination can execute a
# real Hermes terminal tool call. The random value is unknown to the model.
PROOF="HERMES_RUN_PROOF_$(python3 - <<'PY'
import secrets
print(secrets.token_hex(16).upper())
PY
)"
printf '%s\n' "$PROOF" > .hermes-run-proof
chmod 600 .hermes-run-proof
PROOF_PROMPT='Terminal aracını kullan. Çalışma klasöründeki .hermes-run-proof dosyasını terminal komutu ile oku. Son cevapta dosyanın içeriğini aynen yaz; tahmin etme.'

printf '%s\n' '=== Hermes execution proof ==='
set +e
PROOF_OUTPUT=$(timeout 240s hermes chat -q "$PROOF_PROMPT" 2>&1)
PROOF_RC=$?
set -e
printf '%s\n' 'HERMES_PROOF_OUTPUT_BEGIN'
printf '%s\n' "$PROOF_OUTPUT"
printf '%s\n' 'HERMES_PROOF_OUTPUT_END'
rm -f .hermes-run-proof

if [[ "$PROOF_RC" -ne 0 ]]; then
  echo "HERMES_EXECUTION_PROOF: FAIL rc=$PROOF_RC"
  exit "$PROOF_RC"
fi
if ! grep -Fq "$PROOF" <<<"$PROOF_OUTPUT"; then
  echo 'HERMES_EXECUTION_PROOF: FAIL sentinel missing'
  exit 1
fi
if ! grep -Eq 'Messages:.*[1-9][0-9]* tool calls' <<<"$PROOF_OUTPUT"; then
  echo 'HERMES_EXECUTION_PROOF: FAIL no real tool call recorded'
  exit 1
fi
echo 'HERMES_EXECUTION_PROOF: PASS'

run_task() {
  local prompt="$1"
  set +e
  TASK_OUTPUT=$(timeout 600s hermes chat -q "$prompt" 2>&1)
  TASK_RC=$?
  set -e
}

printf '%s\n' '=== Hermes public task ==='
run_task "$TASK"

needs_retry=0
if [[ "$MODE" == "terminal" ]] && ! grep -Eq 'Messages:.*[1-9][0-9]* tool calls' <<<"$TASK_OUTPUT"; then
  needs_retry=1
fi
if grep -Eq '\{"name"[[:space:]]*:[[:space:]]*"terminal"' <<<"$TASK_OUTPUT" && ! grep -Eq 'Messages:.*[1-9][0-9]* tool calls' <<<"$TASK_OUTPUT"; then
  needs_retry=1
fi

if [[ "$TASK_RC" -eq 0 && "$needs_retry" -eq 1 ]]; then
  echo 'HERMES_TASK_RETRY: terminal tool-call text detected or real terminal call missing'
  RECOVERY_PREFIX='Bu görev gerçek Hermes terminal aracını kullanmanı gerektiriyor. Terminal çağrısını JSON, kod veya açıklama olarak yazma. terminal toolunu gerçekten çağır, araç sonucunu gözlemle ve ancak sonra son cevabı ver.'
  run_task "$RECOVERY_PREFIX

$TASK"
fi

printf '%s\n' 'HERMES_TASK_OUTPUT_BEGIN'
printf '%s\n' "$TASK_OUTPUT"
printf '%s\n' 'HERMES_TASK_OUTPUT_END'

if [[ "$TASK_RC" -ne 0 ]]; then
  echo "HERMES_TASK: FAIL rc=$TASK_RC"
  exit "$TASK_RC"
fi

if [[ "$MODE" == "terminal" ]] && ! grep -Eq 'Messages:.*[1-9][0-9]* tool calls' <<<"$TASK_OUTPUT"; then
  echo 'HERMES_TASK: FAIL terminal mode required a real tool call'
  exit 1
fi

if [[ -n "$EXPECT" ]] && ! grep -Fxq "$EXPECT" <<<"$TASK_OUTPUT"; then
  echo 'HERMES_TASK: FAIL expected exact output line missing'
  exit 1
fi

echo 'HERMES_TASK_VALIDATION: PASS'
echo 'HERMES_TASK: PASS'
