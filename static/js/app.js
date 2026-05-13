(function () {
  "use strict";

  /** Origine HTTP validă; altfel folosim căi relative (același host ca pagina). */
  function resolveApiBase() {
    const o = String(window.location.origin || "");
    if (!o || o === "null" || o.toLowerCase().startsWith("file:")) return "";
    return o;
  }

  const apiBase = resolveApiBase();
  const el = (id) => document.getElementById(id);

  /** Evită crash când un id lipsește (ex. preview incomplet). */
  function qtx(id, text) {
    const n = el(id);
    if (n) n.textContent = text == null ? "" : String(text);
  }
  function qhtml(id, html) {
    const n = el(id);
    if (n) n.innerHTML = html == null ? "" : String(html);
  }
  function qhide(id, on) {
    const n = el(id);
    if (n) n.hidden = !!on;
  }

  const setStatus = (id, text, kind = "") => {
    try {
      const box = el(id);
      if (!box) return;
      box.textContent = text == null ? "" : String(text);
      box.className = "status" + (kind ? " " + kind : "");
    } catch (e) {
      console.warn("setStatus", id, e);
    }
  };

  const apiHint = el("apiBase");
  if (apiHint) {
    apiHint.textContent = apiBase || "(același host · URL relativ)";
  }

  function apiUrl(path) {
    return (apiBase || "") + path;
  }

  /* ——— Tab-uri ——— */
  const tabIds = ["index", "search", "chat", "archive", "voice", "drive", "service"];
  function selectTab(name) {
    tabIds.forEach((id) => {
      const tab = el("tab-" + id);
      const panel = el("panel-" + id);
      if (!tab || !panel) return;
      const on = id === name;
      tab.setAttribute("aria-selected", on ? "true" : "false");
      tab.setAttribute("tabindex", on ? "0" : "-1");
      panel.classList.toggle("active", on);
      panel.hidden = !on;
    });
    history.replaceState(null, "", name === "index" ? "#" : "#" + name);
    if (name === "service") loadServicePanel();
    if (name === "voice") loadVoicePanel();
  }
  tabIds.forEach((id) => {
    const t = el("tab-" + id);
    if (t) t.addEventListener("click", () => selectTab(id));
  });
  (function initHash() {
    const h = (location.hash || "").replace(/^#/, "").trim();
    if (tabIds.includes(h)) selectTab(h);
  })();

  async function apiGet(path) {
    const r = await fetch(apiUrl(path));
    const t = await r.text();
    return { ok: r.ok, status: r.status, text: t, json: () => JSON.parse(t) };
  }

  async function apiPost(path, body) {
    const r = await fetch(apiUrl(path), {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
    const t = await r.text();
    return { ok: r.ok, status: r.status, text: t, json: () => JSON.parse(t) };
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  /** Din corpul răspunsului API la /chat (JSON cu «answer» sau text simplu). */
  function extractChatAnswerText(raw) {
    const s = String(raw || "").trim();
    if (!s) return "";
    try {
      const j = JSON.parse(s);
      if (j && typeof j.answer === "string") return String(j.answer).trim();
    } catch (_) {
      /* nu e JSON */
    }
    return s;
  }

  /** Curăță markdown ușor pentru citire vocală. */
  function textForSpeech(s) {
    let t = String(s || "");
    t = t.replace(/\*\*([^*]+)\*\*/g, "$1");
    t = t.replace(/`([^`]+)`/g, "$1");
    t = t.replace(/_{1,2}([^_\n]+)_{1,2}/g, "$1");
    t = t.replace(/^#+\s*/gm, "");
    t = t.replace(/^\s*[-*•]\s+/gm, "");
    return t.replace(/\s+/g, " ").trim();
  }

  const MAIN_INGEST_PROGRESS = {
    wrap: "mainIngestProgressWrap",
    track: "mainIngestProgressTrack",
    bar: "mainIngestProgressBar",
    lab: "mainIngestProgressLabel",
    phase: "mainIngestProgressPhase",
    cancel: "btnMainIngestCancel",
  };
  const VOICE_INGEST_PROGRESS = {
    wrap: "voiceIngestProgressWrap",
    track: "voiceIngestProgressTrack",
    bar: "voiceIngestProgressBar",
    lab: "voiceIngestProgressLabel",
    phase: "voiceIngestProgressPhase",
    cancel: "btnVoiceIngestCancel",
  };

  const ingestSession = { main: { abort: null, es: null }, voice: { abort: null, es: null } };

  function setIngestIndeterminate(cfg, on) {
    const track = el(cfg.track);
    if (track) track.classList.toggle("ingest-progress-indeterminate", !!on);
  }

  function setIngestPhase(cfg, text) {
    const box = cfg.phase ? el(cfg.phase) : null;
    if (!box) return;
    const s = text == null ? "" : String(text);
    box.textContent = s;
    box.hidden = !s;
  }

  function setIngestProgressUi(cfg, visible, pct, opts) {
    opts = opts || {};
    const wrap = el(cfg.wrap);
    const bar = el(cfg.bar);
    const lab = el(cfg.lab);
    const track = el(cfg.track);
    const indet = !!opts.indeterminate;
    if (!indet) setIngestIndeterminate(cfg, false);
    else setIngestIndeterminate(cfg, true);
    const p = Math.max(0, Math.min(100, Math.round(Number(pct) || 0)));
    if (wrap) wrap.hidden = !visible;
    if (bar && !indet) bar.style.width = p + "%";
    if (lab) lab.textContent = indet ? "…" : p + "%";
    if (track) {
      if (indet) {
        track.setAttribute("aria-busy", "true");
        track.removeAttribute("aria-valuenow");
      } else {
        track.removeAttribute("aria-busy");
        track.setAttribute("aria-valuenow", String(p));
      }
    }
  }

  function showIngestCancel(cfg, which, on) {
    const b = cfg.cancel ? el(cfg.cancel) : null;
    if (!b) return;
    const sess = ingestSession[which];
    b.hidden = !on;
    if (on) {
      b.onclick = () => {
        try {
          if (sess.abort) sess.abort();
        } catch (_) {}
        try {
          if (sess.es) sess.es.close();
        } catch (_) {}
        sess.abort = null;
        sess.es = null;
        b.hidden = true;
      };
    } else {
      b.onclick = null;
    }
  }

  /** POST multipart: progres încărcare; returnează { promise, abort }. */
  function postFormDataWithUploadProgress(url, formData, onUploadProgress) {
    let xhr;
    let sawComputable = false;
    const promise = new Promise((resolve, reject) => {
      xhr = new XMLHttpRequest();
      xhr.open("POST", url);
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) {
          sawComputable = true;
          if (typeof onUploadProgress === "function") {
            onUploadProgress((e.loaded / Math.max(e.total, 1)) * 100, { lengthComputable: true });
          }
        } else if (typeof onUploadProgress === "function") {
          onUploadProgress(0, { lengthComputable: false });
        }
      };
      xhr.upload.onloadend = () => {
        if (typeof onUploadProgress === "function" && !sawComputable) {
          onUploadProgress(100, { lengthComputable: false, uploadComplete: true });
        }
      };
      xhr.onload = () => {
        resolve({
          ok: xhr.status >= 200 && xhr.status < 300,
          status: xhr.status,
          text: xhr.responseText || "",
        });
      };
      xhr.onerror = () => reject(new Error("Rețea la încărcare"));
      xhr.onabort = () => {
        const err = new Error("Anulat.");
        err.name = "AbortError";
        reject(err);
      };
      xhr.send(formData);
    });
    return {
      promise,
      abort: () => {
        if (xhr) xhr.abort();
      },
    };
  }

  function summarizeIngestFiles(files) {
    if (!Array.isArray(files)) return "";
    const bad = files.filter((f) => f && f.status === "error");
    if (!bad.length) return "";
    return bad.map((f) => String(f.filename || "?") + ": " + String(f.detail || "")).join(" | ");
  }

  function finishIngestStatus(statusId, data) {
    const files = (data && data.files) || [];
    const errs = files.filter((x) => x && x.status === "error");
    const skipped = files.filter((x) => x && x.status === "skipped_unchanged");
    const dry = !!(data && data.dry_run);
    let line = dry ? "Simulare finalizată" : errs.length ? "Cu erori" : data && data.status === "ok" ? "OK" : "Finalizat";
    const bits = [];
    if (errs.length) bits.push("Eșuat: " + errs.map((e) => e.filename).join(", "));
    if (skipped.length) bits.push("Neschimbat (conținut identic): " + skipped.map((s) => s.filename).join(", "));
    if (bits.length) line += " — " + bits.join(" · ");
    const summ = summarizeIngestFiles(files);
    if (summ && errs.length) line += ". " + summ;
    setStatus(statusId, line, errs.length ? "bad" : "ok");
  }

  function listenIngestJobSse(jobId, basePath, onData, sess) {
    return new Promise((resolve, reject) => {
      const url = apiUrl(basePath + "/" + jobId + "/events");
      let es;
      try {
        es = new EventSource(url);
      } catch (e) {
        reject(e);
        return;
      }
      if (sess) sess.es = es;
      es.onmessage = (ev) => {
        let d = null;
        try {
          d = JSON.parse(ev.data);
        } catch {
          return;
        }
        if (typeof onData === "function") onData(d);
        if (d && d.status === "done") {
          es.close();
          if (sess) sess.es = null;
          resolve(d);
        } else if (d && d.status === "error") {
          es.close();
          if (sess) sess.es = null;
          reject(new Error(d.error || "Eroare job indexare"));
        }
      };
      es.onerror = () => {
        try {
          es.close();
        } catch (_) {}
        if (sess) sess.es = null;
        reject(new Error("Flux progres întrerupt (SSE)."));
      };
    });
  }

  async function loadServicePanel() {
    setStatus("statusService", "Încarc…");
    el("serviceChips").textContent = "";
    try {
      const [h, s] = await Promise.all([apiGet("/health"), apiGet("/status")]);
      el("outService").textContent = JSON.stringify(
        { health: h.ok ? JSON.parse(h.text) : h.text, status: s.ok ? JSON.parse(s.text) : s.text },
        null,
        2
      );
      setStatus("statusService", h.ok && s.ok ? "OK" : "Parțial / eroare", h.ok && s.ok ? "ok" : "bad");
      if (s.ok) {
        const d = JSON.parse(s.text);
        const chips = el("serviceChips");
        const a = d.archive || {};
        const dr = d.drive || {};
        const parts = [
          ["RAG (fragmente)", String(d.rag_chunks ?? "?")],
          ["LLM", String(d.llm_mode || "?")],
          ["Cheie OpenAI", d.openai_key_configured ? "setată" : "lipsește"],
          ["Arhivă", String(a.mode || "?")],
          ["Notion configurat", a.notion_configured ? "da" : "nu"],
          ["Drive activ", dr.enabled ? "da" : "nu"],
        ];
        parts.forEach(([k, v]) => {
          const span = document.createElement("span");
          span.className = "chip";
          span.textContent = k + ": " + v;
          chips.appendChild(span);
        });
        const c = document.createElement("span");
        c.className = "chip muted";
        c.textContent = "Bibliotecă: " + (d.library_dir_exists ? "folder ok" : "folder lipsă");
        chips.appendChild(c);
      }
    } catch (e) {
      setStatus("statusService", "Eroare: " + e, "bad");
    }
  }
  el("btnServiceRefresh").addEventListener("click", loadServicePanel);

  function renderSearchHits(data) {
    const host = el("outSearchHits");
    host.textContent = "";
    const results = (data && data.results) || [];
    if (!results.length) return;
    results.forEach((item, i) => {
      const md = item.metadata || {};
      const src = md.source != null ? String(md.source) : "?";
      const page = md.page != null ? " · p. " + md.page : "";
      const ch = md.chapter != null ? " · cap. " + md.chapter : "";
      const div = document.createElement("div");
      div.className = "hit";
      const meta = document.createElement("div");
      meta.className = "hit-meta";
      meta.textContent = String(i + 1) + ". " + src + page + ch;
      const tx = document.createElement("div");
      tx.className = "hit-text";
      tx.textContent = String(item.text || "").slice(0, 1600);
      div.appendChild(meta);
      div.appendChild(tx);
      host.appendChild(div);
    });
  }

  function showArchiveActions(data) {
    const row = el("archiveLinkRow");
    row.textContent = "";
    row.hidden = true;
    if (!data || !data.ok || !data.path_or_url) return;
    const p = data.path_or_url;
    const dest = data.destination || "";
    if (typeof p === "string" && (p.startsWith("http://") || p.startsWith("https://"))) {
      const a = document.createElement("a");
      a.href = p;
      a.target = "_blank";
      a.rel = "noopener";
      a.textContent = dest === "notion" ? "Deschide în Notion" : "Deschide link";
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = "Copiază URL";
      b.addEventListener("click", async () => {
        try {
          await navigator.clipboard.writeText(p);
          setStatus("statusArchive", "URL copiat.", "ok");
        } catch {
          setStatus("statusArchive", "Clipboard indisponibil.", "bad");
        }
      });
      row.appendChild(a);
      row.appendChild(b);
      row.hidden = false;
      return;
    }
    if (dest === "download" && typeof p === "string" && p.startsWith("/")) {
      const full = apiUrl(p);
      const a = document.createElement("a");
      a.href = full;
      a.target = "_blank";
      a.rel = "noopener";
      a.textContent = "Descarcă .md";
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = "Copiază URL";
      b.addEventListener("click", async () => {
        try {
          await navigator.clipboard.writeText(full);
          setStatus("statusArchive", "URL copiat.", "ok");
        } catch {
          setStatus("statusArchive", "Clipboard indisponibil.", "bad");
        }
      });
      row.appendChild(a);
      row.appendChild(b);
      row.hidden = false;
    }
  }

  el("btnSearch").addEventListener("click", async () => {
    const q = (el("searchQuery").value || "").trim();
    if (!q) {
      setStatus("statusSearch", "Scrie un termen.", "bad");
      return;
    }
    let k = parseInt(String(el("searchK").value || "8"), 10);
    if (Number.isNaN(k) || k < 1) k = 8;
    if (k > 24) k = 24;
    setStatus("statusSearch", "Caut…");
    el("outSearch").textContent = "";
    el("outSearchHits").textContent = "";
    try {
      const qs = new URLSearchParams({ q, k: String(k) });
      const r = await apiGet("/search?" + qs.toString());
      el("outSearch").textContent = r.text;
      setStatus("statusSearch", r.ok ? "OK" : "HTTP " + r.status, r.ok ? "ok" : "bad");
      if (r.ok) {
        try {
          renderSearchHits(JSON.parse(r.text));
        } catch {
          /* ignore */
        }
      }
    } catch (e) {
      setStatus("statusSearch", "Eroare: " + e, "bad");
    }
  });

  el("btnArchive").addEventListener("click", async () => {
    const title = (el("archiveTitle").value || "").trim();
    const body = (el("archiveBody").value || "").trim();
    const sub = (el("archiveSubdir").value || "").trim();
    if (!title || !body) {
      setStatus("statusArchive", "Titlu și conținut obligatorii.", "bad");
      return;
    }
    setStatus("statusArchive", "Salvez…");
    el("outArchive").textContent = "";
    el("archiveLinkRow").textContent = "";
    el("archiveLinkRow").hidden = true;
    try {
      const payload = { title, body_markdown: body };
      if (sub) payload.subdirectory = sub;
      const r = await apiPost("/archive/page", payload);
      el("outArchive").textContent = r.text;
      setStatus("statusArchive", r.ok ? "OK" : "HTTP " + r.status, r.ok ? "ok" : "bad");
      if (r.ok) {
        try {
          showArchiveActions(JSON.parse(r.text));
        } catch {
          /* ignore */
        }
      }
    } catch (e) {
      setStatus("statusArchive", "Eroare: " + e, "bad");
    }
  });

  /* ——— Drive: bulk (avansat) ——— */
  let lastDrivePropose = null;

  function renderDriveDecisions(data, hostId) {
    const host = el(hostId);
    host.innerHTML = "";
    if (!data || !Array.isArray(data.decisions) || data.decisions.length === 0) {
      return;
    }
    lastDrivePropose = data;
    const opts = data.folder_options || [];
    data.decisions.forEach((d, i) => {
      const row = document.createElement("div");
      row.className = "drive-row";
      row.dataset.idx = String(i);
      const sug = d.suggested_target_folder_id || (opts[0] && opts[0].id) || "";
      const optHtml = opts
        .map(
          (o) =>
            `<option value="${escapeHtml(o.id)}"${o.id === sug ? " selected" : ""}>${escapeHtml(
              o.name || o.id
            )}</option>`
        )
        .join("");
      row.innerHTML = `
            <label><input type="checkbox" class="drive-cb" checked /> ${escapeHtml(d.file_name || d.file_id)}</label>
            <select class="drive-sel">${optHtml}</select>
            <span class="tag">${d.needs_user ? "confirmă" : "auto"}</span>
          `;
      host.appendChild(row);
    });
  }

  el("btnDriveStatus").addEventListener("click", async () => {
    setStatus("statusDrive", "…");
    el("outDriveRaw").textContent = "";
    el("driveDecisions").innerHTML = "";
    lastDrivePropose = null;
    try {
      const r = await apiGet("/drive/status");
      el("outDriveRaw").textContent = r.text;
      setStatus("statusDrive", r.ok ? "OK" : "HTTP " + r.status, r.ok ? "ok" : "bad");
    } catch (e) {
      setStatus("statusDrive", "Eroare: " + e, "bad");
    }
  });

  el("btnDrivePropose").addEventListener("click", async () => {
    setStatus("statusDrive", "Scanare…");
    el("outDriveRaw").textContent = "";
    el("driveDecisions").innerHTML = "";
    lastDrivePropose = null;
    try {
      const r = await fetch(apiUrl("/drive/propose"), { method: "POST" });
      const t = await r.text();
      el("outDriveRaw").textContent = t;
      setStatus("statusDrive", r.ok ? "OK" : "HTTP " + r.status, r.ok ? "ok" : "bad");
      if (r.ok) {
        try {
          renderDriveDecisions(JSON.parse(t), "driveDecisions");
        } catch {
          /* ignore */
        }
      }
    } catch (e) {
      setStatus("statusDrive", "Eroare: " + e, "bad");
    }
  });

  el("btnDriveCopy").addEventListener("click", async () => {
    if (!lastDrivePropose || !lastDrivePropose.decisions) {
      setStatus("statusDrive", "Rulează mai întâi „Propune plasări”.", "bad");
      return;
    }
    const rows = el("driveDecisions").querySelectorAll(".drive-row");
    const items = [];
    rows.forEach((row) => {
      const cb = row.querySelector(".drive-cb");
      if (!cb || !cb.checked) return;
      const sel = row.querySelector(".drive-sel");
      const idx = Number(row.dataset.idx);
      const d = lastDrivePropose.decisions[idx];
      if (!d || !sel) return;
      items.push({ source_file_id: d.file_id, target_folder_id: sel.value });
    });
    if (items.length === 0) {
      setStatus("statusDrive", "Bifează cel puțin un rând.", "bad");
      return;
    }
    setStatus("statusDrive", "Copiere…");
    try {
      const ingest_to_rag = el("driveIngestRagBulk").checked;
      const r = await apiPost("/drive/copy", { items, ingest_to_rag });
      el("outDriveRaw").textContent = r.text;
      setStatus("statusDrive", r.ok ? "OK" : "HTTP " + r.status, r.ok ? "ok" : "bad");
      if (r.ok) {
        el("driveDecisions").innerHTML = "";
        lastDrivePropose = null;
      }
    } catch (e) {
      setStatus("statusDrive", "Eroare: " + e, "bad");
    }
  });

  /* ——— Drive wizard ——— */
  const wizard = {
    driveConfigured: false,
    driveOperational: false,
    stageFolderUrl: null,
    uploadedIds: null,
    folderOptionsGlobal: null,
    autoJobRunning: false,
    autoJobFinished: false,
    lastAutoPayload: null,
  };

  const pills = [1, 2, 3].map((n) => el("wizardPill" + n));

  function setWizardPillState(step, state) {
    const p = pills[step - 1];
    if (!p) return;
    p.classList.remove("done", "active");
    if (state === "done") p.classList.add("done");
    if (state === "active") p.classList.add("active");
  }

  function syncWizardChrome() {
    const s1 = wizard.driveOperational;
    [1, 2, 3].forEach((n) => setWizardPillState(n, ""));
    let active = 1;
    if (!s1) active = 1;
    else if (wizard.autoJobRunning || wizard.autoJobFinished) active = 3;
    else active = 2;

    for (let n = 1; n <= 3; n++) {
      if (n < active) setWizardPillState(n, "done");
      else if (n === active) setWizardPillState(n, "active");
    }

    const lock = (cardEl, on) => {
      if (!cardEl) return;
      cardEl.classList.toggle("locked", on);
      cardEl.classList.toggle("unlocked", !on);
    };
    lock(el("wizardCard1"), false);
    lock(el("wizardCard2"), !wizard.driveOperational);
    lock(el("wizardCardResult"), !wizard.driveOperational);
  }

  function appendManualCopySummary(okCount) {
    if (!okCount) return;
    const line = el("wizardAutoProgress");
    if (!line) return;
    const cur = (line.textContent || "").trim();
    line.textContent = cur + (cur ? " " : "") + "+" + okCount + " din copiere manuală.";
  }

  const WIZARD_UPLOAD_PROGRESS_SHARE = 0.38;
  /** Aliniat cu `WizardAutoPlaceRequest` din API (max 120 ID-uri / cerere). */
  const AUTO_PLACE_MAX_IDS = 120;
  /** Cereri HTTP paralele la încărcarea în Stage (ferestre mici, evită spike-uri). */
  const CONCURRENT_STAGE_UPLOADS = 4;

  function splitIntoMaxSizeChunks(arr, maxSize) {
    const out = [];
    const step = Math.max(1, maxSize);
    const n = arr.length;
    for (let i = 0; i < n; i += step) {
      out.push(arr.slice(i, i + step));
    }
    return out;
  }

  function setWizardPipelineState(visible, pct, label) {
    try {
      const wrap = el("wizardPipelineWrap");
      const bar = el("wizardPipelineBar");
      const lab = el("wizardPipelineLabel");
      const host = wrap && wrap.querySelector(".pipeline-progress");
      if (!wrap || !bar || !lab) {
        if (visible) setStatus("statusWizard2", "Reîncarcă pagina (lipsește bara de progres).", "bad");
        return false;
      }
      wrap.hidden = !visible;
      const p = Math.max(0, Math.min(100, Number(pct) || 0));
      bar.style.width = p + "%";
      lab.textContent = visible ? Math.round(p) + "% · " + (label || "") : label || "";
      if (host) host.setAttribute("aria-valuenow", String(Math.round(p)));
      return true;
    } catch (e) {
      console.warn("setWizardPipelineState", e);
      return false;
    }
  }

  function mergeAutoPlacePayload(merged, part) {
    if (!part || typeof part !== "object") return;
    (part.succeeded || []).forEach((x) => merged.succeeded.push(x));
    (part.needs_manual || []).forEach((x) => merged.needs_manual.push(x));
    (part.skipped || []).forEach((x) => merged.skipped.push(x));
    if (part.folder_options && part.folder_options.length) merged.folder_options = part.folder_options;
    if (typeof part.rag_chunks === "number") merged.rag_chunks = part.rag_chunks;
  }

  function renderAutoResults(data) {
    const manual = data.needs_manual || [];
    if (manual.length) {
      const mh = el("wizardManualHost");
      qhide("wizardManualSection", false);
      if (!mh) return;
      mh.innerHTML = "";
      const opts = wizard.folderOptionsGlobal || data.folder_options || [];
      wizard.folderOptionsGlobal = opts;
      manual.forEach((row) => {
        const div = document.createElement("div");
        div.className = "drive-row manual-drive-row";
        div.dataset.fileId = row.file_id;
        const optHtml = opts
          .map((o) => `<option value="${escapeHtml(o.id)}">${escapeHtml(o.name || o.id)}</option>`)
          .join("");
        div.innerHTML = `
            <div style="flex: 1 1 220px">
              <div style="font-weight: 600">${escapeHtml(row.file_name || row.file_id)}</div>
              <div class="wizard-upload-meta">${escapeHtml(row.detail || "")}</div>
            </div>
            <select class="drive-sel wizard-manual-sel" style="min-width: 220px">${optHtml}</select>
          `;
        mh.appendChild(div);
      });
    } else {
      qhide("wizardManualSection", true);
      qhtml("wizardManualHost", "");
    }
  }

  async function runAutoPlacePipeline(ids, opts) {
    if (!ids || !ids.length) return;
    const onProgress = opts && typeof opts.onProgress === "function" ? opts.onProgress : null;
    wizard.autoJobRunning = true;
    wizard.autoJobFinished = false;
    wizard.lastAutoPayload = null;
    syncWizardChrome();
    setStatus("statusWizardAuto", "Plasare automată…", "");
    qtx(
      "wizardAutoProgress",
      onProgress ? "" : "Se procesează " + ids.length + " fișier(e) în Drive…"
    );
    qhtml("wizardManualHost", "");
    qhide("wizardManualSection", true);
    setStatus("statusWizardManual", "", "");
    const ingestCh = el("wizardDriveIngestRag");
    const ingest = ingestCh ? !!ingestCh.checked : false;

    const finishOk = (data) => {
      wizard.lastAutoPayload = data;
      wizard.folderOptionsGlobal = data.folder_options || [];
      setStatus("statusWizardAuto", "Plasare finalizată.", "ok");
      renderAutoResults(data);
      qtx(
        "wizardAutoProgress",
        "Copiate automat: " +
          (data.succeeded || []).length +
          " · Manual: " +
          (data.needs_manual || []).length +
          " · Sărite (deja în memorie): " +
          (data.skipped || []).length
      );
      wizard.autoJobRunning = false;
      wizard.autoJobFinished = true;
      if (onProgress) setWizardPipelineState(true, 100, "Gata — vezi pasul 3 pentru detalii.");
      try {
        const cr = el("wizardCardResult");
        if (cr) cr.scrollIntoView({ behavior: "smooth", block: "nearest" });
      } catch {
        /* ignore */
      }
    };

    try {
      const chunks = splitIntoMaxSizeChunks(ids, AUTO_PLACE_MAX_IDS);
      const merged = {
        ok: true,
        succeeded: [],
        needs_manual: [],
        skipped: [],
        folder_options: [],
        rag_chunks: 0,
      };
      const uShare = WIZARD_UPLOAD_PROGRESS_SHARE;
      const nChunks = Math.max(1, chunks.length);
      for (let c = 0; c < chunks.length; c++) {
        const chunk = chunks[c];
        const r = await apiPost("/drive/wizard/auto-place", {
          source_file_ids: chunk,
          ingest_to_rag: ingest,
        });
        const t = r.text;
        const rawEl = el("wizardAutoRaw");
        if (rawEl) {
          rawEl.textContent = rawEl.textContent ? rawEl.textContent + "\n---\n" + t : t;
          rawEl.hidden = r.ok;
        }
        if (!r.ok) {
          const hi = uShare + (c / nChunks) * (1 - uShare);
          setStatus("statusWizardAuto", "Eroare HTTP " + r.status, "bad");
          wizard.autoJobRunning = false;
          wizard.autoJobFinished = true;
          if (onProgress) {
            onProgress(Math.min(100, hi * 100), "Eroare la plasare (HTTP " + r.status + ").");
          }
          syncWizardChrome();
          return;
        }
        mergeAutoPlacePayload(merged, JSON.parse(t));
        if (onProgress) {
          const placed = chunks.slice(0, c + 1).reduce((acc, ch) => acc + ch.length, 0);
          const hi = uShare + ((c + 1) / nChunks) * (1 - uShare);
          onProgress(hi * 100, "Plasare în bibliotecă " + placed + "/" + ids.length + "…");
        }
      }
      qtx("wizardAutoRaw", JSON.stringify(merged, null, 2));
      qhide("wizardAutoRaw", true);
      finishOk(merged);
    } catch (e) {
      setStatus("statusWizardAuto", "Eroare: " + e, "bad");
      wizard.autoJobRunning = false;
      wizard.autoJobFinished = true;
      if (onProgress) setWizardPipelineState(true, 0, "Eroare: " + e);
    }
    syncWizardChrome();
  }

  function resetWizardFlux() {
    wizard.uploadedIds = null;
    wizard.folderOptionsGlobal = null;
    wizard.autoJobRunning = false;
    wizard.autoJobFinished = false;
    wizard.lastAutoPayload = null;
    qtx("wizardUploadMeta", "");
    qhtml("wizardManualHost", "");
    qhide("wizardManualSection", true);
    qtx("wizardAutoRaw", "");
    qhide("wizardAutoRaw", true);
    qtx("wizardAutoProgress", "");
    setStatus("statusWizardAuto", "", "");
    setStatus("statusWizardManual", "", "");
    setWizardPipelineState(false, 0, "");
    const finp = el("wizardFileInput");
    if (finp) {
      try {
        finp.value = "";
      } catch {
        /* ignore */
      }
    }
    syncWizardChrome();
  }

  el("btnWizardReset").addEventListener("click", resetWizardFlux);

  el("btnWizardManualCopy").addEventListener("click", async () => {
    const mh = el("wizardManualHost");
    const rows = mh ? mh.querySelectorAll(".manual-drive-row") : [];
    const items = [];
    rows.forEach((row) => {
      const fid = row.dataset.fileId;
      const sel = row.querySelector(".wizard-manual-sel");
      if (fid && sel) items.push({ source_file_id: fid, target_folder_id: sel.value });
    });
    if (!items.length) {
      setStatus("statusWizardManual", "Nu există rânduri de copiat.", "bad");
      return;
    }
    setStatus("statusWizardManual", "Copiere…");
    try {
      const wrRag = el("wizardDriveIngestRag");
      const ingest_to_rag = !!(wrRag && wrRag.checked);
      const r = await apiPost("/drive/copy", { items, ingest_to_rag });
      if (!r.ok) {
        setStatus("statusWizardManual", "HTTP " + r.status, "bad");
        return;
      }
      const data = JSON.parse(r.text);
      const results = data.results || [];
      const okRes = results.filter((x) => x.ok);
      appendManualCopySummary(okRes.length);
      results.forEach((res) => {
        if (!res.ok || !res.source_file_id) return;
        const rowHost = el("wizardManualHost");
        if (!rowHost) return;
        const row = rowHost.querySelector('[data-file-id="' + res.source_file_id + '"]');
        if (row) row.remove();
      });
      const mhEnd = el("wizardManualHost");
      if (mhEnd && !mhEnd.children.length) qhide("wizardManualSection", true);
      setStatus("statusWizardManual", "Copiere manuală OK.", "ok");
    } catch (e) {
      setStatus("statusWizardManual", "Eroare: " + e, "bad");
    }
  });

  el("btnWizardDriveStatus").addEventListener("click", async () => {
    setStatus("statusWizard1", "…");
    const link = el("wizardStageLink");
    if (link) {
      link.hidden = true;
      link.removeAttribute("href");
    }
    try {
      const r = await apiGet("/drive/status");
      let j = null;
      try {
        j = JSON.parse(r.text);
      } catch {
        /* ignore */
      }
      wizard.driveConfigured = !!(j && j.enabled);
      const readyExplicit = j && typeof j.ready_for_api === "boolean";
      wizard.driveOperational = !!(
        j &&
        j.enabled &&
        (readyExplicit
          ? j.ready_for_api
          : !!(j.token_present && j.client_secret_present))
      );
      wizard.stageFolderUrl = (j && j.stage_folder_url) || null;
      let msg = "";
      let kind = "";
      if (!r.ok) {
        msg = "HTTP " + r.status;
        kind = "bad";
      } else if (!j || !j.enabled) {
        msg = "Drive neconfigurat pe server (.env: foldere Stage și bibliotecă).";
        kind = "";
      } else if (!wizard.driveOperational) {
        msg = j.setup_hint || "Completează OAuth (client secret + token).";
        kind = "bad";
      } else {
        msg = "Drive gata: poți încărca în Stage; plasarea automată rulează după încărcare.";
        kind = "ok";
      }
      setStatus("statusWizard1", msg, kind);
      if (link && wizard.stageFolderUrl) {
        link.href = wizard.stageFolderUrl;
        link.hidden = false;
      }
      syncWizardChrome();
    } catch (e) {
      setStatus("statusWizard1", "Eroare: " + e, "bad");
    }
  });

  const btnWizardUpload = el("btnWizardUpload");
  if (btnWizardUpload) {
    btnWizardUpload.addEventListener("click", async () => {
      const btnUp = btnWizardUpload;
      try {
        const inp = el("wizardFileInput");
        const files = inp && inp.files;
        if (!files || !files.length) {
          setStatus("statusWizard2", "Alege unul sau mai multe fișiere.", "bad");
          return;
        }
        const list = Array.from(files);
        const n = list.length;
        const uShare = WIZARD_UPLOAD_PROGRESS_SHARE;

        const bumpUpload = (iAfter) => {
          const pct = (iAfter / n) * uShare * 100;
          setWizardPipelineState(true, pct, "Încărcare în Stage " + iAfter + "/" + n + "…");
        };

        const bumpPlace = (pct, label) => {
          setWizardPipelineState(true, pct, label);
        };

        setStatus("statusWizard2", "Se încarcă fișierele…", "");
        qtx("wizardUploadMeta", "");
        wizard.uploadedIds = null;
        wizard.autoJobRunning = false;
        wizard.autoJobFinished = false;
        wizard.lastAutoPayload = null;
        qhtml("wizardManualHost", "");
        qhide("wizardManualSection", true);
        qtx("wizardAutoRaw", "");
        qhide("wizardAutoRaw", true);
        qtx("wizardAutoProgress", "");
        setStatus("statusWizardAuto", "", "");
        setWizardPipelineState(true, 0, "Pornire…");
        btnUp.disabled = true;
        const summaries = new Array(n);
        let uploadDone = 0;
        const bumpOne = () => {
          uploadDone += 1;
          bumpUpload(uploadDone);
        };
        try {
          const conc = Math.max(1, Math.min(8, CONCURRENT_STAGE_UPLOADS));
          for (let start = 0; start < n; start += conc) {
            const batch = list.slice(start, start + conc);
            await Promise.all(
              batch.map(async (file, j) => {
                const i = start + j;
                const fd = new FormData();
                fd.append("files", file);
                try {
                  const r = await fetch(apiUrl("/drive/stage/upload"), { method: "POST", body: fd });
                  const t = await r.text();
                  let parsed = null;
                  try {
                    parsed = JSON.parse(t);
                  } catch {
                    /* ignore */
                  }
                  if (!r.ok || !parsed || !parsed.files || !parsed.files.length) {
                    summaries[i] = { filename: file.name, status: "error", detail: t.slice(0, 400) };
                  } else {
                    summaries[i] = parsed.files[0];
                  }
                } catch (e) {
                  summaries[i] = { filename: file.name, status: "error", detail: String(e).slice(0, 400) };
                }
                bumpOne();
              })
            );
          }

          const okFiles = summaries.filter((x) => x && x.status === "ok" && x.file_id);
          const errFiles = summaries.filter((x) => !x || x.status !== "ok");
          setStatus(
            "statusWizard2",
            okFiles.length ? "Încărcare în Stage finalizată." : "Nicio încărcare reușită.",
            okFiles.length ? "ok" : errFiles.length ? "bad" : ""
          );

          if (!okFiles.length) {
            qtx("wizardUploadMeta", JSON.stringify({ files: summaries }, null, 2));
            setWizardPipelineState(true, 100, "Nu s-au putut încărca fișierele în Stage.");
            syncWizardChrome();
            return;
          }

          wizard.uploadedIds = okFiles.map((x) => x.file_id);
          let uploadLine =
            "Încărcate în Stage: " +
            okFiles.length +
            " " +
            (okFiles.length === 1 ? "fișier." : "fișiere.");
          if (errFiles.length) uploadLine += " Eșecuri la upload: " + errFiles.length + ".";
          if (okFiles.length > AUTO_PLACE_MAX_IDS) {
            uploadLine +=
              "\nPlasare în bibliotecă: " +
              Math.ceil(okFiles.length / AUTO_PLACE_MAX_IDS) +
              " cereri automate (max. " +
              AUTO_PLACE_MAX_IDS +
              " fișiere/cerere). Pentru mii de fișiere deja în Stage, din rădăcina proiectului: python scripts/drive_batch_auto_organize.py";
          }
          qtx("wizardUploadMeta", uploadLine);

          await runAutoPlacePipeline(wizard.uploadedIds, {
            onProgress: bumpPlace,
          });
          syncWizardChrome();
        } catch (e) {
          setStatus("statusWizard2", "Eroare: " + e, "bad");
          wizard.autoJobRunning = false;
          wizard.autoJobFinished = false;
          setWizardPipelineState(true, 0, "Eroare: " + e);
          syncWizardChrome();
        }
      } catch (err) {
        console.error("Drive wizard — încărcare:", err);
        const m = err && err.message ? err.message : String(err);
        setStatus("statusWizard2", "Eroare: " + m, "bad");
        qtx("wizardUploadMeta", "Eroare: " + m);
        wizard.autoJobRunning = false;
        wizard.autoJobFinished = false;
        try {
          syncWizardChrome();
        } catch (_) {
          /* ignore */
        }
      } finally {
        if (btnUp) btnUp.disabled = false;
      }
    });
  }

  syncWizardChrome();

  el("btnStatus").addEventListener("click", async () => {
    setStatus("statusIngest", "…");
    try {
      const r = await apiGet("/status");
      el("outIngest").textContent = r.text;
      setStatus("statusIngest", r.ok ? "OK" : "HTTP " + r.status, r.ok ? "ok" : "bad");
    } catch (e) {
      setStatus("statusIngest", "Eroare: " + e, "bad");
    }
  });

  el("btnIngest").addEventListener("click", async () => {
    const files = el("fileInput").files;
    if (!files || files.length === 0) {
      setStatus("statusIngest", "Alege fișiere.", "bad");
      return;
    }
    const dryRun = el("chkMainDryRun") && el("chkMainDryRun").checked;
    const list = Array.from(files);
    const fd = new FormData();
    list.forEach((f) => fd.append("files", f, f.name));
    fd.append("dry_run", dryRun ? "true" : "false");

    setStatus("statusIngest", "", "");
    setIngestPhase(MAIN_INGEST_PROGRESS, dryRun ? "Simulare…" : "");
    setIngestProgressUi(MAIN_INGEST_PROGRESS, true, 0, {});
    el("outIngest").textContent = "";
    const btn = el("btnIngest");
    if (btn) btn.disabled = true;
    const sess = ingestSession.main;
    sess.abort = null;
    sess.es = null;

    const cleanup = () => {
      showIngestCancel(MAIN_INGEST_PROGRESS, "main", false);
      sess.abort = null;
      sess.es = null;
      window.setTimeout(() => {
        setIngestProgressUi(MAIN_INGEST_PROGRESS, false, 0, {});
        setIngestPhase(MAIN_INGEST_PROGRESS, "");
      }, 650);
      if (btn) btn.disabled = false;
    };

    try {
      if (dryRun) {
        showIngestCancel(MAIN_INGEST_PROGRESS, "main", true);
        const up = postFormDataWithUploadProgress(apiUrl("/ingest/files"), fd, (pct, meta) => {
          const indet = meta && meta.lengthComputable === false && !meta.uploadComplete;
          setIngestPhase(MAIN_INGEST_PROGRESS, indet ? "Încărcare (fără procent)…" : "Încărcare…");
          setIngestProgressUi(MAIN_INGEST_PROGRESS, true, pct, { indeterminate: !!indet });
        });
        sess.abort = up.abort;
        const res = await up.promise;
        sess.abort = null;
        showIngestCancel(MAIN_INGEST_PROGRESS, "main", false);
        let data = null;
        try {
          data = JSON.parse(res.text);
        } catch {
          data = null;
        }
        el("outIngest").textContent = res.text;
        if (res.ok && data) finishIngestStatus("statusIngest", data);
        else setStatus("statusIngest", "HTTP " + res.status, "bad");
      } else {
        showIngestCancel(MAIN_INGEST_PROGRESS, "main", true);
        const up = postFormDataWithUploadProgress(apiUrl("/ingest/jobs"), fd, (pct, meta) => {
          const indet = meta && meta.lengthComputable === false && !meta.uploadComplete;
          setIngestPhase(MAIN_INGEST_PROGRESS, indet ? "Încărcare (fără procent)…" : "Încărcare către server…");
          setIngestProgressUi(MAIN_INGEST_PROGRESS, true, Math.min(99, pct * 0.35), { indeterminate: !!indet });
        });
        sess.abort = up.abort;
        const res = await up.promise;
        sess.abort = null;
        if (!res.ok) {
          el("outIngest").textContent = res.text;
          setStatus("statusIngest", "HTTP " + res.status + " la creare job", "bad");
          return;
        }
        let job = null;
        try {
          job = JSON.parse(res.text);
        } catch (_) {
          job = null;
        }
        const jobId = job && job.job_id ? String(job.job_id) : "";
        if (!jobId) {
          setStatus("statusIngest", "Răspuns job invalid.", "bad");
          return;
        }
        setIngestPhase(MAIN_INGEST_PROGRESS, "Indexare pe server (OCR/extragere)…");
        setIngestProgressUi(MAIN_INGEST_PROGRESS, true, 35, {});
        const finalSnap = await listenIngestJobSse(
          jobId,
          "/ingest/jobs",
          (d) => {
            const p = d.percent != null ? Number(d.percent) : 0;
            const scaled = 35 + (Math.min(100, Math.max(0, p)) / 100) * 65;
            setIngestProgressUi(MAIN_INGEST_PROGRESS, true, scaled, {});
            if (d.current_file) setIngestPhase(MAIN_INGEST_PROGRESS, "Fișier: " + d.current_file);
          },
          sess
        );
        sess.es = null;
        const result = finalSnap && finalSnap.result ? finalSnap.result : null;
        if (result) {
          el("outIngest").textContent = JSON.stringify(result, null, 2);
          finishIngestStatus("statusIngest", result);
        } else {
          setStatus("statusIngest", "Job terminat fără rezultat.", "bad");
        }
      }
    } catch (e) {
      const aborted = e && (e.name === "AbortError" || String(e.message || "").indexOf("Anulat") >= 0);
      if (aborted) setStatus("statusIngest", "Anulat.", "");
      else setStatus("statusIngest", "Eroare: " + e, "bad");
    } finally {
      setIngestProgressUi(MAIN_INGEST_PROGRESS, true, 100, {});
      cleanup();
    }
  });

  el("btnAsk").addEventListener("click", async () => {
    const msg = (el("chatMessage").value || "").trim();
    if (!msg) {
      setStatus("statusChat", "Scrie o întrebare.", "bad");
      return;
    }
    setStatus("statusChat", "Întreb…");
    el("outChat").textContent = "";
    try {
      const r = await fetch(apiUrl("/chat"), {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ message: msg, k: 8 }),
      });
      const t = await r.text();
      const display = extractChatAnswerText(t);
      el("outChat").textContent = display;
      setStatus("statusChat", r.ok ? "OK" : "HTTP " + r.status, r.ok ? "ok" : "bad");
    } catch (e) {
      setStatus("statusChat", "Eroare: " + e, "bad");
    }
  });

  function supportsSpeechRecognition() {
    return !!(window.SpeechRecognition || window.webkitSpeechRecognition);
  }

  let rec = null;
  el("btnMic").addEventListener("click", () => {
    if (!supportsSpeechRecognition()) {
      setStatus("statusChat", "Dictarea nu e disponibilă în acest browser.", "bad");
      return;
    }
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    rec = new SR();
    rec.lang = "ro-RO";
    rec.interimResults = true;
    rec.continuous = false;
    let finalText = "";
    rec.onresult = (ev) => {
      let interim = "";
      for (let i = ev.resultIndex; i < ev.results.length; i++) {
        const txt = ev.results[i][0].transcript;
        if (ev.results[i].isFinal) finalText += txt;
        else interim += txt;
      }
      el("chatMessage").value = (finalText + " " + interim).trim();
    };
    rec.onerror = (e) => setStatus("statusChat", "Mic: " + e.error, "bad");
    rec.onstart = () => setStatus("statusChat", "Ascult…");
    rec.onend = () => setStatus("statusChat", "Dictare oprită.", "ok");
    rec.start();
  });

  function speak(text) {
    if (!("speechSynthesis" in window)) {
      setStatus("statusChat", "Sinteză vocală indisponibilă.", "bad");
      return;
    }
    window.speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(textForSpeech(text));
    u.lang = "ro-RO";
    u.rate = 1.02;
    window.speechSynthesis.speak(u);
  }

  el("btnSpeak").addEventListener("click", () => {
    const raw = el("outChat").textContent || "";
    const ans = extractChatAnswerText(raw);
    if (!ans) {
      setStatus("statusChat", "Nu am răspuns de citit.", "bad");
      return;
    }
    speak(ans);
  });

  async function loadVoiceOcrStatus() {
    try {
      const r = await apiGet("/voice-library/ocr-status");
      let j = null;
      try {
        j = JSON.parse(r.text);
      } catch {
        /* ignore */
      }
      if (!r.ok || !j) {
        setStatus("statusVoiceOcr", "HTTP " + r.status + " la stare OCR.", "bad");
        return;
      }
      if (j.ok) {
        setStatus(
          "statusVoiceOcr",
          "OCR disponibil: " +
            (j.tesseract_path || "tesseract") +
            " · versiune " +
            (j.tesseract_version || "?") +
            " · limbi " +
            (j.ocr_lang || "?") +
            " · poppler " +
            (j.poppler_path || "?") +
            ".",
          "ok"
        );
      } else {
        setStatus(
          "statusVoiceOcr",
          "OCR indisponibil: " + (j.detail || "necunoscut") + (j.hint ? " — " + j.hint : ""),
          "bad"
        );
      }
    } catch (e) {
      setStatus("statusVoiceOcr", "Eroare: " + e, "bad");
    }
  }

  async function refreshVoiceSources() {
    const sel = el("voiceSourceSelect");
    if (!sel) return;
    const cur = sel.value;
    sel.innerHTML = "";
    const opt0 = document.createElement("option");
    opt0.value = "";
    opt0.textContent = "— alege cartea (sursa din index) —";
    sel.appendChild(opt0);
    try {
      const r = await apiGet("/voice-library/sources");
      if (!r.ok) {
        setStatus("statusVoiceIngest", "HTTP " + r.status + " la /voice-library/sources", "bad");
        return;
      }
      const data = JSON.parse(r.text);
      const items = data.sources || [];
      items.forEach((row) => {
        const o = document.createElement("option");
        o.value = String(row.source || "");
        const label = row.book_label || row.source || o.value;
        const tag = row.scanned_pdf || row.voice_shelf ? " · scan" : "";
        o.textContent = label + " (" + String(row.chunks || 0) + " frag.)" + tag;
        sel.appendChild(o);
      });
      if (cur && Array.from(sel.options).some((x) => x.value === cur)) sel.value = cur;
    } catch (e) {
      setStatus("statusVoiceIngest", "Eroare la surse: " + e, "bad");
    }
  }

  async function loadVoicePanel() {
    await loadVoiceOcrStatus();
    await refreshVoiceSources();
  }

  async function voiceAskChat() {
    const srcEl = el("voiceSourceSelect");
    const qEl = el("voiceQuestionText");
    const source = srcEl && srcEl.value ? String(srcEl.value) : "";
    const msg = qEl ? String(qEl.value || "").trim() : "";
    if (!source) {
      setStatus("statusVoiceChat", "Alege cartea din listă (metadata «source»).", "bad");
      return;
    }
    if (!msg) {
      setStatus("statusVoiceChat", "Scrie o întrebare sau folosește microfonul.", "bad");
      return;
    }
    setStatus("statusVoiceChat", "Întreb…");
    const out = el("outVoiceChat");
    if (out) out.textContent = "";
    try {
      const r = await fetch(apiUrl("/chat"), {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ message: msg, k: 10, source: source }),
      });
      const t = await r.text();
      const display = extractChatAnswerText(t);
      if (out) out.textContent = display;
      setStatus("statusVoiceChat", r.ok ? "OK" : "HTTP " + r.status, r.ok ? "ok" : "bad");
    } catch (e) {
      setStatus("statusVoiceChat", "Eroare: " + e, "bad");
    }
  }

  let voiceRec = null;

  function setVoiceListeningUi(on, label) {
    const btn = el("btnVoiceMic");
    const banner = el("voiceListenBanner");
    const lab = el("voiceListenLabel");
    if (btn) btn.classList.toggle("voice-mic-on", !!on);
    if (banner) banner.hidden = !on;
    if (lab && label) lab.textContent = label;
  }

  /** Browsere Chromium trimit audio la Google pentru transcriere; pe http://+IP din rețea e deseori blocată. */
  function getVoiceSpeechOriginBlockMessage() {
    if (typeof window === "undefined") return null;
    if (typeof window.isSecureContext !== "boolean") return null;
    if (window.isSecureContext) return null;
    const h = String((window.location && window.location.hostname) || "").toLowerCase();
    if (h === "localhost" || h === "127.0.0.1" || h === "::1") return null;
    return (
      "Pagina e pe HTTP într-un context nesigur (ex. http://192.168… sau alt IP). " +
      "Dictarea în browser (Chromium) folosește un serviciu în cloud care de obicei nu merge așa. " +
      "Deschide aplicația la http://127.0.0.1:PORT (același PC) sau pune în față HTTPS (reverse proxy / tunel)."
    );
  }

  function voiceMicErrorMessage(code) {
    if (code === "network") {
      const secure =
        typeof window !== "undefined" &&
        window.isSecureContext &&
        String((window.location && window.location.protocol) || "").toLowerCase() === "https:";
      const h = String((window.location && window.location.hostname) || "").toLowerCase();
      const loopback = h === "localhost" || h === "127.0.0.1" || h === "::1";
      const base =
        "Transcrierea vocală (dictare) rulează în browser prin serviciul Google din cloud — nu depinde de serverul unde e găzduită aplicația. ";
      if (!secure && !loopback) {
        return (
          base +
          "Pagina nu e într-un context sigur (ex. http pe IP public). Folosește https:// cu certificat valid. Apoi verifică internet, VPN; în Brave: Shields down pentru acest site."
        );
      }
      return (
        base +
        "Dacă tot vezi asta pe https, cauza e aproape mereu la client: rețea/VPN/firewall care blochează Google, sau Brave Shields (lion → Shields down). Încearcă din nou «Întreabă cu vocea»."
      );
    }
    const m = {
      "not-allowed":
        "Microfon refuzat. În bara de adresă: setări site → Microfon: Permite. Folosește https:// sau localhost. (Brave: verifică și Shields pentru acest site.)",
      "service-not-allowed":
        "Microfon / serviciu vocal blocat. Folosește https:// sau localhost și permisiunile site-ului. În Brave, Shields poate bloca serviciul de transcriere din cloud.",
      "no-speech":
        "Browserul a semnalat «no-speech» (fără voce detectată spre serviciul de transcriere). Verifică microfonul implicit în OS, vorbește după «Canal audio pornit», sau apasă Stop dacă ai terminat.",
      "audio-capture": "Nu pot deschide microfonul (altă aplicație îl folosește sau lipsește dispozitivul).",
      aborted: "",
    };
    return Object.prototype.hasOwnProperty.call(m, code) ? m[code] : "Mic: " + code;
  }

  function speakVoiceAnswer() {
    const raw = el("outVoiceChat") ? el("outVoiceChat").textContent || "" : "";
    if (!("speechSynthesis" in window)) {
      setStatus("statusVoiceChat", "Sinteză vocală indisponibilă în acest browser.", "bad");
      return;
    }
    const ans = extractChatAnswerText(raw);
    if (!ans) {
      setStatus("statusVoiceChat", "Nu am răspuns de citit.", "bad");
      return;
    }
    window.speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(textForSpeech(ans));
    u.lang = "ro-RO";
    u.rate = 1.02;
    window.speechSynthesis.speak(u);
  }

  const btnVoiceIngest = el("btnVoiceIngest");
  if (btnVoiceIngest) {
    btnVoiceIngest.addEventListener("click", async () => {
      const inp = el("voicePdfInput");
      const files = inp && inp.files;
      if (!files || !files.length) {
        setStatus("statusVoiceIngest", "Alege cel puțin un PDF.", "bad");
        return;
      }
      const dryRun = el("chkVoiceDryRun") && el("chkVoiceDryRun").checked;
      const bl = el("voiceBookLabel");
      const fo = el("voiceForceOcr");
      const list = Array.from(files);
      const fd = new FormData();
      list.forEach((f) => fd.append("files", f, f.name));
      fd.append("book_label", bl ? String(bl.value || "").trim() : "");
      fd.append("force_ocr", fo && fo.value ? String(fo.value) : "auto");
      fd.append("dry_run", dryRun ? "true" : "false");

      setStatus("statusVoiceIngest", "", "");
      setIngestPhase(VOICE_INGEST_PROGRESS, dryRun ? "Simulare…" : "");
      setIngestProgressUi(VOICE_INGEST_PROGRESS, true, 0, {});
      const out = el("outVoiceIngest");
      if (out) out.textContent = "";
      const btn = btnVoiceIngest;
      if (btn) btn.disabled = true;
      const sess = ingestSession.voice;
      sess.abort = null;
      sess.es = null;

      const cleanup = () => {
        showIngestCancel(VOICE_INGEST_PROGRESS, "voice", false);
        sess.abort = null;
        sess.es = null;
        window.setTimeout(() => {
          setIngestProgressUi(VOICE_INGEST_PROGRESS, false, 0, {});
          setIngestPhase(VOICE_INGEST_PROGRESS, "");
        }, 650);
        if (btn) btn.disabled = false;
      };

      try {
        if (dryRun) {
          showIngestCancel(VOICE_INGEST_PROGRESS, "voice", true);
          const up = postFormDataWithUploadProgress(apiUrl("/voice-library/ingest"), fd, (pct, meta) => {
            const indet = meta && meta.lengthComputable === false && !meta.uploadComplete;
            setIngestPhase(VOICE_INGEST_PROGRESS, indet ? "Încărcare (fără procent)…" : "Încărcare…");
            setIngestProgressUi(VOICE_INGEST_PROGRESS, true, pct, { indeterminate: !!indet });
          });
          sess.abort = up.abort;
          const res = await up.promise;
          sess.abort = null;
          showIngestCancel(VOICE_INGEST_PROGRESS, "voice", false);
          let data = null;
          try {
            data = JSON.parse(res.text);
          } catch {
            data = null;
          }
          if (out) out.textContent = res.text;
          if (res.ok && data) finishIngestStatus("statusVoiceIngest", data);
          else setStatus("statusVoiceIngest", "HTTP " + res.status, "bad");
        } else {
          showIngestCancel(VOICE_INGEST_PROGRESS, "voice", true);
          const up = postFormDataWithUploadProgress(apiUrl("/voice-library/jobs"), fd, (pct, meta) => {
            const indet = meta && meta.lengthComputable === false && !meta.uploadComplete;
            setIngestPhase(VOICE_INGEST_PROGRESS, indet ? "Încărcare (fără procent)…" : "Încărcare către server…");
            setIngestProgressUi(VOICE_INGEST_PROGRESS, true, Math.min(99, pct * 0.35), { indeterminate: !!indet });
          });
          sess.abort = up.abort;
          const res = await up.promise;
          sess.abort = null;
          if (!res.ok) {
            if (out) out.textContent = res.text;
            setStatus("statusVoiceIngest", "HTTP " + res.status + " la creare job", "bad");
            return;
          }
          let job = null;
          try {
            job = JSON.parse(res.text);
          } catch (_) {
            job = null;
          }
          const jobId = job && job.job_id ? String(job.job_id) : "";
          if (!jobId) {
            setStatus("statusVoiceIngest", "Răspuns job invalid.", "bad");
            return;
          }
          setIngestPhase(VOICE_INGEST_PROGRESS, "OCR și indexare pe server…");
          setIngestProgressUi(VOICE_INGEST_PROGRESS, true, 35, {});
          const finalSnap = await listenIngestJobSse(
            jobId,
            "/voice-library/jobs",
            (d) => {
              const p = d.percent != null ? Number(d.percent) : 0;
              const scaled = 35 + (Math.min(100, Math.max(0, p)) / 100) * 65;
              setIngestProgressUi(VOICE_INGEST_PROGRESS, true, scaled, {});
              if (d.current_file) setIngestPhase(VOICE_INGEST_PROGRESS, "Fișier: " + d.current_file);
            },
            sess
          );
          sess.es = null;
          const result = finalSnap && finalSnap.result ? finalSnap.result : null;
          if (result) {
            if (out) out.textContent = JSON.stringify(result, null, 2);
            finishIngestStatus("statusVoiceIngest", result);
            const ok = !(result.files || []).some((x) => x && x.status === "error");
            if (ok) await refreshVoiceSources();
          } else {
            setStatus("statusVoiceIngest", "Job terminat fără rezultat.", "bad");
          }
        }
      } catch (e) {
        const aborted = e && (e.name === "AbortError" || String(e.message || "").indexOf("Anulat") >= 0);
        if (aborted) setStatus("statusVoiceIngest", "Anulat.", "");
        else setStatus("statusVoiceIngest", "Eroare: " + e, "bad");
      } finally {
        setIngestProgressUi(VOICE_INGEST_PROGRESS, true, 100, {});
        cleanup();
      }
    });
  }

  const btnVoiceRefresh = el("btnVoiceRefreshSources");
  if (btnVoiceRefresh) btnVoiceRefresh.addEventListener("click", () => refreshVoiceSources());

  const btnVoiceDeleteFromRag = el("btnVoiceDeleteFromRag");
  if (btnVoiceDeleteFromRag) {
    btnVoiceDeleteFromRag.addEventListener("click", async () => {
      const sel = el("voiceSourceSelect");
      const source = sel && sel.value ? String(sel.value).trim() : "";
      if (!source) {
        setStatus("statusVoiceChat", "Alege cartea din listă înainte de ștergere din index.", "bad");
        return;
      }
      const opt = sel && sel.selectedIndex >= 0 ? sel.options[sel.selectedIndex] : null;
      const label = opt ? String(opt.textContent || source) : source;
      const msg =
        "Sigur vrei să ștergi din index (RAG) toate fragmentele pentru:\n\n" +
        label +
        "\n\nAcțiunea nu poate fi anulată. Fișierul PDF din folderul de upload nu se șterge — doar intrările din Chroma pentru această sursă.";
      if (!window.confirm(msg)) return;
      setStatus("statusVoiceChat", "Șterg din index…", "");
      const outChat = el("outVoiceChat");
      try {
        const url = apiUrl("/voice-library/index") + "?source=" + encodeURIComponent(source);
        const r = await fetch(url, { method: "DELETE" });
        const t = await r.text();
        let detail = t;
        try {
          const j = JSON.parse(t);
          if (r.ok) {
            detail =
              "Șterse " +
              String(j.deleted_chunks != null ? j.deleted_chunks : "?") +
              " fragment(e). În tot indexul au rămas " +
              String(j.rag_chunks != null ? j.rag_chunks : "?") +
              " fragment(e).";
          }
        } catch (_) {
          /* corp brut */
        }
        setStatus("statusVoiceChat", r.ok ? detail : "HTTP " + r.status + ": " + t, r.ok ? "ok" : "bad");
        if (outChat) outChat.textContent = "";
        if (r.ok) await refreshVoiceSources();
        if (sel && r.ok) sel.value = "";
      } catch (e) {
        setStatus("statusVoiceChat", "Eroare: " + e, "bad");
      }
    });
  }

  const btnVoiceAsk = el("btnVoiceAsk");
  if (btnVoiceAsk) btnVoiceAsk.addEventListener("click", () => voiceAskChat());

  const btnVoiceMic = el("btnVoiceMic");
  /** Dictare: browserul poate închide singur după tăcere — legăm sesiuni până la Stop. */
  const voiceDict = {
    active: false,
    userStop: false,
    chain: 0,
    buf: "",
    /** Ultimul text afișat din onresult; la Stop uneori lipsește ultimul eveniment — folosim asta la trimitere. */
    lastMerged: "",
    maxChain: 120,
    networkFail: 0,
    maxNetworkRetries: 6,
    noSpeechStreak: 0,
    maxNoSpeechStreak: 40,
  };

  function getVoiceQuestionForSubmit() {
    const box = el("voiceQuestionText");
    const fromBox = box ? String(box.value || "").trim() : "";
    const fallback = String(voiceDict.lastMerged || "").trim() || String(voiceDict.buf || "").trim();
    const q = fromBox || fallback;
    if (box && q && !fromBox) box.value = q;
    return q;
  }

  /** Sfat scurt după Stop fără text (Brave include „Chrome” în UA — testăm Brave primul). */
  function voiceStopEmptyHint() {
    const ua = (typeof navigator !== "undefined" && navigator.userAgent) || "";
    if (/Brave/i.test(ua)) {
      return "Încearcă Shields relaxat pentru site, microfon permis, apoi o mică pauză după ultimul cuvânt înainte de Stop.";
    }
    if (/Edg/i.test(ua)) {
      return "Verifică permisiunea pentru microfon; așteaptă puțin după ultimul cuvânt înainte de Stop.";
    }
    if (/Chrom/i.test(ua)) {
      return "Chrome poate întârzia ultimul fragment — așteaptă ~1 s după ce vorbești; verifică intrarea de microfon în OS.";
    }
    return "Așteaptă puțin după ultimul cuvânt înainte de Stop; verifică microfonul în setările sistemului.";
  }

  function triggerVoiceStop(processingMsg) {
    voiceDict.userStop = true;
    if (voiceRec) {
      try {
        voiceRec.stop();
      } catch (_) {
        /* ignore */
      }
      if (processingMsg) setStatus("statusVoiceChat", processingMsg, "ok");
      return;
    }
    if (!voiceDict.active) {
      setVoiceListeningUi(false);
      setStatus("statusVoiceChat", "Dictarea nu era activă (afișaj microfon resetat).", "");
      voiceDict.userStop = false;
      return;
    }
    /* voiceRec e deja null (pauză între segmente sau imediat după stop): lasă mai întâi onend să ruleze, apoi finalizează dacă tot e blocat. */
    window.setTimeout(() => {
      if (!voiceDict.userStop) return;
      if (!voiceDict.active) {
        voiceDict.userStop = false;
        return;
      }
      voiceDict.active = false;
      setVoiceListeningUi(false);
      const finalize = () => {
        const q = getVoiceQuestionForSubmit();
        voiceDict.userStop = false;
        voiceDict.buf = "";
        voiceDict.lastMerged = "";
        voiceDict.chain = 0;
        voiceDict.networkFail = 0;
        voiceDict.noSpeechStreak = 0;
        if (q) {
          setStatus("statusVoiceChat", "Trimit întrebarea…", "ok");
          voiceAskChat();
        } else {
          setStatus(
            "statusVoiceChat",
            "N-am prins text din dictare. Verifică cartea din listă. " + voiceStopEmptyHint() + " Reporne «Întreabă cu vocea» sau scrie întrebarea.",
            "bad"
          );
        }
      };
      let attempt2 = 0;
      function scheduleFinalizeRetry() {
        const delay = attempt2 === 0 ? 0 : attempt2 === 1 ? 300 : 350;
        window.setTimeout(() => {
          if (getVoiceQuestionForSubmit()) {
            finalize();
            return;
          }
          attempt2 += 1;
          if (attempt2 < 3) scheduleFinalizeRetry();
          else finalize();
        }, delay);
      }
      scheduleFinalizeRetry();
    }, 0);
  }

  /** @param {{ skipChainIncrement?: boolean }} [opts] */
  function startVoiceListeningChain(opts) {
    opts = opts || {};
    if (!voiceDict.active || voiceDict.userStop) return;
    if (voiceDict.chain >= voiceDict.maxChain) {
      voiceDict.active = false;
      setVoiceListeningUi(false);
      voiceRec = null;
      voiceDict.networkFail = 0;
      voiceDict.noSpeechStreak = 0;
      setStatus(
        "statusVoiceChat",
        "Ascultare oprită automat (prea multe reporniri fără text nou). Apasă din nou «Întreabă cu vocea» sau scrie întrebarea.",
        "bad"
      );
      return;
    }
    if (!opts.skipChainIncrement) voiceDict.chain += 1;
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    const rec = new SR();
    voiceRec = rec;
    rec.lang = "ro-RO";
    rec.interimResults = true;
    rec.continuous = false;
    rec.maxAlternatives = 1;

    rec.onresult = (ev) => {
      voiceDict.networkFail = 0;
      voiceDict.noSpeechStreak = 0;
      let interim = "";
      for (let i = ev.resultIndex; i < ev.results.length; i++) {
        const txt = ev.results[i][0].transcript;
        if (ev.results[i].isFinal) voiceDict.buf += txt;
        else interim += txt;
      }
      const box = el("voiceQuestionText");
      const merged = (voiceDict.buf + (interim ? (voiceDict.buf ? " " : "") + interim : "")).trim();
      voiceDict.lastMerged = merged;
      if (merged) voiceDict.chain = 0;
      if (box) box.value = merged;
      setVoiceListeningUi(
        true,
        interim
          ? "Te aud — transcriu… (apasă Stop când ai terminat)"
          : voiceDict.buf
            ? "Fragment înregistrat — continuă sau Stop."
            : "Aștept să vorbești…"
      );
    };

    rec.onerror = (e) => {
      if (e.error === "aborted") return;
      /* no-speech după Stop: nu reseta sesiunea înainte de onend */
      if (e.error === "no-speech" && voiceDict.userStop) {
        voiceRec = null;
        return;
      }
      if (e.error === "no-speech" && !voiceDict.active) {
        voiceRec = null;
        return;
      }
      if (e.error === "no-speech" && voiceDict.active && !voiceDict.userStop) {
        voiceDict.noSpeechStreak += 1;
        if (voiceDict.noSpeechStreak >= voiceDict.maxNoSpeechStreak) {
          voiceRec = null;
          voiceDict.active = false;
          voiceDict.noSpeechStreak = 0;
          setVoiceListeningUi(false);
          setStatus(
            "statusVoiceChat",
            "Nu detectez voce transcrisă după multe încercări. Verifică: microfonul implicit în OS (Chrome folosește intrarea aleasă acolo), volumul, că nu vorbești în alt dispozitiv; vorbește după ce apare «Canal audio pornit». Sau scrie întrebarea.",
            "bad"
          );
          return;
        }
        setVoiceListeningUi(true, "Nu s-a auzit voce — reîncerc automat… vorbește sau apasă Stop.");
        if (voiceDict.noSpeechStreak === 1 || voiceDict.noSpeechStreak % 8 === 0) {
          setStatus(
            "statusVoiceChat",
            "Încă ascult (tăcere / no-speech). Vorbește clar după ce vezi «Canal audio pornit»; verifică microfonul implicit în setările sistemului.",
            "ok"
          );
        }
        voiceRec = null;
        window.setTimeout(() => {
          if (voiceDict.active && !voiceDict.userStop) startVoiceListeningChain({ skipChainIncrement: true });
        }, 480);
        return;
      }
      if (
        e.error === "network" &&
        voiceDict.active &&
        !voiceDict.userStop &&
        voiceDict.networkFail < voiceDict.maxNetworkRetries
      ) {
        voiceDict.networkFail += 1;
        voiceRec = null;
        const delay = 450 + voiceDict.networkFail * 350;
        setVoiceListeningUi(
          true,
          "Problemă de rețea la transcriere — reîncerc " + voiceDict.networkFail + "/" + voiceDict.maxNetworkRetries + "…"
        );
        setStatus(
          "statusVoiceChat",
          "Verifică internetul / VPN-ul; transcrierea din browser folosește un serviciu online (Google). În Brave încearcă Shields oprit pentru acest site. Reiau automat…",
          "ok"
        );
        window.setTimeout(() => {
          if (voiceDict.active && !voiceDict.userStop) startVoiceListeningChain({ skipChainIncrement: true });
        }, delay);
        return;
      }
      setVoiceListeningUi(false);
      voiceDict.active = false;
      voiceRec = null;
      voiceDict.networkFail = 0;
      voiceDict.noSpeechStreak = 0;
      const originBlock = getVoiceSpeechOriginBlockMessage();
      const msg = voiceMicErrorMessage(e.error);
      if (msg) {
        const out =
          e.error === "network" && originBlock ? originBlock + " " + msg : msg;
        setStatus("statusVoiceChat", out, "bad");
      }
    };

    rec.onstart = () => {
      setVoiceListeningUi(true, "Microfon activ — vorbește. Apasă «Stop» când ai terminat.");
      if (voiceDict.chain <= 1) {
        setStatus("statusVoiceChat", "Ascult… (dacă se închide singur după o tăcere, reiau automat până apeși Stop).", "ok");
      }
    };
    rec.onaudiostart = () => setVoiceListeningUi(true, "Canal audio pornit — vorbește acum.");
    rec.onsoundstart = () => setVoiceListeningUi(true, "Detectez sunet…");
    rec.onspeechstart = () => setVoiceListeningUi(true, "Te aud…");

    rec.onend = () => {
      voiceRec = null;
      if (!voiceDict.active) return;
      if (voiceDict.userStop) {
        voiceDict.active = false;
        setVoiceListeningUi(false);
        const flushStop = () => {
          const q = getVoiceQuestionForSubmit();
          voiceDict.userStop = false;
          voiceDict.buf = "";
          voiceDict.lastMerged = "";
          voiceDict.chain = 0;
          voiceDict.networkFail = 0;
          voiceDict.noSpeechStreak = 0;
          if (q) {
            setStatus("statusVoiceChat", "Trimit întrebarea…", "ok");
            voiceAskChat();
          } else {
            setStatus(
              "statusVoiceChat",
              "N-am prins text din dictare. Verifică cartea din listă. " + voiceStopEmptyHint() + " Reporne «Întreabă cu vocea» sau scrie întrebarea.",
              "bad"
            );
          }
        };
        let attempt = 0;
        function scheduleFlushRetry() {
          const delay = attempt === 0 ? 0 : attempt === 1 ? 300 : 350;
          window.setTimeout(() => {
            if (getVoiceQuestionForSubmit()) {
              flushStop();
              return;
            }
            attempt += 1;
            if (attempt < 3) scheduleFlushRetry();
            else flushStop();
          }, delay);
        }
        scheduleFlushRetry();
        return;
      }
      /* Sesiune închisă de browser fără Stop — legăm următoarea bucată. */
      setVoiceListeningUi(true, "Continui ascultarea…");
      window.setTimeout(() => {
        if (voiceDict.active && !voiceDict.userStop) startVoiceListeningChain({ skipChainIncrement: true });
      }, 120);
    };

    try {
      rec.start();
    } catch (err) {
      voiceRec = null;
      if (voiceDict.active && !voiceDict.userStop && voiceDict.chain < voiceDict.maxChain) {
        window.setTimeout(() => {
          if (voiceDict.active && !voiceDict.userStop) startVoiceListeningChain({ skipChainIncrement: true });
        }, 250);
        return;
      }
      voiceDict.active = false;
      setVoiceListeningUi(false);
      const m = err && err.message ? err.message : String(err);
      setStatus("statusVoiceChat", "Nu pot porni microfonul: " + m, "bad");
    }
  }

  if (btnVoiceMic) {
    btnVoiceMic.addEventListener("click", () => {
      if (voiceRec || voiceDict.active) {
        triggerVoiceStop("Finalizez transcrierea…");
        return;
      }
      const sel = el("voiceSourceSelect");
      if (!sel || !String(sel.value || "").trim()) {
        setStatus(
          "statusVoiceChat",
          "Alege mai întâi cartea din listă «Cartea din bibliotecă», apoi «Întreabă cu vocea».",
          "bad"
        );
        return;
      }
      if (!supportsSpeechRecognition()) {
        setStatus("statusVoiceChat", "Dictarea nu e disponibilă în acest browser (încearcă Chrome, Brave sau Edge — Chromium).", "bad");
        return;
      }
      if (!window.SpeechRecognition && !window.webkitSpeechRecognition) {
        setStatus("statusVoiceChat", "SpeechRecognition indisponibil.", "bad");
        return;
      }
      const originBlock = getVoiceSpeechOriginBlockMessage();
      if (originBlock) {
        setStatus("statusVoiceChat", originBlock, "bad");
        return;
      }
      voiceDict.active = true;
      voiceDict.userStop = false;
      voiceDict.chain = 0;
      voiceDict.networkFail = 0;
      voiceDict.noSpeechStreak = 0;
      voiceDict.buf = "";
      voiceDict.lastMerged = "";
      const box = el("voiceQuestionText");
      if (box) box.value = "";
      startVoiceListeningChain();
    });
  }

  const btnVoiceSpeak = el("btnVoiceSpeak");
  if (btnVoiceSpeak) btnVoiceSpeak.addEventListener("click", () => speakVoiceAnswer());

  const btnVoiceStopSpeak = el("btnVoiceStopSpeak");
  if (btnVoiceStopSpeak) {
    btnVoiceStopSpeak.addEventListener("click", () => {
      if ("speechSynthesis" in window) window.speechSynthesis.cancel();
      if (voiceRec || voiceDict.active) {
        triggerVoiceStop("Finalizez dictarea…");
      } else {
        setVoiceListeningUi(false);
        setStatus("statusVoiceChat", "Citirea răspunsului (voce) oprită. Dictarea era deja oprită.", "");
      }
    });
  }

  el("btnStopSpeak").addEventListener("click", () => {
    if ("speechSynthesis" in window) window.speechSynthesis.cancel();
  });
})();
