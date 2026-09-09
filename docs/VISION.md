# Outtake — Vision (DRAFT)

*For people working with an agent to retrieve and shape moments from their own
video collection. The specific promises live in the
[agent-tool contract](../contracts/agent-tool.v1.md).*

## What Outtake is

Outtake turns a remembered film or television moment into a usable clip, GIF,
or still. A person describes the moment in ordinary language; their agent uses
Outtake to locate it, show the evidence, refine the selection, and produce the
artifact. Remembering the scene is enough to begin; knowing its timestamp is
not a prerequisite.

Outtake is a Smart Tool: a library with a command-line interface and its own
configured model for interpreting requests. An external agent can complete
the whole task without opening a browser. Deterministic operations, such as
rendering an explicit time range, work without a model.

The agent's general world knowledge, the person's guidance, and available
captions are equally important ways to find a moment; none is a mandatory first
step. An iconic silent gesture is as valid a request as a spoken line. These
clues narrow where to look, and bounded inspection of the actual source checks
the candidate where permitted. The person sets intent and permissions; Outtake
proposes cuts and exposes uncertainty; the calling agent can select and revise.

People choose their source folders or mounted shares and where outputs go.
The optional dashboard provides compact Create → Refine → Results interaction,
real playback, simple trim and reorder controls, appearance settings, and
downloads. It is another way to use Outtake, not a separate source of truth.

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
- A person can find a silent moment from remembered action or context without
  supplying a quote, captions, or an exact timestamp.
- An external agent finds, revises, and renders using installed documentation
  and the public interface alone.
- A new user selects different source and output folders without changing code.
- A person sees the same selection and appearance in the plan, preview, and
  final output; when something cannot be done, they know why and what to try.

## Changelog

- **2026-09-09** — Draft corrected after review exposed a caption prerequisite
  that excluded iconic silent moments; knowledge, guidance, and captions are
  complementary inputs, and source verification remains distinct from inference.
- **2026-09-09** — First draft, including configurable sources and outputs.