"use strict";
const AMPEL_ORDER = {gruen: 0, orange: 1, rot: 2};
let DATA = [], MAKRO = [], MARKT = null, AUS = [], TOPMV = [], RAW = {};
let filter = "alle", sortKey = "ampel", sortDir = 1, chart = null, calTab = "makro", secTab = "woche";
let openSym = null, horizon = "lang";
const DETAIL = {};

// ---------- Theme (Hell / Dunkel / Auto) ----------
function applyTheme(pref){
  try { localStorage.setItem("theme", pref); } catch(e) {}
  const dark = pref === "dark" || (pref === "auto" && matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
  document.documentElement.dataset.pref = pref;
  document.querySelectorAll("[data-theme-set]").forEach(b => b.classList.toggle("on", b.dataset.themeSet === pref));
  if (openSym) showDetail(openSym, horizon);
}
document.querySelectorAll("[data-theme-set]").forEach(b => b.onclick = () => applyTheme(b.dataset.themeSet));
document.querySelectorAll("[data-theme-set]").forEach(b => b.classList.toggle("on", b.dataset.themeSet === document.documentElement.dataset.pref));
const cssVar = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();

// GitHub-Links aus der Pages-Adresse ableiten (user.github.io/repo)
(function(){
  const m = location.hostname.match(/^([^.]+)\.github\.io$/);
  const repo = location.pathname.split("/").filter(Boolean)[0];
  const base = (m && repo) ? `https://github.com/${m[1]}/${repo}` : "https://github.com";
  document.getElementById("editWl").href = (m && repo) ? `${base}/edit/main/watchlist.csv` : base;
  document.getElementById("runNow").href = (m && repo) ? `${base}/actions/workflows/analyse.yml` : base;
})();

// ---------- Formatierung ----------
const fmt = (x, c = "") => x == null ? "–" : x.toLocaleString("de-DE", {minimumFractionDigits: 2, maximumFractionDigits: 2}) + (c ? ` ${c}` : "");
const pct = (a, b) => (a / b - 1) * 100;
const num1 = v => (v >= 0 ? "+" : "") + v.toFixed(1).replace(".", ",") + " %";
const pctTxt = v => v == null || !isFinite(v) ? "–" : `<span class="${v >= 0 ? "pos" : "neg"}">${num1(v)}</span>`;
const WT = ["So", "Mo", "Di", "Mi", "Do", "Fr", "Sa"];
function daysTo(iso){ return Math.round((new Date(iso) - new Date(new Date().toDateString())) / 864e5); }
function dateDe(iso){ const [y, m, d] = iso.split("-"); return `${d}.${m}.${y.slice(2)}`; }
function dateWd(iso){ return `${WT[new Date(iso).getDay()]} ${dateDe(iso)}`; }
function naechsterHandelstag(iso){
  const d = new Date(iso + "T12:00:00"); do { d.setDate(d.getDate() + 1); } while (d.getDay() === 0 || d.getDay() === 6);
  return d.toISOString().slice(0, 10);
}
function wdKurz(iso){ const d = new Date(iso + "T12:00:00"); return `${WT[d.getDay()]} ${String(d.getDate()).padStart(2, "0")}.${String(d.getMonth() + 1).padStart(2, "0")}.`; }
let STAND = null, EMPF = [];
const wann = typ => !STAND ? "" : typ === "kauf" ? `🌙 Kaufen am ${wdKurz(STAND)} abends` : `☀️ Verkaufen am ${wdKurz(naechsterHandelstag(STAND))} morgens`;
// Top-Empfehlungen: beste Kaufkandidaten nach Score, Chance/Risiko und ob das Signal heute neu ist
function empfehlungen(){
  if (Array.isArray(RAW.empfehlungen)) return RAW.empfehlungen.map(s => DATA.find(a => a.symbol === s)).filter(Boolean);
  const neu = new Set(aufgaben().map(a => a.symbol));
  return DATA.filter(a => kategorie(a) === "kauf" && !(a.markt_filter && a.markt_filter.blockiert) && a.check && a.check.score >= 55 && a.crv >= 1)
    .map(a => ({a, r: a.check.score + (a.crv >= 2 ? 5 : 0) + (neu.has(a.symbol) ? 5 : 0)}))
    .sort((x, y) => y.r - x.r || y.a.crv - x.a.crv).slice(0, 3).map(x => x.a);
}
const isEmpf = a => EMPF.some(e => e.symbol === a.symbol);
const empfTag = '<span class="tag star">⭐ Empfohlen</span>';
function earnWarn(a){
  const t = a.termine; if (!t || t.earnings_in_tagen == null || t.earnings_in_tagen > 7) return "";
  return ` <span class="tag warn">⚠️ Earnings ${t.earnings_in_tagen === 0 ? "heute" : "in " + t.earnings_in_tagen + " T."}</span>`;
}

// Farben: grün/rot je nach Vorzeichen, kräftiger je größer die Bewegung
function mix(c1, c2, t){
  const h = c => [1, 3, 5].map(i => parseInt(c.slice(i, i + 2), 16));
  const a = h(c1), b = h(c2);
  return "#" + a.map((x, i) => Math.round(x + (b[i] - x) * t).toString(16).padStart(2, "0")).join("");
}
function heatCol(v, scale){
  if (v == null) return "#6b7280";
  const t = Math.min(1, Math.abs(v) / scale);
  return v >= 0 ? mix("#64748b", "#15803d", .25 + .75 * t) : mix("#64748b", "#b91c1c", .25 + .75 * t);
}
function scoreCol(s){ return s >= 75 ? "#16a34a" : s >= 60 ? "#65a30d" : s >= 45 ? "#ca8a04" : s >= 30 ? "#ea580c" : "#dc2626"; }
const scoreBadge = c => c ? `<span class="score" style="background:${scoreCol(c.score)}" title="${c.label}">${c.score}</span>` : '<span class="mute">–</span>';

// ---------- Tagesaufgaben ----------
// Aufgaben entstehen nur, wenn sich der Status seit dem letzten Börsentag geändert hat.
const HALTEN = ["In Zone", "In Zone (unten)", "Nachkaufbereich", "Welle 5 läuft", "Ziel 1 erreicht", "Ziel 2 erreicht", "Impuls vollendet", "Neues Hoch / Trend läuft"];
const AKTION = {
  "In Zone":          ["kauf",    "Kaufen",      a => `Teilkauf 1 (ca. 1/3) bei ${fmt(a.kurs, a.currency)}`],
  "In Zone (unten)":  ["kauf",    "Nachkaufen",  a => `Teilkauf 2 (ca. 1/3) bei ${fmt(a.kurs, a.currency)}`],
  "Nachkaufbereich":  ["kauf",    "Nachkaufen",  a => `Teilkauf 3 (Rest) – Invalidierung ${fmt(a.zone.invalidierung)}`],
  "Impuls vollendet": ["verkauf", "Teilverkauf", a => `ca. 1/3 sichern – 5 Wellen vollendet, Korrektur bis ${fmt(a.zone.oben)} erwartet`],
  "Ziel 1 erreicht":  ["verkauf", "Teilverkauf", a => `ca. 1/3 verkaufen bei ${fmt(a.kurs, a.currency)}`],
  "Ziel 2 erreicht":  ["verkauf", "Teilverkauf", a => `weiteres Drittel verkaufen, Rest bis ${fmt(a.ziele.t3)}`],
  "Abwärtstrend":     ["verkauf", "Verkaufen",   a => `Szenario invalidiert – Restposition auflösen`],
};
function aufgaben(){
  return DATA.filter(a => {
    if (!a.status_vorher || a.status === a.status_vorher || !AKTION[a.status]) return false;
    if (a.status === "Abwärtstrend") return HALTEN.includes(a.status_vorher);
    return true;
  });
}
function renderTodo(stand){
  const list = aufgaben(), el = document.getElementById("todo");
  document.getElementById("todoDate").textContent = stand ? `Stand ${wdKurz(stand)}` : "";
  const top = EMPF.length ? `<div class="grp">⭐ Top-Empfehlungen für heute Abend</div>` + EMPF.map((a, i) =>
    `<div class="pick" data-sym="${a.symbol}"><span class="rank">${i + 1}</span><div style="min-width:0"><b>${a.name}</b> ${scoreBadge(a.check)} <span class="score" style="background:${crvCol(a.crv)}">${crvTxt(a.crv)}</span>
      <div class="small">${wann("kauf")} · ${a.signal.split(" – ")[0]}</div>
      ${a.uebernacht || a.ev != null ? `<div class="small mute">${a.ev != null ? `Erwartungswert ${evTxt(a.ev)}` : ""}${a.uebernacht ? `${a.ev != null ? " · " : ""}Über Nacht ${a.uebernacht.pos_pct} % positiv, Ø ${sgn2(a.uebernacht.mittel_pct)} %` : ""}</div>` : ""}
      <div class="small mute">${(a.check.pro || []).slice(0, 2).join(" · ")}</div></div></div>`).join("") : "";
  if (!list.length) { el.innerHTML = top + '<div class="empty" style="margin-top:8px">Heute keine neuen Signale.<br><span class="small">Bestehende Positionen einfach halten.</span></div>';
    el.querySelectorAll("[data-sym]").forEach(t => t.onclick = () => showDetail(t.dataset.sym)); return; }
  const mfOf = a => a.markt_filter || {};
  const grp = (typ, title, filt) => { const xs = list.filter(a => AKTION[a.status][0] === typ && filt(a))
      .sort((x, y) => (y.check ? y.check.score : 0) - (x.check ? x.check.score : 0)); if (!xs.length) return "";
    return `<div class="grp">${title} · ${xs.length}</div>` + xs.map(a => { let [t, lbl, txt] = AKTION[a.status];
      let sub = `<b class="when">${wann(typ)}</b><br>` + txt(a);
      if (mfOf(a).blockiert) { t = "warten"; lbl = "Pausiert"; sub = mfOf(a).hinweise[0]; }
      else if (mfOf(a).reduziert) sub = `<b class="when">${wann(typ)}</b><br>Nur Teilkauf 1 (ca. 1/3) – Markt angeschlagen`;
      return `<div class="task" data-sym="${a.symbol}"><span class="pill ${t}">${lbl}</span><div><b>${a.name}</b> ${scoreBadge(a.check)}${isEmpf(a) ? " " + empfTag : ""}<br><span class="small mute">${sub}</span>${earnWarn(a)}</div></div>`; }).join(""); };
  el.innerHTML = top + grp("kauf", "Neue Kaufsignale (nach Score)", a => !mfOf(a).blockiert)
    + grp("kauf", "Kaufzone erreicht – pausiert durch Marktfilter", a => mfOf(a).blockiert)
    + grp("verkauf", "Verkaufen / Gewinne sichern", () => true);
  el.querySelectorAll("[data-sym]").forEach(t => t.onclick = () => showDetail(t.dataset.sym));
}

// ---------- Marktstimmung & Ticker ----------
function gauge(v){
  const ang = Math.PI * (1 - v / 100), r = 52, cx = 60, cy = 60;
  const x = cx + r * Math.cos(ang), y = cy - r * Math.sin(ang);
  const seg = (a0, a1, col) => { const p = t => [cx + r * Math.cos(Math.PI * (1 - t)), cy - r * Math.sin(Math.PI * (1 - t))];
    const [x0, y0] = p(a0), [x1, y1] = p(a1); return `<path d="M${x0},${y0} A${r},${r} 0 0 1 ${x1},${y1}" stroke="${col}" stroke-width="10" fill="none"/>`; };
  return `<svg width="124" height="72" viewBox="0 0 120 70">${seg(0, .25, "#ef4444")}${seg(.25, .45, "#f97316")}${seg(.45, .55, "#eab308")}${seg(.55, .75, "#84cc16")}${seg(.75, 1, "#22c55e")}
    <line x1="${cx}" y1="${cy}" x2="${x}" y2="${y}" stroke="currentColor" stroke-width="3" stroke-linecap="round"/><circle cx="${cx}" cy="${cy}" r="4" fill="currentColor"/></svg>`;
}
function renderMood(m){
  const el = document.getElementById("mood");
  if (!m || !m.stimmung) { el.innerHTML = '<div class="k">Marktstimmung</div><div class="empty">Wird beim nächsten Lauf berechnet.</div>'; return; }
  const s = m.stimmung;
  const hist = [["Vortag", s.vortag], ["Vorwoche", s.woche], ["Vormonat", s.monat]].filter(x => x[1] != null)
    .map(([n, v]) => `${n} <b>${v}</b>`).join(", ");
  const chips = (s.teile_cnn || []).map(t => `<span class="fgc" style="background:${moodCol(t.wert)}" title="${t.name}: ${t.wert} (${t.label})">${t.name} ${t.wert}</span>`).join("");
  el.innerHTML = `<div class="k" title="${s.erklaerung}">Marktstimmung (Angst & Gier) ⓘ</div><div class="mood">${gauge(s.wert)}
    <div style="min-width:0"><div class="big" style="color:${moodCol(s.wert)}">${s.wert} · ${s.label}</div>
    <div class="exp">${hist}</div><div class="exp">${s.quelle || ""}</div></div></div>
    ${chips ? `<div class="fgchips">${chips}</div>` : `<div class="exp" style="margin-top:8px">${(s.teile || []).join(" · ")}</div>`}`;
}
function moodCol(v){ return v < 25 ? "#b91c1c" : v < 45 ? "#ea580c" : v <= 55 ? "#a16207" : v <= 75 ? "#4d7c0f" : "#15803d"; }
function renderTicker(m){
  if (!m || !m.indizes) return;
  document.getElementById("ticker").innerHTML = m.indizes.map(i =>
    `<span class="tk"><b>${i.name}</b>${i.kurs.toLocaleString("de-DE", {maximumFractionDigits: i.kurs < 10 ? 4 : 0})} ${pctTxt(i.tag_pct)}</span>`).join("");
}

// ---------- Marktfilter ----------
const LAGE_COL = {gesund: "#16a34a", schwach: "#ea580c", abverkauf: "#dc2626"};
const LAGE_SATZ = {gesund: "gesund", schwach: "angeschlagen", abverkauf: "im Abverkauf"};
function renderFilter(mf){
  const el = document.getElementById("mf"), hl = document.getElementById("heroLage");
  if (!mf || !mf.nach_markt) {
    el.innerHTML = '<div class="empty">Wird beim nächsten Analyse-Lauf berechnet.</div>';
    hl.innerHTML = '<div class="k">Marktlage</div><div class="empty">Wird beim nächsten Lauf berechnet.</div>'; return;
  }
  const L = mf.lage, bef = mf.befund || {};
  const nPaus = DATA.filter(a => a.markt_filter && a.markt_filter.blockiert).length, nRed = DATA.filter(a => a.markt_filter && a.markt_filter.reduziert).length;
  const aktiv = Object.values(mf.aktiv || {}).some(Boolean);
  hl.innerHTML = L ? `<div class="k">Marktlage · S&P 500</div><div class="lage"><div class="big" style="color:${LAGE_COL[L.regime]}"><i style="background:${LAGE_COL[L.regime]}"></i>${L.label}</div></div>
    <div class="lagefacts">
      <div><b class="${L.spx_5t_pct >= 0 ? "pos" : "neg"}">${num1(L.spx_5t_pct)}</b><span>in 5 Tagen</span></div>
      <div><b class="${L.spx_vs_200_pct >= 0 ? "pos" : "neg"}">${num1(L.spx_vs_200_pct)}</b><span>ggü. 200-Tage-Linie</span></div>
      <div><b>${String(L.vix).replace(".", ",")}</b><span>VIX (${L.vix_vs_50_pct >= 0 ? "+" : ""}${L.vix_vs_50_pct} % ggü. Schnitt)</span></div>
    </div>
    <div class="exp" style="margin-top:8px">Marktfilter ${aktiv ? "aktiv" : "nur als Hinweis – laut Backtest kein Nachteil"}${nPaus ? ` · ${nPaus} Kaufsignale pausiert` : ""}${nRed ? ` · ${nRed} reduziert` : ""}</div>`
    : '<div class="k">Marktlage</div><div class="empty">Marktdaten fehlen</div>';
  const befTxt = k => ({nachteil: '<span class="chip r">Filter aktiv</span>', kein_nachteil: '<span class="chip g">kein Nachteil – nur Hinweis</span>',
    zu_wenig: '<span class="chip o">zu wenige Daten – nur Hinweis</span>'})[bef[k]] || "";
  const row = (name, x, col, extra) => { const q = x.quote_pct;
    return `<div class="mfrow"><span>${name}</span><span class="meter" style="margin:0"><i style="width:${q || 0}%;background:${col}"></i></span>
      <b>${q != null ? q + " %" : "–"}</b><span class="mute small">${x.n} Signale${x.rendite_schnitt_pct != null ? ", Ø " + (x.rendite_schnitt_pct >= 0 ? "+" : "") + String(x.rendite_schnitt_pct).replace(".", ",") + " %" : ""}</span>${extra || ""}</div>`; };
  const m = mf.nach_markt, r = mf.nach_rs;
  el.innerHTML = `<div class="mfgrid">
      <div><div class="k">Trefferquote der Kaufsignale je Marktlage</div>
        ${row("Gesund", m.gesund, LAGE_COL.gesund)}${row("Angeschlagen", m.schwach, LAGE_COL.schwach, befTxt("schwach"))}${row("Abverkauf", m.abverkauf, LAGE_COL.abverkauf, befTxt("abverkauf"))}</div>
      <div><div class="k">Aktie im Vergleich zu ihrem Index (20 Tage)</div>
        ${row("Mit dem Markt", r.markt, "#16a34a")}${row("Eigene Schwäche", r.eigen, "#dc2626", befTxt("eigen"))}</div>
    </div>
    <p class="mute small" style="margin:10px 0 0">Der Filter pausiert oder reduziert Kaufsignale nur, wenn eine Lage im Backtest mindestens ${mf.regeln.min_abstand_pp} Prozentpunkte schlechter abschneidet (ab ${mf.regeln.min_signale} Signalen). Er prüft sich jeden Abend neu.</p>`;
}

// ---------- Sektoren-Heatmap ----------
const SEC_SCALE = {tag: 2.5, woche: 5, monat: 10, ytd: 30};
function renderSectors(){
  const el = document.getElementById("heat"), xs = (MARKT && MARKT.sektoren) || [];
  if (!xs.length) { el.innerHTML = '<div class="empty" style="grid-column:1/-1">Sektordaten kommen mit dem nächsten Analyse-Lauf.</div>'; return; }
  const rows = xs.filter(s => s[secTab] != null).sort((a, b) => b[secTab] - a[secTab]);
  el.innerHTML = rows.map(s => {
    const v = s[secTab];
    return `<div class="hc" style="background:${heatCol(v, SEC_SCALE[secTab])}" title="${s.name} (${s.symbol}): Tag ${num1(s.tag || 0)} · Woche ${num1(s.woche || 0)} · Monat ${num1(s.monat || 0)} · seit 1.1. ${num1(s.ytd || 0)}">
      <div class="n">${s.name}</div><div class="p">${num1(v)}</div><span class="s">${s.symbol}</span></div>`; }).join("");
}

// ---------- Ausreißer heute ----------
function hinweis(a, tag){
  if (!a) return ["", ""];
  const k = kategorie(a), sc = a.check ? a.check.score : 50;
  const an = a.analysten && a.analysten.ampel === "gruen";
  if (a.markt_filter && a.markt_filter.blockiert) return ["o", "Marktfilter: erst Stabilisierung abwarten"];
  if (tag < 0) {
    if (a.status === "Abwärtstrend") return ["r", "Fallendes Messer – Abwärtstrend, nicht kaufen"];
    if (k === "kauf" || (an && sc >= 55)) return ["g", "Kaufpotenzial – Übertreibung, Teilkauf prüfen"];
    if (a.earnings_heute) return ["o", "Reaktion auf Quartalszahlen – erst Stabilisierung abwarten"];
    return ["o", "Abwarten – erst Boden abwarten, dann Zone prüfen"];
  }
  if (a.status === "Abwärtstrend") return ["o", "Gegenbewegung im Abwärtstrend – nicht hinterherlaufen"];
  if (["Impuls vollendet", "Ziel 1 erreicht", "Ziel 2 erreicht"].includes(a.status) || sc < 40) return ["o", "Gewinnmitnahme prüfen – Teil sichern"];
  return ["g", "Starker Ausbruch – halten, nicht hinterherkaufen"];
}
function renderOutliers(){
  const el = document.getElementById("outl");
  const bySym = s => DATA.find(a => a.symbol === s);
  let html = "";
  if (AUS.length) {
    html = AUS.slice().sort((a, b) => Math.abs(b.tag) - Math.abs(a.tag)).map(o => {
      const a = bySym(o.symbol), [c, txt] = hinweis(a, o.tag);
      return `<div class="ol" data-sym="${o.symbol}"><span class="big ${o.tag >= 0 ? "pos" : "neg"}">${o.tag >= 0 ? "🚀" : "📉"} ${num1(o.tag)}</span>
        <div><b>${o.name}</b> <span class="mute small">${o.symbol}</span></div>${a ? scoreBadge(a.check) : ""}
        <div class="hint">${txt ? `<span class="chip ${c}">${txt}</span>` : ""}</div></div>`; }).join("");
  } else {
    html = '<div class="empty" style="margin-bottom:8px">Heute keine Bewegung über ±10 %.</div>';
  }
  const mv = TOPMV.filter(t => !AUS.some(o => o.symbol === t.symbol));
  if (mv.length) {
    const mx = Math.max(...mv.map(t => Math.abs(t.tag)), 1);
    html += `<div class="grp">Größte Bewegungen heute</div>` + mv.map(t => {
      const w = Math.abs(t.tag) / mx * 50;
      return `<div class="mv" data-sym="${t.symbol}"><span><b>${t.name}</b></span>
        <span class="pr"><span class="axis" style="display:block"><i style="${t.tag >= 0 ? "left:50%" : `left:${50 - w}%`};width:${w}%;background:${heatCol(t.tag, 5)}"></i></span></span>
        <b class="${t.tag >= 0 ? "pos" : "neg"}" style="text-align:right">${num1(t.tag)}</b></div>`; }).join("");
  }
  el.innerHTML = html;
  el.querySelectorAll("[data-sym]").forEach(x => x.onclick = () => showDetail(x.dataset.sym));
}

// ---------- Termine ----------
function renderCal(){
  const items = [];
  if (calTab === "earn") {
    DATA.forEach(a => { const t = a.termine || {};
      if (t.earnings && t.earnings_in_tagen != null && t.earnings_in_tagen <= 60) items.push([t.earnings, `<span class="dot ${a.ampel}"></span> <b>${a.name}</b> <span class="mute small">${a.status}</span>`]); });
    document.getElementById("calInfo").textContent = "Quartalszahlen der Watchlist-Aktien in den nächsten 60 Tagen.";
  } else if (calTab === "div") {
    DATA.forEach(a => { const t = a.termine || {};
      if (t.ex_dividende && daysTo(t.ex_dividende) >= -1 && daysTo(t.ex_dividende) <= 90) items.push([t.ex_dividende, `<b>${a.name}</b> <span class="mute small">Ex-Dividende</span>`]);
      if (t.dividende_zahltag && daysTo(t.dividende_zahltag) >= -1 && daysTo(t.dividende_zahltag) <= 90) items.push([t.dividende_zahltag, `<b>${a.name}</b> <span class="mute small">Zahltag</span>`]); });
    document.getElementById("calInfo").textContent = "Dividendentermine der nächsten 90 Tage.";
  } else {
    MAKRO.forEach(t => { if (daysTo(t.datum) >= -1 && daysTo(t.datum) <= 220)
      items.push([t.datum, `<span class="flag" title="${LAND_NAME[landOf(t)]}">${FLAG[landOf(t)]}</span> <b>${t.titel}</b><span class="kat">${t.kategorie}</span>${t.info ? `<div class="mute small" style="margin-left:74px">${t.info}</div>` : ""}`]); });
    document.getElementById("calInfo").textContent = "Notenbanken, Konjunkturdaten, Politik und Börsentermine für USA, Deutschland, Eurozone und China (Quellen: Fed, EZB, BLS, BEA, Destatis, Eurostat, ifo, ZEW, NBS).";
  }
  items.sort((x, y) => x[0] < y[0] ? -1 : 1);
  document.getElementById("cal").innerHTML = items.length ? items.map(([d, html]) => {
    const n = daysTo(d);
    return `<li><span class="date">${dateWd(d)}</span> ${html}${n === 0 ? ' <span class="tag warn">heute</span>' : ""}</li>`; }).join("")
    : '<li class="mute">Keine Termine im Zeitraum.</li>';
}

// ---------- Tabellen-Helfer ----------
function anTxt(a){
  const x = a.analysten;
  if (!x || !x.rating) return '<span class="mute">–</span>';
  const pot = x.potenzial_pct != null ? ` ${pctTxt(x.potenzial_pct)}` : "";
  return `<span class="dot ${x.ampel || ""}"></span> ${x.rating}${pot}${x.anzahl ? ` <span class="mute">(${x.anzahl})</span>` : ""}`;
}
function qTxt(a){
  const b = a.backtest;
  if (!b || b.quote_pct == null) return '<span class="mute">–</span>';
  const c = b.quote_pct >= 60 ? "pos" : b.quote_pct < 45 ? "neg" : "";
  return `<span class="${c}">${b.quote_pct} %</span> <span class="mute">(${b.treffer}/${b.treffer + b.fehler})</span>`;
}
function wTxt(v){
  if (v == null) return '<span class="mute">–</span>';
  const w = Math.min(50, Math.abs(v) / 8 * 50);
  return `<span class="wbar"><b class="${v >= 0 ? "pos" : "neg"}">${num1(v)}</b><span class="tr"><i style="${v >= 0 ? "left:50%" : `left:${50 - w}%`};width:${w}%;background:${v >= 0 ? "var(--green)" : "var(--red)"}"></i></span></span>`;
}
function kategorie(a){
  const s = (a.signal || "").toLowerCase();
  if (a.status === "Abwärtstrend") return "rot";
  if (s.startsWith("teilverkauf")) return "verkauf";
  if (s.startsWith("teilkauf") || s.startsWith("letzter nachkauf") || s.startsWith("kleine position")) return "kauf";
  return "warten";
}

// ---------- Chance / Risiko ----------
// CRV = (Kursziel − Kurs) / (Kurs − Stopp). Stopp = Invalidierung der Elliott-Zählung, Ziel = nächstes Kursziel über dem Kurs.
function crvCalc(v, kurs){
  if (!v || !v.zone || !v.ziele) return null;
  const stop = v.zone.invalidierung;
  const ziel = [v.ziele.t1, v.ziele.t2, v.ziele.t3].find(z => z != null && z > kurs * 1.01);
  if (stop == null || stop >= kurs || ziel == null) return {ok: false, stop, ziel};
  const chance = (ziel / kurs - 1) * 100, risiko = (1 - stop / kurs) * 100;
  const crv = Math.round(chance / risiko * 10) / 10;
  return {ok: true, stop, ziel, chance, risiko, crv, noetig: 100 / (1 + chance / risiko)};
}
const crvCol = c => c >= 2 ? "#16a34a" : c >= 1 ? "#ca8a04" : "#dc2626";
const crvTxt = c => c.toFixed(1).replace(".", ",") + " : 1";
function crvBadge(a){
  const r = crvCalc(a, a.kurs);
  if (!r || !r.ok) return '<span class="mute" title="Kurs unter der Invalidierung bzw. kein Ziel über dem Kurs">–</span>';
  return `<span class="score" style="background:${crvCol(r.crv)};min-width:54px" title="Chance +${r.chance.toFixed(0)} % bis ${fmt(r.ziel)} · Risiko −${r.risiko.toFixed(0)} % bis ${fmt(r.stop)}">${crvTxt(r.crv)}</span>`;
}
function riskBox(a, v){
  const r = crvCalc(v, a.kurs), vol = a.parameter && a.parameter.vol_jahr_pct;
  const volKl = vol == null ? null : vol < 25 ? ["niedrig", "#16a34a"] : vol < 40 ? ["mittel", "#ca8a04"] : ["hoch", "#dc2626"];
  const volHtml = vol == null ? "" : `<div class="rk"><span>Schwankung (Volatilität p. a.)</span><b style="color:${volKl[1]}">${vol.toLocaleString("de-DE")} % · ${volKl[0]}</b></div>`;
  if (!r || !r.ok) return `<div class="mute">Kein sinnvolles Chance-Risiko-Verhältnis: ${r && r.stop != null && r.stop >= a.kurs ? "der Kurs liegt bereits unter der Invalidierung (Abwärtstrend) – kein Long-Einstieg." : "kein Kursziel über dem aktuellen Kurs."}</div>${volHtml}`;
  const tot = r.chance + r.risiko, q = a.backtest && a.backtest.quote_pct;
  return `<div class="crvhead"><span class="score" style="background:${crvCol(r.crv)};font-size:16px;height:30px;min-width:72px">${crvTxt(r.crv)}</span>
      <span class="small mute">${r.crv >= 2 ? "Gutes Verhältnis – die Chance ist mindestens doppelt so groß wie das Risiko." : r.crv >= 1 ? "Ausgeglichen – Chance und Risiko etwa gleich groß." : "Ungünstig – das Risiko ist größer als die Chance."}</span></div>
    <div class="crvbar"><i style="width:${r.risiko / tot * 100}%;background:#dc2626"></i><i style="width:${r.chance / tot * 100}%;background:#16a34a"></i></div>
    <div class="rk"><span>🔴 Risiko bis Stopp ${fmt(r.stop)}</span><b class="neg">−${r.risiko.toFixed(1).replace(".", ",")} %</b></div>
    <div class="rk"><span>🟢 Chance bis Ziel ${fmt(r.ziel)}</span><b class="pos">+${r.chance.toFixed(1).replace(".", ",")} %</b></div>
    <div class="rk"><span>Nötige Trefferquote</span><b>${Math.round(r.noetig)} %</b></div>
    ${a.ev != null && v === a ? `<div class="rk"><span title="p × CRV − (1 − p), p = geschätzte Trefferquote ${a.ev_p_pct} %">Erwartungswert pro Trade</span><b style="color:${evCol(a.ev)}">${evTxt(a.ev)}</b></div>` : ""}
    ${q != null ? `<div class="rk"><span>Trefferquote dieser Aktie (Backtest)</span><b style="color:${q >= r.noetig ? "#16a34a" : "#dc2626"}">${q} % ${q >= r.noetig ? "✓" : "✗"}</b></div>` : ""}
    ${volHtml}
    <div class="mute small" style="margin-top:6px">CRV = Chance ÷ Risiko. Stopp = Invalidierung der Wellenzählung, Ziel = nächstes Kursziel über dem Kurs.</div>`;
}

// ---------- Laden ----------
async function load(){
  const [d, mk] = await Promise.all([
    fetch("data.json?ts=" + Date.now()).then(r => r.json()),
    fetch("makro.json?ts=" + Date.now()).then(r => r.ok ? r.json() : {termine: []}).catch(() => ({termine: []}))]);
  RAW = d; MAKRO = mk.termine || []; MARKT = d.markt; AUS = d.ausreisser || []; TOPMV = d.top_bewegungen || [];
  DATA = d.aktien.map(a => ({...a, dist: pct(a.kurs, a.zone.oben),
    anScore: (a.analysten && a.analysten.score) || 9,
    quote: (a.backtest && a.backtest.quote_pct != null) ? a.backtest.quote_pct : -1,
    earn: (a.termine && a.termine.earnings) || "9999",
    earnings_heute: !!(a.termine && a.termine.earnings_in_tagen != null && a.termine.earnings_in_tagen <= 1),
    w1: a.perf && a.perf.woche != null ? a.perf.woche : -999,
    score: a.check ? a.check.score : -1,
    kstat: a.kurz ? AMPEL_ORDER[a.kurz.ampel] : 9,
    crv: (() => { const r = crvCalc(a, a.kurs); return r && r.ok ? r.crv : -1; })(),
    ev: a.ev != null ? a.ev : -99}));
  const fill = (id, key) => { const el = document.getElementById(id);
    [...new Set(DATA.map(a => a.meta && a.meta[key]).filter(Boolean))].sort().forEach(v => el.add(new Option(v, v))); };
  fill("fLand", "land"); fill("fSektor", "sektor");
  renderMood(MARKT); renderTicker(MARKT); renderSectors(); renderCal(); renderFilter(d.marktfilter);
  const kursStand0 = Object.entries(DATA.reduce((m, a) => (m[a.stand] = (m[a.stand] || 0) + 1, m), {})).sort((x, y) => y[1] - x[1])[0];
  STAND = kursStand0 ? kursStand0[0] : null;
  EMPF = empfehlungen();
  renderTodo(STAND); renderOutliers();
  renderMarkt(); renderNews(); renderChancen(); renderLive(); renderWoche();
  const tq = d.trefferquote || {};
  const kursStand = Object.entries(DATA.reduce((m, a) => (m[a.stand] = (m[a.stand] || 0) + 1, m), {})).sort((x, y) => y[1] - x[1])[0];
  document.getElementById("stand").innerHTML = "Analyse " + new Date(d.erstellt).toLocaleString("de-DE", {dateStyle: "medium", timeStyle: "short"})
    + (kursStand ? ` · Kurse vom ${dateDe(kursStand[0])}` : "");
  const cnt = k => DATA.filter(a => a.ampel === k).length, n = DATA.length || 1;
  const nL = new Set(DATA.map(a => a.meta && a.meta.land).filter(Boolean)).size;
  const parts = [["gruen", "Kaufen / Halten", "var(--green)"], ["orange", "Abwarten / Sichern", "var(--orange)"], ["rot", "Abwärtstrend", "var(--red)"]];
  document.getElementById("heroWl").innerHTML = `<div class="k">Watchlist · ${DATA.length} Aktien${nL ? ` aus ${nL} Ländern` : ""}</div>
    <div class="wlbar">${parts.map(([k, , c]) => `<i style="width:${cnt(k) / n * 100}%;background:${c}" title="${cnt(k)}"></i>`).join("")}</div>
    <div class="wllegend">${parts.map(([k, l]) => `<span><span class="dot ${k}"></span><b>${cnt(k)}</b> ${l}</span>`).join("")}</div>
    <div class="wlstats">
      <div title="Zonen-Kaufsignale im Backtest über alle Aktien"><b>${tq.quote_pct != null ? tq.quote_pct + " %" : "–"}</b><span>Trefferquote Kauf${tq.treffer != null ? ` (${tq.treffer}/${tq.treffer + tq.fehler})` : ""}</span></div>
      <div title="„Impuls vollendet“ im Backtest"><b>${tq.verkauf && tq.verkauf.quote_pct != null ? tq.verkauf.quote_pct + " %" : "–"}</b><span>Trefferquote Verkauf</span></div>
    </div>`;
  // Kopfzeile des Abendbriefings
  const tage = ["Sonntag", "Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag"];
  if (kursStand) { const dt = new Date(kursStand[0]);
    document.getElementById("heroDate").textContent = `${tage[dt.getDay()]}, ${dt.getDate()}. ${dt.toLocaleString("de-DE", {month: "long"})}`; }
  const auf = aufgaben(), nk = auf.filter(a => AKTION[a.status][0] === "kauf" && !(a.markt_filter && a.markt_filter.blockiert)).length,
    nv = auf.filter(a => AKTION[a.status][0] === "verkauf").length, L = d.marktfilter && d.marktfilter.lage, S = MARKT && MARKT.stimmung;
  const satz = [];
  if (L) satz.push(`Der Markt ist <b>${LAGE_SATZ[L.regime]}</b>`);
  if (S) satz.push(`${L ? "die" : "Die"} Stimmung steht bei <b>${S.wert} (${S.label})</b>`);
  document.getElementById("heroSum").innerHTML = (satz.length ? satz.join(", ") + ". " : "")
    + (EMPF.length ? `Empfohlen für heute Abend: <b>${EMPF.map(a => a.name).join(", ")}</b>. ` : "")
    + (nk || nv ? `Heute gibt es <b>${nk} ${nk === 1 ? "neues Kaufsignal" : "neue Kaufsignale"}</b> und <b>${nv} ${nv === 1 ? "Verkaufssignal" : "Verkaufssignale"}</b>.` : "Heute gibt es keine neuen Signale – bestehende Positionen halten.");
  render();
}

function render(){
  const q = document.getElementById("q").value.toLowerCase();
  const fl = document.getElementById("fLand").value, fs = document.getElementById("fSektor").value;
  let rows = DATA.filter(a => (filter === "alle" || kategorie(a) === filter) && (a.name + a.symbol).toLowerCase().includes(q)
    && (!fl || (a.meta && a.meta.land === fl)) && (!fs || (a.meta && a.meta.sektor === fs)));
  rows.sort((a, b) => {
    let x = a[sortKey], y = b[sortKey];
    if (sortKey === "ampel") { x = AMPEL_ORDER[x]; y = AMPEL_ORDER[y]; if (x === y) { x = -a.score; y = -b.score; } }
    return (x > y ? 1 : x < y ? -1 : 0) * sortDir;
  });
  document.getElementById("cnt").textContent = `${rows.length} von ${DATA.length}`;
  document.getElementById("tb").innerHTML = rows.map(a => `
    <tr class="row" data-sym="${a.symbol}">
      <td><span class="dot ${a.ampel}"></span></td>
      <td><span class="nm">${a.name}</span> <span class="mute small">${a.symbol}</span>${isEmpf(a) ? " " + empfTag : ""}${a.meta ? `<div class="sub">${[a.meta.land, a.meta.sektor].filter(Boolean).join(", ")}</div>` : ""}</td>
      <td class="num">${fmt(a.kurs, a.currency)}</td>
      <td class="num">${wTxt(a.perf && a.perf.woche)}</td>
      <td class="num">${scoreBadge(a.check)}</td>
      <td class="num hide-m">${crvBadge(a)}</td>
      <td class="num hide-m">${evBadge(a)}</td>
      <td title="${a.signal.replace(/"/g, "'")}">${a.status}${a.markt_filter && (a.markt_filter.blockiert || a.markt_filter.reduziert) ? ' <span class="tag warn">Filter</span>' : ""}${a.status_vorher && a.status_vorher !== a.status ? '<span class="tag new">neu</span>' : ""}</td>
      <td class="hide-m">${a.kurz ? `<span class="kz"><span class="dot ${a.kurz.ampel}"></span>${a.kurz.status}</span>` : '<span class="mute">–</span>'}</td>
      <td class="sig hide-l hide-m">${a.signal}${a.markt_filter && (a.markt_filter.blockiert || a.markt_filter.reduziert) ? ' <span class="tag warn" title="' + a.markt_filter.hinweise.join(" · ") + '">Marktfilter</span>' : ""}</td>
      <td class="hide-m">${anTxt(a)}</td>
      <td class="num hide-l hide-m">${qTxt(a)}</td>
      <td class="hide-m">${a.termine && a.termine.earnings ? dateDe(a.termine.earnings) + earnWarn(a) : '<span class="mute">–</span>'}</td>
    </tr>`).join("");
  document.querySelectorAll("tr.row").forEach(tr => tr.onclick = () => showDetail(tr.dataset.sym));
}

// ---------- Detail-Boxen ----------
function ringSvg(score){
  const r = 34, c = 2 * Math.PI * r, col = scoreCol(score);
  return `<svg width="88" height="88" viewBox="0 0 88 88"><circle cx="44" cy="44" r="${r}" stroke="var(--panel2)" stroke-width="9" fill="none"/>
    <circle cx="44" cy="44" r="${r}" stroke="${col}" stroke-width="9" fill="none" stroke-linecap="round" stroke-dasharray="${c * score / 100} ${c}" transform="rotate(-90 44 44)"/>
    <text x="44" y="50" text-anchor="middle" font-size="22" font-weight="800" fill="currentColor">${score}</text></svg>`;
}
function checkBox(a){
  const c = a.check; if (!c) return '<span class="mute">Wird beim nächsten Lauf berechnet.</span>';
  const parts = Object.entries(c.teile).map(([n, t]) => { const f = t.max ? t.punkte / t.max : 0;
    return `<div class="part"><span>${n}</span><span class="bar"><i style="width:${f * 100}%;background:${scoreCol(f * 100)}"></i></span><b style="text-align:right">${t.punkte}/${t.max}</b></div>`; }).join("");
  return `<div class="ring">${ringSvg(c.score)}<div><div class="lbl" style="color:${scoreCol(c.score)}">${c.label}</div>
      <div class="mute small">von 100 Punkten · Elliott, Analysten, Trend, Trefferquote & Quartale</div></div></div>
    <div class="parts">${parts}</div>
    <div class="pc"><div><b class="pos">Dafür</b><ul class="pro">${c.pro.map(x => `<li>${x}</li>`).join("") || '<li class="mute">–</li>'}</ul></div>
      <div><b class="neg">Dagegen</b><ul class="con">${c.contra.map(x => `<li>${x}</li>`).join("") || '<li class="mute">–</li>'}</ul></div></div>`;
}
function perfBox(a){
  const p = a.perf; if (!p) return '<span class="mute">Wird beim nächsten Lauf berechnet.</span>';
  const rows = [["Tag", p.tag, 3], ["Woche", p.woche, 8], ["Monat", p.monat, 15], ["Seit 1.1.", p.ytd, 40], ["1 Jahr", p.jahr, 50]];
  return `<div class="perf">${rows.map(([n, v, sc]) => { if (v == null) return "";
    const w = Math.min(50, Math.abs(v) / sc * 50);
    return `<div class="pr"><span>${n}</span><span class="axis"><i style="${v >= 0 ? "left:50%" : `left:${50 - w}%`};width:${Math.max(w, .8)}%;background:${heatCol(v, sc)}"></i></span><b class="${v >= 0 ? "pos" : "neg"}">${num1(v)}</b></div>`; }).join("")}</div>`;
}
function quartBox(a){
  const q = a.quartale || [];
  if (!q.length) return '<span class="mute">Keine Quartalsdaten verfügbar.</span>';
  const beats = q.filter(x => x.beat).length, bew = q.filter(x => x.beat != null).length;
  return `<div class="qs">${q.map(x => `<div class="q" style="background:${x.beat == null ? "#64748b" : x.beat ? "#15803d" : "#b91c1c"}">
      <div class="t">${dateDe(x.datum)}</div><div class="b">${x.beat == null ? "–" : x.beat ? "✓ Beat" : "✗ Miss"}</div>
      <div class="e">${x.ueberraschung_pct != null ? num1(x.ueberraschung_pct) : ""}</div>
      <div class="e">EPS ${fmt(x.ist)} / ${fmt(x.erwartet)}</div></div>`).join("")}</div>
    <div class="mute small" style="margin-top:6px">${beats} von ${bew} Quartalen über den Erwartungen (Gewinn je Aktie, Ist / erwartet).</div>`;
}
function anBox(a){
  const x = a.analysten, c = a.currency;
  if (!x) return '<span class="mute">Keine Analystendaten verfügbar.</span>';
  const v = x.verteilung;
  let st = "";
  if (v) {
    const parts = [["Strong Buy", v.strongBuy, "#15803d"], ["Buy", v.buy, "#4ade80"], ["Hold", v.hold, "#eab308"], ["Sell", v.sell, "#f87171"], ["Strong Sell", v.strongSell, "#b91c1c"]];
    const tot = parts.reduce((s, p) => s + (p[1] || 0), 0) || 1;
    st = `<div class="stack">${parts.map(p => p[1] ? `<i style="width:${p[1] / tot * 100}%;background:${p[2]}" title="${p[0]}: ${p[1]}"></i>` : "").join("")}</div>
      <div class="slg">${parts.map(p => `<span style="--c:${p[2]}">${p[0]} ${p[1] || 0}</span>`).join("")}</div>`;
  }
  let zb = "";
  if (x.ziel_mittel && a.kurs) {
    const lo = Math.min(x.ziel_tief || x.ziel_mittel, a.kurs) * .95, hi = Math.max(x.ziel_hoch || x.ziel_mittel, a.kurs) * 1.05;
    const pos = v => ((v - lo) / (hi - lo) * 100).toFixed(1);
    zb = `<div style="position:relative;height:26px;margin:14px 0 4px">
      <div style="position:absolute;top:11px;left:0;right:0;height:4px;border-radius:3px;background:var(--panel2)"></div>
      ${x.ziel_tief && x.ziel_hoch ? `<div style="position:absolute;top:11px;left:${pos(x.ziel_tief)}%;width:${pos(x.ziel_hoch) - pos(x.ziel_tief)}%;height:4px;background:color-mix(in srgb,var(--accent) 45%,transparent)"></div>` : ""}
      <div title="Kurs" style="position:absolute;top:4px;left:calc(${pos(a.kurs)}% - 2px);width:4px;height:18px;border-radius:2px;background:var(--txt)"></div>
      <div title="Ø-Kursziel" style="position:absolute;top:6px;left:calc(${pos(x.ziel_mittel)}% - 7px);width:14px;height:14px;border-radius:50%;background:var(--accent)"></div></div>
      <div class="mute small">▮ Kurs ${fmt(a.kurs)} · ● Ø-Ziel ${fmt(x.ziel_mittel, c)}${x.ziel_tief ? ` · Spanne ${fmt(x.ziel_tief)}–${fmt(x.ziel_hoch)}` : ""}</div>`;
  }
  return `<b><span class="dot ${x.ampel || ""}"></span> ${x.rating || "–"}</b>${x.anzahl ? ` <span class="mute">· ${x.anzahl} Analysten</span>` : ""}
    ${x.potenzial_pct != null ? ` · Potenzial ${pctTxt(x.potenzial_pct)}` : ""}${st}${zb}`;
}
function btBox(a){
  const b = a.backtest;
  if (!b) return '<span class="mute">Keine Daten.</span>';
  const meter = (t, f, lbl) => { const n = t + f; if (!n) return `<div class="small mute">${lbl}: noch keine abgeschlossenen Signale</div>`;
    const q = Math.round(t / n * 100);
    return `<div class="small"><b>${lbl}: ${q} %</b> <span class="mute">(${t} Treffer, ${f} Fehler)</span></div><div class="meter"><i style="width:${q}%;background:${scoreCol(q)}"></i></div>`; };
  const v = b.verkauf || {treffer: 0, fehler: 0};
  const icon = {treffer: "🟢", fehler: "🔴", offen: "⚪"};
  const rows = (b.signale || []).slice().reverse().slice(0, 8).map(s =>
    `<tr><td>${icon[s.ergebnis]} ${dateDe(s.datum)}</td><td class="num">${fmt(s.einstieg)}</td><td class="num">${fmt(s.ziel)}</td><td class="num">${s.ergebnis === "offen" ? "offen" : pctTxt(s.rendite_pct)}</td></tr>`).join("");
  return meter(b.treffer, b.fehler, "Kaufsignale") + meter(v.treffer || 0, v.fehler || 0, "Verkaufssignale")
    + (rows ? `<table class="plan" style="width:100%;margin-top:6px"><tr class="mute"><td>Kaufsignal</td><td class="num">Einstieg</td><td class="num">Ziel</td><td class="num">Ergebnis</td></tr>${rows}</table>` : "")
    + `<div class="mute small" style="margin-top:4px">Kauf-Treffer = halber Weg zum alten Hoch vor Invalidierung. Verkauf-Treffer = nach „Impuls vollendet“ erst −10 % statt +10 %.</div>`;
}
function scBox(v){
  const s = v.szenarien; if (!s) return '<span class="mute">–</span>';
  const pr = x => x.prob_pct != null ? x.prob_pct : null;
  const ph = pr(s.haupt);
  const bar = ph != null ? `<div class="stack" style="height:10px"><i style="width:${ph}%;background:#22c55e"></i><i style="width:${100 - ph}%;background:#f97316"></i></div>` : "";
  return `${bar}<div class="scen"><i style="border-color:#22c55e"></i><div><b>Haupt:</b> ${s.haupt.name}${ph != null ? ` <b>${ph} %</b>` : ""}<br><span class="mute">${s.haupt.text}</span></div></div>
    <div class="scen"><i style="border-color:#f97316"></i><div><b>Alternative:</b> ${s.alternative.name}${pr(s.alternative) != null ? ` <b>${pr(s.alternative)} %</b>` : ""}<br><span class="mute">${s.alternative.text}</span></div></div>
    <div class="mute small">Wahrscheinlichkeit ${s.basis === "Backtest" ? "aus dem Backtest abgeleitet" : "geschätzt (keine Backtest-Basis)"}. Pfade sind schematisch.</div>`;
}
function newsBox(a){
  const n = a.news || []; if (!n.length) return '<span class="mute">Keine aktuellen News.</span>';
  return `<ul class="news" style="padding-left:16px;margin:0">${n.map(x => `<li><a href="${x.url}" target="_blank" rel="noopener">${x.titel}</a><br><span class="mute small">${[x.quelle, x.datum ? dateDe(x.datum) : ""].filter(Boolean).join(" · ")}</span></li>`).join("")}</ul>`;
}
function termBox(a){
  const t = a.termine || {}; const r = [];
  if (t.earnings) r.push(`Quartalszahlen: <b>${dateDe(t.earnings)}</b> <span class="mute">(in ${t.earnings_in_tagen} Tagen)</span>`);
  if (t.ex_dividende) r.push(`Ex-Dividende: ${dateDe(t.ex_dividende)}`);
  if (t.dividende_zahltag) r.push(`Dividenden-Zahltag: ${dateDe(t.dividende_zahltag)}`);
  return r.length ? r.join("<br>") : '<span class="mute">Keine anstehenden Termine bekannt.</span>';
}

// ---------- Detail (Overlay) ----------
function closeDetail(){ openSym = null; document.getElementById("ov").style.display = "none"; document.body.style.overflow = ""; if (chart) { chart.remove(); chart = null; } }
async function getFull(a){
  if (DETAIL[a.symbol]) return DETAIL[a.symbol];
  if (a.datei) {
    try { const r = await fetch("aktien/" + a.datei + "?ts=" + Date.now()); if (r.ok) { DETAIL[a.symbol] = {...a, ...(await r.json())}; return DETAIL[a.symbol]; } } catch(e) {}
  }
  return a;
}
async function showDetail(sym, h){
  const a0 = DATA.find(x => x.symbol === sym); if (!a0) return;
  openSym = sym; horizon = h || "lang";
  const ov = document.getElementById("ov"), el = document.getElementById("detail");
  if (chart) { chart.remove(); chart = null; }
  if (!DETAIL[sym]) { el.innerHTML = `<h2>${a0.name}</h2><div class="mute">lädt …</div>`; ov.style.display = "block"; document.body.style.overflow = "hidden"; }
  const a = await getFull(a0);
  if (openSym !== sym) return;
  const hasKurz = !!(a.kurz && a.kurz.chart);
  if (!hasKurz) horizon = "lang";
  const v = horizon === "kurz" ? a.kurz : a, c = a.currency, k = a.kurs;
  const planRow = (label, val, color) => val == null ? "" :
    `<tr><td><span class="dot" style="background:${color}"></span> ${label}</td><td class="num">${fmt(val, c)}</td><td class="num">${pctTxt(pct(val, k))}</td></tr>`;
  const tab = (h, lbl, x) => `<button data-h="${h}" class="${horizon === h ? "on" : ""}" ${x ? "" : "disabled"}>${lbl}${x ? ` <span class="dot ${x.ampel}"></span> ${x.status}` : ""}</button>`;
  const w = v.welle || {};
  const mf = a.markt_filter || {}, crv = crvCalc(v, k);
  el.innerHTML = `
    <div class="dtop">
      <div><h2><span class="dot ${a.ampel}" style="width:12px;height:12px"></span>${a.name}<span class="sym">${a.symbol}</span></h2>
        <div class="dprice"><b>${fmt(k, c)}</b>${a.perf ? pctTxt(a.perf.tag) + " heute" : ""} <span class="mute">· Stand ${dateDe(a.stand)}${a.meta ? " · " + [a.meta.land, a.meta.sektor].filter(Boolean).join(", ") : ""}</span></div></div>
      <button class="btn" id="closeBtn">✕ Schließen</button>
    </div>
    <div class="dtools">
      <div class="htabs" role="tablist">${tab("lang", "Langfristig", a)}${tab("kurz", "Kurzfristig", hasKurz ? a.kurz : null)}</div>
      ${a.check ? `<span class="kbadge">Entscheidungscheck ${a.check.label} ${scoreBadge(a.check)}</span>` : ""}
      ${crv && crv.ok ? `<span class="kbadge">Chance/Risiko <span class="score" style="background:${crvCol(crv.crv)}">${crvTxt(crv.crv)}</span></span>` : ""}
      ${isEmpf(a0) ? empfTag : ""}${mf.blockiert || mf.reduziert ? '<span class="tag warn">Marktfilter</span>' : ""}${earnWarn(a)}
    </div>
    <div class="dmain">
      <div class="chartbox"><div id="chart"></div>
        <div class="legend">
          <span><i style="background:#a855f7"></i>Elliott-Wellen</span>
          <span><i style="background:var(--zone)"></i>Einstiegszone</span>
          <span><i style="background:#93c5fd"></i>Nachkauf 61,8 %</span>
          <span><i style="background:var(--red)"></i>Invalidierung</span>
          <span><i style="background:var(--green)"></i>Ziele</span>
          ${v.welle && v.welle.alternative ? `<span><i style="height:0;border-top:3px dotted #ec4899"></i>Alternative Zählung <b>${v.welle.alternative.gewicht_pct} %</b></span>` : ""}
          ${v.szenarien ? `<span><i style="height:0;border-top:3px dashed #22c55e"></i>Hauptszenario ${v.szenarien.haupt.prob_pct != null ? "<b>" + v.szenarien.haupt.prob_pct + " %</b>" : ""}</span><span><i style="height:0;border-top:3px dashed #f97316"></i>Alternative ${v.szenarien.alternative.prob_pct != null ? "<b>" + v.szenarien.alternative.prob_pct + " %</b>" : ""}</span>` : ""}
          <span>${horizon === "kurz" ? "Tageskerzen, Wellen über Wochen bis Monate" : "Wochenkerzen, Wellen über Monate bis Jahre"}</span>
        </div></div>
      <div class="dright">
        <div class="box sigcard" style="--c:var(--${v.ampel === "gruen" ? "green" : v.ampel === "rot" ? "red" : "orange"})"><h3>Signal ${horizon === "kurz" ? "kurzfristig" : "langfristig"}</h3>
          <div class="sigbig"><span class="dot ${v.ampel}"></span>${v.status}</div><div class="sigtxt">${v.signal}</div>
          ${horizon === "lang" && mf.hinweise && mf.hinweise.length ? `<div class="mfbox">${mf.hinweise.map(h => `<div>🧭 ${h}</div>`).join("")}${mf.signal_original ? `<div class="mute small">Ohne Marktfilter: ${mf.signal_original}</div>` : ""}</div>` : ""}
          ${hasKurz ? `<div class="mute small" style="margin-top:10px">${horizon === "kurz" ? `Langfristig: <span class="dot ${a.ampel}"></span> ${a.status}` : `Kurzfristig: <span class="dot ${a.kurz.ampel}"></span> ${a.kurz.status}`}</div>` : ""}</div>
        <div class="box"><h3>Chance & Risiko</h3>${riskBox(a, v)}</div>
      </div>
    </div>
    <div class="drow3">
      <div class="box"><h3>Szenarien</h3>${scBox(v)}</div>
      <div class="box"><h3>Handlungsplan</h3>
        <table class="plan">
          ${v.plan ? planRow("Teilkauf 1 (38,2 %)", v.plan.teilkauf_1, "#3b82f6") + planRow("Teilkauf 2 (50 %)", v.plan.teilkauf_2, "#3b82f6")
            + planRow("Teilkauf 3 (61,8 %)", v.plan.teilkauf_3, "#93c5fd") + planRow("Invalidierung (78,6 %)", v.plan.invalidierung, "#ef4444")
            + planRow("Teilverkauf 1 (altes Hoch)", v.plan.teilverkauf_1, "#22c55e") + planRow("Teilverkauf 2 (127,2 %)", v.plan.teilverkauf_2, "#22c55e")
            + planRow("Teilverkauf 3 (161,8 %)", v.plan.teilverkauf_3, "#22c55e") : ""}
        </table></div>
      <div class="box"><h3>Wellenstruktur</h3>
        ${w.start ? `<div class="facts">
          <div><b>${fmt(w.start.price)}</b><span>Start ${dateDe(w.start.date)}</span></div>
          <div><b>${fmt(w.hoch.price)}</b><span>Hoch ${dateDe(w.hoch.date)}</span></div>
          <div><b>${(w.retracement_aktuell_pct || 0).toLocaleString("de-DE")} %</b><span>Korrektur aktuell</span></div>
          <div><b>${(w.retracement_max_pct || 0).toLocaleString("de-DE")} %</b><span>Korrektur maximal</span></div>
          <div><b>${w.zaehlung_qualitaet ? w.zaehlung_qualitaet + " / 100" : "–"}</b><span>Zählqualität</span></div>
          ${w.alternative ? `<div style="grid-column:1/-1"><b style="color:#ec4899">${100 - w.alternative.gewicht_pct} % / ${w.alternative.gewicht_pct} %</b><span>Hauptzählung / alternative Zählung (Qualität ${w.alternative.qualitaet} / 100, rosa gepunktet im Chart)</span></div>` : ""}
          <div><b>${a.trend_tageschart || "–"}</b><span>Trend Tageschart</span></div>
          <div><b>${fmt(a.sma50)}</b><span>50-Tage-Linie</span></div>
          <div><b>${fmt(a.sma200)}</b><span>200-Tage-Linie</span></div>
        </div>` : '<span class="mute">Keine Wellendaten.</span>'}</div>
    </div>
    <div class="dmason">
      <div class="box"><h3>Entscheidungscheck</h3>${checkBox(a)}</div>
      <div class="box"><h3>Über Nacht</h3>${nachtBox(a)}</div>
      <div class="box"><h3>Saisonalität</h3>${saisonBox(a)}</div>
      <div class="box"><h3>Performance</h3>${perfBox(a)}</div>
      <div class="box"><h3>Letzte 4 Quartale</h3>${quartBox(a)}</div>
      <div class="box"><h3>Analysten</h3>${anBox(a)}</div>
      <div class="box"><h3>Trefferquote dieser Aktie</h3>${btBox(a)}</div>
      <div class="box"><h3>Termine</h3>${termBox(a)}</div>
      <div class="box"><h3>News</h3>${newsBox(a)}</div>
    </div>`;
  ov.style.display = "block"; document.body.style.overflow = "hidden";
  document.getElementById("closeBtn").onclick = closeDetail;
  el.querySelectorAll("[data-h]").forEach(b => b.onclick = () => { if (!b.disabled) showDetail(sym, b.dataset.h); });
  if (v.chart && v.chart.length) drawChart(v, horizon); else document.getElementById("chart").innerHTML = '<div class="empty">Chartdaten kommen mit dem nächsten Lauf.</div>';
}

function drawChart(v, h){
  const box = document.getElementById("chart");
  chart = LightweightCharts.createChart(box, {
    layout: {background: {color: cssVar("--panel")}, textColor: cssVar("--mute"), fontFamily: "Inter, system-ui, sans-serif"},
    grid: {vertLines: {color: cssVar("--chart-grid")}, horzLines: {color: cssVar("--chart-grid")}},
    rightPriceScale: {borderColor: cssVar("--line")}, timeScale: {borderColor: cssVar("--line")},
    autoSize: true, localization: {locale: "de-DE"},
  });
  const s = chart.addCandlestickSeries({upColor: "#22c55e", downColor: "#ef4444", borderVisible: false, wickUpColor: "#22c55e", wickDownColor: "#ef4444"});
  s.setData(v.chart);
  const line = (price, color, title, style = 0, w = 2) => price != null && s.createPriceLine({price, color, lineWidth: w, lineStyle: style, axisLabelVisible: true, title});
  line(v.zone.oben, "#3b82f6", "Zone oben");
  line(v.zone.unten, "#3b82f6", "Zone unten");
  line(v.zone.nachkauf, "#93c5fd", "Nachkauf", 2, 1);
  line(v.zone.invalidierung, "#ef4444", "Invalidierung", 2, 1);
  line(v.ziele.t1, "#22c55e", "Ziel 1", 2, 1);
  line(v.ziele.t2, "#22c55e", "Ziel 2", 2, 1);

  // Wellen-Punkte auf die nächstgelegene Kerze legen
  const times = v.chart.map(c => c.time), t0 = times[0], tN = times[times.length - 1];
  const snap = d => { if (d < t0 || d > tN) return null; let best = times[0], bd = Infinity;
    for (const t of times) { const dd = Math.abs(new Date(t) - new Date(d)); if (dd < bd) { bd = dd; best = t; } } return best; };
  const labels = ((v.welle && v.welle.labels) || []).map(l => ({...l, t: snap(l.date)})).filter(l => l.t).sort((x, y) => x.t < y.t ? -1 : 1);
  const uniq = []; labels.forEach(l => { if (!uniq.length || uniq[uniq.length - 1].t !== l.t) uniq.push(l); });
  if (uniq.length >= 2) {
    const wl = chart.addLineSeries({color: "#a855f7", lineWidth: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false});
    wl.setData(uniq.map(l => ({time: l.t, value: l.price})));
  }
  const lblCol = cssVar("--txt");
  const lowSet = ["0", "2", "4", "Start", "Korr.-Tief", "A", "C"];
  s.setMarkers(uniq.map(l => {
    const low = lowSet.includes(l.label);
    return {time: l.t, position: low ? "belowBar" : "aboveBar", color: /^\d$/.test(l.label) ? "#a855f7" : (low ? "#f59e0b" : lblCol),
            shape: low ? "arrowUp" : "arrowDown", text: /^\d$/.test(l.label) ? `(${l.label})` : l.label};
  }));

  // Alternative Wellenzählung (gepunktet)
  const alt = v.welle && v.welle.alternative;
  if (alt && alt.labels) {
    const al = alt.labels.map(l => ({...l, t: snap(l.date)})).filter(l => l.t).sort((x, y) => x.t < y.t ? -1 : 1);
    const au = []; al.forEach(l => { if (!au.length || au[au.length - 1].t !== l.t) au.push(l); });
    if (au.length >= 2) {
      const als = chart.addLineSeries({color: "#ec4899", lineWidth: 2, lineStyle: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false});
      als.setData(au.map(l => ({time: l.t, value: l.price})));
      als.setMarkers(au.filter(l => !["0", "5"].includes(l.label)).map(l => ({time: l.t, position: ["2", "4"].includes(l.label) ? "belowBar" : "aboveBar",
        color: "#ec4899", shape: "circle", size: 0.4, text: `${l.label}'`})));
    }
  }

  // Szenario-Pfade: wöchentlich (lang) bzw. börsentäglich (kurz) interpolieren
  if (v.szenarien) {
    const DAY = 864e5;
    const expand = pfad => { const out = [];
      for (let i = 0; i < pfad.length - 1; i++) {
        const a0 = new Date(pfad[i].time).getTime(), a1 = new Date(pfad[i + 1].time).getTime();
        if (h === "kurz") {
          const days = []; for (let t = a0; t < a1; t += DAY) { const wd = new Date(t).getUTCDay(); if (wd !== 0 && wd !== 6) days.push(t); }
          const n = Math.max(1, days.length);
          days.forEach((t, k) => out.push({time: new Date(t).toISOString().slice(0, 10), value: pfad[i].value + (pfad[i + 1].value - pfad[i].value) * k / n}));
        } else {
          const n = Math.max(1, Math.round((a1 - a0) / (7 * DAY)));
          for (let k = 0; k < n; k++) out.push({time: new Date(a0 + k * 7 * DAY).toISOString().slice(0, 10), value: pfad[i].value + (pfad[i + 1].value - pfad[i].value) * k / n});
        }
      }
      out.push(pfad[pfad.length - 1]);
      const seen = new Set(); return out.filter(p => !seen.has(p.time) && seen.add(p.time));
    };
    const ls = (pfad, color, w) => { if (!pfad || pfad.length < 2) return;
      const l = chart.addLineSeries({color, lineWidth: w, lineStyle: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false}); l.setData(expand(pfad)); };
    ls(v.szenarien.alternative.pfad, "#f97316", 2);
    ls(v.szenarien.haupt.pfad, "#22c55e", 3);
  }
  chart.timeScale().fitContent();
}

// ---------- Erwartungswert, Übernacht, Saisonalität ----------
const sgn2 = v => v == null ? "–" : (v >= 0 ? "+" : "−") + Math.abs(v).toFixed(2).replace(".", ",");
const evCol = e => e >= 0.2 ? "#16a34a" : e > 0 ? "#ca8a04" : "#dc2626";
const evTxt = e => (e >= 0 ? "+" : "−") + Math.abs(e).toFixed(2).replace(".", ",") + " R";
function evBadge(a){
  if (a.ev == null || a.ev === -99) return '<span class="mute">–</span>';
  return `<span class="evb" style="color:${evCol(a.ev)};border-color:${evCol(a.ev)}" title="Erwartungswert pro Trade: im Schnitt ${evTxt(a.ev)} je eingesetztem Risiko (Trefferquote ca. ${a.ev_p_pct} %, CRV ${a.crv > 0 ? crvTxt(a.crv) : "–"})">${evTxt(a.ev)}</span>`;
}
const MONATE = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"];
const MONATE_LANG = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"];
function nachtBox(a){
  const u = a.uebernacht; if (!u) return '<span class="mute">Noch keine Daten – kommen mit dem nächsten Lauf.</span>';
  const row = (lbl, v, pos) => v == null ? "" : `<div class="rk"><span>${lbl}</span><b class="${v >= 0 ? "pos" : "neg"}">Ø ${sgn2(v)} %${pos != null ? ` · ${pos} % positiv` : ""}</b></div>`;
  return `<div class="crvhead"><span class="score" style="background:${u.pos_pct >= 55 ? "#16a34a" : u.pos_pct >= 48 ? "#ca8a04" : "#dc2626"};font-size:16px;height:30px;min-width:64px">${u.pos_pct} %</span>
      <span class="small mute">der Nächte positiv – vom Schlusskurs am Abend bis zur Eröffnung am nächsten Morgen.</span></div>
    ${row("Alle Nächte", u.mittel_pct, null)}
    ${row(`Nach einem Minustag (≤ −2 %, ${u.n_minus}×)`, u.nach_minus_pct, u.nach_minus_pos_pct)}
    ${row("Nach einem Plustag (≥ +2 %)", u.nach_plus_pct, null)}
    <div class="rk"><span>Beste / schlechteste Nacht</span><b><span class="pos">${sgn2(u.beste_pct)} %</span> / <span class="neg">${sgn2(u.schlechteste_pct)} %</span></b></div>
    <div class="mute small" style="margin-top:6px">Basis: ${u.n} Handelstage (ca. 2 Jahre), Schlusskurs → Eröffnung am nächsten Handelstag. Abends gekauft und morgens verkauft wird außerbörslich zu leicht abweichenden Kursen.</div>`;
}
function saisonBars(ms, cur){
  const ok = (ms || []).filter(m => m.mittel_pct != null); if (!ok.length) return "";
  const mx = Math.max(...ok.map(m => Math.abs(m.mittel_pct)), 1);
  return `<div class="sbars">${ms.map(m => { const v = m.mittel_pct, h = v == null ? 0 : Math.abs(v) / mx * 46;
    return `<div class="sb${m.m === cur ? " cur" : ""}" title="${MONATE_LANG[m.m - 1]}: ${v == null ? "zu wenige Daten" : `Ø ${num1(v)}, ${m.pos_pct} % der Jahre positiv (${m.n} Jahre)`}">
      <div class="sbu">${v != null && v >= 0 ? `<i style="height:${h}px;background:${heatCol(v, mx)}"></i>` : ""}</div>
      <div class="sbd">${v != null && v < 0 ? `<i style="height:${h}px;background:${heatCol(v, mx)}"></i>` : ""}</div>
      <span>${MONATE[m.m - 1].slice(0, 1)}</span></div>`; }).join("")}</div>`;
}
function saisonBox(a){
  const ms = a.saison; if (!ms) return '<span class="mute">Noch keine Daten – kommen mit dem nächsten Lauf.</span>';
  const cur = Number((a.stand || "").slice(5, 7)), c = ms.find(m => m.m === cur), nx = ms.find(m => m.m === cur % 12 + 1);
  const satz = m => m && m.mittel_pct != null ? `im Schnitt <b class="${m.mittel_pct >= 0 ? "pos" : "neg"}">${num1(m.mittel_pct)}</b>, in <b>${m.pos_pct} %</b> der Jahre positiv` : "zu wenige Daten";
  return saisonBars(ms, cur) + `<div class="small" style="margin-top:8px"><b>${MONATE_LANG[cur - 1]}:</b> ${satz(c)}.<br><b>${MONATE_LANG[cur % 12]}:</b> ${satz(nx)}.</div>
    <div class="mute small" style="margin-top:4px">Durchschnittliche Monatsrendite der letzten bis zu 10 Jahre. Saisonalität ist nur ein Rückenwind, kein Signal.</div>`;
}

// ---------- Mini-Linie ----------
function spark(xs, w = 96, h = 28){
  if (!xs || xs.length < 2) return "";
  const lo = Math.min(...xs), hi = Math.max(...xs), r = hi - lo || 1;
  const pts = xs.map((v, i) => `${(i / (xs.length - 1) * w).toFixed(1)},${(h - 2 - (v - lo) / r * (h - 4)).toFixed(1)}`).join(" ");
  const col = xs[xs.length - 1] >= xs[0] ? "var(--green)" : "var(--red)";
  return `<svg class="spark" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" aria-hidden="true"><polyline points="${pts}" fill="none" stroke="${col}" stroke-width="1.6" stroke-linejoin="round"/></svg>`;
}

// ---------- Reiter: Markt ----------
function renderMarkt(){
  const el = document.getElementById("mkt"), m = MARKT || {}, k = RAW.kommentar;
  const kurs = (x, e) => x.kurs.toLocaleString("de-DE", {maximumFractionDigits: x.kurs < 10 ? 4 : x.kurs < 1000 ? 2 : 0}) + (e === "%" ? " %" : "");
  const zeile = (x, e) => `<div class="mkrow"><div><b>${x.name}</b><div class="mute small">${x.monat_pct != null ? "1 M " + num1(x.monat_pct) : ""}${x.jahr_pct != null ? " · 1 J " + num1(x.jahr_pct) : ""}</div></div>
    ${spark(x.spark)}<div class="num"><b>${kurs(x, e)}</b><div class="small">${pctTxt(x.tag_pct)}</div></div></div>`;
  const idx = (m.indizes || []).filter(x => !["GC=F", "EURUSD=X", "BTC-USD"].includes(x.symbol));
  const mak = m.makro || [];
  // Termine der Woche: Makro + Quartalszahlen der Watchlist (nächste 7 Tage)
  const tm = [];
  MAKRO.forEach(t => { const n = daysTo(t.datum); if (n >= 0 && n <= 7) tm.push([t.datum, `${FLAG[landOf(t)]} <b>${t.titel}</b><span class="kat">${t.kategorie}</span>`]); });
  DATA.forEach(a => { const t = a.termine || {}; if (t.earnings && t.earnings_in_tagen != null && t.earnings_in_tagen <= 7) tm.push([t.earnings, `<span class="dot ${a.ampel}"></span> <b>${a.name}</b> <span class="mute small">Quartalszahlen</span>`]); });
  tm.sort((x, y) => x[0] < y[0] ? -1 : 1);
  const cur = STAND ? Number(STAND.slice(5, 7)) : new Date().getMonth() + 1;
  const sais = (m.saison || []).map(s => { const c = (s.monate || []).find(x => x.m === cur);
    return `<div style="margin-bottom:10px"><div class="small"><b>${s.name}</b> im ${MONATE_LANG[cur - 1]}: ${c && c.mittel_pct != null ? `Ø ${pctTxt(c.mittel_pct)}, ${c.pos_pct} % der Jahre positiv` : "–"}</div>${saisonBars(s.monate, cur)}</div>`; }).join("");
  el.innerHTML = `
    ${k ? `<div class="kommentar"><div class="k">Abendkommentar${STAND ? " · " + wdKurz(STAND) : ""}</div><h3>${k.titel}</h3><p>${k.text}</p></div>` : ""}
    <div class="mkgrid">
      <div class="mkcol"><div class="k">Indizes</div>${idx.map(x => zeile(x)).join("") || '<div class="empty">Kommt mit dem nächsten Lauf.</div>'}</div>
      <div class="mkcol"><div class="k">Zinsen, Währung, Rohstoffe</div>${mak.map(x => zeile(x, x.einheit)).join("") || '<div class="empty">Kommt mit dem nächsten Lauf.</div>'}</div>
      <div class="mkcol"><div class="k">Saisonalität (Monatsrenditen, 20 Jahre)</div>${sais || '<div class="empty">Kommt mit dem nächsten Lauf.</div>'}</div>
      <div class="mkcol"><div class="k">Termine der nächsten 7 Tage</div>${tm.length ? `<ul class="list">${tm.map(([d, h]) => `<li><span class="date">${dateWd(d)}</span> ${h}</li>`).join("")}</ul>` : '<div class="empty">Keine wichtigen Termine.</div>'}</div>
    </div>`;
}

// ---------- Reiter: News ----------
const ENTRY_ST = ["In Zone", "In Zone (unten)", "Nachkaufbereich"];
function newsKontext(n){
  const z = n.zone || {};
  if (ENTRY_ST.includes(n.status)) return ["g", `liegt jetzt im Einstiegsbereich (Zone ${fmt(z.unten)}–${fmt(z.oben)})`];
  if (n.status === "Abwärtstrend") return ["r", `unter der Invalidierung – Abwärtstrend, nicht kaufen`];
  if (n.status === "Zulaufend" && z.oben) return ["o", `Kaufzone erst bei ${fmt(z.oben)} (${num1(pct(z.oben, n.kurs))})`];
  if (["Ziel 1 erreicht", "Ziel 2 erreicht", "Impuls vollendet"].includes(n.status)) return ["o", `${n.status} – Gewinne sichern prüfen`];
  return ["", n.status];
}
function renderNews(){
  const el = document.getElementById("newsP"), xs = RAW.wichtige_news || [];
  if (!xs.length) { el.innerHTML = `<div class="empty">${RAW.wichtige_news ? "Heute hat sich keine Watchlist-Aktie um mehr als 4 % bewegt." : "Kommt mit dem nächsten Analyse-Lauf."}</div>`; return; }
  el.innerHTML = `<p class="mute small" style="margin:0 0 10px">Nur Meldungen zu Watchlist-Aktien, die sich heute um mindestens 4 % bewegt haben – mit Einordnung zur Elliott-Zone.</p>
    <div class="ngrid">${xs.map(n => { const [c, txt] = newsKontext(n), up = n.tag_pct >= 0, nw = n.news;
      return `<div class="ncard ${up ? "up" : "down"}"><div class="nhead"><span class="sym" data-sym="${n.symbol}">${n.name}</span>
          <b class="${up ? "pos" : "neg"}">${up ? "▲" : "▼"} ${num1(n.tag_pct)}</b><span class="chip ${up ? "g" : "r"}">${up ? "positiv" : "negativ"}</span></div>
        ${nw ? `<a class="ntitle" href="${nw.url}" target="_blank" rel="noopener">${nw.titel}</a><div class="mute small">${[nw.quelle, nw.datum ? dateDe(nw.datum) : ""].filter(Boolean).join(" · ")}</div>` : '<div class="mute small">Keine passende Meldung gefunden.</div>'}
        <div class="nctx"><span class="dot ${n.ampel}"></span> ${c ? `<span class="chip ${c}">${txt}</span>` : txt}</div></div>`; }).join("")}</div>`;
  el.querySelectorAll("[data-sym]").forEach(x => x.onclick = () => showDetail(x.dataset.sym));
}

// ---------- Reiter: Chancen-Finder ----------
let chTab = "ruecksetzer";
function tvLink(sym){ return "https://www.tradingview.com/chart/?symbol=" + encodeURIComponent(sym.endsWith(".DE") ? "XETR:" + sym.slice(0, -3) : sym); }
function renderChancen(){
  const el = document.getElementById("chP"), c = RAW.chancen;
  if (!c) { el.innerHTML = '<div class="empty">Kommt mit dem nächsten Analyse-Lauf.</div>'; return; }
  const xs = c[chTab] || [];
  const erkl = chTab === "ruecksetzer"
    ? "Starke Aktien im Aufwärtstrend (über der 200-Tage-Linie, gutes Halbjahr), die gerade an ihre 50-Tage-Linie zurückgekommen sind – RSI abgekühlt."
    : "Aktien knapp unter ihrem 52-Wochen-Hoch mit enger Seitwärtsphase der letzten 4 Wochen – oft die Ruhe vor einem Ausbruch.";
  el.innerHTML = `<div class="chhead"><span class="seg small"><button data-ch="ruecksetzer" class="${chTab === "ruecksetzer" ? "on" : ""}">Rücksetzer im Trend (${(c.ruecksetzer || []).length})</button><button data-ch="ausbruch" class="${chTab === "ausbruch" ? "on" : ""}">Vor dem Ausbruch (${(c.ausbruch || []).length})</button></span>
      <span class="mute small">${c.geprueft} von ${c.universum} großen US- und deutschen Aktien geprüft</span></div>
    <p class="mute small" style="margin:8px 0 10px">${erkl} Das ist ein Vorfilter, kein Kaufsignal – erst nach der vollen Elliott-Analyse kaufen.</p>
    ${xs.length ? `<div class="chgrid">${xs.map((x, i) => { const e = x.elliott_kurz;
      const chips = chTab === "ruecksetzer"
        ? [`Halbjahr ${num1(x.halbjahr_pct)}`, `${num1(x.abstand_sma50_pct)} zur 50-T-Linie`, `RSI ${x.rsi}`]
        : [`${num1(x.abstand_hoch_pct)} unter Hoch`, `Spanne 4 Wo. ${x.enge_pct.toFixed(1).replace(".", ",")} %`, `Halbjahr ${num1(x.halbjahr_pct)}`];
      return `<div class="chcard"><div class="chtop"><span class="rank">${i + 1}</span><div style="min-width:0"><b>${x.name}</b> <span class="mute small">${x.symbol}</span></div>
          <div class="num"><b>${fmt(x.kurs, x.currency === "EUR" ? "€" : "$")}</b><div class="small">1 M ${pctTxt(x.monat_pct)}</div></div></div>
        <div class="chips2">${chips.map(t => `<span class="chip2">${t}</span>`).join("")}</div>
        ${e ? `<div class="small" style="margin-top:6px"><span class="dot ${e.ampel}"></span> Elliott kurzfristig: <b>${e.status}</b>${e.zone_oben ? ` · Zone ${fmt(e.zone_unten)}–${fmt(e.zone_oben)}` : ""}</div>` : ""}
        <div class="chact">${x.in_watchlist ? `<button class="btn small" data-sym="${x.symbol}">✓ schon in der Watchlist</button>` : `<button class="btn small" data-add="${x.symbol}" data-name="${x.name.replace(/"/g, "")}">＋ Zur Watchlist</button>`}
          <a class="btn small" href="${tvLink(x.symbol)}" target="_blank" rel="noopener">Chart ↗</a><span class="mute small" style="margin-left:auto">Punkte ${x.punkte}</span></div></div>`; }).join("")}</div>`
      : '<div class="empty">Heute erfüllt keine Aktie die Kriterien.</div>'}`;
  el.querySelectorAll("[data-ch]").forEach(b => b.onclick = () => { chTab = b.dataset.ch; renderChancen(); });
  el.querySelectorAll("[data-sym]").forEach(b => b.onclick = () => showDetail(b.dataset.sym));
  el.querySelectorAll("[data-add]").forEach(b => b.onclick = async () => {
    const line = `${b.dataset.add},${b.dataset.name}`;
    try { await navigator.clipboard.writeText(line); } catch(e) {}
    b.textContent = "✓ Zeile kopiert – unten in die Watchlist einfügen";
    window.open(document.getElementById("editWl").href, "_blank", "noopener");
  });
}

// ---------- Reiter: Live-Bilanz ----------
let LB = null, lbTab = "alle";
async function renderLive(){
  const el = document.getElementById("lbP");
  if (LB === null) {
    try { const r = await fetch("live_bilanz.json?ts=" + Date.now()); LB = r.ok ? await r.json() : false; } catch(e) { LB = false; }
  }
  if (!LB) { el.innerHTML = '<div class="empty">Die Live-Bilanz startet mit dem nächsten Analyse-Lauf. Ab dann wird jedes neue Kaufsignal mit echten Kursen nachgehalten.</div>'; return; }
  const all = LB.trades || [], ts = all.filter(t => lbTab === "alle" || (lbTab === "empfohlen" ? t.empfohlen : t.horizont === lbTab));
  const st = (LB.statistik || {})[lbTab] || {};
  const zu = (st.ziel || 0) + (st.stopp || 0);
  const tile = (lbl, val, sub, col) => `<div class="lbt"><span>${lbl}</span><b style="${col ? "color:" + col : ""}">${val}</b>${sub ? `<em>${sub}</em>` : ""}</div>`;
  const rTxt = v => v == null ? "–" : (v >= 0 ? "+" : "−") + Math.abs(v).toFixed(2).replace(".", ",") + " R";
  const rCol = v => v == null ? "" : v > 0 ? "var(--green)" : v < 0 ? "var(--red)" : "";
  const ERG = {ziel: '<span class="chip g">Ziel erreicht</span>', stopp: '<span class="chip r">Stopp</span>', offen: '<span class="chip o">läuft</span>'};
  el.innerHTML = `<div class="chhead"><span class="seg small">${[["alle", "Alle"], ["lang", "Langfristig"], ["kurz", "Kurzfristig"], ["empfohlen", "⭐ Empfohlen"]].map(([k, l]) =>
      `<button data-lb="${k}" class="${lbTab === k ? "on" : ""}">${l}</button>`).join("")}</span>
      <span class="mute small">Seit ${LB.start ? dateDe(LB.start) : "–"} · jedes neue Kaufsignal wird mit echten Tageskerzen nachgespielt</span></div>
    ${zu < 20 ? `<div class="mfbox" style="margin:10px 0">Noch wenig Daten: ${zu} abgeschlossene Trades. Aussagekräftig wird die Bilanz ab etwa 20–30 – bis dahin sind die Zahlen ein erster Eindruck.</div>` : ""}
    <div class="lbtiles">
      ${tile("Signale", st.signale || 0, `${st.offen || 0} laufen noch`)}
      ${tile("Trefferquote", st.quote_pct != null ? st.quote_pct + " %" : "–", `${st.ziel || 0} Ziele · ${st.stopp || 0} Stopps`, st.quote_pct == null ? "" : st.quote_pct >= 50 ? "var(--green)" : "var(--red)")}
      ${tile("Ø Ergebnis je Trade", rTxt(st.r_schnitt), "abgeschlossene Trades", rCol(st.r_schnitt))}
      ${tile("Summe", rTxt(st.r_summe), `offen: ${rTxt(st.r_offen)}`, rCol(st.r_summe))}
      ${tile("Profitfaktor", st.profitfaktor != null ? String(st.profitfaktor).replace(".", ",") : "–", "Gewinne ÷ Verluste", st.profitfaktor == null ? "" : st.profitfaktor >= 1 ? "var(--green)" : "var(--red)")}
      ${tile("Über Nacht", st.uebernacht_schnitt_pct != null ? sgn2(st.uebernacht_schnitt_pct) + " %" : "–", st.uebernacht_pos_pct != null ? `${st.uebernacht_pos_pct} % positiv (${st.uebernacht_n})` : "abends kaufen → morgens", rCol(st.uebernacht_schnitt_pct))}
    </div>
    ${ts.length ? `<div class="tablewrap lbtab" style="min-height:0;max-height:420px;margin-top:12px"><table><thead><tr><th>Signal</th><th>Aktie</th><th>Horizont</th><th class="num">Einstieg</th><th class="num">Stopp</th><th class="num">Ziel</th><th class="num">Über Nacht</th><th class="num">Ergebnis</th><th>Status</th></tr></thead><tbody>
      ${ts.slice().sort((x, y) => x.datum < y.datum ? 1 : -1).map(t => `<tr class="row" data-sym="${t.symbol}"><td>${dateDe(t.datum)}${t.nachgetragen ? ' <span class="mute small" title="Aus der Signalhistorie nachgetragen, Zone/Ziel vom Starttag der Bilanz">*</span>' : ""}</td>
        <td><b>${t.name}</b>${t.empfohlen ? " ⭐" : ""}</td><td>${t.horizont === "lang" ? "langfristig" : "kurzfristig"}</td>
        <td class="num">${fmt(t.einstieg)}</td><td class="num">${fmt(t.stop)}</td><td class="num">${fmt(t.ziel)}</td>
        <td class="num">${t.uebernacht_pct != null ? pctTxt(t.uebernacht_pct) : '<span class="mute">–</span>'}</td>
        <td class="num"><b style="color:${rCol(t.r)}">${rTxt(t.r)}</b> <span class="small">${pctTxt(t.rendite_pct)}</span></td>
        <td>${ERG[t.ergebnis] || t.ergebnis}${t.ende ? ` <span class="mute small">${dateDe(t.ende)}</span>` : ""}</td></tr>`).join("")}
      </tbody></table></div>` : '<div class="empty" style="margin-top:12px">Noch keine Signale in dieser Auswahl.</div>'}
    <p class="mute small" style="margin:10px 0 0">1 R = Abstand vom Einstieg bis zum Stopp (Invalidierung). +2 R heißt: doppelt so viel gewonnen wie riskiert. Einstieg = Schlusskurs am Signaltag, Ziel = nächstes Kursziel über dem Kurs. Erreicht eine Tageskerze Ziel und Stopp, zählt vorsichtshalber der Stopp.${all.some(t => t.nachgetragen) ? " * = aus der Signalhistorie nachgetragen." : ""}</p>`;
  el.querySelectorAll("[data-lb]").forEach(b => b.onclick = () => { lbTab = b.dataset.lb; renderLive(); });
  el.querySelectorAll("tr[data-sym]").forEach(x => x.onclick = () => showDetail(x.dataset.sym));
}

// ---------- Termine: Zwei-Wochen-Übersicht ----------
const FLAG = {US: "🇺🇸", DE: "🇩🇪", EU: "🇪🇺", CN: "🇨🇳", Global: "🌐"};
const LAND_NAME = {US: "USA", DE: "Deutschland", EU: "Eurozone", CN: "China", Global: "Weltweit"};
const landOf = t => t.land || "US";
const isoOf = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
let tmTypen = new Set(["makro", "earn", "div"]), tmLaender = new Set(["US", "DE", "EU", "CN"]);
try {
  const g = JSON.parse(localStorage.getItem("tmFilter") || "null");
  if (g) { tmTypen = new Set(g.typen); tmLaender = new Set(g.laender); }
} catch(e) {}
function tmMerken(){ try { localStorage.setItem("tmFilter", JSON.stringify({typen: [...tmTypen], laender: [...tmLaender]})); } catch(e) {} }
function renderWoche(){
  const el = document.getElementById("wboard"); if (!el) return;
  // 10 Handelstage ab heute (am Wochenende ab Montag)
  const start = new Date(new Date().toDateString());
  while (start.getDay() === 0 || start.getDay() === 6) start.setDate(start.getDate() + 1);
  const tage = []; const d = new Date(start);
  while (tage.length < 10) { if (d.getDay() !== 0 && d.getDay() !== 6) tage.push(isoOf(d)); d.setDate(d.getDate() + 1); }
  const bis = tage[tage.length - 1];
  // Wochenend-Termine dem folgenden Montag zuordnen
  const ziel = iso => { const x = new Date(iso); const wd = x.getDay(); if (wd === 6) x.setDate(x.getDate() + 2); if (wd === 0) x.setDate(x.getDate() + 1); return isoOf(x); };
  const tagKurz = iso => WT[new Date(iso).getDay()];
  const box = {}; tage.forEach(t => box[t] = {makro: [], earn: [], div: []});
  const heute = isoOf(new Date());
  MAKRO.forEach(t => { if (t.datum < heute || t.datum > bis || !tmLaender.has(landOf(t)) && landOf(t) !== "Global") return;
    const z = ziel(t.datum); if (box[z]) box[z].makro.push({...t, wochenende: z !== t.datum ? tagKurz(t.datum) : ""}); });
  DATA.forEach(a => { const t = a.termine || {};
    if (t.earnings && box[t.earnings]) box[t.earnings].earn.push(a);
    if (t.ex_dividende && box[t.ex_dividende]) box[t.ex_dividende].div.push(a); });
  const kurzTitel = t => t.titel.replace(/^(Deutschland|China|Eurozone):\s*/, "");
  const spalte = (iso, i) => {
    const b = box[iso], heu = iso === heute;
    const mk = tmTypen.has("makro") ? b.makro.sort((x, y) => (y.wichtig ? 1 : 0) - (x.wichtig ? 1 : 0)).map(t =>
      `<div class="ev makro${t.wichtig ? " hoch" : ""}" title="${LAND_NAME[landOf(t)]} · ${t.kategorie}${t.info ? " · " + t.info : ""}">
        <span class="flag">${FLAG[landOf(t)]}</span><span class="evt">${kurzTitel(t)}${t.wochenende ? ` <span class="mute">(${t.wochenende})</span>` : ""}</span></div>`).join("") : "";
    const er = tmTypen.has("earn") && b.earn.length ? (() => { const xs = b.earn.slice().sort((x, y) => (y.check?.score || 0) - (x.check?.score || 0));
      return `<div class="ev earn"><span class="evh">${xs.length} ${xs.length === 1 ? "Quartalszahl" : "Quartalszahlen"}</span>
        <span class="evnames">${xs.slice(0, 4).map(a => `<button class="nm" data-sym="${a.symbol}"><span class="dot ${a.ampel}"></span>${a.name}</button>`).join("")}${xs.length > 4 ? `<span class="mute small">+${xs.length - 4} weitere</span>` : ""}</span></div>`; })() : "";
    const dv = tmTypen.has("div") && b.div.length ? `<div class="ev div"><span class="evh">Ex-Dividende</span><span class="evnames">${b.div.map(a => `<button class="nm" data-sym="${a.symbol}">${a.name}</button>`).join("")}</span></div>` : "";
    const inhalt = mk + er + dv;
    return `<div class="wday${heu ? " heute" : ""}${i === 5 ? " wk2" : ""}">
      <div class="wdh"><b>${tagKurz(iso)}</b> <span>${dateDe(iso).slice(0, 6)}</span>${heu ? '<em>heute</em>' : ""}</div>
      ${inhalt || '<div class="ev leer">–</div>'}</div>`;
  };
  document.getElementById("tmZeitraum").textContent = `${dateDe(tage[0]).slice(0, 6)} – ${dateDe(bis).slice(0, 6)} · zwei Wochen`;
  el.innerHTML = `<div class="wlabel">Diese Woche</div><div class="wlabel wk2">Nächste Woche</div>` + tage.map(spalte).join("");
  el.querySelectorAll("[data-sym]").forEach(x => x.onclick = () => showDetail(x.dataset.sym));
}
document.querySelectorAll("#tmTyp .tbtn").forEach(b => {
  const sync = () => { b.classList.toggle("on", tmTypen.has(b.dataset.typ)); b.setAttribute("aria-pressed", tmTypen.has(b.dataset.typ)); };
  sync(); b.onclick = () => { tmTypen.has(b.dataset.typ) ? tmTypen.delete(b.dataset.typ) : tmTypen.add(b.dataset.typ); sync(); tmMerken(); renderWoche(); };
});
document.querySelectorAll("#tmLand .lbtn").forEach(b => {
  const sync = () => { b.classList.toggle("on", tmLaender.has(b.dataset.land)); b.setAttribute("aria-pressed", tmLaender.has(b.dataset.land)); };
  sync(); b.onclick = () => { tmLaender.has(b.dataset.land) ? tmLaender.delete(b.dataset.land) : tmLaender.add(b.dataset.land); sync(); tmMerken(); renderWoche(); };
});
document.getElementById("tmAlle").onclick = e => {
  const l = document.getElementById("tmList"), auf = l.hidden;
  l.hidden = !auf; e.currentTarget.setAttribute("aria-expanded", auf); e.currentTarget.textContent = auf ? "Alle Termine ▴" : "Alle Termine ▾";
  if (auf) renderCal();
};

// ---------- Bedienung ----------
document.querySelectorAll("[data-f]").forEach(b => b.onclick = () => {
  document.querySelectorAll("[data-f]").forEach(x => x.classList.remove("active"));
  b.classList.add("active"); filter = b.dataset.f; render();
});
document.querySelectorAll("[data-t]").forEach(b => b.onclick = () => {
  document.querySelectorAll("[data-t]").forEach(x => x.classList.remove("active"));
  b.classList.add("active"); calTab = b.dataset.t; renderCal();
});
document.querySelectorAll("[data-sec]").forEach(b => b.onclick = () => {
  document.querySelectorAll("[data-sec]").forEach(x => x.classList.remove("on"));
  b.classList.add("on"); secTab = b.dataset.sec; renderSectors();
});
document.querySelectorAll("th[data-s]").forEach(th => th.onclick = () => {
  const k = th.dataset.s; sortDir = (sortKey === k) ? -sortDir : (["w1", "score", "crv", "ev"].includes(k) ? -1 : 1); sortKey = k; render();
});
document.querySelectorAll("[data-ptab]").forEach(b => b.onclick = () => {
  document.querySelectorAll("[data-ptab]").forEach(x => x.classList.toggle("on", x === b));
  ["sek", "mkt", "news", "ch", "lb", "mf"].forEach(k => document.getElementById("pane-" + k).hidden = b.dataset.ptab !== k);
  document.getElementById("secSeg").style.visibility = b.dataset.ptab === "sek" ? "visible" : "hidden";
});
document.getElementById("q").oninput = render;
document.getElementById("fLand").onchange = render;
document.getElementById("fSektor").onchange = render;
document.getElementById("ov").onclick = e => { if (e.target.id === "ov") closeDetail(); };
document.addEventListener("keydown", e => { if (e.key === "Escape") closeDetail(); });
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { if (document.documentElement.dataset.pref === "auto") applyTheme("auto"); });
load().catch(e => { document.getElementById("stand").textContent = "Fehler beim Laden der Daten: " + e; });
