"""Analystenratings und Kursziele aus Yahoo Finance (über yfinance)."""
from __future__ import annotations

LABELS = {
    "strong_buy": "Strong Buy", "buy": "Buy", "hold": "Hold",
    "underperform": "Sell", "sell": "Sell", "strong_sell": "Strong Sell",
}


def _label_from_mean(m: float | None) -> str | None:
    if m is None:
        return None
    if m <= 1.5:
        return "Strong Buy"
    if m <= 2.5:
        return "Buy"
    if m <= 3.5:
        return "Hold"
    if m <= 4.5:
        return "Sell"
    return "Strong Sell"


def fetch_analysts(ticker, last_price: float) -> dict | None:
    """ticker = yfinance.Ticker. Liefert None, wenn es keine Analystendaten gibt."""
    try:
        info = ticker.info or {}
    except Exception:
        info = {}
    mean = info.get("recommendationMean")
    label = LABELS.get(info.get("recommendationKey") or "") or _label_from_mean(mean)
    anzahl = info.get("numberOfAnalystOpinions")

    verteilung = None
    try:
        rec = ticker.recommendations
        if rec is not None and len(rec):
            row = rec.iloc[0]
            verteilung = {k: int(row.get(k, 0) or 0) for k in ("strongBuy", "buy", "hold", "sell", "strongSell")}
            if not anzahl:
                anzahl = sum(verteilung.values()) or None
    except Exception:
        pass

    ziel = info.get("targetMeanPrice")
    if not label and not ziel and not verteilung:
        return None

    def r(x):
        return None if x is None else round(float(x), 2)

    if label in ("Strong Buy", "Buy"):
        ampel = "gruen"
    elif label == "Hold":
        ampel = "orange"
    elif label:
        ampel = "rot"
    else:
        ampel = None
    return {
        "rating": label,
        "ampel": ampel,
        "score": r(mean),                       # 1 = Strong Buy … 5 = Strong Sell
        "anzahl": anzahl,
        "verteilung": verteilung,
        "ziel_mittel": r(ziel),
        "ziel_median": r(info.get("targetMedianPrice")),
        "ziel_hoch": r(info.get("targetHighPrice")),
        "ziel_tief": r(info.get("targetLowPrice")),
        "potenzial_pct": round((ziel / last_price - 1) * 100, 1) if ziel and last_price else None,
    }
