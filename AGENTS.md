# Working with Outtake

Outtake is a library-first Amplifier Smart Tool for finding and shaping remembered
moments from local video. Read the human overview in `README.md`. Treat
`outtake --help` (or `uv run outtake --help` in this checkout) as the current
tool-owned caller skill.

## Using the tool for a person

1. Read the installed help, then `<command> --help` for capability-specific skills
   and exact request shapes. `-h` is the terse flag reference. Use public library
   operations or the JSON CLI; do not write private state as an integration API.
2. Clarify the remembered event enough to search: usually a known film/show plus
   a line, action, or context. The caller owns this conversation. A known show
   need not imply a known episode; do not invent timestamps from world knowledge.
3. Configure caller-selected source roots, output and retained-state directories.
   Originals stay read-only. Access to a collection does not authorize unbounded
   scanning or provider disclosure. Reuse saved folder authority only explicitly
   (`--saved-settings` or `restore_configuration()`).
4. Deterministic operations need no provider. For `find`/`make`, install the `smart`
   extra and supply a named provider/model and bounded `ModelGrant`, including the
   permitted request, metadata, caption and frame disclosures. Keys come from the
   host environment (or ChatGPT’s provider-owned OAuth cache), never request records.
   Use `provider-login` explicitly for ChatGPT device authentication; finding must
   never launch login. Copilot uses a host GitHub token and requires Copilot access. Outtake does not inherit the calling
   agent's model access. Honor existing authorization without repeatedly asking.
5. Keep request, source, finding, evidence, plan and output IDs. Identical find/make
   retries reuse retained outcomes; changed intent needs a new request ID. A failed
   search is not proof the scene is absent. Read uncertainty and incomplete-scan flags.
6. Review candidates against the requested event, including context on both sides
   of a transition. Select and revise through the public interface. A model proposal
   is not human confirmation. Sound is for local human review, not inferred proof
   from still frames. No raw video/audio is sent to providers.
7. Export directly when appropriate, or explicitly launch the authenticated loopback
   dashboard for participation. Keep its session URL private. The CLI remains running
   until stopped; closing a tab does not stop the server. Preserve unsaved user edits.
8. Import available captions by default while respecting explicit opt-outs. Image
   captions can retain original appearance; conversion to editable text requires
   explicit local OCR and review. Trimming does not reimport captions. Expanded
   coverage may need another import, which replaces prior imported-caption edits.
9. Use meaningful output names and a suitable sharing/editing preset. Check the
   rendered result and receipt, then present the output. Reopen saved plans for
   further revisions. Delete generated outputs only when requested; preserve sources.

See `src/outtake/SMART_TOOL.md` for installation, grants, error recovery, limits,
caption behavior and library examples. Never substitute private trial files for
self-contained caller documentation.

## Develop from this checkout

```sh
uv sync --extra smart
uv run playwright install chromium
uv run outtake --help
uv run pytest
uv run ruff check src tests
uv run ruff format --check src tests
uv build
```

Python 3.12+, FFmpeg and FFprobe are required. Chromium is for browser tests, not
normal tool use. `uv.lock` pins the environment and `pyproject.toml` pins Amplifier
Agent; review compatibility deliberately when updating it. Optional image-caption
OCR needs Tesseract and the relevant language data on PATH.

Tests use isolated fixtures and scripted providers. Live scenarios require existing
or explicit bounded authorization and spend provider tokens. To exercise the cached
real-Agent offline test, set `OUTTAKE_TEST_CACHED_AMPLIFIER=1` and deny network
access. Scripted-provider checks establish integration, not scene recognition.

Run the upstream conformance kit against an installed CLI:
`uv run <spec-checkout>/conformance/run.py <outtake-distribution-root>`.
The root `smart-tool.json` invokes `outtake`, which must be on PATH. The previously
verified spec revision is `0f89dd9263338918d9b27bb48670c688c3e9bac1` in
[microsoft/amplifier-smart-tools](https://github.com/microsoft/amplifier-smart-tools/tree/0f89dd9263338918d9b27bb48670c688c3e9bac1/spec).
Read the current upstream spec before changing conformance behavior. Passing
packaging checks does not establish product acceptance; see `docs/IMPLEMENTATION.md`.

## Code map and boundaries

| Area | Responsibility |
|---|---|
| `src/outtake/lib.py`, `models.py`, `capabilities.py` | Public operations, settings, plans, grants and schemas |
| `discovery.py`, `media.py` | Bounded source discovery, inspection, evidence and FFmpeg rendering |
| `subtitles.py`, `subtitle_worker.py` | Text/image captions and explicit local OCR |
| `editing.py`, `workspace.py` | Revisions, retained state, saved outputs and preferences |
| `intelligence.py`, `agent_runtime.py` | Amplifier Agent, bounded finding and permitted evidence |
| `dashboard.py`, `static/` | Authenticated loopback adapter and optional editing UI |
| `cli.py`, `help.py`, `SMART_TOOL.md` | Thin JSON CLI and library-owned help/skills |

All externally useful domain behavior belongs in the library. The CLI and browser
must not own exclusive business logic. Keep deterministic work model-free. Treat
paths, captions, provider output and browser inputs as untrusted data; a model must
never expand access or change permissions. Keep output confinement, source identity
checks, immutable revisions, receipts, bounded work and cancellation intact.

## Change and review workflow

- Read `docs/VISION.md`, `contracts/agent-tool.v1.md` and
  `contracts/caller-interaction.v1.md` before planning or changing behavior. Read
  nested guidance when present. Explain discrepancies rather than quietly changing
  promises. Keep vision and contracts DRAFT until the owner explicitly locks them
  after runnable end-to-end verification. Propose changes to locked documents
  separately; do not rewrite them in place.
- Preserve unrelated work and keep changes scoped. Keep credentials, developer
  paths, media inventories, generated exports and exploratory scenarios in ignored
  `.work/` or caller-owned storage. Deliberately published README screenshots belong
  in `docs/images/` with provenance notes; exclude paths, tokens and credentials.
- Keep governing documents self-contained with repo-relative or public references.
  Keep README focused on people getting started. Update tool-owned skills and
  capability help alongside API changes, avoiding duplicate drifting API guides.
- Define independent expected results for meaningful behavior checks. Verify a fresh
  installed copy and applicable public CLI, decoded media, and browser behavior.
  Unit tests and HTTP success alone do not establish correct media or interaction.
- Report validation honestly: skipped/blocked scenarios are not passes, scripted
  providers do not prove recognition, and human-confirmed cuts require human review.
  Use real results, never canned outputs as evidence.
- Publish commits or push when requested. Catalog contributions should follow the
  catalog's current contribution guidance; generated snapshots belong to the catalog.
