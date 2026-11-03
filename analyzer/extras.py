"""Zusatzdaten pro Aktie aus Yahoo Finance: Sektor/Land, Termine, News."""
from __future__ import annotations

from datetime import date, datetime, timezone

SECTOR_DE = {
    "Technology": "Technologie", "Communication Services": "Kommunikation",
    "Consumer Cyclical": "Zyklischer Konsum", "Consumer Defensive": "Basiskonsum",
    "Financial Services": "Finanzen", "Healthcare": "Gesundheit", "Industrials": "Industrie",
    "Energy": "Energie", "Basic Materials": "Rohstoffe", "Utilities": "Versorger",
    "Real Estate": "Immobilien",
}
COUNTRY_DE = {
    "United States": "USA", "Germany": "Deutschland", "France": "Frankreich", "Switzerland": "Schweiz",
    "United Kingdom": "Großbritannien", "Netherlands": "Niederlande", "Denmark": "Dänemark",
    "Spain": "Spanien", "Italy": "Italien", "Ireland": "Irland", "Sweden": "Schweden",
    "Japan": "Japan", "South Korea": "Südkorea", "China": "China", "Hong Kong": "Hongkong",
    "Taiwan": "Taiwan", "India": "Indien", "Canada": "Kanada", "Australia": "Australien",
    "Brazil": "Brasilien", "Uruguay": "Uruguay", "Argentina": "Argentinien",
    "Cayman Islands": "Kaimaninseln", "Israel": "Israel", "Singapore": "Singapur", "Luxembourg": "Luxemburg",
}


def _info(ticker) -> dict:
    try:
        return ticker.info or {}
    except Exception:
        return {}


def fetch_meta(ticker) -> dict:
    info = _info(ticker)
    s, c = info.get("sector"), info.get("country")
    return {"sektor": SECTOR_DE.get(s, s), "land": COUNTRY_DE.get(c, c), "branche": info.get("industry")}


def _to_date(x):
    if x is None:
        return None
    if isinstance(x, datetime):
        return x.date()
    if isinstance(x, date):
        return x
    try:
        return datetime.fromtimestamp(float(x), tz=timezone.utc).date()
    except Exception:
        pass
    try:
        return datetime.fromisoformat(str(x)[:10]).date()
    except Exception:
        return None


def fetch_termine(ticker) -> dict:
    """Nächster Earnings-Termin, Ex-Dividende, Dividenden-Zahltag (nur zukünftige)."""
    today = date.today()
    earnings = exdiv = divpay = None
    try:
        cal = ticker.calendar
        if isinstance(cal, dict):
            ed = cal.get("Earnings Date")
            eds = ed if isinstance(ed, (list, tuple)) else [ed]
            fut = sorted(d for d in (_to_date(e) for e in eds) if d and d >= today)
            earnings = fut[0] if fut else None
            exdiv = _to_date(cal.get("Ex-Dividend Date"))
            divpay = _to_date(cal.get("Dividend Date"))
    except Exception:
        pass
    if earnings is None:
        try:
            ed = ticker.get_earnings_dates(limit=8)
            if ed is not None and len(ed):
                fut = sorted(d.date() for d in ed.index if d.date() >= today)
                earnings = fut[0] if fut else None
        except Exception:
            pass

    def iso(d):
        return d.isoformat() if d and d >= today else None

    out = {"earnings": iso(earnings), "ex_dividende": iso(exdiv), "dividende_zahltag": iso(divpay)}
    out["earnings_in_tagen"] = (earnings - today).days if out["earnings"] else None
    return out


def fetch_news(ticker, n: int = 5) -> list[dict]:
    try:
        items = ticker.news or []
    except Exception:
        return []
    out = []
    for it in items:
        c = it.get("content", it) if isinstance(it, dict) else {}
        title = c.get("title")
        url = ((c.get("canonicalUrl") or {}).get("url") or (c.get("clickThroughUrl") or {}).get("url")
               or c.get("link"))
        when = c.get("pubDate") or c.get("displayTime") or it.get("providerPublishTime")
        d = _to_date(when)
        src = (c.get("provider") or {}).get("displayName") or c.get("publisher")
        if title and url:
            out.append({"titel": title, "url": url, "datum": d.isoformat() if d else None, "quelle": src})
        if len(out) >= n:
            break
    return out
