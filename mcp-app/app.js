import { App } from "@modelcontextprotocol/ext-apps";

const app = new App({ name: "Outtake moment review", version: "0.1.0" });
const NATIVE_ALIASES = Object.freeze({
  notice: "status",
  "connection-state": "mcp-connection-state",
  "review-id": "mcp-review-id",
  "attachment-state": "status-text",
  "finding-panel": "moments",
  "candidate-list": "moments-list",
  "finding-summary": "request-title",
  "candidate-count": "moment-count",
  "plan-panel": "workspace",
  "plan-heading": "source-title",
  "plan-revision": "revision-label",
  "source-summary": "source-detail",
  "plan-warning": "uncertainty",
  title: "moment-title",
  "media-video": "video",
  "media-image": "image",
  "media-status": "status-text",
  "media-kind": "mcp-media-kind",
  "draft-status": "dirty-label",
  preview: "preview-button",
  render: "export-button",
});
const $ = (id) =>
  document.getElementById(id) ||
  document.getElementById(NATIVE_ALIASES[id] || "");
const MEDIA_CAP = 32 * 1024 * 1024;
const DEFAULT_CHUNK = 1024 * 1024;
const TERMINAL_OPERATIONS = new Set([
  "ready",
  "completed",
  "failed",
  "cancelled",
  "interrupted",
  "uncertain",
]);
const SHA256_K = [
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b,
  0x59f111f1, 0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01,
  0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7,
  0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc,
  0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152,
  0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147,
  0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc,
 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
 0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819,
 0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116, 0x1e376c08,
 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f,
 0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
];
const state = {
  connected: false,
  reviewId: null,
  snapshot: null,
  finding: null,
  plan: null,
  headPlan: null,
  view: null,
  viewVersion: 1,
  selectedCandidate: null,
  formPlanId: null,
  formBaseline: null,
  draftDirty: false,
  draftVersion: 0,
  draftVersions: new Map(),
  draftTimer: null,
  draftSave: null,
  draftConflict: null,
  mutations: new Map(),
  applyRevision: null,
  navigation: Promise.resolve(),
  refreshPromise: null,
  loadTicket: 0,
  pending: new Map(),
  mediaGeneration: 0,
  mediaKey: null,
  mediaUrl: null,
  mediaDescriptor: null,
  mediaBytes: null,
  mediaArtifactId: null,
  mediaPlanId: null,
  mediaFailedKey: null,
  pollToken: 0,
  intentResult: null,
  editorCues: [],
  editorOverlay: null,
  activeCueId: "",
  playbackReady: false,
  loopSelection: false,
  savedOutputs: [],
  savedTotal: 0,
  savedOpenRequests: new Map(),
};

function ensureNativeSurface() {
  const moments = document.querySelector(".moments");
  if (moments && !moments.id) moments.id = "moments";

  const hidden = (id, tag = "span") => {
    let node = document.getElementById(id);
    if (node) return node;
    node = document.createElement(tag);
    node.id = id;
    node.hidden = true;
    document.body.append(node);
    return node;
  };

  [
    ["mcp-connection-state", "span"],
    ["mcp-review-id", "span"],
    ["mcp-media-kind", "span"],
    ["view-version", "span"],
    ["context-state", "span"],
    ["playhead-value", "output"],
    ["playhead", "input"],
    ["operation-panel", "div"],
    ["evidence-actions", "div"],
    ["evidence-list", "div"],
    ["preview-state", "span"],
    ["render-state", "span"],
    ["preview-check", "button"],
    ["render-check", "button"],
    ["preview-cancel", "button"],
    ["render-cancel", "button"],
    ["draft-conflict", "p"],
  ].forEach(([id, tag]) => hidden(id, tag));
  const semanticPlayhead = document.getElementById("playhead");
  if (semanticPlayhead) {
    semanticPlayhead.type = "range";
    semanticPlayhead.min = "0";
    semanticPlayhead.step = "0.01";
  }

  let format = document.getElementById("format");
  if (!format) {
    format = document.createElement("select");
    format.id = "format";
    format.hidden = true;
    document.body.append(format);
  }
  for (const value of ["mp4", "gif", "png"]) {
    if (!format.querySelector(`[value="${value}"]`)) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = value;
      format.append(option);
    }
  }

  let captionText = document.getElementById("caption-text");
  if (!captionText) {
    captionText = document.createElement("textarea");
    captionText.id = "caption-text";
    captionText.hidden = true;
    document.body.append(captionText);
  }
}

function requestId(prefix = "request") {
  const value =
    typeof crypto.randomUUID === "function"
      ? crypto.randomUUID()
      : Array.from(crypto.getRandomValues(new Uint8Array(16)), (byte) =>
          byte.toString(16).padStart(2, "0"),
        ).join("");
  return `${prefix}_${value}`;
}

function clone(value) {
  return value == null ? value : structuredClone(value);
}

function freeze(value) {
  if (value && typeof value === "object") {
    Object.values(value).forEach(freeze);
    Object.freeze(value);
  }
  return value;
}

function errorWith(message, source = null) {
  const error = Error(message);
  if (source?.code) error.code = source.code;
  if (source?.toolResponse) error.toolResponse = true;
  if (source?.serverResponse) error.serverResponse = true;
  return error;
}

function decode(result) {
  let data = result?.structuredContent;
  if (data === undefined) {
    const text =
      result?.content?.find((part) => part.type === "text")?.text || "{}";
    try {
      data = JSON.parse(text);
    } catch {
      throw errorWith(text, {
        toolResponse: Boolean(result?.isError),
        serverResponse: Boolean(result?.isError),
      });
    }
  }
  const nestedError = data?.result?.error;
  if (result?.isError || data?.error || nestedError) {
    const detail = data?.error || nestedError;
    throw errorWith(
      detail?.message ||
        result?.content?.find((part) => part.type === "text")?.text ||
        "Outtake could not complete that request.",
      { code: detail?.code, toolResponse: true, serverResponse: true },
    );
  }
  // Some MCP servers wrap a direct result in {result}; operation records and
  // review snapshots also have a result field, so only unwrap an otherwise
  // empty envelope.
  if (
    data &&
    data.result !== undefined &&
    Object.keys(data).every((key) => key === "result")
  )
    return data.result;
  return data;
}

async function call(name, arguments_ = {}) {
  if (!state.connected) throw Error("The host has not connected yet.");
  return decode(
    await app.callServerTool({
      name: `outtake_${name}`,
      arguments: arguments_,
    }),
  );
}

function notice(message, error = false) {
  const banner = $("status");
  const text = $("status-text") || banner;
  text.textContent = message;
  banner.dataset.state = error ? "error" : "ready";
  banner.title = message;
  banner.setAttribute("aria-live", error ? "assertive" : "polite");
}

let hostStyleVariables = new Set();
const NATIVE_THEME_VARIABLES = new Set([
  "--bg",
  "--surface",
  "--raised",
  "--line",
  "--text",
  "--muted",
  "--accent",
  "--accent-text",
  "--teal",
  "--shadow",
]);
function style(context = {}) {
  const theme = context.theme || "system";
  document.documentElement.dataset.theme = theme;
  // The native stylesheet resolves the system appearance through its media
  // query. An inline `light dark` value would override that resolved scheme
  // and make the portable form controls differ from the dashboard.
  document.documentElement.style.removeProperty("color-scheme");
  for (const key of hostStyleVariables)
    document.documentElement.style.removeProperty(key);
  hostStyleVariables = new Set();
  for (const [key, value] of Object.entries(context.styles?.variables || {})) {
    if (
      key.startsWith("--") &&
      !NATIVE_THEME_VARIABLES.has(key) &&
      typeof value === "string"
    ) {
      document.documentElement.style.setProperty(key, value);
      hostStyleVariables.add(key);
    }
  }
}

function sourceSummary(plan) {
  const source = plan?.source;
  if (!source) return "No plan is currently selected.";
  return [
    `${source.width || "?"} × ${source.height || "?"}`,
    `${Number(source.duration || 0).toFixed(2)} seconds`,
    source.has_audio ? "audio available" : "no audio stream",
    "source identity checked by Outtake",
  ].join(" · ");
}

function targetIdentity(snapshot = state.snapshot) {
  const target = snapshot?.target;
  return target?.id || null;
}

function currentPlan() {
  return state.plan || null;
}

function setText(id, value) {
  const node = $(id);
  if (node) node.textContent = value == null ? "" : String(value);
}

function context() {
  if (!state.connected) return;
  const plan = currentPlan();
  const pending = [...state.pending.values()]
    .filter((record) => record.review_id === state.reviewId)
    .map((record) => ({
      operation: record.operation,
      request_id: record.request_id,
      status: record.status || record.phase || "unconfirmed",
    }));
  const view = state.view || {};
  app
    .updateModelContext({
      structuredContent: {
        review_id: state.reviewId,
        target_kind: state.snapshot?.target?.kind || null,
        target_id: targetIdentity(),
        displayed_plan_id: plan?.id || null,
        head_plan_id: state.snapshot?.head_plan_id || state.headPlan?.id || null,
        view: {
          plan_id: view.plan_id || null,
          finding_id: view.finding_id || null,
          candidate_id: view.candidate_id || null,
          cue_id: view.cue_id || null,
          playhead: view.playhead ?? null,
        },
        view_version: state.viewVersion,
        selected_candidate_id: state.selectedCandidate?.id || null,
        media_artifact_id: state.mediaArtifactId,
        media_loaded: Boolean(state.mediaUrl),
        media_bytes: state.mediaDescriptor?.bytes || null,
        draft_saved: !state.draftDirty,
        draft_is_authority: false,
        pending_operations: pending,
        observation_only: true,
      },
      content: [
        {
          type: "text",
          text:
            "Outtake portable review observations. Drafts and view context are not authority, human acceptance, or execution instructions.",
        },
      ],
    })
    .catch(() => {});
}

function renderDraftStatus(message = null) {
  const node = $("draft-status");
  if (!node) return;
  node.classList.toggle("conflict", Boolean(state.draftConflict));
  if (state.draftConflict) {
    node.textContent = state.draftConflict;
    return;
  }
  node.textContent =
    message ||
    (state.draftDirty
      ? "Unsaved raw draft · Apply changes is still required."
      : "Raw drafts do not change the applied plan or start work.");
}

function showConflict(message) {
  state.draftConflict = message;
  $("draft-conflict").hidden = false;
  $("draft-conflict").textContent = message;
  renderDraftStatus();
}

function clearConflict() {
  state.draftConflict = null;
  $("draft-conflict").hidden = true;
  $("draft-conflict").textContent = "";
  renderDraftStatus();
}

function nativeFormat() {
  return (
    document.querySelector("[data-format].active")?.dataset.format ||
    $("format")?.value ||
    "mp4"
  );
}

function setNativeFormat(value = "mp4") {
  const format = ["mp4", "gif", "png"].includes(value) ? value : "mp4";
  const mirror = $("format");
  if (mirror) mirror.value = format;
  document
    .querySelectorAll("[data-format]")
    .forEach((button) =>
      button.classList.toggle("active", button.dataset.format === format),
    );
  const audio = $("audio");
  if (audio) audio.disabled = format !== "mp4";
  const note = $("format-note");
  if (note)
    note.textContent = {
      mp4: "MP4 · compatible video with optional audio.",
      gif: "GIF · animated, silent, easy to share.",
      png: "Image · the selected source frame, with your text.",
    }[format];
  return format;
}

function nativeAudio() {
  const audio = $("audio");
  return audio?.type === "checkbox"
    ? audio.checked
      ? "preserve"
      : "mute"
    : audio?.value || "preserve";
}

function setNativeAudio(value = "preserve") {
  const audio = $("audio");
  if (!audio) return;
  if (audio.type === "checkbox") audio.checked = value === "preserve";
  else audio.value = value;
}

function overlayFields(text) {
  return {
    text,
    font: $("text-font")?.value || "pillow-default",
    size: Number($("text-size")?.value || 32),
    color: $("text-color")?.value || "#ffffff",
    outline_color: $("outline-color")?.value || "#000000",
    outline_width: Number($("outline-width")?.value || 2),
    x: Number($("text-x")?.value || 0.5),
    y: Number($("text-y")?.value || 0.85),
    alignment: $("alignment")?.value || "center",
  };
}

function syncActiveCue() {
  const cue = state.editorCues.find((item) => item.id === state.activeCueId);
  if (!cue) {
    const text = $("overlay-text")?.value || "";
    state.editorOverlay = text ? overlayFields(text) : null;
    return;
  }
  const base = Number($("start")?.value || 0);
  const start = Number($("cue-start")?.value);
  const end = Number($("cue-end")?.value);
  Object.assign(
    cue,
    overlayFields($("overlay-text")?.value || ""),
    {
      start: Number.isFinite(start) ? base + start : cue.start,
      end: Number.isFinite(end) ? base + end : cue.end,
      enabled: $("cue-enabled")?.checked !== false,
    },
  );
}

function editorCues() {
  syncActiveCue();
  return clone(state.editorCues || []);
}

function normaliseDraft(plan, draft) {
  const value =
    draft || {
      title: plan.title || "",
      start: String(plan.start ?? ""),
      end: String(plan.end ?? ""),
      frame: String(plan.frame ?? ""),
      format: plan.format || "mp4",
      profile: plan.profile || "share",
      audio: plan.audio || "preserve",
      captions_enabled: plan.captions_enabled !== false,
      caption_mode: plan.caption_mode || "editable",
      cues: clone(plan.cues || []),
      overlay: clone(plan.overlay || null),
      max_width: plan.max_width ?? null,
      fps: plan.fps ?? null,
    };
  const cues = clone(value.cues || plan.cues || []);
  // Drafts written by the first review view carried a caption preview. Keep
  // those drafts readable, but all new saves retain the complete cue objects.
  if (!cues.length && value.caption_text?.trim()) {
    cues.push({
      id: "cue_manual",
      text: value.caption_text,
      start: Number(value.start || plan.start),
      end: Number(value.end || plan.end),
      enabled: true,
      origin: "manual",
      evidence_id: null,
      extraction: "source_text",
      confidence: null,
      review_required: false,
      size: 32,
      color: "#ffffff",
      outline_color: "#000000",
      outline_width: 2,
      x: 0.5,
      y: 0.85,
      alignment: "center",
      font: "pillow-default",
    });
  }
  return {
    title: value.title ?? plan.title ?? "",
    start: String(value.start ?? plan.start ?? ""),
    end: String(value.end ?? plan.end ?? ""),
    frame: String(value.frame ?? plan.frame ?? ""),
    format: value.format || plan.format || "mp4",
    profile: value.profile || plan.profile || "share",
    audio: value.audio || plan.audio || "preserve",
    captions_enabled:
      value.captions_enabled !== undefined
        ? value.captions_enabled
        : plan.captions_enabled !== false,
    caption_mode: value.caption_mode || plan.caption_mode || "editable",
    cues,
    overlay:
      value.overlay !== undefined
        ? clone(value.overlay)
        : clone(plan.overlay || null),
    max_width: value.max_width ?? plan.max_width ?? null,
    fps: value.fps ?? plan.fps ?? null,
  };
}

function formDraft() {
  const plan = currentPlan();
  syncActiveCue();
  const value = {
    title: $("title").value,
    start: $("start").value,
    end: $("end").value,
    frame: $("frame").value,
    format: nativeFormat(),
    profile: $("profile").value,
    audio: nativeAudio(),
    captions_enabled: $("captions-enabled").checked,
    caption_mode: $("caption-mode").value,
    cues: editorCues(),
    overlay: clone(state.editorOverlay),
    max_width: $("max-width")?.value ? Number($("max-width").value) : null,
    fps: $("output-fps")?.value ? Number($("output-fps").value) : null,
  };
  $("caption-text").value = value.cues.map((cue) => cue.text || "").join("\n");
  return plan ? value : value;
}

function planDraft(plan) {
  return normaliseDraft(plan, {
    title: plan.title || "",
    start: String(plan.start ?? ""),
    end: String(plan.end ?? ""),
    frame: String(plan.frame ?? ""),
    format: plan.format || "mp4",
    profile: plan.profile || "share",
    audio: plan.audio || "preserve",
    captions_enabled: plan.captions_enabled !== false,
    caption_mode: plan.caption_mode || "editable",
    cues: clone(plan.cues || []),
    overlay: clone(plan.overlay || null),
    max_width: plan.max_width ?? null,
    fps: plan.fps ?? null,
  });
}

function setFormValue(plan, draft = null) {
  if (!plan) {
    state.formPlanId = null;
    state.formBaseline = null;
    state.editorCues = [];
    state.editorOverlay = null;
    state.activeCueId = "";
    return;
  }
  const value = normaliseDraft(plan, draft);
  $("title").value = value.title ?? "";
  $("start").value = value.start ?? "";
  $("end").value = value.end ?? "";
  $("frame").value = value.frame ?? "";
  setNativeFormat(value.format);
  $("profile").value = value.profile || "share";
  setNativeAudio(value.audio || "preserve");
  $("captions-enabled").checked = value.captions_enabled !== false;
  $("caption-mode").value = value.caption_mode || "editable";
  if ($("max-width")) $("max-width").value = value.max_width ?? "";
  if ($("output-fps")) $("output-fps").value = value.fps ?? "";
  state.editorCues = clone(value.cues || []);
  state.editorOverlay = clone(value.overlay || null);
  state.activeCueId = "";
  $("end").max = String(plan.source?.duration || "");
  $("frame").max = String(plan.source?.duration || "");
  renderNativeCues();
  chooseNativeCue("");
  state.formPlanId = plan.id;
  // Compare edits with the applied plan, not with a retained raw draft. A
  // draft may intentionally differ from the applied head and Apply must make
  // that distinction visible.
  state.formBaseline = planDraft(plan);
}

function draftKey(reviewId = state.reviewId, planId = state.plan?.id) {
  return reviewId && planId ? `${reviewId}:${planId}` : null;
}

function captureDraft() {
  const plan = currentPlan();
  const key = draftKey();
  if (!state.reviewId || !plan || !key) return null;
  const value = clone(formDraft());
  const arguments_ = {
    review_id: state.reviewId,
    base_plan_id: plan.id,
    draft: value,
    expected_version: state.draftVersions.get(key) ?? state.draftVersion ?? 0,
  };
  const mutation = exactMutation("save", key, arguments_);
  return {
    key,
    ...arguments_,
    value,
    mutation_key: mutation.key,
    request_id: mutation.request_id,
  };
}

function sameDraft(a, b) {
  return JSON.stringify(a) === JSON.stringify(b);
}

function persistPending() {
  if (!state.reviewId) return;
  try {
    sessionStorage.setItem(
      `outtake:mcp:pending:${state.reviewId}`,
      JSON.stringify({
        operations: [...state.pending.values()],
        mutations: [...state.mutations.values()],
      }),
    );
  } catch {
    // A sandboxed App may not expose storage. The retained server operation is
    // still authoritative; this is only a presenter-side retry aid.
  }
}

function restorePending() {
  state.pending.clear();
  state.mutations.clear();
  if (!state.reviewId) return;
  try {
    const stored = JSON.parse(
      sessionStorage.getItem(`outtake:mcp:pending:${state.reviewId}`) || "[]",
    );
    const records = Array.isArray(stored) ? stored : stored.operations || [];
    for (const record of records) {
      if (
        record?.review_id === state.reviewId &&
        record.request_id &&
        record.arguments
      )
        state.pending.set(`${record.operation}:${record.base_plan_id}`, record);
    }
    const mutations = Array.isArray(stored) ? [] : stored.mutations || [];
    for (const mutation of mutations) {
      if (
        mutation?.key &&
        mutation.request_id &&
        mutation.arguments &&
        mutation.review_id === state.reviewId
      )
        state.mutations.set(mutation.key, mutation);
    }
  } catch {
    // See persistPending: lack of presenter storage must not become authority.
  }
}

function mutationKey(action, identity) {
  return `${action}:${identity}`;
}

function exactMutation(action, identity, arguments_) {
  const key = mutationKey(action, identity);
  const previous = state.mutations.get(key);
  if (previous && sameDraft(previous.arguments, arguments_)) return previous;
  const mutation = {
    key,
    review_id: state.reviewId,
    action,
    request_id: requestId(action),
    arguments: freeze(clone(arguments_)),
    phase: "submitting",
  };
  state.mutations.set(key, mutation);
  persistPending();
  return mutation;
}

function markMutationError(mutation, error) {
  mutation.phase = error.serverResponse ? "rejected" : "unconfirmed";
  mutation.error = error.message;
  persistPending();
}

function renderFinding() {
  const finding = state.finding;
  const list = $("candidate-list");
  list.replaceChildren();
  const request = finding?.request || {};
  const candidates = finding?.candidates || [];
  setText(
    "finding-summary",
    finding
      ? request.description ||
          request.title ||
          "Review the retained source evidence before choosing a candidate."
      : currentPlan()
        ? "The displayed plan is ready to refine."
        : "Start with a memory, or open a plan from your agent.",
  );
  setText("candidate-count", candidates.length || (currentPlan() ? 1 : 0));
  if (!candidates.length) {
    if (currentPlan()) {
      const item = document.createElement("div");
      item.className = "moment active";
      const title = document.createElement("strong");
      title.textContent = currentPlan().title || "Displayed moment";
      const timing = document.createElement("span");
      timing.className = "timing";
      timing.textContent = `${Number(currentPlan().start).toFixed(2)} — ${Number(
        currentPlan().end,
      ).toFixed(2)}s`;
      item.append(title, timing);
      list.append(item);
    } else if (finding) {
      const empty = document.createElement("p");
      empty.className = "small muted";
      empty.textContent = "No candidate is retained for this finding.";
      list.append(empty);
    }
    return;
  }
  for (const candidate of candidates) {
    const card = document.createElement("article");
    card.className = "moment";
    if (candidate.id === state.selectedCandidate?.id) card.classList.add("selected");
    card.dataset.candidateId = candidate.id;
    const heading = document.createElement("h3");
    heading.textContent =
      candidate.title || `Candidate · ${Number(candidate.start).toFixed(2)}–${Number(candidate.end).toFixed(2)}s`;
    const explanation = document.createElement("p");
    explanation.textContent = candidate.explanation || "No explanation retained.";
    const uncertainty = document.createElement("p");
    uncertainty.className = "small muted";
    uncertainty.textContent =
      "Uncertainty: " + (candidate.uncertainty || "Not recorded.");
    const row = document.createElement("div");
    row.className = "trim-actions";
    const inspect = document.createElement("button");
    inspect.textContent = "Inspect evidence";
    inspect.type = "button";
    inspect.dataset.evidenceId = (candidate.evidence_ids || [])[0] || "";
    inspect.disabled = !inspect.dataset.evidenceId;
    const select = document.createElement("button");
    select.className = "primary";
    select.type = "button";
    select.textContent = "Select candidate";
    select.dataset.candidateId = candidate.id;
    const focus = document.createElement("button");
    focus.type = "button";
    focus.textContent = "Focus candidate";
    focus.dataset.focusCandidateId = candidate.id;
    row.append(focus, inspect, select);
    card.append(heading, explanation, uncertainty, row);
    list.append(card);
  }
}

function renderEvidence(plan = currentPlan()) {
  const ids = new Set();
  for (const id of plan?.evidence_ids || []) ids.add(id);
  for (const id of state.selectedCandidate?.evidence_ids || []) ids.add(id);
  const strip = document.getElementById("filmstrip");
  if (!strip) return;
  strip.replaceChildren();
  let ordinal = 0;
  for (const evidenceId of ids) {
    const button = document.createElement("button");
    button.className = "frame";
    button.type = "button";
    button.dataset.evidenceId = evidenceId;
    button.dataset.evidenceIndex = "0";
    button.title = "Load retained source evidence frame";
    const label = document.createElement("span");
    label.textContent = `Evidence ${++ordinal}`;
    button.append(label);
    strip.append(button);
  }
  if (!ids.size) {
    const empty = document.createElement("span");
    empty.className = "small muted";
    empty.textContent = "No retained frame evidence is linked to this review.";
    strip.append(empty);
  }
}

function retainedDraft(planId) {
  if (
    state.snapshot?.draft?.base_plan_id === planId &&
    state.snapshot.draft.value
  )
    return state.snapshot.draft;
  return (
    (state.snapshot?.drafts || []).find(
      (draft) => draft.base_plan_id === planId,
    ) || null
  );
}

function mergeSnapshotOperations(snapshot, plan) {
  for (const operation of snapshot?.operations || []) {
    if (!operation?.request_id || !operation.operation || !plan?.id) continue;
    const existing =
      [...state.pending.values()].find(
        (record) => record.request_id === operation.request_id,
      ) || state.pending.get(pendingKey(operation.operation, plan.id));
    const record = existing || {
      review_id: state.reviewId,
      base_plan_id: plan.id,
      operation: operation.operation,
      request_id: operation.request_id,
      arguments: { plan_id: plan.id },
      restored_from_server: true,
    };
    Object.assign(record, {
      operation_id: operation.operation_id || record.operation_id,
      output_id: operation.output_id || record.output_id,
      status: operation.status || record.status || "accepted",
      phase: operation.status || record.phase || "accepted",
      result: operation.result || record.result,
      cancel_requested: operation.cancel_requested,
    });
    state.pending.set(pendingKey(operation.operation, plan.id), record);
  }
  persistPending();
}

function renderPlan() {
  const plan = currentPlan();
  const editor = $("edit-controls");
  const trim = $("trim-controls");
  const preview = $("preview-button");
  const exportButton = $("export-button");
  if (!plan) {
    setText("plan-heading", "Select a retained candidate");
    setText("plan-revision", "");
    setText("source-summary", "");
    if (editor) editor.disabled = true;
    if (trim) trim.disabled = true;
    if (preview) preview.disabled = true;
    if (exportButton) exportButton.disabled = true;
    renderEvidence(null);
    return;
  }
  if (editor) editor.disabled = false;
  if (trim) trim.disabled = false;
  setText("plan-heading", plan.title || "Untitled moment");
  setText("plan-revision", `Revision ${plan.revision || 1}`);
  setText("source-summary", sourceSummary(plan));
  const warning = (plan.warnings || []).join(" ");
  setText(
    "plan-warning",
    warning || "Sound is yours to review. Play the clip and adjust its beginning or end.",
  );
  if (state.formPlanId !== plan.id) {
    const retained = retainedDraft(plan.id);
    const draft =
      retained?.base_plan_id === plan.id ? retained.value : null;
    state.draftVersion =
      retained?.base_plan_id === plan.id ? retained.version || 0 : 0;
    state.draftVersions.set(draftKey(), state.draftVersion);
    setFormValue(plan, draft);
    state.draftDirty = false;
  }
  renderDraftStatus();
  renderEvidence(plan);
  renderOperations();
  updateNativeTrim();
}

function renderSnapshot(snapshot) {
  const previousPlanId = state.plan?.id || null;
  const nextPlan = snapshot?.displayed_plan || snapshot?.plan || null;
  const nextHead = snapshot?.workspace?.plan || null;
  const planChanged = previousPlanId !== (nextPlan?.id || null);
  state.snapshot = snapshot;
  state.finding = snapshot?.finding || null;
  state.plan = nextPlan;
  state.headPlan = nextHead;
  state.view = clone(
    snapshot?.view || (nextPlan ? { plan_id: nextPlan.id } : {}),
  );
  state.viewVersion = Number(snapshot?.view_version || 1);
  if (state.finding && state.view?.candidate_id) {
    state.selectedCandidate =
      state.finding.candidates?.find(
        (candidate) => candidate.id === state.view.candidate_id,
      ) || state.selectedCandidate;
  }
  mergeSnapshotOperations(snapshot, nextPlan);
  if (planChanged && state.mediaUrl) clearMedia();
  if (planChanged && state.mediaPlanId && state.mediaPlanId !== nextPlan?.id)
    clearMedia();
  const retained = nextPlan ? retainedDraft(nextPlan.id) : null;
  if (retained && nextPlan && retained.base_plan_id === nextPlan.id) {
    const key = draftKey(state.reviewId, nextPlan.id);
    const incomingVersion = retained.version || 0;
    const shouldRestore =
      !state.draftDirty &&
      (state.formPlanId !== nextPlan.id || incomingVersion !== state.draftVersion);
    state.draftVersions.set(key, retained.version || 0);
    if (!state.draftDirty || state.formPlanId !== nextPlan.id) {
      state.draftVersion = incomingVersion;
      if (shouldRestore) {
        setFormValue(nextPlan, retained.value);
        state.draftDirty = false;
      }
    } else if ((retained.version || 0) > state.draftVersion) {
      showConflict(
        "A newer draft is retained by another participant. Your typing stays here; compare before overwriting it.",
      );
    }
  }
  renderFinding();
  renderPlan();
  setText(
    "context-state",
    `Displayed ${nextPlan?.id || targetIdentity() || "no retained plan"} · draft ${
      state.draftDirty ? "not yet saved" : "saved or unchanged"
    }.`,
  );
  context();
  return {
    planChanged,
    artifactId:
      snapshot?.target?.kind === "artifact"
        ? snapshot.target.id
        : snapshot?.artifact_id || null,
  };
}

function releaseMediaUrl() {
  if (state.mediaUrl) URL.revokeObjectURL(state.mediaUrl);
  state.mediaUrl = null;
}

function clearMedia(message = "No retained media loaded.") {
  state.mediaGeneration += 1;
  state.mediaKey = null;
  state.mediaDescriptor = null;
  state.mediaBytes = null;
  state.mediaArtifactId = null;
  state.mediaPlanId = null;
  state.mediaFailedKey = null;
  state.playbackReady = false;
  releaseMediaUrl();
  $("media-video").pause();
  $("media-video").removeAttribute("src");
  $("media-image").removeAttribute("src");
  $("media-video").hidden = true;
  $("media-image").hidden = true;
  setText("media-status", message);
  setText("media-kind", "");
  context();
}

function descriptorField(descriptor, ...keys) {
  for (const key of keys) {
    if (descriptor?.[key] !== undefined && descriptor[key] !== null)
      return descriptor[key];
  }
  return undefined;
}

function resourceUri(descriptor, kind, identity, index, offset) {
  let uri =
    descriptor.resource_uri ||
    descriptor.resource_template ||
    descriptor.uri_template ||
    descriptor.uri ||
    "";
  const values = {
    review_id: state.reviewId,
    kind,
    identity,
    media_id: descriptor.media_id,
    index: index ?? 0,
    offset,
  };
  for (const [key, value] of Object.entries(values))
    uri = uri.replaceAll(`{${key}}`, encodeURIComponent(String(value)));
  if (uri.includes("{")) uri = "";
  if (uri) {
    if (uri.endsWith("/0") && offset !== 0)
      return uri.replace(/\/0$/, `/${offset}`);
    if (uri.endsWith(`/${offset}`)) return uri;
    return `${uri.replace(/\/$/, "")}/${offset}`;
  }
  // The adapter's resource template is intentionally opaque and scoped by the
  // review and media identities. This fallback is also useful during interface
  // migration when the descriptor has not gained resource_uri yet.
  return `outtake://media/${encodeURIComponent(state.reviewId)}/${encodeURIComponent(
    descriptor.media_id,
  )}/${offset}`;
}

function decodeBase64(value) {
  if (typeof value !== "string") throw Error("The host returned no binary media chunk.");
  const raw = atob(value);
  return Uint8Array.from(raw, (character) => character.charCodeAt(0));
}

function rotr(value, amount) {
  return (value >>> amount) | (value << (32 - amount));
}

// Sandboxed srcdoc Apps can have an opaque origin where SubtleCrypto is not
// exposed. Keep integrity verification local and deterministic rather than
// weakening the declared hash requirement or asking the host to hash bytes.
function sha256Fallback(bytes) {
  const bitLength = bytes.length * 8;
  const total = ((bytes.length + 9 + 63) >> 6) << 6;
  const padded = new Uint8Array(total);
  padded.set(bytes);
  padded[bytes.length] = 0x80;
  const view = new DataView(padded.buffer);
  view.setUint32(total - 8, Math.floor(bitLength / 0x100000000));
  view.setUint32(total - 4, bitLength >>> 0);
  let h0 = 0x6a09e667;
  let h1 = 0xbb67ae85;
  let h2 = 0x3c6ef372;
  let h3 = 0xa54ff53a;
  let h4 = 0x510e527f;
  let h5 = 0x9b05688c;
  let h6 = 0x1f83d9ab;
  let h7 = 0x5be0cd19;
  const words = new Uint32Array(64);
  for (let offset = 0; offset < total; offset += 64) {
    for (let index = 0; index < 16; index++)
      words[index] = view.getUint32(offset + index * 4);
    for (let index = 16; index < 64; index++) {
      const value15 = words[index - 15];
      const value2 = words[index - 2];
      const sigma0 =
        rotr(value15, 7) ^ rotr(value15, 18) ^ (value15 >>> 3);
      const sigma1 = rotr(value2, 17) ^ rotr(value2, 19) ^ (value2 >>> 10);
      words[index] = (words[index - 16] + sigma0 + words[index - 7] + sigma1) >>> 0;
    }
    let a = h0;
    let b = h1;
    let c = h2;
    let d = h3;
    let e = h4;
    let f = h5;
    let g = h6;
    let hh = h7;
    for (let index = 0; index < 64; index++) {
      const sigma1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25);
      const choose = (e & f) ^ (~e & g);
      const temp1 = (hh + sigma1 + choose + SHA256_K[index] + words[index]) >>> 0;
      const sigma0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22);
      const majority = (a & b) ^ (a & c) ^ (b & c);
      const temp2 = (sigma0 + majority) >>> 0;
      hh = g;
      g = f;
      f = e;
      e = (d + temp1) >>> 0;
      d = c;
      c = b;
      b = a;
      a = (temp1 + temp2) >>> 0;
    }
    h0 = (h0 + a) >>> 0;
    h1 = (h1 + b) >>> 0;
    h2 = (h2 + c) >>> 0;
    h3 = (h3 + d) >>> 0;
    h4 = (h4 + e) >>> 0;
    h5 = (h5 + f) >>> 0;
    h6 = (h6 + g) >>> 0;
    h7 = (h7 + hh) >>> 0;
  }
  return [h0, h1, h2, h3, h4, h5, h6, h7]
    .map((value) => value.toString(16).padStart(8, "0"))
    .join("");
}

async function digest(bytes) {
  if (globalThis.crypto?.subtle) {
    const hash = await globalThis.crypto.subtle.digest("SHA-256", bytes);
    return [...new Uint8Array(hash)]
      .map((value) => value.toString(16).padStart(2, "0"))
      .join("");
  }
  return sha256Fallback(bytes);
}

async function readScopedDescriptor(descriptor, kind, identity, index = null) {
  const total = Number(descriptorField(descriptor, "bytes", "total_bytes"));
  const declaredHash = descriptorField(descriptor, "sha256", "hash");
  const mime =
    descriptorField(descriptor, "mime", "mime_type") || "application/octet-stream";
  const advertisedChunk = Number(
    descriptorField(descriptor, "chunk_bytes", "max_chunk_bytes") || DEFAULT_CHUNK,
  );
  if (
    !Number.isSafeInteger(total) ||
    total <= 0 ||
    total > MEDIA_CAP ||
    !/^[a-f0-9]{64}$/i.test(String(declaredHash)) ||
    !Number.isSafeInteger(advertisedChunk) ||
    advertisedChunk < 1
  )
    throw Error("The retained media descriptor is invalid or exceeds the 32 MiB view limit.");
  if (!app.getHostCapabilities()?.serverResources)
    throw Error(
      "This host does not support MCP resource reads. Use the headless library or CLI to obtain the retained bytes.",
    );
  const chunkSize = Math.min(advertisedChunk, DEFAULT_CHUNK);
  const combined = new Uint8Array(total);
  let position = 0;
  for (let offset = 0; offset < total; offset += chunkSize) {
    const response = await app.readServerResource({
      uri: resourceUri(descriptor, kind, identity, index, offset),
    });
    const content = response?.contents?.find((part) => typeof part.blob === "string");
    const bytes = decodeBase64(content?.blob);
    const expected = Math.min(chunkSize, total - offset);
    if (bytes.length !== expected)
      throw Error("The retained resource returned an incomplete or oversized chunk.");
    combined.set(bytes, position);
    position += bytes.length;
  }
  if (position !== total || (await digest(combined)).toLowerCase() !== String(declaredHash).toLowerCase())
    throw Error("The retained resource failed its SHA-256 integrity check.");
  return { bytes: combined, mime, total };
}

function mediaName(descriptor, plan, kind) {
  const advertised = descriptor.name || descriptor.filename;
  if (
    typeof advertised === "string" &&
    advertised &&
    !advertised.includes("/") &&
    !advertised.includes("\\")
  )
    return advertised;
  const title = (plan?.title || kind || "outtake-moment")
    .replace(/[^a-z0-9]+/gi, "-")
    .replace(/^-|-$/g, "")
    .toLowerCase();
  const mime = String(descriptor.mime || descriptor.mime_type || "");
  const extension =
    mime === "video/mp4"
      ? "mp4"
      : mime === "image/gif"
        ? "gif"
        : mime === "image/png"
          ? "png"
          : "bin";
  return `${title || "outtake-moment"}.${extension}`;
}

async function loadMedia({ kind, identity, index = null }) {
  if (!identity) {
    clearMedia("No retained preview is available for this target.");
    return;
  }
  const key = [state.reviewId, kind, identity, index ?? ""].join(":");
  if (state.mediaKey === key && state.mediaUrl) return;
  clearMedia("Loading scoped retained media…");
  const token = state.mediaGeneration;
  state.mediaKey = key;
  setText("media-kind", kind === "frame" ? "source evidence frame" : "retained output");
  try {
    const descriptor = await call("describe_media", {
      review_id: state.reviewId,
      kind,
      identity,
      ...(index === null ? {} : { index }),
    });
    if (token !== state.mediaGeneration) return;
    const { bytes: combined, mime, total } = await readScopedDescriptor(
      descriptor,
      kind,
      identity,
      index,
    );
    if (token !== state.mediaGeneration) return;

    releaseMediaUrl();
    state.mediaDescriptor = descriptor;
    state.mediaBytes = combined;
    state.mediaUrl = URL.createObjectURL(new Blob([combined], { type: mime }));
    state.mediaArtifactId = kind === "artifact" ? identity : null;
    state.mediaPlanId = currentPlan()?.id || null;
    state.mediaFailedKey = null;
    const video = $("media-video");
    const image = $("media-image");
    video.pause();
    video.removeAttribute("src");
    image.removeAttribute("src");
    if (mime.startsWith("video/")) {
      video.src = state.mediaUrl;
      video.controls = false;
      video.hidden = false;
      image.hidden = true;
    } else {
      image.src = state.mediaUrl;
      image.hidden = false;
      video.hidden = true;
    }
    setText(
      "media-status",
      `${mime.split("/").at(-1).toUpperCase()} · ${(total / 1024).toFixed(
        0,
      )} KiB · hash verified`,
    );
    if ($("empty-preview")) $("empty-preview").hidden = true;
    if ($("preview-label")) {
      $("preview-label").hidden = false;
      $("preview-label").textContent =
        kind === "frame" ? "Source evidence" : "Retained output";
    }
    state.playbackReady = mime.startsWith("video/");
    context();
  } catch (error) {
    if (token !== state.mediaGeneration) return;
    clearMedia("Retained media is unavailable; stale playback and download were cleared.");
    state.mediaFailedKey = key;
    notice(error.message, true);
  }
}

function savedLabel(receipt) {
  return receipt.plan?.title || `Saved ${String(receipt.artifact_id || "").slice(-6)}`;
}

function savedTime(seconds) {
  const value = Math.max(0, Number(seconds) || 0);
  return `${Math.floor(value / 60)}:${(value % 60).toFixed(2).padStart(5, "0")}`;
}

function actionIcon(element, name, path) {
  element.classList.add("icon-action");
  element.title = name;
  element.setAttribute("aria-label", name);
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  const shape = document.createElementNS(svg.namespaceURI, "path");
  shape.setAttribute("d", path);
  svg.append(shape);
  element.append(svg);
}

function showNativeView(name) {
  $("workspace").hidden = name !== "workspace";
  $("saved").hidden = name !== "saved";
  $("workspace-tab").classList.toggle("active", name === "workspace");
  $("saved-tab").classList.toggle("active", name === "saved");
  if (name === "saved") $("media-video").pause();
}

async function hydrateSavedCard(media, receipt) {
  try {
    const descriptor = await call("describe_saved_output_media", {
      artifact_id: receipt.artifact_id,
    });
    const { bytes, mime } = await readScopedDescriptor(
      descriptor,
      "artifact",
      receipt.artifact_id,
    );
    const url = URL.createObjectURL(new Blob([bytes], { type: mime }));
    media.src = url;
    media.dataset.resourceUrl = url;
    media.dataset.resourceMime = mime;
  } catch (error) {
    media.replaceWith(Object.assign(document.createElement("p"), {
      className: "hint",
      textContent: "Saved media is unavailable.",
    }));
  }
}

async function openSavedOutput(receipt) {
  await flushDraftForNavigation();
  const requestId =
    state.savedOpenRequests.get(receipt.artifact_id) ||
    requestIdForSavedOutput(receipt.artifact_id);
  state.savedOpenRequests.set(receipt.artifact_id, requestId);
  const opened = await call("open_saved_output", {
    artifact_id: receipt.artifact_id,
    request_id: requestId,
  });
  await loadReview(opened.review_id);
  showNativeView("workspace");
  await loadMedia({ kind: "artifact", identity: receipt.artifact_id });
  notice("Opened saved output. Its retained draft and exact export workspace are preserved.");
}

function requestIdForSavedOutput(artifactId) {
  return `open_saved_${String(artifactId).slice(-12)}_${requestId("retry")}`;
}

async function refreshSavedOutputs() {
  const page = await call("saved_outputs", {
    sort_by: $("saved-sort").value,
    offset: 0,
    limit: 20,
  });
  state.savedOutputs = page.outputs || [];
  state.savedTotal = Number(page.total || 0);
  $("saved-count").textContent = String(state.savedTotal);
  const grid = $("saved-grid");
  grid.replaceChildren();
  if (!state.savedOutputs.length) {
    const empty = document.createElement("p");
    empty.className = "muted";
    empty.textContent = "Your authorized exports will appear here. Previews stay in the workspace.";
    grid.append(empty);
    return;
  }
  for (const receipt of state.savedOutputs) {
    const card = document.createElement("article");
    card.className = "output-card";
    card.dataset.artifactId = receipt.artifact_id;
    const media = document.createElement(receipt.plan?.format === "mp4" ? "video" : "img");
    if (media.tagName === "VIDEO") {
      media.controls = true;
      media.preload = "metadata";
      media.muted = true;
    } else media.alt = savedLabel(receipt);
    const body = document.createElement("div");
    body.className = "body";
    const title = document.createElement("h2");
    title.textContent = savedLabel(receipt);
    const detail = document.createElement("p");
    detail.textContent = `${String(receipt.plan?.format || "").toUpperCase()} · ${savedTime(receipt.plan?.start)}–${savedTime(receipt.plan?.end)} · ${(Number(receipt.bytes || 0) / 1024 / 1024).toFixed(1)} MB`;
    const edits = document.createElement("p");
    edits.textContent = receipt.plan?.cues?.length
      ? `${receipt.plan.cues.length} timed text cues`
      : receipt.plan?.overlay?.text
        ? `“${receipt.plan.overlay.text}”`
        : "Original moment · no text overlay";
    const actions = document.createElement("div");
    actions.className = "card-actions";
    const open = document.createElement("button");
    open.type = "button";
    open.textContent = "Open";
    open.addEventListener("click", () => run(() => openSavedOutput(receipt)));
    const download = document.createElement("a");
    actionIcon(download, "Download", "M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5");
    download.download = `${savedLabel(receipt)}.${receipt.plan?.format || "bin"}`;
    const remove = document.createElement("button");
    remove.type = "button";
    actionIcon(
      remove,
      "Delete",
      "M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7m4-7v7",
    );
    remove.addEventListener("click", () =>
      run(async () => {
        if (!confirm(`Delete “${savedLabel(receipt)}”? This removes its generated file and receipt. The source and plan remain.`))
          return;
        const opened = await call("open_saved_output", {
          artifact_id: receipt.artifact_id,
          request_id:
            state.savedOpenRequests.get(receipt.artifact_id) ||
            requestIdForSavedOutput(receipt.artifact_id),
        });
        await call("delete_saved_output", {
          review_id: opened.review_id,
          artifact_id: receipt.artifact_id,
          expected_plan_id: receipt.plan.id,
          request_id: requestId("delete"),
        });
        await refreshSavedOutputs();
        notice("Export deleted. Source and plan preserved.");
      }),
    );
    actions.append(open, download, remove);
    body.append(title, detail, edits, actions);
    card.append(media, body);
    grid.append(card);
    hydrateSavedCard(media, receipt).then(() => {
      const url = media.dataset.resourceUrl;
      if (url) {
        download.href = url;
        download.download = mediaName(
          { mime: media.dataset.resourceMime },
          receipt.plan,
          "artifact",
        );
      }
    });
  }
}

async function saveDraftValue(target) {
  if (!target) return;
  const prior = state.draftSave;
  if (prior && prior.key === target.key) {
    await prior.promise;
    return saveDraftValue(target);
  }
  const promise = (async () => {
    const result = await call("save_draft", {
      review_id: target.review_id,
      base_plan_id: target.base_plan_id,
      draft: target.value,
      expected_version: target.expected_version,
      request_id: target.request_id,
    });
    const version = Number(result.version ?? target.expected_version + 1);
    state.draftVersions.set(target.key, version);
    if (target.review_id === state.reviewId && target.key === draftKey()) {
      state.draftVersion = version;
      if (sameDraft(target.value, formDraft())) {
        state.draftDirty = false;
        clearConflict();
        renderDraftStatus("Draft saved · not applied.");
      } else {
        state.draftDirty = true;
        renderDraftStatus("Earlier draft saved; newer typing remains unsaved.");
      }
    }
    context();
    return result;
  })().catch((error) => {
    const mutation = state.mutations.get(target.mutation_key);
    if (mutation) markMutationError(mutation, error);
    if (error.code === "DRAFT_CONFLICT" || /newer raw draft/i.test(error.message))
      showConflict(
        "Draft conflict: a newer raw draft is retained. Your typing is preserved; refresh and merge explicitly.",
      );
    throw error;
  });
  state.draftSave = { key: target.key, promise };
  try {
    return await promise;
  } finally {
    if (state.draftSave?.promise === promise) state.draftSave = null;
  }
}

async function saveCurrentDraft(force = false) {
  clearTimeout(state.draftTimer);
  if (state.draftSave) {
    await state.draftSave.promise;
    if (!force || !state.draftDirty) return;
  }
  const target = captureDraft();
  if (!target || (!force && !state.draftDirty)) return;
  return saveDraftValue(target);
}

async function flushDraftForNavigation() {
  clearTimeout(state.draftTimer);
  if (state.draftSave) {
    try {
      await state.draftSave.promise;
    } catch (error) {
      const retry = captureDraft();
      const mutation = retry && state.mutations.get(retry.mutation_key);
      if (!retry || mutation?.phase !== "unconfirmed") throw error;
      await saveDraftValue(retry);
    }
  }
  // Capture again after an outstanding response. If the person kept typing
  // while the first save was delayed, persist that newer exact old-target value
  // before changing the displayed review.
  for (let attempt = 0; attempt < 4; attempt += 1) {
    const target = captureDraft();
    if (!target || !state.draftDirty) return;
    try {
      await saveDraftValue(target);
    } catch (error) {
      const retry = captureDraft();
      const mutation = retry && state.mutations.get(retry.mutation_key);
      if (!retry || mutation?.phase !== "unconfirmed") throw error;
      await saveDraftValue(retry);
    }
    if (!state.draftDirty || target.key !== draftKey()) return;
  }
  if (state.draftDirty)
    throw Error("The old review still has newer typing; navigation was not applied.");
}

function validateForm(plan) {
  const start = Number($("start").value);
  const end = Number($("end").value);
  const frame = Number($("frame").value);
  const duration = Number(plan.source?.duration || 0);
  if (
    !Number.isFinite(start) ||
    !Number.isFinite(end) ||
    !Number.isFinite(frame) ||
    start < 0 ||
    start >= end ||
    end > duration ||
    frame < start ||
    frame >= end
  )
    throw Error("Choose start, end and still-frame times within the displayed source.");
  if (nativeFormat() !== "mp4" && nativeAudio() !== "mute")
    throw Error("GIF and PNG outputs must use the mute audio policy.");
  return { start, end, frame };
}

function changesFromForm(plan) {
  const times = validateForm(plan);
  syncActiveCue();
  const changes = {
    ...times,
    title: $("title").value.trim(),
    format: nativeFormat(),
    profile: $("profile").value,
    audio: nativeAudio(),
    captions_enabled: $("captions-enabled").checked,
    caption_mode: $("caption-mode").value,
    cues: editorCues(),
    overlay: clone(state.editorOverlay),
    max_width: $("max-width")?.value ? Number($("max-width").value) : null,
    fps: $("output-fps")?.value ? Number($("output-fps").value) : null,
  };
  return changes;
}

function cueEditorValues(item) {
  const cue = item || state.editorOverlay || {};
  return {
    text: cue.text || "",
    font: cue.font || "pillow-default",
    size: cue.size ?? 32,
    color: cue.color || "#ffffff",
    outline_color: cue.outline_color || "#000000",
    outline_width: cue.outline_width ?? 2,
    x: cue.x ?? 0.5,
    y: cue.y ?? 0.85,
    alignment: cue.alignment || "center",
  };
}

function setCueEditorValues(item, cue = null) {
  const value = cueEditorValues(item);
  $("overlay-text").value = value.text;
  $("text-font").value = value.font;
  $("text-size").value = value.size;
  $("text-color").value = value.color;
  $("outline-color").value = value.outline_color;
  $("outline-width").value = value.outline_width;
  $("text-x").value = value.x;
  $("text-y").value = value.y;
  $("alignment").value = value.alignment;
  $("cue-timing").hidden = !cue;
  if (cue) {
    const base = Number($("start").value || 0);
    $("cue-start").value = Math.max(0, Number(cue.start) - base).toFixed(2);
    $("cue-end").value = Math.max(0, Number(cue.end) - base).toFixed(2);
    $("cue-enabled").checked = cue.enabled !== false;
  }
  const review = $("cue-review");
  if (review) {
    review.hidden = !cue || cue.extraction !== "ocr";
    review.textContent =
      cue?.extraction === "ocr"
        ? `OCR · Review words and punctuation${
            cue.confidence != null
              ? ` · ${Math.round(cue.confidence * 100)}% engine confidence`
              : ""
          }`
        : "";
  }
}

function chooseNativeCue(id) {
  if (state.activeCueId) syncActiveCue();
  state.activeCueId = id || "";
  const cue = state.editorCues.find((item) => item.id === state.activeCueId);
  setCueEditorValues(cue || state.editorOverlay, cue);
  if ($("cue-select")) $("cue-select").value = state.activeCueId;
  const editor = $("text-editor");
  const empty = $("text-empty");
  if (editor) editor.hidden = !state.activeCueId;
  if (empty) empty.hidden = Boolean(state.activeCueId);
  renderNativeCues();
}

function renderNativeCues() {
  const track = $("cue-track");
  const select = $("cue-select");
  if (!track || !select) return;
  const start = Number($("start")?.value || currentPlan()?.start || 0);
  const end = Number($("end")?.value || currentPlan()?.end || start + 1);
  const span = Math.max(0.01, end - start);
  select.replaceChildren(new Option("Select text", ""));
  track.replaceChildren();
  const laneEnds = [];
  let rows = 0;
  for (const cue of state.editorCues || []) {
    const cueStart = Number(cue.start);
    const cueEnd = Number(cue.end);
    if (!Number.isFinite(cueStart) || !Number.isFinite(cueEnd) || cueEnd <= cueStart)
      continue;
    const option = new Option(
      cue.text?.slice(0, 45) || "New text",
      cue.id,
    );
    select.append(option);
    const left = Math.max(0, cueStart - start);
    const right = Math.min(span, cueEnd - start);
    if (right <= left) continue;
    let lane = laneEnds.findIndex((value) => value <= left);
    if (lane < 0) lane = laneEnds.length;
    laneEnds[lane] = right;
    rows = Math.max(rows, lane + 1);
    const button = document.createElement("button");
    button.type = "button";
    button.className =
      "cue-chip" + (state.activeCueId === cue.id ? " active" : "");
    button.dataset.cueId = cue.id;
    button.textContent = `${(cueStart - start).toFixed(2)}–${(
      cueEnd - start
    ).toFixed(2)} · ${cue.text || "New text"}`;
    button.title = button.textContent;
    Object.assign(button.style, {
      position: "absolute",
      left: `${(100 * left) / span}%`,
      width: `${(100 * (right - left)) / span}%`,
      top: `${lane * 30}px`,
    });
    button.addEventListener("click", () => {
      chooseNativeCue(cue.id);
      markDraftDirty();
    });
    track.append(button);
  }
  track.style.height = `${rows * 30}px`;
  select.value = state.activeCueId;
  if ($("text-editor")) $("text-editor").hidden = !state.activeCueId;
  if ($("text-empty")) $("text-empty").hidden = Boolean(state.activeCueId);
}

function addNativeCue() {
  syncActiveCue();
  const start = Number($("start").value || 0);
  const end = Number($("end").value || start + 1);
  const playhead = Number(state.view?.playhead);
  const cueStart = Number.isFinite(playhead)
    ? Math.max(start, Math.min(playhead, end - 0.01))
    : start;
  const cue = {
    id: `cue_${requestId("manual").replace(/[^a-zA-Z0-9_-]/g, "")}`,
    text: "",
    start: cueStart,
    end: Math.min(end, cueStart + 2),
    enabled: true,
    origin: "manual",
    evidence_id: null,
    extraction: "source_text",
    confidence: null,
    review_required: false,
    ...cueEditorValues(null),
  };
  state.editorCues.push(cue);
  chooseNativeCue(cue.id);
  markDraftDirty();
  $("overlay-text").focus();
}

function removeNativeCue() {
  if (!state.activeCueId) return;
  syncActiveCue();
  state.editorCues = state.editorCues.filter(
    (cue) => cue.id !== state.activeCueId,
  );
  chooseNativeCue("");
  markDraftDirty();
}

function wireNativeCueControls() {
  $("cue-select")?.addEventListener("change", () => {
    chooseNativeCue($("cue-select").value);
    markDraftDirty();
  });
  $("add-cue")?.addEventListener("click", addNativeCue);
  $("remove-cue")?.addEventListener("click", removeNativeCue);
  for (const id of [
    "overlay-text",
    "text-font",
    "text-size",
    "text-color",
    "text-x",
    "text-y",
    "alignment",
    "outline-width",
    "outline-color",
    "cue-start",
    "cue-end",
    "cue-enabled",
  ]) {
    const node = $(id);
    if (!node) continue;
    node.addEventListener("input", () => {
      syncActiveCue();
      renderNativeCues();
      markDraftDirty();
    });
    node.addEventListener("change", () => {
      syncActiveCue();
      renderNativeCues();
      markDraftDirty();
    });
  }
  document.querySelectorAll("[data-format]").forEach((button) => {
    button.addEventListener("click", () => {
      setNativeFormat(button.dataset.format);
      markDraftDirty();
    });
  });
}

function currentTrim() {
  return {
    start: Number($("start")?.value || currentPlan()?.start || 0),
    end: Number($("end")?.value || currentPlan()?.end || 0),
  };
}

function updateNativeTrim() {
  const plan = currentPlan();
  if (!plan) return;
  const { start, end } = currentTrim();
  const rangeStart = Number(plan.start);
  const rangeEnd = Number(plan.end);
  const length = Math.max(0.01, rangeEnd - rangeStart);
  for (const id of ["start-slider", "end-slider"]) {
    const slider = $(id);
    if (!slider) continue;
    slider.max = String(length);
    slider.value = String(
      id === "start-slider" ? start - rangeStart : end - rangeStart,
    );
  }
  const kept = $("trim-kept");
  if (kept) {
    kept.style.left = `${(100 * (start - rangeStart)) / length}%`;
    kept.style.width = `${(100 * (end - start)) / length}%`;
  }
  setText(
    "trim-summary",
    `${(start - rangeStart).toFixed(2)} – ${(end - rangeStart).toFixed(
      2,
    )} · ${(end - start).toFixed(2)}s kept / ${length.toFixed(2)}s`,
  );
  setText("cut-summary", `Export selection: ${(end - start).toFixed(2)}s`);
  renderNativeCues();
  updateNativePlayhead();
}

function updateNativePlayhead(sourceTime = null) {
  const plan = currentPlan();
  if (!plan) return;
  const { start, end } = currentTrim();
  const video = $("media-video");
  const source =
    sourceTime ??
    (state.playbackReady && video && !video.hidden
      ? Number(plan.start) + Number(video.currentTime || 0)
      : Number(state.view?.playhead ?? start));
  const position = Math.max(start, Math.min(end, source));
  const length = Math.max(0.01, end - start);
  const seek = $("timeline-seek");
  if (seek) {
    seek.setAttribute("aria-valuemin", "0");
    seek.setAttribute("aria-valuemax", String(length));
    seek.setAttribute("aria-valuenow", String(position - start));
    seek.setAttribute("aria-valuetext", `${(position - start).toFixed(2)}s`);
  }
  const playhead = $("playhead");
  if (playhead) {
    playhead.max = String(length);
    playhead.value = String(position - start);
  }
  setText("playhead-time", `Playhead · ${(position - start).toFixed(2)}s`);
  setText("playhead-value", `${(position - start).toFixed(2)}s`);
  const marker = $("playhead");
  if (marker?.style) marker.style.left = `${(100 * (position - start)) / length}%`;
}

function nativeSourceTimeFromPointer(event) {
  const track = $("timeline-seek");
  const { start, end } = currentTrim();
  const box = track.getBoundingClientRect();
  const fraction = Math.max(
    0,
    Math.min(1, (event.clientX - box.left) / Math.max(1, box.width)),
  );
  return start + fraction * (end - start);
}

async function seekNativePlayback(sourceTime, persist = true) {
  const plan = currentPlan();
  if (!plan) return;
  const video = $("media-video");
  const { start, end } = currentTrim();
  const target = Math.max(start, Math.min(end, sourceTime));
  if (!state.playbackReady || video.hidden || !Number.isFinite(video.duration)) {
    notice(
      "Playback is unavailable until an exact retained preview is loaded. Apply changes, then choose Preview.",
      true,
    );
    updateNativePlayhead(target);
    return;
  }
  video.pause();
  video.currentTime = Math.max(
    0,
    Math.min(video.duration - 0.001, target - Number(plan.start)),
  );
  state.view = { ...(state.view || {}), playhead: target };
  updateNativePlayhead(target);
  if (persist)
    await navigateSemantic({ playhead: target }, { message: "Review position saved." });
}

function moveNativeBoundary(which, value) {
  const plan = currentPlan();
  if (!plan) return;
  const other = currentTrim()[which === "start" ? "end" : "start"];
  const next =
    which === "start"
      ? Math.max(Number(plan.start), Math.min(value, other - 0.01))
      : Math.min(Number(plan.end), Math.max(value, other + 0.01));
  $(which).value = next.toFixed(2);
  updateNativeTrim();
  markDraftDirty();
}

function wireNativePlayback() {
  const video = $("media-video");
  if (!video) return;
  video.controls = false;
  $("play-selection")?.addEventListener("click", async () => {
    if (!state.playbackReady || video.hidden) {
      notice(
        "Play selection is disabled until an exact retained preview is loaded. Apply changes, then choose Preview.",
        true,
      );
      return;
    }
    const { start, end } = currentTrim();
    if (video.paused || video.ended) {
      if (
        video.currentTime < 0 ||
        video.currentTime >= Math.max(0, end - Number(currentPlan()?.start || 0))
      )
        video.currentTime = Math.max(0, start - Number(currentPlan()?.start || 0));
      await video.play();
    } else video.pause();
  });
  $("loop-selection")?.addEventListener("click", () => {
    state.loopSelection = !state.loopSelection;
    $("loop-selection").setAttribute(
      "aria-pressed",
      String(state.loopSelection),
    );
  });
  for (const which of ["start", "end"]) {
    $(`${which}-slider`)?.addEventListener("input", () => {
      const plan = currentPlan();
      if (!plan) return;
      moveNativeBoundary(
        which,
        Number(plan.start) + Number($(`${which}-slider`).value),
      );
    });
    $(`set-${which}`)?.addEventListener("click", () => {
      if (!state.playbackReady || video.hidden) {
        notice(
          `Set ${which} here is disabled until an exact retained preview is loaded.`,
          true,
        );
        return;
      }
      const plan = currentPlan();
      moveNativeBoundary(which, Number(plan.start) + video.currentTime);
    });
  }
  $("timeline-seek")?.addEventListener("click", (event) => {
    seekNativePlayback(nativeSourceTimeFromPointer(event)).catch((error) =>
      notice(error.message, true),
    );
  });
  $("timeline-seek")?.addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key))
      return;
    event.preventDefault();
    const { start, end } = currentTrim();
    const current = Number(state.view?.playhead ?? start);
    const step = event.shiftKey ? 0.1 : 0.01;
    const target =
      event.key === "Home"
        ? start
        : event.key === "End"
          ? end
          : current + (event.key === "ArrowLeft" ? -step : step);
    seekNativePlayback(Math.max(start, Math.min(end, target))).catch((error) =>
      notice(error.message, true),
    );
  });
  video.addEventListener("timeupdate", () => {
    const plan = currentPlan();
    if (!plan || video.hidden) return;
    const { start, end } = currentTrim();
    const source = Number(plan.start) + video.currentTime;
    if (source >= end || video.ended) {
      if (state.loopSelection) {
        video.currentTime = Math.max(0, start - Number(plan.start));
        video.play().catch(() => {});
      } else {
        video.pause();
        video.currentTime = Math.max(0, end - Number(plan.start));
      }
    } else if (source < start) {
      video.currentTime = Math.max(0, start - Number(plan.start));
    }
    state.view = { ...(state.view || {}), playhead: source };
    updateNativePlayhead(source);
  });
  video.addEventListener("ended", () => {
    if (state.loopSelection) video.play().catch(() => {});
  });
}

function wireUnavailableNativeActions() {
  const unavailable = (id, message) => {
    const node = document.getElementById(id);
    if (!node) return;
    node.title = message;
    node.addEventListener("click", (event) => {
      event.preventDefault();
      notice(message, true);
    });
  };
  unavailable(
    "search-button",
    "Finding a new moment is unavailable in this scoped MCP review; attach an authorized retained finding first.",
  );
  unavailable(
    "empty-search",
    "Finding a new moment is unavailable in this scoped MCP review; attach an authorized retained finding first.",
  );
  unavailable(
    "settings-button",
    "Collection and provider settings are not exposed by the scoped MCP adapter.",
  );
  unavailable(
    "expand-context",
    "Original-source context expansion is not exposed by the scoped MCP adapter.",
  );
  for (const id of ["caption-track", "caption-offset", "import-captions", "convert-captions"]) {
    unavailable(
      id,
      "Source-caption collection and conversion are not exposed by the scoped MCP adapter; edit retained cues and apply them instead.",
    );
    const node = document.getElementById(id);
    if (node) node.disabled = true;
  }
  const captionStatus = document.getElementById("caption-status");
  if (captionStatus)
    captionStatus.textContent =
      "MCP limitation: source-caption import/conversion is disabled. Existing retained cue fields can still be applied.";
}

function pendingKey(operation, planId) {
  return `${operation}:${planId}`;
}

function pendingFor(operation) {
  const plan = currentPlan();
  return plan ? state.pending.get(pendingKey(operation, plan.id)) : null;
}

function operationLabel(record) {
  if (!record) return "Not requested";
  if (record.phase === "unconfirmed")
    return "Response uncertain · no retry was started";
  if (record.phase === "rejected")
    return "Rejected · no operation was admitted";
  const status = record.status || record.phase || "accepted";
  if (
    status === "ready" ||
    (status === "completed" && record.result?.result?.status === "ready")
  )
    return "Ready · artifact receipt committed";
  if (status === "completed") return "Completed · inspect retained result";
  if (status === "cancelled") return "Cancelled · inspect cleanup result";
  if (status === "failed") return "Failed · no success artifact claimed";
  if (status === "interrupted" || status === "uncertain")
    return `${status} · inspect before any new intent`;
  return `${status} · admission is not an artifact receipt`;
}

function renderOperationRow(operation) {
  const record = pendingFor(operation);
  const stateNode = $(`${operation}-state`);
  const main = $(operation);
  const check = $(`${operation}-check`);
  const cancel = $(`${operation}-cancel`);
  if (stateNode) {
    stateNode.textContent = operationLabel(record);
    stateNode.className = "operation-state";
    if (record?.phase === "rejected" || record?.status === "failed")
      stateNode.classList.add("error");
    if (record?.status === "ready") stateNode.classList.add("ready");
  }
  const active = record && !TERMINAL_OPERATIONS.has(record.status);
  const unknown = record?.phase === "unconfirmed" && !record.operation_id;
  if (main) {
    main.disabled = Boolean(active || (record && !unknown && record.status === "ready"));
    main.setAttribute("aria-busy", String(Boolean(active)));
    main.title = unknown
      ? "The admission response is uncertain. Use the operation check affordance."
      : operationLabel(record);
  }
  if (check) {
    check.hidden = !unknown;
    check.disabled = false;
  }
  if (cancel) {
    cancel.hidden = !record?.operation_id || !active;
    cancel.disabled = !active;
  }
}

function renderOperations() {
  renderOperationRow("preview");
  renderOperationRow("render");
}

function setRecordFromAdmission(record, admission) {
  record.admission = clone(admission);
  record.operation_id = admission.operation_id || record.operation_id;
  record.output_id = admission.output_id || record.output_id;
  record.status = admission.status || "accepted";
  record.phase = record.status;
  record.uncertain = false;
  persistPending();
  renderOperations();
  context();
}

async function readOperation(record) {
  if (!record.operation_id) return null;
  const result = await call("operation", {
    review_id: record.review_id,
    operation_id: record.operation_id,
  });
  record.status = result.status || record.status;
  record.phase = record.status;
  record.result = clone(result);
  if (result.output_id) record.output_id = result.output_id;
  const nested = result.result || {};
  if (nested.artifact_id) record.output_id = nested.artifact_id;
  persistPending();
  renderOperations();
  const completedReady =
    record.status === "ready" ||
    (record.status === "completed" && nested.status === "ready");
  if (completedReady && record.output_id) {
    await loadMedia({
      kind: "artifact",
      identity: record.output_id,
    });
    if (record.operation === "render") await refreshSavedOutputs();
  } else if (["failed", "cancelled", "interrupted", "uncertain"].includes(record.status)) {
    clearMedia(`No preview for ${record.status} operation.`);
  }
  return result;
}

function wait(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

async function pollOperation(record) {
  const token = ++state.pollToken;
  while (
    token === state.pollToken &&
    record.operation_id &&
    !TERMINAL_OPERATIONS.has(record.status)
  ) {
    await wait(650);
    if (token !== state.pollToken) return;
    try {
      await readOperation(record);
    } catch (error) {
      record.phase = "unconfirmed";
      record.uncertain = true;
      persistPending();
      renderOperations();
      notice(
        `Operation status is uncertain. Check ${record.operation_id} explicitly; no new work was started.`,
        true,
      );
      return;
    }
  }
}

async function admitRecord(record) {
  try {
    const admission = await call("admit", {
      review_id: record.review_id,
      request_id: record.request_id,
      operation: record.operation,
      arguments: record.arguments,
    });
    setRecordFromAdmission(record, admission);
    notice(
      `${record.operation} accepted. Production remains separate from the admission record.`,
    );
    await pollOperation(record);
  } catch (error) {
    const looksLikeLostTransport =
      /lost|timeout|timed out|transport|disconnect|network|acknowledg/i.test(
        error.message || "",
      );
    const rejected = Boolean(error.serverResponse) && !looksLikeLostTransport;
    record.phase = rejected ? "rejected" : "unconfirmed";
    record.uncertain = !rejected;
    persistPending();
    renderOperations();
    notice(
      rejected
        ? error.message
        : `The response is uncertain${
            error.message ? ` (${error.message})` : ""
          }. Check request reuses the original identity and inputs; it never creates a new operation.`,
      true,
    );
    return null;
  }
}

async function submitOperation(operation) {
  const plan = currentPlan();
  if (!plan) throw Error("Select a retained plan before requesting production.");
  const key = pendingKey(operation, plan.id);
  let record = state.pending.get(key);
  if (!record) {
    // Capture the complete accepted effect before the first await. Later form
    // edits are a separate raw draft and cannot mutate this request.
    record = {
      review_id: state.reviewId,
      base_plan_id: plan.id,
      operation,
      request_id: requestId(operation),
      arguments: freeze({ plan_id: plan.id }),
      phase: "submitting",
      status: "accepted",
      created_at: Date.now(),
    };
    state.pending.set(key, record);
    persistPending();
  } else if (record.operation_id && !TERMINAL_OPERATIONS.has(record.status)) {
    await readOperation(record);
    await pollOperation(record);
    return;
  } else if (record.phase === "unconfirmed" && !record.operation_id) {
    // An explicit click is the only retry for an unknown acknowledgement.
  } else if (record.phase === "rejected") {
    throw Error("This request was rejected. Apply a new plan revision for new intent.");
  } else if (TERMINAL_OPERATIONS.has(record.status)) {
    throw Error("This request already has a terminal outcome. Apply a new revision for new work.");
  }
  renderOperations();
  await admitRecord(record);
}

async function checkOperation(operation) {
  const record = pendingFor(operation);
  if (!record) return submitOperation(operation);
  if (record.operation_id) {
    try {
      await readOperation(record);
      if (!TERMINAL_OPERATIONS.has(record.status)) await pollOperation(record);
    } catch (error) {
      notice(error.message, true);
    }
    return;
  }
  // The exact request is retried only because the person pressed Check request.
  await admitRecord(record);
}

async function cancelOperation(operation) {
  const record = pendingFor(operation);
  if (!record?.operation_id) throw Error("No admitted operation is available to cancel.");
  await call("cancel", {
    review_id: record.review_id,
    operation_id: record.operation_id,
  });
  record.status = "cancelling";
  record.phase = "cancelling";
  persistPending();
  renderOperations();
  notice("Cancellation requested. The terminal publication outcome is still pending.");
  await pollOperation(record);
}

async function reconcileKnownOperations() {
  for (const record of state.pending.values()) {
    if (
      record.review_id === state.reviewId &&
      record.operation_id &&
      !TERMINAL_OPERATIONS.has(record.status)
    ) {
      try {
        await readOperation(record);
      } catch {
        // Keep the identity and surface it through the operation row.
        record.phase = "unconfirmed";
        record.uncertain = true;
        persistPending();
      }
    }
  }
  renderOperations();
}

function semanticView(overrides = {}) {
  const value = { ...(state.view || {}), ...overrides };
  return Object.fromEntries(
    Object.entries(value).filter(
      ([, item]) => item !== null && item !== undefined && item !== "",
    ),
  );
}

async function navigateSemantic(view, options = {}) {
  if (!state.reviewId) throw Error("No retained review is attached.");
  const nextView = semanticView(view);
  const currentPlanId = currentPlan()?.id || null;
  if (nextView.plan_id && nextView.plan_id !== currentPlanId)
    await flushDraftForNavigation();
  const arguments_ = {
    review_id: state.reviewId,
    view: nextView,
    expected_version: state.viewVersion,
  };
  const identity =
    options.mutationIdentity || JSON.stringify(arguments_);
  const mutation = exactMutation("navigate", identity, arguments_);
  let result;
  if (mutation.phase === "completed") {
    result = mutation.result;
  } else if (mutation.phase === "rejected") {
    throw Error(mutation.error || "Navigation was rejected.");
  } else {
    try {
      result = await call("navigate", {
        ...arguments_,
        request_id: mutation.request_id,
      });
      mutation.phase = "completed";
      mutation.result = clone(result);
      mutation.error = null;
      persistPending();
    } catch (error) {
      markMutationError(mutation, error);
      notice(
        error.serverResponse
          ? error.message
          : `Navigation response is uncertain. Retry keeps request ${mutation.request_id} and does not create a new revision.`,
        true,
      );
      return null;
    }
  }
  state.view = clone(result?.view || nextView);
  state.viewVersion = Number(result?.view_version || state.viewVersion + 1);
  await refresh();
  if (options.message) notice(options.message);
  return result;
}

async function adoptPlan(planId, message = "Displayed revision adopted explicitly.") {
  const plan = currentPlan();
  if (!planId || planId === plan?.id) {
    await refresh();
    return;
  }
  await navigateSemantic(
    {
      plan_id: planId,
      finding_id: null,
      candidate_id: null,
      cue_id: null,
      playhead: state.view?.playhead,
    },
    { message },
  );
}

async function focusCandidate(candidateId) {
  const finding = state.finding;
  if (!finding) throw Error("No retained finding is open.");
  const candidate = (finding.candidates || []).find(
    (item) => item.id === candidateId,
  );
  if (!candidate) throw Error("That candidate is no longer retained.");
  state.selectedCandidate = candidate;
  await navigateSemantic({
    plan_id: null,
    finding_id: finding.id,
    candidate_id: candidate.id,
    playhead: candidate.start,
  });
  renderFinding();
  notice("Candidate focus persisted. Selection remains a separate explicit action.");
}

async function applyChanges() {
  const plan = currentPlan();
  if (!plan) throw Error("Select a retained plan before applying edits.");
  const changes = changesFromForm(plan);
  const arguments_ = {
    review_id: state.reviewId,
    plan_id: plan.id,
    changes: clone(changes),
  };
  const mutation = exactMutation("apply", plan.id, arguments_);
  let result;
  if (mutation.phase === "completed") {
    result = mutation.result;
  } else if (mutation.phase === "rejected") {
    throw Error(mutation.error || "Apply was rejected.");
  } else {
    try {
      result = await call("apply_changes", {
        ...arguments_,
        request_id: mutation.request_id,
      });
      mutation.phase = "completed";
      mutation.result = clone(result);
      mutation.error = null;
      persistPending();
    } catch (error) {
      markMutationError(mutation, error);
      notice(
        error.serverResponse
          ? error.message
          : `Apply response is uncertain. Retry keeps request ${mutation.request_id} and never creates a second revision.`,
        true,
      );
      return;
    }
  }
  const revised = result?.plan;
  if (!revised?.id)
    throw Error("Outtake did not return the applied plan revision.");
  state.applyRevision = revised;
  clearConflict();
  clearMedia("Applied revision has no preview until an exact operation produces one.");
  await navigateSemantic(
    {
      plan_id: revised.id,
      finding_id: null,
      candidate_id: state.view?.candidate_id,
      cue_id: null,
      playhead: state.view?.playhead,
    },
    {
      mutationIdentity: `apply-adopt:${mutation.request_id}`,
      message: `Applied immutable plan revision ${revised.id}; explicitly adopted for this review.`,
    },
  );
}

async function selectCandidate(candidateId) {
  const finding = state.finding;
  if (!finding || !state.reviewId) throw Error("No retained finding is open.");
  const candidate = (finding.candidates || []).find(
    (item) => item.id === candidateId,
  );
  if (!candidate) throw Error("That candidate is no longer retained in this finding.");
  const arguments_ = {
    review_id: state.reviewId,
    finding_id: finding.id,
    candidate_id: candidateId,
    format: nativeFormat(),
    profile: $("profile").value || "share",
  };
  const mutation = exactMutation(
    "select",
    `${finding.id}:${candidateId}:${arguments_.format}:${arguments_.profile}`,
    arguments_,
  );
  let result;
  if (mutation.phase === "completed") {
    result = mutation.result;
  } else if (mutation.phase === "rejected") {
    throw Error(mutation.error || "Candidate selection was rejected.");
  } else {
    try {
      result = await call("select_candidate", {
        ...arguments_,
        request_id: mutation.request_id,
      });
      mutation.phase = "completed";
      mutation.result = clone(result);
      mutation.error = null;
      persistPending();
    } catch (error) {
      markMutationError(mutation, error);
      notice(
        error.serverResponse
          ? error.message
          : `Selection response is uncertain. Retry keeps request ${mutation.request_id}.`,
        true,
      );
      return;
    }
  }
  state.selectedCandidate = candidate;
  await refresh();
  renderFinding();
  context();
  notice(
    `Candidate selected for review (${result?.selected_plan_id || "retained outcome"}).`,
  );
}

async function loadReview(reviewId) {
  if (!reviewId || typeof reviewId !== "string")
    throw Error("The host did not provide an authorized review identity.");
  const ticket = ++state.loadTicket;
  state.pollToken += 1;
  clearMedia("Attaching to retained review…");
  state.reviewId = reviewId;
  state.snapshot = null;
  state.finding = null;
  state.plan = null;
  state.headPlan = null;
  state.view = null;
  state.viewVersion = 1;
  state.selectedCandidate = null;
  state.formPlanId = null;
  state.draftDirty = false;
  state.draftConflict = null;
  restorePending();
  setText("review-id", reviewId);
  $("connection-state").className = "state-pill";
  $("connection-state").textContent = "Attached";
  setText("attachment-state", "Reading retained work · no production or grant renewal");
  renderFinding();
  renderPlan();
  const snapshot = await call("review", { review_id: reviewId });
  if (ticket !== state.loadTicket) return;
  const rendered = renderSnapshot(snapshot);
  const artifactId = rendered.artifactId;
  const plan = currentPlan();
  const targetIsArtifact = snapshot.target?.kind === "artifact";
  const saveOutputName = $("save-output-name");
  if (saveOutputName) saveOutputName.hidden = !targetIsArtifact;
  if (
    artifactId &&
    plan &&
    (!targetIsArtifact || !state.mediaPlanId) &&
    !state.mediaFailedKey
  )
    await loadMedia({ kind: "artifact", identity: artifactId });
  await reconcileKnownOperations();
  await refreshSavedOutputs();
  if (ticket === state.loadTicket && !state.mediaFailedKey)
    notice("Attached to retained review. No work was started.");
}

async function refresh() {
  if (!state.reviewId) return;
  if (state.refreshPromise) return state.refreshPromise;
  const ticket = state.loadTicket;
  state.refreshPromise = (async () => {
    let snapshot = await call("review", { review_id: state.reviewId });
    if (ticket !== state.loadTicket) return;
    const incomingPlanId =
      snapshot?.displayed_plan?.id || snapshot?.view?.plan_id || null;
    const currentPlanId = currentPlan()?.id || null;
    if (
      incomingPlanId !== currentPlanId &&
      (state.draftDirty || state.draftSave)
    ) {
      await flushDraftForNavigation();
      snapshot = await call("review", { review_id: state.reviewId });
      if (ticket !== state.loadTicket) return;
    }
    const rendered = renderSnapshot(snapshot);
    const targetIsArtifact = snapshot.target?.kind === "artifact";
    if (
      rendered.artifactId &&
      currentPlan() &&
      targetIsArtifact &&
      !state.mediaUrl &&
      !state.mediaFailedKey &&
      (!state.mediaPlanId || state.mediaPlanId === currentPlan().id)
    )
      await loadMedia({ kind: "artifact", identity: rendered.artifactId });
    await reconcileKnownOperations();
  })().finally(() => {
    state.refreshPromise = null;
  });
  return state.refreshPromise;
}

function navigate(reviewId) {
  state.navigation = state.navigation
    .then(async () => {
      if (state.reviewId === reviewId) {
        await refresh();
        return;
      }
      await flushDraftForNavigation();
      await loadReview(reviewId);
    })
    .catch((error) => {
      notice(error.message, true);
      throw error;
    });
  return state.navigation;
}

async function run(action) {
  try {
    await action();
  } catch (error) {
    notice(error.message, true);
  }
}

function wireDraftInputs() {
  for (const id of [
    "title",
    "start",
    "end",
    "frame",
    "format",
    "profile",
    "audio",
    "captions-enabled",
    "caption-mode",
    "caption-text",
    "overlay-text",
    "max-width",
    "output-fps",
  ]) {
    $(id).addEventListener("input", markDraftDirty);
    $(id).addEventListener("change", markDraftDirty);
  }
}

function markDraftDirty() {
  if (!currentPlan()) return;
  state.draftDirty = true;
  clearConflict();
  renderDraftStatus();
  clearTimeout(state.draftTimer);
  state.draftTimer = setTimeout(
    () =>
      saveCurrentDraft().catch((error) => {
        notice(error.message, true);
      }),
    650,
  );
  context();
}

ensureNativeSurface();
wireNativeCueControls();
wireNativePlayback();
wireUnavailableNativeActions();

$("workspace-tab").onclick = () => showNativeView("workspace");
$("saved-tab").onclick = () =>
  run(async () => {
    await refreshSavedOutputs();
    showNativeView("saved");
    notice(`${state.savedTotal} saved output${state.savedTotal === 1 ? "" : "s"}.`);
  });
$("saved-refresh").onclick = () => run(refreshSavedOutputs);
$("saved-sort").onchange = () => run(refreshSavedOutputs);
$("playhead").oninput = () =>
  setText("playhead-value", `${Number($("playhead").value || 0).toFixed(2)}s`);
$("playhead").onchange = () =>
  run(() =>
    navigateSemantic({
      playhead: Number($("playhead").value || 0),
    }),
  );
$("preview").onclick = () => run(() => submitOperation("preview"));
$("render").onclick = () => run(() => submitOperation("render"));
$("preview-check").onclick = () => run(() => checkOperation("preview"));
$("render-check").onclick = () => run(() => checkOperation("render"));
$("preview-cancel").onclick = () => run(() => cancelOperation("preview"));
$("render-cancel").onclick = () => run(() => cancelOperation("render"));
$("save-output-name").onclick = () =>
  run(async () => {
    const artifactId = state.snapshot?.target?.kind === "artifact"
      ? state.snapshot.target.id
      : state.mediaArtifactId;
    if (!artifactId || !state.reviewId)
      throw Error("Open a saved output before changing its saved name.");
    await flushDraftForNavigation();
    const receipt = await call("rename_saved_output", {
      review_id: state.reviewId,
      artifact_id: artifactId,
      title: $("title").value.trim(),
      expected_plan_id: state.snapshot?.displayed_plan?.id,
      request_id: requestId("rename"),
    });
    if (receipt.plan?.title) {
      state.plan = { ...state.plan, title: receipt.plan.title };
      setText("plan-heading", receipt.plan.title);
    }
    await refreshSavedOutputs();
    notice("Name saved. No new export needed.");
  });

$("candidate-list").addEventListener("click", (event) => {
  const evidenceId = event.target.closest("[data-evidence-id]")?.dataset.evidenceId;
  const candidateId = event.target.closest("[data-candidate-id]")?.dataset.candidateId;
  const focusCandidateId = event.target.closest("[data-focus-candidate-id]")?.dataset
    .focusCandidateId;
  if (event.target.closest("button")?.dataset.evidenceId) {
    run(() => loadMedia({ kind: "frame", identity: evidenceId, index: 0 }));
  } else if (focusCandidateId && event.target.closest("button")) {
    run(() => focusCandidate(focusCandidateId));
  } else if (candidateId && event.target.closest("button")) {
    run(() => selectCandidate(candidateId));
  }
});
$("evidence-list").addEventListener("click", (event) => {
  const evidenceId = event.target.closest("[data-evidence-id]")?.dataset.evidenceId;
  if (evidenceId) run(() => loadMedia({ kind: "frame", identity: evidenceId, index: 0 }));
});
$("media-video").onerror = $("media-image").onerror = () => {
  clearMedia("This browser could not decode the verified retained bytes.");
  notice("The media bytes are verified, but this browser could not decode them.", true);
};
$("media-video").onplay = $("media-video").onpause = () => context();
$("media-video").onloadedmetadata = () => {
  const playhead = Number(state.view?.playhead);
  if (Number.isFinite(playhead)) $("media-video").currentTime = playhead;
};

app.onhostcontextchanged = style;
app.ontoolinput = async ({ arguments: arguments_ = {} }) => {
  if (arguments_.review_id) await run(() => navigate(arguments_.review_id));
};
app.ontoolresult = async (result) => {
  state.intentResult = result;
  try {
    const value = decode(result);
    const reviewId =
      value?.review_id ||
      value?.result?.review_id ||
      value?.structuredContent?.review_id;
    if (reviewId) await navigate(reviewId);
  } catch (error) {
    notice(error.message, true);
  }
};
app.onerror = (error) => notice(error.message || String(error), true);
app.onteardown = async () => {
  state.pollToken += 1;
  clearTimeout(state.draftTimer);
  try {
    await flushDraftForNavigation();
  } catch {
    // Detaching never cancels work. A failed draft flush remains visible on the
    // server as a conflict for the next authorized attachment.
  }
  releaseMediaUrl();
  return {};
};

wireDraftInputs();
try {
  await app.connect();
  state.connected = true;
  $("connection-state").className = "state-pill";
  $("connection-state").textContent = "Connected";
  style(app.getHostContext() || {});
  notice("Connected. Waiting for an authorized retained review…");
} catch (error) {
  notice(error.message, true);
}