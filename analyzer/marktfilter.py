"""
Marktfilter: bezieht die Lage des Gesamtmarkts und die relative Stärke einer Aktie in die Kaufsignale ein.

Marktlage (für jeden Tag nur mit den bis dahin bekannten Kursen berechnet):
  Abverkauf : VIX mind. 30 % über seinem 50-Tage-Schnitt ODER S&P 500 in 5 Tagen um mind. 4 % gefallen
  Schwach   : S&P 500 unter seiner 200-Tage-Linie (und kein akuter Abverkauf)
  Gesund    : alles andere

Relative Stärke: 20-Tage-Rendite der Aktie minus 20-Tage-Rendite ihres Heimatindex.
  Eigene Schwäche: mind. 8 Prozentpunkte schlechter als der Index.

Ob der Filter ein Kaufsignal wirklich abschwächt, entscheidet der Backtest: Er greift nur, wenn
Signale in dieser Lage historisch klar schlechter liefen (mind. 8 Prozentpunkte weniger Treffer,
mind. 25 abgeschlossene Signale). Sonst gibt es nur einen Hinweis.
"""
from __future__ import annotations

import pandas as pd

MIN_N = 25         # mindestens so viele abgeschlossene Signale je Klasse
MIN_ABSTAND = 8    # Prozentpunkte schlechtere Trefferquote, damit der Filter greift
RS_GRENZE = -0.08  # eigene Schwäche ab -8 Prozentpunkten ggü. Index (20 Tage)

LABEL = {"gesund": "Gesund", "schwach": "Angeschlagen", "abverkauf": "Abverkauf"}
INDEX_NAME = {"^GSPC": "S&P 500", "^STOXX50E": "Euro Stoxx 50", "^N225": "Nikkei 225", "^HSI": "Hang Seng",
              "^KS11": "KOSPI", "^NSEI": "Nifty 50", "^AXJO": "ASX 200", "^GDAXI": "DAX"}
EUROPA = (".DE", ".PA", ".AS", ".MI", ".MC", ".SW", ".CO", ".L", ".ST", ".HE", ".OL", ".BR", ".VI", ".LS", ".IR")


def index_fuer(symbol: str) -> str:
    s = symbol.upper()
    if s.endswith(".DE"):
        return "^GDAXI"
    if s.endswith(EUROPA):
        return "^STOXX50E"
    for suf, idx in ((".T", "^N225"), (".HK", "^HSI"), (".KS", "^KS11"), (".NS", "^NSEI"),
                     (".BO", "^NSEI"), (".AX", "^AXJO")):
        if s.endswith(suf):
            return idx
    return "^GSPC"


def lade_markt() -> dict | None:
    """Lädt S&P 500, VIX und die Heimatindizes einmalig und berechnet die Marktlage für jeden Tag."""
    import yfinance as yf

    def close(sym, period="max"):
        h = yf.Ticker(sym).history(period=period, interval="1d", auto_adjust=False)
        try:
            neu = yf.Ticker(sym).history(period="5d", interval="1d", auto_adjust=False)
            h = pd.concat([h, neu])
        except Exception:
            pass
        c = h["Close"].dropna()
        c.index = pd.DatetimeIndex(c.index).tz_localize(None).normalize()
        return c[~c.index.duplicated(keep="last")].sort_index()

    try:
        spx, vix = close("^GSPC"), close("^VIX")
    except Exception as e:
        print(f"Marktfilter: Indexdaten nicht verfügbar ({e})")
        return None
    df = pd.DataFrame({"spx": spx}).join(pd.DataFrame({"vix": vix}), how="left")
    df["vix"] = df["vix"].ffill()
    df["sma200"] = df["spx"].rolling(200).mean()
    df["ret5"] = df["spx"] / df["spx"].shift(5) - 1
    df["vix_rel"] = df["vix"] / df["vix"].rolling(50).mean()
    df = df.dropna()
    abv = (df["vix_rel"] >= 1.30) | (df["ret5"] <= -0.04)
    df["regime"] = "gesund"
    df.loc[df["spx"] < df["sma200"], "regime"] = "schwach"
    df.loc[abv, "regime"] = "abverkauf"

    idx = {"^GSPC": spx}
    for sym in INDEX_NAME:
        if sym not in idx:
            try:
                idx[sym] = close(sym)
            except Exception:
                pass
    return {"tage": df, "idx": idx}


def regime_am(markt: dict | None, datum) -> str | None:
    if not markt:
        return None
    df = markt["tage"]
    pos = df.index.searchsorted(pd.Timestamp(datum), side="right") - 1
    return None if pos < 0 else df["regime"].iloc[pos]


def rs20(markt: dict | None, symbol: str, close: pd.Series) -> float | None:
    """20-Tage-Rendite der Aktie minus 20-Tage-Rendite des Heimatindex (bis zum letzten Tag von close)."""
    if not markt or len(close) < 21:
        return None
    ix = markt["idx"].get(index_fuer(symbol))
    if ix is None:
        ix = markt["idx"].get("^GSPC")
    if ix is None:
        return None
    d1, d0 = close.index[-1], close.index[-21]
    i1 = ix[:d1]
    i0 = ix[:d0]
    if not len(i1) or not len(i0):
        return None
    return float(close.iloc[-1] / close.iloc[-21] - 1) - float(i1.iloc[-1] / i0.iloc[-1] - 1)


def rs_klasse(rs: float | None) -> str | None:
    if rs is None:
        return None
    return "eigen" if rs <= RS_GRENZE else "markt"


def _quote(x: dict) -> float | None:
    n = x["treffer"] + x["fehler"]
    return x["treffer"] / n * 100 if n else None


def auswerten(results: list[dict]) -> dict:
    """Trefferquote der Kaufsignale je Marktlage / relativer Stärke – über alle Aktien."""
    def leer():
        return {"treffer": 0, "fehler": 0, "rendite_summe": 0.0}

    nach_markt = {k: leer() for k in LABEL}
    nach_rs = {"markt": leer(), "eigen": leer()}
    for r in results:
        for s in (r.get("backtest") or {}).get("signale", []):
            if s["ergebnis"] == "offen":
                continue
            for grp, key in ((nach_markt, s.get("markt")), (nach_rs, s.get("rs_klasse"))):
                if key in grp:
                    grp[key][s["ergebnis"]] += 1
                    grp[key]["rendite_summe"] += s["rendite_pct"]

    def fertig(g):
        out = {}
        for k, v in g.items():
            n = v["treffer"] + v["fehler"]
            out[k] = {"treffer": v["treffer"], "fehler": v["fehler"], "n": n,
                      "quote_pct": round(_quote(v)) if n else None,
                      "rendite_schnitt_pct": round(v["rendite_summe"] / n, 1) if n else None}
        return out

    m, rs = fertig(nach_markt), fertig(nach_rs)

    def schlechter(x, basis):
        return (x["n"] >= MIN_N and basis["n"] >= MIN_N and x["quote_pct"] is not None
                and basis["quote_pct"] is not None and x["quote_pct"] <= basis["quote_pct"] - MIN_ABSTAND)

    def befund(x, basis):
        if x["n"] < MIN_N or basis["n"] < MIN_N:
            return "zu_wenig"
        return "nachteil" if schlechter(x, basis) else "kein_nachteil"

    befunde = {"schwach": befund(m["schwach"], m["gesund"]), "abverkauf": befund(m["abverkauf"], m["gesund"]),
               "eigen": befund(rs["eigen"], rs["markt"])}
    aktiv = {k: v == "nachteil" for k, v in befunde.items()}
    return {"nach_markt": m, "nach_rs": rs, "aktiv": aktiv, "befund": befunde}


def lage_heute(markt: dict | None) -> dict | None:
    if not markt:
        return None
    df = markt["tage"]
    z = df.iloc[-1]
    return {"regime": z["regime"], "label": LABEL[z["regime"]], "datum": df.index[-1].strftime("%Y-%m-%d"),
            "spx_vs_200_pct": round((z["spx"] / z["sma200"] - 1) * 100, 1),
            "spx_5t_pct": round(z["ret5"] * 100, 1),
            "vix": round(float(z["vix"]), 1), "vix_vs_50_pct": round((z["vix_rel"] - 1) * 100)}


KAUF_START = ("teilkauf", "letzter nachkauf", "kleine position")


def anwenden(r: dict, lage: dict | None, test: dict, rs: float | None) -> None:
    """Passt das Kaufsignal einer Aktie an Marktlage und relative Stärke an (nur wenn der Backtest es stützt)."""
    sig = r.get("signal") or ""
    if not sig.lower().startswith(KAUF_START):
        r["markt_filter"] = {"rs20_pct": None if rs is None else round(rs * 100, 1)}
        return
    aktiv = test.get("aktiv", {})
    bef = test.get("befund", {})

    def kein(key):
        return " – zu wenige historische Signale für eine Aussage" if bef.get(key) == "zu_wenig" else " – laut Backtest aber kein Nachteil"

    reg = lage["regime"] if lage else None
    hinweise, blockiert, reduziert, grund = [], False, False, ""
    if reg == "abverkauf":
        if aktiv.get("abverkauf"):
            blockiert, grund = True, "Markt im akuten Abverkauf"
            hinweise.append("Akuter Marktabverkauf – Kaufsignale liefen in solchen Phasen historisch schlechter")
        else:
            hinweise.append("Akuter Marktabverkauf" + kein("abverkauf"))
    elif reg == "schwach":
        if aktiv.get("schwach"):
            reduziert = True
            hinweise.append("S&P 500 unter der 200-Tage-Linie – nur erste Tranche, Rest erst bei Erholung")
        else:
            hinweise.append("S&P 500 unter der 200-Tage-Linie" + kein("schwach"))
    if rs_klasse(rs) == "eigen":
        txt = f"Aktie {abs(rs) * 100:.0f} Prozentpunkte schwächer als ihr Index (20 Tage)".replace(".", ",")
        if aktiv.get("eigen"):
            blockiert, grund = True, grund or "Aktie deutlich schwächer als ihr Index"
            hinweise.append(txt + " – eigene Schwäche, erst Stabilisierung abwarten")
        else:
            hinweise.append(txt + kein("eigen"))
    original = sig
    if blockiert:
        r["signal"] = f"Abwarten (Marktfilter) – Kaufzone erreicht, aber {grund}"
        r["ampel"] = "orange"
    elif reduziert:
        r["signal"] = "Teilkauf 1 (nur ca. 1/3) – Markt angeschlagen, Rest erst bei Erholung"
    r["markt_filter"] = {"rs20_pct": None if rs is None else round(rs * 100, 1), "regime": reg,
                         "blockiert": blockiert, "reduziert": reduziert, "hinweise": hinweise,
                         "signal_original": original if (blockiert or reduziert) else None}
