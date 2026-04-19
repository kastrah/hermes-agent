# Hybrid Runtime: Arguments Against + Mitigations

Date: 2026-04-19

## 1) "Too many moving parts"
Mitigation:
- Explicit ownership by layer (runtime vs durable log vs backups).
- One runbook and one health-check command.

## 2) "Debugging becomes harder"
Mitigation:
- Use `event_id` correlation in logs/queue/Supabase.
- Keep append-only event log in Supabase.

## 3) "Latency gets worse"
Mitigation:
- Keep direct user-response path on Hetzner runtime.
- Use queue path for async/background work only.

## 4) "Consistency drift"
Mitigation:
- Single writer rule for each data domain.
- Idempotent processors keyed by `event_id`.

## 5) "Costs creep"
Mitigation:
- Stop unused services (Modal kept stopped).
- Keep queue consumers disabled unless needed.
- Retention + archive policy to R2.
