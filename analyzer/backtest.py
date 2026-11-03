"""
Trefferquote der Elliott-Signale (Backtest ohne Blick in die Zukunft).

Für jede Aktie wird die Analyse rückwirkend alle 2 Wochen ausgeführt – jeweils
nur mit den Kursen, die an diesem Tag bekannt waren. Sobald der Kurs zum ersten
Mal in eine Einstiegszone läuft, zählt das als Signal (ein Signal pro Zyklus).

Bewertung des Signals mit den Kursen DANACH:
  Treffer  = Kurs erreicht das Ziel, bevor er die Invalidierung unterschreitet
             Ziel = halber Weg vom Einstieg zurück zum alten Hoch
  Fehler   = Kurs unterschreitet zuerst die Invalidierung (78,6 %-Level)
  Offen    = noch keins von beiden
Trefferquote = Treffer / (Treffer + Fehler)
"""
from __future__ import annotations

import pandas as pd

from analyzer.elliott import analyze

STEP_DAYS = 10          # Handelstage zwischen zwei Rückblick-Analysen (~2 Wochen)
WARMUP_DAYS = 252 * 3   # mindestens 3 Jahre Historie vor der ersten Rückblick-Analyse
ENTRY_STATUS = ("In Zone", "In Zone (unten)")


def backtest(daily: pd.DataFrame, symbol: str) -> dict:
    daily = daily.dropna(subset=["High", "Low", "Close"])
    n = len(daily)
    signals: list[dict] = []
    seen_cycles: set[str] = set()

    ends = list(range(WARMUP_DAYS, n, STEP_DAYS)) + [n]  # letzter Punkt = heute (offenes Signal)
    for end in ends:
        hist = daily.iloc[:end]
        try:
            res = analyze(hist, symbol)
        except Exception:
            continue
        if res["status"] not in ENTRY_STATUS:
            continue
        cycle = f'{res["welle"]["start"]["date"]}|{res["welle"]["hoch"]["date"]}'
        if cycle in seen_cycles:
            continue
        seen_cycles.add(cycle)

        entry = float(hist["Close"].iloc[-1])
        high = float(res["welle"]["hoch"]["price"])
        stop = float(res["zone"]["invalidierung"])
        target = entry + 0.5 * (high - entry)
        future = daily.iloc[end:]
        outcome, exit_date, days = "offen", None, None
        for i, (d, row) in enumerate(future.iterrows()):
            if row["Low"] <= stop:
                outcome, exit_date, days = "fehler", d, i + 1
                break
            if row["High"] >= target:
                outcome, exit_date, days = "treffer", d, i + 1
                break
        signals.append({
            "datum": hist.index[-1].strftime("%Y-%m-%d"),
            "einstieg": round(entry, 2),
            "ziel": round(target, 2),
            "invalidierung": round(stop, 2),
            "ergebnis": outcome,
            "ende": exit_date.strftime("%Y-%m-%d") if exit_date is not None else None,
            "tage": days,
            "rendite_pct": round(((target if outcome == "treffer" else stop if outcome == "fehler"
                                   else float(daily["Close"].iloc[-1])) / entry - 1) * 100, 1),
        })

    t = sum(s["ergebnis"] == "treffer" for s in signals)
    f = sum(s["ergebnis"] == "fehler" for s in signals)
    return {
        "signale": signals,
        "treffer": t,
        "fehler": f,
        "offen": sum(s["ergebnis"] == "offen" for s in signals),
        "quote_pct": round(t / (t + f) * 100) if (t + f) else None,
    }
