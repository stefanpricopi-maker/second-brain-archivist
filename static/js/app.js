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
    setStatus("statusIngest", "Indexare…");
    el("outIngest").textContent = "";
    const fd = new FormData();
    for (const f of files) fd.append("files", f);
    try {
      const r = await fetch(apiUrl("/ingest/files"), { method: "POST", body: fd });
      const t = await r.text();
      el("outIngest").textContent = t;
      setStatus("statusIngest", r.ok ? "OK" : "HTTP " + r.status, r.ok ? "ok" : "bad");
    } catch (e) {
      setStatus("statusIngest", "Eroare: " + e, "bad");
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
      el("outChat").textContent = t;
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
    const u = new SpeechSynthesisUtterance(text);
    u.lang = "ro-RO";
    u.rate = 1.02;
    window.speechSynthesis.speak(u);
  }

  el("btnSpeak").addEventListener("click", () => {
    const raw = el("outChat").textContent || "";
    try {
      const j = JSON.parse(raw);
      const ans = String(j.answer || "").trim();
      if (!ans) {
        setStatus("statusChat", "Nu am răspuns de citit.", "bad");
        return;
      }
      speak(ans);
    } catch {
      setStatus("statusChat", "Răspunsul nu e JSON valid.", "bad");
    }
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
      if (out) out.textContent = t;
      setStatus("statusVoiceChat", r.ok ? "OK" : "HTTP " + r.status, r.ok ? "ok" : "bad");
    } catch (e) {
      setStatus("statusVoiceChat", "Eroare: " + e, "bad");
    }
  }

  let voiceRec = null;

  function speakVoiceAnswer() {
    const raw = el("outVoiceChat") ? el("outVoiceChat").textContent || "" : "";
    if (!("speechSynthesis" in window)) {
      setStatus("statusVoiceChat", "Sinteză vocală indisponibilă în acest browser.", "bad");
      return;
    }
    try {
      const j = JSON.parse(raw);
      const ans = String(j.answer || "").trim();
      if (!ans) {
        setStatus("statusVoiceChat", "Nu am răspuns de citit.", "bad");
        return;
      }
      window.speechSynthesis.cancel();
      const u = new SpeechSynthesisUtterance(ans);
      u.lang = "ro-RO";
      u.rate = 1.02;
      window.speechSynthesis.speak(u);
    } catch {
      setStatus("statusVoiceChat", "Răspunsul nu e JSON valid.", "bad");
    }
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
      setStatus("statusVoiceIngest", "Indexare…");
      const out = el("outVoiceIngest");
      if (out) out.textContent = "";
      const fd = new FormData();
      for (const f of files) fd.append("files", f);
      const bl = el("voiceBookLabel");
      const fo = el("voiceForceOcr");
      fd.append("book_label", bl ? String(bl.value || "").trim() : "");
      fd.append("force_ocr", fo && fo.value ? String(fo.value) : "auto");
      try {
        const r = await fetch(apiUrl("/voice-library/ingest"), { method: "POST", body: fd });
        const t = await r.text();
        if (out) out.textContent = t;
        setStatus("statusVoiceIngest", r.ok ? "OK" : "HTTP " + r.status, r.ok ? "ok" : "bad");
        if (r.ok) await refreshVoiceSources();
      } catch (e) {
        setStatus("statusVoiceIngest", "Eroare: " + e, "bad");
      }
    });
  }

  const btnVoiceRefresh = el("btnVoiceRefreshSources");
  if (btnVoiceRefresh) btnVoiceRefresh.addEventListener("click", () => refreshVoiceSources());

  const btnVoiceAsk = el("btnVoiceAsk");
  if (btnVoiceAsk) btnVoiceAsk.addEventListener("click", () => voiceAskChat());

  const btnVoiceMic = el("btnVoiceMic");
  if (btnVoiceMic) {
    btnVoiceMic.addEventListener("click", () => {
      if (!supportsSpeechRecognition()) {
        setStatus("statusVoiceChat", "Dictarea nu e disponibilă în acest browser.", "bad");
        return;
      }
      const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
      voiceRec = new SR();
      voiceRec.lang = "ro-RO";
      voiceRec.interimResults = true;
      voiceRec.continuous = false;
      let finalText = "";
      voiceRec.onresult = (ev) => {
        let interim = "";
        for (let i = ev.resultIndex; i < ev.results.length; i++) {
          const txt = ev.results[i][0].transcript;
          if (ev.results[i].isFinal) finalText += txt;
          else interim += txt;
        }
        const box = el("voiceQuestionText");
        if (box) box.value = (finalText + " " + interim).trim();
      };
      voiceRec.onerror = (e) => setStatus("statusVoiceChat", "Mic: " + e.error, "bad");
      voiceRec.onstart = () => setStatus("statusVoiceChat", "Ascult…");
      voiceRec.onend = () => {
        setStatus("statusVoiceChat", "Dictare oprită — trimit întrebarea.", "ok");
        voiceAskChat();
      };
      voiceRec.start();
    });
  }

  const btnVoiceSpeak = el("btnVoiceSpeak");
  if (btnVoiceSpeak) btnVoiceSpeak.addEventListener("click", () => speakVoiceAnswer());

  const btnVoiceStopSpeak = el("btnVoiceStopSpeak");
  if (btnVoiceStopSpeak) {
    btnVoiceStopSpeak.addEventListener("click", () => {
      if ("speechSynthesis" in window) window.speechSynthesis.cancel();
    });
  }

  el("btnStopSpeak").addEventListener("click", () => {
    if ("speechSynthesis" in window) window.speechSynthesis.cancel();
  });
})();
