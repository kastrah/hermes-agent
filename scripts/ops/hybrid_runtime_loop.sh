#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

echo "=== Hybrid Runtime Ops Loop ==="
date -Is

echo
echo "[1/3] Running health check..."
bash scripts/ops/hybrid_runtime_healthcheck.sh

echo
echo "[2/3] Quick RAM snapshot (Hetzner)..."
ssh -o ConnectTimeout=8 root@ubuntu-4gb-nbg1-1.taildc14a1.ts.net 'free -h; echo ---; ps -eo pid,cmd,%mem,%cpu --sort=-%mem | head -n 12'

echo
echo "[3/3] Backup runner status (Hetzner)..."
ssh -o ConnectTimeout=8 root@ubuntu-4gb-nbg1-1.taildc14a1.ts.net 'tail -n 20 /root/.hermes/logs/r2_backup.log 2>/dev/null || echo "No backup log yet"'

echo
echo "Loop complete. Update TODO board: docs/migration/2026-04-19-hybrid-runtime-ops-loop.md"
