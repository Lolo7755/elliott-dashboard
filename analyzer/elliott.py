"""
Elliott-Wellen-Analyse-Kern (regelbasiert, im Stil von HKCM-Langfrist-Zonen).

Ablauf pro Aktie:
1. Wochenkerzen -> ZigZag-Wendepunkte auf zwei Ebenen (gross / mittel)
2. Laufende Haupt-Aufwärtswelle bestimmen: letztes "Bärenmarkt-Tief" (S) -> Hoch (H)
3. 5-Wellen-Zählung innerhalb S->H nach den harten Elliott-Regeln suchen
4. Fibonacci-Zonen der Korrektur (38,2 % / 50 % / 61,8 % / 78,6 %)
5. Status (zulaufend / in Zone / Nachkauf / invalidiert / Welle 5 läuft / Ziel erreicht)
6. Handlungsplan: Teilkäufe und Teilverkäufe mit konkreten Kursen

Die Zählung ist bewusst mechanisch. Sie liefert Kandidaten und Zonen;
die Gewichtung der Szenarien ist Aufgabe der KI-Kommentarschicht.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, asdict

import numpy as np
import pandas as pd

FIB_ZONE_TOP = 0.382
FIB_ZONE_BOTTOM = 0.5
FIB_NACHKAUF = 0.618
FIB_INVALID = 0.786


# --------------------------------------------------------------------------- #
# Hilfsfunktionen
# --------------------------------------------------------------------------- #
def to_weekly(daily: pd.DataFrame) -> pd.DataFrame:
    """Tageskerzen (Open/High/Low/Close) -> Wochenkerzen (Freitag)."""
    w = daily.resample("W-FRI").agg(
        {"Open": "first", "High": "max", "Low": "min", "Close": "last"}
    )
    return w.dropna()


def annual_vol(daily: pd.DataFrame, years: int = 3) -> float:
    c = daily["Close"].iloc[-252 * years:]
    r = np.log(c).diff().dropna()
    if len(r) < 20:
        return 0.35
    return float(r.std() * math.sqrt(252))


@dataclass
class Pivot:
    i: int          # Index in der Wochenreihe
    date: str
    price: float
    kind: str       # "H" oder "L"


def zigzag(w: pd.DataFrame, pct: float) -> list[Pivot]:
    """Klassischer ZigZag auf High/Low: neuer Pivot, wenn Gegenbewegung >= pct."""
    highs, lows = w["High"].values, w["Low"].values
    dates = [d.strftime("%Y-%m-%d") for d in w.index]
    piv: list[Pivot] = []
    trend = 0  # 1 = sucht Hoch, -1 = sucht Tief
    ext_i, ext_p = 0, highs[0]
    lo_i, lo_p = 0, lows[0]
    hi_i, hi_p = 0, highs[0]
    for i in range(1, len(w)):
        if trend == 0:
            if highs[i] > hi_p:
                hi_i, hi_p = i, highs[i]
            if lows[i] < lo_p:
                lo_i, lo_p = i, lows[i]
            if hi_p >= lo_p * (1 + pct) and hi_i > lo_i:
                piv.append(Pivot(lo_i, dates[lo_i], float(lo_p), "L"))
                trend, ext_i, ext_p = 1, hi_i, hi_p
            elif lo_p <= hi_p * (1 - pct) and lo_i > hi_i:
                piv.append(Pivot(hi_i, dates[hi_i], float(hi_p), "H"))
                trend, ext_i, ext_p = -1, lo_i, lo_p
            continue
        if trend == 1:
            if highs[i] >= ext_p:
                ext_i, ext_p = i, highs[i]
            elif lows[i] <= ext_p * (1 - pct):
                piv.append(Pivot(ext_i, dates[ext_i], float(ext_p), "H"))
                trend, ext_i, ext_p = -1, i, lows[i]
        else:
            if lows[i] <= ext_p:
                ext_i, ext_p = i, lows[i]
            elif highs[i] >= ext_p * (1 + pct):
                piv.append(Pivot(ext_i, dates[ext_i], float(ext_p), "L"))
                trend, ext_i, ext_p = 1, i, highs[i]
    # letzter (noch offener) Extrempunkt
    if trend != 0:
        piv.append(Pivot(ext_i, dates[ext_i], float(ext_p), "H" if trend == 1 else "L"))
    return piv


# --------------------------------------------------------------------------- #
# 5-Wellen-Zählung
# --------------------------------------------------------------------------- #
def _closeness(x: float, target: float, tol: float) -> float:
    return math.exp(-((x - target) / tol) ** 2)


def fit_impulse(pivots: list[Pivot], start: Pivot, end: Pivot):
    """
    Sucht in den Pivots zwischen start (Tief) und end (Hoch) die beste
    1-2-3-4-5-Zählung, die die harten Regeln erfüllt:
      - Welle 2 unterschreitet den Start nicht
      - Welle 3 ist nicht die kürzeste
      - Welle 4 überlappt nicht mit Welle 1
      - Welle 3 und 5 markieren jeweils neue Hochs
    Liefert (score 0..1, [p0..p5]) oder (0, None).
    """
    inner = [p for p in pivots if start.i < p.i < end.i]
    Hs = [p for p in inner if p.kind == "H"]
    Ls = [p for p in inner if p.kind == "L"]
    best, best_seq = 0.0, None
    S, E = start.price, end.price
    for h1 in Hs:
        w1 = h1.price - S
        if w1 <= 0:
            continue
        for l2 in Ls:
            if l2.i <= h1.i or l2.price <= S:
                continue
            for h3 in Hs:
                if h3.i <= l2.i or h3.price <= h1.price:
                    continue
                w3 = h3.price - l2.price
                for l4 in Ls:
                    if l4.i <= h3.i or l4.price <= h1.price or E <= h3.price:
                        continue
                    w5 = E - l4.price
                    if w3 < w1 and w3 < w5:
                        continue
                    r2 = (h1.price - l2.price) / w1
                    r4 = (h3.price - l4.price) / w3
                    score = (
                        0.25 * _closeness(r2, 0.55, 0.25)
                        + 0.30 * _closeness(w3 / w1, 1.618, 0.8)
                        + 0.25 * _closeness(r4, 0.382, 0.2)
                        + 0.20 * (1.0 if r2 > r4 * 0.8 else 0.5)  # Alternation
                    )
                    if score > best:
                        best, best_seq = score, [start, h1, l2, h3, l4, end]
    return best, best_seq


def _decline_into(pivots: list[Pivot], k: int) -> float:
    """Prozentualer Rückgang vom vorherigen Hoch-Pivot in das Tief pivots[k]."""
    prev_h = [p for p in pivots[:k] if p.kind == "H"]
    if not prev_h:
        return float("inf")
    return 1 - pivots[k].price / prev_h[-1].price


def _max_internal_decline(pivots: list[Pivot], start_i: int, end_i: int) -> float:
    seg = [p for p in pivots if start_i <= p.i <= end_i]
    m = 0.0
    for a, b in zip(seg, seg[1:]):
        if a.kind == "H" and b.kind == "L":
            m = max(m, 1 - b.price / a.price)
    return m


def select_start(pivots: list[Pivot], H: Pivot, w: pd.DataFrame):
    """
    Wählt den Startpunkt S der Aufwärtswelle, die im Hoch H endet.
    Bedingungen (vom jüngsten Tief rückwärts geprüft):
      a) S ist das tiefste Tief zwischen S und H
      b) Grad-Konsistenz: der Rückgang IN das Tief S ist mindestens so gross wie
         jede Korrektur innerhalb S->H (sonst ist S nur ein Zwischentief)
      c) innerhalb S->H existiert eine gültige 5-Wellen-Zählung
    Fallback 1: jüngstes Tief mit a)+b) ohne Zählung. Fallback 2: tiefstes Tief.
    """
    lowsH = w["Low"].values
    fallback = None
    for k in range(len(pivots) - 1, -1, -1):
        p = pivots[k]
        if p.kind != "L" or p.i >= H.i:
            continue
        if lowsH[p.i:H.i + 1].min() < p.price - 1e-9:
            continue
        if _decline_into(pivots, k) + 1e-9 < _max_internal_decline(pivots, p.i, H.i):
            continue
        score, seq = fit_impulse(pivots, p, H)
        if seq:
            return p, score, seq
        if fallback is None:
            fallback = p
    if fallback is not None:
        return fallback, 0.0, None
    lo_idx = int(np.argmin(lowsH[: max(H.i, 1)]))
    S = Pivot(lo_idx, w.index[lo_idx].strftime("%Y-%m-%d"), float(lowsH[lo_idx]), "L")
    return S, 0.0, None


# --------------------------------------------------------------------------- #
# Hauptanalyse
# --------------------------------------------------------------------------- #
def analyze(daily: pd.DataFrame, symbol: str, name: str = "", currency: str = "") -> dict:
    daily = daily.dropna(subset=["High", "Low", "Close"]).copy()
    w = to_weekly(daily.iloc[-252 * 10:])  # max. 10 Jahre Wochenchart
    vol = annual_vol(daily)
    mid = float(np.clip(0.45 * vol, 0.10, 0.30))  # Schwelle für Unterwellen

    last = float(daily["Close"].iloc[-1])
    last_date = daily.index[-1].strftime("%Y-%m-%d")
    piv_mid = zigzag(w, mid)

    # Hoch H = höchstes Hoch der letzten 10 Jahre
    hi_idx = int(np.argmax(w["High"].values))
    H = Pivot(hi_idx, w.index[hi_idx].strftime("%Y-%m-%d"), float(w["High"].iloc[hi_idx]), "H")

    S, score, seq = select_start(piv_mid, H, w)

    rng = H.price - S.price
    lvl = lambda f: H.price - f * rng  # noqa: E731
    zone_top, zone_bot = lvl(FIB_ZONE_TOP), lvl(FIB_ZONE_BOTTOM)
    nachkauf, invalid = lvl(FIB_NACHKAUF), lvl(FIB_INVALID)

    # Korrektur seit dem Hoch
    after = w.iloc[H.i + 1:]
    if len(after):
        c_idx = int(np.argmin(after["Low"].values)) + H.i + 1
        corr_low = float(w["Low"].iloc[c_idx])
        corr_low_date = w.index[c_idx].strftime("%Y-%m-%d")
    else:
        c_idx, corr_low, corr_low_date = H.i, H.price, H.date
    retr_now = (H.price - last) / rng if rng > 0 else 0.0
    retr_max = (H.price - corr_low) / rng if rng > 0 else 0.0
    rebound = last / corr_low - 1 if corr_low > 0 else 0.0

    labels = []
    if seq:
        for lab, p in zip(["0", "1", "2", "3", "4", "5"], seq):
            labels.append({"label": lab, "date": p.date, "price": round(p.price, 2)})
    else:
        labels = [
            {"label": "Start", "date": S.date, "price": round(S.price, 2)},
            {"label": "Hoch", "date": H.date, "price": round(H.price, 2)},
        ]
    if c_idx > H.i:
        labels.append({"label": "Korr.-Tief", "date": corr_low_date, "price": round(corr_low, 2)})

    # Kursziele der nächsten Aufwärtswelle (gemessen ab Korrekturtief)
    base = min(corr_low, last)
    leg = H.price - base
    t1 = H.price
    t2 = base + 1.272 * leg
    t3 = base + 1.618 * leg

    # ------------------------------------------------------------------ #
    # Status & Signal
    # ------------------------------------------------------------------ #
    near_high = last >= H.price * 0.97
    corr_done_alt = retr_max < FIB_ZONE_TOP and rebound >= mid  # Alternativ: Korrektur ohne Zone vorbei
    bounced_from_zone = FIB_ZONE_TOP <= retr_max <= FIB_INVALID and rebound >= mid

    if retr_max > FIB_INVALID and last < invalid:
        status, ampel = "Invalidiert", "rot"
        signal = "Nicht kaufen – Szenario gekippt, Positionen reduzieren"
    elif last >= t2:
        status, ampel = "Ziel 2 erreicht", "rot"
        signal = "Teilverkauf 2 (weiteres Drittel), Rest mit Ziel 3"
    elif near_high and c_idx > H.i and bounced_from_zone:
        status, ampel = "Ziel 1 erreicht", "orange"
        signal = "Teilverkauf 1 (ca. 1/3) am alten Hoch"
    elif bounced_from_zone:
        status, ampel = "Welle 5 läuft", "gruen"
        signal = "Halten – Aufwärtswelle aus der Zone gestartet"
    elif zone_bot < last <= zone_top:
        status, ampel = "In Zone", "gruen"
        signal = "Teilkauf 1 (ca. 1/3) – Langfrist-Einstiegsbereich erreicht"
    elif nachkauf < last <= zone_bot:
        status, ampel = "In Zone (unten)", "gruen"
        signal = "Teilkauf 2 / Nachkauf (ca. 1/3)"
    elif invalid < last <= nachkauf:
        status, ampel = "Nachkaufbereich", "orange"
        signal = "Letzter Nachkauf (Rest) – Invalidierung nah"
    elif corr_done_alt:
        status, ampel = "Alternativ: Korrektur beendet", "orange"
        signal = "Kleine Position möglich – Hauptszenario erwartet aber noch die Zone"
    elif near_high and c_idx <= H.i:
        status, ampel = "Neues Hoch / Trend läuft", "orange"
        signal = "Kein Einstieg im Hoch – auf Korrektur warten; Bestand halten"
    else:
        need = (zone_top / last - 1) * 100
        status, ampel = "Zulaufend", "orange"
        signal = f"Abwarten – Kauflimit bei {zone_top:.2f} ({need:+.1f} % vom aktuellen Kurs)".replace(".", ",")

    # Tageschart-Kontext (50/200-Tage-Linie)
    sma50 = float(daily["Close"].rolling(50).mean().iloc[-1]) if len(daily) >= 50 else None
    sma200 = float(daily["Close"].rolling(200).mean().iloc[-1]) if len(daily) >= 200 else None
    if sma50 and sma200:
        trend = "Aufwärts" if last > sma50 > sma200 else "Abwärts" if last < sma50 < sma200 else "Seitwärts"
    else:
        trend = "unbekannt"

    def r(x):
        return None if x is None else round(float(x), 2)

    plan = {
        "teilkauf_1": r(zone_top),
        "teilkauf_2": r(zone_bot),
        "teilkauf_3": r(nachkauf),
        "invalidierung": r(invalid),
        "teilverkauf_1": r(t1),
        "teilverkauf_2": r(t2),
        "teilverkauf_3": r(t3),
    }

    # Chartdaten: Wochenkerzen ab ca. 1 Jahr vor S
    start_chart = max(0, S.i - 52)
    wc = w.iloc[start_chart:]
    candles = [
        {"time": d.strftime("%Y-%m-%d"), "open": r(o), "high": r(h), "low": r(l), "close": r(c)}
        for d, o, h, l, c in zip(wc.index, wc["Open"], wc["High"], wc["Low"], wc["Close"])
    ]

    return {
        "symbol": symbol,
        "name": name or symbol,
        "currency": currency,
        "stand": last_date,
        "kurs": r(last),
        "status": status,
        "ampel": ampel,
        "signal": signal,
        "trend_tageschart": trend,
        "sma50": r(sma50),
        "sma200": r(sma200),
        "welle": {
            "start": {"date": S.date, "price": r(S.price)},
            "hoch": {"date": H.date, "price": r(H.price)},
            "korrektur_tief": {"date": corr_low_date, "price": r(corr_low)},
            "retracement_aktuell_pct": round(retr_now * 100, 1),
            "retracement_max_pct": round(retr_max * 100, 1),
            "zaehlung_qualitaet": round(score * 100),
            "labels": labels,
        },
        "zone": {"oben": r(zone_top), "unten": r(zone_bot), "nachkauf": r(nachkauf), "invalidierung": r(invalid)},
        "ziele": {"t1": r(t1), "t2": r(t2), "t3": r(t3)},
        "plan": plan,
        "parameter": {"vol_jahr_pct": round(vol * 100, 1), "zigzag_mittel_pct": round(mid * 100)},
        "chart": candles,
    }
