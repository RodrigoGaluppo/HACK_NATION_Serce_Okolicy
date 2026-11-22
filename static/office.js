"use strict";
const get = (id) => document.getElementById(id);
const make = (tag, text = "", className = "") => {
  const node = document.createElement(tag);
  node.textContent = text;
  if (className) node.className = className;
  return node;
};
let language = "pl";
try { language = localStorage.getItem("aed-language") === "en" ? "en" : "pl"; } catch {}
const t = (pl, en) => language === "en" ? en : pl;
const fmt = (value) => Number(value || 0).toLocaleString(language === "en" ? "en-GB" : "pl-PL");
const date = (value) => value ? new Date(value).toLocaleString(language === "en" ? "en-GB" : "pl-PL") : "—";
let repaint = () => {};
function applyLanguage(value) {
  language = value;
  document.documentElement.lang = language;
  try { localStorage.setItem("aed-language", value); } catch {}
  document.querySelectorAll("[data-pl][data-en]").forEach(node => { node.textContent = node.dataset[language]; });
  document.querySelectorAll("[data-language]").forEach(node => node.setAttribute("aria-pressed", String(node.dataset.language === language)));
  repaint();
}
document.querySelectorAll("[data-language]").forEach(node => node.onclick = () => applyLanguage(node.dataset.language));
applyLanguage(language);

async function api(path, body, token) {
  const headers = {};
  if (token) headers.Authorization = "Bearer " + token;
  if (body) headers["Content-Type"] = "application/json";
  const response = await fetch(path, { method: body ? "POST" : "GET", headers, body: body ? JSON.stringify(body) : undefined, cache: "no-store" });
  if (response.ok && response.headers.get("Content-Type")?.startsWith("application/zip")) return response.blob();
  const out = await response.json();
  if (!response.ok) throw new Error(out.error || out.message || t("Operacja nie powiodła się.", "The operation failed."));
  return out;
}

if (document.body.dataset.view === "submit") {
  const form = get("submit-form"), format = get("format"), send = get("send-submission");
  let preview, revision = 0;
  function reset() {
    revision += 1;
    preview = null;
    send.disabled = true;
    get("validation-errors").replaceChildren();
    get("submit-status").textContent = "";
    get("submission-preview").hidden = true;
  }
  function switchFormat() {
    get("device-fields").disabled = format.value !== "form";
    get("device-fields").hidden = format.value !== "form";
    get("batch-fields").hidden = format.value === "form";
    get("batch").accept = format.value === "xlsx" ? ".xlsx" : format.value === "csv" ? ".csv" : ".geojson,.json";
  }
  format.addEventListener("change", switchFormat);
  form.addEventListener("input", reset);
  form.addEventListener("change", reset);
  switchFormat();
  form.addEventListener("submit", async event => {
    event.preventDefault();
    reset();
    const requested = revision;
    get("preview-button").disabled = true;
    const status = get("submit-status");
    status.textContent = t("Sprawdzanie danych…", "Checking your data…");
    try {
      const selected = format.value;
      let data;
      if (selected === "form") data = Object.fromEntries(new FormData(form));
      else {
        const file = get("batch").files[0];
        if (!file || file.size > 1_600_000) throw new Error(t("Wybierz plik o rozmiarze do 1,6 MB.", "Choose a file up to 1.6 MB."));
        if (selected === "xlsx") {
          data = await new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(String(reader.result).split(",", 2)[1]);
            reader.onerror = () => reject(new Error(t("Nie można odczytać pliku.", "Could not read the file.")));
            reader.readAsDataURL(file);
          });
        } else data = await file.text();
      }
      const payload = { operator: get("operator").value, consent: get("consent").checked, format: selected, data };
      const out = await api("/api/submit/preview", payload);
      if (requested !== revision) return;
      get("validation-errors").replaceChildren(...out.errors.map(error => make("li", `${t("Wiersz", "Row")} ${error.row} · ${error.message}`)));
      status.textContent = t(`Poprawne rekordy: ${out.valid}. Błędy: ${out.errors.length}.`, `Valid records: ${out.valid}. Errors: ${out.errors.length}.`);
      preview = out.valid && !out.errors.length ? payload : null;
      send.disabled = !preview;
      if (out.sample?.length) {
        const box = get("submission-preview");
        box.replaceChildren(make("h3", t("Podgląd zgłoszenia", "Contribution preview")));
        out.sample.forEach(item => {
          const row = make("article");
          row.append(make("strong", item.site_name), make("p", [item.public_operator_name, item.municipality, item.placement].filter(Boolean).join(" · ")));
          box.append(row);
        });
        box.hidden = false;
      }
    } catch (error) { if (requested === revision) status.textContent = error.message; }
    finally { get("preview-button").disabled = false; }
  });
  send.addEventListener("click", async () => {
    if (!preview) return;
    const payload = preview;
    send.disabled = true;
    get("preview-button").disabled = true;
    try {
      const out = await api("/api/submit", payload);
      if (!out.accepted) throw new Error(t("Sprawdź dane ponownie.", "Please preview the data again."));
      form.reset(); switchFormat(); reset();
      get("submit-status").textContent = t(`Dziękujemy. ${out.accepted} rekordów oczekuje na zatwierdzenie przez redaktora.`, `Thank you. ${out.accepted} records are awaiting editor approval.`);
    } catch (error) { get("submit-status").textContent = error.message; send.disabled = false; }
    finally { get("preview-button").disabled = false; }
  });
} else if (document.body.dataset.view === "admin") {
  let token, poll, connectorData, queueData, conflictData;
  const workspace = get("admin-workspace");
  function renderConnectors() {
    if (!connectorData) return;
    const data = connectorData, busy = data.run.state === "running";
    get("sync-all").disabled = busy;
    const labels = {
      idle: t("Gotowe do synchronizacji", "Ready to sync"),
      running: t("Pobieranie i scalanie danych…", "Fetching and reconciling data…"),
      complete: t("Synchronizacja zakończona", "Sync complete"),
      failed: t("Przebudowa nie powiodła się. Sprawdź migawki.", "Rebuild failed. Check source snapshots."),
    };
    get("sync-status").textContent = [labels[data.run.state] || data.run.state, data.run.finished_at ? t("Ostatnia: ", "Last: ") + date(data.run.finished_at) : "", data.run.next_sync_at ? t("Następna: ", "Next: ") + date(data.run.next_sync_at) : ""].filter(Boolean).join(" · ");
    const live = data.items.filter(item => (item.snapshot || item.status === "approved_operator") && item.count > 0);
    get("metric-sources").textContent = fmt(live.length);
    get("metric-records").textContent = fmt(data.items.reduce((sum, item) => sum + Number(item.count || 0), 0));
    get("pipeline-sources").replaceChildren(...data.items.map(item => {
      const row = make("div", "", "pipeline-source" + ((item.count > 0 && (item.snapshot || item.status === "approved_operator")) ? "" : " pending"));
      row.append(make("strong", item.name), make("small", (item.count > 0 && (item.snapshot || item.status === "approved_operator")) ? fmt(item.count) : t("nieaktywne", "inactive")));
      return row;
    }));
    get("connector-list").replaceChildren(...data.items.map(item => {
      const row = make("article"), title = make("div", "", "connector-title"), meta = make("div", "", "connector-meta"), state = make("div", "", "connector-meta");
      const link = make("a", t("Zobacz źródło ↗", "View source ↗"));
      if (/^https?:\/\//.test(item.url)) { link.href = item.url; link.target = "_blank"; link.rel = "noopener noreferrer"; }
      title.append(make("h3", item.name), link);
      meta.append(make("p", `${fmt(item.count)} ${t("rekordów", "records")} · ${item.format}`), make("p", item.scope || t("Polska", "Poland")), make("p", item.license || t("Warunki do sprawdzenia", "Reuse terms need review")));
      state.append(make("p", item.status === "approved_operator" ? t("Zatwierdzone zgłoszenia", "Approved contributions") : item.snapshot ? date(item.snapshot) : t("Brak lokalnej migawki", "No local snapshot"), "source-status" + (item.snapshot ? "" : " missing")));
      if (item.last_result) state.append(make("p", item.last_result === "kept_snapshot" ? t("Zachowano poprzednią migawkę", "Previous snapshot retained") : item.last_result === "updated" ? t("Pobrano poprawnie", "Fetch succeeded") : item.last_result));
      const stateLabels = {awaiting_adapter: t("Adapter do przygotowania", "Adapter pending"), requires_api_token: t("Wymagany klucz API", "API key required"), configured: t("Źródło skonfigurowane", "Source configured"), procurement_lead_only: t("Tylko trop zamówienia", "Procurement lead only"), approved_operator: t("Aktualizacja po zatwierdzeniu", "Updated after approval"), active: t("Aktywne", "Active")};
      if (item.status) state.append(make("p", stateLabels[item.status] || item.status));
      const button = make("button", t("Synchronizuj", "Sync"), "button secondary compact");
      button.type = "button"; button.disabled = busy || item.refreshable === false || item.enabled === false || item.status === "approved_operator"; button.onclick = () => sync(item.id);
      row.append(title, meta, state, button);
      return row;
    }));
  }
  async function loadConnectors() {
    clearTimeout(poll);
    connectorData = await api("/api/admin/connectors", null, token);
    renderConnectors();
    if (connectorData.run.state === "running") poll = setTimeout(() => loadConnectors().catch(error => { get("sync-status").textContent = error.message; }), 2000);
    else await loadConflicts();
  }
  async function sync(source) {
    clearTimeout(poll);
    try { await api("/api/admin/connectors", { source }, token); await loadConnectors(); }
    catch (error) { get("sync-status").textContent = error.message; }
  }
  function renderConflicts() {
    if (!conflictData) return;
    get("metric-conflicts").textContent = fmt(conflictData.length);
    get("conflict-list").replaceChildren(...conflictData.map(item => make("li", `${item.source} · ${item.name} — ${item.reason}${item.address ? " · " + item.address : ""}`)));
    if (!conflictData.length) get("conflict-list").append(make("li", t("Brak rekordów wymagających sprawdzenia.", "No records need review.")));
  }
  async function loadConflicts() { conflictData = (await api("/api/review")).items; renderConflicts(); }
  function renderQueue() {
    if (!queueData) return;
    const items = queueData;
    get("metric-pending").textContent = fmt(items.length);
    get("queue-status").textContent = items.length ? t(`Oczekuje na decyzję: ${items.length}`, `Awaiting a decision: ${items.length}`) : t("Wszystkie zgłoszenia sprawdzone.", "All contributions reviewed.");
    get("submission-queue").replaceChildren(...items.map(item => {
      const p = item.payload, row = make("article", "", "queue-entry"), details = make("details"), actions = make("div", "", "queue-actions");
      details.append(make("summary", t("Dane zgłoszenia · JSON", "Contribution data · JSON")), make("pre", JSON.stringify(p, null, 2)));
      row.append(make("h3", p.site_name), make("p", [p.public_operator_name, p.municipality, p.placement].filter(Boolean).join(" · ")), make("p", t("Zgłoszono: ", "Submitted: ") + date(item.created)), details);
      for (const [status, title] of [["approved", t("Zatwierdź", "Approve")], ["rejected", t("Odrzuć", "Reject")]]) {
        const button = make("button", title, "button compact " + (status === "approved" ? "primary" : "secondary"));
        button.type = "button";
        button.onclick = async () => {
          actions.querySelectorAll("button").forEach(node => node.disabled = true);
          try {
            const out = await api("/api/admin/decision", { id: item.id, status }, token);
            if (!out.updated) throw new Error(t("Decyzja nie została zapisana.", "The decision was not saved."));
            await Promise.all([loadQueue(), loadConnectors()]);
          } catch (error) { get("queue-status").textContent = error.message; actions.querySelectorAll("button").forEach(node => node.disabled = false); }
        };
        actions.append(button);
      }
      row.append(actions); return row;
    }));
  }
  async function loadQueue() { queueData = (await api("/api/admin/queue", null, token)).items; renderQueue(); }
  repaint = () => { renderConnectors(); renderConflicts(); renderQueue(); };
  get("admin-auth").onsubmit = async event => {
    event.preventDefault();
    const button = event.submitter; button.disabled = true;
    token = get("admin-token").value.trim();
    try { await Promise.all([loadConnectors(), loadQueue()]); get("admin-lock").hidden = true; get("admin-token").value = ""; workspace.hidden = false; }
    catch (error) { get("admin-status").textContent = error.message; }
    finally { button.disabled = false; }
  };
  get("source-config-form").onsubmit = async event => {
    event.preventDefault();
    const button = event.submitter, status = get("source-config-status");
    button.disabled = true;
    status.textContent = t("Sprawdzanie i pobieranie źródła…", "Validating and fetching the source…");
    try {
      const body = Object.fromEntries(new FormData(event.target));
      body.format = "geojson";
      await api("/api/admin/sources", body, token);
      status.textContent = t("Dodano źródło. Zobacz stan migawki na liście źródeł.", "Source added. Check its snapshot status in the source list.");
      event.target.reset();
      await loadConnectors();
    } catch (error) { status.textContent = error.message; }
    finally { button.disabled = false; }
  };
  get("sync-all").onclick = () => sync("all");
  get("portal-export").onclick = async () => {
    const button = get("portal-export"); button.disabled = true;
    try {
      const payload = await api("/api/admin/export", null, token), href = URL.createObjectURL(payload), link = make("a");
      link.href = href; link.download = "serce-okolicy-pakiet-portalu.zip"; document.body.append(link); link.click(); link.remove();
      setTimeout(() => URL.revokeObjectURL(href), 2000);
    } catch (error) { get("queue-status").textContent = error.message; }
    finally { button.disabled = false; }
  };
}
