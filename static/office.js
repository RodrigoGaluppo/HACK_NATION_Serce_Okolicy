"use strict";
const get = (id) => document.getElementById(id);
const make = (tag, text) => {
  const node = document.createElement(tag);
  node.textContent = text ?? "";
  return node;
};
async function api(path, body, token) {
  const headers = {};
  if (token) headers.Authorization = "Bearer " + token;
  if (body) headers["Content-Type"] = "application/json";
  const res = await fetch(path, { method: body ? "POST" : "GET", headers, body: body ? JSON.stringify(body) : undefined });
  if (res.headers.get("Content-Type")?.startsWith("application/zip")) return res.blob();
  const out = await res.json();
  if (!res.ok) throw new Error(out.error || out.message || "Operacja nie powiodła się.");
  return out;
}

if (document.body.dataset.view === "submit") {
  const form = get("submit-form");
  const format = get("format");
  const send = get("send-submission");
  let preview;
  let revision = 0;
  function reset() {
    revision += 1;
    preview = null;
    send.disabled = true;
    get("validation-errors").replaceChildren();
    get("submit-status").textContent = "";
  }
  function switchFormat() {
    get("device-fields").disabled = format.value !== "form";
    get("device-fields").hidden = format.value !== "form";
    get("batch-fields").hidden = format.value === "form";
  }
  format.addEventListener("change", switchFormat);
  form.addEventListener("input", reset);
  switchFormat();
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    reset();
    const requested = revision;
    get("preview-button").disabled = true;
    const status = get("submit-status");
    status.textContent = "Sprawdzanie…";
    try {
      const selected = format.value;
      let data;
      if (selected === "form") data = Object.fromEntries(new FormData(form));
      else {
        const file = get("batch").files[0];
        if (!file || file.size > 1_600_000) throw new Error("Wybierz plik o rozmiarze do 1,6 MB.");
        if (selected === "xlsx") {
          data = await new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(String(reader.result).split(",", 2)[1]);
            reader.onerror = reject;
            reader.readAsDataURL(file);
          });
        } else data = await file.text();
      }
      const payload = { operator: get("operator").value, consent: get("consent").checked, format: selected, data };
      const out = await api("/api/submit/preview", payload);
      if (requested !== revision) return;
      const list = out.errors.map((err) => make("li", "Wiersz " + err.row + " · " + err.message));
      get("validation-errors").replaceChildren(...list);
      status.textContent = out.valid + " poprawnych · " + out.errors.length + " błędów";
      preview = out.valid && !out.errors.length ? payload : null;
      send.disabled = !preview;
    } catch (error) { status.textContent = error.message; }
    finally { get("preview-button").disabled = false; }
  });
  send.addEventListener("click", async () => {
    if (!preview) return;
    send.disabled = true;
    try {
      const out = await api("/api/submit", preview);
      if (!out.accepted) throw new Error("Sprawdź dane ponownie.");
      form.reset();
      switchFormat();
      reset();
      get("submit-status").textContent = "Liczba zgłoszeń przekazanych do weryfikacji · " + out.accepted;
    } catch (error) { get("submit-status").textContent = error.message; send.disabled = false; }
  });
} else {
  let token;
  let poll;
  const workspace = get("admin-workspace");
  async function loadConnectors() {
    const data = await api("/api/admin/connectors", null, token);
    const busy = data.run.state === "running";
    get("sync-all").disabled = busy;
    const labels = { idle: "Gotowe do synchronizacji", running: "Synchronizacja w toku…", complete: "Synchronizacja zakończona", failed: "Przebudowa indeksu nie powiodła się" };
    get("sync-status").textContent = labels[data.run.state] + (data.run.finished_at ? " · " + new Date(data.run.finished_at).toLocaleString("pl-PL") : "");
    get("connector-list").replaceChildren(...data.items.map((item) => {
      const row = make("article");
      const title = make("h3", item.name);
      const link = make("a", item.file);
      link.href = item.url;
      const btn = make("button", "Odśwież");
      btn.type = "button";
      btn.className = "button secondary compact";
      btn.disabled = busy;
      btn.onclick = () => sync(item.id);
      row.append(title, make("p", item.format + " · " + item.count.toLocaleString("pl-PL") + " rekordów"), link,
        make("p", item.snapshot ? "Migawka · " + new Date(item.snapshot).toLocaleString("pl-PL") : "Brak migawki"),
        make("p", item.last_result === "kept_snapshot" ? "Błąd pobierania · zachowano poprzednią migawkę" :
          item.last_result === "updated" ? "Pobrano nową migawkę" : ""), btn);
      return row;
    }));
    if (busy) poll = setTimeout(() => loadConnectors().catch((err) => { get("sync-status").textContent = err.message; }), 1200);
    else await loadConflicts();
  }
  async function sync(source) {
    clearTimeout(poll);
    try { await api("/api/admin/connectors", { source }, token); await loadConnectors(); }
    catch (err) { get("sync-status").textContent = err.message; }
  }
  async function loadConflicts() {
    const { items } = await api("/api/review");
    get("conflict-list").replaceChildren(...items.map((item) => make("li", item.name + " · " + item.reason)));
  }
  async function loadQueue() {
    const { items } = await api("/api/admin/queue", null, token);
    get("queue-status").textContent = items.length ? "Oczekujące · " + items.length : "Brak zgłoszeń do sprawdzenia.";
    get("submission-queue").replaceChildren(...items.map((item) => {
      const p = item.payload;
      const row = make("article");
      row.className = "queue-entry";
      const details = make("details");
      details.append(make("summary", "Dane zgłoszenia"), make("pre", JSON.stringify(p, null, 2)));
      row.append(make("h3", p.site_name), make("p", [p.public_operator_name, p.municipality, p.placement].filter(Boolean).join(" · ")), details);
      for (const [status, title] of [["approved", "Zatwierdź"], ["rejected", "Odrzuć"]]) {
        const btn = make("button", title);
        btn.type = "button";
        btn.className = "button secondary compact";
        btn.onclick = async () => {
          btn.disabled = true;
          try { await api("/api/admin/decision", { id: item.id, status }, token); await loadQueue(); }
          catch (err) { get("queue-status").textContent = err.message; btn.disabled = false; }
        };
        row.append(btn);
      }
      return row;
    }));
  }
  get("admin-auth").onsubmit = async (event) => {
    event.preventDefault();
    token = get("admin-token").value.trim();
    try {
      await Promise.all([loadConnectors(), loadQueue()]);
      get("admin-lock").hidden = true;
      get("admin-token").value = "";
      workspace.hidden = false;
    } catch (err) { get("admin-status").textContent = err.message; }
  };
  get("sync-all").onclick = () => sync("all");
  get("portal-export").onclick = async () => {
    try {
      const payload = await api("/api/admin/export", null, token);
      const href = URL.createObjectURL(payload);
      const link = make("a");
      link.href = href;
      link.download = "odblokuj-aed-pakiet-portalu.zip";
      link.click();
      setTimeout(() => URL.revokeObjectURL(href), 1000);
    } catch (err) { get("queue-status").textContent = err.message; }
  };
}
