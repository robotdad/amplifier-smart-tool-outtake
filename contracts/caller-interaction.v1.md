# Calling Agent Interaction Contract — v1 (DRAFT)

**Who builds against this:** Calling agent applications, library/CLI and optional
MCP adapters, the dashboard, portable review views, and people using them.
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
   distinguish a new refinement from a repeated request. Within the documented
   deduplication scope and retention period, an exact retry returns its retained
   mutation outcome or operation-admission record, including when the original
   acknowledgement was lost. Admission alone is not an artifact receipt or proof
   of completion. Changed action, target, input or execution grant under the same
   request identity conflicts.
   Uncertain execution is inspected, not silently replayed as new work.
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

## Portable collaborative review (proposed amendment)

These proposed obligations cover Outtake's optional MCP adapter and MCP Apps view.
They do not adopt a new Smart Tool standard or lock method names and storage layout.

- **Preserve the existing interface.** Portable delivery adapts the established
  Outtake dashboard, not a separately designed review interface. Preserve its
  recognizable layout, controls, editing workflow and light/dark/system appearance.
  System appearance must resolve and react to the current environment rather than
  defaulting permanently to dark. A host limitation must be explained at the
  affected control; it does not authorize an unrelated interface redesign or
  broader data disclosure.
- **Saved Outputs remains usable.** The portable view preserves Saved Outputs
  browsing, sorting, refresh, download and reopening through public agent-callable
  operations. Listing excludes previews and is bounded. Opening an output resumes
  its isolated editing workspace and drafts without regenerating media, while
  preserving outgoing edits. Review-only authority exposes only authorized outputs;
  exposing the configured saved-output collection requires explicit caller authority.
  Listing, opening and media reads enforce the same disclosure boundary.
- **One retained workspace.** Agent calls and portable controls operate on the same
  finding, candidate, immutable plan, editing workspace and output identities. A
  saved output retains its own editing context; returning to it must not import
  unrelated drafts or overwrite its published media. Existing workspace behavior
  is shared rather than copied into adapter-owned domain state.
- **Observable, explicit review focus.** Bounded public snapshots identify the
  workspace, finding/candidate, displayed plan revision, preview/output and useful
  review position, including selected cue or playhead where supported. Agents can
  read and change supported semantic navigation through public methods. Changes
  use version preconditions and report conflicts instead of overwriting another
  participant. Inspecting a candidate is not selecting it; navigation is not
  editing a plan or granting execution. A newly produced revision must not silently
  replace the revision being reviewed.
- **Drafts are retained context, not commands.** Distinguish raw editor drafts,
  applied immutable plan revisions and published exports within the same workspace.
  Raw drafts retain unsubmitted text or edit values, their exact workspace and
  base revision, and a version precondition for conditional saves. They may be
  incomplete or invalid for a plan; retaining them does not advance the applied
  plan head. Applying valid edits creates an immutable plan revision through the
  existing workspace behavior; publishing produces an artifact and artifact
  receipt from an identified plan. An explicitly enabled valid-edit autosave may
  apply revisions, but must distinguish that result from raw-draft retention.
  None of these editing saves implicitly authorizes production or model work.
  Local and agent-driven navigation preserve raw drafts, including typing during
  an outstanding save and delayed autosave replies.
  Older saves cannot overwrite newer text. Rejected or stale edits remain
  recoverable with a visible conflict. Saving a draft never starts finding,
  rendering or model work; applying edits and requesting production are explicit.
- **Submissions have durable identities.** Persist the accepted operation and its
  immutable requested effect, targets and effective grant before admitting owned
  background work. Return an operation-admission record identifying the accepted
  request, operation and status lookup, not an artifact receipt. That operation
  resolves to a terminal domain outcome or an explicit interrupted/uncertain
  state. Successful artifact production links to its separately published
  artifact receipt, which binds the artifact to its plan and production evidence.
  Exact retries retain the admission identity and do not fabricate completion. The
  presenter retains uncertain request identities and inputs until reconciliation;
  new intent is a separate explicit submission, not a retry with a fresh identity.
  Concurrent retries cannot admit the same operation twice or restore consumed
  authority. A conflicting identity cannot replace another retained object.
- **Attachment is not execution.** Opening or reconnecting reads retained work
  without generation, grant renewal or replay. Closing a portable view detaches
  it; disconnecting the transport does not implicitly cancel owned work. Explicit
  cancellation reports acknowledgement and terminal cleanup separately.
  Restart recovery reports interrupted or uncertain operations and preserves
  committed artifacts; it never claims exactly-once external model execution
  across crashes or repeats uncertain charges automatically.
- **Cancellation and publication have an ordered boundary.** For artifact
  production, the library serializes effective cancellation against the durable
  publication of artifact and artifact receipt together. If cancellation takes
  effect first, the operation ends `cancelled` with no new published artifact;
  unfinished cleanup remains explicit. If publication commits first, report
  `ready` with that artifact receipt, even if a cancellation request was
  acknowledged. Acknowledgement alone does not establish which won. Recovery
  reconciles the committed publication; when it cannot establish the outcome,
  it reports uncertainty instead of claiming cancellation or starting production
  again. This does not roll back provider calls already made.
- **Shared work is explicit.** Host conversation identity is not required domain
  identity. Attaching requires an explicit opaque retained-work reference and
  caller-authorized host disclosure scope covering that work. Reads and edits
  enforce their applicable authority; possessing a reference alone grants neither.
  Existing valid authority may cover attachment without another approval prompt.
  A fresh conversation does not automatically inherit prior work or permissions.
  When another view or fork explicitly attaches to the same reference within
  authorized scope, disclose that it shares the original work; only a supported
  explicit clone/import creates independent identities. View context alone is
  not a restorable snapshot, a grant or verified human acceptance.
  Incompatible retained state or tool versions fail visibly
  rather than silently migrating, regenerating or overwriting work.
- **Authority and attention remain separate.** The trusted caller supplies source
  scope and bounded execution authority. Opening a view, submitting a draft, or
  receiving a tool result cannot enable provider access or enlarge scope. Provider
  credentials stay outside presenter data. Caller-reported attribution does not
  establish a verified human decision. Public progress does not expose private
  reasoning or imply that the host will notify a person or wake an agent. Report
  supported limits and known usage honestly; unknown usage/cost is not zero, and
  call/token limits are not advertised as hard billing limits.

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
- A dashboard or portable-view choice is retrievable with its actual target revision.
  Exact retries after both received and lost responses preserve the original
  operation and allowance; changed input, target or grant conflicts.
- Valid existing authority allows its intended continuation; missing authority
  produces an explicit limitation. Cancellation reports actual cleanup while
  preserving committed results and caller-owned resources.
- Interleave user and agent edits, delayed saves and navigation between two saved
  outputs. Drafts remain on their original bases, newer typing survives, stale
  updates conflict, and published media is unchanged until explicit production.
- Close/reopen a view and restart its transport during accepted work. Recovery
  reads the same operation and revisions, with no duplicate generation or grant
  renewal. Explicit cancellation reaches terminal cleanup or reports uncertainty;
  unrelated processes and previously committed outputs remain intact.
- Retain incomplete raw edits without changing the applied plan head; apply valid
  edits to a new immutable revision; publish that exact revision with an artifact
  receipt. Verify each state is distinguishable and earlier exports remain intact.
- Lose an admission response before production completes. The exact retry returns
  the same admission identity, not artifact success. Race cancellation on each
  side of publication: before yields no new artifact; after returns the committed
  artifact and receipt. Simulate lost completion records and verify reconciliation
  or explicit uncertainty without repeated work.
- Reject attachment/read/edit without the required retained-work reference and
  host scope. An authorized second view shares the same identities without
  cloning or expanding authority; a new or forked conversation inherits no
  permission solely through view context.
- Agent navigation and user controls expose equivalent targets and mutation
  outcomes or operation-admission records.
  Bounded view context identifies what is actually shown, never silently accepts
  a result, and does not become execution authority on reconnect or chat fork.

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

- **2026-09-19** — Owner approved the revised portable collaboration amendments
  as the implementation baseline, including all five review clarifications.
  The contract remains DRAFT, not locked; implementation and acceptance evidence
  are still required.

- **2026-09-19** — Clarified admission records versus artifact receipts, raw drafts
  versus applied plans and exports, authorized explicit attachment, and the
  cancellation/publication boundary after independent review. Still proposed;
  owner agreement and implementation verification remain outstanding.

- **2026-09-18** — Proposed portable collaboration amendment: shared workspace and
  semantic review state, exact-target drafts, lost-response retry safety, retained
  operation lifecycle, explicit shared attachment, and honest authority/usage.
  Awaiting owner review; this is not an implementation or conformance claim.

- **2026-09-16** — Added shared timed text/default captions, fonts, moment titles,
  output size and deliberate export deletion to caller continuity.

- **2026-09-16** — First behavioral draft defining caller/tool ownership,
  known-title retrieval, reviewable evidence, and continuity without an API design.
