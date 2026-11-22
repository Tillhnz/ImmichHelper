// ===========================================================================
// Ordnen: Ereignisse, Quellen, Orte, Ordner → Alben in Immich
// ===========================================================================
import { h, icon, clear, api, pageHead, callout, loader, num, bytes, toast, errorToast, thumb, segmented, openSheet, field, input, withBusy, empty, select } from "../core.js";
import { PhotoGrid } from "../photos.js";

const TABS = [
  { value: "events", label: "Ereignisse" },
  { value: "sources", label: "Quellen" },
  { value: "places", label: "Orte" },
  { value: "folders", label: "Ordner" },
];
const SRC_ICON = { messenger: "message", screen: "phone", camera: "camera", none: "image" };

export async function renderOrganize({ el, page, tab, params, refreshOverview }) {
  el.append(pageHead("Ordnen", "Fotos, die zusammengehören, mit einem Tipp als Album in Immich anlegen."));
  el.append(h("div", { class: "tabs" }, segmented(TABS, tab, (v) => { location.hash = `#/organize/${v}`; })));
  const body = h("div", null, loader());
  el.append(body);
  const draw = { events: drawEvents, sources: drawSources, places: drawPlaces, folders: drawFolders }[tab] || drawEvents;
  const run = () => draw(body, params, refreshOverview).catch(e => clear(body).append(callout("bad", null, e.message)));
  page.on("ih:synced", run);
  await run();
}

function albumBadge(g) {
  if (!g.count) return null;
  const share = g.in_album / g.count;
  if (share >= 0.8) return h("span", { class: "badge ok" }, icon("check", "sm"), "im Album");
  if (share > 0.1) return h("span", { class: "badge warn" }, `${Math.round(share * 100)} % in Alben`);
  return h("span", { class: "badge info" }, "kein Album");
}

async function drawEvents(body, params, refreshOverview) {
  const r = await api("/organize/events");
  clear(body);
  if (!r.items.length) {
    body.append(h("div", { class: "card" }, empty("album", "Noch keine Ereignisse", "Ereignisse sind Tage mit vielen Fotos (z. B. ein Geburtstag) und Reisen – erkannt an Datum und Ort. Die Mindestzahl stellst du in den Einstellungen ein.")));
    return;
  }
  const open = r.items.filter(e => e.in_album < e.count * 0.8);
  body.append(h("p", { class: "muted", style: { marginTop: 0 } }, `${num(r.items.length)} Ereignisse erkannt, ${num(open.length)} davon noch ohne Album. Reisen werden über mehrere Tage zusammengefasst, Tage zu Hause einzeln.`));
  const grid = h("div", { class: "ev-grid" });
  body.append(grid);
  for (const e of r.items) {
    const card = h("div", { class: "card ev-card", id: `ev-${e.key}` },
      h("div", { class: "ev-cover", onclick: () => showGroup("event", e) }, h("img", { src: thumb(e.cover, "preview"), loading: "lazy", alt: "" }),
        h("div", { class: "p-badges" }, e.away ? h("span", { class: "p-badge" }, icon("map"), `${e.days} ${e.days === 1 ? "Tag" : "Tage"}`) : null)),
      h("div", { class: "ev-body" },
        h("div", null, h("div", { class: "ev-title" }, e.title), h("div", { class: "ev-sub" }, [e.subtitle, `${num(e.photos)} Fotos`, e.videos ? `${num(e.videos)} ${e.videos === 1 ? "Video" : "Videos"}` : null].filter(Boolean).join(" · "))),
        h("div", { class: "row" }, albumBadge(e)),
        h("div", { class: "ev-actions" },
          h("button", { class: "btn sm primary", onclick: () => albumDialog("event", e, refreshOverview) }, icon("album", "sm"), "Album anlegen"),
          h("a", { class: "btn sm", href: `#/swipe?source=event:${encodeURIComponent(e.key)}` }, icon("swipe", "sm"), "Aussortieren"))));
    grid.append(card);
  }
  const want = params?.get("key");
  if (want) setTimeout(() => document.getElementById(`ev-${want}`)?.scrollIntoView({ behavior: "smooth", block: "center" }), 100);
}

function row(kind, g, ico, refreshOverview, extra) {
  return h("div", { class: "list-item wrap-sm" },
    g.cover ? h("img", { class: "row-cover", src: thumb(g.cover), loading: "lazy", alt: "", style: { cursor: "pointer" }, onclick: () => showGroup(kind, g) })
      : h("div", { class: "row-cover", style: { display: "grid", placeItems: "center" } }, icon(ico)),
    h("div", { class: "grow" }, h("div", { class: "title" }, g.title), h("div", { class: "meta" }, [`${num(g.count)} ${g.count === 1 ? "Foto" : "Fotos"}`, g.years, g.bytes ? bytes(g.bytes) : null].filter(Boolean).join(" · "))),
    h("div", { class: "end" }, albumBadge(g), extra,
      h("button", { class: "btn sm ghost hide-sm", onclick: () => showGroup(kind, g) }, icon("eye", "sm"), "Ansehen"),
      h("button", { class: "btn sm", onclick: () => albumDialog(kind, g, refreshOverview) }, icon("album", "sm"), h("span", { class: "hide-sm" }, "Album"))));
}

async function drawSources(body, params, refreshOverview) {
  const r = await api("/organize/sources");
  clear(body);
  body.append(h("p", { class: "muted", style: { marginTop: 0 } }, "Woher deine Fotos stammen – erkannt an Kamera und Dateinamen. Praktisch z. B. für ein Album „Fujifilm X-S20“ oder um WhatsApp-Bilder zu sammeln."));
  const groups = [["camera", "Kameras & Handys"], ["messenger", "Messenger"], ["screen", "Bildschirm"], ["none", "Sonstige"]];
  for (const [kind, title] of groups) {
    const items = r.items.filter(s => s.kind === kind);
    if (!items.length) continue;
    body.append(h("h2", { class: "section" }, icon(SRC_ICON[kind], "sm"), title),
      h("div", { class: "card pad-0" }, h("div", { class: "list" }, items.map(s => row("source", s, SRC_ICON[kind], refreshOverview)))));
  }
}

async function drawPlaces(body, params, refreshOverview) {
  const r = await api("/organize/places");
  clear(body);
  if (!r.items.length) { body.append(h("div", { class: "card" }, empty("pin", "Keine Orte", "Deine Fotos haben keine GPS-Daten – oder Immich hat die Orte noch nicht ermittelt."))); return; }
  body.append(h("p", { class: "muted", style: { marginTop: 0 } }, "Nach Land und Ort – aus den GPS-Daten deiner Fotos."));
  for (const c of r.items) {
    const cities = h("div", { class: "list hidden" }, c.cities.map(ci => row("place", ci, "pin", refreshOverview)));
    const toggleBtn = h("button", { class: "btn sm ghost", onclick: () => { cities.classList.toggle("hidden"); toggleBtn.textContent = cities.classList.contains("hidden") ? `${num(c.cities.length)} Orte` : "Weniger"; } }, `${num(c.cities.length)} Orte`);
    body.append(h("div", { class: "card pad-0", style: { marginBottom: "12px" } }, h("div", { class: "list" }, row("place", c, "globe", refreshOverview, c.cities.length > 1 ? toggleBtn : null)), cities));
  }
}

async function drawFolders(body, params, refreshOverview) {
  const r = await api("/organize/folders");
  clear(body);
  if (r.random) body.append(h("div", { style: { marginBottom: "16px" } }, callout("info", "Immich legt deine Fotos in eigene Ordner",
    "Weil die Fotos über die App hochgeladen werden, sortiert Immich sie selbst ein (nach Datum oder zufällig). Die Ordner sagen dann wenig – nimm lieber „Ereignisse“ oder „Quellen“.")));
  if (!r.items.length) { body.append(h("div", { class: "card" }, empty("folder", "Keine Ordner"))); return; }
  body.append(h("div", { class: "card pad-0" }, h("div", { class: "list" }, r.items.slice(0, 500).map(f => row("folder", f, "folder", refreshOverview)))));
}

// ---------------------------------------------------------------------------
async function showGroup(kind, g) {
  const r = await api("/group", { query: { kind, key: g.key, limit: 2000 } });
  openSheet((sheet, close) => {
    const grid = new PhotoGrid({ small: true, tapSelects: false });
    grid.add(r.items);
    sheet.append(h("h2", null, g.title), h("p", { class: "sheet-sub" }, [g.subtitle, `${num(r.total)} Fotos und Videos`].filter(Boolean).join(" · ")),
      grid.el, h("div", { class: "sheet-foot" }, h("button", { class: "btn", onclick: () => close() }, "Schließen"),
        h("button", { class: "btn primary", onclick: () => { close(); albumDialog(kind, g); } }, icon("album", "sm"), "Als Album anlegen")));
  }, { wide: true });
}

async function albumDialog(kind, g, refreshOverview) {
  let albums = [];
  try { albums = (await api("/albums")).items; } catch { /* ohne Liste geht auch */ }
  openSheet((sheet, close) => {
    const d = { mode: "new", name: g.album || g.title, album: albums[0]?.id || "" };
    const nameInp = input({ value: d.name, oninput: (e) => { d.name = e.target.value; } });
    const newBox = field("Name des Albums", nameInp, "In Immich änderbar.");
    const exBox = albums.length ? field("Album", select(albums.map(a => ({ value: a.id, label: `${a.name} (${num(a.count)})` })), d.album, { onchange: (e) => { d.album = e.target.value; } })) : null;
    if (exBox) exBox.classList.add("hidden");
    const save = h("button", { class: "btn primary" }, icon("check", "sm"), "Anlegen");
    save.addEventListener("click", () => withBusy(save, async () => {
      try {
        const body = { kind, key: g.key, name: d.name.trim() };
        if (d.mode === "add") { body.album_id = d.album; body.name = albums.find(a => a.id === d.album)?.name; }
        const r = await api("/albums", { method: "POST", body });
        close();
        toast(d.mode === "add" ? "Zum Album hinzugefügt" : "Album angelegt", `${num(r.added)} Fotos · ${body.name}`, "ok",
          { actions: r.url ? [{ label: "In Immich öffnen", onClick: () => window.open(r.url, "_blank", "noopener") }] : [] });
        refreshOverview && refreshOverview();
        window.dispatchEvent(new Event("ih:synced"));
      } catch (e) { errorToast(e); }
    }));
    const modes = albums.length ? segmented([{ value: "new", label: "Neues Album" }, { value: "add", label: "Zu bestehendem" }], "new", (v) => {
      d.mode = v; newBox.classList.toggle("hidden", v !== "new"); exBox.classList.toggle("hidden", v !== "add");
      clear(save).append(icon("check", "sm"), v === "new" ? "Anlegen" : "Hinzufügen");
    }) : null;
    sheet.append(h("h2", null, "Als Album speichern"),
      h("p", { class: "sheet-sub" }, `${num(g.count)} Fotos und Videos aus „${g.title}“${g.in_album ? ` – ${num(g.in_album)} davon sind schon in einem Album` : ""}.`),
      h("div", { class: "stack", style: { gap: "16px" } }, modes, newBox, exBox),
      h("div", { class: "sheet-foot" }, h("button", { class: "btn", onclick: () => close() }, "Abbrechen"), save));
  });
}
