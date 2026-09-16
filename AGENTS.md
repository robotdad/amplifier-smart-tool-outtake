# Outtake working conventions (DRAFT)

## Read first

- Read `docs/VISION.md`, `contracts/agent-tool.v1.md`, and
  `contracts/caller-interaction.v1.md` before planning or
  changing behavior. They describe intended behavior, not shipped capability.
- The contract contains the acceptance scenarios and their approval questions.
  Keep repository documentation self-contained: use repo-relative references
  or public upstream sources, never private planning files or host-local paths.
- Read nested guidance when it exists. Keep this file lean; put interface
  promises in the contract. Do not use the vision as a progress report.

## Current authorization boundary

- The steward has authorized implementation, starting with the Python library and
  thin CLI, then Amplifier-powered finding and the reviewed dashboard. Preserve
  the draft behavioral promises and report milestone scope honestly. The steward
  has now authorized the dashboard and end-to-end scenario runs against the supplied
  collection, using the configured vision provider with bounded request, metadata,
  caption and sampled-frame disclosure. No raw video/audio or whole inventories
  go to providers. Human confirmation of semantic cuts remains distinct from tests.
- The steward has made a local media collection available for investigation.
  Keep its location and inventory outside repository content, preserve sources,
  and keep inspection relevant and bounded. Local access does not authorize
  provider disclosure or unbounded whole-library content scanning. Honor existing
  session authorization without repeatedly asking for the same permission.
- Amplifier Agent is the chosen intelligence layer, including vision-capable
  providers for permitted source images. Provider/model/account/disclosure/budgets
  and human-confirmed scene references remain decisions for the affected work.
- Keep vision and contract marked DRAFT until their promises are clear, examples
  distinguish right from wrong, a real implementation passes an end-to-end
  runnable check, and the project owner explicitly agrees to lock them.
  Approval of direction is not proof of conformance. Never edit a locked
  document in place; propose changes separately for owner review.
- Do not push until the steward reviews the integrated deliverable.

## Implementation discipline once authorized

- Library first; thin CLI; optional, explicitly launched dashboard. All domain
  behavior is agent-callable without browser state or a running UI server.
- Read the upstream [Smart Tools specifications](https://github.com/microsoft/amplifier-smart-tools/tree/main/spec)
  and record the verified revision before implementing package conformance.
  Python and FFmpeg/FFprobe are selected for the first implementation. Storage
  remains an internal choice. Verified spec revision:
  `0f89dd9263338918d9b27bb48670c688c3e9bac1`.
- Treat paths, captions, model output, and browser inputs as untrusted data.
  Keep sources read-only and outputs confined; never let a model expand access.
- Keep developer paths, credentials, private media, and library inventories out
  of source and fixtures. State/cache/temp live outside the installed package.
- Keep working materials, including exploratory scenarios, in git-ignored `.work/`.
  Governing documents must remain self-contained without relying on those files.
  Keep disposable experiments and mock assets out of committed product content.
  Governing draft documents belong in the repo. Never use canned outputs as proof.
- Preserve existing work; use the smallest change that serves an agreed promise.

## Verification and completion

- The library, bounded finding integration, and dashboard have runnable checks
  (install Chromium once with `uv run playwright install chromium`):
  `uv run --extra smart pytest`,
  `uv run ruff check src tests`, `uv run ruff format --check src tests`, and
  `uv build`. Run the upstream package checks against an installed CLI using
  `uv run <spec-checkout>/conformance/run.py <outtake-distribution-root>`.
  For the cached real-Agent offline test set `OUTTAKE_TEST_CACHED_AMPLIFIER=1`
  and deny network access. Scripted providers verify integration, not recognition.
  These do not establish complete product acceptance. See `docs/IMPLEMENTATION.md`.
- Derive new checks from the approved rubric and define independent expected
  results before running them.
- Verify a fresh installed copy, provider-free deterministic paths, public CLI
  use by an independent agent, decoded media, and applicable browser behavior.
  Unit tests and HTTP 200 responses alone do not establish these outcomes.
- A skipped or blocked acceptance row is not a pass. Real-scene semantic
  references require human confirmation; fixture tests cannot substitute.
- Report what was checked, what it printed, and what remains unverified.
  Internal incremental work culminates in one integrated review package.
