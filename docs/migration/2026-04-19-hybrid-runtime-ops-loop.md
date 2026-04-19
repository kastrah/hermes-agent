# Hybrid Runtime Ops Loop (Hetzner + Cloudflare + Supabase)

Date: 2026-04-19
Status: Active
Owner: Kastrah

## Objective
Keep Hetzner as the runtime/gateway host while using Cloudflare + Supabase for durability and backups, with Modal disabled.

## Operating Model
- Hetzner: gateway runtime (Telegram/Discord), cron execution, tool runtime.
- Supabase: durable event/session/archive metadata.
- Cloudflare: edge/queue/R2 backup path.
- Modal: stopped unless explicitly re-enabled.

## Source-of-Truth Contract
- Live execution truth: Hetzner runtime.
- Durable event truth: Supabase `public.event_log`.
- Backup artifact truth: R2 objects + Supabase `public.backup_archive` metadata.
- Never run two Telegram polling gateways simultaneously.

## Loop TODO Board
Legend: `[ ]` todo, `[-]` in progress, `[x]` done

### Phase A: Stabilize (must stay green)
- [x] Hetzner SSH reachable.
- [x] Hetzner gateway process running.
- [x] Telegram and Discord connected on Hetzner.
- [x] Local gateway process stopped (no polling conflict).
- [x] Modal worker app stopped.

### Phase B: Memory/Cost control
- [ ] Inventory always-on services on Hetzner (`docker`, `ollama`, sidecars) and classify keep/stop.
- [ ] Stop non-essential resident services and record RAM deltas.
- [ ] Set max acceptable RAM target and swap guardrail.

### Phase C: Durability and backup
- [ ] Confirm nightly R2 backup job succeeds and logs success marker.
- [ ] Write backup object metadata to Supabase `public.backup_archive`.
- [ ] Run one restore drill and timestamp result in runbook.

### Phase D: Reliability guardrails
- [ ] Add one-command health check loop (`scripts/ops/hybrid_runtime_healthcheck.sh`).
- [ ] Configure alert policy for failed backup / gateway disconnected / queue backlog.
- [ ] Add weekly ops review cadence.

## Daily Loop
Run:
```bash
bash scripts/ops/hybrid_runtime_loop.sh
```

If any check fails:
1. Fix blocking gateway issue first.
2. Re-run health check until green.
3. Only then continue optimization work.

## Rollback Rule
If queue/DB offload introduces instability:
- Keep Hetzner runtime primary.
- Pause non-critical queue consumers.
- Continue backups and logging only.
