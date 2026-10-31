#!/usr/bin/env bash
set -euo pipefail

echo 'REMOTE_TERMINAL_PASS'
echo "UTC: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "Kernel: $(uname -a)"
echo "CPU cores: $(nproc)"
echo 'Memory:'
free -h

if [[ -z "${NEON_DATABASE_URL:-}" ]]; then
  echo 'G003_NEON_DATABASE_URL=NOT_CONFIGURED'
  exit 0
fi

python3 -m pip install --disable-pip-version-check --no-input --quiet 'psycopg[binary]>=3.2,<4'
python3 scripts/g003_pg_connection_probe.py
