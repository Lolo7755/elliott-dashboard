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
from analyzer.marktfilter import regime_am, rs20, rs_klasse

STEP_DAYS = 10          # Handelstage zwischen zwei Rückblick-Analysen (~2 Wochen)
WARMUP_DAYS = 252 * 3   # mindestens 3 Jahre Historie vor der ersten Rückblick-Analyse
ENTRY_STATUS = ("In Zone", "In Zone (unten)")


def backtest(daily: pd.DataFrame, symbol: str, markt: dict | None = None) -> dict:
    daily = daily.dropna(subset=["High", "Low", "Close"])
    n = len(daily)
    signals: list[dict] = []
    seen_cycles: set[str] = set()
    seen_zulauf: set[str] = set()
    zulauf = {"zone": 0, "direkt": 0, "offen": 0}  # erreicht eine laufende Korrektur die Zone?
    seen_imp: set[str] = set()
    verkauf: list[dict] = []  # Verkaufssignale "Impuls vollendet"
    seen_abw: set[str] = set()
    abwaerts = {"haelt": 0, "ausbruch": 0, "offen": 0}  # hält ein Abwärtstrend an?

    ends = list(range(WARMUP_DAYS, n, STEP_DAYS)) + [n]  # letzter Punkt = heute (offenes Signal)
    for end in ends:
        hist = daily.iloc[:end]
        try:
            res = analyze(hist, symbol)
        except Exception:
            continue
        cycle = f'{res["welle"]["start"]["date"]}|{res["welle"]["hoch"]["date"]}'
        if res["status"] == "Zulaufend" and cycle not in seen_zulauf and cycle not in seen_cycles:
            seen_zulauf.add(cycle)
            top, high = float(res["zone"]["oben"]), float(res["welle"]["hoch"]["price"])
            erg = "offen"
            for _, row in daily.iloc[end:].iterrows():
                if row["Low"] <= top:
                    erg = "zone"
                    break
                if row["High"] > high:
                    erg = "direkt"
                    break
            zulauf[erg] += 1
        imp_key = res["welle"]["start"]["date"]  # ein Verkaufssignal pro Impuls
        if res["status"] == "Impuls vollendet" and imp_key not in seen_imp:
            # Treffer = Kurs fällt um 10 % unter den Verkaufskurs (günstiger Rückkauf möglich),
            # bevor er 10 % darüber steigt
            seen_imp.add(imp_key)
            kurs0 = float(hist["Close"].iloc[-1])
            down, up = kurs0 * 0.90, kurs0 * 1.10
            erg = "offen"
            for _, row in daily.iloc[end:].iterrows():
                if row["Low"] <= down:
                    erg = "treffer"
                    break
                if row["High"] >= up:
                    erg = "fehler"
                    break
            verkauf.append({"datum": hist.index[-1].strftime("%Y-%m-%d"), "kurs": round(kurs0, 2),
                            "ziel": round(down, 2), "ergebnis": erg})
        if res["status"] == "Abwärtstrend" and res.get("einstiegs_trigger") and cycle not in seen_abw:
            # Hält der Abwärtstrend? "haelt" = erst weitere -10 %, "ausbruch" = erst über das Zwischenhoch
            seen_abw.add(cycle)
            kurs0, trig = float(hist["Close"].iloc[-1]), float(res["einstiegs_trigger"])
            erg = "offen"
            for _, row in daily.iloc[end:].iterrows():
                if row["Low"] <= kurs0 * 0.90:
                    erg = "haelt"
                    break
                if row["High"] >= trig:
                    erg = "ausbruch"
                    break
            abwaerts[erg] += 1
        if res["status"] not in ENTRY_STATUS:
            continue
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
        rs = rs20(markt, symbol, hist["Close"])
        signals.append({
            "markt": regime_am(markt, hist.index[-1]),  # Marktlage am Signaltag (ohne Blick nach vorn)
            "rs_pct": None if rs is None else round(rs * 100, 1),
            "rs_klasse": rs_klasse(rs),
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
        "zulauf": zulauf,
        "abwaerts": abwaerts,
        "verkauf": {
            "signale": verkauf,
            "treffer": sum(v["ergebnis"] == "treffer" for v in verkauf),
            "fehler": sum(v["ergebnis"] == "fehler" for v in verkauf),
            "offen": sum(v["ergebnis"] == "offen" for v in verkauf),
        },
    }
