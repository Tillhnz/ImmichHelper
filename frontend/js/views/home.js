// ===========================================================================
// Übersicht: Bibliothek, Vorschläge zum Aufräumen, Ereignisse
// ===========================================================================
import { h, icon, clear, api, state, pageHead, callout, loader, bytes, num, relTime, thumb, empty } from "../core.js";
import { CATS } from "./clean.js";

function mosaic(ids) {
  const cells = [];
  for (let i = 0; i < 4; i++) cells.push(ids[i] ? h("img", { src: thumb(ids[i]), loading: "lazy", alt: "" }) : h("span"));
  return h("div", { class: "mosaic" }, cells);
}

function sugg({ href, ico, color, title, sub, count, unit, covers }) {
  return h("a", { class: `card clickable sugg ${count ? "" : "done"}`, href },
    mosaic(covers || []),
    h("div", { class: "s-body" },
      h("div", { class: "s-ico", style: { "--c": color } }, icon(ico)),
      h("div", { style: { minWidth: 0 } }, h("div", { class: "s-title" }, title), h("div", { class: "s-sub" }, sub)),
      h("div", { class: "s-count" }, h("strong", null, count ? num(count) : "✓"), h("span", null, count ? unit : "erledigt"))));
}

export async function renderHome({ el, page, refreshOverview, startSync }) {
  const hour = new Date().getHours();
  const greet = hour < 11 ? "Guten Morgen" : hour < 18 ? "Hallo" : "Guten Abend";
  const syncBtn = h("button", { class: "btn", onclick: () => startSync() }, icon("refresh", "sm"), "Neu einlesen");
  el.append(pageHead(`${greet}, ${state.user.name}`, "Was sich in deiner Immich-Bibliothek aufräumen lässt.", [syncBtn,
    h("a", { class: "btn primary", href: "#/swipe" }, icon("swipe", "sm"), "Wischen")]));
  const body = h("div", null, loader());
  el.append(body);

  async function draw() {
    const ov = await refreshOverview();
    if (!ov) { clear(body).append(callout("bad", "Übersicht nicht verfügbar", "ImmichHelper erreicht Immich gerade nicht.")); return; }
    clear(body);
    const L = ov.library;
    const st = ov.status;
    if (!L.photos && !L.videos) {
      const running = st?.job?.state === "running";
      body.append(h("div", { class: "card" }, empty(running ? "spinner" : "photos", running ? "Deine Bibliothek wird gerade eingelesen" : "Noch keine Fotos eingelesen",
        running ? "Das dauert beim ersten Mal ein paar Minuten – die Vorschläge erscheinen danach hier." : "Tippe auf „Neu einlesen“, um deine Fotos aus Immich zu laden.")));
      return;
    }
    const stat = (label, ico, value, sub) => h("div", { class: "card stat" }, h("span", { class: "label" }, icon(ico, "sm"), label), h("span", { class: "value num" }, value), sub ? h("span", { class: "sub" }, sub) : null);
    const c = ov.cats;
    const potential = ["blurry", "dark", "screenshots", "messenger", "shortvideos"].reduce((s, k) => s + c[k].bytes, 0) + c.duplicates.bytes + c.bursts.bytes + c.raw.bytes;
    body.append(h("div", { class: "stats" },
      stat("Fotos", "image", num(L.photos), L.analyzed < L.photos ? `${num(L.analyzed)} geprüft` : "alle geprüft"),
      stat("Videos", "video", num(L.videos)),
      stat("Speicher", "hdd", bytes(L.bytes), st?.last_sync ? `eingelesen ${relTime(st.last_sync)}` : null),
      stat("Ohne Album", "album", num(L.noalbum), L.photos + L.videos ? `${Math.round((L.noalbum / (L.photos + L.videos)) * 100)} % der Bibliothek` : null),
      stat("Aufräum-Potenzial", "broom", bytes(potential), "ohne große Dateien")));

    if (ov.pending.count) {
      body.append(h("div", { style: { marginTop: "16px" } }, callout("warn", `${num(ov.pending.count)} Fotos zum Löschen vorgemerkt (${bytes(ov.pending.bytes)})`,
        "Beim Wischen markiert, aber noch nicht gelöscht. Öffne „Wischen“, um sie in den Papierkorb zu legen.")));
    }

    body.append(h("h2", { class: "section" }, icon("broom", "sm"), "Aufräumen"));
    const items = [
      { href: "#/dups", ico: "copy", color: "#e0457b", title: "Duplikate", sub: c.duplicates.count ? `${num(c.duplicates.items)} doppelt · ${bytes(c.duplicates.bytes)}` : "von Immich erkannt", count: c.duplicates.count, unit: "Gruppen", covers: c.duplicates.covers },
      { href: "#/bursts", ico: "burst", color: "#1a9a9a", title: "Serien", sub: c.bursts.count ? `${num(c.bursts.items)} ähnliche · ${bytes(c.bursts.bytes)}` : "schnell hintereinander", count: c.bursts.count, unit: "Serien", covers: c.bursts.covers },
      ...CATS.map(k => ({ href: `#/cat/${k.key}`, ico: k.icon, color: k.color, title: k.title, sub: c[k.key].count ? bytes(c[k.key].bytes) : "nichts gefunden", count: c[k.key].count, unit: k.key === "large" ? "Dateien" : "Treffer", covers: c[k.key].covers })),
      { href: "#/raw", ico: "aperture", color: "#c98a05", title: "RAW + JPG", sub: c.raw.unstacked ? `${num(c.raw.unstacked)} Paare nicht gestapelt` : c.raw.pairs ? `${num(c.raw.pairs)} Paare, alle gestapelt` : "keine RAW-Fotos",
        count: c.raw.count || c.raw.unstacked, unit: c.raw.count ? "RAW ohne JPG" : "zum Stapeln", covers: c.raw.covers },
    ];
    body.append(h("div", { class: "sugg-grid" }, items.map(sugg)));

    // Ereignisse
    const ev = ov.events;
    body.append(h("h2", { class: "section" }, icon("album", "sm"), "Ordnen", h("span", { class: "spacer" }), h("a", { class: "btn sm ghost", href: "#/organize" }, "Alle ansehen", icon("chevronRight", "sm"))));
    if (!ev.count) body.append(h("div", { class: "card" }, h("p", { class: "muted", style: { margin: 0 } }, "Noch keine Ereignisse erkannt. Ab etwa 15 Fotos an einem Tag oder auf einer Reise schlägt ImmichHelper ein Album vor.")));
    else body.append(h("div", { class: "src-list" }, ev.top.map(e => h("a", { class: "src-item", href: `#/organize/events?key=${encodeURIComponent(e.key)}` },
      h("img", { src: thumb(e.cover), loading: "lazy", alt: "" }),
      h("div", { class: "grow" }, h("div", { class: "title" }, e.title), h("div", { class: "meta" }, [e.subtitle, `${num(e.count)} Fotos`].filter(Boolean).join(" · ")),
        h("div", { class: "meta", style: { color: e.in_album >= e.count * 0.8 ? "var(--ok)" : "var(--info)" } }, e.in_album >= e.count * 0.8 ? "schon im Album" : "noch kein Album"))))));
  }
  await draw();
  page.on("ih:synced", draw);
  let lastProgress = 0;
  page.on("ih:progress", () => { if (Date.now() - lastProgress > 30000) { lastProgress = Date.now(); draw(); } });
  page.on("ih:changed", () => refreshOverview());
}
