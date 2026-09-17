#!/usr/bin/env bash
set -euo pipefail

: "${KAGGLE_BASE_URL:?KAGGLE_BASE_URL is required}"
: "${KAGGLE_API_KEY:?KAGGLE_API_KEY is required}"

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
        "timeout": 90,
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

printf '%s\n' '=== Basic Hermes chat acceptance ==='
set +e
BASIC_OUTPUT=$(timeout 240s hermes chat -q 'Sadece HERMES_AGENT_PASS yaz.' 2>&1)
BASIC_RC=$?
set -e
printf '%s\n' "$BASIC_OUTPUT"
if [ "$BASIC_RC" -ne 0 ]; then
  echo "HERMES_BASIC_CHAT: FAIL rc=$BASIC_RC"
  exit "$BASIC_RC"
fi
if ! grep -q 'HERMES_AGENT_PASS' <<<"$BASIC_OUTPUT"; then
  echo 'HERMES_BASIC_CHAT: FAIL expected marker missing'
  exit 1
fi
echo 'HERMES_BASIC_CHAT: PASS'

printf '%s\n' '=== Hermes real tool-call acceptance ==='
SENTINEL="HERMES_TOOL_$(python3 - <<'PY'
import secrets
print(secrets.token_hex(12).upper())
PY
)"
printf '%s\n' "$SENTINEL" > .hermes-tool-sentinel

TOOL_PROMPT='Terminal aracını kullan. Çalışma klasöründeki .hermes-tool-sentinel dosyasını terminal komutu ile oku. Son cevapta dosyanın içeriğini aynen yaz; tahmin etme.'
set +e
TOOL_OUTPUT=$(timeout 300s hermes chat -q "$TOOL_PROMPT" 2>&1)
TOOL_RC=$?
set -e
printf '%s\n' "$TOOL_OUTPUT"
rm -f .hermes-tool-sentinel

if [ "$TOOL_RC" -ne 0 ]; then
  echo "HERMES_TOOL_CALL: FAIL rc=$TOOL_RC"
  exit "$TOOL_RC"
fi
if ! grep -Fq "$SENTINEL" <<<"$TOOL_OUTPUT"; then
  echo 'HERMES_TOOL_CALL: FAIL sentinel not returned'
  exit 1
fi
echo 'HERMES_TOOL_CALL: PASS'

echo 'HERMES_GITHUB_KAGGLE_AGENT_ACCEPTANCE: PASS'
