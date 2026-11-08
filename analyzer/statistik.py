"""
Zusatzstatistiken pro Aktie aus der Kurshistorie (kein zusätzlicher Download nötig).

Übernacht:   Wie entwickelt sich die Aktie vom Schlusskurs bis zur Eröffnung am nächsten
             Handelstag? (passt zur Strategie "abends kaufen, morgens verkaufen")
Saisonalität: Durchschnittliche Monatsrendite und Anteil positiver Jahre je Kalendermonat.
"""
from __future__ import annotations

import pandas as pd


def uebernacht(daily: pd.DataFrame, tage: int = 504) -> dict | None:
    """Rendite Schluss -> nächste Eröffnung der letzten ~2 Jahre."""
    d = daily[["Open", "Close"]].dropna()
    d = d[(d["Open"] > 0) & (d["Close"] > 0)].iloc[-(tage + 1):]
    if len(d) < 60:
        return None
    nacht = (d["Open"].shift(-1) / d["Close"] - 1).dropna()
    tag = (d["Close"] / d["Close"].shift(1) - 1).reindex(nacht.index)
    # Tage ohne echte Eröffnung (Open == Vortagesschluss exakt) verzerren das Bild kaum, bleiben drin
    nach_minus = nacht[tag <= -0.02]
    nach_plus = nacht[tag >= 0.02]

    def r(x, k=2):
        return None if x is None or x != x else round(float(x) * 100, k)

    return {
        "n": int(len(nacht)),
        "pos_pct": round(float((nacht > 0).mean()) * 100),
        "mittel_pct": r(nacht.mean()),
        "median_pct": r(nacht.median()),
        "nach_minus_pct": r(nach_minus.mean()) if len(nach_minus) >= 10 else None,
        "nach_minus_pos_pct": round(float((nach_minus > 0).mean()) * 100) if len(nach_minus) >= 10 else None,
        "n_minus": int(len(nach_minus)),
        "nach_plus_pct": r(nach_plus.mean()) if len(nach_plus) >= 10 else None,
        "schlechteste_pct": r(nacht.min(), 1),
        "beste_pct": r(nacht.max(), 1),
    }


def saison(closes: pd.Series) -> list[dict] | None:
    """Monatsrenditen je Kalendermonat (bis zu 10 Jahre)."""
    c = closes.dropna()
    if len(c) < 260:
        return None
    m = c.resample("ME").last().pct_change().dropna()
    # angebrochenen aktuellen Monat nicht mitzählen
    if len(m) and m.index[-1].to_period("M") == c.index[-1].to_period("M"):
        m = m.iloc[:-1]
    out = []
    for monat in range(1, 13):
        x = m[m.index.month == monat]
        if len(x) < 3:
            out.append({"m": monat, "n": int(len(x)), "mittel_pct": None, "pos_pct": None})
            continue
        out.append({"m": monat, "n": int(len(x)), "mittel_pct": round(float(x.mean()) * 100, 1),
                    "median_pct": round(float(x.median()) * 100, 1), "pos_pct": round(float((x > 0).mean()) * 100)})
    return out
