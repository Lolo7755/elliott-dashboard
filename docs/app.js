"use strict";
const AMPEL_ORDER = {gruen: 0, orange: 1, rot: 2};
let DATA = [], MAKRO = [], MARKT = null, AUS = [], TOPMV = [];
let filter = "alle", sortKey = "ampel", sortDir = 1, chart = null, calTab = "earn", secTab = "woche";
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
  document.getElementById("todoDate").textContent = stand ? dateWd(stand) : "";
  if (!list.length) { el.innerHTML = '<div class="empty">Heute keine neuen Aufgaben.<br><span class="small">Bestehende Positionen einfach halten.</span></div>'; return; }
  const mfOf = a => a.markt_filter || {};
  const grp = (typ, title, filt) => { const xs = list.filter(a => AKTION[a.status][0] === typ && filt(a))
      .sort((x, y) => (y.check ? y.check.score : 0) - (x.check ? x.check.score : 0)); if (!xs.length) return "";
    return `<div class="grp">${title} · ${xs.length}</div>` + xs.map(a => { let [t, lbl, txt] = AKTION[a.status];
      let sub = txt(a);
      if (mfOf(a).blockiert) { t = "warten"; lbl = "Pausiert"; sub = mfOf(a).hinweise[0]; }
      else if (mfOf(a).reduziert) sub = "Nur Teilkauf 1 (ca. 1/3) – Markt angeschlagen";
      return `<div class="task" data-sym="${a.symbol}"><span class="pill ${t}">${lbl}</span><div><b>${a.name}</b> ${scoreBadge(a.check)}<br><span class="small mute">${sub}</span>${earnWarn(a)}</div></div>`; }).join(""); };
  el.innerHTML = grp("kauf", "Kaufen (sortiert nach Score)", a => !mfOf(a).blockiert)
    + grp("kauf", "Kaufzone erreicht – pausiert durch Marktfilter", a => mfOf(a).blockiert)
    + grp("verkauf", "Verkaufen / Gewinne sichern", () => true);
  el.querySelectorAll(".task").forEach(t => t.onclick = () => showDetail(t.dataset.sym));
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
  if (!m || !m.stimmung) { el.innerHTML = '<div class="k">Marktstimmung</div><div class="sub">Wird beim nächsten Lauf berechnet.</div>'; return; }
  const s = m.stimmung, col = s.wert < 45 ? "neg" : s.wert <= 55 ? "" : "pos";
  const hist = [["Vortag", s.vortag], ["Vorwoche", s.woche], ["Vormonat", s.monat]].filter(x => x[1] != null)
    .map(([n, v]) => `${n} <b>${v}</b>`).join(" · ");
  const chips = (s.teile_cnn || []).map(t => `<span class="fgc" style="background:${moodCol(t.wert)}" title="${t.name}: ${t.wert} (${t.label})">${t.name} ${t.wert}</span>`).join("");
  el.innerHTML = `<div class="k">Marktstimmung · Angst & Gier <span title="${s.erklaerung}" style="cursor:help">ⓘ</span></div><div class="mood">${gauge(s.wert)}
    <div style="min-width:0"><div><span class="lbl ${col}">${s.wert} · ${s.label}</span></div>
    <div class="exp">${hist}${hist ? " · " : ""}<span class="mute">${s.quelle || ""}</span></div>
    ${chips ? `<div class="fgchips">${chips}</div>` : `<div class="exp">${(s.teile || []).join(" · ")}</div>`}</div></div>`;
  el.title = s.erklaerung;
}
function moodCol(v){ return v < 25 ? "#b91c1c" : v < 45 ? "#ea580c" : v <= 55 ? "#a16207" : v <= 75 ? "#4d7c0f" : "#15803d"; }
function renderTicker(m){
  if (!m || !m.indizes) return;
  document.getElementById("ticker").innerHTML = m.indizes.map(i =>
    `<span class="tk"><b>${i.name}</b>${i.kurs.toLocaleString("de-DE", {maximumFractionDigits: i.kurs < 10 ? 4 : 0})} ${pctTxt(i.tag_pct)}</span>`).join("");
}

// ---------- Marktfilter ----------
const LAGE_COL = {gesund: "#16a34a", schwach: "#ea580c", abverkauf: "#dc2626"};
function renderFilter(mf){
  const el = document.getElementById("mf");
  if (!mf || !mf.nach_markt) { el.innerHTML = '<h2>🧭 Marktfilter</h2><div class="empty">Wird beim nächsten Analyse-Lauf berechnet.</div>'; return; }
  const L = mf.lage, bef = mf.befund || {};
  const befTxt = k => ({nachteil: '<span class="chip r">Filter aktiv</span>', kein_nachteil: '<span class="chip g">kein Nachteil – nur Hinweis</span>',
    zu_wenig: '<span class="chip o">zu wenige Daten – nur Hinweis</span>'})[bef[k]] || "";
  const row = (name, x, col, extra) => { const q = x.quote_pct;
    return `<div class="mfrow"><span>${name}</span><span class="meter" style="margin:0"><i style="width:${q || 0}%;background:${col}"></i></span>
      <b>${q != null ? q + " %" : "–"}</b><span class="mute small">${x.n} Signale${x.rendite_schnitt_pct != null ? " · Ø " + (x.rendite_schnitt_pct >= 0 ? "+" : "") + String(x.rendite_schnitt_pct).replace(".", ",") + " %" : ""}</span>${extra || ""}</div>`; };
  const m = mf.nach_markt, r = mf.nach_rs;
  const nPaus = DATA.filter(a => a.markt_filter && a.markt_filter.blockiert).length, nRed = DATA.filter(a => a.markt_filter && a.markt_filter.reduziert).length;
  el.innerHTML = `<h2>🧭 Marktfilter <span class="mute small">Gesamtmarkt & relative Stärke im Elliott-Signal</span></h2>
    <div class="mfgrid">
      <div>${L ? `<div class="k">Marktlage heute</div><div class="mflage" style="color:${LAGE_COL[L.regime]}">● ${L.label}</div>
        <div class="small">S&P 500 ${num1(L.spx_vs_200_pct)} ggü. 200-Tage-Linie · ${num1(L.spx_5t_pct)} in 5 Tagen<br>VIX ${String(L.vix).replace(".", ",")} (${L.vix_vs_50_pct >= 0 ? "+" : ""}${L.vix_vs_50_pct} % ggü. 50-Tage-Schnitt)</div>
        <div class="small" style="margin-top:6px">${nPaus ? `<b>${nPaus}</b> Kaufsignale pausiert` : "Keine Kaufsignale pausiert"}${nRed ? ` · <b>${nRed}</b> auf 1/3 reduziert` : ""}</div>` : '<span class="mute">Marktdaten fehlen</span>'}</div>
      <div><div class="k">Trefferquote der Kaufsignale je Marktlage (Backtest)</div>
        ${row("Gesund", m.gesund, LAGE_COL.gesund)}${row("Angeschlagen", m.schwach, LAGE_COL.schwach, befTxt("schwach"))}${row("Abverkauf", m.abverkauf, LAGE_COL.abverkauf, befTxt("abverkauf"))}</div>
      <div><div class="k">Aktie vs. Index (20 Tage, Backtest)</div>
        ${row("Mit dem Markt", r.markt, "#16a34a")}${row("Eigene Schwäche", r.eigen, "#dc2626", befTxt("eigen"))}
        <div class="mute small" style="margin-top:6px">Der Filter greift nur, wenn eine Lage mind. ${mf.regeln.min_abstand_pp} Prozentpunkte schlechter abschneidet (ab ${mf.regeln.min_signale} Signalen).</div></div>
    </div>`;
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
      items.push([t.datum, `<b>${t.titel}</b><span class="kat">${t.kategorie}</span>${t.info ? `<div class="mute small" style="margin-left:74px">${t.info}</div>` : ""}`]); });
    document.getElementById("calInfo").textContent = "Notenbanken, Konjunkturdaten, Politik und Börsentermine (Quellen: Fed, EZB, BLS).";
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
    ${q != null ? `<div class="rk"><span>Trefferquote dieser Aktie (Backtest)</span><b style="color:${q >= r.noetig ? "#16a34a" : "#dc2626"}">${q} % ${q >= r.noetig ? "✓" : "✗"}</b></div>` : ""}
    ${volHtml}
    <div class="mute small" style="margin-top:6px">CRV = Chance ÷ Risiko. Stopp = Invalidierung der Wellenzählung, Ziel = nächstes Kursziel über dem Kurs.</div>`;
}

// ---------- Laden ----------
async function load(){
  const [d, mk] = await Promise.all([
    fetch("data.json?ts=" + Date.now()).then(r => r.json()),
    fetch("makro.json?ts=" + Date.now()).then(r => r.ok ? r.json() : {termine: []}).catch(() => ({termine: []}))]);
  MAKRO = mk.termine || []; MARKT = d.markt; AUS = d.ausreisser || []; TOPMV = d.top_bewegungen || [];
  DATA = d.aktien.map(a => ({...a, dist: pct(a.kurs, a.zone.oben),
    anScore: (a.analysten && a.analysten.score) || 9,
    quote: (a.backtest && a.backtest.quote_pct != null) ? a.backtest.quote_pct : -1,
    earn: (a.termine && a.termine.earnings) || "9999",
    earnings_heute: !!(a.termine && a.termine.earnings_in_tagen != null && a.termine.earnings_in_tagen <= 1),
    w1: a.perf && a.perf.woche != null ? a.perf.woche : -999,
    score: a.check ? a.check.score : -1,
    kstat: a.kurz ? AMPEL_ORDER[a.kurz.ampel] : 9,
    crv: (() => { const r = crvCalc(a, a.kurs); return r && r.ok ? r.crv : -1; })()}));
  const fill = (id, key) => { const el = document.getElementById(id);
    [...new Set(DATA.map(a => a.meta && a.meta[key]).filter(Boolean))].sort().forEach(v => el.add(new Option(v, v))); };
  fill("fLand", "land"); fill("fSektor", "sektor");
  renderMood(MARKT); renderTicker(MARKT); renderSectors(); renderCal(); renderFilter(d.marktfilter);
  const stand = DATA.map(a => a.stand).sort().pop();
  renderTodo(stand); renderOutliers();
  const tq = d.trefferquote;
  if (tq && tq.quote_pct != null) {
    document.getElementById("cQ").textContent = tq.quote_pct + " %";
    const vk = tq.verkauf && tq.verkauf.quote_pct != null ? ` · Verkauf ${tq.verkauf.quote_pct} %` : "";
    document.getElementById("cQs").textContent = `Kauf ${tq.treffer}/${tq.treffer + tq.fehler}${vk}`;
    document.getElementById("cQs").title = "Kauf = Zonen-Signale, Verkauf = „Impuls vollendet“ (Backtest über alle Aktien)";
  }
  const kursStand = Object.entries(DATA.reduce((m, a) => (m[a.stand] = (m[a.stand] || 0) + 1, m), {})).sort((x, y) => y[1] - x[1])[0];
  document.getElementById("stand").innerHTML = "Analyse " + new Date(d.erstellt).toLocaleString("de-DE", {dateStyle: "medium", timeStyle: "short"})
    + (kursStand ? ` · Kurse vom ${dateDe(kursStand[0])}` : "");
  document.getElementById("cAll").textContent = DATA.length;
  const nL = new Set(DATA.map(a => a.meta && a.meta.land).filter(Boolean)).size;
  document.getElementById("cAllS").textContent = nL ? `aus ${nL} Ländern` : "";
  ["gruen", "orange", "rot"].forEach((k, i) => document.getElementById(["cG", "cO", "cR"][i]).textContent = DATA.filter(a => a.ampel === k).length);
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
      <td><b>${a.name}</b> <span class="mute">${a.symbol}</span>${a.meta ? `<div class="mute small">${[a.meta.land, a.meta.sektor].filter(Boolean).join(" · ")}</div>` : ""}</td>
      <td class="num">${fmt(a.kurs, a.currency)}</td>
      <td class="num">${wTxt(a.perf && a.perf.woche)}</td>
      <td class="num">${scoreBadge(a.check)}</td>
      <td class="num hide-m">${crvBadge(a)}</td>
      <td>${a.status}${a.status_vorher && a.status_vorher !== a.status ? '<span class="tag new">neu</span>' : ""}</td>
      <td>${a.kurz ? `<span class="kz"><span class="dot ${a.kurz.ampel}"></span>${a.kurz.status}</span>` : '<span class="mute">–</span>'}</td>
      <td class="sig hide-m">${a.signal}${a.markt_filter && (a.markt_filter.blockiert || a.markt_filter.reduziert) ? ' <span class="tag warn" title="' + a.markt_filter.hinweise.join(" · ") + '">Marktfilter</span>' : ""}</td>
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
  const tab = (h, lbl, x) => `<button data-h="${h}" class="${horizon === h ? "on" : ""}" ${x ? "" : "disabled"}>${lbl}${x ? ` · <span class="dot ${x.ampel}"></span> ${x.status}` : ""}</button>`;
  const w = v.welle || {};
  el.innerHTML = `
    <button class="btn close" id="closeBtn">✕ Schließen</button>
    <div class="dhead">
      <div><h2><span class="dot ${a.ampel}"></span> ${a.name} <span class="mute">${a.symbol}</span></h2>
        <div class="mute">Kurs ${fmt(k, c)} ${a.perf ? pctTxt(a.perf.tag) + " heute" : ""} · Stand ${a.stand}${a.meta ? " · " + [a.meta.land, a.meta.sektor].filter(Boolean).join(" · ") : ""}</div></div>
      <div class="htabs">${tab("lang", "📅 Langfristig (Monate–Jahre)", a)}${tab("kurz", "⚡ Kurzfristig (Wochen–Monate)", hasKurz ? a.kurz : null)}</div>
      ${a.check ? `<span class="kbadge">Entscheidungscheck ${scoreBadge(a.check)} ${a.check.label}</span>` : ""}
    </div>
    <div class="grid2">
      <div>
        <div class="chartbox"><div id="chart"></div>
        <div class="legend">
          <span><i style="background:#a855f7"></i>Elliott-Wellen (Zählung)</span>
          <span><i style="background:var(--zone)"></i>Einstiegszone</span>
          <span><i style="background:#93c5fd"></i>Nachkauf 61,8 %</span>
          <span><i style="background:var(--red)"></i>Invalidierung</span>
          <span><i style="background:var(--green)"></i>Ziele</span>
          ${v.szenarien ? `<span><i style="height:0;border-top:3px dashed #22c55e"></i>Hauptszenario ${v.szenarien.haupt.prob_pct != null ? "<b>" + v.szenarien.haupt.prob_pct + " %</b>" : ""}</span><span><i style="height:0;border-top:3px dashed #f97316"></i>Alternative ${v.szenarien.alternative.prob_pct != null ? "<b>" + v.szenarien.alternative.prob_pct + " %</b>" : ""}</span>` : ""}
        </div>
        <div class="mute small" style="margin-top:4px">${horizon === "kurz" ? "Tageskerzen der letzten Monate – kurzfristige Wellen (Wochen bis Monate)." : "Wochenkerzen über mehrere Jahre – übergeordnete Wellen (Monate bis Jahre)."}</div></div>
        <div class="box" style="margin-top:14px"><h3>🌊 Wellenstruktur ${horizon === "kurz" ? "kurzfristig" : "langfristig"}</h3>
          ${w.start ? `Start ${fmt(w.start.price)} (${dateDe(w.start.date)}) → Hoch ${fmt(w.hoch.price)} (${dateDe(w.hoch.date)})<br>
          Korrektur aktuell ${(w.retracement_aktuell_pct || 0).toLocaleString("de-DE")} % · max. ${(w.retracement_max_pct || 0).toLocaleString("de-DE")} %<br>
          Zählqualität: ${w.zaehlung_qualitaet ? w.zaehlung_qualitaet + " / 100" : "keine saubere 5-Wellen-Zählung"}<br>` : ""}
          <span class="mute">50-Tage ${fmt(a.sma50)} · 200-Tage ${fmt(a.sma200)} · Trend ${a.trend_tageschart}</span>
        </div>
      </div>
      <div>
        <div class="box"><h3>Signal ${horizon === "kurz" ? "kurzfristig" : "langfristig"}</h3><div class="sigbig"><span class="dot ${v.ampel}"></span> ${v.status}</div><div style="margin-top:4px">${v.signal}</div>${earnWarn(a)}
          ${horizon === "lang" && a.markt_filter && a.markt_filter.hinweise && a.markt_filter.hinweise.length ? `<div class="mfbox">${a.markt_filter.hinweise.map(h => `<div>🧭 ${h}</div>`).join("")}${a.markt_filter.signal_original ? `<div class="mute small">Ohne Marktfilter: ${a.markt_filter.signal_original}</div>` : ""}</div>` : ""}
          ${hasKurz ? `<div class="mute small" style="margin-top:8px">${horizon === "kurz" ? `Langfristig: <span class="dot ${a.ampel}"></span> ${a.status}` : `Kurzfristig: <span class="dot ${a.kurz.ampel}"></span> ${a.kurz.status}`}</div>` : ""}</div>
        <div class="box"><h3>⚖️ Chance / Risiko ${horizon === "kurz" ? "kurzfristig" : "langfristig"}</h3>${riskBox(a, v)}</div>
        <div class="box"><h3>✅ Entscheidungscheck</h3>${checkBox(a)}</div>
        <div class="box"><h3>🔮 Szenarien</h3>${scBox(v)}</div>
        <div class="box"><h3>Handlungsplan</h3>
          <table class="plan" style="width:100%">
            ${v.plan ? planRow("Teilkauf 1 (38,2 %)", v.plan.teilkauf_1, "#3b82f6") + planRow("Teilkauf 2 (50 %)", v.plan.teilkauf_2, "#3b82f6")
              + planRow("Teilkauf 3 (61,8 %)", v.plan.teilkauf_3, "#93c5fd") + planRow("Invalidierung (78,6 %)", v.plan.invalidierung, "#ef4444")
              + planRow("Teilverkauf 1 (altes Hoch)", v.plan.teilverkauf_1, "#22c55e") + planRow("Teilverkauf 2 (127,2 %)", v.plan.teilverkauf_2, "#22c55e")
              + planRow("Teilverkauf 3 (161,8 %)", v.plan.teilverkauf_3, "#22c55e") : ""}
          </table>
        </div>
      </div>
      <div class="col3">
        <div class="box"><h3>📈 Performance</h3>${perfBox(a)}</div>
        <div class="box"><h3>🧾 Letzte 4 Quartale</h3>${quartBox(a)}</div>
        <div class="box"><h3>📊 Analysten</h3>${anBox(a)}</div>
        <div class="box"><h3>🎯 Trefferquote dieser Aktie</h3>${btBox(a)}</div>
        <div class="box"><h3>📅 Termine</h3>${termBox(a)}</div>
        <div class="box"><h3>📰 News</h3>${newsBox(a)}</div>
      </div>
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
    autoSize: true,
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
  const k = th.dataset.s; sortDir = (sortKey === k) ? -sortDir : (["w1", "score", "crv"].includes(k) ? -1 : 1); sortKey = k; render();
});
document.getElementById("q").oninput = render;
document.getElementById("fLand").onchange = render;
document.getElementById("fSektor").onchange = render;
document.getElementById("ov").onclick = e => { if (e.target.id === "ov") closeDetail(); };
document.addEventListener("keydown", e => { if (e.key === "Escape") closeDetail(); });
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { if (document.documentElement.dataset.pref === "auto") applyTheme("auto"); });
load().catch(e => { document.getElementById("stand").textContent = "Fehler beim Laden der Daten: " + e; });
