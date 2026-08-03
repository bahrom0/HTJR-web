const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

const state = {
  images: [],
  currentIndex: -1,
  current: null,
  image: null,
  regions: [],
  pending: null,
  selectedIndex: -1,
  undoStack: [],
  zoom: 1,
  panX: 0,
  panY: 0,
  drawing: null,
  resizing: null,
  panning: null,
  spacePressed: false,
  dirty: false,
  saving: null,
  saveTimer: null,
  toastTimer: null,
  orientationDegrees: 0,
  deskewDegrees: 0,
  viewWidth: 1,
  viewHeight: 1,
  futureBaselineAngle: 0,
};

const canvas = $("#annotation-canvas");
const context = canvas.getContext("2d");
const canvasShell = $("#canvas-shell");

async function api(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const payload = await response.json();
      detail = payload.detail || detail;
    } catch {
      // Keep HTTP fallback.
    }
    throw new Error(detail);
  }
  const contentType = response.headers.get("content-type") || "";
  return contentType.includes("application/json") ? response.json() : response;
}

function showToast(message) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.add("visible");
  clearTimeout(state.toastTimer);
  state.toastTimer = setTimeout(() => toast.classList.remove("visible"), 3200);
}

function setSaveState(kind, label) {
  $("#save-state").dataset.state = kind;
  $("#save-label").textContent = label;
}

function snapshotEditor() {
  return {
    regions: state.regions.map((region) => ({ ...region })),
    orientationDegrees: state.orientationDegrees,
    deskewDegrees: state.deskewDegrees,
  };
}

function pushUndo() {
  state.undoStack.push(snapshotEditor());
  if (state.undoStack.length > 40) state.undoStack.shift();
  $("#undo-button").disabled = false;
}

function undo() {
  if (!state.undoStack.length) return;
  const previous = state.undoStack.pop();
  state.regions = previous.regions;
  state.orientationDegrees = previous.orientationDegrees;
  state.deskewDegrees = previous.deskewDegrees;
  updateCorrectedSize();
  state.selectedIndex = Math.min(state.selectedIndex, state.regions.length - 1);
  markDirty();
  updateCorrectionUI();
  renderRegions();
  renderCanvas();
  $("#undo-button").disabled = state.undoStack.length === 0;
}

function correctionAngle(orientation = state.orientationDegrees, deskew = state.deskewDegrees) {
  return orientation + deskew;
}

function correctedSize(angle = correctionAngle()) {
  if (!state.current) return { width: 1, height: 1 };
  const normalized = ((angle % 180) + 180) % 180;
  if (Math.abs(normalized) < 1e-9) {
    return { width: state.current.width, height: state.current.height };
  }
  if (Math.abs(normalized - 90) < 1e-9) {
    return { width: state.current.height, height: state.current.width };
  }
  const radians = (normalized * Math.PI) / 180;
  return {
    width: Math.ceil(
      Math.abs(state.current.width * Math.cos(radians)) +
        Math.abs(state.current.height * Math.sin(radians)),
    ),
    height: Math.ceil(
      Math.abs(state.current.width * Math.sin(radians)) +
        Math.abs(state.current.height * Math.cos(radians)),
    ),
  };
}

function updateCorrectedSize() {
  const size = correctedSize();
  state.viewWidth = size.width;
  state.viewHeight = size.height;
}

function originalToCorrected(point, angle) {
  const size = correctedSize(angle);
  const radians = (angle * Math.PI) / 180;
  const x = point.x - state.current.width / 2;
  const y = point.y - state.current.height / 2;
  return {
    x: x * Math.cos(radians) - y * Math.sin(radians) + size.width / 2,
    y: x * Math.sin(radians) + y * Math.cos(radians) + size.height / 2,
  };
}

function correctedToOriginal(point, angle) {
  const size = correctedSize(angle);
  const radians = (angle * Math.PI) / 180;
  const x = point.x - size.width / 2;
  const y = point.y - size.height / 2;
  return {
    x: x * Math.cos(radians) + y * Math.sin(radians) + state.current.width / 2,
    y: -x * Math.sin(radians) + y * Math.cos(radians) + state.current.height / 2,
  };
}

function transformRegionCorrection(region, previousAngle, nextAngle) {
  const transformPoint = (point) =>
    originalToCorrected(correctedToOriginal(point, previousAngle), nextAngle);
  const corners = [
    { x: region.x, y: region.y },
    { x: region.x + region.width, y: region.y },
    { x: region.x + region.width, y: region.y + region.height },
    { x: region.x, y: region.y + region.height },
  ].map(transformPoint);
  const xs = corners.map((point) => point.x);
  const ys = corners.map((point) => point.y);
  const nextSize = correctedSize(nextAngle);
  const x = Math.max(0, Math.min(...xs));
  const y = Math.max(0, Math.min(...ys));
  const right = Math.min(nextSize.width, Math.max(...xs));
  const bottom = Math.min(nextSize.height, Math.max(...ys));
  const baseline = [
    transformPoint({ x: region.x, y: region.baseline_y }),
    transformPoint({ x: region.x + region.width, y: region.baseline_y }),
  ];
  const height = Math.max(1, bottom - y);
  return {
    ...region,
    x,
    y,
    width: Math.max(1, right - x),
    height,
    baseline_y: Math.max(
      y,
      Math.min(bottom, (baseline[0].y + baseline[1].y) / 2),
    ),
  };
}

function updateCorrectionUI() {
  const total = correctionAngle();
  $("#correction-value").textContent = `${total.toFixed(1).replace(".0", "")}°`;
  $("#deskew-value").textContent = `${state.deskewDegrees.toFixed(1)}°`;
  $("#deskew-slider").value = String(state.deskewDegrees);
}

function applyCorrection(orientation, deskew) {
  if (!state.current) return;
  const normalizedOrientation = ((orientation % 360) + 360) % 360;
  const normalizedDeskew = Math.max(-15, Math.min(15, Number(deskew) || 0));
  const previousAngle = correctionAngle();
  const nextAngle = correctionAngle(normalizedOrientation, normalizedDeskew);
  if (Math.abs(previousAngle - nextAngle) < 1e-9) {
    updateCorrectionUI();
    return;
  }
  commitPending();
  pushUndo();
  state.regions = state.regions.map((region) =>
    transformRegionCorrection(region, previousAngle, nextAngle),
  );
  state.orientationDegrees = normalizedOrientation;
  state.deskewDegrees = Math.round(normalizedDeskew * 10) / 10;
  updateCorrectedSize();
  state.selectedIndex = Math.min(state.selectedIndex, state.regions.length - 1);
  state.zoom = 1;
  state.panX = 0;
  state.panY = 0;
  updateCurrentUI();
  renderRegions();
  renderCanvas();
  markDirty(120);
}

async function refreshStats() {
  const stats = await api("/api/stats");
  $("#header-annotated").textContent = stats.annotated;
  $("#header-total").textContent = stats.total;
  $("#summary-total").textContent = stats.total;
  $("#summary-annotated").textContent = stats.annotated;
  $("#summary-regions").textContent = stats.regions;
  $("#summary-pending").textContent = stats.pending;
  $("#source-count").textContent = stats.total;
}

async function refreshImages({ preserveCurrent = true } = {}) {
  const currentId = preserveCurrent ? state.current?.id : null;
  state.images = await api("/api/images?limit=2000");
  let index = currentId ? state.images.findIndex((image) => image.id === currentId) : -1;
  if (index < 0) index = state.images.findIndex((image) => image.status === "pending");
  if (index < 0 && state.images.length) index = 0;
  if (index >= 0) {
    await openImage(index);
  } else {
    state.currentIndex = -1;
    state.current = null;
    state.image = null;
    state.regions = [];
    updateCurrentUI();
    renderCanvas();
  }
  await refreshStats();
}

function loadBrowserImage(source) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = reject;
    image.src = source;
  });
}

async function openImage(index) {
  if (index < 0 || index >= state.images.length) return;
  if (state.current && state.dirty) await saveNow();
  const summary = state.images[index];
  const full = await api(`/api/images/${summary.id}`);
  const image = await loadBrowserImage(`/api/images/${summary.id}/content?v=${full.revision}`);
  state.currentIndex = index;
  state.current = full;
  state.image = image;
  state.regions = full.regions.map((region) => ({ ...region }));
  state.orientationDegrees = Number(full.metadata?.orientation_degrees || 0);
  state.deskewDegrees = Number(full.metadata?.deskew_degrees || 0);
  state.futureBaselineAngle = 0;
  updateCorrectedSize();
  state.pending = null;
  state.selectedIndex = state.regions.length ? state.regions.length - 1 : -1;
  state.undoStack = [];
  state.zoom = 1;
  state.panX = 0;
  state.panY = 0;
  state.dirty = false;
  updateCurrentUI();
  renderRegions();
  renderCanvas();
  setSaveState("saved", "Сохранено");
}

function updateCurrentUI() {
  const hasImage = Boolean(state.current);
  $("#empty-canvas").hidden = hasImage;
  $("#image-position").textContent = hasImage
    ? `${state.currentIndex + 1} / ${state.images.length}`
    : `0 / ${state.images.length}`;
  $("#image-name").textContent = hasImage ? state.current.filename : "Импортируйте фотографии";
  $("#image-dimensions").textContent = hasImage
    ? `${state.viewWidth} × ${state.viewHeight}${
        state.viewWidth !== state.current.width || state.viewHeight !== state.current.height
          ? ` · исходник ${state.current.width} × ${state.current.height}`
          : ""
      } · ${(state.current.file_size / 1024 / 1024).toFixed(1)} МБ`
    : "—";
  $("#meta-split").value = hasImage ? state.current.split : "unassigned";
  $("#meta-document").value = hasImage ? state.current.document_label : "";
  $("#meta-writer").value = hasImage ? state.current.metadata?.writer || "" : "";
  $("#meta-language").value = hasImage ? state.current.metadata?.language || "Tajik" : "Tajik";
  $("#meta-notes").value = hasImage ? state.current.notes : "";
  $("#previous-image").disabled = !hasImage || state.currentIndex <= 0;
  $("#next-image").disabled = !hasImage || state.currentIndex >= state.images.length - 1;
  $("#pending-banner").hidden = !state.pending;
  updateCorrectionUI();
  $("#future-baseline-angle").value = String(state.futureBaselineAngle);
  $("#future-baseline-value").textContent = `${state.futureBaselineAngle.toFixed(1)}°`;
}

function currentPayload() {
  return {
    regions: state.regions.map(({ x, y, width, height, baseline_y, baseline_angle, line_type }) => ({
      x,
      y,
      width,
      height,
      baseline_y,
      baseline_angle: baseline_angle || 0,
      line_type,
    })),
    split: $("#meta-split").value,
    document_label: $("#meta-document").value.trim(),
    notes: $("#meta-notes").value,
    metadata: {
      ...(state.current?.metadata || {}),
      writer: $("#meta-writer").value.trim(),
      language: $("#meta-language").value.trim() || "Tajik",
      orientation_degrees: state.orientationDegrees,
      deskew_degrees: state.deskewDegrees,
    },
    expected_revision: state.current?.revision ?? null,
  };
}

function markDirty(delay = 260) {
  if (!state.current) return;
  state.dirty = true;
  setSaveState("saving", "Изменения");
  clearTimeout(state.saveTimer);
  state.saveTimer = setTimeout(() => saveNow().catch(handleSaveError), delay);
}

function handleSaveError(error) {
  setSaveState("error", "Ошибка");
  showToast(`Не удалось сохранить: ${error.message}`);
}

async function saveNow() {
  clearTimeout(state.saveTimer);
  if (!state.current || !state.dirty) return;
  if (state.saving) {
    await state.saving;
    if (!state.dirty) return;
  }
  const imageId = state.current.id;
  const payload = currentPayload();
  state.dirty = false;
  setSaveState("saving", "Сохраняю");
  state.saving = api(`/api/images/${imageId}/annotations`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  try {
    const saved = await state.saving;
    if (state.current?.id !== imageId) return;
    const selected = state.selectedIndex;
    state.current = saved;
    state.regions = saved.regions.map((region) => ({ ...region }));
    state.selectedIndex = Math.min(selected, state.regions.length - 1);
    const summaryIndex = state.images.findIndex((image) => image.id === imageId);
    if (summaryIndex >= 0) {
      state.images[summaryIndex] = { ...saved, regions: undefined };
    }
    renderRegions();
    renderCanvas();
    setSaveState("saved", "Сохранено");
    refreshStats().catch(() => {});
  } catch (error) {
    state.dirty = true;
    throw error;
  } finally {
    state.saving = null;
  }
}

async function navigate(delta) {
  if (!state.current) return;
  commitPending();
  await saveNow();
  const target = Math.max(0, Math.min(state.images.length - 1, state.currentIndex + delta));
  if (target !== state.currentIndex) await openImage(target);
}

function transform() {
  if (!state.image) return { scale: 1, originX: 0, originY: 0 };
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  const fit = Math.min((width - 36) / state.viewWidth, (height - 36) / state.viewHeight);
  const scale = Math.max(0.01, fit * state.zoom);
  return {
    scale,
    originX: (width - state.viewWidth * scale) / 2 + state.panX,
    originY: (height - state.viewHeight * scale) / 2 + state.panY,
  };
}

function screenToImage(clientX, clientY) {
  const bounds = canvas.getBoundingClientRect();
  const { scale, originX, originY } = transform();
  return {
    x: Math.max(0, Math.min(state.viewWidth, (clientX - bounds.left - originX) / scale)),
    y: Math.max(0, Math.min(state.viewHeight, (clientY - bounds.top - originY) / scale)),
  };
}

function resizeCanvas() {
  const ratio = window.devicePixelRatio || 1;
  const width = Math.max(1, canvas.clientWidth);
  const height = Math.max(1, canvas.clientHeight);
  canvas.width = Math.round(width * ratio);
  canvas.height = Math.round(height * ratio);
  context.setTransform(ratio, 0, 0, ratio, 0, 0);
  renderCanvas();
}

function baselineEndpoints(region) {
  const inset = Math.min(Math.max(region.width * 0.02, 1), region.width / 4);
  const halfSpan = Math.max(0, region.width - 2 * inset) / 2;
  const requestedRise =
    Math.tan(((Number(region.baseline_angle) || 0) * Math.PI) / 180) * halfSpan;
  const availableRise = Math.max(
    0,
    Math.min(region.baseline_y - region.y, region.y + region.height - region.baseline_y),
  );
  const rise = Math.sign(requestedRise) * Math.min(Math.abs(requestedRise), availableRise);
  return {
    left: { x: region.x + inset, y: region.baseline_y - rise },
    right: { x: region.x + region.width - inset, y: region.baseline_y + rise },
  };
}

function regionCorners(region) {
  return {
    northwest: { x: region.x, y: region.y },
    northeast: { x: region.x + region.width, y: region.y },
    southeast: { x: region.x + region.width, y: region.y + region.height },
    southwest: { x: region.x, y: region.y + region.height },
  };
}

function drawResizeHandles(region) {
  const { scale, originX, originY } = transform();
  context.save();
  for (const [corner, point] of Object.entries(regionCorners(region))) {
    const x = originX + point.x * scale;
    const y = originY + point.y * scale;
    context.beginPath();
    context.arc(x, y, 6, 0, Math.PI * 2);
    context.fillStyle = "#101311";
    context.fill();
    context.lineWidth = 2.5;
    context.strokeStyle = "#b7f36b";
    context.stroke();
    context.beginPath();
    context.arc(x, y, 2, 0, Math.PI * 2);
    context.fillStyle = "#b7f36b";
    context.fill();
    context.closePath();
  }
  context.restore();
}

function hitResizeHandle(clientX, clientY) {
  const region = state.regions[state.selectedIndex];
  if (!region) return null;
  const bounds = canvas.getBoundingClientRect();
  const { scale, originX, originY } = transform();
  const pointer = { x: clientX - bounds.left, y: clientY - bounds.top };
  for (const [corner, point] of Object.entries(regionCorners(region))) {
    const x = originX + point.x * scale;
    const y = originY + point.y * scale;
    // The visible handle is compact, while its hit target remains forgiving.
    if (Math.hypot(pointer.x - x, pointer.y - y) <= 16) return corner;
  }
  return null;
}

function resizeSelectedRegion(corner, point, original) {
  const minimumEdge = 4;
  let left = original.x;
  let top = original.y;
  let right = original.x + original.width;
  let bottom = original.y + original.height;
  if (corner === "northwest" || corner === "southwest") {
    left = Math.min(point.x, right - minimumEdge);
  }
  if (corner === "northeast" || corner === "southeast") {
    right = Math.max(point.x, left + minimumEdge);
  }
  if (corner === "northwest" || corner === "northeast") {
    top = Math.min(point.y, bottom - minimumEdge);
  }
  if (corner === "southwest" || corner === "southeast") {
    bottom = Math.max(point.y, top + minimumEdge);
  }
  left = Math.max(0, left);
  top = Math.max(0, top);
  right = Math.min(state.viewWidth, right);
  bottom = Math.min(state.viewHeight, bottom);
  const baselineRatio = Math.max(
    0,
    Math.min(1, (original.baseline_y - original.y) / original.height),
  );
  return {
    ...original,
    x: left,
    y: top,
    width: Math.max(minimumEdge, right - left),
    height: Math.max(minimumEdge, bottom - top),
    baseline_y: top + Math.max(minimumEdge, bottom - top) * baselineRatio,
  };
}

function drawRegion(region, index, selected, pending = false) {
  const { scale, originX, originY } = transform();
  const x = originX + region.x * scale;
  const y = originY + region.y * scale;
  const width = region.width * scale;
  const height = region.height * scale;
  context.save();
  context.lineWidth = selected ? 2.5 : 1.5;
  context.strokeStyle = pending ? "#ffd166" : selected ? "#b7f36b" : "#8dc84e";
  context.fillStyle = pending ? "rgba(255, 209, 102, .12)" : "rgba(183, 243, 107, .09)";
  context.setLineDash(pending ? [8, 5] : []);
  context.fillRect(x, y, width, height);
  context.strokeRect(x, y, width, height);
  context.setLineDash([]);
  const baseline = baselineEndpoints(region);
  context.beginPath();
  context.moveTo(originX + baseline.left.x * scale, originY + baseline.left.y * scale);
  context.lineTo(originX + baseline.right.x * scale, originY + baseline.right.y * scale);
  context.strokeStyle = "#ff6b6b";
  context.lineWidth = selected ? 2 : 1.25;
  context.stroke();
  if (!pending) {
    const label = String(index + 1);
    context.font = "700 11px ui-monospace, monospace";
    const badgeWidth = Math.max(22, context.measureText(label).width + 10);
    context.fillStyle = selected ? "#b7f36b" : "#28321f";
    context.fillRect(x, y, badgeWidth, 20);
    context.fillStyle = selected ? "#17200d" : "#d9e7d5";
    context.fillText(label, x + 6, y + 14);
  }
  context.restore();
}

function renderCanvas() {
  const ratio = window.devicePixelRatio || 1;
  context.setTransform(ratio, 0, 0, ratio, 0, 0);
  context.clearRect(0, 0, canvas.clientWidth, canvas.clientHeight);
  if (!state.image || !state.current) {
    $("#zoom-fit").textContent = "100%";
    return;
  }
  const { scale, originX, originY } = transform();
  context.imageSmoothingEnabled = true;
  context.imageSmoothingQuality = "high";
  context.save();
  context.translate(
    originX + (state.viewWidth * scale) / 2,
    originY + (state.viewHeight * scale) / 2,
  );
  context.rotate((correctionAngle() * Math.PI) / 180);
  context.drawImage(
    state.image,
    -(state.current.width * scale) / 2,
    -(state.current.height * scale) / 2,
    state.current.width * scale,
    state.current.height * scale,
  );
  context.restore();
  state.regions.forEach((region, index) => drawRegion(region, index, index === state.selectedIndex));
  if (state.pending) drawRegion(state.pending, -1, true, true);
  const selected = state.regions[state.selectedIndex];
  if (selected) drawResizeHandles(selected);
  $("#zoom-fit").textContent = `${Math.round(state.zoom * 100)}%`;
}

function hitRegion(point) {
  for (let index = state.regions.length - 1; index >= 0; index -= 1) {
    const region = state.regions[index];
    if (
      point.x >= region.x &&
      point.x <= region.x + region.width &&
      point.y >= region.y &&
      point.y <= region.y + region.height
    ) {
      return index;
    }
  }
  return -1;
}

function commitPending() {
  if (!state.pending) return false;
  pushUndo();
  state.regions.push({ ...state.pending });
  state.selectedIndex = state.regions.length - 1;
  state.pending = null;
  $("#pending-banner").hidden = true;
  markDirty();
  renderRegions();
  renderCanvas();
  return true;
}

function selectRegion(index) {
  state.selectedIndex = index;
  renderRegions();
  renderCanvas();
}

function renderRegions() {
  const list = $("#region-list");
  $("#region-count").textContent = state.regions.length;
  if (!state.regions.length) {
    list.innerHTML = '<div class="empty-list">Нарисуйте первую строку</div>';
  } else {
    list.innerHTML = state.regions
      .map(
        (region, index) => `
          <button class="region-row ${index === state.selectedIndex ? "selected" : ""}" data-region="${index}">
            <span class="region-index">${index + 1}</span>
            <span>${escapeHtml(region.line_type || "DefaultLine")}</span>
            <small>${Math.round(region.width)}×${Math.round(region.height)} · ${(Number(region.baseline_angle) || 0).toFixed(1)}°</small>
          </button>`,
      )
      .join("");
    $$(".region-row").forEach((button) => {
      button.addEventListener("click", () => selectRegion(Number(button.dataset.region)));
    });
  }
  const selected = state.regions[state.selectedIndex];
  $("#region-editor").hidden = !selected;
  if (selected) {
    const ratio = Math.round(((selected.baseline_y - selected.y) / selected.height) * 100);
    $("#selected-order").textContent = `#${state.selectedIndex + 1}`;
    $("#region-type").value = selected.line_type || "DefaultLine";
    $("#baseline-slider").value = Math.max(55, Math.min(95, ratio));
    $("#baseline-value").textContent = `${ratio}%`;
  }
}

function deleteSelected() {
  if (state.selectedIndex < 0) return;
  pushUndo();
  state.regions.splice(state.selectedIndex, 1);
  state.selectedIndex = Math.min(state.selectedIndex, state.regions.length - 1);
  markDirty();
  renderRegions();
  renderCanvas();
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function changeZoom(factor, anchorX = canvas.clientWidth / 2, anchorY = canvas.clientHeight / 2) {
  if (!state.image) return;
  const before = transform();
  const imageX = (anchorX - before.originX) / before.scale;
  const imageY = (anchorY - before.originY) / before.scale;
  state.zoom = Math.max(0.25, Math.min(8, state.zoom * factor));
  const after = transform();
  state.panX += anchorX - (after.originX + imageX * after.scale);
  state.panY += anchorY - (after.originY + imageY * after.scale);
  renderCanvas();
}

canvas.addEventListener("pointerdown", (event) => {
  if (!state.current) return;
  canvas.setPointerCapture(event.pointerId);
  if (state.spacePressed || event.button === 1) {
    state.panning = { x: event.clientX, y: event.clientY, panX: state.panX, panY: state.panY };
    canvas.classList.add("panning");
    return;
  }
  if (event.button !== 0) return;
  const resizeCorner = hitResizeHandle(event.clientX, event.clientY);
  if (resizeCorner) {
    pushUndo();
    state.resizing = {
      pointerId: event.pointerId,
      corner: resizeCorner,
      original: { ...state.regions[state.selectedIndex] },
    };
    canvas.classList.add(`resizing-${resizeCorner}`);
    return;
  }
  const point = screenToImage(event.clientX, event.clientY);
  const hit = hitRegion(point);
  if (hit >= 0 && !event.shiftKey) {
    selectRegion(hit);
    return;
  }
  commitPending();
  state.drawing = { start: point, current: point };
});

canvas.addEventListener("pointermove", (event) => {
  if (state.panning) {
    state.panX = state.panning.panX + event.clientX - state.panning.x;
    state.panY = state.panning.panY + event.clientY - state.panning.y;
    renderCanvas();
    return;
  }
  if (state.resizing?.pointerId === event.pointerId) {
    const point = screenToImage(event.clientX, event.clientY);
    state.regions[state.selectedIndex] = resizeSelectedRegion(
      state.resizing.corner,
      point,
      state.resizing.original,
    );
    renderCanvas();
    return;
  }
  if (!state.drawing) {
    canvas.dataset.resizeCorner = hitResizeHandle(event.clientX, event.clientY) || "";
    return;
  }
  state.drawing.current = screenToImage(event.clientX, event.clientY);
  const x = Math.min(state.drawing.start.x, state.drawing.current.x);
  const y = Math.min(state.drawing.start.y, state.drawing.current.y);
  const width = Math.abs(state.drawing.current.x - state.drawing.start.x);
  const height = Math.abs(state.drawing.current.y - state.drawing.start.y);
  state.pending = {
    x,
    y,
    width,
    height,
    baseline_y: y + height * 0.82,
    baseline_angle: state.futureBaselineAngle,
    line_type: "DefaultLine",
  };
  renderCanvas();
});

canvas.addEventListener("pointerup", () => {
  if (state.panning) {
    state.panning = null;
    canvas.classList.remove("panning");
    return;
  }
  if (state.resizing) {
    canvas.classList.remove(`resizing-${state.resizing.corner}`);
    state.resizing = null;
    markDirty(120);
    renderRegions();
    renderCanvas();
    return;
  }
  if (!state.drawing) return;
  state.drawing = null;
  if (!state.pending || state.pending.width < 4 || state.pending.height < 4) {
    state.pending = null;
  }
  $("#pending-banner").hidden = !state.pending;
  renderCanvas();
});

canvas.addEventListener(
  "wheel",
  (event) => {
    event.preventDefault();
    const bounds = canvas.getBoundingClientRect();
    changeZoom(event.deltaY < 0 ? 1.15 : 1 / 1.15, event.clientX - bounds.left, event.clientY - bounds.top);
  },
  { passive: false },
);

canvas.addEventListener("dblclick", async (event) => {
  event.preventDefault();
  commitPending();
  await navigate(1);
});

function metadataChanged() {
  if (!state.current) return;
  markDirty(420);
}

["#meta-split", "#meta-document", "#meta-writer", "#meta-language", "#meta-notes"].forEach((selector) => {
  $(selector).addEventListener("input", metadataChanged);
  $(selector).addEventListener("change", metadataChanged);
});

$("#region-type").addEventListener("input", (event) => {
  const region = state.regions[state.selectedIndex];
  if (!region) return;
  region.line_type = event.target.value || "DefaultLine";
  markDirty(420);
  renderRegions();
  renderCanvas();
});

$("#baseline-slider").addEventListener("input", (event) => {
  const region = state.regions[state.selectedIndex];
  if (!region) return;
  const ratio = Number(event.target.value) / 100;
  region.baseline_y = region.y + region.height * ratio;
  $("#baseline-value").textContent = `${event.target.value}%`;
  markDirty(300);
  renderCanvas();
});

$("#delete-region").addEventListener("click", deleteSelected);
$("#undo-button").addEventListener("click", undo);
$("#previous-image").addEventListener("click", () => navigate(-1).catch(handleSaveError));
$("#next-image").addEventListener("click", () => navigate(1).catch(handleSaveError));
$("#zoom-in").addEventListener("click", () => changeZoom(1.2));
$("#zoom-out").addEventListener("click", () => changeZoom(1 / 1.2));
$("#zoom-fit").addEventListener("click", () => {
  state.zoom = 1;
  state.panX = 0;
  state.panY = 0;
  renderCanvas();
});
$("#rotate-left").addEventListener("click", () =>
  applyCorrection(state.orientationDegrees - 90, state.deskewDegrees),
);
$("#rotate-right").addEventListener("click", () =>
  applyCorrection(state.orientationDegrees + 90, state.deskewDegrees),
);
$("#rotation-reset").addEventListener("click", () => applyCorrection(0, 0));
$("#deskew-slider").addEventListener("input", (event) => {
  const value = Number(event.target.value);
  $("#deskew-value").textContent = `${value.toFixed(1)}°`;
  $("#correction-value").textContent =
    `${(state.orientationDegrees + value).toFixed(1).replace(".0", "")}°`;
});
$("#deskew-slider").addEventListener("change", (event) =>
  applyCorrection(state.orientationDegrees, Number(event.target.value)),
);
$("#future-baseline-angle").addEventListener("input", (event) => {
  state.futureBaselineAngle = Number(event.target.value) || 0;
  $("#future-baseline-value").textContent = `${state.futureBaselineAngle.toFixed(1)}°`;
  if (state.pending) {
    state.pending.baseline_angle = state.futureBaselineAngle;
    renderCanvas();
  }
});

async function switchView(view) {
  if (view === "dataset") {
    commitPending();
    await saveNow();
    await refreshDatasetTable();
  }
  $$(".tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.view === view));
  $("#annotate-view").classList.toggle("active", view === "annotate");
  $("#dataset-view").classList.toggle("active", view === "dataset");
  if (view === "annotate") {
    requestAnimationFrame(() => {
      // Wait one more frame after display:grid is restored. This keeps the
      // sidebars' definite height and their independent scroll containers
      // after opening an image from the dataset table.
      requestAnimationFrame(resizeCanvas);
    });
  }
}

$$(".tab").forEach((tab) => tab.addEventListener("click", () => switchView(tab.dataset.view)));

$("#import-raw").addEventListener("click", async () => {
  const button = $("#import-raw");
  const progress = $("#import-progress");
  button.disabled = true;
  progress.hidden = false;
  progress.textContent = "Сканирую raw_dataset…";
  try {
    const result = await api("/api/import/raw-dataset", { method: "POST" });
    progress.textContent = `Добавлено: ${result.imported}, уже было: ${result.existing}, пропущено: ${result.invalid}`;
    await refreshImages({ preserveCurrent: false });
    showToast("Импорт raw_dataset завершён");
  } catch (error) {
    progress.textContent = `Ошибка: ${error.message}`;
  } finally {
    button.disabled = false;
  }
});

$("#pick-folder").addEventListener("click", () => $("#folder-input").click());
$("#folder-input").addEventListener("change", async (event) => {
  const files = [...event.target.files].filter((file) => file.type.startsWith("image/"));
  if (!files.length) return;
  const progress = $("#import-progress");
  progress.hidden = false;
  let added = 0;
  for (let index = 0; index < files.length; index += 1) {
    const file = files[index];
    progress.textContent = `Импорт ${index + 1} / ${files.length}: ${file.name}`;
    try {
      const result = await api(`/api/import/file?filename=${encodeURIComponent(file.name)}`, {
        method: "POST",
        headers: { "Content-Type": file.type || "application/octet-stream" },
        body: file,
      });
      if (result.created) added += 1;
    } catch (error) {
      showToast(`${file.name}: ${error.message}`);
    }
  }
  progress.textContent = `Готово: добавлено ${added} из ${files.length}`;
  event.target.value = "";
  await refreshImages({ preserveCurrent: false });
});

async function refreshDatasetTable() {
  const filter = $("#dataset-filter").value;
  const search = $("#dataset-search").value.trim();
  const query = new URLSearchParams({ limit: "2000" });
  if (filter !== "all") query.set("status", filter);
  if (search) query.set("search", search);
  const images = await api(`/api/images?${query}`);
  const body = $("#dataset-table");
  body.innerHTML = images
    .map(
      (image) => `
      <tr data-image-id="${image.id}">
        <td>
          <div class="table-image">
            <img src="/api/images/${image.id}/content" alt="" loading="lazy" />
            <span>${escapeHtml(image.filename)}</span>
          </div>
        </td>
        <td>${image.width} × ${image.height}</td>
        <td>${image.region_count}</td>
        <td>${escapeHtml(image.split)}</td>
        <td><span class="status-chip ${image.status}">${image.status === "annotated" ? "Размечено" : "Ожидает"}</span></td>
        <td>${new Date(image.updated_at).toLocaleString("ru-RU", { dateStyle: "short", timeStyle: "short" })}</td>
      </tr>`,
    )
    .join("");
  $("#table-empty").hidden = images.length > 0;
  $$("[data-image-id]").forEach((row) => {
    row.addEventListener("click", async () => {
      const id = Number(row.dataset.imageId);
      const index = state.images.findIndex((image) => image.id === id);
      if (index >= 0) {
        await switchView("annotate");
        await openImage(index);
      }
    });
  });
  await refreshStats();
}

let searchTimer;
$("#dataset-search").addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => refreshDatasetTable().catch((error) => showToast(error.message)), 220);
});
$("#dataset-filter").addEventListener("change", () => refreshDatasetTable().catch((error) => showToast(error.message)));
$("#refresh-dataset").addEventListener("click", () => refreshDatasetTable().catch((error) => showToast(error.message)));

$("#export-dataset").addEventListener("click", async () => {
  const button = $("#export-dataset");
  button.disabled = true;
  try {
    const result = await api("/api/export", { method: "POST" });
    const container = $("#export-result");
    container.hidden = false;
    container.innerHTML = `
      Экспортировано ${result.counts.images} изображений и ${result.counts.lines} строк.
      <a href="${result.download_url}">Скачать ${escapeHtml(result.export_id)}.zip</a>
    `;
    showToast("PAGE XML экспорт готов");
  } catch (error) {
    showToast(`Экспорт не выполнен: ${error.message}`);
  } finally {
    button.disabled = false;
  }
});

window.addEventListener("keydown", (event) => {
  const editing = ["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName);
  if (event.code === "Space" && !editing) {
    state.spacePressed = true;
    event.preventDefault();
  }
  if (editing) return;
  if (event.key === "Enter") {
    event.preventDefault();
    if (!commitPending()) saveNow().catch(handleSaveError);
  } else if (event.key === "Delete" || event.key === "Backspace") {
    event.preventDefault();
    deleteSelected();
  } else if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z") {
    event.preventDefault();
    undo();
  } else if (event.key === "ArrowRight" || event.key.toLowerCase() === "n") {
    event.preventDefault();
    navigate(1).catch(handleSaveError);
  } else if (event.key === "ArrowLeft" || event.key.toLowerCase() === "p") {
    event.preventDefault();
    navigate(-1).catch(handleSaveError);
  } else if (event.key === "+" || event.key === "=") {
    changeZoom(1.2);
  } else if (event.key === "-") {
    changeZoom(1 / 1.2);
  } else if (event.key === "0") {
    state.zoom = 1;
    state.panX = 0;
    state.panY = 0;
    renderCanvas();
  } else if (event.key === "[") {
    applyCorrection(state.orientationDegrees - 90, state.deskewDegrees);
  } else if (event.key === "]") {
    applyCorrection(state.orientationDegrees + 90, state.deskewDegrees);
  } else if (event.key === "1") {
    switchView("annotate");
  } else if (event.key === "2") {
    switchView("dataset");
  }
});

window.addEventListener("keyup", (event) => {
  if (event.code === "Space") {
    state.spacePressed = false;
    state.panning = null;
    canvas.classList.remove("panning");
  }
});

window.addEventListener("beforeunload", () => {
  if (state.dirty && state.current) {
    const payload = JSON.stringify(currentPayload());
    navigator.sendBeacon(
      `/api/images/${state.current.id}/annotations`,
      new Blob([payload], { type: "application/json" }),
    );
  }
});

new ResizeObserver(resizeCanvas).observe(canvasShell);
refreshImages({ preserveCurrent: false }).catch((error) => {
  showToast(`Не удалось открыть приложение: ${error.message}`);
});
