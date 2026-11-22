// Gewähltes Design (hell/dunkel) vor dem ersten Zeichnen setzen, damit nichts aufblitzt
try { const t = localStorage.getItem("ih-theme"); if (t === "light" || t === "dark") document.documentElement.dataset.theme = t; } catch (e) { /* */ }
