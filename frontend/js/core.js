// ===========================================================================
// Kern: DOM-Helfer, Icons, API, Formatierung, Toasts, Dialoge
// (gleiche Bausteine wie in der Proxmox Zentrale)
// ===========================================================================

for (const proto of [Element.prototype, DocumentFragment.prototype]) {
  for (const m of ["append", "prepend", "replaceChildren"]) {
    const orig = proto[m];
    proto[m] = function (...nodes) { return orig.apply(this, nodes.flat(Infinity).filter(n => n !== null && n !== undefined && n !== false)); };
  }
}

export const state = { user: null, version: "", immich: "", settings: {}, overview: null };

// ---------- DOM ----------
export function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  if (attrs) {
    for (const [k, v] of Object.entries(attrs)) {
      if (v === null || v === undefined || v === false) continue;
      if (k === "class") el.className = v;
      else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
      else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2).toLowerCase(), v);
      else if (k === "html") el.innerHTML = v;
      else if (v === true) el.setAttribute(k, "");
      else el.setAttribute(k, v);
    }
  }
  appendAll(el, children);
  return el;
}
function appendAll(el, children) {
  for (const c of children) {
    if (c === null || c === undefined || c === false) continue;
    if (Array.isArray(c)) appendAll(el, c);
    else if (c instanceof Node) el.appendChild(c);
    else el.appendChild(document.createTextNode(String(c)));
  }
}
export function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); return el; }

// ---------- Icons ----------
const P = {
  home: '<path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V20a1 1 0 0 0 1 1h4v-6h4v6h4a1 1 0 0 0 1-1V9.5"/>',
  server: '<rect x="3" y="4" width="18" height="7" rx="2"/><rect x="3" y="13" width="18" height="7" rx="2"/><path d="M7 7.5h.01M7 16.5h.01M11 7.5h6M11 16.5h6"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  apps: '<rect x="3.5" y="3.5" width="7" height="7" rx="2"/><rect x="13.5" y="3.5" width="7" height="7" rx="2"/><rect x="3.5" y="13.5" width="7" height="7" rx="2"/><rect x="13.5" y="13.5" width="7" height="7" rx="2"/>',
  archive: '<rect x="3" y="4" width="18" height="5" rx="1.5"/><path d="M5 9v9a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V9M10 13h4"/>',
  refresh: '<path d="M20 11a8 8 0 0 0-14.3-4.9L4 8"/><path d="M4 4v4h4"/><path d="M4 13a8 8 0 0 0 14.3 4.9L20 16"/><path d="M20 20v-4h-4"/>',
  list: '<path d="M9 6h11M9 12h11M9 18h11"/><path d="M4.5 6h.01M4.5 12h.01M4.5 18h.01"/>',
  power: '<path d="M12 3v8"/><path d="M6.3 6.8a8 8 0 1 0 11.4 0"/>',
  play: '<path d="M7 4.5v15l12-7.5z"/>',
  music: '<path d="M9 18V5l11-2v13"/><circle cx="6.5" cy="18" r="2.5"/><circle cx="17.5" cy="16" r="2.5"/>',
  speaker: '<rect x="5" y="2.5" width="14" height="19" rx="2.5"/><circle cx="12" cy="14.5" r="3.5"/><path d="M12 7h.01"/>',
  volume: '<path d="M4 9.5v5h3.5L12 19V5L7.5 9.5z"/><path d="M15.5 9a4 4 0 0 1 0 6M18.5 6.5a8 8 0 0 1 0 11"/>',
  cable: '<path d="M7 3v5M11 3v5M5 8h8v3a4 4 0 0 1-8 0zM9 15v2a4 4 0 0 0 8 0V9a3 3 0 0 1 3-3"/>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="2"/>',
  restart: '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/>',
  trash: '<path d="M4 7h16M10 11v6M14 11v6"/><path d="M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3"/>',
  terminal: '<rect x="3" y="4" width="18" height="16" rx="2.5"/><path d="m7 9 3 3-3 3M13 15h4"/>',
  cpu: '<rect x="6" y="6" width="12" height="12" rx="2"/><rect x="9.5" y="9.5" width="5" height="5" rx="1"/><path d="M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3"/>',
  memory: '<rect x="2.5" y="7" width="19" height="10" rx="2"/><path d="M6 11v2M10 11v2M14 11v2M18 11v2M6 17v3M18 17v3"/>',
  disk: '<ellipse cx="12" cy="6" rx="8" ry="3"/><path d="M4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6"/><path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/>',
  network: '<rect x="9" y="3" width="6" height="5" rx="1"/><rect x="3" y="16" width="6" height="5" rx="1"/><rect x="15" y="16" width="6" height="5" rx="1"/><path d="M12 8v4M6 16v-2h12v2"/>',
  logout: '<path d="M15 4h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-3"/><path d="M10 17l-5-5 5-5M5 12h11"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
  check: '<path d="M5 12.5 10 17 19 7"/>',
  checkCircle: '<circle cx="12" cy="12" r="9"/><path d="m8 12.5 3 3 5-6"/>',
  x: '<path d="M6 6l12 12M18 6 6 18"/>',
  alert: '<path d="M12 3 2 20h20z"/><path d="M12 10v4M12 17h.01"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
  xCircle: '<circle cx="12" cy="12" r="9"/><path d="m9 9 6 6M15 9l-6 6"/>',
  chevronRight: '<path d="m9 6 6 6-6 6"/>',
  chevronLeft: '<path d="m15 6-6 6 6 6"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  camera: '<path d="M4 8a2 2 0 0 1 2-2h2l1.5-2h5L16 6h2a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2z"/><circle cx="12" cy="13" r="3.5"/>',
  download: '<path d="M12 4v11M7 10l5 5 5-5M5 20h14"/>',
  copy: '<rect x="8.5" y="8.5" width="12" height="12" rx="2.5"/><path d="M15.5 8.5V6a2.5 2.5 0 0 0-2.5-2.5H6A2.5 2.5 0 0 0 3.5 6v7A2.5 2.5 0 0 0 6 15.5h2.5"/>',
  more: '<circle cx="5" cy="12" r="1.3"/><circle cx="12" cy="12" r="1.3"/><circle cx="19" cy="12" r="1.3"/>',
  menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
  shield: '<path d="M12 3 4 6v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V6z"/><path d="m9 12 2 2 4-4"/>',
  box: '<path d="M21 8 12 3 3 8v8l9 5 9-5z"/><path d="M3 8l9 5 9-5M12 13v8"/>',
  monitor: '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>',
  external: '<path d="M14 4h6v6M20 4l-9 9"/><path d="M18 14v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4"/>',
  spinner: '<path d="M12 3a9 9 0 1 0 9 9" />',
  lock: '<rect x="4.5" y="10.5" width="15" height="10" rx="2"/><path d="M8 10.5V7a4 4 0 0 1 8 0v3.5"/>',
  user: '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
  calendar: '<rect x="3.5" y="5" width="17" height="15.5" rx="2"/><path d="M3.5 10h17M8 3v4M16 3v4"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
  sparkle: '<path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M6 18l2.5-2.5M15.5 8.5 18 6"/>',
  upload: '<path d="M12 20V9M7 14l5-5 5 5M5 4h14"/>',
  edit: '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="m13.5 6.5 4 4"/>',
  globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.5 2.7 3.8 5.7 3.8 9s-1.3 6.3-3.8 9c-2.5-2.7-3.8-5.7-3.8-9S9.5 5.7 12 3z"/>',
  chart: '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
  folder: '<path d="M3 6.5A1.5 1.5 0 0 1 4.5 5h4.6l2 2.2h8.4A1.5 1.5 0 0 1 21 8.7v9.8a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 18.5z"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  moon: '<path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5z"/>',
};
Object.assign(P, {
  grid: '<rect x="3.5" y="3.5" width="7" height="7" rx="1.5"/><rect x="13.5" y="3.5" width="7" height="7" rx="1.5"/><rect x="3.5" y="13.5" width="7" height="7" rx="1.5"/><rect x="13.5" y="13.5" width="7" height="7" rx="1.5"/>',
  rows: '<path d="M4 6h16M4 12h16M4 18h16"/>',
  file: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/>',
  fileText: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M9 13h6M9 17h6M9 9h2"/>',
  image: '<rect x="3" y="4" width="18" height="16" rx="2.5"/><circle cx="9" cy="10" r="1.8"/><path d="m21 16-5-5-9 9"/>',
  video: '<rect x="2.5" y="5.5" width="14" height="13" rx="2.5"/><path d="m16.5 10 5-3v10l-5-3"/>',
  zip: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M10 5h1M10 8h1M10 11h1M10 14h1v3h-1z"/>',
  table: '<rect x="3.5" y="4" width="17" height="16" rx="2"/><path d="M3.5 9.5h17M3.5 15h17M9.5 4v16"/>',
  slides: '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M12 16v4M8 20h8"/>',
  pen: '<path d="M12 19l7-7 3 3-7 7z"/><path d="M18 13l-1.5-7.5L2 2l3.5 14.5L13 18z"/><path d="M2 2l7.6 7.6"/><circle cx="11" cy="11" r="2"/>',
  star: '<path d="m12 3 2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.5 2.9 1-6.1L3.2 9.5l6.1-.9z"/>',
  link: '<path d="M10 14a4.5 4.5 0 0 0 6.4 0l3-3a4.5 4.5 0 0 0-6.4-6.4l-1 1"/><path d="M14 10a4.5 4.5 0 0 0-6.4 0l-3 3a4.5 4.5 0 0 0 6.4 6.4l1-1"/>',
  share: '<circle cx="18" cy="5.5" r="2.5"/><circle cx="6" cy="12" r="2.5"/><circle cx="18" cy="18.5" r="2.5"/><path d="m8.2 10.8 7.6-4.1M8.2 13.2l7.6 4.1"/>',
  move: '<path d="M3 6.5A1.5 1.5 0 0 1 4.5 5h4.6l2 2.2h8.4A1.5 1.5 0 0 1 21 8.7v9.8a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 18.5z"/><path d="M9 13.5h6M13 11l2.5 2.5L13 16"/>',
  folderPlus: '<path d="M3 6.5A1.5 1.5 0 0 1 4.5 5h4.6l2 2.2h8.4A1.5 1.5 0 0 1 21 8.7v9.8a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 18.5z"/><path d="M12 10.5v6M9 13.5h6"/>',
  filePlus: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M12 11v6M9 14h6"/>',
  eye: '<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
  eyeOff: '<path d="M3 3l18 18M10.6 5.1A10 10 0 0 1 12 5c6.4 0 10 7 10 7a17 17 0 0 1-3 3.8M6.6 6.6C3.8 8.4 2 12 2 12s3.6 7 10 7a9.7 9.7 0 0 0 5.4-1.6M9.9 9.9a3 3 0 0 0 4.2 4.2"/>',
  sort: '<path d="M7 4v16M3.5 16.5 7 20l3.5-3.5M17 20V4M13.5 7.5 17 4l3.5 3.5"/>',
  arrowUp: '<path d="M12 19V5M6 11l6-6 6 6"/>',
  arrowDown: '<path d="M12 5v14M6 13l6 6 6-6"/>',
  selectAll: '<rect x="3.5" y="3.5" width="17" height="17" rx="3"/><path d="m8 12.5 3 3 5-6"/>',
  users: '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0"/><circle cx="17" cy="9" r="2.8"/><path d="M16 14.2A5.5 5.5 0 0 1 21.5 20"/>',
  key: '<circle cx="8" cy="15" r="4.5"/><path d="m11.2 11.8 8.3-8.3M16 7l3 3M18.5 4.5l2 2"/>',
  palette: '<path d="M12 3a9 9 0 1 0 0 18c1.1 0 1.7-.8 1.7-1.7 0-.5-.2-.9-.5-1.2a1.7 1.7 0 0 1 1.3-2.8H17a4 4 0 0 0 4-4C21 6.6 17 3 12 3z"/><circle cx="7.5" cy="11.5" r="1.2"/><circle cx="10.5" cy="7.5" r="1.2"/><circle cx="15.5" cy="7.5" r="1.2"/>',
  hdd: '<rect x="2.5" y="13" width="19" height="7" rx="2"/><path d="M5 13 7.5 5h9L19 13M6.5 16.5h.01M10 16.5h.01"/>',
  photos: '<rect x="3" y="3" width="8" height="8" rx="1.5"/><rect x="13" y="3" width="8" height="8" rx="1.5"/><rect x="3" y="13" width="8" height="8" rx="1.5"/><rect x="13" y="13" width="8" height="8" rx="1.5"/>',
  minus: '<path d="M6 12h12"/>',
  maximize: '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>',
});

Object.assign(P, {
  swipe: '<rect x="6" y="3" width="12" height="16" rx="2.5"/><path d="M3 8v8M21 8v8"/><path d="m9 22 3-2 3 2"/>',
  heart: '<path d="M12 20s-7.5-4.6-9.2-9.4C1.6 7.2 3.8 4 7.2 4c2 0 3.6 1.1 4.8 2.8C13.2 5.1 14.8 4 16.8 4c3.4 0 5.6 3.2 4.4 6.6C19.5 15.4 12 20 12 20z"/>',
  layers: '<path d="m12 3 9 5-9 5-9-5z"/><path d="m3 13 9 5 9-5"/>',
  burst: '<rect x="7" y="7" width="13" height="13" rx="2.5"/><path d="M4 16V6a2 2 0 0 1 2-2h10"/>',
  blur: '<circle cx="12" cy="12" r="8.5" stroke-dasharray="2.2 2.6"/><circle cx="12" cy="12" r="4"/>',
  phone: '<rect x="6.5" y="2.5" width="11" height="19" rx="2.5"/><path d="M11 18.5h2"/>',
  message: '<path d="M4 5.5A1.5 1.5 0 0 1 5.5 4h13A1.5 1.5 0 0 1 20 5.5v10a1.5 1.5 0 0 1-1.5 1.5H9l-5 4z"/>',
  film: '<rect x="3" y="4" width="18" height="16" rx="2.5"/><path d="M7 4v16M17 4v16M3 9h4M3 15h4M17 9h4M17 15h4"/>',
  weight: '<path d="M6.5 8h11l2.5 12H4z"/><circle cx="12" cy="5.5" r="2.5"/>',
  aperture: '<circle cx="12" cy="12" r="9"/><path d="M14.3 3.3 9.5 11.6M20.6 9.5h-9.6M18.6 18.2l-4.8-8.3M9.7 20.7l4.8-8.3M3.4 14.5h9.6M5.4 5.8l4.8 8.3"/>',
  map: '<path d="M9 4 3 6.5v13.5l6-2.5 6 2.5 6-2.5V4l-6 2.5z"/><path d="M9 4v13.5M15 6.5V20"/>',
  pin: '<path d="M12 21s-6.5-6.2-6.5-11.2a6.5 6.5 0 0 1 13 0C18.5 14.8 12 21 12 21z"/><circle cx="12" cy="9.8" r="2.4"/>',
  undo: '<path d="M9 14 4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/>',
  album: '<rect x="3.5" y="3.5" width="17" height="17" rx="3"/><path d="m3.5 16 5-5 4 4 3-3 5 5"/><circle cx="15.5" cy="8.5" r="1.6"/>',
  history: '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/><path d="M12 7.5V12l3 2"/>',
  wand: '<path d="m15 4 1-1M20 9l1-1M15 9l6-6M3 21 15 9l-2-2L3 17z"/><path d="M8 3v2M3 8h2M19 14v2M18 15h2"/>',
  dark: '<rect x="3" y="4" width="18" height="16" rx="2.5"/><path d="M14.5 9.5a3.5 3.5 0 1 0 0 5 3 3 0 0 1 0-5z"/>',
  broom: '<path d="M14 4l6 6M12.5 5.5 18.5 11.5"/><path d="M11 7 4 14c-1 1-1 3 0 4l2 2c1 1 3 1 4 0l7-7z"/><path d="m7 17 2 2"/>',
  tag: '<path d="M3 12V4h8l10 10-8 8z"/><circle cx="7.5" cy="7.5" r="1.5"/>',
});

export function icon(name, cls = "") {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("class", `i ${cls}`.trim());
  svg.setAttribute("aria-hidden", "true");
  svg.innerHTML = P[name] || P.info;
  return svg;
}

// ---------- API ----------
export class ApiError extends Error {
  constructor(status, message, data) { super(message); this.status = status; this.data = data; }
}
export function qs(query) {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(query || {})) {
    if (Array.isArray(v)) v.forEach(x => p.append(k, x));
    else if (v !== undefined && v !== null && v !== "") p.set(k, v);
  }
  const s = p.toString();
  return s ? "?" + s : "";
}
export async function api(path, { method = "GET", body, query, base = "/api" } = {}) {
  const url = base + path + qs(query);
  const opts = { method, headers: { "X-ImmichHelper": "1" }, credentials: "same-origin" };
  if (body !== undefined) { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
  let res;
  try { res = await fetch(url, opts); } catch { throw new ApiError(0, "Keine Verbindung zum ImmichHelper"); }
  let data = {};
  try { data = await res.json(); } catch { /* leer */ }
  if (!res.ok) {
    if (res.status === 401 && base === "/api" && !["/login", "/me", "/setup"].includes(path)) window.dispatchEvent(new Event("ih:logout"));
    throw new ApiError(res.status, data.error || `Fehler ${res.status}`, data);
  }
  return data;
}
export const thumb = (id, size = "thumbnail") => `/api/thumb/${id}${size === "preview" ? "?size=preview" : ""}`;
export const videoUrl = (id) => `/api/video/${id}`;
export const immichLink = (id) => state.immich ? `${state.immich}/photos/${id}` : null;

// ---------- Formatierung ----------
export function bytes(n, digits = 1) {
  if (n === undefined || n === null || isNaN(n)) return "–";
  const u = ["B", "KB", "MB", "GB", "TB", "PB"];
  let i = 0; let v = Number(n);
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return `${v.toFixed(i < 2 ? 0 : digits).replace(".", ",")} ${u[i]}`;
}
export function pct(v, max) { if (!max) return 0; return Math.max(0, Math.min(100, (v / max) * 100)); }
export function dateTime(ts) {
  if (!ts) return "–";
  return new Date(ts * 1000).toLocaleString("de-DE", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
}
export function shortDate(ts) {
  if (!ts) return "–";
  const d = new Date(ts * 1000), now = new Date();
  if (d.toDateString() === now.toDateString()) return "Heute, " + d.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
  const y = new Date(now); y.setDate(now.getDate() - 1);
  if (d.toDateString() === y.toDateString()) return "Gestern, " + d.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
  return d.toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit", year: "numeric" });
}
export function relTime(ts) {
  if (!ts) return "–";
  const diff = Date.now() / 1000 - ts;
  if (diff < 60) return "gerade eben";
  if (diff < 3600) return `vor ${Math.floor(diff / 60)} Min.`;
  if (diff < 86400) return `vor ${Math.floor(diff / 3600)} Std.`;
  if (diff < 86400 * 7) { const d = Math.floor(diff / 86400); return `vor ${d} ${d === 1 ? "Tag" : "Tagen"}`; }
  return shortDate(ts);
}
export function meter(p, cls = "") {
  const lvl = p > 90 ? "bad" : p > 75 ? "warn" : "";
  return h("div", { class: `meter ${lvl} ${cls}` }, h("i", { style: { width: `${p.toFixed(1)}%` } }));
}
export function plural(n, one, many) { return `${n.toLocaleString("de-DE")} ${n === 1 ? one : many}`; }

// ---------- Fotos ----------
const MONTHS = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"];
/** Aufnahmezeit (Ortszeit aus Immich, „2025-03-12T17:30:00.000Z“ = 17:30 vor Ort) */
export function takenAt(a, withTime = true) {
  const s = a.local || "";
  const m = s.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);
  if (!m) return a.taken ? dateTime(a.taken) : "–";
  const d = `${+m[3]}. ${MONTHS[+m[2] - 1]} ${m[1]}`;
  return withTime ? `${d}, ${m[4]}:${m[5]}` : d;
}
export function monthLabel(ym) { const [y, m] = ym.split("-"); return `${MONTHS[+m - 1]} ${y}`; }
export function duration(ms) {
  if (!ms && ms !== 0) return "";
  const s = Math.round(ms / 1000);
  if (s < 60) return ms < 10000 ? `${(ms / 1000).toFixed(1).replace(".", ",")} s` : `${s} s`;
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}
export function mp(a) { return a.w && a.h ? `${((a.w * a.h) / 1e6).toFixed(1).replace(".", ",")} MP` : ""; }
export function num(n) { return (n || 0).toLocaleString("de-DE"); }

// ---------- Toasts ----------
export function toast(title, text = "", kind = "ok", { timeout = 4500, actions = [] } = {}) {
  const box = document.getElementById("toasts");
  const ico = kind === "ok" ? icon("checkCircle") : kind === "bad" ? icon("xCircle") : kind === "busy" ? icon("spinner", "spin") : icon("info");
  const textEl = h("div", { class: "t-text" }, text || "");
  const titleEl = h("div", { class: "t-title" }, title);
  const t = h("div", { class: `toast ${kind}` },
    h("div", { class: "t-ico" }, ico),
    h("div", { class: "t-body" }, titleEl, textEl,
      actions.length ? h("div", { class: "t-actions" }, actions.map(a => h("button", { class: "btn sm", onclick: () => { a.onClick(); close(); } }, a.label))) : null),
    h("button", { class: "x", onclick: () => close(), "aria-label": "Schließen" }, icon("x", "sm")));
  if (!text) textEl.remove();
  box.appendChild(t);
  let timer = timeout ? setTimeout(() => close(), timeout) : null;
  function close() { clearTimeout(timer); t.remove(); }
  return { el: t, close, setText(s) { textEl.textContent = s; if (!textEl.parentNode) titleEl.after(textEl); } };
}
export function errorToast(e, title = "Das hat nicht geklappt") { toast(title, e?.message || String(e), "bad", { timeout: 8000 }); }

// ---------- Sheets / Dialoge ----------
export const isMobile = () => window.matchMedia("(max-width: 860px)").matches;
export function openSheet(build, { wide = false, onClose } = {}) {
  const sheet = h("div", { class: `sheet ${wide ? "wide" : ""}`, role: "dialog", "aria-modal": "true" });
  const overlay = h("div", { class: "overlay" }, sheet);
  let closed = false;
  const close = (result) => {
    if (closed) return; closed = true;
    overlay.remove(); document.removeEventListener("keydown", onKey, true);
    onClose && onClose(result);
  };
  const onKey = (e) => { if (e.key === "Escape") { e.stopPropagation(); close(); } };
  overlay.addEventListener("mousedown", (e) => { if (e.target === overlay) close(); });
  document.addEventListener("keydown", onKey, true);
  build(sheet, close);
  document.body.appendChild(overlay);
  const first = sheet.querySelector("input:not([type=checkbox]), select, textarea");
  if (first && !isMobile()) setTimeout(() => { first.focus(); first.select?.(); }, 50);
  return close;
}
export function confirmDialog({ title, text, confirmText = "Bestätigen", danger = false, extra = null }) {
  return new Promise((resolve) => {
    openSheet((sheet, close) => {
      sheet.append(h("h2", null, title), text ? h("p", { class: "sheet-sub" }, text) : null, extra,
        h("div", { class: "sheet-foot" }, h("button", { class: "btn", onclick: () => close(false) }, "Abbrechen"),
          h("button", { class: `btn ${danger ? "danger" : "primary"}`, onclick: () => close(true) }, confirmText)));
    }, { onClose: (r) => resolve(!!r) });
  });
}
export function promptDialog({ title, text, label, value = "", confirmText = "OK", placeholder = "", selectStem = false, validate }) {
  return new Promise((resolve) => {
    openSheet((sheet, close) => {
      const inp = input({ value, placeholder, autocapitalize: "off", autocomplete: "off", spellcheck: "false" });
      const errEl = h("div", { class: "error-text" });
      const ok = () => {
        const v = inp.value.trim();
        const problem = validate ? validate(v) : (!v ? "Bitte etwas eingeben." : null);
        if (problem) { errEl.textContent = problem; inp.classList.add("invalid"); return; }
        close(v);
      };
      inp.addEventListener("keydown", (e) => { if (e.key === "Enter") ok(); });
      sheet.append(h("h2", null, title), text ? h("p", { class: "sheet-sub" }, text) : null, field(label, inp, null, errEl),
        h("div", { class: "sheet-foot" }, h("button", { class: "btn", onclick: () => close(null) }, "Abbrechen"), h("button", { class: "btn primary", onclick: ok }, confirmText)));
      setTimeout(() => {
        if (isMobile()) return;
        inp.focus();
        const dot = value.lastIndexOf(".");
        if (selectStem && dot > 0) inp.setSelectionRange(0, dot); else inp.select();
      }, 60);
    }, { onClose: (r) => resolve(r ?? null) });
  });
}
export async function withBusy(btn, fn) {
  const old = Array.from(btn.childNodes);
  btn.disabled = true;
  clear(btn).append(icon("spinner", "spin sm"), " Bitte warten …");
  try { return await fn(); } finally { btn.disabled = false; clear(btn).append(...old); }
}

/** Menü: am Desktop schwebend am Knopf, auf dem Handy als Sheet von unten. */
export function openMenu(anchor, items, { head } = {}) {
  const build = (wrap, close) => {
    if (head) wrap.append(head);
    for (const it of items) {
      if (!it) continue;
      if (it === "-") { wrap.append(h("div", { class: "menu-sep" })); continue; }
      wrap.append(h("button", { class: `menu-item ${it.danger ? "danger" : ""}`, disabled: it.disabled, onclick: () => { close(); it.onClick(); } },
        icon(it.icon, "sm"), h("span", null, it.label)));
    }
  };
  if (isMobile() || !anchor) return openSheet((sheet, close) => build(sheet, close));
  const pop = h("div", { class: "menu-pop", role: "menu" });
  const close = () => { pop.remove(); document.removeEventListener("mousedown", outside, true); document.removeEventListener("keydown", onKey, true); window.removeEventListener("scroll", close, true); };
  const outside = (e) => { if (!pop.contains(e.target)) close(); };
  const onKey = (e) => { if (e.key === "Escape") { e.stopPropagation(); close(); } };
  build(pop, close);
  document.body.append(pop);
  const r = anchor.getBoundingClientRect ? anchor.getBoundingClientRect() : { left: anchor.x, right: anchor.x, top: anchor.y, bottom: anchor.y };
  const pw = pop.offsetWidth, ph = pop.offsetHeight;
  let left = Math.min(r.right - pw, window.innerWidth - pw - 8); if (left < 8) left = Math.min(r.left, window.innerWidth - pw - 8);
  let top = r.bottom + 6; if (top + ph > window.innerHeight - 8) top = Math.max(8, r.top - ph - 6);
  Object.assign(pop.style, { left: `${Math.max(8, left)}px`, top: `${top}px` });
  setTimeout(() => { document.addEventListener("mousedown", outside, true); document.addEventListener("keydown", onKey, true); window.addEventListener("scroll", close, true); }, 0);
  return close;
}

// ---------- Formularbausteine ----------
export function field(label, control, hint, err) {
  return h("div", { class: "field" }, label ? h("label", null, label) : null, control, hint ? h("div", { class: "hint" }, hint) : null, err || null);
}
export function input(attrs = {}) { return h("input", { class: "input", ...attrs }); }
export function select(options, value, attrs = {}) {
  const el = h("select", { class: "input", ...attrs });
  for (const o of options) {
    const opt = h("option", { value: o.value }, o.label);
    if (String(o.value) === String(value)) opt.selected = true;
    el.appendChild(opt);
  }
  return el;
}
export function toggle(label, hint, checked, onChange) {
  const inp = h("input", { type: "checkbox" });
  inp.checked = !!checked;
  inp.addEventListener("change", () => onChange(inp.checked));
  return h("label", { class: "toggle" }, inp, h("span", { class: "sw" }), h("span", { class: "t-text" }, h("strong", null, label), hint ? h("span", null, hint) : null));
}
export function segmented(options, value, onChange) {
  const wrap = h("div", { class: "segmented" });
  for (const o of options) {
    const b = h("button", { type: "button", class: o.value === value ? "active" : "" }, o.label);
    b.addEventListener("click", () => { wrap.querySelectorAll("button").forEach(x => x.classList.remove("active")); b.classList.add("active"); onChange(o.value); });
    wrap.append(b);
  }
  return wrap;
}
export function callout(kind, title, text) {
  const ico = { warn: "alert", bad: "xCircle", ok: "checkCircle" }[kind] || "info";
  return h("div", { class: `callout ${kind}` }, icon(ico), h("div", null, title ? h("strong", null, title) : null, text ? h("p", null, text) : null));
}
export function loader() { return h("div", { class: "loader" }, icon("spinner", "spin lg")); }
export function empty(ico, title, text, action) {
  return h("div", { class: "empty" }, h("div", { class: "e-ico" }, icon(ico, "lg")), h("h3", null, title), text ? h("p", { style: { margin: "0 auto", maxWidth: "460px" } }, text) : null,
    action ? h("div", { style: { marginTop: "16px" } }, action) : null);
}
export function pageHead(title, sub, actions) {
  return h("div", { class: "page-head" }, h("div", null, h("h1", null, title), sub ? h("p", null, sub) : null),
    actions ? h("div", { class: "actions" }, actions) : null);
}
export async function copyText(text) {
  try { await navigator.clipboard.writeText(text); return true; }
  catch {
    const ta = h("textarea", { style: { position: "fixed", opacity: "0" } }, text);
    document.body.append(ta); ta.select();
    let ok = false; try { ok = document.execCommand("copy"); } catch { /* */ }
    ta.remove(); return ok;
  }
}
export function uid() { return (crypto.randomUUID ? crypto.randomUUID() : String(Math.random()).slice(2) + Date.now()).replace(/[^a-zA-Z0-9]/g, "").slice(0, 24); }
