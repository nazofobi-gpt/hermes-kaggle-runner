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
DYNAMIC_FIXTURE="no"
TASK="$RAW_TASK"
if grep -q '^---$' "$TASK_FILE"; then
  MODE=$(sed -n 's/^MODE:[[:space:]]*//p' "$TASK_FILE" | head -n1)
  EXPECT=$(sed -n 's/^EXPECT:[[:space:]]*//p' "$TASK_FILE" | head -n1)
  DYNAMIC_FIXTURE=$(sed -n 's/^DYNAMIC_FIXTURE:[[:space:]]*//p' "$TASK_FILE" | head -n1)
  TASK=$(sed '1,/^---$/d' "$TASK_FILE")
  MODE="${MODE:-auto}"
  DYNAMIC_FIXTURE="${DYNAMIC_FIXTURE:-no}"
fi

case "$MODE" in
  auto|chat|terminal) ;;
  *) echo "TASK_MODE_INVALID: $MODE" >&2; exit 2 ;;
esac
case "$DYNAMIC_FIXTURE" in
  yes|no) ;;
  *) echo "DYNAMIC_FIXTURE_INVALID: $DYNAMIC_FIXTURE" >&2; exit 2 ;;
esac

if [[ -z "${TASK//[[:space:]]/}" ]]; then
  echo "TASK_BODY_EMPTY" >&2
  exit 2
fi

echo "TASK_MODE=$MODE"
echo "TASK_DYNAMIC_FIXTURE=$DYNAMIC_FIXTURE"

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
# Remove them before any agent-controlled terminal command is possible.
unset KAGGLE_API_KEY
unset KAGGLE_BASE_URL

# Optional runtime-only fixture used by the acceptance task. The random value is
# never included in the prompt. Acceptance is based on a filesystem side effect,
# not on trusting the model's final prose.
if [[ "$DYNAMIC_FIXTURE" == "yes" ]]; then
  DYNAMIC_VALUE="HERMES_TASK_FIXTURE_$(python3 - <<'PY'
import secrets
print(secrets.token_hex(16).upper())
PY
)"
  printf '%s\n' "$DYNAMIC_VALUE" > .hermes-task-fixture
  chmod 600 .hermes-task-fixture
  rm -f .hermes-task-observed
  echo 'TASK_EXPECTATION_CONFIGURED=dynamic-side-effect'
elif [[ -n "$EXPECT" ]]; then
  echo 'TASK_EXPECTATION_CONFIGURED=static-final-output'
else
  echo 'TASK_EXPECTATION_CONFIGURED=no'
fi

TASK_SHA=$(printf '%s' "$TASK" | sha256sum | awk '{print $1}')
echo "TASK_SHA256=$TASK_SHA"

run_hermes() {
  local prompt="$1"
  set +e
  HERMES_OUTPUT=$(timeout 600s hermes chat -q "$prompt" 2>&1)
  HERMES_RC=$?
  set -e
}

has_real_tool_call() {
  grep -Eq 'Messages:.*[1-9][0-9]* tool calls' <<<"$1"
}

# Phase A: prove real terminal execution with a side effect. The model does not
# need to repeat or interpret the random value correctly; the shell validates
# the file produced by the command that Hermes actually executed.
PROOF="HERMES_RUN_PROOF_$(python3 - <<'PY'
import secrets
print(secrets.token_hex(16).upper())
PY
)"
printf '%s\n' "$PROOF" > .hermes-proof-token
chmod 600 .hermes-proof-token
cat > .hermes-proof-command.sh <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
cat .hermes-proof-token > .hermes-proof-result
EOF
chmod 700 .hermes-proof-command.sh
rm -f .hermes-proof-result

PROOF_PROMPT='Terminal aracını gerçekten kullan ve çalışma klasöründe ./.hermes-proof-command.sh komutunu çalıştır. Komutu açıklama veya JSON olarak yazmak yeterli değil; terminal toolunu çağır. Son cevap kısa olsun.'

printf '%s\n' '=== Hermes execution proof ==='
run_hermes "$PROOF_PROMPT"
PROOF_OUTPUT="$HERMES_OUTPUT"
PROOF_RC="$HERMES_RC"

if [[ "$PROOF_RC" -eq 0 ]] && { [[ ! -f .hermes-proof-result ]] || ! cmp -s .hermes-proof-token .hermes-proof-result || ! has_real_tool_call "$PROOF_OUTPUT"; }; then
  echo 'HERMES_EXECUTION_PROOF_RETRY: required side effect or real tool call missing'
  RECOVERY='Terminal toolunu şimdi gerçekten çağır ve sadece ./.hermes-proof-command.sh komutunu çalıştır. Komut tamamlanınca kısa bir cevap ver.'
  run_hermes "$RECOVERY"
  PROOF_OUTPUT="$HERMES_OUTPUT"
  PROOF_RC="$HERMES_RC"
fi

printf '%s\n' 'HERMES_PROOF_OUTPUT_BEGIN'
printf '%s\n' "$PROOF_OUTPUT"
printf '%s\n' 'HERMES_PROOF_OUTPUT_END'

if [[ "$PROOF_RC" -ne 0 ]]; then
  echo "HERMES_EXECUTION_PROOF: FAIL rc=$PROOF_RC"
  rm -f .hermes-proof-token .hermes-proof-result .hermes-proof-command.sh
  exit "$PROOF_RC"
fi
if [[ ! -f .hermes-proof-result ]] || ! cmp -s .hermes-proof-token .hermes-proof-result; then
  echo 'HERMES_EXECUTION_PROOF: FAIL side-effect mismatch'
  rm -f .hermes-proof-token .hermes-proof-result .hermes-proof-command.sh
  exit 1
fi
if ! has_real_tool_call "$PROOF_OUTPUT"; then
  echo 'HERMES_EXECUTION_PROOF: FAIL no real tool call recorded'
  rm -f .hermes-proof-token .hermes-proof-result .hermes-proof-command.sh
  exit 1
fi
rm -f .hermes-proof-token .hermes-proof-result .hermes-proof-command.sh
echo 'HERMES_EXECUTION_PROOF: PASS'

# Phase B: run the actual public task in a fresh Hermes invocation.
printf '%s\n' '=== Hermes public task ==='
run_hermes "$TASK"
TASK_OUTPUT="$HERMES_OUTPUT"
TASK_RC="$HERMES_RC"

needs_retry=0
if [[ "$MODE" == "terminal" ]] && ! has_real_tool_call "$TASK_OUTPUT"; then
  needs_retry=1
fi
if grep -Eq '\{"name"[[:space:]]*:[[:space:]]*"terminal"' <<<"$TASK_OUTPUT" && ! has_real_tool_call "$TASK_OUTPUT"; then
  needs_retry=1
fi

if [[ "$TASK_RC" -eq 0 && "$needs_retry" -eq 1 ]]; then
  echo 'HERMES_TASK_RETRY: real terminal call missing'
  RECOVERY_PREFIX='Bu görev gerçek Hermes terminal aracını kullanmanı gerektiriyor. Terminal çağrısını JSON, kod veya açıklama olarak yazma; terminal toolunu gerçekten çağır ve sonucu gözlemle.'
  run_hermes "$RECOVERY_PREFIX

$TASK"
  TASK_OUTPUT="$HERMES_OUTPUT"
  TASK_RC="$HERMES_RC"
fi

printf '%s\n' 'HERMES_TASK_OUTPUT_BEGIN'
printf '%s\n' "$TASK_OUTPUT"
printf '%s\n' 'HERMES_TASK_OUTPUT_END'

if [[ "$TASK_RC" -ne 0 ]]; then
  echo "HERMES_TASK: FAIL rc=$TASK_RC"
  rm -f .hermes-task-fixture .hermes-task-observed
  exit "$TASK_RC"
fi
if [[ "$MODE" == "terminal" ]] && ! has_real_tool_call "$TASK_OUTPUT"; then
  echo 'HERMES_TASK: FAIL terminal mode required a real tool call'
  rm -f .hermes-task-fixture .hermes-task-observed
  exit 1
fi

if [[ "$DYNAMIC_FIXTURE" == "yes" ]]; then
  if [[ ! -f .hermes-task-observed ]] || ! cmp -s .hermes-task-fixture .hermes-task-observed; then
    echo 'HERMES_TASK: FAIL dynamic side-effect mismatch'
    rm -f .hermes-task-fixture .hermes-task-observed
    exit 1
  fi
  echo 'HERMES_TASK_DYNAMIC_SIDE_EFFECT: PASS'
elif [[ -n "$EXPECT" ]] && ! grep -Fxq "$EXPECT" <<<"$TASK_OUTPUT"; then
  echo 'HERMES_TASK: FAIL expected exact output line missing'
  exit 1
fi

rm -f .hermes-task-fixture .hermes-task-observed
echo 'HERMES_TASK_VALIDATION: PASS'
echo 'HERMES_TASK: PASS'
