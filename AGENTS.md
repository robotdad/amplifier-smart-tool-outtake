# Outtake working conventions (DRAFT)

## Read first

- Read `docs/VISION.md` and `contracts/agent-tool.v1.md` before planning or
  changing behavior. They describe intended behavior, not shipped capability.
- The contract contains the acceptance scenarios and their approval questions.
  Keep repository documentation self-contained: use repo-relative references
  or public upstream sources, never private planning files or host-local paths.
- Read nested guidance when it exists. Keep this file lean; put interface
  promises in the contract. Do not use the vision as a progress report.

## Current authorization boundary

- Foundation documents only: no implementation, executable work items, worker
  launches, media preflight/scanning, or provider configuration/calls yet.
- Document review is not permission to use real media or send provider data.
  Processing permissions, provider/model/account/disclosure/budgets, and real
  scene references still need the steward's decisions before the affected work.
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
  Python, FFmpeg/FFprobe, and SQLite are proposals, not verified prerequisites.
- Treat paths, captions, model output, and browser inputs as untrusted data.
  Keep sources read-only and outputs confined; never let a model expand access.
- Keep developer paths, credentials, private media, and library inventories out
  of source and fixtures. State/cache/temp live outside the installed package.
- Keep disposable experiments and mock assets out of committed product content.
  Governing draft documents belong in the repo. Never use canned outputs as proof.
- Preserve existing work; use the smallest change that serves an agreed promise.

## Verification and completion

- No implementation or runnable conformance kit exists yet. Do not invent test
  commands or report the document checks as product acceptance.
- Once runnable checks exist, record their exact commands here. Derive them
  from the approved rubric; define independent expected results before running.
- Verify a fresh installed copy, provider-free deterministic paths, public CLI
  use by an independent agent, decoded media, and applicable browser behavior.
  Unit tests and HTTP 200 responses alone do not establish these outcomes.
- A skipped or blocked acceptance row is not a pass. Real-scene semantic
  references require human confirmation; fixture tests cannot substitute.
- Report what was checked, what it printed, and what remains unverified.
  Internal incremental work culminates in one integrated review package.