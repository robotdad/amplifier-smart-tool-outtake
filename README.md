# Outtake

A library-first tool for finding and shaping remembered film and television moments.
The [vision](docs/VISION.md) and [contracts](contracts/agent-tool.v1.md) remain drafts.

Outtake now includes deterministic single-source editing and an **Amplifier Agent
finding integration**: bounded source discovery, text-caption search, timestamped
frame evidence, selectable proposed cuts, and headless find-to-export. All behavior
lives in the library behind the thin JSON CLI and optional loopback dashboard.
The workspace supports source review, cut/text controls, real previews, exports,
saved-output reopening/deletion, shared settings, and light/dark/system appearance.
Timed text cues import available captions by default and support manual dialogue,
font selection and explicit on/off times. Named exports and Mobile presets are
available through the same library and CLI used by the dashboard.
Real-model proposals still require review; see the implementation status for evidence.

```sh
uv sync
uv run outtake --help
uv run outtake render --help  # Focused agent skill for one command
uv run outtake render -h      # Concise flag reference
uv run playwright install chromium
uv run pytest
uv run ruff check .
```

FFmpeg and FFprobe must be installed for media operations. See the packaged
[usage guide](src/outtake/SMART_TOOL.md) for library examples, CLI request shapes,
current limits, and error behavior. `uv run outtake schemas` emits the actual
public data schemas. Deterministic operations need no provider. For smart finding,
install `uv sync --extra smart` and explicitly supply a named provider/model grant.
See the usage guide for disclosure categories and budgets.

The user reviews sound through local playback and adjusts cuts. Outtake does not
claim to have listened or automatically verified nonverbal sound.

Implementation follows the upstream Smart Tool specification at
[`0f89dd9`](https://github.com/microsoft/amplifier-smart-tools/tree/0f89dd9263338918d9b27bb48670c688c3e9bac1/spec).
Passing its packaging checks alone does not establish a complete Smart Tool or
the product acceptance scenarios. See [implementation status](docs/IMPLEMENTATION.md).

Launch the optional workspace explicitly, using caller-selected folders:

```sh
uv run outtake dashboard --settings settings.json --plan-id plan_...
```

Open the returned session URL. Omit `--plan-id` to start empty, or use
`--finding-id finding_...` to show candidates. `--saved-settings` explicitly reuses
folder/limit preferences saved in that workspace. Ctrl-C closes the server.
No browser or server is required for normal library/CLI calls.

Source captions support editable text tracks and original-appearance DVD/PGS/DVB
image tracks. Explicit local OCR (`convert-captions`) requires Tesseract and its
language data on PATH; imported image captions work without it. OCR creates timed,
review-labeled text for styling and preserves the original images. No provider is
used for import or conversion.
