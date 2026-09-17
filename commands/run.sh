#!/usr/bin/env bash
set -euo pipefail

echo 'REMOTE_TERMINAL_PASS'
echo "UTC: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "Kernel: $(uname -a)"
echo "CPU cores: $(nproc)"
echo 'Memory:'
free -h
