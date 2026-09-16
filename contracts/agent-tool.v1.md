# Outtake Agent-Tool Contract — v1 (DRAFT)

**Who builds against this:** People using Outtake through external agents, scripts,
library integrations, and the optional dashboard depend on the same public behavior.
The current implementation covers only part of this contract;
the full conformance kit below remains an acceptance plan. See
[implementation status](../docs/IMPLEMENTATION.md) for verified scope.
The [calling-agent contract](caller-interaction.v1.md) defines context, ownership,
source resolution, questions, and continuity across the public boundary.

## What it looks like

A caller asks for a remembered moment, receives candidates with evidence, selects
one, revises its plan, and obtains a real artifact and receipt without a browser.
This behavioral example is not a published command or JSON schema:

```text
Right: select source A in an approved folder; revise plan P1 to P2;
       render P2 to the configured output folder; return its artifact and receipt.
Wrong: ignore that folder, reuse P1's canned preview, and report P2 as ready.
Right: repeated dialogue returns needs_selection with evidence for each occurrence.
Wrong: choose the first occurrence silently and describe it as certain.
Right: use remembered action to locate a silent candidate, then check the source.
Wrong: reject the request solely because the moment has no caption.
```

## Purpose

An agent must be able to finish and revise a media task without private knowledge
of Outtake or hidden UI state. One shared contract keeps adapters from acquiring
different capabilities and prevents a plausible response from replacing a
traceable artifact. Configuration and permissions belong to the caller.

## Core (the teeth)

1. **Every domain capability is available through both library and CLI.** Required capabilities are moment finding, smart end-to-end making, scoped cataloging, plan validation, preview, rendering, manifest discovery, and headless selection/revision of cuts, ordering, frames, overlays, and output. One library owns behavior; adapters add no private domain logic.
2. **Normal calls are headless and machine-readable.** Plans and results have versioned JSON schemas. CLI JSON goes to stdout, progress/warnings to stderr, and operational failures exit non-zero without interactive prompts. Concise `-h` and detailed `--help` document arguments, results, AI use, artifacts, and remedies; no UI server or browser session is required.
3. **Users configure source roots and output destinations.** Documented configuration and library/CLI inputs accept local folders or mounted shares without code edits. Per-invocation values override configured defaults within caller-approved roots; models and plans cannot expand permissions. Unreadable sources, unwritable destinations, and unauthorized overrides return actionable errors without silent fallback; developer trial paths are not prerequisites.
4. **Smart retrieval uses knowledge, user guidance, and captions without a fixed hierarchy.** Outtake uses Amplifier Agent for its intelligence layer, owns its configured model dependency, and accepts the calling agent's knowledge and the user's contextual clues as first-class inputs, equally important to finding a moment as available captions. Any can identify a source or candidate range; captions are not a prerequisite for bounded source inspection or silent-moment retrieval. Inferred locations remain hypotheses until checked against source evidence. The model receives bounded evidence, not filesystem access; uncertain occurrences, conflicting clues, or boundaries remain explicit.
5. **Missing captions are a limitation of caption operations, not of the request.** Silent moments and sources with no text captions remain eligible for knowledge- or guidance-led retrieval and permitted source inspection. A specifically requested caption-dependent operation without text captions returns `MISSING_TEXT_CAPTIONS`; generic finding does not fail for that reason alone. If available clues and permitted inspection cannot locate or verify a moment, return an actionable limitation or ambiguity, not an invented match. No implicit OCR, transcription, or upload fills the gap. An explicit known-source timestamp/range remains provider-free; caption and shot boundaries alone do not establish a complete scene.
6. **Edits are immutable, serializable plans.** Each plan identifies its schema and plan version, source identities/fingerprints, selection provenance (knowledge/user guidance and source observations, caption anchors when used, or caller-specified range), requested/resolved time/frame basis, ordered clip IDs, per-clip overlay mode/text/style, still or sequence target, and audio/transition/output/destination/resource policies. Provenance distinguishes supplied clues, inferred hypotheses, and observed source evidence; caption evidence includes identity/version, language, time base, and offset. A selection, trim, order, frame, appearance, or output revision yields a new plan identity/version; saved plans require no browser state.
7. **Rendering validates the plan against current sources and policy.** Every render rechecks identities, ranges, and permissions even after earlier validation; changed sources or caption evidence fail as `STALE_SOURCE` rather than silently rendering different material. Receipts bind plan and artifact IDs/paths to resolved sources, timing, transformations, warnings, and failure/cancellation details.
8. **Outputs faithfully implement the selected plan.** One render produces one requested format: silent GIF, MP4 with the declared audio policy, or PNG of the active clip's selected source frame, never a sequence composite. Ordered mixed-source clips retain declared order and synchronization. Source captions or custom text support font family, size, color, outline, normalized position, and alignment, with resolved values recorded.
9. **Timing and image transformations are explicit.** Accurate cuts and stills select the first source frame at or after requested presentation time. Output profiles define frame rate, scaling, and HDR-to-SDR policy; unapproved tone mapping is rejected, and HDR detection and transformations are recorded. Decoded output, not player metadata alone, establishes correctness.
10. **Outcomes tell the caller what happened and what to do next.** `ready`, `needs_selection`, `partial`, `failed`, and `cancelled` are distinct. `needs_selection` carries ranked candidates, their provenance, available source evidence, and uncertainty, accepting a subsequent choice; captions are included when used, not required. Failures carry stable code, affected identity, message, and remediation. Render/preview allow ready/failed/cancelled; smart find/make also allow needs_selection; only catalog allows partial and lists completed entries and unreadable sources; manifest/validation allow ready/failed.
11. **Artifact success is atomic and resource-bounded.** `ready` for artifact production means artifact and receipt are published together, not a partially published format batch. Configurable concurrency, wall-time, temporary-space, and output-size caps fail explicitly as `RESOURCE_LIMIT`; they never silently truncate output. Cancellation or failure cleans uncommitted temporary output and publishes no success artifact.
12. **Provider disclosure requires explicit authorization.** Deterministic loading/catalog/validation/preview/render/manifest require no provider credentials and send no content to a provider. Smart calls without a named approved provider fail as `PROVIDER_NOT_AUTHORIZED`, never silently downgrade. Request/metadata/caption disclosure is opt-in and bounded; candidate frames require separate permission and budget. Raw video/audio, source paths, and whole-library inventories are not sent. Calls, retries, text, responses, frames, and elapsed time share enforced invocation caps; exhaustion and oversized input fail explicitly.
13. **Untrusted inputs cannot escape approved roots or execute instructions.** Canonicalize and confine reads/writes, preserve originals unchanged, and use fixed executables with argument vectors, never a shell or caller-supplied FFmpeg filters. Treat captions, paths, model output, and browser requests as data. Cache/state/temp are outside the install tree; outputs go to caller-selected destinations.
14. **The dashboard is an optional runtime adapter, not a capability gate.** The caller can complete finding, editing, and delivery without opening it. When opened for participation, it presents the current moment directly in a compact workspace with search, actual generated playback, trim/reorder, and per-clip appearance, using the same plans/configuration/validation. Rendering makes the new output available in the same saved-outputs collection used to return to previous requests and exports. Reopening restores the identified source, occurrence, edits, and output choices; subsequent changes preserve earlier exports. Settings expose source/output locations and Amplifier Agent provider/model configuration through the same public behavior, and the interface supports light, dark, and system appearance. Browser presentation and explicit server lifecycle are surface-specific; UI-only domain behavior is forbidden. Launch is explicit, loopback by default, with no automatic LAN exposure; registered artifact IDs replace arbitrary paths, and viewing existing artifacts requires no model credential.
15. **The installed package truthfully describes its capabilities.** Git installation, one packaged `SMART_TOOL.md`, and root `smart-tool.json` provide documented library/CLI use, manifest location, CLI argv, and a real provider-free deterministic smoke capability. Required manifest fields are nonempty, package/manifest versions agree, prerequisites are documented, and platform claims match verified installations.

## Evidence available to the intelligence layer

These are behavioral obligations on Outtake's internal capabilities, not a tool
inventory or API design. Amplifier Agent is the chosen intelligence layer;
specific runtime versions, providers, and capability compatibility are unverified.

- **Resolve and inspect within scope.** Intelligence can request source resolution,
  available metadata/caption evidence, and bounded observations of relevant source
  intervals. It need not ask the calling agent to perform Outtake's internal media
  inspection. Requests are mediated by enforced access and resource limits; the
  model has no unrestricted filesystem, shell, or permission-changing capability.
- **Use actual visual evidence.** With authorized frame disclosure and a compatible
  vision-capable provider, intelligence can examine images sampled from the source
  and request further bounded observations to locate or refine a candidate. Each
  observation identifies its source and presentation time. Multiple observations
  preserve temporal order and expose sampling gaps; a sampled still alone does not
  establish movement, a transition, or absence of an event between samples.
- **Support the requested event and cut.** Evidence must support the relevant
  action, dialogue, or transition and the proposed beginning/end, with uncertainty
  visible. Caption matches and related images may locate candidates without proving
  the whole moment. A visual match does not prove a nonverbal sound. Where sound is
  essential, mark sound as unverified and provide local playback and deterministic
  cut revision so the person can verify it and adjust boundaries. Automatic sound
  verification is outside the initial scope; do not describe visual inference as
  listening or block an otherwise usable proposed cut solely on that limitation.
- **Separate observation from interpretation.** Source observations, supplied clues,
  model hypotheses, and human confirmation remain distinguishable in public
  provenance. The caller receives useful evidence and limitations, not a requirement
  to inspect private reasoning. Model assertions do not replace source validation.
- **Make missing capability actionable.** A provider without the needed vision
  support cannot silently pass visual verification. Unsupported observation types,
  denied disclosure, and exhausted budgets are reported distinctly. All internal
  attempts share the invocation limits in clause 12; another observation request
  does not create a fresh budget. Local frame extraction and deterministic rendering
  remain provider-free; model interpretation is smart work.

## What v1 deliberately does NOT freeze

- Function/command spellings, schema layout details, and configuration syntax: promote before external clients first depend on them, with round-trip examples and compatibility checks.
- Language, database, process layout, renderer acceleration, internal intelligence-tool interfaces, and dashboard framework: internal choices get tests, not promises; promote only if an external consumer depends on their behavior.
- Specific providers, models, numerical budgets, fonts, and output profiles: select before their acceptance cases execute; changing a user-visible promise requires revisiting the affected clause.
- Latency, throughput, and broad platform coverage: promote only when representative installed runs establish a meaningful supported guarantee.

## Conformance kit asserts

The following acceptance scenarios map to the stable clauses above.
This table is the full acceptance plan, not a pass report. The initial runtime
checks exercise subsets of these promises; no full row is claimed passed here.
Expected results are fixed independently before execution; skipped rows never
count as passed. See implementation status for exact current checks and gaps.

| Check / clauses | Observable assertion and independent oracle | False-positive risk |
|---|---|---|
| AT-01 / 1, 2, 6, 10 | An external agent using only installed CLI/docs completes a natural-language request and one revision; process traces, JSON, plan/receipt, and artifact IDs prove headless use. | Private imports or checkout knowledge secretly help the agent. |
| AT-02 / 1, 5, 7, 12 | With credentials absent and provider network denied, local-fixture manifest/catalog/validate/preview/render produce fresh valid artifacts; malformed fixtures fail with expected codes. Independent markers/hashes and receipts are the oracle. | Cached model results or pre-existing artifacts. |
| AT-03 / 4 | The chosen real source/occurrence belongs to the human-approved expected set; anchors trace to caption text and offset. The steward confirms independently prepared reference windows and acceptable bounds, recorded by name/date. | Repeated dialogue, recaps, drift, or a traceable wrong occurrence. |
| AT-03a / 4, 5, 6, 10 | A real silent moment is found without a quote, text captions, or supplied exact timecodes: test both a knowledge-led request and a user-guided request. Pass only if each selected source/occurrence and cut are in the independently human-approved expected set and provenance separates clues/inference from source observations. Repeat with a misleading clue: it must not yield an unsupported confident match. | Memorized timecodes, a different edit of the film, hidden caption dependence, supplied reference windows leaking into the search, or attractive but wrong imagery. |
| AT-03b / 4, 5, 6; evidence obligations | Human-approved transition and moving-action examples are located without supplied timecodes; timestamped, ordered source observations support the event and proposed boundaries. Sound-dependent examples mark sound unverified and offer local playback and cut revision for user verification; they never claim that visual inference is listening. | Related stills mistaken for an event; gaps in sampling hidden; visual expression mistaken for heard audio. |
| AT-03c / 4, 12, 13; evidence obligations | Controlled observations and provider/audit records show bounded source-linked evidence reaches the intelligence layer, unsupported vision is explicit, and repeated internal requests cannot expand scope or reset caps. | Model-authored evidence, undeclared uploads, or a fresh budget per internal call. |
| AT-04 / 4, 5, 10 | Fixed ambiguity fixtures return needs_selection. No-text/image-caption fixtures fail specifically caption-dependent operations with MISSING_TEXT_CAPTIONS, not generic finding solely for absent captions. Insufficient clues or prohibited inspection produce actionable limitations without unauthorized fallback; explicit timestamp rendering still succeeds. Fixture-specific expected outcomes are fixed before execution. | Weak matches pass as unique; blanket caption errors conceal an unimplemented path; hidden OCR/transcription. |
| AT-05 / 7, 8, 9 | Visible frame IDs prove first-frame selection; decoded duration differs from the independent expected timeline by at most one output-frame interval. Audio markers stay within max(one output frame, 25 ms); container metadata handles encoder delay, not tolerance inflation. Profiles fix frame rate/scaling/HDR policy before execution. | Keyframe seeks, metadata-only checks, or declared padding conceal drift. |
| AT-06 / 8, 13 | Independent pixels/reference images show planned and receipted text/style in the output; hostile HTML/shell-like strings do not execute. Placement tolerance is proposed at 3 pixels, subject to rubric approval. | Rasterization variance, hidden text, or metadata substituted for pixels. |
| AT-07 / 6, 8, 9 | Independent frame IDs prove PNG uses the active clip's selected frame at/after requested time and its overlay. | Nearest/keyframe substitution or stale active-clip state. |
| AT-08 / 8, 9 | Independently generated frame/audio markers prove mixed-source order and audio policy, with AT-05 duration/synchronization tolerances. | Normalization shifts cuts or silently loses audio. |
| AT-09 / 7, 10, 11, 12, 13 | Controlled provider/audit sink and filesystem snapshots show no unapproved disclosure, original mutation, root escape, injection, stale-plan success, hidden cap overrun, or success artifact after cancellation. | Telemetry, cached output, or cleanup misread as atomic publication. |
| AT-09a / 3, 13 | Fresh installation, with developer trial paths absent, uses distinct non-default source/output roots via config and library/CLI without code edits or a dashboard. Approved overrides take effect; unreadable approved sources, unwritable approved destinations, and readable-but-unauthorized overrides fail without fallback. Markers, filesystem snapshots, and returned paths establish actual use. | Developer paths, ignored overrides, or browser state mask failure. |
| AT-10 / 1, 2, 14, 15 | Fresh installed-copy smoke and manifest/descriptor checks pass; explicitly launched browser plays/seeks produced MP4, animates produced GIF, and downloads matching artifacts. Routine workspace and saved-output tasks fit 1366×768; advanced controls may scroll. | HTTP 200, thumbnails, canned samples, cache, or a source checkout masks failure. |
| AT-11 / 1, 6, 7, 12, 14 | A headless result can be opened directly in the workspace; rendering adds an identified export to the shared saved-output collection. Reopening two distinct sources restores each source, occurrence, cut/frame, overlays and output choices; a new revision/export preserves the earlier one. Settings round-trip through public configuration, preserve work in progress, and obey existing access/disclosure authority. Light/dark/system remain legible, with system following host appearance. | Only title labels change; stale candidates or captions leak between sources; an old export is overwritten; dashboard-only configuration; theme changes affect chrome but obscure controls. |

## Reserved / open questions (NOT frozen)

- A local collection has been made available for investigation. Each execution must use the applicable caller-approved source/output scope; its private location is not a product default or prerequisite. Broader cataloging is not implied.
- Named provider/model/account, terms review, disclosure categories including candidate frames, and exact model/render budgets remain approval choices; none are authorized by this draft.
- Concrete test requests, source editions/episodes, occurrences, and human-confirmed reference cuts/quality must be selected before acceptance runs; generated fixtures cannot establish those semantic outcomes.
- Initial sound review is user-owned: local playback and cut adjustments, with sound explicitly unverified by Outtake. Raw-audio provider disclosure remains prohibited. Automatic sound understanding is deferred.
- The bounded source-inspection strategy for knowledge- and guidance-led candidates, including silent moments, needs implementation design and an approved test setup. The outcome is required; no particular search algorithm, whole-library scan, or new disclosure permission is implied.
- Dashboard delivery remains in the proposed integrated scope and AT-10; optional at runtime does not waive its acceptance gate. Omitting it requires an explicit scope decision.
- Upstream Smart Tools revision, supported platforms, package runner, and exact smoke invocation must be pinned from verified implementation evidence before release.

## Changelog

- **2026-09-16** — Agreed user-owned sound review through local playback and cut adjustment for the initial version; automatic sound verification is deferred.

- **2026-09-16** — Clarified workspace handoff, saved-output continuity, shared
  settings, and light/dark/system appearance from reviewed UI direction.

- **2026-09-16** — Added caller-contract linkage, Amplifier Agent direction,
  and internal evidence obligations. These changes define behavior; no internal
  tool interface or retrieval algorithm is frozen.
