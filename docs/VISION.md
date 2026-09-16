# Outtake — Vision (DRAFT)

*For people working with an agent to retrieve and shape moments from their own
video collection. The specific promises live in the
[agent-tool contract](../contracts/agent-tool.v1.md) and
[calling-agent contract](../contracts/caller-interaction.v1.md).*

## What Outtake is

Outtake turns a remembered film or television moment into a usable clip, GIF,
or still. A person describes the moment in ordinary language; their agent uses
Outtake to locate it, show the evidence, refine the selection, and produce the
artifact. Remembering the scene is enough to begin; knowing its timestamp is
not a prerequisite.

Exports serve everyday creative uses: sharing a clip with friends, making a
reaction GIF or image meme, and extracting a higher-quality clip for editing
into a film criticism piece on YouTube. Outtake offers GIFs, still images, and
MP4 video, with a small set of familiar output choices suited to common sharing
and editing needs. People can express the intended use without knowing encoding
terminology. Convenient sharing balances file size and compatibility; material
for further editing preserves the available source quality where practical.
Exact presets and encoding settings remain open, with no ambition to cover
esoteric formats or become a full video editor.

The usual starting point is a known film or show and a remembered moment. The
calling agent owns the conversation: it can help narrow a vague recollection
before reaching for Outtake, then supply the title, description, and useful
context. Outtake resolves the source in the permitted collection, locates and
checks the moment, and returns material the caller can present and refine with
the person. A known show need not mean a known episode, and a title need not
identify a unique file or edition. Missing details become focused questions or
bounded retrieval work, not a demand that the person already know the timestamp.

Outtake is an Amplifier-powered Smart Tool: a library with a command-line
interface and Amplifier Agent as its internal intelligence layer. Configured
vision-capable providers allow it to interpret permitted images sampled from
the actual source. The calling agent does not need to use Amplifier or operate
Outtake's internal Agent sessions. An external agent can complete
the whole task without opening a browser. Deterministic operations, such as
rendering an explicit time range, work without a model.

The agent's general world knowledge, the person's guidance, and available
captions are equally important ways to find a moment; none is a mandatory first
step. An iconic silent gesture is as valid a request as a spoken line. These
clues narrow where to look, and bounded inspection of the actual source checks
the candidate where permitted. The person sets intent and permissions; Outtake
proposes cuts and exposes uncertainty; the calling agent can select and revise.

A moment may be a line, a gesture, a nonverbal sound, an action unfolding over
time, or a transition between shots. Finding a related image is not necessarily
finding the event: the bone-to-spacecraft transition in *2001* needs both sides
of the cut; a flying car passing a billboard needs its movement and context.
The evidence and proposed boundaries must support what the person asked for.
Visual evidence alone does not establish that a particular sound occurred.

The usual workflow starts in conversation with the calling agent, which may
find, refine, and deliver the result without opening a dashboard. When a person
wants to participate, the agent can open the current moment in a compact
workspace for finding and editing. That workspace also supports starting a new
search, without requiring an agent-provided moment to pass through a setup wizard.

The optional dashboard brings candidate moments, source previews, trim and frame
controls, text appearance, and output choices together. Rendering leads to one
saved-outputs view, where people can inspect or download results and return to a
prior request and its edits. Revisiting an export preserves it while allowing a
new revision. History and newly produced results belong to this same collection.

Settings let people manage source folders or mounted shares, output destinations,
and Outtake's Amplifier Agent configuration, including provider and model choices.
The interface supports light, dark, and system appearance. These settings and the
workspace use the same underlying behavior available to the calling agent; the
dashboard is another way to participate, not a separate source of truth.

The same edit plan—a versioned description of sources, cuts, order, appearance,
and output—governs both agent and browser use. The artifact and its receipt
make it possible to see what was requested and what was actually produced.

## Principles

### 1. **The agent can do the whole job.**

No capability is trapped behind a browser control. The library owns behavior;
the command line and dashboard expose it.

### 2. **Evidence anchors the answer.**

Knowledge and guidance generate useful leads, not guaranteed timestamps.
Source evidence establishes whether a candidate is the requested moment;
captions help when present but are not required. Conflicting clues and uncertain
boundaries stay visible rather than being forced into a confident answer.

### 3. **The user's collection and destinations are their choice.**

Sources and output locations are configuration, not developer-specific paths.
Original media stays unchanged, and access remains within approved locations.

### 4. **A revision is an explicit plan, not hidden state.**

Changing a cut, clip order, text, or output produces an inspectable revision.
Returning to a saved plan does not depend on a browser session.

### 5. **Privacy and failure are visible.**

Local mechanical work needs no provider. Smart work uses only an authorized
provider and bounded, permitted evidence. Missing capability, exhausted limits,
and cancellation are reported honestly rather than disguised as success.

## What this deliberately resists

- Unbounded whole-library visual scanning: targeted moment finding does not
  imply permission to inspect an entire collection.
- Silent transcription, image-subtitle recognition, or media uploads to fill gaps.
- Treating a subtitle boundary or shot change as proof of a complete scene.
- A full timeline editor or a dashboard required for routine agent use.
- Canned previews, untraceable outputs, or performance and platform claims
  unsupported by actual verification.

## How you can tell it is working

- A person recognizes the requested moment and can judge its cut and quality.
- A person can obtain a convenient shareable GIF, image, or video, or a
  higher-quality video clip for further editing, with understandable output choices.
- A person can find a silent moment from remembered action or context without
  supplying a quote, captions, or an exact timestamp.
- An external agent finds, revises, and renders using installed documentation
  and the public interface alone.
- A new user selects different source and output folders without changing code.
- A person sees the same selection and appearance in the plan, preview, and
  final output; when something cannot be done, they know why and what to try.

## Changelog

- **2026-09-16** — Clarified optional workspace participation, unified saved
  outputs, return-and-revise behavior, and appearance/folder/intelligence settings.

- **2026-09-16** — Clarified everyday sharing, meme creation, and higher-quality
  editing uses for exports; specific output presets remain open.
- **2026-09-16** — Clarified the calling-agent/Outtake boundary, the usual
  known-title starting point, event-level evidence, and the choice of Amplifier
  Agent with vision-capable providers. Concrete interfaces remain open.
- **2026-09-09** — Draft corrected after review exposed a caption prerequisite
  that excluded iconic silent moments; knowledge, guidance, and captions are
  complementary inputs, and source verification remains distinct from inference.
- **2026-09-09** — First draft, including configurable sources and outputs.
