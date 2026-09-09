# Outtake working conventions (DRAFT)

## Read first

- Read `docs/VISION.md` and `contracts/agent-tool.v1.md` before planning or
  changing behavior. They describe intended behavior, not shipped capability.
- This foundation is extracted from the workspace's reviewed
  `.work/outtake/build-brief.md`; its AT-01 through AT-10 rubric, including
  AT-09a, is the approval source. The brief is outside this clone, not a runtime
  dependency. Preserve its commitments rather than create competing specs.
- Read nested guidance when it exists. Keep this file lean; put interface
  promises in the contract and status in the work record.

## Current authorization boundary

- Foundation documents only: no implementation, executable work items, worker
  launches, media preflight/scanning, or provider configuration/calls yet.
- Document review is not permission to use real media or send provider data.
  Processing permissions, provider/model/account/disclosure/budgets, and real
  scene references still need the steward's decisions before the affected work.
- Keep vision and contract marked DRAFT. Approval of direction is not proof of
  conformance; do not stamp a lock without the full freeze-bar evidence and the
  steward's explicit agreement. Never edit a locked document in place.
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
- Non-governing working drafts, mocks, screenshots, and experiments stay in the
  workspace's ignored `.work/outtake/`, not product source. These foundation
  documents belong here even while DRAFT. Never reuse canned mock outputs as proof.
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
- End every commit message with:

  ```text
  Generated with Amplifier

  Co-Authored-By: Amplifier <240397093+microsoft-amplifier@users.noreply.github.com>
  ```