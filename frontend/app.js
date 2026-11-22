// ===========================================================================
// ImmichHelper – Rahmen, Navigation, Einrichtung, Anmeldung
// ===========================================================================
import { h, icon, clear, api, state, toast, errorToast, field, input, loader, num, bytes } from "./js/core.js";
import { renderHome } from "./js/views/home.js";
import { renderCategory, renderGroups, renderRaw, CATS } from "./js/views/clean.js";
import { renderSwipe } from "./js/views/swipe.js";
import { renderOrganize } from "./js/views/organize.js";
import { renderHistory } from "./js/views/history.js";
import { renderSettings } from "./js/views/settings.js";

const app = document.getElementById("app");
let page = null;
let mainEl = null;
let syncEl = null;
let navCounts = {};

// ---------------------------------------------------------------------------
// Design
// ---------------------------------------------------------------------------
export function setTheme(t) {
  try { t === "auto" ? localStorage.removeItem("ih-theme") : localStorage.setItem("ih-theme", t); } catch { /* */ }
  if (t === "auto") delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = t;
}
export function currentTheme() { return document.documentElement.dataset.theme || "auto"; }

// ---------------------------------------------------------------------------
// Erster Start: Immich-Adresse
// ---------------------------------------------------------------------------
function loginArt() {
  return h("div", { class: "login-art" },
    h("div", { class: "brand" }, h("div", { class: "brand-mark" }, icon("broom")), h("div", null, "ImmichHelper", h("small", null, "Aufräumen für Immich"))),
    h("h1", null, "Weniger Ballast. Mehr Lieblingsfotos."),
    h("p", null, "Unscharfe Bilder, Serien, Duplikate, Screenshots und WhatsApp-Bilder finden – und deine Fotos zu Alben ordnen. Alles über Immich, gelöscht wird in den Papierkorb."),
    h("div", { class: "login-features" }, ["Wischen zum Aussortieren", "Duplikate & Serien", "Ereignisse als Alben", "RAW + JPG"].map(t => h("span", null, t))));
}

function renderSetup(info) {
  clear(app);
  const url = input({ placeholder: "http://192.168.1.20:2283", autocapitalize: "off", spellcheck: "false", value: info?.immich_url || "" });
  const errBox = h("div");
  const btn = h("button", { class: "btn primary lg block", type: "submit" }, "Verbinden");
  const form = h("form", { class: "stack", style: { gap: "16px" } },
    field("Adresse deines Immich", url, "Dieselbe Adresse, mit der du Immich im Heimnetz öffnest – meist mit Port 2283."), errBox, btn);
  form.addEventListener("submit", async (e) => {
    e.preventDefault(); clear(errBox); btn.disabled = true;
    try { await api("/setup", { method: "POST", body: { url: url.value.trim() } }); renderLogin(); }
    catch (err) { errBox.append(h("div", { class: "callout bad" }, icon("xCircle"), h("div", null, h("p", null, err.message)))); }
    finally { btn.disabled = false; }
  });
  app.append(h("div", { class: "login-wrap" }, loginArt(),
    h("div", { class: "login-panel" }, h("div", { class: "login-box" },
      h("h2", null, "Willkommen!"), h("p", null, "Einmal einrichten: Wo läuft dein Immich?"), form))));
  setTimeout(() => url.focus(), 50);
}

// ---------------------------------------------------------------------------
// Anmeldung
// ---------------------------------------------------------------------------
function renderLogin(message) {
  clear(app);
  let useKey = false;
  const email = input({ type: "email", autocomplete: "username", autocapitalize: "off", spellcheck: "false", placeholder: "du@beispiel.de" });
  const pass = input({ type: "password", autocomplete: "current-password" });
  const key = input({ type: "password", autocomplete: "off", placeholder: "Immich → Kontoeinstellungen → API-Schlüssel" });
  const remember = h("input", { type: "checkbox", checked: true });
  const errBox = h("div");
  const btn = h("button", { class: "btn primary lg block", type: "submit" }, "Anmelden");
  try { email.value = localStorage.getItem("ih-last-user") || ""; } catch { /* */ }
  const pwFields = h("div", { class: "stack", style: { gap: "16px" } }, field("E-Mail", email), field("Passwort", pass));
  const keyFields = h("div", { class: "stack hidden" }, field("API-Schlüssel", key, "Für Konten mit Anmeldung über OAuth. Rechte: alles zu Fotos, Alben und Papierkorb."));
  const switcher = h("button", { type: "button", class: "btn ghost sm", style: { alignSelf: "flex-start" }, onclick: () => {
    useKey = !useKey; pwFields.classList.toggle("hidden", useKey); keyFields.classList.toggle("hidden", !useKey);
    switcher.textContent = useKey ? "Mit E-Mail und Passwort anmelden" : "Mit API-Schlüssel anmelden";
  } }, "Mit API-Schlüssel anmelden");
  const form = h("form", { class: "stack", style: { gap: "16px" } }, pwFields, keyFields,
    h("label", { class: "row", style: { gap: "10px", cursor: "pointer" } }, remember, h("span", null, "Angemeldet bleiben (30 Tage)")),
    errBox, btn, switcher);
  form.addEventListener("submit", async (e) => {
    e.preventDefault(); clear(errBox); btn.disabled = true;
    try {
      const body = useKey ? { api_key: key.value.trim(), remember: remember.checked } : { email: email.value.trim(), password: pass.value, remember: remember.checked };
      await api("/login", { method: "POST", body });
      try { if (!useKey) localStorage.setItem("ih-last-user", email.value.trim()); } catch { /* */ }
      await boot();
    } catch (err) {
      errBox.append(h("div", { class: "callout bad" }, icon("xCircle"), h("div", null, h("p", null, err.message))));
      (useKey ? key : pass).select();
    } finally { btn.disabled = false; }
  });
  app.append(h("div", { class: "login-wrap" }, loginArt(),
    h("div", { class: "login-panel" }, h("div", { class: "login-box" },
      h("h2", null, "Anmelden"), h("p", null, message || "Mit deinem Immich-Konto – dieselben Zugangsdaten wie in der Immich-App."), form))));
  setTimeout(() => (email.value ? pass : email).focus(), 50);
}

window.addEventListener("ih:logout", () => { state.user = null; renderLogin("Deine Anmeldung ist abgelaufen. Bitte neu anmelden."); });

export async function logout() {
  try { await api("/logout", { method: "POST" }); } catch { /* */ }
  state.user = null;
  location.hash = "#/";
  renderLogin("Du wurdest abgemeldet.");
}

// ---------------------------------------------------------------------------
// Rahmen
// ---------------------------------------------------------------------------
function navLink(href, ico, label, countKey) {
  const count = h("span", { class: "n-count" });
  if (countKey) navCounts[countKey] = count;
  return h("a", { href, "data-href": href }, icon(ico), h("span", { class: "n-label" }, label), countKey ? count : null);
}

function buildShell() {
  clear(app);
  navCounts = {};
  const initials = (state.user.name?.[0] || "?").toUpperCase();
  const themeBtn = h("button", { class: "btn icon sm ghost theme-btn", title: "Hell/Dunkel", onclick: () => {
    const dark = currentTheme() === "dark" || (currentTheme() === "auto" && matchMedia("(prefers-color-scheme: dark)").matches);
    setTheme(dark ? "light" : "dark"); clear(themeBtn).append(icon(dark ? "moon" : "sun", "sm"));
  } }, icon(document.documentElement.dataset.theme === "dark" ? "sun" : "moon", "sm"));
  const sidebar = h("aside", { class: "sidebar" },
    h("a", { class: "brand", href: "#/" }, h("div", { class: "brand-mark" }, icon("broom")), h("div", null, "ImmichHelper", h("small", null, "Aufräumen für Immich"))),
    h("nav", { class: "nav" },
      navLink("#/", "home", "Übersicht"),
      navLink("#/swipe", "swipe", "Wischen"),
      navLink("#/organize", "album", "Ordnen"),
      navLink("#/history", "history", "Verlauf"),
      navLink("#/settings", "settings", "Einstellungen")),
    h("div", { class: "nav-section" }, "Aufräumen"),
    h("nav", { class: "nav" },
      navLink("#/dups", "copy", "Duplikate", "duplicates"),
      navLink("#/bursts", "burst", "Serien", "bursts"),
      ...CATS.map(c => navLink(`#/cat/${c.key}`, c.icon, c.nav || c.title, c.key)),
      navLink("#/raw", "aperture", "RAW + JPG", "raw")),
    h("div", { class: "sidebar-foot" }, h("div", { class: "user-chip" },
      h("div", { class: "avatar" }, initials),
      h("div", { style: { minWidth: 0, flex: 1 } }, h("div", { style: { fontWeight: 650, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } }, state.user.name),
        h("div", { class: "muted small" }, state.user.admin ? "Admin" : "Immich-Konto")),
      themeBtn,
      h("button", { class: "btn icon sm ghost", title: "Abmelden", onclick: logout }, icon("logout", "sm")))));

  const topbar = h("div", { class: "topbar" },
    h("a", { class: "brand", href: "#/" }, h("div", { class: "brand-mark" }, icon("broom", "sm")), "ImmichHelper"),
    h("span", { class: "spacer" }),
    h("a", { class: "btn icon ghost", href: "#/settings", "aria-label": "Einstellungen" }, icon("user")));

  const bottom = h("nav", { class: "bottom-nav" },
    h("a", { href: "#/", "data-href": "#/" }, icon("home"), "Übersicht"),
    h("a", { href: "#/organize", "data-href": "#/organize" }, icon("album"), "Ordnen"),
    h("a", { href: "#/swipe", "data-href": "#/swipe", class: "plus" }, icon("swipe"), "Wischen"),
    h("a", { href: "#/history", "data-href": "#/history" }, icon("history"), "Verlauf"),
    h("a", { href: "#/settings", "data-href": "#/settings" }, icon("settings"), "Mehr"));

  syncEl = h("div");
  mainEl = h("main", { class: "main" });
  app.append(h("div", { class: "shell" }, sidebar, h("div", null, topbar, h("div", { class: "main", style: { paddingBottom: 0, paddingTop: "18px" } }, syncEl), mainEl)), bottom);
  syncEl.parentElement.style.display = "none";
}

export function setNavCounts(ov) {
  if (!ov) return;
  const c = ov.cats;
  const set = (k, n) => { if (navCounts[k]) navCounts[k].textContent = n ? num(n) : ""; };
  set("duplicates", c.duplicates.count);
  set("bursts", c.bursts.count);
  for (const k of ["blurry", "dark", "screenshots", "messenger", "shortvideos", "large"]) set(k, c[k].count);
  set("raw", c.raw.count);
}

function markActive() {
  const hash = (location.hash || "#/").split("?")[0];
  document.querySelectorAll(".nav a, .bottom-nav a").forEach(a => {
    const href = a.dataset.href;
    const on = href === hash || (href !== "#/" && href && hash.startsWith(href + "/")) || (href !== "#/" && href === hash);
    a.classList.toggle("active", !!on);
  });
}

// ---------------------------------------------------------------------------
// Einlesen im Hintergrund – Fortschritt oben anzeigen
// ---------------------------------------------------------------------------
let pollTimer = null;
let lastJobState = null;
const PHASE = { library: "Bibliothek wird gelesen", albums: "Alben werden abgeglichen", duplicates: "Duplikate werden abgefragt", analysis: "Fotos werden geprüft" };

export function drawSync(st) {
  if (!syncEl) return;
  const j = st?.job;
  const wrap = syncEl.parentElement;
  clear(syncEl);
  if (j && j.state === "running") {
    const pctv = j.total ? Math.min(100, (j.done / j.total) * 100) : 0;
    wrap.style.display = "";
    syncEl.append(h("div", { class: "syncbar" }, icon("spinner", "spin"),
      h("div", { class: "grow" },
        h("div", { style: { fontWeight: 650 } }, `${PHASE[j.phase] || j.message} …`),
        h("div", { class: "muted small num" }, j.total ? `${num(j.done)} von ${num(j.total)}` : num(j.done),
          j.phase === "analysis" ? " · Schärfe, Helligkeit und Ähnlichkeit (nur beim ersten Mal so lange)" : ""),
        h("div", { class: "meter thin" }, h("i", { style: { width: `${pctv.toFixed(1)}%` } }))),
      h("button", { class: "btn sm ghost", onclick: async () => { await api("/sync/cancel", { method: "POST" }); } }, "Abbrechen")));
  } else if (j && j.state === "error") {
    wrap.style.display = "";
    syncEl.append(h("div", { class: "syncbar bad" }, icon("alert"),
      h("div", { class: "grow" }, h("div", { style: { fontWeight: 650 } }, "Einlesen fehlgeschlagen"), h("div", { class: "small" }, j.error)),
      h("button", { class: "btn sm", onclick: startSync }, icon("refresh", "sm"), "Nochmal")));
  } else wrap.style.display = "none";
}

export async function startSync() {
  try { drawSync(await api("/sync", { method: "POST" })); poll(); } catch (e) { errorToast(e); }
}

export function poll() {
  clearTimeout(pollTimer);
  const tick = async () => {
    let st;
    try { st = await api("/status"); } catch { pollTimer = setTimeout(tick, 5000); return; }
    drawSync(st);
    const running = st.job?.state === "running";
    if (lastJobState === "running" && !running) {
      if (st.job?.state === "done") toast("Bibliothek ist aktuell", st.job.analyzed ? `${num(st.job.analyzed)} Fotos neu geprüft.` : "");
      window.dispatchEvent(new Event("ih:synced"));
    }
    if (running && st.job.phase === "analysis" && st.job.done && st.job.done % 400 < 25) window.dispatchEvent(new Event("ih:progress"));
    lastJobState = st.job?.state || null;
    pollTimer = setTimeout(tick, running ? 1500 : 30000);
  };
  tick();
}

// ---------------------------------------------------------------------------
// Seiten
// ---------------------------------------------------------------------------
function newPage() {
  if (page) page.cleanup.forEach(fn => { try { fn(); } catch { /* */ } });
  page = { cleanup: [], on(ev, fn, target = window) { target.addEventListener(ev, fn); this.cleanup.push(() => target.removeEventListener(ev, fn)); } };
  return page;
}

export async function refreshOverview() {
  try { state.overview = await api("/overview"); setNavCounts(state.overview); } catch { /* */ }
  return state.overview;
}

async function route() {
  if (!state.user) return;
  const [hash, hquery] = (location.hash || "#/").split("?");
  const params = new URLSearchParams(hquery || "");
  const p = newPage();
  clear(mainEl);
  const el = h("div", { class: "fade-in" });
  mainEl.append(el);
  markActive();
  window.scrollTo(0, 0);
  const parts = hash.slice(2).split("/").map(decodeURIComponent);
  const ctx = { page: p, el, params, refreshOverview, startSync };
  try {
    if (parts[0] === "cat" && parts[1]) await renderCategory({ ...ctx, name: parts[1] });
    else if (parts[0] === "dups") await renderGroups({ ...ctx, kind: "duplicates" });
    else if (parts[0] === "bursts") await renderGroups({ ...ctx, kind: "bursts" });
    else if (parts[0] === "raw") await renderRaw(ctx);
    else if (parts[0] === "swipe") await renderSwipe({ ...ctx, source: params.get("source") });
    else if (parts[0] === "organize") await renderOrganize({ ...ctx, tab: parts[1] || "events" });
    else if (parts[0] === "history") await renderHistory(ctx);
    else if (parts[0] === "settings") await renderSettings({ ...ctx, logout, setTheme, currentTheme });
    else await renderHome(ctx);
  } catch (e) {
    if (e.status === 401) return;
    clear(el).append(h("div", { class: "callout bad" }, icon("xCircle"), h("div", null, h("strong", null, "Laden fehlgeschlagen"), h("p", null, e.message))));
  }
}

window.addEventListener("hashchange", route);

async function boot() {
  clear(app).append(loader());
  let setup;
  try { setup = await api("/setup"); } catch (e) {
    clear(app).append(h("div", { class: "main" }, h("div", { class: "callout bad" }, icon("xCircle"), h("div", null, h("strong", null, "ImmichHelper ist nicht erreichbar"), h("p", null, e.message)))));
    return;
  }
  if (!setup.configured) return renderSetup(setup);
  try {
    const me = await api("/me");
    state.user = me.user;
    state.version = me.version;
    state.immich = me.immich;
    state.settings = me.settings;
  } catch (e) {
    if (e.status === 401) return renderLogin();
    clear(app).append(h("div", { class: "main" }, h("div", { class: "callout bad" }, icon("xCircle"), h("div", null, h("strong", null, "Fehler"), h("p", null, e.message)))));
    return;
  }
  buildShell();
  refreshOverview();
  poll();
  await route();
}

boot();
export { bytes };
