/* Fonctions communes à toutes les pages */
const LM = {
  /** Appel de l'API REST (cookie de session envoyé automatiquement). */
  async api(path, options = {}) {
    const res = await fetch(path, { headers: { "Accept": "application/json", ...(options.headers || {}) }, ...options });
    if (res.status === 401) { window.location = "/login?next=" + encodeURIComponent(location.pathname + location.search); throw new Error("401"); }
    let body = null;
    const text = await res.text();
    try { body = text ? JSON.parse(text) : null; } catch (e) { body = text; }
    if (!res.ok) {
      const err = new Error((body && body.message) || ("Erreur " + res.status));
      err.status = res.status; err.body = body; throw err;
    }
    return body;
  },

  /** Date ISO (UTC) -> date et heure locales (Africa/Tunis sur le poste de l'utilisateur). */
  date(iso, withSeconds = true) {
    if (!iso) return "—";
    let s = String(iso);
    if (!/[zZ]|[+-]\d\d:?\d\d$/.test(s)) s += "Z";   // dates MongoDB renvoyées sans fuseau = UTC
    let d = new Date(s);
    if (isNaN(d)) d = new Date(String(iso));   // autre format (ex. « Sun, 01 Nov 2026 00:00:00 GMT »)
    if (isNaN(d)) return iso;
    return d.toLocaleString("fr-FR", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit",
      minute: "2-digit", ...(withSeconds ? { second: "2-digit" } : {}) });
  },

  num(n, digits = 0) {
    if (n === null || n === undefined || isNaN(n)) return "—";
    return Number(n).toLocaleString("fr-FR", { maximumFractionDigits: digits, minimumFractionDigits: digits });
  },

  size(bytes) {
    if (!bytes && bytes !== 0) return "—";
    const u = ["o", "Ko", "Mo", "Go"]; let i = 0, v = bytes;
    while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
    return LM.num(v, i ? 1 : 0) + " " + u[i];
  },

  esc(v) {
    return String(v ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  },

  level(lv) { return lv ? `<span class="lv lv-${LM.esc(lv)}">${LM.esc(lv)}</span>` : "—"; },

  status(st) {
    const label = { pending: "En attente", processing: "En cours", indexed: "Indexé", failed: "Erreur" }[st] || st;
    return `<span class="st st-${LM.esc(st)}">${LM.esc(label)}</span>`;
  },

  /** Message en haut de page (succès, erreur…). */
  toast(message, kind = "success") {
    const zone = document.getElementById("lm-alerts");
    const div = document.createElement("div");
    div.className = `alert alert-${kind} alert-dismissible fade show`;
    div.innerHTML = `${LM.esc(message)}<button type="button" class="btn-close" data-bs-dismiss="alert"></button>`;
    zone.prepend(div);
    setTimeout(() => div.remove(), 7000);
  },

  colors: { accent: "#2F80ED", ok: "#27AE60", warn: "#F2994A", danger: "#EB5757", critical: "#9B1C1C",
            muted: "#6B7280", navy: "#1F3A68", palette: ["#2F80ED", "#27AE60", "#F2994A", "#EB5757", "#9B51E0", "#56CCF2", "#6B7280"] },
  levelColor: { DEBUG: "#6B7280", INFO: "#2F80ED", WARNING: "#F2994A", ERROR: "#EB5757", CRITICAL: "#9B1C1C" },
};

if (window.Chart) {
  Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
  Chart.defaults.locale = "fr-FR";
  Chart.defaults.color = "#444";
  Chart.defaults.plugins.legend.labels.boxWidth = 12;
}

// Menu latéral sur mobile
document.addEventListener("click", e => {
  if (e.target.closest(".lm-burger")) document.body.classList.toggle("sidebar-open");
  else if (!e.target.closest(".lm-sidebar")) document.body.classList.remove("sidebar-open");
});
