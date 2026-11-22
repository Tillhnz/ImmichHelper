// ===========================================================================
// Einstellungen: Konto, Darstellung, Aufräum-Regeln, Immich-Verbindung, System, Benachrichtigungen
// ===========================================================================
import { h, icon, clear, api, state, toast, errorToast, pageHead, field, input, segmented, toggle, callout, loader, withBusy, relTime, num } from "../core.js";

export async function renderSettings({ el, logout, setTheme, currentTheme, startSync }) {
  el.append(pageHead("Einstellungen", null, [h("button", { class: "btn", onclick: logout }, icon("logout", "sm"), "Abmelden")]));

  // Konto
  el.append(h("div", { class: "card" },
    h("div", { class: "row", style: { gap: "14px" } }, h("div", { class: "avatar", style: { width: "48px", height: "48px", fontSize: "18px" } }, (state.user.name?.[0] || "?").toUpperCase()),
      h("div", { style: { flex: 1, minWidth: 0 } }, h("div", { style: { fontWeight: 700, fontSize: "17px" } }, state.user.name),
        h("div", { class: "muted small" }, [state.user.email, state.user.admin ? "Immich-Admin" : null, state.user.kind === "key" ? "per API-Schlüssel" : null].filter(Boolean).join(" · "))),
      state.immich ? h("a", { class: "btn", href: state.immich, target: "_blank", rel: "noopener" }, icon("external", "sm"), h("span", { class: "hide-sm" }, "Immich öffnen")) : null)));

  // Darstellung
  el.append(h("h2", { class: "section" }, icon("palette", "sm"), "Darstellung"),
    h("div", { class: "card" }, field("Design", segmented([{ value: "auto", label: "Automatisch" }, { value: "light", label: "Hell" }, { value: "dark", label: "Dunkel" }], currentTheme(), setTheme),
      "Automatisch folgt der Einstellung deines Geräts.")));

  // Regeln
  const s = { ...state.settings };
  const numField = (key, label, hint, min, max, unit) => field(label,
    h("div", { class: "row" }, input({ type: "number", min, max, value: s[key], style: { maxWidth: "120px" }, oninput: (e) => { s[key] = Number(e.target.value); } }), unit ? h("span", { class: "muted" }, unit) : null), hint);
  const saveRules = h("button", { class: "btn primary" }, icon("check", "sm"), "Speichern");
  saveRules.addEventListener("click", () => withBusy(saveRules, async () => {
    try { state.settings = (await api("/settings", { method: "PUT", body: s })).settings; toast("Gespeichert", "Die Vorschläge richten sich ab jetzt danach."); window.dispatchEvent(new Event("ih:changed")); }
    catch (e) { errorToast(e); }
  }));
  el.append(h("h2", { class: "section" }, icon("broom", "sm"), "Regeln zum Aufräumen"),
    h("div", { class: "card" }, h("div", { class: "stack", style: { gap: "18px" } },
      h("div", { class: "form-grid" },
        numField("blur_threshold", "Unscharf unter Schärfe", "Höher = mehr Fotos gelten als unscharf. Standard 35.", 1, 500),
        numField("burst_seconds", "Serie: Abstand höchstens", "Zwischen zwei Fotos einer Serie.", 1, 60, "Sekunden"),
        numField("burst_similarity", "Serie: Ähnlichkeit", "0 = fast identisch, 20 = locker. Standard 14.", 0, 32),
        numField("short_video_s", "Kurze Videos: kürzer als", null, 1, 60, "Sekunden"),
        numField("large_mb", "Große Dateien: ab", null, 10, 100000, "MB"),
        numField("event_min", "Ereignis: mindestens", "So viele Fotos an einem Tag oder auf einer Reise.", 2, 1000, "Fotos")),
      toggle("RAW-Dateien mitlöschen", "Löschst du ein JPG, kommt das passende RAW (z. B. .RAF) mit in den Papierkorb.", s.raw_follow, (v) => { s.raw_follow = v; }),
      toggle("Archivierte Fotos mit aufräumen", null, s.include_archived, (v) => { s.include_archived = v; }),
      toggle("Favoriten auch vorschlagen", "Normalerweise tauchen Favoriten nie in den Vorschlägen auf.", s.include_favorites, (v) => { s.include_favorites = v; }),
      field("Beim Wischen", segmented([{ value: "new", label: "Neueste zuerst" }, { value: "old", label: "Älteste zuerst" }], s.swipe_order, (v) => { s.swipe_order = v; })),
      numField("auto_sync_hours", "Automatisch neu einlesen alle", "0 = nur von Hand. Neue Fotos werden dabei gleich geprüft.", 0, 168, "Stunden")),
    h("div", { class: "sheet-foot" }, saveRules)));

  // Bibliothek
  const libBox = h("div", null, loader());
  el.append(h("h2", { class: "section" }, icon("photos", "sm"), "Bibliothek"), libBox);
  async function drawLib() {
    let st;
    try { st = await api("/status"); } catch (e) { clear(libBox).append(callout("bad", null, e.message)); return; }
    const btn = h("button", { class: "btn" }, icon("refresh", "sm"), "Jetzt neu einlesen");
    btn.addEventListener("click", () => withBusy(btn, async () => { await startSync(); drawLib(); }));
    clear(libBox).append(h("div", { class: "card" }, h("div", { class: "row wrap" },
      h("div", { style: { flex: 1, minWidth: "220px" } },
        h("div", { style: { fontWeight: 650 } }, st.job?.state === "running" ? "Wird gerade eingelesen …" : st.last_sync ? `Zuletzt eingelesen ${relTime(st.last_sync)}` : "Noch nicht eingelesen"),
        h("div", { class: "muted small" }, st.sync_error || "ImmichHelper liest nur – geändert wird in Immich erst, wenn du etwas löschst, stapelst oder ein Album anlegst.")),
      btn)));
  }

  await drawLib();

  // Diagnose
  const diagBox = h("div");
  const diagBtn = h("button", { class: "btn" }, icon("refresh", "sm"), "Verbindung testen");
  diagBtn.addEventListener("click", () => withBusy(diagBtn, async () => {
    try {
      const d = await api("/system/diag");
      clear(diagBox).append(h("div", { class: "list", style: { marginTop: "14px" } },
        ...d.checks.map(ch => h("div", { class: "list-item" }, icon(ch.ok ? "checkCircle" : "xCircle", "sm"),
          h("div", { class: "grow" }, h("div", { class: "title" }, ch.label), h("div", { class: "meta", style: { whiteSpace: "normal" } }, ch.detail)),
          h("span", { class: `badge ${ch.ok ? (ch.ms < 800 ? "ok" : "warn") : "bad"}` }, `${num(ch.ms)} ms`))),
        h("div", { class: "list-item" }, icon("server", "sm"), h("div", { class: "grow" }, h("div", { class: "title" }, "ImmichHelper"),
          h("div", { class: "meta", style: { whiteSpace: "normal" } }, `${num(d.assets)} Fotos/Videos geladen in ${num(d.library_ms)} ms · Arbeitsspeicher ${num(d.ram_mb_after)} MB · `
            + `Bilder-Zwischenspeicher ${d.cache.mem_mb}/${d.cache.mem_cap_mb} MB im RAM, ${num(Math.round(d.cache.disk_mb))}/${num(d.cache.disk_cap_mb)} MB auf der Platte`)))));
    } catch (e) { errorToast(e); }
  }));
  el.append(h("h2", { class: "section" }, icon("shield", "sm"), "Diagnose"),
    h("div", { class: "card" }, h("div", { class: "row wrap" },
      h("div", { style: { flex: 1, minWidth: "220px" } }, h("div", { style: { fontWeight: 650 } }, "Laden Bilder nicht oder ist es langsam?"),
        h("div", { class: "muted small" }, "Prüft, wie schnell Immich Vorschaubilder liefert, und zeigt den Speicherbedarf. Hilfreich, wenn du ein Problem meldest.")),
      diagBtn), diagBox));

  if (!state.user.admin) { el.append(h("p", { class: "muted small", style: { marginTop: "24px" } }, `ImmichHelper ${state.version}`)); return; }

  // Immich-Verbindung
  const sysBox = h("div", null, loader());
  const notifyBox = h("div", null, loader());
  el.append(h("h2", { class: "section" }, icon("link", "sm"), "Verbindung zu Immich"), h("div", { id: "immich-box" }, loader()),
    h("h2", { class: "section" }, icon("server", "sm"), "System"), sysBox,
    h("h2", { class: "section" }, icon("sparkle", "sm"), "Benachrichtigungen"), notifyBox);

  async function drawSystem(check = false) {
    let sy;
    try { sy = await api("/system", { query: { check: check ? 1 : undefined } }); } catch (e) { clear(sysBox).append(callout("bad", null, e.message)); return; }
    drawImmich(sy);
    drawNotify(sy);
    const updBtn = h("button", { class: `btn ${sy.update ? "primary" : ""}` }, icon(sy.update ? "download" : "refresh", "sm"), sy.update ? "Jetzt aktualisieren" : "Nach Updates suchen");
    updBtn.addEventListener("click", () => withBusy(updBtn, async () => {
      if (!sy.update) { await drawSystem(true); return; }
      try {
        await api("/system/update", { method: "POST" });
        toast("Update läuft", "ImmichHelper startet gleich neu – die Seite lädt sich danach selbst neu.", "busy", { timeout: 0 });
        waitForRestart(sy.version);
      } catch (e) { errorToast(e); }
    }));
    clear(sysBox).append(h("div", { class: "card" },
      h("div", { class: "row wrap", style: { gap: "12px" } },
        h("div", { style: { flex: 1, minWidth: "200px" } }, h("div", { style: { fontWeight: 700, fontSize: "16px" } }, `ImmichHelper ${sy.version}`),
          h("div", { class: "muted small" }, sy.check_error ? "Update-Prüfung gerade nicht möglich (kein Internet?)"
            : sy.update ? `${sy.changes.length}${sy.more ? "+" : ""} neue ${sy.changes.length === 1 ? "Änderung" : "Änderungen"} auf GitHub${sy.latest && sy.latest !== sy.version ? ` · Version ${sy.latest}` : ""}`
            : `Du hast den neuesten Stand${sy.installed ? ` (${sy.installed})` : ""}.`)),
        sy.update && sy.security ? h("span", { class: "badge warn" }, icon("shield", "sm"), "Sicherheitsupdate") : null,
        updBtn),
      sy.update && sy.changes.length ? h("details", { style: { marginTop: "12px" } },
        h("summary", { class: "muted small", style: { cursor: "pointer", fontWeight: 600 } }, "Was ist neu?"),
        h("ul", { class: "small", style: { marginTop: "8px" } }, sy.changes.map(c => h("li", null, c.subject)))) : null,
      sy.users?.length ? h("p", { class: "muted small", style: { margin: "14px 0 0" } }, `Benutzt von: ${sy.users.map(u => u.name).join(", ")}`) : null));
  }

  function drawImmich(sy) {
    const box = document.getElementById("immich-box");
    const d = { url: sy.immich_url, public_url: sy.immich_public_url };
    const save = h("button", { class: "btn primary" }, icon("check", "sm"), "Speichern");
    save.addEventListener("click", () => withBusy(save, async () => {
      try { const r = await api("/system/immich", { method: "PUT", body: d }); toast("Gespeichert", r.immich_version ? `Immich ${r.immich_version} erreichbar.` : ""); state.immich = d.public_url || d.url; }
      catch (e) { errorToast(e); }
    }));
    clear(box).append(h("div", { class: "card" },
      h("div", { class: "row", style: { marginBottom: "14px" } }, icon("checkCircle", "sm"), h("span", null, sy.immich_version ? `Verbunden mit Immich ${sy.immich_version}` : "Verbunden")),
      h("div", { class: "form-grid" },
        field("Adresse im Heimnetz", input({ value: d.url, autocapitalize: "off", oninput: (e) => { d.url = e.target.value.trim(); } }), "Darüber spricht ImmichHelper mit Immich, z. B. http://192.168.1.20:2283"),
        field("Adresse für Links", input({ value: d.public_url, placeholder: "z. B. https://fotos.all-heinzen.de", autocapitalize: "off", oninput: (e) => { d.public_url = e.target.value.trim(); } }), "Optional: „In Immich öffnen“ nutzt dann diese Adresse.")),
      h("div", { class: "sheet-foot" }, save)));
  }

  function drawNotify(sy) {
    const n = sy.ntfy || {};
    const d = { topic: n.topic || "", url: n.url || "", notify: n.notify !== false, click: n.click || "" };
    const save = h("button", { class: "btn primary" }, icon("check", "sm"), "Speichern");
    const test = h("button", { class: "btn" }, "Test senden");
    save.addEventListener("click", () => withBusy(save, async () => {
      try { await api("/system/notify", { method: "PUT", body: d }); toast("Gespeichert", d.topic ? `Updates kommen über ntfy, Thema „${d.topic}“.` : "Push-Nachrichten sind aus."); }
      catch (e) { errorToast(e); }
    }));
    test.addEventListener("click", () => withBusy(test, async () => {
      try { await api("/system/notify/test", { method: "POST" }); toast("Test gesendet", "Schau in die ntfy-App."); } catch (e) { errorToast(e); }
    }));
    clear(notifyBox).append(h("div", { class: "card" },
      h("p", { class: "muted", style: { margin: "0 0 16px" } }, "Wie bei den anderen Helpern: Sobald auf GitHub eine neue Version liegt – auch automatisch übernommene Sicherheitsupdates von Dependabot –, kommt eine Push-Nachricht über ntfy. Geprüft wird alle 6 Stunden."),
      h("div", { class: "stack", style: { gap: "16px" } },
        h("div", { class: "form-grid" },
          field("ntfy-Thema", input({ value: d.topic, placeholder: "z. B. till-homelab", autocapitalize: "off", oninput: (e) => { d.topic = e.target.value.trim(); } }), "Dasselbe Thema wie bei den anderen Helpern. Leer = aus."),
          field("ntfy-Server", input({ value: d.url, placeholder: "https://ntfy.sh", autocapitalize: "off", oninput: (e) => { d.url = e.target.value.trim(); } }))),
        h("div", { class: "form-grid" },
          field("Zugangstoken", input({ type: "password", placeholder: n.has_token ? "gespeichert – leer lassen = unverändert" : "nur bei geschütztem Thema", autocomplete: "off", oninput: (e) => { d.token = e.target.value.trim(); } })),
          field("Adresse von ImmichHelper", input({ value: d.click, placeholder: "z. B. https://aufraeumen.all-heinzen.de", autocapitalize: "off", oninput: (e) => { d.click = e.target.value.trim(); } }), "Optional: Tippen auf die Nachricht öffnet die Einstellungen.")),
        toggle("Bei neuen Versionen benachrichtigen", null, d.notify, (v) => { d.notify = v; })),
      h("div", { class: "sheet-foot", style: { marginTop: "16px" } }, test, save)));
  }

  await drawSystem();
  void num;
}

function waitForRestart(oldVersion) {
  let n = 0;
  const t = setInterval(async () => {
    n++;
    try {
      const r = await fetch("/api/health", { cache: "no-store" });
      const j = await r.json();
      if (j.version !== oldVersion || n > 60) { clearInterval(t); location.reload(); }
    } catch { /* startet gerade neu */ }
  }, 3000);
}
