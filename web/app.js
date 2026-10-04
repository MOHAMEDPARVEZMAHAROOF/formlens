/* FormLens frontend: analyze / batch / gallery / history. */
const $ = (s, r) => (r || document).querySelector(s);
const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.remove("hidden");
  clearTimeout(t._h);
  t._h = setTimeout(() => t.classList.add("hidden"), 4200);
}

function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g,
    c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
}

async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) {
    let msg = r.statusText;
    try { const j = await r.json(); msg = j.detail || msg; } catch (e) { /* ignore */ }
    throw new Error(msg);
  }
  return r.json();
}

/* ---------------- tabs ---------------- */
$$("nav button").forEach(b => b.addEventListener("click", () => {
  $$("nav button").forEach(x => x.classList.remove("active"));
  b.classList.add("active");
  $$(".tab").forEach(t => t.classList.remove("active"));
  $("#tab-" + b.dataset.tab).classList.add("active");
  if (b.dataset.tab === "history") loadHistory();
  if (b.dataset.tab === "gallery") loadGallery();
}));
$$("[data-goto]").forEach(b => b.addEventListener("click", () =>
  $(`nav button[data-tab="${b.dataset.goto}"]`).click()));

/* ---------------- status ---------------- */
async function refreshStatus() {
  try {
    const s = await api("/api/status");
    const b = $("#status-badge");
    const aws = s.aws && s.aws.mode === "s3" ? " · AWS S3 on" : " · local mode";
    b.textContent = `OpenCV ${esc(s.opencv)}${aws} · ${s.analyses} analyzed`;
    b.classList.add("ok");
  } catch (e) { $("#status-badge").textContent = "backend unreachable"; }
}

/* ---------------- shared renderers ---------------- */
function pillFor(value) {
  const good = ["checked", "present"].includes(value) ||
    (typeof value === "string" && /^[A-D]$/.test(value));
  const warn = value === "none";
  return `<span class="pill ${warn ? "warn" : good ? "good" : "bad"}">${esc(value)}</span>`;
}

function fieldsTable(fields) {
  if (!fields.length)
    return `<p class="muted">No fields detected. Try a clearer photo — the page edges should be visible.</p>`;
  const rows = fields.map(f => `
    <tr class="${f.ambiguous ? "amb-row" : ""}">
      <td><b>${esc(f.label)}</b><br><span class="kind">${esc(f.kind.replace("_", " "))}</span></td>
      <td>${pillFor(f.value)}${f.ambiguous ? `<span class="pill review" title="Low confidence — please verify">review</span>` : ""}</td>
      <td><div class="conf"><div class="bar"><div class="fill" style="width:${Math.round(f.confidence * 100)}%"></div></div><span class="pct">${Math.round(f.confidence * 100)}%</span></div></td>
    </tr>`).join("");
  const amb = fields.filter(f => f.ambiguous).length;
  const note = amb ? `<p class="amb-note">⚠ ${amb} field${amb > 1 ? "s" : ""} flagged for human review (low confidence) — verify before trusting.</p>` : "";
  return note + `<table class="fields"><thead><tr><th>Field</th><th>Reading</th><th>Confidence</th></tr></thead><tbody>${rows}</tbody></table>`;
}

function awsNote(aws) {
  if (aws && aws.ok)
    return `<div class="aws-note"><b>AWS S3:</b> annotated image uploaded to <span class="muted">${esc(aws.bucket)}/${esc(aws.key)}</span></div>`;
  const reason = aws && aws.reason ? esc(aws.reason) : "not configured";
  return `<div class="aws-note"><b>AWS S3:</b> ${reason} — running in local mode. Set <span class="muted">FORMLENS_S3_BUCKET</span> with AWS credentials to enable cloud upload.</div>`;
}

function resultHTML(a, opts) {
  opts = opts || {};
  const s = a.summary;
  return `
  <div class="card">
    <div class="stat-row">
      <div class="stat"><div class="n">${s.total_fields}</div><div class="l">fields detected</div></div>
      <div class="stat"><div class="n">${s.checkboxes_checked}/${s.checkboxes}</div><div class="l">checkboxes checked</div></div>
      <div class="stat"><div class="n">${s.bubble_answered}/${s.bubble_questions}</div><div class="l">bubbles answered</div></div>
      <div class="stat"><div class="n">${esc(s.signature)}</div><div class="l">signature</div></div>
    </div>
    ${s.rectified ? "" : `<p class="err">Page edges not found — analyzed without perspective correction. A straight-on photo works best.</p>`}
  </div>
  <div class="result-grid">
    <div class="card">
      <h3 style="margin-top:0">Annotated output</h3>
      <div class="annotated-wrap" data-zoom="${esc(a.annotated_url)}">
        <img src="${esc(a.annotated_url)}" alt="Annotated form">
        <div class="img-actions">
          <a class="btn small" href="${esc(a.annotated_url)}" download>Download PNG</a>
        </div>
      </div>
      ${opts.showReport === false ? "" : `<div class="mt"><a class="btn ghost small" href="/api/analyses/${a.id}/report.json" download>Export JSON report</a></div>`}
      ${awsNote(a.aws)}
    </div>
    <div class="card">
      <h3 style="margin-top:0">Per-field readings</h3>
      ${fieldsTable(a.fields)}
    </div>
  </div>`;
}

function bindZoom(scope) {
  $$("[data-zoom]", scope).forEach(el => el.addEventListener("click", e => {
    if (e.target.closest("a")) return;
    $("#lightbox-img").src = el.dataset.zoom;
    $("#lightbox").classList.remove("hidden");
  }));
}
$("#lightbox-close").addEventListener("click", () => $("#lightbox").classList.add("hidden"));
$("#lightbox").addEventListener("click", e => {
  if (e.target.id === "lightbox") $("#lightbox").classList.add("hidden");
});

/* ---------------- analyze tab ---------------- */
function setupDropzone(dzId, inputId, onFiles) {
  const dz = $(dzId), input = $(inputId);
  dz.addEventListener("click", () => input.click());
  dz.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") input.click(); });
  ["dragover", "dragenter"].forEach(ev => dz.addEventListener(ev, e => {
    e.preventDefault(); dz.classList.add("over");
  }));
  ["dragleave", "drop"].forEach(ev => dz.addEventListener(ev, e => {
    e.preventDefault(); dz.classList.remove("over");
  }));
  dz.addEventListener("drop", e => { if (e.dataTransfer.files.length) onFiles(e.dataTransfer.files); });
  input.addEventListener("change", () => { if (input.files.length) onFiles(input.files); input.value = ""; });
}

setupDropzone("#dropzone", "#file-input", files => analyzeOne(files[0]));

async function analyzeOne(file) {
  const res = $("#analyze-result");
  $("#analyze-empty").classList.add("hidden");
  res.classList.add("hidden");
  $("#analyze-loading").classList.remove("hidden");
  try {
    const fd = new FormData();
    fd.append("file", file);
    const a = await api("/api/analyze", { method: "POST", body: fd });
    res.innerHTML = `<h2 style="margin:0 0 14px">Result — ${esc(a.filename)}</h2>` + resultHTML(a);
    res.classList.remove("hidden");
    bindZoom(res);
    refreshStatus();
  } catch (e) {
    toast("Analysis failed: " + e.message);
    $("#analyze-empty").classList.remove("hidden");
  } finally {
    $("#analyze-loading").classList.add("hidden");
  }
}

/* ---------------- batch tab ---------------- */
setupDropzone("#batch-dropzone", "#batch-input", files => analyzeBatch(Array.from(files).slice(0, 20)));

async function analyzeBatch(files) {
  const res = $("#batch-result");
  $("#batch-empty").classList.add("hidden");
  res.classList.add("hidden");
  const load = $("#batch-loading");
  load.classList.remove("hidden");
  try {
    $("#batch-progress").textContent = `Uploading ${files.length} files…`;
    const fd = new FormData();
    files.forEach(f => fd.append("files", f));
    $("#batch-progress").textContent = `Analyzing ${files.length} forms…`;
    const out = await api("/api/analyze/batch", { method: "POST", body: fd });
    const rows = out.results.map(a => `
      <tr class="clickable" data-id="${a.id}">
        <td><b>${esc(a.filename)}</b></td>
        <td>${a.summary.total_fields}</td>
        <td>${a.summary.checkboxes_checked}/${a.summary.checkboxes}</td>
        <td>${a.summary.bubble_answered}/${a.summary.bubble_questions}</td>
        <td>${pillFor(a.summary.signature)}</td>
      </tr>`).join("");
    const errs = out.errors.map(e =>
      `<p class="err">${esc(e.filename)}: ${esc(e.error)}</p>`).join("");
    res.innerHTML = `
      <div class="card"><div class="stat-row">
        <div class="stat"><div class="n">${out.summary.files}</div><div class="l">forms analyzed</div></div>
        <div class="stat"><div class="n">${out.summary.total_fields}</div><div class="l">total fields</div></div>
        <div class="stat"><div class="n">${out.summary.checkboxes_checked}</div><div class="l">checkboxes checked</div></div>
        <div class="stat"><div class="n">${out.summary.failed}</div><div class="l">failed</div></div>
      </div>${errs}</div>
      <div class="card"><h3 style="margin-top:0">Per-form breakdown (click a row for detail)</h3>
      <table class="batch-table"><thead><tr><th>File</th><th>Fields</th><th>Checked</th><th>Answered</th><th>Signature</th></tr></thead>
      <tbody>${rows}</tbody></table></div>`;
    res.classList.remove("hidden");
    $$("tr.clickable", res).forEach(tr => tr.addEventListener("click", () => openDetail(+tr.dataset.id)));
    refreshStatus();
  } catch (e) {
    toast("Batch failed: " + e.message);
    $("#batch-empty").classList.remove("hidden");
  } finally {
    load.classList.add("hidden");
  }
}

async function openDetail(id) {
  try {
    const a = await api(`/api/analyses/${id}`);
    $(`nav button[data-tab="analyze"]`).click();
    const res = $("#analyze-result");
    $("#analyze-empty").classList.add("hidden");
    res.innerHTML = `<h2 style="margin:0 0 14px">Result — ${esc(a.filename)}</h2>` + resultHTML(a);
    res.classList.remove("hidden");
    bindZoom(res);
    res.scrollIntoView({ behavior: "smooth" });
  } catch (e) { toast("Could not open: " + e.message); }
}

/* ---------------- gallery ---------------- */
let galleryLoaded = false;
async function loadGallery() {
  if (galleryLoaded) return;
  galleryLoaded = true;
  try {
    const items = await api("/api/gallery");
    const grid = $("#gallery-grid");
    if (!items.length) { $("#gallery-empty").classList.remove("hidden"); return; }
    grid.innerHTML = items.map(g => {
      const t = g.truth || {};
      const truth = t.synthetic === undefined ? "" :
        `<div class="truth">Ground truth — checked: ${(t.checkboxes_checked || []).length}, ` +
        `bubbles: ${(t.bubble_answers || []).map(a => a == null ? "–" : "ABCD"[a]).join("/")}, ` +
        `signature: ${t.signature_present ? "yes" : "no"}</div>`;
      return `<div class="gcard"><img src="${esc(g.url)}" alt="${esc(g.name)}" loading="lazy">
        <div class="body"><div class="name">${esc(g.name)}</div>${truth}
        <button class="btn small" data-analyze="${esc(g.url)}" data-name="${esc(g.name)}">Analyze this form</button></div></div>`;
    }).join("");
    $$("[data-analyze]", grid).forEach(b => b.addEventListener("click", async () => {
      try {
        b.disabled = true; b.textContent = "Analyzing…";
        const blob = await (await fetch(b.dataset.analyze)).blob();
        await analyzeOne(new File([blob], b.dataset.name, { type: blob.type || "image/png" }));
        $(`nav button[data-tab="analyze"]`).click();
      } catch (e) { toast("Gallery analyze failed: " + e.message); }
      finally { b.disabled = false; b.textContent = "Analyze this form"; }
    }));
  } catch (e) { toast("Gallery failed: " + e.message); }
}

/* ---------------- history ---------------- */
async function loadHistory() {
  const p = new URLSearchParams();
  const q = $("#f-q").value.trim();
  const from = $("#f-from").value, to = $("#f-to").value, min = $("#f-min").value;
  if (q) p.set("q", q);
  if (from) p.set("from_ts", Date.parse(from + "T00:00:00") / 1000);
  if (to) p.set("to_ts", Date.parse(to + "T23:59:59") / 1000);
  if (min) p.set("min_fields", min);
  try {
    const items = await api("/api/analyses?" + p.toString());
    const list = $("#history-list");
    $("#history-empty").classList.toggle("hidden", items.length > 0);
    list.innerHTML = items.map(a => `
      <div class="hitem">
        <img src="${esc(a.annotated_url)}" data-zoom="${esc(a.annotated_url)}" alt="annotated">
        <div class="meta">
          <div class="fname">${esc(a.filename)}</div>
          <div class="sub2">${new Date(a.created_at * 1000).toLocaleString()} ·
            ${a.summary.total_fields} fields · ${a.summary.checkboxes_checked} checked ·
            ${a.summary.bubble_answered}/${a.summary.bubble_questions} answered ·
            signature ${esc(a.summary.signature)}</div>
        </div>
        <div class="actions">
          <button class="btn small ghost" data-view="${a.id}">View</button>
          <a class="btn small ghost" href="${esc(a.annotated_url)}" download>PNG</a>
          <a class="btn small ghost" href="/api/analyses/${a.id}/report.json" download>JSON</a>
          <button class="btn small ghost" data-del="${a.id}">Delete</button>
        </div>
      </div>`).join("");
    bindZoom(list);
    $$("[data-view]", list).forEach(b => b.addEventListener("click", () => openDetail(+b.dataset.view)));
    $$("[data-del]", list).forEach(b => b.addEventListener("click", async () => {
      if (!confirm("Delete this analysis?")) return;
      await api(`/api/analyses/${b.dataset.del}`, { method: "DELETE" });
      loadHistory(); refreshStatus();
    }));
  } catch (e) { toast("History failed: " + e.message); }
}
$("#f-apply").addEventListener("click", loadHistory);
$("#f-clear").addEventListener("click", () => {
  $("#f-q").value = ""; $("#f-from").value = ""; $("#f-to").value = ""; $("#f-min").value = "";
  loadHistory();
});

refreshStatus();
