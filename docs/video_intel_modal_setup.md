# Video Intel on Modal (TRIBE + SAM + Gemma)

This setup runs heavy video analysis on Modal while Hermes remains your orchestrator.

## Files

- Modal app: `scripts/modal_video_intel_app.py`
- Bootstrap script: `scripts/setup_video_intel_modal.sh`

## Required Secrets

- `MODAL_TOKEN_ID`
- `MODAL_TOKEN_SECRET`
- `HUGGINGFACE_HUB_TOKEN`

## Quick Start

```bash
export MODAL_TOKEN_ID=...
export MODAL_TOKEN_SECRET=...
export HUGGINGFACE_HUB_TOKEN=...

bash scripts/setup_video_intel_modal.sh
```

This script will:

1. Install Modal SDK if needed.
2. Authenticate Modal CLI.
3. Create/update Modal secret `video-intel-secrets`.
4. Run `ping` health check.
5. Deploy the app.

## Notes

- Gemma is the orchestration layer: it consumes ingest/SAM/TRIBE signals and returns structured JSON analysis.
- A thin deterministic layer only validates and normalizes model output schema.
- Model loading is soft-fail by design so deployment succeeds even if upstream model APIs shift.
- Current known limitation: `facebook/tribev2` may fall back to proxy saliency if the repo does not expose a compatible processor/model API for `transformers`.
