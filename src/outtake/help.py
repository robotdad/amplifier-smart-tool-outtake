"""Focused, library-owned command skills. Rendering help performs no domain work."""

import inspect
import json
from importlib.resources import files

from .capabilities import OPERATIONS

EXTRA_COMMANDS = {
    "manifest": "Read the packaged tool identity and guidance.",
    "schemas": "Read the public JSON schemas for structured inputs.",
    "dashboard": "Launch the optional local review workspace.",
}

# Example, result, behavior/defaults and recovery guidance for each capability.
GUIDANCE = {
    "get-evidence": (
        {"evidence_id": "evidence_<returned-id>"},
        "A retained evidence record: source identity plus frames, caption hits, image displays or OCR provenance depending on kind.",
        "Reads existing evidence without extraction or a model call. This lookup alone does not revalidate current source bytes; selection and rendering recheck dependencies. Local evidence is not permission to disclose it to a provider.",
        "RECORD_MISSING requires the original state folder or repeating the appropriate bounded observation/import. Inspect kind before interpreting frames or hits.",
    ),
    "caption-tracks": (
        {"plan": "@plan"},
        "A list of track IDs, language, kind, codec and default flags.",
        "Discover tracks before choosing a language. Text and supported image tracks are distinct; this does not import captions.",
        "If no tracks are returned, keep manual text available. Inspect the source path if probing fails.",
    ),
    "caption-image": (
        {"evidence_id": "evidence_<returned-id>", "index": 0},
        "An image path, SHA-256 and source-relative start/end for the selected display.",
        "Index is zero-based within retained image-caption evidence. Local inspection grants no provider disclosure.",
        "INVALID_EVIDENCE means the ID/type/index is wrong. STALE_EVIDENCE requires reimporting the source track.",
    ),
    "fonts": (
        {},
        "Font IDs, display names and hashes; includes pillow-default.",
        "Choose returned IDs for cue.font or overlay.font. Installed font choices depend on the host.",
        "FONT_UNAVAILABLE during later rendering requires listing fonts again and explicitly choosing another ID.",
    ),
    "output-profiles": (
        {},
        "A mapping of mobile, share and editing to width and frame-rate defaults.",
        "Mobile favors smaller exports. Per-plan max_width and fps override the preset. File size is measured after rendering, not guaranteed in advance.",
        "If output exceeds limits, shorten the cut or choose smaller dimensions/frame rate before rendering again.",
    ),
    "import-captions": (
        {"plan": "@plan", "track": "stream:3", "offset": 0},
        "A new retained Plan revision with caption status, warnings and evidence references.",
        "List tracks first; stream:3 is an example, not a universal English track. Omitted track uses a sole declared default or sole eligible track. Ambiguity remains needs_selection. Offset adds seconds to source caption times. Text becomes editable cues; image tracks use original appearance. Explicit import replaces imported text edits, preserving manual cues.",
        "Check caption_status and warnings even when the call succeeds. INVALID_TRACK requires selecting an available track. Refresh image captions after expanding beyond retained coverage.",
    ),
    "convert-captions": (
        {"plan": "@plan", "language": "eng"},
        "A new editable Plan with OCR cues, confidence and review_required flags; original images remain retained.",
        "Requires imported image captions plus local Tesseract and language data. Omitted language uses track metadata. Conversion preserves timing and manual cues; repeating it replaces imported text edits. No provider is contacted.",
        "MISSING_PREREQUISITE or OCR_LANGUAGE_UNAVAILABLE names the missing local support. Original captions remain usable. Review OCR words and punctuation regardless of confidence.",
    ),
    "delete-output": (
        {"artifact_id": "export_<returned-id>"},
        "Deletion status, removed filenames and already_absent.",
        "Deliberately removes only generated media and its receipt. Source media and retained plans remain. Use a returned export ID, never a path.",
        "DELETE_FAILED can report partial removal; inspect the directory before retrying. Unexpected files or symlinks are refused.",
    ),
    "preferences": (
        {},
        "Current settings, model grant, appearance and credential-availability booleans.",
        "Returns availability, never secret values. This does not restore saved source roots into the current client; CLI --saved-settings explicitly opts into saved folders and limits.",
        "Invalid or inaccessible workspace state must be corrected locally. Do not treat missing credentials as authorization to change provider.",
    ),
    "configure": (
        {"settings": "@settings", "appearance": "system"},
        "The resulting preferences, also persisted for this workspace.",
        "Appearance is light, dark or system. Omitted/null model_grant clears the saved grant. An active workspace cannot change state_root. Folder changes alter accessible sources and the saved-output collection; use caller-authorized paths.",
        "INVALID_INPUT identifies bad settings or an attempted state-folder move. Start a separate workspace to use another state folder.",
    ),
    "review-frames": (
        {"plan": "@plan"},
        "Retained frame evidence with image paths, timestamps and sampling gaps.",
        "Samples five ordered positions across the cut. These are source observations, not the final styled export. Gaps and sound remain unverified.",
        "STALE_SOURCE requires inspecting/reselecting current media. Missing FFmpeg/FFprobe or exhausted resource limits are actionable failures, not empty evidence.",
    ),
    "artifact": (
        {"artifact_id": "export_<returned-id>"},
        "A published receipt binding media path/hash/size to its exact plan.",
        "Looks up one generated artifact within the configured output root. Use saved-outputs to discover IDs.",
        "ARTIFACT_MISSING means the file/receipt is absent or unsafe. Re-render the retained plan if appropriate; do not substitute another output.",
    ),
    "catalog": (
        {"title": "Example Film", "scope": "/media/Movies", "limit": 20},
        "A bounded source listing with IDs, paths, labels, errors and scope_complete.",
        "Scope must be inside approved source roots. Filename/folder matches are clues, not verified title or scene identities. Defaults: limit 20, scan_limit 5000.",
        "A partial result is not proof that no match exists. Narrow scope or explicitly increase scan_limit; inspect reported access errors.",
    ),
    "source-details": (
        {"source_id": "source_<returned-id>", "fingerprint_source": False},
        "Source metadata and available caption tracks, with fingerprinted indicating whether content was hashed.",
        "Default fingerprint_source=true verifies content identity. False is useful for cheap title/episode resolution but is not source evidence.",
        "Missing retained source IDs require catalog discovery again. Source access remains confined to approved roots.",
    ),
    "observe": (
        {"source_id": "source_<returned-id>", "times": [10, 12, 14]},
        "Retained image evidence with requested/resolved times and gaps.",
        "Supply 1–12 increasing source-relative times. Extraction is local; sending frames to a provider needs a separate explicit disclosure grant.",
        "Out-of-range times, missing frames or resource exhaustion must be resolved by changing the bounded sample request. Do not claim events in unsampled gaps.",
    ),
    "captions": (
        {
            "source_id": "source_<returned-id>",
            "query": "remembered phrase",
            "track": "sidecar",
            "offset": 0,
            "limit": 20,
        },
        "Caption evidence with matching text, start/end, track, language, offset and fingerprint.",
        "Searches existing text only: embedded stream:N or same-basename UTF-8 SRT sidecar. List tracks first. No implicit OCR or transcription; offset is added in seconds.",
        "MISSING_TEXT_CAPTIONS does not prevent generic clipping. Use explicit image import/conversion if desired. A match anchors dialogue but does not establish complete scene boundaries.",
    ),
    "find": (
        {"request": "@find-request", "grant": "@model-grant"},
        "A retained finding with candidates/evidence, uncertainty and an actionable status such as needs_selection.",
        "Model-backed through Amplifier Agent. Requires an explicitly selected provider/model and disclosure/budget grant. Put title, description and request_id in FindRequest. A finding is a proposal, not human confirmation; sound requires user review. Does not render an export.",
        "Do not retry blindly after interruption: consult the retained request/finding. Resolve ambiguity with select; inspect credential, disclosure and budget errors without silently switching providers.",
    ),
    "get-finding": (
        {"finding_id": "finding_<returned-id>"},
        "The retained finding and its candidate/evidence identities.",
        "Reads prior work without another model call. Use the original state folder.",
        "RECORD_MISSING requires the correct state folder or a deliberate new find request. Do not invent candidates for a missing finding.",
    ),
    "select": (
        {"finding_id": "finding_<returned-id>", "candidate_id": "candidate_<returned-id>"},
        "A retained model-proposal Plan ready to revise, preview or render.",
        "Deterministic: rechecks candidate source/evidence without another model call. Defaults to MP4/share; imports available unambiguous captions. Preserve the returned candidate identity.",
        "Stale evidence or an invalid candidate requires resolving the finding again. Selection does not establish human approval of scene or sound.",
    ),
    "make": (
        {"request": "@find-request", "grant": "@model-grant", "format": "mp4", "profile": "share"},
        "A finding and, when uniquely selectable, the selected plan and rendered artifact; ambiguity remains needs_selection.",
        "Model-backed: find, select and render in one call only when there is one candidate. Requires the same explicit provider/disclosure/budget grant as find. Defaults MP4/share.",
        "Inspect status and artifact presence; a needs_selection result is not an export. Before retrying an interrupted call, inspect retained findings and saved outputs to avoid duplicate model work or exports.",
    ),
    "inspect": (
        {"source": "/media/example.mp4"},
        "Source metadata including hash, bytes, duration, dimensions, pixel aspect and audio availability.",
        "Reads one approved local source and fingerprints it. Does not modify media or call a provider.",
        "Missing prerequisites, disallowed paths and unsupported HDR/rotation are explicit errors. Do not normalize or replace original media implicitly.",
    ),
    "plan": (
        {
            "source": "/media/example.mp4",
            "start": 10,
            "end": 15,
            "title": "A remembered moment",
            "format": "mp4",
        },
        "A retained immutable Plan, including source identity, cut, output choices and caption status.",
        "Times are seconds from video start; end is exclusive. Defaults: MP4/share, frame=start, source audio preserved for MP4 and muted otherwise. Captions are imported by default when unambiguous; captions_enabled=false opts out. Supports title, cues, overlay, max_width and fps. No render occurs.",
        "Require 0 <= start < end <= duration and frame inside the cut. Missing/ambiguous captions are reported without failing a generic cut. Use inspect and schemas to correct input.",
    ),
    "get-plan": (
        {"plan_id": "plan_<returned-id>"},
        "The exact retained Plan revision.",
        "Load the original revision before revise. A plan ID is not a replacement for the full plan object in commands accepting plan.",
        "PLAN_MISSING requires the original state folder or a supplied plan value. Never reuse an ID for changed fields.",
    ),
    "revise": (
        {"plan": "@plan", "changes": {"title": "A tighter cut", "profile": "mobile"}},
        "A new Plan with a new ID, parent_id and incremented revision; earlier plans/exports remain intact.",
        "Allowed changes: start, end, frame, format, profile, audio, overlay, title, cues, captions_enabled, caption_mode, max_width, fps. Trimming preserves cue source timing and edits. caption_mode is original or editable; captions_enabled=false disables source captions without removing manual text. Use import-captions explicitly to refresh coverage.",
        "PLAN_CONFLICT means the supplied base differs from its retained revision. Load get-plan first. INVALID_REVISION names unsupported fields; do not mutate source or provenance.",
    ),
    "validate": (
        {"plan": "@plan"},
        "A ready result with plan_id if current source, evidence, fonts and limits validate.",
        "Does not render or judge whether the semantic moment is correct. Validity can change if source/evidence/font files change later.",
        "Follow STALE_SOURCE, STALE_EVIDENCE, FONT_UNAVAILABLE or CAPTION_COVERAGE remedies. Validation success does not authorize a different source or wider cut.",
    ),
    "preview": (
        {"plan": "@plan"},
        "An artifact receipt with purpose=preview, exact plan, media path, hash, bytes and resolved timing.",
        "Renders the actual selected format, captions, fonts and overlays. Same renderer as export; previews are excluded from saved-outputs unless include_previews=true. Local deterministic operation.",
        "Source changes, missing fonts and output/time/space limits fail explicitly. Shorten the cut or change width/fps when too large; do not present a failed preview as complete.",
    ),
    "render": (
        {"plan": "@plan"},
        "A published export receipt with artifact_id/path, receipt path, SHA-256, bytes, created_at, resolved timing and exact plan.",
        "Creates a new export directory on every successful call. MP4 can preserve audio; GIF/PNG are silent. Image and text captions follow the plan. The source is unchanged. Repeated rendering creates another export.",
        "STALE_SOURCE or STALE_EVIDENCE, unavailable fonts, invalid coverage and resource limits require correction before retry. Inspect saved outputs after interruption; never claim success without an artifact receipt.",
    ),
    "saved-outputs": (
        {"sort_by": "newest"},
        "Published receipts ordered by the selected sort; previews excluded by default.",
        "sort_by: newest (default), oldest, name (A–Z), size (largest first). include_previews defaults false. Older receipts fall back to receipt-file modification time. Changing output_root changes this list.",
        "INVALID_SORT requires a supported choice. Missing or corrupt receipt files are not silently replaced with invented outputs.",
    ),
}


PARAMETERS = {
    "plan": "Plan object; use the complete returned revision",
    "source": "string; approved local source path",
    "source_id": "string; source identity returned by catalog",
    "evidence_id": "string; retained evidence identity",
    "finding_id": "string; retained finding identity",
    "candidate_id": "string; candidate belonging to that finding",
    "artifact_id": "string; published export identity",
    "plan_id": "string; retained plan identity",
    "index": "integer; zero-based display index",
    "track": "string or null; returned stream:N or sidecar ID",
    "offset": "number; seconds added to source caption times",
    "language": "string or null; installed Tesseract language ID",
    "settings": "Settings object; approved roots and resource limits",
    "model_grant": "ModelGrant object or null; explicit provider permissions and budgets",
    "appearance": "string; light, dark or system",
    "title": "string; source-name clue for catalog, output name for plan",
    "scope": "string or null; search folder inside approved roots",
    "limit": "integer; maximum returned sources or hits",
    "scan_limit": "integer; maximum catalog entries examined",
    "fingerprint_source": "boolean; whether to hash source content",
    "times": "array of increasing numbers; source-relative sample seconds",
    "query": "string; text to search in existing text captions",
    "request": "FindRequest object; title, description, request_id and optional scope/context",
    "grant": "ModelGrant object; caller-authorized provider, model, disclosure and budgets",
    "start": "number; inclusive source-relative cut start in seconds",
    "end": "number; exclusive source-relative cut end in seconds",
    "frame": "number or null; still-frame time inside the cut",
    "format": "string; mp4, gif or png",
    "profile": "string; mobile, share or editing",
    "audio": "string or null; preserve or mute, subject to output format",
    "overlay": "Overlay object or null; legacy whole-cut text",
    "cues": "array of TextCue objects; timed text in stacking order",
    "captions_enabled": "boolean; source-caption inclusion",
    "max_width": "integer or null; output width override",
    "fps": "integer or null; output frame-rate override",
    "changes": "object; only supported revision fields",
    "include_previews": "boolean; include otherwise hidden preview receipts",
    "sort_by": "string; newest, oldest, name or size",
}


def command_names():
    return (*OPERATIONS, *EXTRA_COMMANDS)


def command_skill(name):
    from .lib import Outtake

    if name not in command_names():
        raise ValueError(f"Unknown capability: {name}")
    root = files("outtake")
    model_backed = name in {"find", "make"}
    lines = [
        f'<skill_content name="outtake-{name}">',
        f"Skill directory: {root}",
        "Repository: https://github.com/robotdad/amplifier-smart-tool-outtake",
        "Relative paths below are relative to the skill directory.",
        "",
        f"# outtake {name}",
        "",
        OPERATIONS.get(name, EXTRA_COMMANDS.get(name)),
        "",
        "## When to use",
        "",
    ]
    if name in GUIDANCE:
        example, result, behavior, recovery = GUIDANCE[name]
        lines += [
            behavior,
            "",
            f"Execution: {'model-backed; consumes provider tokens' if model_backed else 'local; no model-provider call'}.",
            "",
            "## Arguments and defaults",
            "",
            "JSON object keys are library arguments, not CLI flags. Full plan/settings values are objects, not filenames or IDs.",
            "",
        ]
        for param in inspect.signature(
            getattr(Outtake, name.replace("-", "_"))
        ).parameters.values():
            if param.name in {"self", "cancelled"}:
                continue
            default = (
                "required"
                if param.default is inspect.Parameter.empty
                else "default " + json.dumps(param.default)
            )
            lines.append(f"- `{param.name}` — {PARAMETERS[param.name]}; {default}.")
        lines += [
            "",
            "Nested types and constraints: `outtake schemas`. Plan fields, FindRequest and ModelGrant are documented in SMART_TOOL.md and models.py.",
            "",
            "## Example",
            "",
            "Replace example paths/returned-ID placeholders with authorized local values."
            + (
                " plan.json holds a complete plan returned by plan/get-plan/select, not a receipt."
                if "@plan" in example.values()
                else ""
            )
            + (
                " find-request.json and model-grant.json hold caller-approved values conforming to find_request/model_grant schemas."
                if model_backed
                else ""
            ),
            "",
            "```bash",
            "python - <<'PY' > request.json",
            "import json",
            "from pathlib import Path",
        ]
        request = repr(example)
        for marker, filename in [
            ("plan", "plan.json"),
            ("settings", "settings.json"),
            ("find-request", "find-request.json"),
            ("model-grant", "model-grant.json"),
        ]:
            request = request.replace(
                repr("@" + marker), f'json.loads(Path("{filename}").read_text())'
            )
        lines += [
            f"request = {request}",
            "print(json.dumps(request))",
            "PY",
            f"outtake {name} --settings settings.json --input request.json",
            "```",
            "",
            "`--input -` reads JSON from stdin (the default); empty input is invalid. `--saved-settings` explicitly restores this workspace's saved folders and limits.",
            "",
            "## Library equivalent",
            "",
            "```python",
            "import json",
            "from pathlib import Path",
            "from outtake import Outtake, Settings",
            'tool = Outtake(Settings.model_validate_json(Path("settings.json").read_text()))',
            'request = json.loads(Path("request.json").read_text())',
            f"result = tool.{name.replace('-', '_')}(**request)",
            "```",
            "",
            "Compose operations through the library and pass returned values directly. Library callers can supply cancelled=callback where the signature supports it; this is not a JSON/CLI argument.",
            "",
            "## Result and side effects",
            "",
            result,
            "",
            "## Failures and recovery",
            "",
            recovery,
        ]
    elif name == "dashboard":
        lines += [
            "Launch only when the user wants to review or edit locally. Domain operations remain available without a browser. Launch itself makes no model call; using Find in the workspace can invoke the configured provider.",
            "",
            "## Arguments and defaults",
            "",
            "- `--settings PATH` — required Settings JSON file.",
            "- `--saved-settings` — opt into saved folders and limits; default false.",
            "- `--port INTEGER` — default 0 (choose a free local port).",
            "- `--plan-id ID` / `--finding-id ID` — optionally open retained work.",
            "",
            "## Example",
            "",
            "```bash",
            "outtake dashboard --settings settings.json --port 0",
            "```",
            "",
            "## Library equivalent",
            "",
            "Use `tool.dashboard(port=0, plan_id=None, finding_id=None)` as a context manager; its `url` opens the workspace. Keep the context alive while using it.",
            "",
            "## Result and side effects",
            "",
            "Prints a ready JSON object containing the loopback URL, including a session token, then keeps serving until interrupted. Keep the token private. Does not automatically render, open a browser or call a provider.",
            "",
            "## Failures and recovery",
            "",
            "Invalid settings or an occupied port prevent launch. Choose another port or correct settings. CLI Ctrl-C interrupts the process; retained work remains.",
        ]
    else:
        lines += [
            "Read-only metadata; no settings, credentials or source media required. No provider call.",
            "",
            "## Arguments and defaults",
            "",
            "No arguments.",
            "",
            "## Example",
            "",
            "```bash",
            f"outtake {name}",
            "```",
            "",
            "## Library equivalent",
            "",
            "```python",
            f"from outtake import {name}",
            f"result = {name}()",
            "```",
            "",
            "## Result and side effects",
            "",
            "Manifest identity/frontmatter plus Markdown body as JSON."
            if name == "manifest"
            else "JSON schemas keyed by plan, settings, overlay, TextCue, find_request, model_grant and candidate_input, plus schema_version.",
            "",
            "## Failures and recovery",
            "",
            "If packaged metadata/resources are missing, reinstall Outtake. These commands do not validate a media request or authorize any source access.",
        ]
    lines += [
        "",
        "CLI successful results are JSON on stdout (help is Markdown). Operational failures exit 1; invalid input exits 2; interrupted domain operations exit 130. Parser errors use stderr; structured operation errors include code, message and remediation. Findings may require selection without being failures: inspect their status. Library errors raise OuttakeError or validation exceptions.",
        "",
        f"Use `outtake {name} -h` for terse CLI syntax and `outtake --help` for the overall workflow.",
        "",
        "<skill_resources>",
        "<file>SMART_TOOL.md</file>",
        "<file>lib.py</file>",
        "<file>models.py</file>",
        "<file>help.py</file>",
        "</skill_resources>",
        "</skill_content>",
    ]
    return "\n".join(lines)
