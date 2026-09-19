# Optional MCP collaborative review

Outtake's optional MCP server is a narrow stdio adapter over the same public Python
library and SQLite retained state used by the JSON CLI. It is not required for normal
library, CLI, dashboard, catalog, preview, or render use.

## Install and authorize

Install the optional adapter alongside Outtake:

```sh
# from this review checkout
uv sync --extra mcp
```

This work is on `feat/mcp-collaborative-review`. Until the review commit is published,
use the checkout command above. The PR will include a verified commit-pinned installation:
`uv tool install "outtake[mcp] @ git+https://github.com/robotdad/amplifier-smart-tool-outtake@<published-commit>"`.

Create a review identity with the normal public API or JSON CLI first. This is the
explicit decision to disclose one retained finding, plan, or export to a trusted
portable host:

```sh
outtake open-review --settings settings.json <<'JSON'
{"target_kind":"plan","target_id":"plan_...","scope":"my-trusted-host"}
JSON
```

Start the server only with caller-owned settings and the exact review identities that
host may attach to:

```sh
outtake-mcp --settings settings.json --allow-reviews review_...
```

That scope lists only exact artifact review targets and exports recorded as outputs
of authorized review operations. Sharing a plan ID does not authorize another export.
To expose
the configured output collection's ordinary **exports** (not previews), explicitly
add `--allow-saved-outputs`:

```sh
outtake-mcp --settings settings.json --allow-reviews review_... --allow-saved-outputs
```

Use that flag only for a caller-authorized output collection. It exposes no source
root, state root, arbitrary filesystem handle, HTTP URL, or output collection outside
the supplied settings. Without it, the Saved Outputs tab still lists exports reachable
from the allowed reviews and their owned operations; it is not an
unavailable control. The server does **not** trust a host conversation ID, an arbitrary
path, or a model claim as authority. A second unrelated review needs another explicit
`--allow-reviews` entry.
For example, a host configuration can use:

```json
{
  "command": "outtake-mcp",
  "args": ["--settings", "/caller/settings.json", "--allow-reviews", "review_..."]
}
```

Model-backed portable `find`/`make` work is disabled by default. To enable it for this
server only, add `--allow-models`; each admitted request still needs its bounded
`ModelGrant`. Credentials remain in the host environment/provider cache and are never
stored in review, admission, or MCP response records.
Install both extras (`uv sync --extra mcp --extra smart`) for model-backed work.
Portable continuations are confined to source identities authorized by the retained
finding. Initial discovery and source-folder configuration remain library/CLI tasks.

## Tools and workflow

| Tool | Purpose |
|---|---|
| `outtake_review` | Read bounded retained review/workspace/finding state. |
| `outtake_read_draft`, `outtake_finding_page` | Read one exact draft or a bounded page of candidates from a linked finding. |
| `outtake_operation_result_page` | Read host-safe result JSON in base64 pages up to 64 KiB. |
| `outtake_navigate` | Versioned semantic focus: displayed plan/finding/candidate/cue/playhead; it never follows a newer head implicitly. |
| `outtake_save_draft` | Save raw editor values with optimistic draft versioning; it does not change a plan. |
| `outtake_apply_changes` | Apply an exact displayed `plan_id` through shared workspace conflict checks. |
| `outtake_select_candidate` | Select a candidate from the explicitly reviewed finding. |
| `outtake_admit` | Persist exact request/args/effective settings/grant before detached preview/render/find/make work. |
| `outtake_operation`, `outtake_cancel` | Inspect or request cancellation of a retained operation. |
| `outtake_describe_media` | Describe authorized artifact/frame evidence and return its standard resource URI. |
| `outtake_saved_outputs` | Read a bounded (1–50) sorted page of authorized exports; previews are excluded. |
| `outtake_open_saved_output` | Open one listed export in its canonical export workspace without rendering. |
| `outtake_describe_saved_output_media` | Return a scoped resource URI for a listed export's verified bytes. |
| `outtake_rename_saved_output`, `outtake_delete_saved_output` | Idempotent scoped rename/delete; neither renders nor touches sources. |

All tool responses use typed MCP structured content plus text supplied by the official
SDK. Tool annotations accurately mark read-only/destructive/idempotent/open-world
behavior. The server declares no MCP Tasks, sampling, elicitation, subscriptions, or
host-private APIs.

`outtake_admit` returns an **admission record**, never a fabricated artifact receipt.
It writes exact immutable input and a preassigned output identity before launching an
owned `outtake.worker` package subprocess. A lost client response can safely repeat
the same request ID and receives the same admission. Changed operation, arguments,
effective settings, or grant under that ID conflicts.

Poll `outtake_operation`. Lifecycle status (`accepted`, `running`, `completed`,
`cancelled`, `failed`, `interrupted`, or `uncertain`) is distinct from the nested
domain result (`ready`, `needs_selection`, etc.). A transport disconnect does not cancel work. Cancellation
is requested separately and serialized against publication: cancellation before the
atomic artifact+receipt rename yields `cancelled`; publication first yields `ready`
with its receipt. `recover_operations` reconciles a preassigned published identity,
marks expired workers interrupted, and never auto-replays unknown or paid model work.
Lease ownership is checked again at the rename boundary, so a worker considered dead
cannot later publish.

Opening a saved output uses the existing retained workspace rather than importing a
copy of its plan or drafts. The canonical export review is linked to the allowed parent
review, so it remains usable after a server reconnect with that same parent in
`--allow-reviews`; the host does not need an unbounded list of derived reviews.
Use stable request IDs for exact retries. Rename and delete additionally require the
displayed receipt `expected_plan_id`, checked under the shared receipt-mutation lock.
Completed retries return their retained outcome; changed input or a stale target
conflicts. A crash after a rename/delete effect but before durable completion leaves
the request explicitly incomplete: matching titles or missing files are not proof
of that request's success. Artifact review authority is rechecked against the current
output root after reconnect. Listing is read-only and never starts a render, finding,
model call, or preview.

## Snapshot and recovery limits

Raw draft input is capped at 256 KiB. A review snapshot returns the full raw draft for
its displayed plan, plus summaries for at most eight other draft bases and at most eight
operation summaries. It never silently embeds an oversized finding: the snapshot marks
it limited and callers use the public bounded finding-page read (1–50 candidates) to
continue. An individual operation result above 256 KiB has an explicit limit marker;
`outtake_operation_result_page` retrieves the host-safe JSON projection in base64
pages up to 64 KiB rather than silently truncating it. Local filesystem paths are
removed before encoding, not merely hidden in the surrounding response.

Applied workspace edits carry their exact mutation identity into the workspace database.
If a process dies after the workspace commit but before the collaboration acknowledgement,
the same request ID deterministically recovers that applied immutable revision rather
than remaining permanently uncertain or creating a second revision. Candidate selection
preassigns and persists one operation-owned plan identity before the public selection
boundary. A retry can finalize only that exact identity; it never scans for an
equivalent-looking older plan. If the owned identity was not retained, the request stays
explicitly incomplete rather than guessing. A newer explicit navigation is preserved
instead of being overwritten while that selection completes.

## Material and disclosure

`describe_media` accepts the exact reviewed artifact, outputs owned by that review's
operations, or approved frame evidence. It returns
`outtake://review/{review_id}/media/{media_id}/{offset}`. The
MCP resource template reads a fixed 192 KiB chunk at the decimal offset; there is no
invented Range protocol. The JSON review resource is
`outtake://review/{review_id}`. Library reads recheck review membership, approved
output/state roots, symlinks, byte size, and SHA-256 using the same open descriptor
for hash and bytes. They never return filesystem paths. Raw source media and audio, paths,
dashboard tokens, provider credentials, and private errors are excluded from host
projections.

Saved-output card previews, playback and downloads use
`outtake://saved-output/{artifact_id}/{offset}` only after library scope checks.
Each fixed chunk rechecks collection/review membership, confinement, symlinks, size
and SHA-256; neither the card data nor its resource URI exposes a local path. The App
reads and verifies those bytes before creating a local Blob URL. It never uses the
native dashboard's loopback HTTP media URLs.

The package includes compiled `resources/mcp_app.html` and third-party notices. The server
advertises `ui://outtake/review` with standard MCP Apps metadata on review tools. The
server does not fabricate that resource when the packaged asset is absent.

## Capability matrix

| Capability | Library / JSON CLI | MCP | Portable App |
|---|---|---|---|
| Initial discovery and configuration | Yes | Not exposed | Not exposed |
| Revisions, preview/render | Yes | Exact retained plan | Explicit apply, preview, export |
| Retained raw draft | Yes | Versioned exact-target save/read | Save, restore, conflict reporting |
| Candidate selection | Yes | Reviewed finding only | Review evidence and select |
| Semantic review navigation | Yes | Versioned focus | Explicit revision/head adoption and playhead |
| Operation status/cancel | Yes | Scoped review | Poll, explicit cancel, reopen |
| Interrupted-operation recovery | Yes | No recovery mutation exposed | Reports retained outcome; use CLI recovery |
| Scoped media | Yes | Standard resources | Verified playback/download up to 32 MiB |
| Saved outputs | Yes | Bounded authorized exports; `--allow-saved-outputs` for all configured exports | Native grid, sorting, refresh, open, rename/delete and verified media |
| Model find/make | Direct grant | `--allow-models` plus grant and retained source scope | No generation/grant controls |
| Native dashboard | Yes | No host embedding | Separate from native dashboard |

## Reproducing the provider-free checks

From the review checkout with Python 3.12+, FFmpeg/FFprobe and Node installed:

```sh
uv sync --extra mcp --extra smart --locked
npm ci --prefix mcp-app
npm run build --prefix mcp-app
uv run playwright install chromium
PATH="$PWD/.venv/bin:$PATH" uv run pytest -q -rs
uv run ruff check src tests
uv run ruff format --check src tests
uv build
```

The independent browser fixture uses official AppBridge (MCP Apps SDK 2.0.0),
MCP Python SDK 2.2.0 and Playwright 1.63.0/Chromium. It discovers and reads the
advertised HTML resource, rather than substituting a mock view. Checks exercise
real generated media, byte-verified downloads, dark/light/narrow layouts,
displayed-plan/head separation, draft preservation, reopen, and lost responses.
The stdio regression disconnects after admission and reconnects to the same render.

The current integrated Linux aarch64 run passed 114 tests with three explicit skips:
two local OCR tests need Tesseract; the cached-intelligence test is opt-in.
No live-provider inference or scene-recognition claim follows from these tests.
Other production hosts and Windows have not been verified by this contribution.
Optional protocol features such as Tasks, sampling, elicitation and subscriptions
are not implemented. A selection interrupted before its preassigned plan is retained
remains explicitly incomplete; retries do not generate another plan.