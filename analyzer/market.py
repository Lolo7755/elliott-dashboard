"""
Marktüberblick: wichtige Indizes (Tagesveränderung) und ein eigener Angst-&-Gier-Index.

Ersatzwert (0 = extreme Angst, 100 = extreme Gier), Mittelwert aus fünf Teilen:
  1. Volatilität:  VIX im Verhältnis zu seinem 50-Tage-Schnitt
  2. Momentum:     S&P 500 vs. 125-Tage-Linie, -6 % -> 0, +6 % -> 100
  3. Sichere Häfen: Aktien (SPY) vs. Staatsanleihen (TLT), 20 Tage
  4. Ramschanleihen: High-Yield (HYG) vs. Staatsanleihen (IEF), 20 Tage
  5. Marktbreite:  Anteil der Watchlist-Aktien über ihrer 200-Tage-Linie (in %)
Vorrang hat der offizielle CNN Fear & Greed Index (7 Teilindikatoren). Nur wenn CNN nicht
erreichbar ist, wird der eigene Ersatzwert verwendet.
"""
from __future__ import annotations

INDIZES = [
    ("^GSPC", "S&P 500"), ("^NDX", "Nasdaq 100"), ("^GDAXI", "DAX"), ("^STOXX50E", "Euro Stoxx 50"),
    ("^N225", "Nikkei 225"), ("GC=F", "Gold"), ("EURUSD=X", "EUR/USD"), ("BTC-USD", "Bitcoin"),
]


SEKTOREN = [
    ("XLK", "Technologie"), ("SMH", "Halbleiter"), ("BOTZ", "KI & Robotik"), ("XLC", "Kommunikation"),
    ("XLY", "Zyklischer Konsum"), ("XLP", "Basiskonsum"), ("XLF", "Finanzen"), ("XLV", "Gesundheit"),
    ("XLI", "Industrie"), ("ITA", "Rüstung"), ("XLE", "Energie"), ("XLB", "Rohstoffe"),
    ("XLU", "Versorger"), ("XLRE", "Immobilien"), ("TAN", "Solar"), ("IBB", "Biotech"),
]


def _perf(h, tage: int):
    if h is None or len(h) <= tage:
        return None
    return round((float(h.iloc[-1]) / float(h.iloc[-1 - tage]) - 1) * 100, 2)


def fetch_sektoren() -> list[dict]:
    """Sektor-Performance über US-Sektor-ETFs (1 Tag, 1 Woche, 1 Monat, seit Jahresbeginn)."""
    import yfinance as yf

    out = []
    for sym, name in SEKTOREN:
        try:
            h = yf.Ticker(sym).history(period="1y", interval="1d")["Close"].dropna()
            h.index = h.index.tz_localize(None)
            ytd_base = h[h.index.year < h.index[-1].year]
            ytd = round((float(h.iloc[-1]) / float(ytd_base.iloc[-1]) - 1) * 100, 2) if len(ytd_base) else None
            out.append({"symbol": sym, "name": name, "tag": _perf(h, 1), "woche": _perf(h, 5),
                        "monat": _perf(h, 21), "ytd": ytd})
        except Exception:
            pass
    return out


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


CNN_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
CNN_TEILE = [
    ("market_momentum_sp125", "Momentum S&P 500"), ("stock_price_strength", "52-Wochen-Hochs/-Tiefs"),
    ("stock_price_breadth", "Marktbreite"), ("put_call_options", "Put/Call-Verhältnis"),
    ("market_volatility_vix", "Volatilität (VIX)"), ("junk_bond_demand", "Nachfrage Ramschanleihen"),
    ("safe_haven_demand", "Flucht in sichere Häfen"),
]
RATING_DE = {"extreme fear": "Extreme Angst", "fear": "Angst", "neutral": "Neutral",
             "greed": "Gier", "extreme greed": "Extreme Gier"}


def fetch_cnn() -> dict | None:
    """Offizieller CNN Fear & Greed Index inkl. der 7 Teilindikatoren (öffentliche JSON-Schnittstelle).
    Einfache Anfrage ohne Tricks – lehnt CNN sie ab, wird der eigene Ersatzwert verwendet."""
    try:
        import requests
        r = requests.get(CNN_URL, headers={"User-Agent": "elliott-dashboard/1.0 (github.com/Lolo7755/elliott-dashboard)",
                                           "Accept": "application/json"}, timeout=20)
        if not r.ok:
            print(f"CNN Fear & Greed nicht verfügbar (HTTP {r.status_code}) – Ersatzwert wird berechnet")
            return None
        j = r.json()
    except Exception as e:
        print(f"CNN Fear & Greed nicht verfügbar ({e}) – Ersatzwert wird berechnet")
        return None
    fg = (j or {}).get("fear_and_greed") or {}
    if fg.get("score") is None:
        return None
    teile = []
    for key, name in CNN_TEILE:
        v = j.get(key) or {}
        if v.get("score") is not None:
            teile.append({"name": name, "wert": round(float(v["score"])),
                          "label": RATING_DE.get(str(v.get("rating", "")).lower(), "")})
    rnd = lambda x: None if x is None else round(float(x))  # noqa: E731
    return {"wert": round(float(fg["score"])), "vortag": rnd(fg.get("previous_close")),
            "woche": rnd(fg.get("previous_1_week")), "monat": rnd(fg.get("previous_1_month")),
            "jahr": rnd(fg.get("previous_1_year")), "teile_cnn": teile}


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
    # Ersatzwert nach CNN-Logik (5 von 7 Teilen frei verfügbar)
    try:  # Volatilität: VIX im Verhältnis zu seinem 50-Tage-Schnitt
        v = yf.Ticker("^VIX").history(period="6mo")["Close"].dropna()
        vix, rel = float(v.iloc[-1]), float(v.iloc[-1]) / float(v.iloc[-50:].mean())
        teile.append(_clip((1.25 - rel) / 0.45 * 100))
        texte.append(f"VIX {_de(vix)} ({'+' if rel >= 1 else ''}{_de((rel - 1) * 100, 0)} % ggü. 50-Tage-Schnitt)")
    except Exception:
        pass
    spx = closes.get("^GSPC")
    if spx is not None and len(spx) >= 125:  # Momentum: S&P 500 vs. 125-Tage-Linie
        mom = float(spx.iloc[-1]) / float(spx.iloc[-125:].mean()) - 1
        teile.append(_clip((mom + 0.06) / 0.12 * 100))
        texte.append(f"S&P 500 {'+' if mom >= 0 else ''}{_de(mom * 100)} % ggü. 125-Tage-Linie")

    def _ret20(sym):
        h = yf.Ticker(sym).history(period="3mo")["Close"].dropna()
        return float(h.iloc[-1]) / float(h.iloc[-21]) - 1

    try:  # Sichere Häfen: Aktien (SPY) vs. Staatsanleihen (TLT), 20 Tage
        d = _ret20("SPY") - _ret20("TLT")
        teile.append(_clip((d + 0.05) / 0.10 * 100))
        texte.append(f"Aktien vs. Anleihen {'+' if d >= 0 else ''}{_de(d * 100)} %")
    except Exception:
        pass
    try:  # Ramschanleihen: High-Yield (HYG) vs. sichere Anleihen (IEF), 20 Tage
        d = _ret20("HYG") - _ret20("IEF")
        teile.append(_clip((d + 0.02) / 0.04 * 100))
        texte.append(f"Ramsch- vs. Staatsanleihen {'+' if d >= 0 else ''}{_de(d * 100)} %")
    except Exception:
        pass
    mit = [r for r in results if r.get("sma200")]
    if mit:
        breite = sum(r["kurs"] > r["sma200"] for r in mit) / len(mit) * 100
        teile.append(_clip(breite))
        texte.append(f"{round(breite)} % der Watchlist über 200-Tage-Linie")

    stimmung = None
    cnn = None
    try:
        cnn = fetch_cnn()
    except Exception:
        cnn = None
    if cnn:
        stimmung = {
            "wert": cnn["wert"], "label": _label(cnn["wert"]), "quelle": "CNN Fear & Greed Index",
            "vortag": cnn["vortag"], "woche": cnn["woche"], "monat": cnn["monat"], "jahr": cnn["jahr"],
            "teile": [f"{t['name']} {t['wert']}" for t in cnn["teile_cnn"]], "teile_cnn": cnn["teile_cnn"],
            "erklaerung": ("Offizieller CNN Fear & Greed Index aus 7 Teilindikatoren. Hohe Werte = Gier: Kurse sind gelaufen, "
                           "Rücksetzer werden wahrscheinlicher. Niedrige Werte = Angst: oft gute Einstiegsphasen für Langfrist-Anleger."),
        }
    elif teile:
        wert = round(sum(teile) / len(teile))
        vortag = (previous or {}).get("wert")
        stimmung = {
            "wert": wert, "label": _label(wert), "teile": texte, "vortag": vortag,
            "quelle": "Ersatzwert (CNN nicht erreichbar)",
            "erklaerung": ("Hohe Werte = Gier: Viele kaufen, Kurse sind gelaufen – Rücksetzer werden wahrscheinlicher. "
                           "Niedrige Werte = Angst: Viele verkaufen – oft gute Einstiegsphasen für Langfrist-Anleger."),
        }
    try:
        sektoren = fetch_sektoren()
    except Exception:
        sektoren = []
    return {"indizes": indizes, "stimmung": stimmung, "sektoren": sektoren}
