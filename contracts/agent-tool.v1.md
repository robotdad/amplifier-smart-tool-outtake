# Outtake Agent-Tool Contract — v1 (DRAFT)

**Who builds against this:** People using Outtake through external agents, scripts,
library integrations, and the optional dashboard depend on the same public behavior.
There is no reference implementation yet; the conformance kit below is a plan.

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
4. **Smart retrieval is model-backed and caption-led.** Outtake owns the configured model dependency. Requests and general knowledge are grounded in text subtitle streams or sidecars tied to source identity, caption identity/version, language, time base, and offset. Inspection is bounded to caption-selected candidates; the model receives mechanical evidence, not filesystem access. Uncertain occurrences or boundaries remain explicit, with alternatives rather than guessed certainty.
5. **Missing captions do not trigger hidden capabilities.** No-text or image-only captions return `MISSING_TEXT_CAPTIONS` for automatic retrieval, without implicit OCR, transcription, or upload. An explicit known-source timestamp/range remains a provider-free path; caption and shot boundaries alone do not establish a complete scene.
6. **Edits are immutable, serializable plans.** Each plan identifies its schema and plan version, source identities/fingerprints, caption-anchor provenance or explicit range, requested/resolved time/frame basis, ordered clip IDs, per-clip overlay mode/text/style, still or sequence target, and audio/transition/output/destination/resource policies. A selection, trim, order, frame, appearance, or output revision yields a new plan identity/version; saved plans require no browser state.
7. **Rendering validates the plan against current sources and policy.** Every render rechecks identities, ranges, and permissions even after earlier validation; changed sources or caption evidence fail as `STALE_SOURCE` rather than silently rendering different material. Receipts bind plan and artifact IDs/paths to resolved sources, timing, transformations, warnings, and failure/cancellation details.
8. **Outputs faithfully implement the selected plan.** One render produces one requested format: silent GIF, MP4 with the declared audio policy, or PNG of the active clip's selected source frame, never a sequence composite. Ordered mixed-source clips retain declared order and synchronization. Source captions or custom text support font family, size, color, outline, normalized position, and alignment, with resolved values recorded.
9. **Timing and image transformations are explicit.** Accurate cuts and stills select the first source frame at or after requested presentation time. Output profiles define frame rate, scaling, and HDR-to-SDR policy; unapproved tone mapping is rejected, and HDR detection and transformations are recorded. Decoded output, not player metadata alone, establishes correctness.
10. **Outcomes tell the caller what happened and what to do next.** `ready`, `needs_selection`, `partial`, `failed`, and `cancelled` are distinct. `needs_selection` carries ranked candidates and caption evidence, accepting a subsequent choice. Failures carry stable code, affected identity, message, and remediation. Render/preview allow ready/failed/cancelled; smart find/make also allow needs_selection; only catalog allows partial and lists completed entries and unreadable sources; manifest/validation allow ready/failed.
11. **Artifact success is atomic and resource-bounded.** `ready` for artifact production means artifact and receipt are published together, not a partially published format batch. Configurable concurrency, wall-time, temporary-space, and output-size caps fail explicitly as `RESOURCE_LIMIT`; they never silently truncate output. Cancellation or failure cleans uncommitted temporary output and publishes no success artifact.
12. **Provider disclosure requires explicit authorization.** Deterministic loading/catalog/validation/preview/render/manifest require no provider credentials and send no content to a provider. Smart calls without a named approved provider fail as `PROVIDER_NOT_AUTHORIZED`, never silently downgrade. Request/metadata/caption disclosure is opt-in and bounded; candidate frames require separate permission and budget. Raw video/audio, source paths, and whole-library inventories are not sent. Calls, retries, text, responses, frames, and elapsed time share enforced invocation caps; exhaustion and oversized input fail explicitly.
13. **Untrusted inputs cannot escape approved roots or execute instructions.** Canonicalize and confine reads/writes, preserve originals unchanged, and use fixed executables with argument vectors, never a shell or caller-supplied FFmpeg filters. Treat captions, paths, model output, and browser requests as data. Cache/state/temp are outside the install tree; outputs go to caller-selected destinations.
14. **The dashboard is an optional runtime adapter, not a capability gate.** When delivered it exposes compact Create → Refine → Results, actual generated playback/downloads, trim/reorder and per-clip appearance, using the same plans/configuration/validation. Browser presentation and explicit server lifecycle are surface-specific; UI-only domain behavior is forbidden. Launch is explicit, loopback by default, with no automatic LAN exposure; registered artifact IDs replace arbitrary paths, and viewing existing artifacts requires no model credential.
15. **The installed package truthfully describes its capabilities.** Git installation, one packaged `SMART_TOOL.md`, and root `smart-tool.json` provide documented library/CLI use, manifest location, CLI argv, and a real provider-free deterministic smoke capability. Required manifest fields are nonempty, package/manifest versions agree, prerequisites are documented, and platform claims match verified installations.

## What v1 deliberately does NOT freeze

- Function/command spellings, schema layout details, and configuration syntax: promote before external clients first depend on them, with round-trip examples and compatibility checks.
- Language, database, process layout, renderer acceleration, and dashboard framework: internal choices get tests, not promises; promote only if an external consumer depends on their behavior.
- Specific providers, models, numerical budgets, fonts, and output profiles: select before their acceptance cases execute; changing a user-visible promise requires revisiting the affected clause.
- Latency, throughput, and broad platform coverage: promote only when representative installed runs establish a meaningful supported guarantee.

## Conformance kit asserts

This is the planned mapping from stable clauses to the reviewed build brief's
acceptance IDs, not an implemented test suite or a pass report. Runtime assertions
currently **Can't check**: no implementation or harness exists. Expected results
are fixed independently before execution; skipped rows never count as passed.

| Check / clauses | Observable assertion and independent oracle | False-positive risk |
|---|---|---|
| AT-01 / 1, 2, 6, 10 | An external agent using only installed CLI/docs completes a natural-language request and one revision; process traces, JSON, plan/receipt, and artifact IDs prove headless use. | Private imports or checkout knowledge secretly help the agent. |
| AT-02 / 1, 5, 7, 12 | With credentials absent and provider network denied, local-fixture manifest/catalog/validate/preview/render produce fresh valid artifacts; malformed fixtures fail with expected codes. Independent markers/hashes and receipts are the oracle. | Cached model results or pre-existing artifacts. |
| AT-03 / 4 | The chosen real source/occurrence belongs to the human-approved expected set; anchors trace to caption text and offset. The steward confirms independently prepared reference windows and acceptable bounds, recorded by name/date. | Repeated dialogue, recaps, drift, or a traceable wrong occurrence. |
| AT-04 / 4, 5, 10 | Fixed ambiguity fixtures return needs_selection; no-text/image-caption fixtures return the declared error; explicit timestamp rendering still succeeds. | Weak matches pass as unique; hidden OCR/transcription. |
| AT-05 / 7, 8, 9 | Visible frame IDs prove first-frame selection; decoded duration differs from the independent expected timeline by at most one output-frame interval. Audio markers stay within max(one output frame, 25 ms); container metadata handles encoder delay, not tolerance inflation. Profiles fix frame rate/scaling/HDR policy before execution. | Keyframe seeks, metadata-only checks, or declared padding conceal drift. |
| AT-06 / 8, 13 | Independent pixels/reference images show planned and receipted text/style in the output; hostile HTML/shell-like strings do not execute. Placement tolerance is proposed at 3 pixels, subject to rubric approval. | Rasterization variance, hidden text, or metadata substituted for pixels. |
| AT-07 / 6, 8, 9 | Independent frame IDs prove PNG uses the active clip's selected frame at/after requested time and its overlay. | Nearest/keyframe substitution or stale active-clip state. |
| AT-08 / 8, 9 | Independently generated frame/audio markers prove mixed-source order and audio policy, with AT-05 duration/synchronization tolerances. | Normalization shifts cuts or silently loses audio. |
| AT-09 / 7, 10, 11, 12, 13 | Controlled provider/audit sink and filesystem snapshots show no unapproved disclosure, original mutation, root escape, injection, stale-plan success, hidden cap overrun, or success artifact after cancellation. | Telemetry, cached output, or cleanup misread as atomic publication. |
| AT-09a / 3, 13 | Fresh installation, with developer trial paths absent, uses distinct non-default source/output roots via config and library/CLI without code edits or a dashboard. Approved overrides take effect; unreadable approved sources, unwritable approved destinations, and readable-but-unauthorized overrides fail without fallback. Markers, filesystem snapshots, and returned paths establish actual use. | Developer paths, ignored overrides, or browser state mask failure. |
| AT-10 / 1, 2, 14, 15 | Fresh installed-copy smoke and manifest/descriptor checks pass; explicitly launched browser plays/seeks produced MP4, animates produced GIF, and downloads matching artifacts. Routine Create/Refine/Results fit 1366×768; advanced controls may scroll. | HTTP 200, thumbnails, canned samples, cache, or a source checkout masks failure. |

## Reserved / open questions (NOT frozen)

- Trial host, read-only source scope, writable output location, and up-to-five-named-file preflight need explicit authorization; broader cataloging is not implied.
- Named provider/model/account, terms review, disclosure categories including candidate frames, and exact model/render budgets remain approval choices; none are authorized by this draft.
- Two or three real film/show moment requests and human-confirmed reference cuts/quality remain missing; generated fixtures cannot establish those semantic outcomes.
- Dashboard delivery remains in the proposed integrated scope and AT-10; optional at runtime does not waive its acceptance gate. Omitting it requires an explicit scope decision.
- Upstream Smart Tools revision, supported platforms, package runner, and exact smoke invocation must be pinned from verified implementation evidence before release.