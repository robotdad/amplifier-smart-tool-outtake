# Calling Agent Interaction Contract — v1 (DRAFT)

**Who builds against this:** Calling agent applications, library/CLI adapters,
the optional dashboard, and people finding and refining moments through them.
The current implementation covers only part of this contract;
see [implementation status](../docs/IMPLEMENTATION.md). The bounded smart interaction and optional dashboard have runnable checks; complete
conformance and human-confirmed scene acceptance remain unverified.

## What it looks like

The calling agent owns the conversation and presentation to the person. It may
narrow a vague recollection before invoking Outtake. Outtake owns retrieval,
source verification, edit plans, and artifact production within supplied scope.
Its intelligence uses Amplifier Agent; callers need neither Amplifier nor access
to internal sessions. Concrete operation names, schemas, and transports remain open.

```text
Caller → known title/show + moment description + useful clues + authority
Outtake → identified candidates + source evidence + proposed cuts + uncertainty
Caller → identified choice or clarification + requested refinement
Outtake → revised plan → requested artifact + receipt
Caller → presents the result and carries the person's next instruction
```

Right: the caller supplies “Repo Man, the plate of shrimp conversation”; Outtake
resolves a permitted source and proposes an evidenced cut the caller can show.
Wrong: Outtake assumes it can read the earlier conversation, or demands a timestamp
as the prerequisite for finding the scene.

Right: “include the setup” revises the identified candidate's cut and preserves
the chosen occurrence. Wrong: silently switch to another occurrence or edition.

## Core (the teeth)

1. **Context crosses the boundary explicitly.** Outtake accepts a title or source
   hint, a natural-language moment description, and caller/user clues without
   requiring a quote, exact timestamp, or full transcript. A known title is the
   primary path. The caller can help identify an unknown title first; unrestricted
   discovery across the collection is not a prerequisite to this promise. The tool
   assumes neither access to the caller's conversation nor its filesystem.
2. **Source resolution is part of retrieval.** A film or show name may leave the
   episode, installment, edition, or local file unresolved. Outtake uses permitted
   evidence to resolve it or returns distinguishable choices or a focused question.
   Folder names and filenames are clues, not proof of identity or content. Unknown
   episode numbers do not require the person to locate the scene manually; any
   search remains within granted scope and limits.
3. **Results carry evidence the caller can use.** Candidates identify the source,
   occurrence, proposed boundaries, supporting source observations, and remaining
   uncertainty. Available review material is accessible through public capabilities
   so the caller can present it without an internal Agent transcript or dashboard.
   A hypothesis, an observed match, and a human-confirmed cut remain distinguishable.
   Locating the event does not imply that the person has approved its cut.
4. **Unresolved outcomes explain the next useful action.** Multiple plausible
   matches, missing context, insufficient permitted evidence, no match within the
   inspected scope, unavailable model capability, and exhausted resources remain
   distinguishable. A clarification identifies the affected request/candidate,
   explains what is missing, and accepts a correlated follow-up. No inaccessible
   interactive prompt is required. Failure to find within a bounded search is not
   proof that the moment is absent from the source or collection. These distinctions
   refine the outcomes in `agent-tool.v1.md`; they do not add frozen status names.
5. **Selection and refinement preserve their targets.** Choices, feedback, plans,
   previews, and artifacts identify the actual candidate or revision concerned.
   “The other scream,” “include the setup,” or “two seconds longer” uses supplied
   context and the identified base; unresolved references return a question rather
   than silently guessing. Changes preserve choices outside the requested change.
   Earlier plans remain available; stale feedback never silently targets a newer
   revision. Accepted dashboard choices are observable through the public boundary.
6. **Continuation uses public retained context.** The caller can continue from
   identified candidates and plans without replaying the entire conversation or
   operating an internal intelligence session. Replacing a presenter does not erase
   accepted choices. Public results expose enough retained intent and evidence to
   distinguish a new refinement from a repeated request; documented retry behavior
   prevents an acknowledged retry from silently duplicating work or spending.
7. **Authority remains outside the intelligence layer.** The caller supplies or
   explicitly selects source access, output destinations, model configuration,
   permitted disclosure, and bounded work. Existing valid authority can cover
   finding, choosing, refining, and making without repeated human approval; a
   clue or model suggestion cannot enlarge that authority. The tool reports the
   additional input or authority needed when it cannot proceed. Deterministic
   public operations require neither credentials nor internal Agent state.
8. **Presentation and execution are distinguishable.** Returning a preview does
   not establish that the person saw or approved it. Public results let the caller
   observe work outcomes, pending questions, accepted choices, and cancellation.
   Cancellation acknowledgement is distinct from finished cleanup. Retained plans
   and committed artifacts survive cancellation; caller-owned resources remain
   caller owned. No caller wake-up, browser launch, or background continuation is
   implied by the availability of a result.

## Shared refinement and export metadata

Callers can read and revise the same timed text cues, caption inclusion policy,
font choices, moment title and output settings that the dashboard presents.
Available text captions populate enabled editable cues by default unless explicitly
opted out; supported image captions retain their original appearance by default.
Track ambiguity and unavailable caption support remain visible. Callers can choose
original image captions, explicitly convert them locally to editable text, or turn
source captions off while retaining manual text. OCR text is labeled for review;
mode changes preserve edits and retained original image evidence. Conversion grants
no permission to disclose subtitle images or text to a provider.
Manual dialogue and caption-derived text share cue behavior while retaining their
provenance. Choosing a font, importing local captions, naming explicitly, revising
cues and deleting a specified export require no model or browser session.

The calling agent may propose a short title from the person's request. Public
results retain it alongside stable plan/export IDs and report actual output size.
An export deletion is an explicit action on an identified result, preserving its
source and reusable plan; it is never inferred from a refinement request.

Saved-output title changes are available to callers without rendering again.
They preserve export identity and media, and do not apply unrelated draft edits.

## Conformance kit asserts

Proposed assertions only: **Can't check** until implementation and independent
fixtures exist. Product correctness also requires the scene and artifact checks
in [the agent-tool contract](agent-tool.v1.md).

- A caller using only public documentation supplies a known title and scene
  description, receives reviewable evidence, selects, revises, and renders through
  both library and CLI paths without private imports or internal Agent sessions.
- Show-only, multiple-edition, and grouped-film fixtures produce the intended
  source or an actionable question; folder naming alone cannot certify a match.
- Misleading clues, missing context, ambiguous occurrences, exhausted budgets,
  and an incomplete unsuccessful search yield distinguishable, actionable results.
- A follow-up continues the identified candidate; “include the setup” preserves
  the occurrence and output choices, and ambiguous or stale feedback is not
  silently retargeted. A fresh caller can continue using public retained context.
- A dashboard choice is retrievable with its actual target revision. Retrying an
  acknowledged request follows documented semantics without duplicate work.
- Valid existing authority allows its intended continuation; missing authority
  produces an explicit limitation. Cancellation reports actual cleanup while
  preserving committed results and caller-owned resources.

## What v1 deliberately does NOT freeze

- Method/command names, input/result schemas, question representation, and transport.
- Retained-state format, identity encoding, retry keys/retention, polling or events,
  background execution, and lifecycle mechanics.
- Internal Agent prompts, tool names, provider APIs, or retrieval algorithms.

## Reserved / open questions (NOT frozen)

- What evidence and preview presentation lets a caller and person judge each
  scenario without mistaking a related frame for the complete requested event?
- What source/episode search scope is useful when a show is known but its episode
  is not, and how does the caller express and observe that bounded scope?
- What retention and retry guarantees are needed for practical return-and-refine
  use, and how do clarification results map to public outcome schemas?

## Changelog

- **2026-09-16** — Added shared timed text/default captions, fonts, moment titles,
  output size and deliberate export deletion to caller continuity.

- **2026-09-16** — First behavioral draft defining caller/tool ownership,
  known-title retrieval, reviewable evidence, and continuity without an API design.
