# Implementation status

## First milestone: deterministic single-source extraction

The public Python library owns inspection, plans, revision, validation, rendering,
preview, and saved receipt retrieval. CLI commands are JSON I/O adapters over it.
No server, browser, model credentials or Amplifier session starts on these paths.

Implemented:

- Explicit caller-selected source/output/state folders, local container restrictions,
  and source-root confinement including resolved symlinks.
- Versioned validated plan values, immutable retained revisions, source SHA-256
  fingerprints, stale-source rejection and conflicting-plan rejection.
- First-frame-at-or-after selection; PNG stills, animated GIF and H.264/AAC MP4.
- Share and editing profiles, mute/preserve-first-audio choices, and literal custom
  text with a bundled font, size, colors, outline, position and alignment.
- A preview is a real render of the same plan. Each render publishes a unique
  directory containing artifact and receipt together. Prior exports remain intact.
- Receipts contain the whole plan for reopening/revising, actual resolved start,
  content hash, dimensions, frame rate, audio handling and sound-review warning.
- Wall-time, cut-length, output-size and temporary-space limits; cancellation and
  cleanup; one render per process. Disk limits are polled rather than OS quotas.

## Second milestone: bounded finding and Amplifier integration

Implemented library capabilities, all exposed through the thin CLI:

- Bounded filename/folder discovery with partial-scope reporting and opaque source
  IDs; source identity remains unverified until actual evidence is inspected.
- Cheap metadata-only inspection for resolving unselected editions/episodes; full
  content fingerprints for source observations and plans. Caption-track inspection,
  ordered timestamped frames with gaps,
  same-basename SRT and embedded text-caption search with language/offset/hash.
- Amplifier Agent v0.17.0 embedding, restricted domain tools: narrow source/episode clues,
  inspect source, sample frames, search captions, submit candidates, or report a limitation.
- Explicit provider/model grants, separate request/metadata/caption/frame disclosure,
  no source paths in tool results sent to providers, and base64 image delivery.
- Shared model/tool/frame/text/image/time allowances, disabled provider retries,
  validated evidence references and explicit uncertainty. Raw audio/video is never
  supplied to a model. Source observations remain distinct from model proposals.
- Retained findings and idempotent request IDs; deterministic candidate selection,
  plan revision and rendering; make renders a single candidate or returns ambiguity.
  Sources and caption evidence are rechecked before selection and rendering.

The real Amplifier Engine and session loop have been exercised with a scripted
provider and network access denied. This establishes integration, not a model's
ability to recognize remembered scenes. Bounded live scenario checks now additionally exercise the selected vision
provider against permitted source samples; their aggregate outcomes are recorded below; private run material remains outside
tracked product content.
Automatic source correctness and visual reasoning still require per-result review. Generic packaging conformance
cannot establish these semantic outcomes. Live testing exposed and fixed SDK
response-metadata serialization, excessive boundary sampling, costly PNG disclosure,
and unnecessary hashing of unselected candidates. Provider review images are JPEG
quality 90; original PNG evidence remains local. Limits and remaining work are made
explicit to the intelligence layer, and denied observations still allow an honest
limitation based on the work already completed.

## Third milestone: optional local dashboard

The explicitly launched loopback dashboard uses the same public library. It opens
an identified plan/finding directly, places moments at left and trim/text/output
controls at right, and shows actual source frames and rendered media. MP4 playback,
GIF/image exports, downloads, a unified saved-output collection, and reopening
immutable edits work without an intelligence session. Previews are marked separately
and excluded from the default saved collection.

Shared configuration exposes source/output folders, provider/model and disclosure
choices, work limits, credential availability (never keys), and light/dark/system
appearance. Folder settings are saved; reuse by a new caller is explicit through
`restore_configuration()` / `--saved-settings`. In-progress edits survive Settings.
The server requires a random session token/cookie, validates Host/Origin, serves
media by retained IDs, and closes through an explicit handle or CLI interruption.
No server starts during ordinary library/CLI work.

## Live scenario exercise

The authorized local trials used Gemini 3.7 Flash through the real Amplifier Agent
runtime. Five remembered requests produced seven reviewable MP4 proposals, including
multiple plausible occurrences for an ambiguous nonverbal-sound request and episode
resolution from a show-level request. The missing-source case was not run; a separate
bonus-short request remained unresolved in both the feature and a related compilation.
These are retrieval/rendering outcomes, not semantic acceptance passes.

Every produced MP4 matched its receipt hash, dimensions and declared audio, decoded
fully without errors, and had duration consistent with its planned range. Real-media
browser playback, seeking and appearance were also checked. The calling agent visually
reviewed representative source evidence; exact dialogue, sound and human-approved cut
boundaries remain unverified. Initial failures and cancelled investigations are retained
in ignored working material and are not counted as successful searches.

## Verification scope

Tests generate an independent 10fps source with numbered spatial markers, red/green/
blue intervals, and a tone beginning at 1.2 seconds. They decode output pixels and
audio samples, rather than treating FFprobe metadata as proof. Checks cover:

- A requested 0.95-second start resolves to frame 10 at 1.0 seconds.
- The editing MP4 has the expected 11 decoded frames for the selected range and
  tone onset within 25ms of the expected 0.2-second output position.
- GIF animation, selected PNG frame identity, literal overlay pixels, and originals
  remaining unchanged.
- Retained revisions and earlier exports, invalid inputs, stale sources, symlink
  escapes, modified plan metadata, cancellation cleanup, output caps, playlist
  rejection and non-zero Matroska start timestamps.
- Public CLI help, manifest, schemas, plan/render, nonzero failures and closed stdin.

Install Chromium once with `uv run playwright install chromium`.
Run `uv run --extra smart pytest`, `uv run ruff check src tests`,
`uv run ruff format --check src tests`, and `uv build`.

Verified on macOS with Python 3.12 and FFmpeg/FFprobe 8.0.1:

- **46 tests passed** against a newly installed wheel outside the checkout:
  42 tests with network denied, including the real cached Amplifier session with
  a scripted provider, plus 4 real Chromium tests using only the local dashboard.
  CLI deterministic tests scrub provider credentials. Browser checks cover
  decoded playback and seeking, MP4/GIF/PNG exports, download byte equality,
  two-source reopening, unchanged prior exports, settings preserving edits,
  system appearance, responsive read operations during rendering, cancellation,
  and the 1366×768 layout.
- **16 upstream packaging checks passed**, zero failed or skipped, against the
  extracted source distribution using the installed CLI. The initial checkout run
  counted a disposable install environment as a duplicate manifest; checking the
  actual distribution confirmed it contains exactly one canonical manifest.
- Ruff lint/format, wheel/source distribution builds, and `git diff --check` passed.

These results do not mark any entire AT row as passed.

The second milestone adds checks for catalog limits and confinement, real sampled
frame pixels/gaps, embedded and sidecar caption timing, missing-caption fallback,
provider image delivery and path exclusion, grant enforcement, invocation budgets,
evidence-reference validation, sanitized provider errors, limitation questions,
idempotent find/make and active-Agent cancellation. Scripted fixtures test the
plumbing; they never stand in for real-scene recognition.

The real cached-session integration check is opt-in with
`OUTTAKE_TEST_CACHED_AMPLIFIER=1`; it requires the pinned Agent bundle/modules to
already be cached. Run it with network denied when validating the offline claim.
The ordinary smart tests use the actual Engine with an isolated session fixture.
Base-only installations skip the smart test module, so those runs are not full
integration passes.

## Remaining implementation

1. Human-confirmed real-scene acceptance and broader provider/model coverage.
   Vision in a grant is a caller declaration, not a completed per-model capability test.
2. Multi-clip ordering and broader output policies. Natural-language refinement remains a new explicit find or
   calling-agent interpretation followed by deterministic plan revision.
3. Broader dashboard accessibility, large saved collections, and cross-browser coverage.
4. Broader timing/codec coverage, including variable frame rate and audio offsets,
   concurrency across processes, and full schema/receipt compatibility guarantees.

HDR and rotated media are currently rejected. Non-square pixels are normalized using the source display aspect ratio. Editing output
is a high-quality H.264 re-encode, not a lossless master. An initial full-source hash can consume substantial time on large mounted files.
A bounded process-local hash cache reuses unchanged file identities; accurate input
seeking avoids decoding from the beginning for late-film renders and observations. Only macOS has been exercised.

The initial product deliberately leaves sound verification to the person via
local playback and boundary edits. Sound is unverified by Outtake; no raw audio
is disclosed to a provider. This is an agreed scope decision, not a model failure.

Human-approved cuts, the independent calling-agent exercise, broader live-provider
coverage, full dashboard acceptance, and complete product conformance remain
unverified. Automated correctness tests use generated media with independent
expected pixels and audio; real scene trials remain separate.

## Sources for implementation choices

- Smart Tool spec revision
  [`0f89dd9263338918d9b27bb48670c688c3e9bac1`](https://github.com/microsoft/amplifier-smart-tools/tree/0f89dd9263338918d9b27bb48670c688c3e9bac1/spec).
- [FFmpeg trim and timestamp filters](https://ffmpeg.org/ffmpeg-filters.html#trim)
  and [protocol restrictions](https://ffmpeg.org/ffmpeg-protocols.html).
- Possibly integration reviewed at revision
  [`1011cae68c0b0e5ef4254a89814a8be7251e5c4f`](https://github.com/robotdad/possibly/tree/1011cae68c0b0e5ef4254a89814a8be7251e5c4f).

## Refinement update

Timed manual/caption cues, default text-caption import with explicit opt-out and
track selection, installed-font discovery, editable titles, export deletion and
mobile output presets now share library/CLI/dashboard behavior. Original whole-cut
text remains compatible. Multiple cues use source-relative times and explicit
stacking; immutable revisions preserve manual edits. Rendered previews use actual
fonts; the live browser text draft remains approximate. Caption import replaces
caption cues explicitly. Image subtitle import preserves original appearance; local OCR is an explicit separate operation. No transcription is performed.

Mobile defaults are 480px, 10fps GIF / 24fps MP4, with public width/rate overrides.
Receipts expose actual size; no target-size encoding promise is made. Discovered
fonts depend on the host; only macOS has been exercised. The UI has one selection
play/pause control and source-context expansion under Refine. Full contract
conformance and human-confirmed semantic cuts remain separate acceptance work.

Refinement verification: a fresh wheel passed 45 tests with network denied (including
cached Amplifier integration), six Chromium dashboard tests, and all 16 upstream
packaging checks. Decoded-frame checks cover timed text boundaries and stills;
workflow checks cover cue/font/title persistence, Mobile export, Unicode download
names and deletion preserving sources/plans. The final download-header and shared
help-inventory changes were also checked against the installed wheel. A real
4.05-second source cut produced a 24.9 MB sharing GIF and a 2.5 MB Mobile GIF;
this comparison is measured, not a size guarantee for other clips.


## Original subtitles and local OCR

DVD/PGS/DVB image track import now retains decoded RGBA display images, timing,
track/language/offset and source fingerprints. PyAV decodes subtitle events in a
bounded, cancellable subprocess; FFmpeg extracts their pixels. Text tracks remain
editable by default; unambiguous image tracks default to original appearance.
Explicit Tesseract conversion creates review-labeled text cues while retaining the
original evidence. Source-caption inclusion and appearance are shared plan fields;
manual text remains independent. Expanded image-caption coverage requires refresh.
No subtitle content leaves the machine during import or OCR.

Original output preserves decoded subtitle appearance subject to output scaling.
Converted text can be styled using existing cue controls. OCR confidence is an
engine score, not a quality guarantee. Low-resolution lettering can confuse “I”
with a vertical bar, and users must review wording/punctuation. Missing Tesseract or
language data leaves original captions available. Only local English OCR has been
exercised; DVB decoding and other OCR languages remain unverified on real media.


Image-caption verification: a fresh wheel passed 48 provider-free tests with
network access denied (including cached Agent integration), seven Chromium tests,
and all 16 upstream package checks. Synthetic PGS events verified actual decoded
pixels at start/end boundaries, captions crossing a trim boundary, offset handling,
square-pixel output dimensions, stale evidence rejection and cancellation. Local
OCR checks covered retained originals/manual edits, quoted TSV text and actionable
missing-language/engine errors. Browser checks exercised conversion, mode switching,
export persistence and independent manual text. A real DVD-subtitle source also
produced original-caption and styled OCR exports that decoded completely. Its OCR
exposed recognition mistakes, corrected in the editable revision after inspecting
original pixels; this is not blanket OCR or human semantic acceptance.
