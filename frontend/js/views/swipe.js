// ===========================================================================
// Wischen: links = aussortieren, rechts = behalten, hoch = Favorit
// Aussortiertes wird erst vorgemerkt und mit einem Tipp gesammelt in den Papierkorb gelegt.
// ===========================================================================
import { h, icon, clear, api, state, pageHead, callout, loader, bytes, num, toast, errorToast, confirmDialog, takenAt, duration, thumb, videoUrl, monthLabel, withBusy, empty } from "../core.js";
import { catByKey } from "./clean.js";
import { PhotoGrid, undoToast, retryOnError } from "../photos.js";

const THRESH = 110;

export async function renderSwipe({ el, page, source, refreshOverview }) {
  if (!source) return renderPicker({ el, page, refreshOverview });

  const label = sourceLabel(source);
  const pendingBox = h("div");
  const counter = h("span", { class: "muted small num" });
  el.append(h("a", { class: "back", href: "#/swipe" }, icon("chevronLeft", "sm"), "Andere Auswahl"));
  const wrap = h("div", { class: "swipe-wrap" });
  el.append(wrap);
  const stage = h("div", { class: "swipe-stage" });
  const undoBtn = h("button", { class: "sa undo", title: "Rückgängig (Z)", disabled: true }, icon("undo"));
  const trashBtn = h("button", { class: "sa trash", title: "Aussortieren (←)" }, icon("x"));
  const favBtn = h("button", { class: "sa fav", title: "Favorit (↑)" }, icon("heart"));
  const keepBtn = h("button", { class: "sa keep", title: "Behalten (→)" }, icon("check"));
  wrap.append(h("div", { class: "swipe-top" }, h("div", { style: { minWidth: 0 } }, h("div", { style: { fontWeight: 700, fontSize: "18px" } }, label), counter), h("span", { class: "spacer" }), pendingBox),
    stage, h("div", { class: "swipe-actions" }, undoBtn, trashBtn, favBtn, keepBtn),
    h("div", { class: "swipe-hint" }, "Nach links wischen: aussortieren · nach rechts: behalten · nach oben: Favorit. Am Rechner: Pfeiltasten, Z = rückgängig."));

  const preloaded = new Set(), keep = [];
  let queue = [], total = 0, since = 0, pending = { count: 0, bytes: 0 }, busy = false, loading = false;
  const done = [];

  async function fetchMore() {
    if (loading) return;
    loading = true;
    try {
      const r = await api("/swipe", { query: { source, limit: 120 } });
      const have = new Set([...queue.map(a => a.id), ...done.map(d => d.a.id)]);
      queue.push(...r.items.filter(a => !have.has(a.id)));
      total = r.total; since = 0;
      pending = r.pending;
    } catch (e) { errorToast(e); }
    loading = false;
  }

  function drawPending() {
    clear(pendingBox);
    if (!pending.count) return;
    const btn = h("button", { class: "btn sm danger" }, "Jetzt löschen");
    btn.addEventListener("click", () => commit(btn));
    pendingBox.append(h("span", { class: "pending-pill" }, icon("trash", "sm"), `${num(pending.count)} vorgemerkt · ${bytes(pending.bytes)}`, btn));
  }

  async function commit(btn) {
    if (!(await confirmDialog({ title: `${num(pending.count)} Fotos in den Papierkorb?`,
      text: `Alles, was du nach links gewischt hast (${bytes(pending.bytes)}). Wiederherstellen geht im Verlauf oder im Immich-Papierkorb.`,
      confirmText: "In den Papierkorb", danger: true }))) return;
    await withBusy(btn, async () => {
      try {
        const r = await api("/marks/commit", { method: "POST", body: {} });
        undoToast(r, `${num(r.count)} in den Papierkorb`, r.raw ? `inkl. ${num(r.raw)} RAW · ${bytes(r.bytes)}` : bytes(r.bytes));
        pending = { count: 0, bytes: 0 };
        done.length = 0; undoBtn.disabled = true;
        drawPending(); refreshOverview();
      } catch (e) { errorToast(e); }
    });
  }

  function card(a, back = false) {
    // Erst das kleine Vorschaubild (meist schon geladen), darüber die große Vorschau, sobald sie da ist – nie ein schwarzes Bild
    const low = h("img", { class: "sc-low", src: thumb(a.id), alt: "", draggable: "false" });
    let media;
    if (a.type === "V") {
      media = h("video", { src: videoUrl(a.id), poster: thumb(a.id, "preview"), controls: true, playsinline: true, preload: "metadata", muted: true });
    } else {
      media = h("img", { class: "sc-hi", src: thumb(a.id, "preview"), alt: "", draggable: "false", decoding: "async", fetchpriority: back ? "auto" : "high" });
      const show = () => media.classList.add("ready");
      if (media.complete && media.naturalWidth) show(); else media.addEventListener("load", show, { once: true });
      retryOnError(media);
    }
    retryOnError(low);
    const tags = [];
    if (a.sharp != null && a.sharp < (state.settings.blur_threshold || 35)) tags.push(h("span", { class: "badge bad" }, "wirkt unscharf"));
    if (a.type === "V") tags.push(h("span", { class: "badge" }, `Video ${duration(a.dur)}`));
    if (a.raw) tags.push(h("span", { class: "badge" }, "RAW"));
    if (a.size) tags.push(h("span", { class: "badge" }, bytes(a.size)));
    return h("div", { class: `swipe-card ${back ? "back" : ""}`, "data-id": a.id },
      low, media,
      h("div", { class: "sc-stamp keep" }, "Behalten"), h("div", { class: "sc-stamp trash" }, "Weg"), h("div", { class: "sc-stamp fav" }, "Favorit"),
      h("div", { class: "sc-info" }, h("strong", null, takenAt(a)), h("span", null, [a.place, a.cam].filter(Boolean).join(" · ") || a.name),
        tags.length ? h("div", { class: "sc-tags" }, tags) : null));
  }

  function draw() {
    clear(stage);
    counter.textContent = queue.length ? `noch ${num(Math.max(total - since, queue.length))} offen` : "";
    drawPending();
    const a = queue[0];
    if (!a) {
      trashBtn.disabled = keepBtn.disabled = favBtn.disabled = true;
      stage.append(h("div", { class: "card", style: { height: "100%", display: "grid", placeItems: "center" } },
        empty("checkCircle", "Alles gesichtet!", pending.count ? `Du hast ${num(pending.count)} Fotos zum Löschen vorgemerkt – oben „Jetzt löschen“ tippen.` : "Hier gibt es nichts mehr zu entscheiden.",
          h("a", { class: "btn", href: "#/swipe" }, "Andere Auswahl"))));
      return;
    }
    trashBtn.disabled = keepBtn.disabled = favBtn.disabled = false;
    if (queue[1]) stage.append(card(queue[1], true));
    const top = card(a);
    stage.append(top);
    attachDrag(top);
    // Die nächsten Bilder schon laden (klein und groß), damit sie beim Wischen sofort da sind
    const next = queue.slice(1, 9).filter(n => !preloaded.has(n.id));
    for (const n of next) { preloaded.add(n.id); const lo = new Image(); lo.src = thumb(n.id); keep.push(lo); }
    for (const n of next) if (n.type !== "V") { const hi = new Image(); hi.decoding = "async"; hi.src = thumb(n.id, "preview"); hi.decode?.().catch(() => {}); keep.push(hi); }
    while (keep.length > 40) keep.shift();
  }

  function attachDrag(c) {
    let sx = 0, sy = 0, dx = 0, dy = 0, dragging = false;
    const stamps = { keep: c.querySelector(".sc-stamp.keep"), trash: c.querySelector(".sc-stamp.trash"), fav: c.querySelector(".sc-stamp.fav") };
    c.addEventListener("pointerdown", (e) => {
      if (e.target.tagName === "VIDEO" && e.offsetY > e.target.clientHeight - 60) return; // Videosteuerung bedienen
      dragging = true; sx = e.clientX; sy = e.clientY; dx = dy = 0;
      c.setPointerCapture(e.pointerId); c.style.transition = "none"; c.style.cursor = "grabbing";
    });
    c.addEventListener("pointermove", (e) => {
      if (!dragging) return;
      dx = e.clientX - sx; dy = e.clientY - sy;
      c.style.transform = `translate(${dx}px, ${dy}px) rotate(${dx / 18}deg)`;
      stamps.keep.style.opacity = Math.max(0, Math.min(1, dx / THRESH));
      stamps.trash.style.opacity = Math.max(0, Math.min(1, -dx / THRESH));
      stamps.fav.style.opacity = Math.abs(dx) < THRESH / 2 ? Math.max(0, Math.min(1, -dy / THRESH)) : 0;
    });
    const end = () => {
      if (!dragging) return;
      dragging = false; c.style.cursor = "";
      if (dx > THRESH) decide("keep", c, dx, dy);
      else if (dx < -THRESH) decide("trash", c, dx, dy);
      else if (dy < -THRESH && Math.abs(dx) < THRESH) decide("fav", c, dx, dy);
      else { c.style.transition = "transform .25s ease"; c.style.transform = ""; Object.values(stamps).forEach(s => { s.style.opacity = 0; }); }
    };
    c.addEventListener("pointerup", end);
    c.addEventListener("pointercancel", end);
  }

  async function decide(decision, c, dx = 0, dy = 0) {
    if (busy || !queue.length) return;
    const a = queue[0];
    busy = true;
    c = c || stage.querySelector(".swipe-card:not(.back)");
    if (c) {
      const x = decision === "keep" ? window.innerWidth : decision === "trash" ? -window.innerWidth : dx;
      const y = decision === "fav" ? -window.innerHeight : dy;
      c.style.transition = "transform .28s ease, opacity .28s ease";
      c.style.transform = `translate(${x}px, ${y}px) rotate(${x / 22}deg)`;
      c.style.opacity = "0";
      c.querySelector(`.sc-stamp.${decision}`).style.opacity = 1;
    }
    queue.shift();
    setTimeout(() => { busy = false; draw(); }, 200);
    try {
      const r = await api("/marks", { method: "POST", body: { ids: [a.id], decision } });
      pending = r.pending;
      done.push({ a, decision }); since++;
      undoBtn.disabled = false;
      drawPending();
    } catch (e) { errorToast(e); queue.unshift(a); draw(); return; }
    if (queue.length < 15) { await fetchMore(); if (!stage.querySelector(".swipe-card")) draw(); }
  }

  async function undo() {
    const last = done.pop();
    if (!last) return;
    undoBtn.disabled = !done.length;
    try {
      const r = await api("/marks", { method: "POST", body: { ids: [last.a.id], decision: "none" } });
      pending = r.pending; since--;
      queue.unshift({ ...last.a, mark: null });
      draw();
    } catch (e) { errorToast(e); }
  }

  trashBtn.addEventListener("click", () => decide("trash"));
  keepBtn.addEventListener("click", () => decide("keep"));
  favBtn.addEventListener("click", () => decide("fav"));
  undoBtn.addEventListener("click", undo);
  page.on("keydown", (e) => {
    if (document.querySelector(".overlay, .viewer") || e.target.tagName === "INPUT") return;
    if (e.key === "ArrowLeft") { e.preventDefault(); decide("trash"); }
    else if (e.key === "ArrowRight") { e.preventDefault(); decide("keep"); }
    else if (e.key === "ArrowUp") { e.preventDefault(); decide("fav"); }
    else if (e.key === "z" || e.key === "Backspace") { e.preventDefault(); undo(); }
  });

  stage.append(loader());
  await fetchMore();
  draw();
}

function sourceLabel(s) {
  if (s === "all") return "Alle Fotos";
  if (s === "random") return "Zufällige Fotos";
  if (s.startsWith("month:")) return monthLabel(s.slice(6));
  if (s.startsWith("cat:")) return catByKey[s.slice(4)]?.title || "Auswahl";
  if (s.startsWith("event:")) return "Ereignis";
  return "Auswahl";
}

// ---------------------------------------------------------------------------
// Auswahl, was gesichtet werden soll
// ---------------------------------------------------------------------------
async function renderPicker({ el, page, refreshOverview }) {
  el.append(pageHead("Wischen", "Foto für Foto entscheiden – wie bei einer Dating-App, nur für deine Bilder. Was du schon gesichtet hast, kommt nicht wieder."));
  const body = h("div", null, loader());
  el.append(body);
  async function draw() {
    let months, ov, events;
    try {
      [months, ov, events] = await Promise.all([api("/months"), refreshOverview(), api("/organize/events")]);
    } catch (e) { clear(body).append(callout("bad", null, e.message)); return; }
    clear(body);
    if (ov?.pending?.count) {
      const btn = h("button", { class: "btn danger" }, icon("trash", "sm"), "Jetzt in den Papierkorb");
      btn.addEventListener("click", async () => {
        if (!(await confirmDialog({ title: `${num(ov.pending.count)} vorgemerkte Fotos löschen?`, text: `Sie kommen in den Immich-Papierkorb (${bytes(ov.pending.bytes)}).`, confirmText: "In den Papierkorb", danger: true }))) return;
        await withBusy(btn, async () => {
          try { const r = await api("/marks/commit", { method: "POST", body: {} }); undoToast(r, `${num(r.count)} in den Papierkorb`, bytes(r.bytes)); draw(); }
          catch (e) { errorToast(e); }
        });
      });
      const look = h("button", { class: "btn", onclick: () => showPending(draw) }, icon("eye", "sm"), "Ansehen");
      body.append(h("div", { class: "card", style: { marginBottom: "18px" } }, h("div", { class: "row wrap" },
        h("div", { style: { flex: 1, minWidth: "220px" } }, h("strong", null, `${num(ov.pending.count)} Fotos vorgemerkt`), h("div", { class: "muted small" }, `${bytes(ov.pending.bytes)} – noch nicht gelöscht`)),
        look, btn)));
    }
    const open = months.items.reduce((s, m) => s + m.open, 0);
    const item = (href, ico, title, meta, n) => h("a", { class: `src-item ${n === 0 ? "done" : ""}`, href },
      typeof ico === "string" ? h("div", { class: "s-ico", style: { width: "42px", height: "42px", borderRadius: "11px", display: "grid", placeItems: "center", background: "var(--accent-soft)", color: "var(--accent)", flex: "none" } }, icon(ico)) : ico,
      h("div", { class: "grow" }, h("div", { class: "title" }, title), h("div", { class: "meta" }, meta)), icon("chevronRight", "sm"));
    body.append(h("div", { class: "src-list" },
      item("#/swipe?source=all", "photos", "Alle Fotos", `${num(open)} noch nicht gesichtet`, open),
      item("#/swipe?source=random", "sparkle", "Zufällig", "Quer durch die Jahre", open)));
    if (ov) {
      const cats = ["blurry", "dark", "screenshots", "messenger", "shortvideos"].filter(k => ov.cats[k].count);
      if (cats.length) body.append(h("h2", { class: "section" }, icon("broom", "sm"), "Vorschläge durchgehen"),
        h("div", { class: "src-list" }, cats.map(k => item(`#/swipe?source=cat:${k}`, catByKey[k].icon, catByKey[k].title, `${num(ov.cats[k].count)} Treffer`, ov.cats[k].count))));
    }
    if (events.items.length) body.append(h("h2", { class: "section" }, icon("album", "sm"), "Ereignisse"),
      h("div", { class: "src-list" }, events.items.slice(0, 12).map(e => item(`#/swipe?source=event:${encodeURIComponent(e.key)}`,
        h("img", { src: thumb(e.cover), alt: "", loading: "lazy" }), e.title, [e.subtitle, `${num(e.count)} Fotos`].filter(Boolean).join(" · ")))));
    body.append(h("h2", { class: "section" }, icon("calendar", "sm"), "Nach Monat"),
      h("div", { class: "src-list" }, months.items.map(m => item(`#/swipe?source=month:${m.month}`, "calendar", m.label,
        m.open ? `${num(m.open)} von ${num(m.total)} offen` : `alle ${num(m.total)} gesichtet`, m.open))));
  }
  page.on("ih:synced", draw);
  await draw();
}

async function showPending(onDone) {
  const { openSheet } = await import("../core.js");
  const r = await api("/marks/pending");
  openSheet((sheet, close) => {
    const grid = new PhotoGrid({ small: true });
    grid.add(r.items);
    const undoSel = h("button", { class: "btn" }, icon("undo", "sm"), "Auswahl doch behalten");
    undoSel.addEventListener("click", () => withBusy(undoSel, async () => {
      const ids = [...grid.sel];
      if (!ids.length) return toast("Erst Fotos antippen", "", "info");
      try { await api("/marks", { method: "POST", body: { ids, decision: "none" } }); grid.remove(ids); onDone(); } catch (e) { errorToast(e); }
    }));
    sheet.append(h("h2", null, "Vorgemerkt zum Löschen"), h("p", { class: "sheet-sub" }, `${num(r.total)} Fotos · ${bytes(r.bytes)}. Antippen und „doch behalten“, um sie zurückzuholen.`),
      grid.el, h("div", { class: "sheet-foot" }, undoSel, h("button", { class: "btn primary", onclick: () => close() }, "Fertig")));
  }, { wide: true });
}
