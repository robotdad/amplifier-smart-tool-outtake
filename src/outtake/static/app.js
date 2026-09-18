let workspaceId = null, autosaveTimer = null, saving = null, editVersion = 0;
const workspaceUrl = () => workspaceId?.startsWith("export_")
  ? `/?plan=${encodeURIComponent(plan.id)}&output=${encodeURIComponent(workspaceId)}`
  : `/?plan=${encodeURIComponent(workspaceId || plan.id)}`;
const draftKey = () => `outtake-draft:${workspaceId}`;
function rememberDraft() {
  if (!plan || !workspaceId) return;
  try {
    localStorage.setItem(draftKey(), JSON.stringify({base: plan.id, changes: editChanges()}));
  } catch (error) {
    fail(new Error(`Could not protect pending edits: ${error.message}`));
  }
}
function scheduleSave() {
  clearTimeout(autosaveTimer);
  autosaveTimer = setTimeout(() => {
    if (activeJob || cleanPreparing) return scheduleSave();
    saveEdits().catch(error => {
      $("dirty-label").textContent = "Not saved · check edits";
      fail(error);
    });
  }, 450);
}
window.addEventListener("pagehide", () => {
  if (!dirty || !workspaceId) return;
  rememberDraft();
  // Submission continues during navigation; the local buffer also covers offline exits.
  if (!saving && !activeJob) fetch("/api/call", {
    method: "POST", keepalive: true,
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({operation: "save_workspace", arguments: {
      workspace_id: workspaceId, plan, changes: editChanges(),
    }}),
  }).catch(() => {});
});
let openedOutput = null;
let captionEvidence = null, captionImages = [];
"use strict";
const $ = (id) => document.getElementById(id);
let mediaOverlay = null,
  cleanPreparing = false;
let playbackPreparation = null, playPending = false;
let cues = [],
  activeCue = "",
  wholeOverlay = {},
  availableFonts = [];
const playbackCache = [];
let clipStart = 0,
  clipEnd = 0,
  mediaStart = 0,
  mediaEnd = 0,
  playbackReady = false;
let prefs,
  plan = null,
  finding = null,
  dirty = false,
  format = "mp4",
  activeJob = null,
  outputs = [];
const time = (n) => {
  const seconds = Number(n);
  return `${Math.floor(seconds / 60)}:${(seconds % 60).toFixed(2).padStart(5, "0")}`;
};
const label = (p) =>
  p.title ||
  p.source.path
    .split(/[\\/]/)
    .pop()
    .replace(/\.[^.]+$/, "");
const status = (text) => {
  $("status-text").textContent = text;
};
const fail = (error) => {
  $("error-text").textContent = error.message || String(error);
  $("error").hidden = false;
  status("Ready when you are.");
};
const event = (id, name, fn) =>
  $(id).addEventListener(name, (e) => Promise.resolve(fn(e)).catch(fail));
const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const readOperations = [
    "caption_tracks",
    "fonts",
    "output_profiles",
    "preferences",
    "get_plan",
    "get_workspace",
    "get_finding",
    "get_evidence",
    "artifact",
    "saved_outputs",
  ];
let operationQueue = Promise.resolve();
async function api(operation, args = {}) {
  if (readOperations.includes(operation)) return callApi(operation, args);
  // Reserve the slot before fetch starts, including while its job ID is pending.
  const result = operationQueue.then(() => callApi(operation, args));
  operationQueue = result.catch(() => {});
  return result;
}
async function callApi(operation, args = {}) {
  const readOnly = readOperations.includes(operation);
  if (activeJob && !readOnly)
    throw new Error(
      "An operation is already running. Wait for it to finish, or cancel it.",
    );
  if (!readOnly) document.body.classList.add("busy");
  if (!activeJob && !["save_workspace", "get_workspace"].includes(operation))
    status(
      {
        find: "Finding the moment in your collection…",
        render: "Rendering your export…",
        preview: "Preparing a real preview…",
        review_frames: "Inspecting source frames…",
        catalog: "Looking for matching sources…",
      }[operation] || "Working…",
    );
  try {
    const response = await fetch("/api/call", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ operation, arguments: args }),
    });
    const started = await response.json();
    if (!response.ok)
      throw new Error(started.error || "Could not start the operation.");
    const jobId = started.job_id;
    if (!readOnly) activeJob = jobId;
    if (!readOnly)
      $("cancel-button").hidden = ![
        "find",
        "make",
        "inspect",
        "preview",
        "render",
        "review_frames",
      ].includes(operation);
    for (;;) {
      await pause(180);
      const jobResponse = await fetch(`/api/jobs/${jobId}`);
      if (!jobResponse.ok)
        throw new Error(
          "Workspace session expired. Reopen the dashboard link from your agent.",
        );
      const job = await jobResponse.json();
      if (job.status === "running") continue;
      if (
        job.status === "failed" ||
        ["failed", "cancelled"].includes(job.result?.status)
      ) {
        const detail = job.result?.error;
        throw new Error(
          `${detail?.message || "Operation did not complete."} ${detail?.remediation || ""}`,
        );
      }
      return job.result;
    }
  } finally {
    if (!readOnly) {
      activeJob = null;
      $("cancel-button").hidden = true;
      document.body.classList.remove("busy");
    }
  }
}

function view(name) {
  $("workspace").hidden = name !== "workspace";
  $("saved").hidden = name !== "saved";
  $("workspace-tab").classList.toggle("active", name === "workspace");
  $("saved-tab").classList.toggle("active", name === "saved");
  if (name === "saved") $("video").pause();
}
function setFormat(value) {
  format = value;
  document
    .querySelectorAll("[data-format]")
    .forEach((button) =>
      button.classList.toggle("active", button.dataset.format === value),
    );
  $("audio").disabled = value !== "mp4";
  $("format-note").textContent = {
    mp4: "MP4 · compatible video with optional audio.",
    gif: "GIF · animated, silent, easy to share.",
    png: "Image · the selected source frame, with your text.",
  }[value];
}
function edited() {
  if (!plan) return;
  dirty = true;
  editVersion++;
  rememberDraft();
  scheduleSave();
  if (mediaOverlay) {
    if (!cleanPreparing && !activeJob) {
      cleanPreparing = true;
      preparePlayback()
        .then(() => {
          if ($("video").paused) $("video").currentTime = Math.max(0, Number($("start").value) - mediaStart);
          status("Ready to play the selected clip.");
        })
        .catch(fail)
        .finally(() => { cleanPreparing = false; });
    }
  }
  if (!$("preview-label").hidden)
    $("preview-label").textContent =
      "Preview has earlier edits · preview to update";
  $("dirty-label").textContent = "Saving edits…";
  $("duration-label").textContent =
    `${Math.max(0, Number($("end").value) - Number($("start").value)).toFixed(2)}s`;
  updateTrim();
}
function fillPlan() {
  $("edit-controls").disabled = false;
  $("preview-button").disabled = false;
  $("export-button").disabled = false;
  $("source-title").textContent = label(plan);
  $("source-detail").textContent =
    `${time(plan.start)} — ${time(plan.end)} · ${plan.source.width} × ${plan.source.height}`;
  $("revision-label").hidden = false;
  $("revision-label").textContent = `Revision ${plan.revision}`;
  $("start").value = plan.start;
  $("end").value = plan.end;
  $("frame").value = plan.frame;
  updateTrim();
  $("start").max = plan.source.duration;
  $("end").max = plan.source.duration;
  $("frame").max = plan.source.duration;
  cues = structuredClone(plan.cues || []);
  wholeOverlay = {};
  if (plan.overlay?.text)
    cues.unshift({
      ...structuredClone(plan.overlay),
      id: "cue_legacy",
      start: plan.start,
      end: plan.end,
      enabled: true,
      origin: "manual",
      evidence_id: null,
    });
  activeCue = "";
  $("moment-title").value = plan.title || label(plan);
  $("captions-enabled").checked = plan.captions_enabled !== false;
  $("caption-mode").value = plan.caption_mode || "editable";
  $("caption-mode").querySelector('[value="original"]').disabled = !plan.caption_evidence_id;
  $("caption-mode").querySelector('[value="editable"]').disabled = !!plan.caption_evidence_id && !cues.some(c => c.origin === "caption");
  $("convert-captions").hidden = !plan.caption_evidence_id;
  $("ocr-note").hidden = !plan.caption_evidence_id;
  $("cue-review").hidden = true;
  $("caption-status").textContent =
    (plan.warnings || []).join(" ") ||
    `Captions: ${plan.caption_status || "not imported"}`;
  $("max-width").value = plan.max_width || "";
  $("output-fps").value = plan.fps || "";
  const overlay = {};
  $("overlay-text").value = overlay.text || "";
  $("text-size").value = overlay.size || 32;
  $("text-color").value = overlay.color || "#ffffff";
  $("outline-color").value = overlay.outline_color || "#000000";
  $("outline-width").value = overlay.outline_width ?? 2;
  $("text-x").value = overlay.x ?? 0.5;
  $("text-y").value = overlay.y ?? 0.85;
  $("alignment").value = overlay.alignment || "center";
  $("text-font").value = overlay.font || "pillow-default";
  refreshCues();
  $("profile").value = plan.profile;
  $("audio").checked = plan.audio === "preserve";
  setFormat(plan.format);
  dirty = false;
  $("dirty-label").textContent = "Saved plan";
  $("duration-label").textContent = `${(plan.end - plan.start).toFixed(2)}s`;
  $("cut-summary").textContent =
    `${time(plan.start)} → ${time(plan.end)} · ${(plan.end - plan.start).toFixed(2)}s`;
  history.replaceState(null, "", workspaceUrl());
}
function editChanges(validate = false) {
  const start = Number($("start").value),
    end = Number($("end").value);
  if (validate && (
    !Number.isFinite(start) ||
    !Number.isFinite(end) ||
    start < 0 ||
    end <= start ||
    end > plan.source.duration
  ))
    throw new Error(
      "Choose a beginning and end inside the source, with the end after the beginning.",
    );
  let frame = Number($("frame").value);
  if (frame < start || frame >= end) frame = start;
  storeText();
  const overlay = wholeOverlay.text ? wholeOverlay : null;
  return {
      start,
      end,
      frame,
      format,
      profile: $("profile").value,
      audio: format === "mp4" && $("audio").checked ? "preserve" : "mute",
      overlay,
      cues,
      title: $("moment-title").value,
      captions_enabled: $("captions-enabled").checked,
      caption_mode: $("caption-mode").value,
      max_width: $("max-width").value ? Number($("max-width").value) : null,
      fps: $("output-fps").value ? Number($("output-fps").value) : null,
  };
}
async function saveEdits() {
  clearTimeout(autosaveTimer);
  if (saving) return saving;
  if (!plan || !dirty) return;
  saving = (async () => {
    while (dirty) {
      while (activeJob) await pause(100);
      const version = editVersion;
      const changes = editChanges(true);
      const revised = await api("save_workspace", {workspace_id: workspaceId, plan, changes});
      plan = revised;
      $("revision-label").textContent = `Revision ${plan.revision}`;
      $("source-title").textContent = label(plan);
      history.replaceState(null, "", workspaceUrl());
      if (version === editVersion) {
        dirty = false;
        localStorage.removeItem(draftKey());
        $("dirty-label").textContent = "All edits saved";
      } else rememberDraft();
    }
  })();
  try { await saving; } finally { saving = null; }
}
function showMedia(receipt) {
  $("empty-preview").hidden = true;
  $("video").pause();
  const video = receipt.plan.format === "mp4";
  playbackReady = video;
  mediaOverlay =
    receipt.plan.overlay || (receipt.plan.cues?.length || (receipt.plan.captions_enabled && receipt.plan.caption_mode === "original") ? true : null);
  if (
    video &&
    !playbackCache.some((r) => r.artifact_id === receipt.artifact_id)
  )
    playbackCache.push(receipt);
  mediaStart = receipt.plan.start;
  mediaEnd = receipt.plan.end;
  $("video").hidden = !video;
  $("image").hidden = video;
  const element = video ? $("video") : $("image");
  element.src = `/media/export/${receipt.artifact_id}`;
  if (video) $("video").load();
  $("preview-label").hidden = false;
  $("preview-label").textContent =
    receipt.purpose === "preview" ? "Rendered preview" : "Saved export";
}
function showEvidence(evidence) {
  $("filmstrip").replaceChildren();
  (evidence.frames || []).forEach((frame, index) => {
    const button = document.createElement("button");
    button.className = "frame";
    button.title = `Select still at ${time(frame.time)}`;
    const img = document.createElement("img");
    img.src = `/media/frame/${evidence.id}/${index}`;
    img.alt = `Source frame at ${time(frame.time)}`;
    const caption = document.createElement("span");
    caption.textContent = time(frame.time);
    button.append(img, caption);
    button.addEventListener("click", () => {
      if (
        plan &&
        frame.time >= Number($("start").value) &&
        frame.time < Number($("end").value)
      ) {
        $("frame").value = frame.time;
        edited();
      }
      $("video").pause();
      $("video").hidden = true;
      $("image").hidden = false;
      $("image").src = img.src;
      $("empty-preview").hidden = true;
      $("preview-label").hidden = false;
      $("preview-label").textContent = "Source evidence";
    });
    $("filmstrip").append(button);
  });
  if (evidence.frames?.length && $("empty-preview").hidden === false) {
    $("image").src = `/media/frame/${evidence.id}/0`;
    $("image").hidden = false;
    $("empty-preview").hidden = true;
    $("preview-label").hidden = false;
    $("preview-label").textContent = "Source evidence";
  }
}
async function loadPlan(value, receipt = null, preserveFinding = false, outputId = null) {
  await saveEdits();
  $("edit-controls").disabled = true;
  $("trim-controls").disabled = true;
  $("preview-button").disabled = true;
  $("export-button").disabled = true;
  $("filmstrip").replaceChildren();
  const workspace = await api("get_workspace", {plan_id: value.id, artifact_id: receipt?.artifact_id || outputId});
  workspaceId = workspace.workspace_id;
  value = workspace.plan;
  if (receipt && receipt.plan.id !== value.id) receipt = null;
  receipt ||= outputs.find((output) => output.plan.id === value.id) || null;
  openedOutput = receipt;
  $("save-output-name").hidden = !receipt || receipt.purpose === "preview";
  clipStart = value.start;
  clipEnd = value.end;
  playbackReady = false;
  mediaOverlay = null;
  plan = value;
  fillPlan();
  const buffered = localStorage.getItem(draftKey());
  if (buffered) {
    const draft = JSON.parse(buffered);
    const contains = (saved, pending) => pending !== null && typeof pending === "object"
      ? saved != null && Object.entries(pending).every(([key, value]) => contains(saved[key], value))
        && (!Array.isArray(pending) || saved.length === pending.length)
      : saved === pending;
    const matches = contains(plan, draft.changes);
    if (matches) localStorage.removeItem(draftKey());
    else if (draft.base === plan.id) {
      const retained = plan;
      plan = {...plan, ...draft.changes};
      fillPlan();
      plan = retained;
      edited();
    } else fail(new Error("This workspace has newer saved edits. A pending local draft was preserved; reconcile it before continuing."));
  }
  view("workspace");
  $("video").pause();
  $("video").hidden = true;
  $("image").hidden = true;
  $("empty-preview").hidden = false;
  if (!preserveFinding) {
    finding = plan.finding_id
      ? await api("get_finding", { finding_id: plan.finding_id })
      : null;
    showMoments();
  }
  const selected =
    finding?.candidates?.find(
      (candidate) => candidate.id === plan.candidate_id,
    ) || (finding?.candidates?.length === 1 ? finding.candidates[0] : null);
  $("uncertainty").textContent =
    selected?.uncertainty ||
    "Sound is yours to review. Play the clip and adjust its beginning or end.";
  const tracks = await api("caption_tracks", { plan });
  $("caption-track").replaceChildren(
    new Option("Default track", ""),
    ...tracks.map(
      (t) =>
        new Option(
          `${t.language} · ${t.kind} · ${t.id}${t.default ? " · default" : ""}`,
          t.id,
        ),
    ),
  );
  const hasCaptions = tracks.length > 0;
  $("captions-section").open = false;
  $("captions-summary").textContent = hasCaptions
    ? "Source captions"
    : "Source captions · None available";
  $("captions-summary").setAttribute("aria-disabled", String(!hasCaptions));
  $("captions-enabled").disabled = !hasCaptions;
  if (!hasCaptions) $("captions-enabled").checked = false;
  $("import-captions").disabled = !hasCaptions;
  await loadCaptionImages();
  if (receipt) showMedia(receipt);
  showEvidence(await api("review_frames", { plan }));
  status("Ready to refine. Your earlier exports stay unchanged.");
}
function showMoments() {
  $("moments-list").replaceChildren();
  const candidates = finding?.candidates || [];
  $("moment-count").textContent = candidates.length || (plan ? 1 : 0);
  $("request-title").textContent = finding
    ? `${finding.request.title} · ${finding.request.description}`
    : plan
      ? label(plan)
      : "Start with a memory, or open a plan from your agent.";
  if (!candidates.length && plan) {
    const item = document.createElement("div");
    item.className = "moment active";
    const title = document.createElement("strong");
    title.textContent = label(plan);
    const detail = document.createElement("span");
    detail.className = "timing";
    detail.textContent = `${time(plan.start)} — ${time(plan.end)}`;
    item.append(title, detail);
    $("moments-list").append(item);
  }
  candidates.forEach((candidate, index) => {
    const button = document.createElement("button");
    button.className =
      "moment" + (candidate.id === plan?.candidate_id ? " active" : "");
    button.title = candidate.explanation;
    const title = document.createElement("strong");
    title.textContent = `Moment ${index + 1}`;
    const timing = document.createElement("span");
    timing.className = "timing";
    timing.textContent = `${time(candidate.start)} — ${time(candidate.end)}`;
    const description = document.createElement("p");
    description.textContent = candidate.explanation;
    const sample = candidate.review_frames?.[0];
    if (sample) {
      const thumbnail = document.createElement("img");
      thumbnail.src = `/media/frame/${sample.evidence_id}/${sample.index}`;
      thumbnail.alt = `Source evidence at ${time(sample.time)}`;
      thumbnail.className = "moment-thumbnail";
      button.append(thumbnail);
    }
    button.append(title, timing, description);
    button.addEventListener("click", async () => {
      try {
        const selected = await api("select", {
          finding_id: finding.id,
          candidate_id: candidate.id,
        });
        await loadPlan(selected, null, true);
        document
          .querySelectorAll(".moment")
          .forEach((el) => el.classList.remove("active"));
        button.classList.add("active");
        $("uncertainty").textContent =
          candidate.uncertainty +
          " Sound is unverified; review local playback.";
      } catch (e) {
        fail(e);
      }
    });
    $("moments-list").append(button);
  });
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
event("captions-summary", "click", (e) => {
  if ($("captions-summary").getAttribute("aria-disabled") === "true")
    e.preventDefault();
});
for (const boundary of ["start", "end"])
  event(`cue-${boundary}-here`, "click", () => {
    const cue = cues.find((c) => c.id === activeCue);
    if (!cue || !playbackReady) return;
    const t = mediaStart + $("video").currentTime;
    cue[boundary] =
      boundary === "start"
        ? Math.min(t, cue.end - 0.01)
        : Math.max(t, cue.start + 0.01);
    cue[boundary] = Math.max(0, Math.min(plan.source.duration, cue[boundary]));
    chooseCue(activeCue);
    edited();
  });
async function refreshSaved() {
  outputs = await api("saved_outputs", {sort_by: $("saved-sort").value});
  $("saved-count").textContent = outputs.length;
  $("saved-grid").replaceChildren();
  if (!outputs.length) {
    const p = document.createElement("p");
    p.className = "muted";
    p.textContent =
      "Your exports will appear here. Previews stay in the workspace.";
    $("saved-grid").append(p);
  }
  outputs.forEach((receipt) => {
    const card = document.createElement("article");
    card.className = "output-card";
    const media = document.createElement(
      receipt.plan.format === "mp4" ? "video" : "img",
    );
    media.src = `/media/export/${receipt.artifact_id}`;
    if (media.tagName === "VIDEO") {
      media.controls = true;
      media.preload = "metadata";
    } else media.alt = label(receipt.plan);
    const body = document.createElement("div");
    body.className = "body";
    const title = document.createElement("h2");
    title.textContent = label(receipt.plan);
    const detail = document.createElement("p");
    detail.textContent = `${receipt.plan.format.toUpperCase()} · ${time(receipt.plan.start)}–${time(receipt.plan.end)} · ${(receipt.bytes / 1024 / 1024).toFixed(1)} MB`;
    const edits = document.createElement("p");
    edits.textContent = receipt.plan.cues?.length
      ? `${receipt.plan.cues.length} timed text cues`
      : receipt.plan.overlay
        ? `“${receipt.plan.overlay.text}”`
        : "Original moment · no text overlay";
    const actions = document.createElement("div");
    actions.className = "card-actions";
    const open = document.createElement("button");
    open.textContent = "Open";
    open.addEventListener("click", () =>
      loadPlan(receipt.plan, receipt).catch(fail),
    );
    const download = document.createElement("a");
    download.href = `/media/export/${receipt.artifact_id}?download=1`;
    actionIcon(download, "Download", "M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5");
    download.download = `outtake.${receipt.plan.format}`;
    const remove = document.createElement("button");
    actionIcon(
      remove,
      "Delete",
      "M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7m4-7v7",
    );
    remove.addEventListener("click", async () => {
      if (
        !confirm(
          `Delete “${label(receipt.plan)}”? This removes its generated file and receipt. The source and plan remain.`,
        )
      )
        return;
      try {
        await api("delete_output", { artifact_id: receipt.artifact_id });
        for (let i = playbackCache.length - 1; i >= 0; i--)
          if (playbackCache[i].artifact_id === receipt.artifact_id)
            playbackCache.splice(i, 1);
        await refreshSaved();
        status("Export deleted. Source and plan preserved.");
      } catch (error) {
        fail(error);
      }
    });
    actions.append(open, download, remove);
    body.append(title, detail, edits, actions);
    card.append(media, body);
    $("saved-grid").append(card);
  });
  status(`${outputs.length} saved output${outputs.length === 1 ? "" : "s"}.`);
}
function credentialStatus() {
  const name = $("provider").value;
  $("credential-status").textContent = prefs.credentials[name]
    ? "Host credential available. Keys are never stored here."
    : name === "openai-chatgpt"
      ? "Sign in using outtake provider-login (provider: openai-chatgpt), then reopen Settings. Uses the Amplifier Agent OAuth cache."
      : name === "github-copilot"
        ? "Run gh auth login, then export GH_TOKEN from gh auth token before starting Outtake. Requires Copilot access."
        : "No host credential found. Set the provider’s environment key before starting Outtake.";
}
function settingsForm() {
  const grant = prefs.model_grant || {};
  $("source-roots").value = prefs.settings.source_roots.join("\n");
  $("output-root").value = prefs.settings.output_root;
  $("appearance").value = prefs.appearance;
  $("provider").value = grant.provider || "gemini";
  $("model").value = grant.model || "";
  $("allow-smart").checked = !!(grant.allow_request && grant.allow_metadata);
  $("allow-captions").checked = !!grant.allow_captions;
  $("allow-frames").checked = !!grant.allow_frames;
  $("time-budget").value = prefs.settings.limits.timeout_seconds;
  $("model-budget").value = grant.max_model_calls || 12;
  $("frame-budget").value = grant.max_frames || 48;
  credentialStatus();
}

event("settings-form", "submit", async (e) => {
  e.preventDefault();
  const settings = structuredClone(prefs.settings);
  settings.source_roots = $("source-roots")
    .value.split("\n")
    .map((s) => s.trim())
    .filter(Boolean);
  settings.output_root = $("output-root").value.trim();
  settings.limits.timeout_seconds = Number($("time-budget").value);
  const model = $("model").value.trim();
  const grant = model
    ? {
        ...(prefs.model_grant || {}),
        provider: $("provider").value,
        model,
        allow_request: $("allow-smart").checked,
        allow_metadata: $("allow-smart").checked,
        allow_captions: $("allow-captions").checked,
        allow_frames: $("allow-frames").checked,
        vision: $("allow-frames").checked,
        max_model_calls: Number($("model-budget").value),
        max_frames: Number($("frame-budget").value),
      }
    : null;
  prefs = await api("configure", {
    settings,
    model_grant: grant,
    appearance: $("appearance").value,
  });
  document.documentElement.dataset.theme = prefs.appearance;
  $("settings-dialog").close();
  status("Settings saved. Your current edits are preserved.");
});
event("search-form", "submit", async (e) => {
  e.preventDefault();
  if (!prefs.model_grant?.allow_request)
    throw new Error(
      "Choose a provider/model and allow request metadata in Settings first.",
    );
  const title = $("search-title").value.trim(),
    description = $("search-description").value.trim();
  if (!description) throw new Error("Describe the moment you remember.");
  $("search-dialog").close();
  finding = await api("find", {
    request: { title, description, request_id: crypto.randomUUID() },
    grant: prefs.model_grant,
  });
  plan = null;
  $("video").pause();
  $("video").hidden = true;
  $("image").hidden = true;
  $("empty-preview").hidden = false;
  $("filmstrip").replaceChildren();
  $("source-title").textContent = "Choose a moment";
  $("source-detail").textContent = "";
  $("preview-label").hidden = true;
  $("revision-label").hidden = true;
  $("edit-controls").disabled = true;
  $("preview-button").disabled = true;
  $("export-button").disabled = true;
  showMoments();
  view("workspace");
  status("Choose a proposed moment to review and refine.");
});
event("browse-button", "click", async () => {
  const title = $("search-title").value.trim();
  if (!title) throw new Error("Enter a film or show title first.");
  const result = await api("catalog", { title, limit: 20 });
  $("source-results").replaceChildren();
  for (const source of result.sources) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = source.label;
    button.addEventListener("click", async () => {
      try {
        const info = await api("source_details", { source_id: source.id });
        const selection = await api("plan", {
          source: info.source.path,
          start: 0,
          end: Math.min(10, info.source.duration),
        });
        $("search-dialog").close();
        await loadPlan(selection);
      } catch (e) {
        fail(e);
      }
    });
    $("source-results").append(button);
  }
  status(
    result.scope_complete
      ? `${result.sources.length} matching sources.`
      : "Discovery was bounded. Narrow the title if needed.",
  );
});
event("preview-button", "click", async () => {
  await saveEdits();
  showMedia(await api("preview", { plan }));
  status("Preview ready. Play it to check the cut and sound.");
});
event("export-button", "click", async () => {
  await saveEdits();
  const exportedVersion = editVersion;
  const sourceWorkspace = workspaceId;
  const receipt = await api("render", { plan });
  await saveEdits();
  const published = await api("finish_workspace_export", {
    workspace_id: sourceWorkspace, artifact_id: receipt.artifact_id,
  });
  if (editVersion === exportedVersion) {
    workspaceId = published.workspace_id;
    plan = published.plan;
    history.replaceState(null, "", workspaceUrl());
  }
  openedOutput = receipt;
  $("save-output-name").hidden = false;
  await refreshSaved();
  view("saved");
  status(
    `Export ready · ${receipt.plan.format.toUpperCase()}. Your earlier outputs are preserved.`,
  );
});
event("workspace-tab", "click", () => view("workspace"));
event("saved-tab", "click", async () => {
  await saveEdits();
  await refreshSaved();
  view("saved");
});
event("saved-refresh", "click", refreshSaved);
event("saved-sort", "change", refreshSaved);
for (const id of ["search-button", "empty-search"])
  event(id, "click", () => $("search-dialog").showModal());
event("settings-button", "click", () => {
  settingsForm();
  $("settings-dialog").showModal();
});
event("provider", "change", credentialStatus);
event("cancel-button", "click", async () => {
  if (activeJob) {
    await fetch("/api/cancel", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_id: activeJob }),
    });
    status("Cancellation requested; waiting for cleanup…");
  }
});
event("dismiss-error", "click", () => {
  $("error").hidden = true;
});
document
  .querySelectorAll("[data-close]")
  .forEach((button) =>
    button.addEventListener("click", () => $(button.dataset.close).close()),
  );
document.querySelectorAll("[data-format]").forEach((button) =>
  button.addEventListener("click", () => {
    setFormat(button.dataset.format);
    if (button.dataset.format === "gif" && $("profile").value === "share")
      $("profile").value = "mobile";
    edited();
  }),
);
for (const id of [
  "start",
  "end",
  "frame",
  "captions-enabled",
  "caption-mode",
  "max-width",
  "output-fps",
  "overlay-text",
  "text-font",
  "cue-start",
  "cue-end",
  "cue-enabled",
  "text-size",
  "text-color",
  "text-x",
  "text-y",
  "alignment",
  "outline-width",
  "outline-color",
  "profile",
  "audio",
])
  event(id, "input", () => {
    storeText();
    refreshCues();
    edited();
  });
function updateTrim() {
  if (!plan) return;
  $("trim-controls").disabled = false;
  const length = clipEnd - clipStart;
  const start = Number($("start").value) - clipStart;
  const end = Number($("end").value) - clipStart;
  for (const id of ["start-slider", "end-slider"]) $(id).max = length;
  $("start-slider").value = start;
  $("end-slider").value = end;
  $("trim-kept").style.left = `${(100 * start) / length}%`;
  $("trim-kept").style.width = `${(100 * (end - start)) / length}%`;
  $("trim-summary").textContent =
    `${time(start)} – ${time(end)} · ${(end - start).toFixed(2)}s kept / ${time(length)}`;
  $("cut-summary").textContent =
    `Export selection: ${(end - start).toFixed(2)}s`;
}
function moveBoundary(which, sourceTime) {
  const start = Number($("start").value),
    end = Number($("end").value);
  const value =
    which === "start"
      ? Math.max(clipStart, Math.min(sourceTime, end - 0.01))
      : Math.min(clipEnd, Math.max(sourceTime, start + 0.01));
  $(which).value = value.toFixed(2);
  edited();
  const video = $("video");
  video.pause();
  if (playbackReady && value >= mediaStart && value <= mediaEnd)
    video.currentTime = Math.max(
      0,
      Math.min(value - mediaStart, video.duration - 0.04),
    );
  else status("Use Play selection to prepare video for these boundaries.");
}
for (const which of ["start", "end"]) {
  event(`${which}-slider`, "input", () =>
    moveBoundary(which, clipStart + Number($(`${which}-slider`).value)),
  );
  event(`set-${which}`, "click", () => {
    if (!playbackReady)
      return status("Use Play selection to prepare the video first.");
    moveBoundary(which, mediaStart + $("video").currentTime);
  });
}
async function preparePlayback(start = clipStart, end = clipEnd) {
  if (playbackPreparation) return playbackPreparation;
  playbackPreparation = loadPlayback(start, end);
  try { await playbackPreparation; }
  finally { playbackPreparation = null; }
}
async function loadPlayback(start, end) {
  const cached = [...playbackCache, ...outputs].find(
    (r) =>
      r.plan.format === "mp4" &&
      !r.plan.overlay &&
      !r.plan.cues?.length &&
      !(r.plan.captions_enabled && r.plan.caption_mode === "original") &&
      r.plan.source.sha256 === plan.source.sha256 &&
      r.plan.start <= start &&
      r.plan.end >= end,
  );
  if (cached) showMedia(cached);
  else {
    const review = await api("revise", {
      plan,
      changes: {
        start,
        end,
        frame: start,
        format: "mp4",
        overlay: null,
        cues: [],
        captions_enabled: false,
        audio: plan.source.has_audio ? "preserve" : "mute",
      },
    });
    showMedia(await api("preview", { plan: review }));
  }
  $("video").muted = format === "gif" || !$("audio").checked;
  await new Promise((resolve, reject) => {
    const video = $("video");
    if (video.readyState >= 2) return resolve();
    video.addEventListener("loadeddata", resolve, { once: true });
    video.addEventListener(
      "error",
      () => reject(new Error("Playback preview could not load.")),
      { once: true },
    );
  });
}
event("play-selection", "click", async () => {
  const video = $("video");
  if (playPending) return;
  if (!video.paused && !video.ended) {
    video.pause();
    return;
  }
  playPending = true;
  updatePlaybackButton();
  try {
    if (playbackPreparation) await playbackPreparation;
    let start = Number($("start").value), end = Number($("end").value);
    if (!playbackReady || start < mediaStart || end > mediaEnd)
      await preparePlayback();
    start = Number($("start").value);
    end = Number($("end").value);
    video.muted = format === "gif" || !$("audio").checked;
    if (video.currentTime < start - mediaStart || video.currentTime >= end - mediaStart)
      video.currentTime = Math.max(0, start - mediaStart);
    await video.play();
  } catch (error) {
    if (error.name !== "AbortError") throw error;
  } finally {
    playPending = false;
    updatePlaybackButton();
  }
});
event("expand-context", "click", async () => {
  const start = Math.max(0, clipStart - 15),
    end = Math.min(plan.source.duration, clipEnd + 15);
  await preparePlayback(start, end);
  clipStart = start;
  clipEnd = end;
  updateTrim();
  status("More source context loaded. Your export selection is unchanged.");
});
event("video", "play", () => {
  const video = $("video"),
    start = Number($("start").value) - mediaStart,
    end = Number($("end").value) - mediaStart;
  if (video.currentTime < start || video.currentTime >= end)
    video.currentTime = Math.max(0, start);
});
event("loop-selection", "click", () => {
  const button = $("loop-selection");
  button.setAttribute(
    "aria-pressed",
    String(button.getAttribute("aria-pressed") !== "true"),
  );
});
function constrainPlayback() {
  const video = $("video");
  if (!playbackReady || video.seeking || video.readyState < 2 || (video.paused && !video.ended)) return;
  const start = Number($("start").value) - mediaStart,
    end = Number($("end").value) - mediaStart;
  if (video.currentTime >= end || video.ended) {
    if ($("loop-selection").getAttribute("aria-pressed") === "true") {
      video.currentTime = Math.max(0, start);
      video.play().catch(fail);
    } else {
      video.pause();
      video.currentTime = Math.min(end, video.duration);
    }
  } else if (video.currentTime < start - 0.002) video.currentTime = Math.max(0, start);
}
event("video", "timeupdate", constrainPlayback);
event("video", "ended", constrainPlayback);
function updatePlayhead() {
  const visible = plan && playbackReady && !$("video").hidden;
  $("playhead").hidden = !visible;
  if (!visible) return;
  const position = Math.max(
    0,
    Math.min(
      clipEnd - clipStart,
      mediaStart + $("video").currentTime - clipStart,
    ),
  );
  $("playhead").style.left = `${(100 * position) / (clipEnd - clipStart)}%`;
  $("playhead-time").textContent = `Playhead · ${time(position)}`;
  $("timeline-seek").setAttribute("aria-valuemax", String(clipEnd - clipStart));
  $("timeline-seek").setAttribute("aria-valuenow", position.toFixed(2));
  $("timeline-seek").setAttribute("aria-valuetext", time(position));
}
async function seekTimeline(sourceTime) {
  if (!plan || activeJob) return;
  const resume = !$("video").paused && !$("video").ended;
  $("video").pause();
  if (playbackPreparation) await playbackPreparation;
  if (!playbackReady || sourceTime < mediaStart || sourceTime >= mediaEnd)
    await preparePlayback();
  const video = $("video");
  video.pause();
  video.currentTime = Math.max(
    0,
    Math.min(sourceTime - mediaStart, video.duration - 0.001),
  );
  updatePlayhead();
  if (resume) await video.play();
  status("Ready to refine. Your earlier exports stay unchanged.");
}
event("timeline-seek", "click", async (e) => {
  const box = $("timeline-seek").getBoundingClientRect();
  await seekTimeline(
    clipStart +
      Math.max(0, Math.min(1, (e.clientX - box.left) / box.width)) *
        (clipEnd - clipStart),
  );
});
event("timeline-seek", "keydown", async (e) => {
  if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) return;
  e.preventDefault();
  const current = playbackReady
    ? mediaStart + $("video").currentTime
    : clipStart;
  const step = e.shiftKey ? 0.1 : 0.01;
  const target =
    e.key === "Home"
      ? clipStart
      : e.key === "End"
        ? clipEnd
        : current + (e.key === "ArrowLeft" ? -step : step);
  await seekTimeline(Math.max(clipStart, Math.min(clipEnd, target)));
});
function textFields() {
  return {
    text: $("overlay-text").value,
    font: $("text-font").value || "pillow-default",
    size: Number($("text-size").value),
    color: $("text-color").value,
    outline_color: $("outline-color").value,
    outline_width: Number($("outline-width").value),
    x: Number($("text-x").value),
    y: Number($("text-y").value),
    alignment: $("alignment").value,
  };
}
function storeText() {
  const cue = cues.find((c) => c.id === activeCue);
  if (cue)
    Object.assign(cue, textFields(), {
      start: clipStart + Number($("cue-start").value),
      end: clipStart + Number($("cue-end").value),
      enabled: $("cue-enabled").checked,
    });
}
function chooseCue(id) {
  activeCue = id;
  const item = cues.find((c) => c.id === id) || wholeOverlay;
  $("cue-timing").hidden = !id;
  $("overlay-text").value = item.text || "";
  $("text-font").value = item.font || "pillow-default";
  $("text-size").value = item.size || 32;
  $("text-color").value = item.color || "#ffffff";
  $("outline-color").value = item.outline_color || "#000000";
  $("outline-width").value = item.outline_width ?? 2;
  $("text-x").value = item.x ?? 0.5;
  $("text-y").value = item.y ?? 0.85;
  $("alignment").value = item.alignment || "center";
  if (id) {
    $("cue-start").value = (item.start - clipStart).toFixed(2);
    $("cue-end").value = (item.end - clipStart).toFixed(2);
    $("cue-enabled").checked = item.enabled;
  }
  $("cue-review").hidden = item.extraction !== "ocr";
  $("cue-review").textContent = item.extraction === "ocr" ? `OCR · Review words and punctuation${item.confidence != null ? ` · ${Math.round(item.confidence * 100)}% engine confidence` : ""}` : "";
  refreshCues();
}
function refreshCues() {
  $("cue-select").replaceChildren(new Option("Select text", ""));
  $("cue-track").replaceChildren();
  let row = 0;
  const laneEnds = [];
  for (const cue of cues) {
    $("cue-select").add(
      new Option(cue.text.slice(0, 45) || "New text", cue.id),
    );
    const button = document.createElement("button");
    button.textContent = `${time(cue.start - clipStart)}–${time(cue.end - clipStart)} · ${cue.text || "New text"}`;
    button.className = "cue-chip" + (activeCue === cue.id ? " active" : "");
    button.dataset.cueId = cue.id;
    button.title = button.textContent;
    const left = Math.max(0, cue.start - clipStart),
      right = Math.min(clipEnd - clipStart, cue.end - clipStart);
    if (right <= left) continue;
    let lane = laneEnds.findIndex((end) => end <= left);
    if (lane < 0) lane = laneEnds.length;
    laneEnds[lane] = right;
    row = Math.max(row, lane + 1);
    Object.assign(button.style, {
      position: "absolute",
      left: `${(100 * left) / (clipEnd - clipStart)}%`,
      width: `${(100 * (right - left)) / (clipEnd - clipStart)}%`,
      top: `${lane * 30}px`,
    });
    button.addEventListener("click", () => {
      storeText();
      chooseCue(cue.id);
      seekTimeline(Math.max(clipStart, cue.start)).catch(fail);
    });
    $("cue-track").append(button);
  }
  $("cue-track").style.height = `${row * 30}px`;
  $("text-editor").hidden = !activeCue;
  $("text-empty").hidden = Boolean(activeCue);
  $("cue-select").value = activeCue;
  $("cue-timing").hidden = !activeCue;
}
event("cue-select", "change", () => {
  const id = $("cue-select").value;
  storeText();
  chooseCue(id);
});
event("add-cue", "click", () => {
  storeText();
  const start = Math.max(
    Number($("start").value),
    Math.min(
      playbackReady
        ? mediaStart + $("video").currentTime
        : Number($("start").value),
      Number($("end").value) - 0.01,
    ),
  );
  const id = "cue_" + crypto.randomUUID().replaceAll("-", "");
  cues.push({
    ...textFields(),
    id,
    text: "",
    start,
    end: Math.min(Number($("end").value), start + 2),
    enabled: true,
    origin: "manual",
    evidence_id: null,
  });
  chooseCue(id);
  edited();
  $("overlay-text").focus();
});
event("remove-cue", "click", () => {
  cues = cues.filter((c) => c.id !== activeCue);
  chooseCue("");
  edited();
});
event("import-captions", "click", async () => {
  if (
    cues.some((c) => c.origin === "caption") &&
    !confirm(
      "Replace imported caption cues? Manual cues remain; edits to imported cues will be replaced.",
    )
  )
    return;
  await saveEdits();
  plan = await api("import_captions", {
    plan,
    track: $("caption-track").value || null,
    offset: Number($("caption-offset").value),
  });
  plan = await api("save_workspace", {workspace_id: workspaceId, plan, changes: {}});
  await loadCaptionImages();
  fillPlan();
  status("Caption import updated. Review the selected appearance and any track warning.");
});
async function loadCaptionImages() {
  captionEvidence = plan.caption_evidence_id ? await api("get_evidence", {evidence_id: plan.caption_evidence_id}) : null;
  if (captionEvidence) $("caption-track").value = captionEvidence.track;
  captionImages = (captionEvidence?.hits || []).map((hit, index) => {
    const img = new Image();
    img.src = `/media/subtitle/${captionEvidence.id}/${index}`;
    img.alt = "Original source caption";
    return img;
  });
}
event("convert-captions", "click", async () => {
  if (cues.some(c => c.origin === "caption") && !confirm("Replace converted caption text? Manual text and original images remain available.")) return;
  await saveEdits();
  status("Converting subtitle images locally. Review the recognized text when ready.");
  plan = await api("convert_captions", {plan, language: $("ocr-language").value.trim() || null});
  plan = await api("save_workspace", {workspace_id: workspaceId, plan, changes: {}});
  fillPlan();
  status("Converted with local OCR. Review the words and punctuation; source timing is preserved.");
});
function updateLiveOverlay() {
  const layer = $("live-overlay");
  layer.hidden = !plan || Boolean(mediaOverlay) || !$("empty-preview").hidden;
  if (layer.hidden) return;
  const position =
    playbackReady && !$("video").hidden
      ? mediaStart + $("video").currentTime
      : Number($("frame").value);
  const visible = [
    wholeOverlay,
    ...cues.filter(
      (c) =>
        c.enabled &&
        (c.origin !== "caption" || ($("captions-enabled").checked && $("caption-mode").value === "editable")) &&
        c.start <= position &&
        position < c.end,
    ),
  ].filter((c) => c.text);
  layer.replaceChildren();
  const screen = layer.parentElement;
  const sar = (plan.source.sample_aspect_ratio || "1:1").split(":").map(Number);
  const sourceWidth = plan.source.width * (sar[0] > 0 && sar[1] > 0 ? sar[0] / sar[1] : 1);
  const scale = Math.min(
    screen.clientWidth / sourceWidth,
    screen.clientHeight / plan.source.height,
  );
  const width = sourceWidth * scale,
    height = plan.source.height * scale;
  const renderWidth = Math.min(
    sourceWidth,
    Number($("max-width").value) ||
      { mobile: 480, share: 1280, editing: 8192 }[$("profile").value],
  );
  if ($("captions-enabled").checked && $("caption-mode").value === "original") {
    (captionEvidence?.hits || []).forEach((hit, index) => {
      if (hit.start <= position && position < hit.end) {
        const img = captionImages[index];
        Object.assign(img.style, {position: "absolute", width: `${width}px`, height: `${height}px`, left: `${(screen.clientWidth-width)/2}px`, top: `${(screen.clientHeight-height)/2}px`});
        layer.append(img);
      }
    });
  }
  for (const cue of visible) {
    const text = document.createElement("span");
    text.textContent = cue.text;
    Object.assign(text.style, {
      position: "absolute",
      left: `${(screen.clientWidth - width) / 2 + (cue.x ?? 0.5) * width}px`,
      top: `${(screen.clientHeight - height) / 2 + (cue.y ?? 0.85) * height}px`,
      fontSize: `${((cue.size || 32) * width) / renderWidth}px`,
      color: cue.color || "#ffffff",
      webkitTextStroke: `${((cue.outline_width ?? 2) * width) / renderWidth}px ${cue.outline_color || "#000000"}`,
      textAlign: cue.alignment || "center",
      transform: `translateX(${cue.alignment === "left" ? 0 : cue.alignment === "right" ? -100 : -50}%)`,
      fontFamily:
        availableFonts.find((f) => f.id === cue.font)?.name || "Arial",
    });
    layer.append(text);
  }
  if (visible.length)
    $("preview-label").textContent =
      "Live text draft · Preview edits for final appearance";
}
function updatePlaybackButton() {
  const playing = playbackReady && !$("video").paused && !$("video").ended;
  $("play-selection").textContent = playPending ? "Preparing…" : playing ? "Ⅱ Pause" : "▶ Play";
  $("play-selection").disabled = playPending;
  $("play-selection").setAttribute(
    "aria-label",
    playPending ? "Preparing selected clip" : playing ? "Pause selected clip" : "Play selected clip",
  );
}
event("video", "play", updatePlaybackButton);
event("video", "pause", updatePlaybackButton);
event("video", "ended", updatePlaybackButton);
function playbackTick() {
  constrainPlayback();
  updatePlayhead();
  const at = playbackReady
    ? mediaStart + $("video").currentTime
    : Number($("frame").value);
  document.querySelectorAll(".cue-chip").forEach((button) => {
    const cue = cues.find((c) => c.id === button.dataset.cueId);
    button.classList.toggle(
      "at-playhead",
      Boolean(cue?.enabled && cue.start <= at && at < cue.end),
    );
  });
  updateLiveOverlay();
  requestAnimationFrame(playbackTick);
}
requestAnimationFrame(playbackTick);

async function boot() {
  const params = new URLSearchParams(location.search),
    fragment = new URLSearchParams(location.hash.slice(1));
  const token = fragment.get("token");
  if (token) {
    const response = await fetch("/api/session", {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!response.ok) throw new Error("Could not open this workspace session.");
    history.replaceState(null, "", location.pathname + location.search);
  }
  availableFonts = await api("fonts");
  $("text-font").replaceChildren(
    ...availableFonts.map((f) => new Option(f.name, f.id)),
  );
  prefs = await api("preferences");
  document.documentElement.dataset.theme = prefs.appearance;
  await refreshSaved();
  view("workspace");
  if (params.get("plan"))
    await loadPlan(await api("get_plan", { plan_id: params.get("plan") }), null, false, params.get("output"));
  else if (params.get("finding")) {
    finding = await api("get_finding", { finding_id: params.get("finding") });
    showMoments();
    status("Choose a moment to review.");
  } else status("Your collection. Your cut.");
}
boot().catch(fail);


event("moment-title", "input", edited);
event("save-output-name", "click", async () => {
  if (!openedOutput) return;
  await saveEdits();
  const receipt = await api("rename_output", {
    artifact_id: openedOutput.artifact_id, title: $("moment-title").value,
  });
  openedOutput = receipt;
  $("moment-title").value = receipt.plan.title;
  $("source-title").textContent = receipt.plan.title;
  $("dirty-label").textContent = dirty ? "Saving edits…" : "All edits saved";
  await refreshSaved();
  status("Name saved. No new export needed.");
});
