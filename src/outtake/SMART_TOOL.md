---
smart_tool_format: 1
name: outtake
version: 0.1.0.dev0
description: >-
  Extract local video ranges as MP4, GIF, or PNG with inspectable plans and receipts.
  Find remembered moments through Amplifier Agent with bounded local evidence.
  Optional local dashboard for reviewing, refining, exporting and reopening moments.
use_cases:
  - Make a shareable clip or reaction GIF from a known local time range
  - Extract a still with literal custom text
  - Revise a cut while preserving earlier plans and exports
  - Find a remembered moment using captions, clues and permitted source frames
platforms:
  - macos
  - linux
  - windows
requires:
  - name: FFmpeg and FFprobe
    purpose: Inspect and render local media; manifest and schemas work without them.
    install: https://ffmpeg.org/download.html
    optional: true
---
# Outtake

**The library is the tool.** Import `Outtake`, `Settings`, `Plan`, `Overlay`,
`OuttakeError`, `manifest`, `schemas`, or `skill` from `outtake`. The CLI is a thin
adapter. Chain operations through library return values, not parsed CLI text.

The current implementation handles single-source edits plus bounded Amplifier
finding/making and an optional dashboard. Timed caption/manual text, font discovery, titles, mobile presets and explicit export deletion are supported. Multi-clip assembly remains unimplemented. Do not claim human confirmation or automatic sound verification.
The person reviews sound through local playback and revises the cut. The actual
Amplifier session is covered by offline scripted-provider tests and bounded live
scenario runs. Neither establishes human-approved cuts or complete conformance.

## Installation and prerequisites

Install this checkout with `uv tool install .`, or use `uv sync` and `uv run outtake`.
Without a checkout, git installation uses
`uv tool install git+https://github.com/robotdad/amplifier-smart-tool-outtake`.
Python 3.12+ is required. Install FFmpeg including FFprobe from its official download
page; rendering MP4 requires libx264 and AAC support. Deterministic operations
need no model credentials. For smart finding install the `smart` extra (`uv sync
--extra smart` in a checkout, or `uv tool install ".[smart]"`). For an agent-ready git installation use
`uv tool install "outtake[smart] @ git+https://github.com/robotdad/amplifier-smart-tool-outtake"`. This pins Amplifier
Agent v0.17.0; provider module revisions are pinned in `agent_runtime.py`. Initial
Agent/provider preparation can download modules; no source media is part of setup.

### Optional trusted MCP adapter

The base package neither imports nor starts MCP. Install `outtake[mcp]` (or use
`uv sync --extra mcp` in a checkout) to obtain `outtake-mcp`. First use
`open-review` to explicitly authorize one retained plan, export, or finding for a
portable host. Start stdio with caller-owned settings and the exact review IDs:

```sh
outtake-mcp --settings settings.json --allow-reviews review_<returned-id>
```

The server does not accept arbitrary paths or conversation IDs as authority. It
exposes bounded retained review controls and standard scoped MCP media resources. Model
work through this server is disabled unless startup explicitly adds `--allow-models`;
each such request still requires its own bounded `ModelGrant`. Read
`docs/MCP.md` in the source distribution for capability, recovery and host-disclosure
details. When packaged compiled review HTML is present, it advertises
`ui://outtake/review`; otherwise it truthfully omits that resource.

To list the caller-authorized configured export collection in the portable Saved
Outputs tab, explicitly add `--allow-saved-outputs`. Without that flag the tab lists
only exports reachable from the allowed reviews and their retained workspaces; previews
and arbitrary local paths remain unavailable. The flag does not grant source-root,
state-root, or other filesystem access.

## Caller authority and data

Construct `Outtake(Settings(source_roots=("/media",), output_root="/exports"))`.
Use actual local directories chosen by the caller. Never derive Settings from a
model-produced plan. No remote media URLs or implicit uploads are accepted.
Directory discovery occurs only through bounded catalog/find operations.
Optional `state_root` controls retained plans; on macOS the default is
`~/Library/Application Support/Outtake`.
Settings remain a caller-owned JSON file; Outtake does not discover shell configuration.

All capabilities except `find` and `make` are deterministic. Library methods accept ordinary objects
or JSON-compatible dictionaries. `plan()` and `revise()` return `Plan` values;
`inspect()` returns a `Source`; `render()` and `preview()` return receipt dictionaries.
Use `model_dump(mode="json")` to obtain JSON-compatible dictionaries from model values.
Schemas are available from `schemas()` or `outtake schemas`. These are development
interfaces, not a promise that the complete behavioral contract is implemented.

```python
from outtake import Outtake, Settings

tool = Outtake(Settings(source_roots=("/media",), output_root="/exports"))
plan = tool.plan("/media/example.mp4", 12.2, 16.8, format="mp4")
receipt = tool.render(plan)
revised = tool.revise(plan, {"start": 11.8})
```

Times are seconds from the selected video's first presentation timestamp.
The selected frame is the first at or after the requested start/frame; end is
exclusive. PNG uses `frame` (default start). GIF/PNG use `audio="mute"`.
MP4 preserves the first audio stream unless muted. `share` uses up to 1280px width
and 30fps video; GIF uses 15fps. `editing` preserves source dimensions (rounded
down to even pixels) and uses average source frame rate with H.264 CRF18 rather
than share CRF23. It is a high-quality re-encode, not a lossless editing master.
All media is SDR; HDR and rotated video are rejected explicitly. Non-square pixels are normalized to square pixels using the source display aspect ratio.
Supported local containers are MP4/MOV, Matroska/WebM, AVI and MPEG-TS.

Custom text uses a discovered font ID (or Pillow's bundled default font); text is never an FFmpeg filter or
shell expression. Size, hex colors, outline, normalized position and alignment
are supported. Position is the text's horizontal anchor and top edge. Text is
not auto-wrapped or auto-shrunk; review the preview for clipping. Use `fonts` to discover installed font choices. Selected source captions populate timed editable cues by default when a usable unambiguous text track is available. OCR is explicit and local; no transcription is performed.


### Original image captions and explicit OCR

`caption_mode` is `original` or `editable`; `captions_enabled=false` turns source
captions off without removing either representation or manual text. `revise` changes
these choices without reimporting or replacing edited text. Original mode requires
retained image caption evidence. Text-only tracks use editable cues.

`import-captions` with an image track retains decoded transparent subtitle images,
source-relative display times and import coverage in `caption_evidence_id`. It
selects original mode and explicitly replaces old imported text, preserving manual
cues. `caption-image` resolves one retained image by `{evidence_id, index}` for local
inspection. A cut extended beyond image coverage needs another explicit import.

`convert-captions` accepts `{plan, language?}` and returns a new editable plan using
local Tesseract OCR. Install Tesseract and its language data on PATH to use this
optional operation; original rendering needs no OCR installation. `language` is an
installed Tesseract language ID such as `eng`; omitted language uses track metadata
(with standard French/German aliases). Unknown/unavailable languages fail with
installed choices, rather than silently using English. Conversion is bounded and
cancellable and never calls a provider. It preserves source display timing and
original image evidence, retains manual cues, and explicitly replaces imported
text on repeat conversion. Each OCR cue has `extraction="ocr"`, `confidence` (0–1)
and `review_required=true`. Review recognition errors even at high confidence.
Words and punctuation may need correction. OCR is not scene or dialogue verification.

## Timed text, captions, names and sharing

`plan` accepts `title`, `cues`, `captions_enabled` (default true), `max_width`
and `fps` in addition to the existing arguments. `revise` accepts those same fields.
A cue extends Overlay with `id` (`cue_` plus letters/digits/underscores/hyphens),
`start`, `end`, `enabled`, `origin` (`manual` or `caption`), and `evidence_id`.
Times are source seconds, start inclusive and end exclusive. Cues retain timing
and IDs across trims; rendering intersects them with the selected cut. List order
is stacking order. PNG includes only cues visible at the resolved frame. Legacy
`overlay` remains whole-cut text underneath timed cues.

New plans and smart selections import intersecting captions by default: text tracks become editable cues; supported DVD/PGS/DVB image tracks retain original pixels and timing.
A single eligible track or single declared default is chosen; ambiguity/missing
captions is reported in `caption_status` and `warnings` without preventing manual
editing. `captions_enabled=false` opts out without deleting retained cue edits.
Use `caption-tracks` to list choices and `import-captions` to explicitly replace
caption cues (manual cues remain). Import creates a new revision; it is not a
merge and replaces edits to previously imported captions. Evidence retains language,
track, offset and fingerprint; stale captions fail rendering. Trimming never
reimports captions. After expanding a cut, explicitly import to add new captions.

`fonts` returns the default plus a small set of familiar installed fonts. Nondefault
IDs bind exact font bytes; unavailable/changed fonts fail rather than substitute.
The browser live draft approximates typography; Preview edits uses the actual font.
Available fonts depend on the host. `output-profiles` reports presets:
mobile (480px, GIF 10fps / MP4 24fps), share (1280px, GIF 15fps / MP4 30fps),
editing (source size/rate, GIF 15fps). Width never upscales; `max_width` (160..3840)
and `fps` (1..60) explicitly override presets. Actual bytes/settings are in receipts;
there is no guaranteed target file size or automatic quality reduction.

`title` is editable display metadata and the sanitized export filename stem;
unique export directories prevent collisions. Smart finding proposes a short title;
explicit range plans fall back to the source basename without a model call.
`delete-output` deletes only the identified generated file and receipt, preserving
sources and plans. It reports already absent exports; unsafe paths or incomplete
deletion fail explicitly. This operation is destructive to that generated export.

Example library use (source must be within caller-approved roots):

```python
plan = tool.plan(
    source,
    10,
    15,
    title="Sushi without paying",
    format="gif",
    profile="mobile",
    captions_enabled=False,
    cues=[
        {
            "id": "cue_line",
            "start": 11,
            "end": 13,
            "text": "Let's get sushi",
            "font": "pillow-default",
        }
    ],
)
receipt = tool.render(plan)
# Deliberate deletion of a generated output, not source media:
result = tool.delete_output(receipt["artifact_id"])
```

## CLI capabilities

`-h` is a short summary; `--help` is this library-owned skill. Each capability
has its own focused skill via `<command> --help`, including defaults, examples,
results and recovery guidance; `<command> -h` remains terse CLI syntax. Library
callers can use `skill("render")` (or any other command name) to read the same text
without loading sources or starting a provider. For domain operations, supply `--settings settings.json` and
`--input request.json` (or `--input -` for JSON on stdin). The library receives
the parsed values rather than file references. Requests have these shapes:

- `fonts`: `{}`; available font IDs and names, deterministic.
- `output-profiles`: `{}`; output preset dimensions/frame rates, deterministic.
- `caption-tracks`: `{"plan": ...}`; available text/image track IDs, kind, codec, languages and defaults.
- `import-captions`: `{"plan": ..., "track": "sidecar", "offset": 0}`; a new revision replacing caption cues.
- `rename-output`: `{"artifact_id": "export_...", "title": "A better name"}`; updates the saved name without rendering. Keeps the media path, bytes, artifact ID and publication time; retains a new title-only plan revision. Dashboard downloads use the new sanitized title.
- `delete-output`: `{"artifact_id": "export_..."}`; removal result, or explicit failure.
- `catalog`: `{"title":"Repo Man","scope":"/media/Movies","limit":20,"scan_limit":5000}`. Matches filename/folder clues only; `partial` explicitly reports truncated or unreadable scope.
- `source-details`: `{"source_id":"source_..."}`; fingerprint, duration and available caption tracks. Optional `"fingerprint_source":false` returns cheap metadata without a content hash, suitable for title/episode resolution; it is not source evidence. Actual frame/caption observations and plans still fingerprint content.
- `observe`: `{"source_id":"source_...","times":[12.2,13.5,15]}`; 1..12 increasing sample times, retained image paths, resolved times and gaps. Local only.
- `captions`: `{"source_id":"source_...","query":"plate of shrimp","track":"sidecar","offset":0,"limit":20}`. Same-basename UTF-8 SRT or embedded text tracks (`stream:N` from source-details); no OCR/transcription. Offset is explicit seconds, added to caption times.
- `get-evidence`: `{"evidence_id":"evidence_..."}`; retained frame/caption observations.
- `find` [model-backed]: `{"request":{...},"grant":{...}}`; see below.
- `make` [model-backed]: same, plus optional `format` and `profile`; one candidate is selected and rendered, while multiple candidates stay `needs_selection`.
- `get-finding`: `{"finding_id":"finding_..."}`; retained result and evidence identities.
- `select`: `{"finding_id":"finding_...","candidate_id":"candidate_...","format":"mp4"}`; source/evidence rechecked, returns a plan without another model call. Optional profile and overlay match plan.
- `manifest`: packaged manifest as structured JSON; no arguments.
- `schemas`: public plan/settings/overlay JSON schemas; no arguments.
- `inspect`: `{"source":"/media/example.mp4"}`.
- `plan`: `{"source":"/media/example.mp4","start":12.2,"end":16.8,"format":"mp4"}`.
- `get-plan`: `{"plan_id":"plan_..."}`; load a retained revision.
- `revise`: `{"plan":{...},"changes":{"start":11.8}}`; creates a new revision.
- `validate`: `{"plan":{...}}`; checks current source identity and configured limits.
- `render`: `{"plan":{...}}`; produces a new export directory and receipt.
- `preview`: same input/result as render; actual plan output for local review.
- `saved-outputs`: `{}`; reads exported receipts newest first, excluding previews. `sort_by` also accepts `oldest`, `name` (A–Z), or `size` (largest first). New receipts record `created_at`; older receipts use the receipt file modification time. Use `{"include_previews":true}` to include them.
- `provider-login`: `{"provider":"openai-chatgpt","timeout_seconds":300}`; explicit device authentication, with verification instructions on CLI stderr; no model generation.
- `preferences`: `{}`; current folders/limits, saved model grant and appearance, credential-availability booleans.
- `configure`: `{"settings":{...},"model_grant":{...},"appearance":"system"}`; shared saved configuration. Omit/null the grant for deterministic use.
- `review-frames`: `{"plan":{...}}`; five actual ordered source observations spanning the cut.
- `artifact`: `{"artifact_id":"export_..."}`; validates and retrieves a published receipt.

## Results, limits, and failures

Stdout carries JSON results, stderr diagnostics. Library failures raise
`OuttakeError` with code, message, remedy and optional identity; malformed model
data raises Pydantic `ValidationError`. CLI operational failures exit 1, invalid
input exits 2, and keyboard interruption exits 130. Do not treat a failed call
or missing artifact as success. Closed stdin does not trigger an interactive prompt.

Each direct render gets a new export ID. Direct render retries produce new exports and never overwrite
an earlier result. Artifact and receipt publish together by a directory rename.
Receipt includes the complete plan, resolved start, format settings, content hash,
and sound-review warning. Saved receipts contain the original plan for revision. Caller-range plans can
be restored in a new state folder; model-proposal plans also require their
retained evidence in the original state folder. Portable evidence import/export
is not implemented yet.

Default limits: 120 seconds of work, 120-second cuts, 256MiB output, 512MiB temporary
files, maximum 4K source pixels. Adjust through `Settings.limits`. Limits on disk
are polled and can briefly overshoot; an oversized artifact is never published.
Only one render per process runs at a time; other processes are independent.
Long source hashing or decoding may require a larger wall-time allowance.
Pass a cancellation callback to library inspect/render/preview; return occurs
after subprocess cleanup. Committed outputs and plans survive cancellation.

Source files are SHA-256 fingerprinted and rechecked before publication. A bounded
process-local hash cache reuses a digest only while device, inode, size, modification
time and change time match; a changed identity forces a new full hash.
The caller must keep source and destination directories stable while running;
hostile concurrent filesystem replacement is not an OS sandbox boundary.
Unreadable sources, stale sources, unsupported media, missing FFmpeg, and exceeded
limits produce explicit failures. Source originals are never output destinations.


## Smart finding, disclosure and continuation

The calling agent owns the conversation. Supply the title, remembered event and
optional context as actual content. Outtake does not read the caller's history.
The model gets only the matched/selected source labels and opaque IDs, source
metadata and explicitly permitted observations. No source paths, raw video/audio,
shell, filesystem tool, delegation tool or permission-changing tool is exposed.
Context mentioning a configured source root is redacted before model submission.

```python
from outtake import FindRequest, ModelGrant

request = FindRequest(
    request_id="repo-man-shrimp-1", title="Repo Man", description="the plate of shrimp conversation"
)
grant = ModelGrant(
    provider="gemini",
    model="YOUR_VISION_CAPABLE_MODEL",
    allow_request=True,
    allow_metadata=True,
    allow_captions=True,
    allow_frames=True,
    vision=True,
)
finding = tool.find(request, grant)
# If needs_selection, present candidates and observations before choosing:
plan = tool.select(finding["id"], finding["candidates"][0]["id"])
```

Provider choices are `openai`, `anthropic`, `gemini`, `github-copilot`, and
`openai-chatgpt`. For the three API-key providers, set respectively
`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, or `GOOGLE_API_KEY` (`GEMINI_API_KEY` is a
fallback). Keys stay in process memory and never enter retained grant/result data.
GitHub Copilot requires an account with Copilot access. Run `gh auth login`,
then set `GH_TOKEN` from `gh auth token` in the shell that starts Outtake.
Credential precedence is `COPILOT_AGENT_TOKEN`, `COPILOT_GITHUB_TOKEN`,
`GH_TOKEN`, then `GITHUB_TOKEN`. Tokens stay in runtime configuration, never
plans, grants or preferences.

ChatGPT uses the Amplifier Agent provider-owned OAuth cache, separate from OpenAI
API keys and the calling agent's sign-in. Start an explicit device login:

```sh
printf '%s' '{"provider":"openai-chatgpt","timeout_seconds":300}' |
  outtake provider-login --settings settings.json --input -
```

Read the verification URL/code on stderr and complete sign-in yourself. Login may
prepare/download the pinned provider module, but does not inspect media or generate
a model response. Library callers use `tool.provider_login("openai-chatgpt",
progress=callback)`. The dashboard explains this CLI setup in Settings; it does not
start a sign-in flow. Reopen Settings after login to refresh availability.
Existing provider-cache sign-ins (including Possibly's when using the same
Amplifier Agent state root) are reused. Expired access tokens are refreshed before
mounting; missing/invalid credentials fail with explicit login guidance.
Finding never initiates interactive login. Restart the dashboard after changing
environment credentials. Credential availability is not proof of account/model
access, and a selected model must support both tools and images for visual finding.

`vision=True` is the caller's declaration of model capability, not an independent
capability test. Unsupported image input must fail; it never becomes visual proof.
Live scenario verification is recorded in the implementation status. Provider
availability and semantic quality are separate from packaging conformance.

`request.source_ids` may select up to 20 catalog entries. Otherwise find matches
`title` in the configured roots or optional request `scope`, with 5000 directory
entries examined at most and up to 20 initial matches. The intelligence can narrow
an episode/edition using an additional name clue within the original title and scope;
each resolution is bounded to 20 matches/5000 entries, 100 distinct sources total,
and the shared tool/time/disclosure limits. Explicit source IDs cannot be expanded.
An incomplete search does not establish absence. Labels are clues,
not proof of title/episode/edition identity.

Defaults per find: 8 model calls, 24 tool calls, 24 sampled frames, 250000 bytes of
transmitted/received text, 8000000 base64 image bytes and 2048 output tokens per
model response. Model and tool attempts share one wall-time allowance from
Settings. Repeated conversation text is charged again on every transmission;
provider retries are disabled. Frame samples are downscaled to at most 640 pixels
wide. Lossless PNG observations stay local; the provider receives JPEG review
copies at quality 90, and the actual encoded bytes count against disclosure limits. Observations precede submission; evidence not delivered to a completed
model call cannot support a candidate. Byte caps reject oversized responses after
receipt, so actual usage may exceed that cap by the rejected response.

`needs_selection` contains proposals, evidence IDs, supporting explanations and
explicit uncertainty. Interpretations are not human confirmations. Missing captions
only prevent caption operations, not generic finding. Insufficient evidence returns
`failed` with an actionable next question; that is not proof a scene is absent.
Evidence and source fingerprints are rechecked at selection and rendering.

Each request needs a caller-generated `request_id`. Repeating find with identical
input returns the retained outcome, including a failed outcome, without new model
work. Changed input with the same ID fails. Make similarly returns the same retained
artifact/outcome; changed output choices need a new ID. A crash after publication
but before retaining the make result can leave a saved output with an incomplete
request marker: inspect saved outputs before authorizing another attempt. Interrupted
work is not automatically restarted. Use a new ID to explicitly retry failed work.

A follow-up can select a retained candidate, revise its plan and render without a
model or transcript replay. A new smart investigation uses a new request ID with
explicit context and source IDs. Natural-language refinement is not a separate
implemented operation. When using `make`, a single proposal is automatic selection,
not an assertion of human approval; use find/select for explicit participation.


## Optional dashboard

`tool.dashboard(port=0, plan_id=plan.id)` starts an explicit loopback server and
returns a handle with `url` and `close()` (also a context manager). Use `finding_id`
to open candidate review. CLI: `outtake dashboard --settings settings.json
--plan-id plan_...`; omit the plan to start with an empty workspace. The CLI prints
the session URL, stays running, and closes on Ctrl-C. No launch occurs on import.

The random URL fragment establishes an HttpOnly SameSite session cookie and is
then removed. Keep the initial URL private. API calls require that session and
same-origin/host checks; media URLs accept retained IDs, never arbitrary paths.
The server serves installed static assets and uses the same library operations.
It binds only to 127.0.0.1 and does not support LAN exposure.

Workspace controls revise immutable plans. Preview renders the selected format
for real local review; Export adds a new saved output. Reopening restores the
receipt's source, range, still, text and output settings; earlier exports survive.
Unsaved edits are marked, and Settings preserves them. Candidate interpretation
and source observations remain distinct. Sound is reviewed through local playback.

`configure()` saves folders/limits, model grant and appearance in the selected state
folder. A new `Outtake(settings)` honors its explicit caller settings. To explicitly
reuse the saved folder authority, call `restore_configuration()` or pass
`--saved-settings` to a CLI operation/dashboard launch. Credentials always come
from the host environment and are never saved by the dashboard. Restart the server
to inherit changed shell credentials. An active workspace cannot change its state
folder. Changing the output folder changes which saved outputs are listed.

Jobs are serialized within one dashboard; find/make/inspect/review-frames/preview/render support
cancellation. Other short operations finish within their configured time bounds.
Cancellation acknowledgement is separate from cleanup completion. Closing the
handle cancels supported work and waits for cleanup. The dashboard is not a queue,
a background scheduler, or a required step for agents making exports.


### Durable editing workspaces

`get-workspace` / `get_workspace(plan_id)` resumes saved edits and returns
`workspace_id` plus `plan`. Without saved edits it returns the requested plan.
`save-workspace` / `save_workspace(workspace_id, plan, changes)` creates an
immutable revision and advances the workspace atomically. `changes` uses the
same fields as `revise`; an empty object attaches an existing descendant revision.
Concurrent stale writes fail with `WORKSPACE_CONFLICT`; reload and reconcile
explicitly. `get-plan` always returns its exact immutable revision.

The dashboard saves valid edits after a brief typing pause, preserves the active
text editor, and flushes edits before preview, export, and in-app navigation.
A local pending-edit buffer protects immediate reloads on the same browser origin;
server-saved revisions survive browser and dashboard restarts. The workspace link
resumes saved edits even after an export is deleted. Failed saves remain visibly
unsaved and are never reported as successful. Deleting an output does not delete
its workspace or retained revisions.


Saved Outputs opens a workspace scoped to that export: call `get-workspace`
with `artifact_id` as well as `plan_id`. Export workspaces do not follow a shared
ancestor's draft. After rendering, `finish-workspace-export` takes the source
`workspace_id` and new `artifact_id`, returns the new output workspace, and closes
the source draft only if it still matches the published revision. The original
saved output then opens its own original selection; newer unsaved work is retained.
Dashboard links carry the output identity so reloads resume the correct draft.
