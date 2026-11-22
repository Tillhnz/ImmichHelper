// ===========================================================================
// Fotos: Kacheln, Raster mit Auswahl, große Ansicht, Löschen/Behalten
// ===========================================================================
import { h, icon, clear, api, thumb, videoUrl, immichLink, takenAt, duration, bytes, mp, num, toast, errorToast, confirmDialog, isMobile, state } from "./core.js";

export function tile(a, { badges = [], cls = "" } = {}) {
  const img = h("img", { loading: "lazy", decoding: "async", alt: "", src: thumb(a.id) });
  img.addEventListener("error", () => { img.style.opacity = "0"; }, { once: true });
  const b = [];
  if (a.type === "V") b.push(h("span", { class: "p-badge" }, icon("play"), a.dur ? duration(a.dur) : "Video"));
  if (a.raw) b.push(h("span", { class: "p-badge" }, "RAW"));
  if (a.fav) b.push(h("span", { class: "p-badge" }, icon("heart")));
  b.push(...badges.filter(Boolean));
  return h("div", { class: `ptile ${cls} ${a.mark === "trash" ? "marked" : ""}`, "data-id": a.id, tabindex: "0" },
    img, h("span", { class: "cbx" }, icon("check")), b.length ? h("div", { class: "p-badges" }, b) : null);
}

/** Raster mit Auswahl. Tippen wählt aus (oder öffnet, je nach Modus), langes Drücken/Lupe öffnet die große Ansicht. */
export class PhotoGrid {
  constructor({ badge, onSelection, tapSelects = true, small = false, actions } = {}) {
    this.items = [];
    this.sel = new Set();
    this.badge = badge;
    this.onSelection = onSelection || (() => {});
    this.tapSelects = tapSelects;
    this.actions = actions;
    this.el = h("div", { class: `pgrid ${small ? "small" : ""}` });
    this.tiles = new Map();
  }

  add(items) {
    for (const a of items) {
      if (this.tiles.has(a.id)) continue;
      const i = this.items.length;
      this.items.push(a);
      const t = tile(a, { badges: this.badge ? [this.badge(a)] : [] });
      if (!isMobile()) {
        const z = h("button", { class: "p-zoom", title: "Groß ansehen", onclick: (e) => { e.stopPropagation(); this.open(a.id); } }, icon("maximize", "sm"));
        t.append(z);
      }
      t.querySelector(".cbx").addEventListener("click", (e) => { e.stopPropagation(); this.toggle(a.id); });
      let timer = null, long = false, sx = 0, sy = 0;
      t.addEventListener("pointerdown", (e) => {
        long = false; sx = e.clientX; sy = e.clientY;
        timer = setTimeout(() => { long = true; this.open(a.id); }, 480);
      });
      const cancel = () => clearTimeout(timer);
      t.addEventListener("pointermove", (e) => { if (Math.abs(e.clientX - sx) + Math.abs(e.clientY - sy) > 10) cancel(); });
      t.addEventListener("pointerup", cancel);
      t.addEventListener("pointercancel", cancel);
      t.addEventListener("contextmenu", (e) => { if (isMobile()) e.preventDefault(); });
      t.addEventListener("click", () => {
        if (long) return;
        if (this.tapSelects || this.sel.size) this.toggle(a.id); else this.open(a.id);
      });
      t.addEventListener("keydown", (e) => { if (e.key === " " || e.key === "Enter") { e.preventDefault(); e.key === "Enter" ? this.open(a.id) : this.toggle(a.id); } });
      this.tiles.set(a.id, t);
      this.el.append(t);
      void i;
    }
  }

  toggle(id, on) {
    const t = this.tiles.get(id);
    if (!t) return;
    const v = on === undefined ? !this.sel.has(id) : on;
    v ? this.sel.add(id) : this.sel.delete(id);
    t.classList.toggle("sel", v);
    this.el.classList.toggle("selecting", this.sel.size > 0);
    this.onSelection(this);
  }

  selectAll(on = true) { for (const a of this.items) this.toggle(a.id, on); }
  selected() { return this.items.filter(a => this.sel.has(a.id)); }
  selectedBytes() { return this.selected().reduce((s, a) => s + (a.size || 0), 0); }

  remove(ids) {
    const set = new Set(ids);
    for (const id of set) { this.tiles.get(id)?.remove(); this.tiles.delete(id); this.sel.delete(id); }
    this.items = this.items.filter(a => !set.has(a.id));
    this.el.classList.toggle("selecting", this.sel.size > 0);
    this.onSelection(this);
  }

  open(id) {
    const i = this.items.findIndex(a => a.id === id);
    if (i >= 0) openViewer(this.items, i, { grid: this, actions: this.actions });
  }
}

// ---------------------------------------------------------------------------
// Große Ansicht
// ---------------------------------------------------------------------------
export function openViewer(items, index, { grid, actions } = {}) {
  let i = index;
  const stage = h("div", { class: "v-stage" });
  const title = h("div", { class: "v-title" });
  const info = h("div", { class: "v-info" });
  const selBtn = grid ? h("button", { class: "btn sm", onclick: () => { grid.toggle(items[i].id); draw(); } }) : null;
  const ext = h("a", { class: "btn icon", target: "_blank", rel: "noopener", title: "In Immich öffnen" }, icon("external"));
  const dl = h("a", { class: "btn icon", title: "Original herunterladen" }, icon("download"));
  const close = () => { v.remove(); document.removeEventListener("keydown", onKey, true); };
  const v = h("div", { class: "viewer", role: "dialog" },
    h("div", { class: "v-top" }, title, selBtn, actions ? actions.map(a => h("button", { class: `btn sm ${a.cls || ""}`, onclick: async () => {
      const it = items[i];
      const r = await a.run(it);
      if (r === "remove") { items.splice(i, 1); if (!items.length) return close(); if (i >= items.length) i = items.length - 1; }
      draw();
    } }, a.icon ? icon(a.icon, "sm") : null, h("span", { class: "lbl" }, a.label))) : null, ext, dl,
      h("button", { class: "btn icon", onclick: close, "aria-label": "Schließen" }, icon("x"))),
    stage,
    h("button", { class: "v-nav prev", onclick: () => go(-1) }, icon("chevronLeft")),
    h("button", { class: "v-nav next", onclick: () => go(1) }, icon("chevronRight")),
    info);
  function go(d) { const n = i + d; if (n >= 0 && n < items.length) { i = n; draw(); } }
  function draw() {
    const a = items[i];
    clear(stage);
    if (a.type === "V") {
      stage.append(h("video", { src: videoUrl(a.id), controls: true, autoplay: true, playsinline: true, poster: thumb(a.id, "preview") }));
    } else {
      const low = h("img", { src: thumb(a.id), alt: "" });
      const hi = h("img", { src: thumb(a.id, "preview"), alt: "", style: { opacity: "0" } });
      hi.addEventListener("load", () => { hi.style.opacity = "1"; low.remove(); });
      stage.append(low, hi);
    }
    clear(title).append(h("strong", null, a.name), h("span", null, `${takenAt(a)} · ${i + 1} von ${items.length}`));
    if (selBtn) {
      const on = grid.sel.has(a.id);
      clear(selBtn).append(icon(on ? "checkCircle" : "selectAll", "sm"), h("span", { class: "lbl" }, on ? "Ausgewählt" : "Auswählen"));
      selBtn.classList.toggle("on", on);
    }
    const link = immichLink(a.id);
    ext.href = link || "#"; ext.style.display = link ? "" : "none";
    dl.href = `/api/original/${a.id}`; dl.setAttribute("download", a.name);
    const chip = (ico, t) => t ? h("span", { class: "chip-d" }, icon(ico), t) : null;
    clear(info).append(
      chip("image", [a.w && a.h ? `${a.w} × ${a.h}` : null, mp(a)].filter(Boolean).join(" · ")),
      chip("hdd", a.size ? bytes(a.size) : null),
      chip("camera", a.cam),
      chip("pin", a.place),
      a.sharp != null ? chip("blur", `Schärfe ${Math.round(a.sharp)}`) : null,
      a.type === "V" ? chip("film", duration(a.dur)) : null);
  }
  const onKey = (e) => {
    if (e.key === "Escape") { e.stopPropagation(); close(); }
    else if (e.key === "ArrowLeft") go(-1);
    else if (e.key === "ArrowRight") go(1);
    else if (e.key === " " && grid) { e.preventDefault(); grid.toggle(items[i].id); draw(); }
  };
  // Wischen zum Blättern
  let sx = null;
  stage.addEventListener("touchstart", (e) => { sx = e.touches[0].clientX; }, { passive: true });
  stage.addEventListener("touchend", (e) => { if (sx === null) return; const dx = e.changedTouches[0].clientX - sx; if (Math.abs(dx) > 50) go(dx < 0 ? 1 : -1); sx = null; });
  document.addEventListener("keydown", onKey, true);
  document.body.append(v);
  draw();
  return close;
}

// ---------------------------------------------------------------------------
// Auswahl-Leiste
// ---------------------------------------------------------------------------
export function selectionBar(grid, { onTrash, onKeep, extra } = {}) {
  const bar = h("div", { class: "selbar hidden" });
  const update = () => {
    const n = grid.sel.size;
    bar.classList.toggle("hidden", n === 0);
    clear(bar).append(
      h("span", { class: "count" }, `${num(n)} ausgewählt · ${bytes(grid.selectedBytes())}`),
      h("button", { class: "btn sm", onclick: () => grid.selectAll(grid.sel.size < grid.items.length) }, icon("selectAll", "sm"), h("span", null, grid.sel.size < grid.items.length ? "Alle" : "Keine")),
      extra ? extra(grid) : null,
      onKeep ? h("button", { class: "btn sm", onclick: () => onKeep(grid.selected()) }, icon("check", "sm"), h("span", null, "Behalten")) : null,
      onTrash ? h("button", { class: "btn sm danger-ghost", onclick: () => onTrash(grid.selected()) }, icon("trash", "sm"), h("span", null, "Löschen")) : null,
      h("button", { class: "btn sm icon", title: "Auswahl aufheben", onclick: () => grid.selectAll(false) }, icon("x", "sm")));
  };
  const prev = grid.onSelection;
  grid.onSelection = (g) => { prev(g); update(); };
  update();
  return bar;
}

// ---------------------------------------------------------------------------
// Aktionen
// ---------------------------------------------------------------------------
export async function trashItems(items, { label = "Aussortiert", confirm = true, rawFollow } = {}) {
  if (!items.length) return null;
  const n = items.length;
  const size = items.reduce((s, a) => s + (a.size || 0), 0);
  const hasJpgFromRaw = state.settings?.raw_follow && items.some(a => !a.raw);
  if (confirm && !(await confirmDialog({
    title: `${num(n)} ${n === 1 ? "Foto" : "Fotos"} in den Papierkorb?`,
    text: `Sie landen im Immich-Papierkorb (${bytes(size)}) und lassen sich dort oder im Verlauf wiederherstellen, bis der Papierkorb geleert wird.`
      + (hasJpgFromRaw ? " Zugehörige RAW-Dateien werden mitgelöscht." : ""),
    confirmText: "In den Papierkorb", danger: true,
  }))) return null;
  try {
    const body = { ids: items.map(a => a.id), label };
    if (rawFollow !== undefined) body.raw_follow = rawFollow;
    const r = await api("/trash", { method: "POST", body });
    undoToast(r, `${num(r.count)} in den Papierkorb`, r.raw ? `inkl. ${num(r.raw)} RAW · ${bytes(r.bytes)}` : bytes(r.bytes));
    window.dispatchEvent(new Event("ih:changed"));
    return r;
  } catch (e) { errorToast(e); return null; }
}

export function undoToast(r, title, text) {
  toast(title, text, "ok", { timeout: 7000, actions: r.log ? [{ label: "Rückgängig", onClick: async () => {
    try { await api(`/history/${r.log}/restore`, { method: "POST" }); toast("Wiederhergestellt"); window.dispatchEvent(new Event("ih:changed")); window.dispatchEvent(new Event("ih:reload")); }
    catch (e) { errorToast(e); }
  } }] : [] });
}

export async function keepItems(items) {
  if (!items.length) return;
  try {
    await api("/marks", { method: "POST", body: { ids: items.map(a => a.id), decision: "keep" } });
    toast(`${num(items.length)} behalten`, "Werden nicht mehr vorgeschlagen.", "ok", { timeout: 3000 });
    window.dispatchEvent(new Event("ih:changed"));
    return true;
  } catch (e) { errorToast(e); return false; }
}
