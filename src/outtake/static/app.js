"use strict";
const $ = (id) => document.getElementById(id);
let mediaOverlay = null;
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

async function api(operation, args = {}) {
  const readOnly = [
    "preferences",
    "get_plan",
    "get_finding",
    "get_evidence",
    "artifact",
    "saved_outputs",
  ].includes(operation);
  if (activeJob && !readOnly)
    throw new Error(
      "An operation is already running. Wait for it to finish, or cancel it.",
    );
  if (!readOnly) document.body.classList.add("busy");
  if (!activeJob)
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
  if (mediaOverlay) {
    const clean = [...playbackCache, ...outputs].find(
      (r) =>
        r.plan.format === "mp4" &&
        !r.plan.overlay &&
        r.plan.source.sha256 === plan.source.sha256 &&
        r.plan.start <= Number($("start").value) &&
        r.plan.end >= Number($("end").value),
    );
    if (clean) showMedia(clean);
  }
  if (!$("preview-label").hidden)
    $("preview-label").textContent =
      "Preview has earlier edits · preview to update";
  $("dirty-label").textContent = "Unsaved edits";
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
  const overlay = plan.overlay || {};
  $("overlay-text").value = overlay.text || "";
  $("text-size").value = overlay.size || 32;
  $("text-color").value = overlay.color || "#ffffff";
  $("outline-color").value = overlay.outline_color || "#000000";
  $("outline-width").value = overlay.outline_width ?? 2;
  $("text-x").value = overlay.x ?? 0.5;
  $("text-y").value = overlay.y ?? 0.85;
  $("alignment").value = overlay.alignment || "center";
  $("profile").value = plan.profile;
  $("audio").checked = plan.audio === "preserve";
  setFormat(plan.format);
  dirty = false;
  $("dirty-label").textContent = "Saved plan";
  $("duration-label").textContent = `${(plan.end - plan.start).toFixed(2)}s`;
  $("cut-summary").textContent =
    `${time(plan.start)} → ${time(plan.end)} · ${(plan.end - plan.start).toFixed(2)}s`;
  history.replaceState(null, "", `/?plan=${encodeURIComponent(plan.id)}`);
}
async function saveEdits() {
  if (!dirty) return;
  const start = Number($("start").value),
    end = Number($("end").value);
  if (
    !Number.isFinite(start) ||
    !Number.isFinite(end) ||
    start < 0 ||
    end <= start ||
    end > plan.source.duration
  )
    throw new Error(
      "Choose a beginning and end inside the source, with the end after the beginning.",
    );
  let frame = Number($("frame").value);
  if (frame < start || frame >= end) frame = start;
  const text = $("overlay-text").value;
  const overlay = text
    ? {
        text,
        size: Number($("text-size").value),
        color: $("text-color").value,
        outline_color: $("outline-color").value,
        outline_width: Number($("outline-width").value),
        x: Number($("text-x").value),
        y: Number($("text-y").value),
        alignment: $("alignment").value,
      }
    : null;
  plan = await api("revise", {
    plan,
    changes: {
      start,
      end,
      frame,
      format,
      profile: $("profile").value,
      audio: format === "mp4" && $("audio").checked ? "preserve" : "mute",
      overlay,
    },
  });
  fillPlan();
  showEvidence(await api("review_frames", { plan }));
}
function showMedia(receipt) {
  $("empty-preview").hidden = true;
  $("video").pause();
  const video = receipt.plan.format === "mp4";
  playbackReady = video;
  mediaOverlay = receipt.plan.overlay;
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
async function loadPlan(value, receipt = null, preserveFinding = false) {
  receipt ||= outputs.find((output) => output.plan.id === value.id) || null;
  clipStart = value.start;
  clipEnd = value.end;
  playbackReady = false;
  mediaOverlay = null;
  plan = value;
  fillPlan();
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
async function refreshSaved() {
  outputs = await api("saved_outputs");
  $("saved-count").textContent = outputs.length;
  $("saved-grid").replaceChildren();
  if (!outputs.length) {
    const p = document.createElement("p");
    p.className = "muted";
    p.textContent =
      "Your exports will appear here. Previews stay in the workspace.";
    $("saved-grid").append(p);
  }
  [...outputs].reverse().forEach((receipt) => {
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
    edits.textContent = receipt.plan.overlay
      ? `“${receipt.plan.overlay.text}”`
      : "Original moment · no text overlay";
    const actions = document.createElement("div");
    actions.className = "card-actions";
    const open = document.createElement("button");
    open.textContent = "Open in workspace";
    open.addEventListener("click", () =>
      loadPlan(receipt.plan, receipt).catch(fail),
    );
    const download = document.createElement("a");
    download.href = `/media/export/${receipt.artifact_id}?download=1`;
    download.textContent = "Download ↗";
    download.download = `outtake.${receipt.plan.format}`;
    actions.append(open, download);
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
  const receipt = await api("render", { plan });
  await refreshSaved();
  view("saved");
  status(
    `Export ready · ${receipt.plan.format.toUpperCase()}. Your earlier outputs are preserved.`,
  );
});
event("workspace-tab", "click", () => view("workspace"));
event("saved-tab", "click", async () => {
  await refreshSaved();
  view("saved");
});
event("saved-refresh", "click", refreshSaved);
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
    edited();
  }),
);
for (const id of [
  "start",
  "end",
  "frame",
  "overlay-text",
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
  event(id, "input", edited);
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
  const cached = [...playbackCache, ...outputs].find(
    (r) =>
      r.plan.format === "mp4" &&
      !r.plan.overlay &&
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
  const start = Number($("start").value),
    end = Number($("end").value);
  if (!playbackReady || start < mediaStart || end > mediaEnd)
    await preparePlayback();
  $("video").muted = format === "gif" || !$("audio").checked;
  $("video").currentTime = start - mediaStart;
  await $("video").play();
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
  if (!playbackReady || (video.paused && !video.ended)) return;
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
  } else if (video.currentTime < start) video.currentTime = Math.max(0, start);
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
function updateLiveOverlay() {
  const overlay = $("live-overlay"),
    text = $("overlay-text").value;
  overlay.hidden =
    !plan || !text || Boolean(mediaOverlay) || !$("empty-preview").hidden;
  if (overlay.hidden) return;
  const screen = overlay.parentElement;
  const scale = Math.min(
    screen.clientWidth / plan.source.width,
    screen.clientHeight / plan.source.height,
  );
  const width = plan.source.width * scale,
    height = plan.source.height * scale;
  const renderWidth =
    $("profile").value === "share"
      ? Math.min(1280, plan.source.width)
      : plan.source.width;
  const textScale = width / renderWidth;
  overlay.textContent = text;
  overlay.style.left = `${(screen.clientWidth - width) / 2 + Number($("text-x").value) * width}px`;
  overlay.style.top = `${(screen.clientHeight - height) / 2 + Number($("text-y").value) * height}px`;
  overlay.style.fontSize = `${Number($("text-size").value) * textScale}px`;
  overlay.style.color = $("text-color").value;
  overlay.style.webkitTextStroke = `${Number($("outline-width").value) * textScale}px ${$("outline-color").value}`;
  overlay.style.textAlign = $("alignment").value;
  overlay.style.transform = `translateX(${$("alignment").value === "center" ? -50 : $("alignment").value === "right" ? -100 : 0}%)`;
  $("preview-label").textContent =
    "Live text draft · Preview edits for final appearance";
}
function playbackTick() {
  constrainPlayback();
  updatePlayhead();
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
  prefs = await api("preferences");
  document.documentElement.dataset.theme = prefs.appearance;
  await refreshSaved();
  view("workspace");
  if (params.get("plan"))
    await loadPlan(await api("get_plan", { plan_id: params.get("plan") }));
  else if (params.get("finding")) {
    finding = await api("get_finding", { finding_id: params.get("finding") });
    showMoments();
    status("Choose a moment to review.");
  } else status("Your collection. Your cut.");
}
boot().catch(fail);
