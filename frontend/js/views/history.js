// ===========================================================================
// Verlauf: was ImmichHelper gemacht hat – mit Wiederherstellen
// ===========================================================================
import { h, icon, clear, api, pageHead, callout, loader, num, bytes, toast, errorToast, confirmDialog, thumb, dateTime, relTime, withBusy, empty } from "../core.js";

const KIND = { trash: ["trash", "In den Papierkorb"], album: ["album", "Album"], stack: ["layers", "Gestapelt"] };

export async function renderHistory({ el, page, refreshOverview }) {
  el.append(pageHead("Verlauf", "Was du mit ImmichHelper aufgeräumt hast. Gelöschtes liegt im Immich-Papierkorb und lässt sich hier zurückholen – bis der Papierkorb geleert wird (Immich: standardmäßig nach 30 Tagen)."));
  const body = h("div", null, loader());
  el.append(body);
  async function draw() {
    let r;
    try { r = await api("/history"); } catch (e) { clear(body).append(callout("bad", null, e.message)); return; }
    clear(body);
    const emptyBtn = h("button", { class: "btn danger-ghost" }, icon("trash", "sm"), "Immich-Papierkorb leeren");
    emptyBtn.addEventListener("click", async () => {
      if (!(await confirmDialog({ title: "Papierkorb endgültig leeren?",
        text: "Alles im Immich-Papierkorb deines Kontos wird endgültig gelöscht – auch, was du in Immich selbst gelöscht hast. Erst danach wird der Speicher auf der NAS frei. Das lässt sich nicht rückgängig machen.",
        confirmText: "Endgültig löschen", danger: true }))) return;
      await withBusy(emptyBtn, async () => {
        try { const res = await api("/trash/empty", { method: "POST" }); toast("Papierkorb geleert", res.count ? `${num(res.count)} Dateien endgültig gelöscht.` : "Immich räumt im Hintergrund auf."); draw(); refreshOverview(); }
        catch (e) { errorToast(e); }
      });
    });
    body.append(h("div", { class: "card", style: { marginBottom: "18px" } }, h("div", { class: "row wrap", style: { gap: "16px" } },
      h("div", { class: "stat", style: { flex: 1, minWidth: "200px" } }, h("span", { class: "label" }, icon("broom", "sm"), "Aussortiert"),
        h("span", { class: "value num" }, num(r.freed_count), h("small", null, "Dateien")), h("span", { class: "sub" }, `${bytes(r.freed)} – frei, sobald der Papierkorb geleert ist`)),
      emptyBtn)));
    if (!r.items.length) { body.append(h("div", { class: "card" }, empty("history", "Noch nichts passiert", "Sobald du Fotos aussortierst oder Alben anlegst, steht es hier."))); return; }
    body.append(h("div", { class: "card pad-0" }, h("div", { class: "list" }, r.items.map(it => {
      const [ico] = KIND[it.kind] || ["info"];
      let action = null;
      if (it.kind === "trash") {
        if (it.restored === -1) action = h("span", { class: "badge" }, "endgültig gelöscht");
        else if (it.restored) action = h("span", { class: "badge ok" }, icon("undo", "sm"), "wiederhergestellt");
        else {
          action = h("button", { class: "btn sm" }, icon("undo", "sm"), h("span", { class: "hide-sm" }, "Wiederherstellen"));
          action.addEventListener("click", () => withBusy(action, async () => {
            try { const res = await api(`/history/${it.id}/restore`, { method: "POST" }); toast("Wiederhergestellt", `${num(res.count)} Dateien sind wieder in Immich.`); draw(); refreshOverview(); }
            catch (e) { errorToast(e); }
          }));
        }
      }
      return h("div", { class: "list-item" },
        h("div", { class: "folder-ico", style: { width: "38px", height: "38px", borderRadius: "11px", display: "grid", placeItems: "center", background: "var(--surface-3)", flex: "none" } }, icon(ico, "sm")),
        h("div", { class: "grow" }, h("div", { class: "title" }, it.label),
          h("div", { class: "meta", title: dateTime(it.ts) }, [relTime(it.ts), `${num(it.count)} ${it.count === 1 ? "Datei" : "Dateien"}`, it.bytes ? bytes(it.bytes) : null].filter(Boolean).join(" · "))),
        h("div", { class: "hist-covers hide-sm" }, it.kind !== "stack" && it.restored !== -1 ? it.covers.slice(0, 4).map(id => h("img", { src: thumb(id), loading: "lazy", alt: "", onerror: (e) => e.target.remove() })) : null),
        h("div", { class: "end" }, action));
    }))));
  }
  page.on("ih:reload", draw);
  await draw();
}
