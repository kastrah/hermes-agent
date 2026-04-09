# Dev Browser Runtime Migration Plan

## Goal

Adopt the strongest runtime ideas from `SawyerHood/dev-browser` without replacing the Hermes browser product surface all at once.

The target outcome is:

- Hermes keeps its current high-level browser tools and product behavior.
- Hermes gains a more capable local/CDP browser runtime.
- Runtime concerns become replaceable behind a stable interface.
- We can switch backends safely with config and tests.

## Recommendation

Do not do a wholesale replacement of the current Hermes browser framework with `dev-browser`.

Instead:

1. Keep the existing Hermes browser tool contract stable.
2. Introduce a backend/runtime adapter layer.
3. Add a `dev-browser`-style runtime as an optional backend first.
4. Migrate local and CDP execution to the new runtime incrementally.
5. Preserve Hermes-only capabilities above the runtime layer.

## Why Not Replace Everything

Hermes already owns product-level behavior that `dev-browser` does not:

- cloud provider abstraction
- Browserbase and Browser Use integration
- stealth/provider knobs
- website policy enforcement
- vision analysis and screenshot sharing
- session recording
- existing tool schemas and agent expectations

Those are valuable and already integrated into Hermes.

The main weakness in Hermes is not the product contract. It is the local/CDP execution layer, which is currently tightly coupled to `agent-browser` subprocess calls.

## What To Take From Dev Browser

### Core runtime ideas

- Named pages and explicit tab lifecycle
- Persistent browser profiles for launched browsers
- Better CDP auto-discovery and endpoint resolution
- A daemon-based request/response runtime instead of ad hoc subprocess invocation
- Incremental AI snapshots
- Sandboxed script execution
- Safer temp-file handling and better local IPC primitives

### What not to take verbatim

- A complete replacement of Hermes tool names and semantics
- A forced shift to full-script control for every browser task
- Removal of cloud-provider support

## Target Architecture

### Layer 1: Hermes browser tools

Keep the current public tool surface for compatibility:

- `browser_navigate`
- `browser_snapshot`
- `browser_click`
- `browser_type`
- `browser_scroll`
- `browser_back`
- `browser_press`
- `browser_console`
- `browser_get_images`
- `browser_vision`
- `browser_close`

These remain the default agent-facing primitives.

### Layer 2: Browser runtime interface

Introduce a runtime adapter interface used by `tools/browser_tool.py`.

Suggested shape:

```python
class BrowserRuntime(ABC):
    def get_or_create_session(self, task_id: str, mode: RuntimeMode) -> RuntimeSession: ...
    def navigate(self, session: RuntimeSession, url: str) -> dict: ...
    def snapshot(self, session: RuntimeSession, full: bool = False) -> dict: ...
    def click(self, session: RuntimeSession, ref: str) -> dict: ...
    def fill(self, session: RuntimeSession, ref: str, text: str) -> dict: ...
    def scroll(self, session: RuntimeSession, direction: str) -> dict: ...
    def back(self, session: RuntimeSession) -> dict: ...
    def press(self, session: RuntimeSession, key: str) -> dict: ...
    def console(self, session: RuntimeSession, clear: bool = False) -> dict: ...
    def errors(self, session: RuntimeSession, clear: bool = False) -> dict: ...
    def screenshot(self, session: RuntimeSession, path: str, annotate: bool = False) -> dict: ...
    def eval(self, session: RuntimeSession, code: str) -> dict: ...
    def close(self, session: RuntimeSession) -> dict: ...
```

This interface is intentionally close to today’s Hermes tool needs.

### Layer 3: Runtime implementations

Planned implementations:

- `AgentBrowserRuntime`
- `DevBrowserRuntime`

Potential future implementation:

- `PlaywrightNativeRuntime`

### Layer 4: Product-only augmentations

These stay in Hermes and wrap the runtime:

- website policy checks
- cloud provider selection
- first-nav feature reporting
- bot-detection hints
- snapshot summarization
- screenshot persistence
- vision model analysis
- session recordings
- inactivity cleanup policy

## Proposed File Structure

Suggested additions under `hermes-agent/tools/`:

```text
tools/
  browser_tool.py
  browser_runtime/
    __init__.py
    base.py
    session.py
    agent_browser_runtime.py
    dev_browser_runtime.py
    runtime_config.py
```

Optional if we vendor or integrate a daemon:

```text
tools/browser_runtime/dev_browser_daemon/
```

## Migration Phases

## Phase 0: Refactor for separation

Goal: isolate today’s `agent-browser` coupling without changing behavior.

Tasks:

1. Extract `_run_browser_command()` logic into `AgentBrowserRuntime`.
2. Move session bookkeeping into reusable runtime session helpers.
3. Keep `browser_tool.py` as orchestration plus response shaping.
4. Preserve all existing tool outputs.

Exit criteria:

- No behavior change for current browser tools.
- Existing browser tests still pass.

## Phase 1: Add runtime selection

Goal: allow Hermes to select a runtime backend by config.

Suggested config:

```yaml
browser:
  runtime: agent-browser
```

Accepted values initially:

- `agent-browser`
- `dev-browser`

Selection rules:

- Default to `agent-browser` until `dev-browser` proves stable.
- Allow override in config and environment for testing.

Exit criteria:

- Runtime selected via config.
- Hermes still behaves exactly as before when `agent-browser` is selected.

## Phase 2: Add DevBrowserRuntime for local and CDP modes

Goal: use a `dev-browser`-style backend for:

- local launched browsers
- live Chrome/CDP attached browsers

Scope:

- navigation
- snapshots
- click/fill/press/scroll/back
- console/errors
- screenshots
- eval
- close

Not in scope yet:

- cloud providers
- browser script sandbox exposed to agents

Exit criteria:

- Hermes high-level tools work on the new runtime in local mode.
- Hermes high-level tools work on the new runtime in CDP mode.

## Phase 3: Add named page primitives

Goal: expose the best page-lifecycle concepts from `dev-browser`.

New Hermes tools:

- `browser_list_pages`
- `browser_get_page`
- `browser_new_page`
- `browser_close_page`

Design notes:

- These should be additive, not replacements.
- Existing tools continue to operate on a default page if no page is selected.
- Task/session state should remember the active page.

Exit criteria:

- Agents can intentionally manage multiple tabs.
- CDP mode can attach to existing tabs by stable page identity.

## Phase 4: Improve snapshots

Goal: reduce token churn and improve long workflows.

Changes:

- Add runtime support for AI-oriented snapshots.
- Prefer incremental snapshots where the runtime supports them.
- Preserve current summarization fallback in Hermes.

Suggested response shape:

```json
{
  "success": true,
  "snapshot": "...full or reduced view...",
  "incremental": "...optional delta...",
  "element_count": 12
}
```

Exit criteria:

- Multi-step browser tasks send less repeated content.
- Snapshot output remains readable to existing agents.

## Phase 5: Add sandboxed browser scripts

Goal: add a new advanced tool for tasks that need programmable browser control.

Suggested new tool:

- `browser_script`

Suggested contract:

- Runs sandboxed JavaScript against the current session/page context
- Time-limited
- Memory-limited
- No arbitrary filesystem/network host access
- Can optionally access restricted temp artifact storage

Use cases:

- one-off DOM extraction
- complex locator logic
- multi-step client-side workflows
- structured extraction too awkward for fixed primitives

This should be additive and advanced, not the default path for normal browsing.

Exit criteria:

- Agents can solve edge cases without exploding the core tool surface.
- Runtime isolation is strong enough to trust in normal use.

## Phase 6: Revisit default backend

Only after Phases 2-4 are stable:

- compare local-mode reliability
- compare CDP attach reliability
- compare snapshot quality
- compare speed
- compare debugging burden

If the new runtime wins, change default local/CDP runtime to `dev-browser`.

Cloud mode can still remain provider-based and separate.

## Backend Strategy

The final backend map should likely be:

- local mode: `DevBrowserRuntime`
- CDP mode: `DevBrowserRuntime`
- cloud mode: existing provider flow, then either:
  - keep `agent-browser` for cloud execution initially, or
  - later teach `DevBrowserRuntime` to attach to provider CDP endpoints too

Recommended order:

1. Migrate local mode first
2. Migrate CDP mode second
3. Evaluate cloud integration later

This avoids mixing the hardest concerns all at once.

## Concrete First Slice

The first implementation slice should be small and reversible.

### Slice 1

Build the runtime abstraction and move current logic behind it.

Files:

- update `tools/browser_tool.py`
- add `tools/browser_runtime/base.py`
- add `tools/browser_runtime/session.py`
- add `tools/browser_runtime/agent_browser_runtime.py`
- add `tools/browser_runtime/runtime_config.py`

Deliverables:

- no feature changes
- no new tools yet
- runtime selected through one helper

### Slice 2

Implement `DevBrowserRuntime` for local navigation, snapshot, click, fill, screenshot, and close.

Files:

- add `tools/browser_runtime/dev_browser_runtime.py`
- add tests for backend parity

### Slice 3

Wire CDP mode onto `DevBrowserRuntime`.

### Slice 4

Add named page tools.

## Test Plan

Add backend-parity tests for both runtimes where possible.

Minimum coverage:

1. Local launch and navigate
2. Snapshot shape and element refs
3. Click and fill
4. Console/errors capture
5. Screenshot creation
6. Cleanup behavior
7. CDP attach with explicit endpoint
8. CDP auto-discovery
9. Session isolation across task IDs
10. Runtime selection fallback behavior

Add focused tests for:

- stale daemon/socket handling
- malformed non-JSON runtime responses
- macOS socket/path edge cases
- temp-file safety

## Risks

### Compatibility risk

`dev-browser` uses a richer model than Hermes’s current ref-based browser primitives. Mapping Playwright objects and page state cleanly into Hermes’s current tool contract will require careful response shaping.

### Operational risk

Maintaining two runtimes temporarily increases complexity. This is acceptable if the first phase is mostly extraction and test coverage.

### Packaging risk

If Hermes adopts `dev-browser` directly, installation and binary distribution need to be handled deliberately. Avoid making packaging changes part of the first migration slice.

### Scope risk

Do not combine:

- runtime abstraction
- backend migration
- new page tools
- sandbox scripting

into one PR. That is too much change at once.

## Recommended Decision

Proceed with a hybrid migration:

- Keep Hermes browser product APIs
- Replace the runtime layer incrementally
- Start with local and CDP execution
- Defer full script sandbox exposure until the runtime is proven

## Immediate Next Steps

1. Extract the runtime interface from `browser_tool.py`
2. Move existing `agent-browser` logic behind `AgentBrowserRuntime`
3. Add config-based runtime selection
4. Land tests that lock current behavior
5. Implement `DevBrowserRuntime` for local mode behind a flag

## Success Criteria

This migration is successful if:

- existing Hermes browser prompts continue to work unchanged
- local browser reliability improves
- CDP attach becomes more robust
- browser internals become replaceable and testable
- advanced browser capabilities can be added without bloating `browser_tool.py`
