#!/usr/bin/env bash
set -euo pipefail

HERMES_HOST="${HERMES_HOST:-ubuntu-4gb-nbg1-1.taildc14a1.ts.net}"
HERMES_SSH_USER="${HERMES_SSH_USER:-root}"
SUPABASE_URL="${SUPABASE_URL:-}"
SUPABASE_SERVICE_ROLE_KEY="${SUPABASE_SERVICE_ROLE_KEY:-}"

ok() { printf "[OK] %s\n" "$*"; }
warn() { printf "[WARN] %s\n" "$*"; }
fail() { printf "[FAIL] %s\n" "$*"; exit 1; }

# 1) SSH reachability
if ssh -o ConnectTimeout=8 "${HERMES_SSH_USER}@${HERMES_HOST}" 'hostname >/dev/null'; then
  ok "Hetzner SSH reachable"
else
  fail "Hetzner SSH unreachable"
fi

# 2) Gateway process + state
if ssh -o ConnectTimeout=8 "${HERMES_SSH_USER}@${HERMES_HOST}" "pgrep -af '[h]ermes_cli.main gateway run' >/dev/null"; then
  ok "Hetzner gateway process running"
else
  fail "Hetzner gateway process not running"
fi

state_json="$(ssh -o ConnectTimeout=8 "${HERMES_SSH_USER}@${HERMES_HOST}" 'cat /root/.hermes/gateway_state.json 2>/dev/null || true')"
if [[ -n "${state_json}" ]]; then
  echo "${state_json}" | python3 - <<'PY'
import json, sys
s=json.load(sys.stdin)
if s.get('gateway_state')!='running':
    print('[WARN] gateway_state is not running')
else:
    print('[OK] gateway_state is running')
platforms=s.get('platforms',{})
for p in ('telegram','discord'):
    if p in platforms:
        st=platforms[p].get('state')
        if st=='connected':
            print(f'[OK] {p} connected')
        else:
            print(f'[WARN] {p} state={st}')
    else:
        print(f'[WARN] {p} missing from gateway_state')
PY
else
  warn "gateway_state.json missing"
fi

# 3) Supabase event log reachability (optional)
if [[ -n "${SUPABASE_URL}" && -n "${SUPABASE_SERVICE_ROLE_KEY}" ]]; then
  code="$(curl -sS -o /tmp/hybrid_supa_health.out -w '%{http_code}' \
    "${SUPABASE_URL}/rest/v1/event_log?select=id&limit=1" \
    -H "apikey: ${SUPABASE_SERVICE_ROLE_KEY}" \
    -H "Authorization: Bearer ${SUPABASE_SERVICE_ROLE_KEY}")"
  if [[ "${code}" == "200" ]]; then
    ok "Supabase event_log reachable"
  else
    warn "Supabase event_log check returned HTTP ${code}"
  fi
else
  warn "Supabase env vars not set; skipping Supabase check"
fi

# 4) Local conflict check
if pgrep -af '[h]ermes_cli.main gateway run' >/dev/null; then
  warn "Local gateway process detected; ensure no polling conflict"
else
  ok "No local gateway process detected"
fi

echo "Health check completed"
