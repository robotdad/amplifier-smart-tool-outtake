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

Search starts with text captions associated with local video sources.
Bounded inspection of caption-selected candidates helps refine a moment where
permitted. The person sets the intent and permissions; Outtake proposes cuts
and exposes uncertainty; the calling agent can select and revise them.

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

A remembered moment is matched to a source and caption evidence, not presented
as found because a model remembers the film. Ambiguity stays visible.

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

- Whole-library semantic visual search: the scope is caption-led retrieval.
- Silent transcription, image-subtitle recognition, or media uploads to fill gaps.
- Treating a subtitle boundary or shot change as proof of a complete scene.
- A full timeline editor or a dashboard required for routine agent use.
- Canned previews, untraceable outputs, or performance and platform claims
  unsupported by actual verification.

## How you can tell it is working

- A person recognizes the requested moment and can judge its cut and quality.
- An external agent finds, revises, and renders using installed documentation
  and the public interface alone.
- A new user selects different source and output folders without changing code.
- A person sees the same selection and appearance in the plan, preview, and
  final output; when something cannot be done, they know why and what to try.

## Changelog

- **2026-09-09** — First draft, extracted from the reviewed build brief and the
  explicit end-user source/output configuration clarification.