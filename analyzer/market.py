"""
Marktüberblick: wichtige Indizes (Tagesveränderung) und ein eigener Angst-&-Gier-Index.

Angst-&-Gier-Index (0 = extreme Angst, 100 = extreme Gier), Mittelwert aus drei Teilen:
  1. Volatilität: VIX 12 -> 100 Punkte, VIX 35 -> 0 Punkte
  2. Momentum:    S&P 500 vs. 125-Tage-Linie, -10 % -> 0, +10 % -> 100
  3. Marktbreite: Anteil der Watchlist-Aktien über ihrer 200-Tage-Linie (in %)
Angelehnt an den bekannten CNN Fear & Greed Index, aber vollständig selbst berechnet.
"""
from __future__ import annotations

INDIZES = [
    ("^GSPC", "S&P 500"), ("^NDX", "Nasdaq 100"), ("^GDAXI", "DAX"), ("^STOXX50E", "Euro Stoxx 50"),
    ("^N225", "Nikkei 225"), ("GC=F", "Gold"), ("EURUSD=X", "EUR/USD"), ("BTC-USD", "Bitcoin"),
]


def _clip(x: float) -> float:
    return max(0.0, min(100.0, x))


def _label(v: float) -> str:
    if v < 25:
        return "Extreme Angst"
    if v < 45:
        return "Angst"
    if v <= 55:
        return "Neutral"
    if v <= 75:
        return "Gier"
    return "Extreme Gier"


def _de(x: float, d: int = 1) -> str:
    return f"{x:.{d}f}".replace(".", ",")


def fetch_market(results: list[dict], previous: dict | None = None) -> dict:
    import yfinance as yf

    indizes, closes = [], {}
    for sym, name in INDIZES:
        try:
            h = yf.Ticker(sym).history(period="1y", interval="1d")["Close"].dropna()
            closes[sym] = h
            if len(h) >= 2:
                indizes.append({"symbol": sym, "name": name, "kurs": round(float(h.iloc[-1]), 2),
                                "tag_pct": round((float(h.iloc[-1]) / float(h.iloc[-2]) - 1) * 100, 2)})
        except Exception:
            pass

    teile, texte = [], []
    try:
        vix = float(yf.Ticker("^VIX").history(period="5d")["Close"].dropna().iloc[-1])
        teile.append(_clip((35 - vix) / (35 - 12) * 100))
        texte.append(f"VIX {_de(vix)} ({'niedrig' if vix < 16 else 'erhöht' if vix > 22 else 'normal'})")
    except Exception:
        pass
    spx = closes.get("^GSPC")
    if spx is not None and len(spx) >= 125:
        mom = float(spx.iloc[-1]) / float(spx.iloc[-125:].mean()) - 1
        teile.append(_clip((mom + 0.10) / 0.20 * 100))
        texte.append(f"S&P 500 {'+' if mom >= 0 else ''}{_de(mom * 100)} % ggü. 125-Tage-Linie")
    mit = [r for r in results if r.get("sma200")]
    if mit:
        breite = sum(r["kurs"] > r["sma200"] for r in mit) / len(mit) * 100
        teile.append(_clip(breite))
        texte.append(f"{round(breite)} % der Watchlist über 200-Tage-Linie")

    stimmung = None
    if teile:
        wert = round(sum(teile) / len(teile))
        vortag = (previous or {}).get("wert")
        stimmung = {
            "wert": wert, "label": _label(wert), "teile": texte, "vortag": vortag,
            "erklaerung": ("Hohe Werte = Gier: Viele kaufen, Kurse sind gelaufen – Rücksetzer werden wahrscheinlicher. "
                           "Niedrige Werte = Angst: Viele verkaufen – oft gute Einstiegsphasen für Langfrist-Anleger."),
        }
    return {"indizes": indizes, "stimmung": stimmung}
