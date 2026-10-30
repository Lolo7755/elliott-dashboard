"""
Lädt Kursdaten für alle Werte aus watchlist.csv, analysiert sie und schreibt
docs/data.json (für das Dashboard) sowie docs/signal_historie.csv
(jede Signaländerung wird angehängt, nie gelöscht).

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

from analyzer.elliott import analyze

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


def fetch(symbol: str) -> tuple[pd.DataFrame, str]:
    import yfinance as yf

    t = yf.Ticker(symbol)
    df = t.history(period="10y", interval="1d", auto_adjust=False)
    if df is None or df.empty:
        raise ValueError("keine Kursdaten")
    df.index = pd.DatetimeIndex(df.index).tz_localize(None)
    try:
        cur = t.fast_info.get("currency") or ""
    except Exception:
        cur = ""
    return df[["Open", "High", "Low", "Close"]], cur


def main() -> int:
    DOCS.mkdir(exist_ok=True)
    old = {}
    if (DOCS / "data.json").exists():
        try:
            old = {a["symbol"]: a for a in json.loads((DOCS / "data.json").read_text())["aktien"]}
        except Exception:
            old = {}
    kommentare = {}
    if (DOCS / "kommentare.json").exists():
        kommentare = json.loads((DOCS / "kommentare.json").read_text(encoding="utf-8"))

    results, errors = [], []
    for item in load_watchlist():
        sym = item["symbol"]
        try:
            df, cur = fetch(sym)
            res = analyze(df, sym, item["name"], cur)
            res["kommentar"] = kommentare.get(sym)
            prev = old.get(sym)
            res["signal_vorher"] = prev["signal"] if prev else None
            res["status_vorher"] = prev["status"] if prev else None
            results.append(res)
            print(f"OK   {sym:10s} {res['status']:28s} {res['signal']}")
        except Exception as e:  # einzelne Fehler sollen den Lauf nicht abbrechen
            errors.append({"symbol": sym, "fehler": str(e)})
            print(f"FEHL {sym:10s} {e}", file=sys.stderr)
        time.sleep(0.5)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    (DOCS / "data.json").write_text(
        json.dumps({"erstellt": now, "aktien": results, "fehler": errors}, ensure_ascii=False),
        encoding="utf-8",
    )

    # Signalhistorie (nur Änderungen anhängen)
    hist = DOCS / "signal_historie.csv"
    new_file = not hist.exists()
    with open(hist, "a", newline="", encoding="utf-8") as f:
        wr = csv.writer(f)
        if new_file:
            wr.writerow(["datum", "symbol", "kurs", "status_alt", "status_neu", "signal_neu"])
        for r in results:
            if r["status"] != r["status_vorher"]:
                wr.writerow([r["stand"], r["symbol"], r["kurs"], r["status_vorher"] or "", r["status"], r["signal"]])
    print(f"{len(results)} analysiert, {len(errors)} Fehler")
    return 0 if results else 1


if __name__ == "__main__":
    sys.exit(main())
