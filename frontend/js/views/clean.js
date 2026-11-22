// ===========================================================================
// Aufräumen: Kategorien (Raster), Duplikate & Serien (Gruppen), RAW + JPG
// ===========================================================================
import { h, icon, clear, api, state, pageHead, empty, callout, loader, bytes, num, toast, errorToast, confirmDialog, takenAt, mp, withBusy, thumb } from "../core.js";
import { PhotoGrid, selectionBar, trashItems, keepItems, tile, openViewer, undoToast } from "../photos.js";

export const CATS = [
  { key: "blurry", title: "Unscharfe Fotos", nav: "Unscharf", icon: "blur", color: "#e0571c",
    text: "Verwackelt oder daneben fokussiert. Bei Porträts mit unscharfem Hintergrund zählt das Motiv – die tauchen hier nur auf, wenn gar nichts scharf ist." },
  { key: "dark", title: "Fehlaufnahmen", nav: "Fehlaufnahmen", icon: "dark", color: "#4a5260",
    text: "Fast schwarz, komplett überbelichtet oder einfarbig – typisch für Aufnahmen aus der Hosentasche." },
  { key: "screenshots", title: "Screenshots", nav: "Screenshots", icon: "phone", color: "#2f6df6",
    text: "Bildschirmfotos und Bildschirmaufnahmen. Oft nur kurz gebraucht – und dann vergessen." },
  { key: "messenger", title: "WhatsApp & Messenger", nav: "Messenger", icon: "message", color: "#17a364",
    text: "Bilder aus WhatsApp, Telegram, Signal & Co. – Memes, Weiterleitungen und Fotos, die du meist schon im Original hast." },
  { key: "shortvideos", title: "Sehr kurze Videos", nav: "Kurze Videos", icon: "film", color: "#8a4fff",
    text: "Videos, die nur ein, zwei Sekunden lang sind – meistens aus Versehen gestartet." },
  { key: "large", title: "Große Dateien", nav: "Große Dateien", icon: "weight", color: "#c98a05",
    text: "Die größten Fotos und Videos – hier bringt Aufräumen am meisten Platz." },
];
export const catByKey = Object.fromEntries(CATS.map(c => [c.key, c]));

function badgeFor(name) {
  if (name === "blurry") return (a) => a.sharp != null ? h("span", { class: "p-badge bad" }, `Schärfe ${Math.round(a.sharp)}`) : null;
  if (name === "large" || name === "shortvideos") return (a) => a.size ? h("span", { class: "p-badge" }, bytes(a.size)) : null;
  return null;
}

// ---------------------------------------------------------------------------
export async function renderCategory({ el, page, name, refreshOverview }) {
  const c = catByKey[name];
  if (!c) { el.append(callout("bad", "Unbekannte Kategorie")); return; }
  const sub = h("span", { class: "num" }, "…");
  el.append(h("a", { class: "back", href: "#/" }, icon("chevronLeft", "sm"), "Übersicht"),
    pageHead(c.title, h("span", null, c.text)));
  const tools = h("div", { class: "toolbar" });
  const body = h("div", null, loader());
  el.append(tools, body);
  let grid, offset = 0, total = 0;

  async function load(reset = false) {
    if (reset) { offset = 0; }
    let r;
    try { r = await api(`/cat/${name}`, { query: { offset, limit: 240 } }); } catch (e) { clear(body).append(callout("bad", null, e.message)); return; }
    total = r.total;
    if (reset || !grid) {
      grid = new PhotoGrid({ badge: badgeFor(name), actions: [
        { label: "Behalten", icon: "check", run: async (a) => { if (await keepItems([a])) { grid.remove([a.id]); return "remove"; } } },
        { label: "Löschen", icon: "trash", cls: "danger", run: async (a) => { if (await trashItems([a], { label: c.title, confirm: false })) { grid.remove([a.id]); return "remove"; } } },
      ] });
      const bar = selectionBar(grid, {
        onTrash: async (items) => { if (await trashItems(items, { label: c.title })) { grid.remove(items.map(a => a.id)); afterChange(); } },
        onKeep: async (items) => { if (await keepItems(items)) { grid.remove(items.map(a => a.id)); afterChange(); } },
      });
      clear(body);
      if (!r.total) { body.append(h("div", { class: "card" }, empty("checkCircle", "Nichts gefunden", emptyText(name)))); drawTools(r); return; }
      body.append(bar, grid.el);
    }
    grid.add(r.items);
    offset += r.items.length;
    body.querySelector(".more-row")?.remove();
    if (offset < total) body.append(h("div", { class: "more-row" }, h("button", { class: "btn", onclick: (e) => withBusy(e.currentTarget, () => load()) }, `Weitere ${num(Math.min(240, total - offset))} laden`)));
    drawTools(r);
  }

  function drawTools(r) {
    clear(tools).append(h("span", { class: "info num" }, `${num(r.total)} ${r.total === 1 ? "Treffer" : "Treffer"} · ${bytes(r.bytes)}`), sub);
    sub.textContent = "";
    if (name === "blurry") tools.append(slider("Empfindlichkeit", "blur_threshold", 5, 150, (v) => `bis Schärfe ${v}`));
    if (name === "shortvideos") tools.append(slider("Kürzer als", "short_video_s", 1, 15, (v) => `${v} s`));
    if (name === "large") tools.append(slider("Ab", "large_mb", 20, 2000, (v) => `${v} MB`, 10));
    if (name === "messenger" && r.sources) tools.append(h("div", { class: "chips" }, r.sources.map(([label, n]) => h("span", { class: "chip" }, `${label} ${num(n)}`))));
    if (r.total) tools.append(h("span", { class: "spacer" }), h("button", { class: "btn sm", onclick: () => { grid.selectAll(true); } }, icon("selectAll", "sm"), "Alle auswählen"));
    tools.append(h("p", { class: "muted small", style: { flexBasis: "100%", margin: "2px 0 0" } }, "Antippen wählt aus, lange drücken (oder die Lupe) zeigt das Foto groß. „Behalten“ nimmt Fotos dauerhaft aus den Vorschlägen."));
  }

  function slider(label, key, min, max, fmt, step = 1) {
    const val = h("span", { class: "muted small num", style: { minWidth: "90px" } }, fmt(state.settings[key]));
    const inp = h("input", { type: "range", min, max, step, value: state.settings[key] });
    let t;
    inp.addEventListener("input", () => { val.textContent = fmt(inp.value); clearTimeout(t); t = setTimeout(save, 350); });
    async function save() {
      try { state.settings = (await api("/settings", { method: "PUT", body: { [key]: Number(inp.value) } })).settings; grid = null; await load(true); }
      catch (e) { errorToast(e); }
    }
    return h("label", { class: "range-wrap" }, h("span", { class: "small", style: { fontWeight: 600 } }, label), inp, val);
  }

  function afterChange() { refreshOverview(); if (!grid.items.length && offset < total) load(true); }
  page.on("ih:reload", () => { grid = null; load(true); });
  page.on("ih:synced", () => { grid = null; load(true); });
  await load(true);
}

function emptyText(name) {
  if (name === "blurry" || name === "dark") return "Entweder ist alles gut – oder die Fotos werden gerade noch geprüft. Das passiert beim Einlesen automatisch.";
  return "Hier gibt es gerade nichts aufzuräumen.";
}

// ---------------------------------------------------------------------------
// Duplikate und Serien
// ---------------------------------------------------------------------------
const GROUP_TEXT = {
  duplicates: { title: "Duplikate", back: "Übersicht", icon: "copy",
    text: "Immich hat diese Fotos als gleich oder fast gleich erkannt. Vorgeschlagen wird das beste (größte Auflösung, meiste Infos) – grün bleibt, rot kommt in den Papierkorb.",
    none: "Keine Duplikate. Immich sucht sie selbst (Verwaltung → Aufträge → Duplikat-Erkennung), sobald das maschinelle Lernen läuft." },
  bursts: { title: "Serien", back: "Übersicht", icon: "burst",
    text: "Fotos, die innerhalb weniger Sekunden aufgenommen wurden und sich stark ähneln. Vorgeschlagen wird das schärfste – tippe an, was du sonst noch behalten willst.",
    none: "Keine Serien gefunden. Neue Fotos werden beim Einlesen geprüft." },
};

export async function renderGroups({ el, page, kind, refreshOverview }) {
  const T = GROUP_TEXT[kind];
  el.append(h("a", { class: "back", href: "#/" }, icon("chevronLeft", "sm"), T.back), pageHead(T.title, T.text));
  const head = h("div");
  const list = h("div", { class: "groups" }, loader());
  el.append(head, list);
  let offset = 0, total = 0, allBytes = 0;

  async function load(reset = false) {
    if (reset) { offset = 0; clear(list).append(loader()); }
    let r;
    try { r = await api(`/${kind === "duplicates" ? "duplicates" : "bursts"}`, { query: { offset, limit: 25 } }); } catch (e) { clear(list).append(callout("bad", null, e.message)); return; }
    total = r.total; allBytes = r.bytes;
    if (reset) clear(list);
    drawHead();
    if (!total) { list.append(h("div", { class: "card" }, empty("checkCircle", "Alles aufgeräumt", T.none))); return; }
    r.items.forEach(g => list.append(groupCard(g)));
    offset += r.items.length;
    list.querySelector(".more-row")?.remove();
    if (offset < total) list.append(h("div", { class: "more-row" }, h("button", { class: "btn", onclick: (e) => withBusy(e.currentTarget, () => load()) }, "Weitere Gruppen laden")));
  }

  function drawHead() {
    clear(head);
    if (!total) return;
    const all = h("button", { class: "btn primary" }, icon("wand", "sm"), total === 1 ? "Nach Vorschlag aufräumen" : `Alle ${num(total)} nach Vorschlag aufräumen`);
    all.addEventListener("click", async () => {
      if (!(await confirmDialog({ title: total === 1 ? "Gruppe aufräumen?" : `Alle ${num(total)} Gruppen aufräumen?`,
        text: `Aus jeder Gruppe bleibt der Vorschlag, der Rest kommt in den Immich-Papierkorb (insgesamt ${bytes(allBytes)}). Du kannst das im Verlauf rückgängig machen.`,
        confirmText: "Aufräumen", danger: true }))) return;
      await withBusy(all, async () => {
        try {
          const res = await api("/resolve/all", { method: "POST", body: { kind } });
          undoToast(res, `${num(res.count)} in den Papierkorb`, bytes(res.bytes));
          refreshOverview(); await load(true);
        } catch (e) { errorToast(e); }
      });
    });
    head.append(h("div", { class: "toolbar" }, h("span", { class: "info num" }, `${num(total)} ${total === 1 ? "Gruppe" : "Gruppen"} · bis zu ${bytes(allBytes)} frei`), h("span", { class: "spacer" }), all));
  }

  function groupCard(g) {
    const keep = new Set(g.keep);
    const card = h("div", { class: "card group-card" });
    const strip = h("div", { class: "g-strip" });
    const saveLbl = h("span");
    const apply = h("button", { class: "btn primary sm" }, icon("check", "sm"), saveLbl);
    const tiles = new Map();
    const draw = () => {
      for (const a of g.assets) {
        const t = tiles.get(a.id);
        const k = keep.has(a.id);
        t.classList.toggle("keep", k); t.classList.toggle("marked", !k);
        clear(t.querySelector(".p-state")).append(icon(k ? "check" : "trash"));
      }
      const drop = g.assets.filter(a => !keep.has(a.id));
      saveLbl.textContent = drop.length ? `${num(drop.length)} löschen (${bytes(drop.reduce((s, a) => s + (a.size || 0), 0))})` : "Alle behalten";
    };
    g.assets.forEach((a, i) => {
      const t = tile(a);
      t.append(h("span", { class: "p-state" }));
      t.addEventListener("click", () => { keep.has(a.id) ? keep.delete(a.id) : keep.add(a.id); if (!keep.size) keep.add(a.id); draw(); });
      t.addEventListener("contextmenu", (e) => { e.preventDefault(); openViewer(g.assets, i); });
      tiles.set(a.id, t);
      const best = g.keep.includes(a.id);
      strip.append(h("div", { class: "g-item" }, t, h("div", { class: "g-meta" },
        h("div", null, best ? h("strong", null, "Vorschlag · ") : null, [a.w && a.h ? `${a.w}×${a.h}` : null, a.size ? bytes(a.size) : null].filter(Boolean).join(" · ")),
        kind === "bursts" && a.sharp != null ? h("div", null, `Schärfe ${Math.round(a.sharp)}`) : h("div", { style: { overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } }, a.name),
        h("button", { class: "btn ghost sm", style: { height: "26px", padding: "0 6px", marginLeft: "-6px" }, onclick: () => openViewer(g.assets, i) }, icon("maximize", "sm"), "Groß"))));
    });
    apply.addEventListener("click", () => withBusy(apply, async () => {
      const drop = g.assets.filter(a => !keep.has(a.id)).map(a => a.id);
      try {
        const r = await api("/resolve", { method: "POST", body: { kind, keep: [...keep], trash: drop } });
        if (r.count) undoToast(r, `${num(r.count)} in den Papierkorb`, bytes(r.bytes)); else toast("Alle behalten");
        card.classList.add("done");
        setTimeout(() => card.remove(), 400);
        total--; drawHead(); refreshOverview();
      } catch (e) { errorToast(e); }
    }));
    const first = g.assets[0];
    card.append(h("div", { class: "g-head" },
      h("div", { class: "grow" }, h("div", { class: "g-title" }, `${num(g.assets.length)} ${kind === "duplicates" ? "gleiche Fotos" : "Fotos in Serie"}`),
        h("div", { class: "muted small" }, [takenAt(first), first.place].filter(Boolean).join(" · "))),
      h("button", { class: "btn ghost sm", onclick: () => { g.assets.forEach(a => keep.add(a.id)); draw(); } }, "Alle behalten"),
      h("button", { class: "btn ghost sm", onclick: () => { keep.clear(); g.keep.forEach(i => keep.add(i)); draw(); } }, "Vorschlag")),
      strip, h("div", { class: "g-foot" }, apply));
    draw();
    return card;
  }

  page.on("ih:synced", () => load(true));
  page.on("ih:reload", () => load(true));
  await load(true);
}

// ---------------------------------------------------------------------------
// RAW + JPG
// ---------------------------------------------------------------------------
export async function renderRaw({ el, page, refreshOverview }) {
  el.append(h("a", { class: "back", href: "#/" }, icon("chevronLeft", "sm"), "Übersicht"),
    pageHead("RAW + JPG", "Kameras wie die Fujifilm X-S20 speichern jedes Foto doppelt (RAF + JPG). Hier stapelst du die Paare in Immich und findest RAW-Dateien, deren JPG du schon gelöscht hast."));
  const body = h("div", null, loader());
  el.append(body);
  async function draw() {
    let r;
    try { r = await api("/raw"); } catch (e) { clear(body).append(callout("bad", null, e.message)); return; }
    clear(body);
    const stat = (label, value, sub) => h("div", { class: "card stat" }, h("span", { class: "label" }, label), h("span", { class: "value num" }, value), sub ? h("span", { class: "sub" }, sub) : null);
    body.append(h("div", { class: "stats" },
      stat("RAW+JPG-Paare", num(r.pairs), r.unstacked ? `${num(r.unstacked)} noch nicht gestapelt` : "alle gestapelt"),
      stat("RAW ohne JPG", num(r.orphans), r.orphans ? `${bytes(r.orphan_bytes)} – JPG schon gelöscht` : "keine"),
      stat("Platz für RAW", bytes(r.raw_bytes), r.raw_only ? `${num(r.raw_only)} RAW-Fotos ohne JPG-Partner` : null)));

    // Stapeln
    const stackBtn = h("button", { class: "btn primary" }, icon("layers", "sm"), `Alle ${num(r.unstacked)} Paare stapeln`);
    stackBtn.addEventListener("click", () => withBusy(stackBtn, async () => {
      try { const res = await api("/stack", { method: "POST" }); toast(`${num(res.done)} Paare gestapelt`, res.failed ? `${num(res.failed)} nicht möglich` : "In Immich siehst du jetzt nur noch das JPG – das RAW liegt darunter."); refreshOverview(); draw(); }
      catch (e) { errorToast(e); }
    }));
    body.append(h("h2", { class: "section" }, icon("layers", "sm"), "Paare stapeln"),
      h("div", { class: "card" },
        h("p", { style: { margin: "0 0 14px" } }, "Ein Stapel zeigt in Immich nur das JPG, das RAW liegt darunter. Die Zeitleiste wird übersichtlicher – nichts wird gelöscht."),
        r.unstacked ? h("div", { class: "pgrid small", style: { marginBottom: "14px" } }, r.examples.map(p => tile(p.jpg, { badges: [h("span", { class: "p-badge" }, "+ RAW")] }))) : null,
        r.unstacked ? stackBtn : callout("ok", "Alle Paare sind gestapelt", null)));

    // Verwaiste RAWs
    body.append(h("h2", { class: "section" }, icon("aperture", "sm"), "RAW-Dateien ohne JPG"));
    if (!r.orphans) {
      body.append(h("div", { class: "card" }, empty("checkCircle", "Keine verwaisten RAW-Dateien",
        state.settings.raw_follow ? "Löschst du ein JPG mit ImmichHelper, kommt das passende RAW automatisch mit (einstellbar)." : "Tipp: In den Einstellungen kannst du RAW-Dateien automatisch mitlöschen lassen.")));
      return;
    }
    const list = await api("/cat/raworphans", { query: { limit: 1000 } });
    const grid = new PhotoGrid({ badge: (a) => a.size ? h("span", { class: "p-badge" }, bytes(a.size)) : null });
    const bar = selectionBar(grid, {
      onTrash: async (items) => { if (await trashItems(items, { label: "RAW ohne JPG" })) { grid.remove(items.map(a => a.id)); refreshOverview(); } },
      onKeep: async (items) => { if (await keepItems(items)) grid.remove(items.map(a => a.id)); },
    });
    body.append(h("p", { class: "muted", style: { marginTop: 0 } }, "Zu diesen RAW-Dateien gab es ein JPG, das inzwischen gelöscht ist – meist willst du das RAW dann auch nicht mehr."),
      h("div", { class: "toolbar" }, h("button", { class: "btn sm", onclick: () => grid.selectAll(true) }, icon("selectAll", "sm"), "Alle auswählen")), bar, grid.el);
    grid.add(list.items);
  }
  page.on("ih:synced", draw);
  page.on("ih:reload", draw);
  await draw();
}

export { thumb, mp };
