"""
Lädt Kursdaten für alle Werte aus watchlist.csv, analysiert sie und schreibt
docs/data.json (für das Dashboard) sowie docs/signal_historie.csv
(jede Signaländerung wird angehängt, nie gelöscht).

Pro Aktie:
  - Elliott-Analyse (analyzer/elliott.py)
  - Analystenratings und Kursziele (analyzer/analysts.py)
  - Trefferquote per Backtest (analyzer/backtest.py)

Aufruf:  python -m analyzer.run
"""
from __future__ import annotations

import csv
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from analyzer.analysts import fetch_analysts
from analyzer.backtest import backtest
from analyzer.elliott import analyze
from analyzer.extras import fetch_meta, fetch_news, fetch_termine
from analyzer.market import fetch_market
from analyzer.notify import send as send_telegram
from analyzer.scenarios import build as build_scenarios

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"


def load_watchlist() -> list[dict]:
    rows = []
    with open(ROOT / "watchlist.csv", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            sym = (r.get("symbol") or "").strip()
            if sym and not sym.startswith("#"):
                rows.append({"symbol": sym, "name": (r.get("name") or sym).strip()})
    return rows


def fetch(symbol: str):
    import yfinance as yf

    t = yf.Ticker(symbol)
    df = None
    for attempt in range(3):  # bei Yahoo-Drosselung kurz warten und erneut versuchen
        try:
            df = t.history(period="10y", interval="1d", auto_adjust=False)
            if df is not None and not df.empty:
                break
        except Exception:
            pass
        time.sleep(3 * (attempt + 1))
    if df is None or df.empty:
        raise ValueError("keine Kursdaten")
    df.index = pd.DatetimeIndex(df.index).tz_localize(None)
    try:
        cur = t.fast_info.get("currency") or ""
    except Exception:
        cur = ""
    return df[["Open", "High", "Low", "Close"]], cur, t


def main() -> int:
    DOCS.mkdir(exist_ok=True)
    old, old_markt = {}, {}
    if (DOCS / "data.json").exists():
        try:
            prev_data = json.loads((DOCS / "data.json").read_text())
            old = {a["symbol"]: a for a in prev_data["aktien"]}
            old_markt = prev_data.get("markt") or {}
        except Exception:
            old = {}
    kommentare = {}
    if (DOCS / "kommentare.json").exists():
        kommentare = json.loads((DOCS / "kommentare.json").read_text(encoding="utf-8"))

    results, errors = [], []
    for item in load_watchlist():
        sym = item["symbol"]
        try:
            df, cur, ticker = fetch(sym)
            res = analyze(df, sym, item["name"], cur)
            res["analysten"] = fetch_analysts(ticker, res["kurs"])
            res["meta"] = fetch_meta(ticker)
            res["termine"] = fetch_termine(ticker)
            res["news"] = fetch_news(ticker, name=item["name"])
            try:
                res["backtest"] = backtest(df, sym)
            except Exception as e:
                res["backtest"] = None
                print(f"     {sym}: Backtest-Fehler {e}", file=sys.stderr)
            res["kommentar"] = kommentare.get(sym)
            prev = old.get(sym)
            res["signal_vorher"] = prev["signal"] if prev else None
            res["status_vorher"] = prev["status"] if prev else None
            results.append(res)
            bt = res["backtest"] or {}
            an = res["analysten"] or {}
            print(f"OK   {sym:11s} {res['status']:28s} Analysten: {an.get('rating')}  Treffer: {bt.get('quote_pct')}%")
        except Exception as e:  # einzelne Fehler sollen den Lauf nicht abbrechen
            errors.append({"symbol": sym, "fehler": str(e)})
            print(f"FEHL {sym:11s} {e}", file=sys.stderr)
        time.sleep(0.3)

    # Gesamt-Trefferquote über alle Aktien
    t = sum((r.get("backtest") or {}).get("treffer", 0) for r in results)
    f = sum((r.get("backtest") or {}).get("fehler", 0) for r in results)
    o = sum((r.get("backtest") or {}).get("offen", 0) for r in results)
    gesamt = {"treffer": t, "fehler": f, "offen": o, "quote_pct": round(t / (t + f) * 100) if (t + f) else None}

    # Szenarien: Wahrscheinlichkeiten aus den Backtest-Basisraten aller Aktien
    zz = sum(((r.get("backtest") or {}).get("zulauf") or {}).get("zone", 0) for r in results)
    zd = sum(((r.get("backtest") or {}).get("zulauf") or {}).get("direkt", 0) for r in results)
    rates = {"zone_erfolg": t / (t + f) if (t + f) else None, "zulauf_zone": zz / (zz + zd) if (zz + zd) else None}
    gesamt["zulauf_zone_pct"] = round(rates["zulauf_zone"] * 100) if rates["zulauf_zone"] is not None else None
    for r in results:
        try:
            r["szenarien"] = build_scenarios(r, rates)
        except Exception as e:
            r["szenarien"] = None
            print(f"     {r['symbol']}: Szenario-Fehler {e}", file=sys.stderr)

    try:
        markt = fetch_market(results, old_markt.get("stimmung"))
    except Exception as e:
        markt = None
        print(f"Markt-Fehler {e}", file=sys.stderr)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    (DOCS / "data.json").write_text(
        json.dumps({"erstellt": now, "trefferquote": gesamt, "markt": markt, "aktien": results, "fehler": errors},
                   ensure_ascii=False),
        encoding="utf-8",
    )

    # Signalhistorie (nur Änderungen anhängen)
    hist = DOCS / "signal_historie.csv"
    new_file = not hist.exists()
    with open(hist, "a", newline="", encoding="utf-8") as fh:
        wr = csv.writer(fh)
        if new_file:
            wr.writerow(["datum", "symbol", "kurs", "status_alt", "status_neu", "signal_neu"])
        for r in results:
            if r["status"] != r["status_vorher"]:
                wr.writerow([r["stand"], r["symbol"], r["kurs"], r["status_vorher"] or "", r["status"], r["signal"]])
    print(f"{len(results)} analysiert, {len(errors)} Fehler, Trefferquote gesamt: {gesamt}")
    send_telegram(results, gesamt)
    return 0 if results else 1


if __name__ == "__main__":
    sys.exit(main())
