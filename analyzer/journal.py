"""
Live-Bilanz: Jedes neue Kaufsignal wird ab dem Signaltag mit echten Kursen nachgehalten.

Ein Trade entsteht, wenn eine Aktie (lang- oder kurzfristig) neu in den Einstiegsbereich
läuft ("In Zone", "In Zone (unten)", "Nachkaufbereich"). Einstieg = Schlusskurs am Signaltag,
Stopp = Invalidierung, Ziel = nächstes Kursziel über dem Kurs (wie beim CRV).

Bewertung mit den Tageskerzen danach:
  Ziel   = Hoch erreicht das Ziel  (Ergebnis in R = Gewinn / Risiko)
  Stopp  = Tief erreicht den Stopp (−1 R, bei einer Kurslücke darunter entsprechend mehr)
  Offen  = noch keins von beiden (R zum aktuellen Kurs)
Erreicht eine Kerze beides, zählt vorsichtshalber der Stopp.
Zusätzlich: Übernacht-Ergebnis (Einstieg am Abend -> Eröffnung am nächsten Handelstag).

1 R = Abstand Einstieg bis Stopp. +2 R heißt: doppelt so viel gewonnen wie riskiert.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import pandas as pd

ENTRY = ("In Zone", "In Zone (unten)", "Nachkaufbereich")


def ziel_ueber(v: dict, kurs: float):
    z = v.get("ziele") or {}
    for k in ("t1", "t2", "t3"):
        if z.get(k) is not None and z[k] > kurs * 1.01:
            return float(z[k])
    return None


def crv(v: dict, kurs: float):
    stop = (v.get("zone") or {}).get("invalidierung")
    ziel = ziel_ueber(v, kurs)
    if stop is None or ziel is None or stop >= kurs:
        return None
    return round((ziel / kurs - 1) / (1 - stop / kurs), 2)


def _neuer_trade(r: dict, v: dict, horizont: str, datum: str, kurs: float, empfohlen: bool, nachgetragen=False):
    stop = (v.get("zone") or {}).get("invalidierung")
    ziel = ziel_ueber(v, kurs)
    if stop is None or ziel is None or not (stop < kurs < ziel):
        return None
    return {
        "id": f"{r['symbol']}|{horizont}|{datum}", "symbol": r["symbol"], "name": r["name"],
        "currency": r.get("currency", ""), "horizont": horizont, "datum": datum, "status_signal": v.get("status"),
        "einstieg": round(kurs, 4), "stop": round(float(stop), 4), "ziel": round(ziel, 4),
        "crv": round((ziel / kurs - 1) / (1 - stop / kurs), 2),
        "score": (r.get("check") or {}).get("score"), "empfohlen": empfohlen,
        "marktfilter": bool((r.get("markt_filter") or {}).get("blockiert")) if horizont == "lang" else False,
        "nachgetragen": nachgetragen, "ergebnis": "offen", "ende": None, "tage": 0,
        "r": 0.0, "rendite_pct": 0.0, "uebernacht_pct": None, "letzter_kurs": round(kurs, 4),
    }


def _bewerten(t: dict, df: pd.DataFrame):
    if t["ergebnis"] != "offen" or df is None or df.empty:
        return
    e, s, z = t["einstieg"], t["stop"], t["ziel"]
    risk = e - s
    nach = df[df.index > pd.Timestamp(t["datum"])].dropna(subset=["Open", "High", "Low", "Close"])
    if not len(nach):
        return
    if t["uebernacht_pct"] is None and nach["Open"].iloc[0] > 0:
        t["uebernacht_pct"] = round((float(nach["Open"].iloc[0]) / e - 1) * 100, 2)
    for i, (d, row) in enumerate(nach.iterrows()):
        o, h, lo = float(row["Open"]), float(row["High"]), float(row["Low"])
        if lo <= s:
            aus = min(o, s) if o > 0 else s     # Kurslücke unter den Stopp -> Ausstieg zur Eröffnung
            t.update(ergebnis="stopp", ende=d.strftime("%Y-%m-%d"), tage=i + 1, letzter_kurs=round(aus, 4))
            t["r"] = round((aus - e) / risk, 2)
            t["rendite_pct"] = round((aus / e - 1) * 100, 2)
            return
        if h >= z:
            aus = max(o, z) if o > 0 else z
            t.update(ergebnis="ziel", ende=d.strftime("%Y-%m-%d"), tage=i + 1, letzter_kurs=round(aus, 4))
            t["r"] = round((aus - e) / risk, 2)
            t["rendite_pct"] = round((aus / e - 1) * 100, 2)
            return
    last = float(nach["Close"].iloc[-1])
    t.update(tage=len(nach), letzter_kurs=round(last, 4))
    t["r"] = round((last - e) / risk, 2)
    t["rendite_pct"] = round((last / e - 1) * 100, 2)


def _statistik(ts: list[dict]) -> dict:
    zu = [t for t in ts if t["ergebnis"] != "offen"]
    z = sum(t["ergebnis"] == "ziel" for t in zu)
    s = sum(t["ergebnis"] == "stopp" for t in zu)
    gew = sum(t["r"] for t in zu if t["r"] > 0)
    verl = -sum(t["r"] for t in zu if t["r"] < 0)
    un = [t["uebernacht_pct"] for t in ts if t.get("uebernacht_pct") is not None]
    offen = [t for t in ts if t["ergebnis"] == "offen"]
    return {
        "signale": len(ts), "offen": len(offen), "ziel": z, "stopp": s,
        "quote_pct": round(z / (z + s) * 100) if (z + s) else None,
        "r_schnitt": round(sum(t["r"] for t in zu) / len(zu), 2) if zu else None,
        "r_summe": round(sum(t["r"] for t in zu), 2) if zu else 0.0,
        "r_offen": round(sum(t["r"] for t in offen), 2) if offen else 0.0,
        "profitfaktor": round(gew / verl, 2) if verl > 0 else (None if not zu else 99.0),
        "bester_r": max((t["r"] for t in zu), default=None),
        "schlechtester_r": min((t["r"] for t in zu), default=None),
        "uebernacht_n": len(un),
        "uebernacht_pos_pct": round(sum(u > 0 for u in un) / len(un) * 100) if un else None,
        "uebernacht_schnitt_pct": round(sum(un) / len(un), 2) if un else None,
    }


def aktualisieren(pfad: Path, results: list[dict], kurse: dict, empfohlen: set[str], historie: Path | None = None) -> dict:
    """Neue Signale aufnehmen, offene Trades bewerten, Statistik schreiben. kurse = {symbol: Tages-DataFrame}."""
    j = None
    if pfad.exists():
        try:
            j = json.loads(pfad.read_text(encoding="utf-8"))
        except Exception:
            j = None
    erstlauf = j is None
    if erstlauf:
        stand0 = max((r["stand"] for r in results), default=None)
        j = {"start": stand0, "zustand": {}, "trades": []}
    by_sym = {r["symbol"]: r for r in results}
    offen_ids = {(t["symbol"], t["horizont"]) for t in j["trades"] if t["ergebnis"] == "offen"}

    if erstlauf and historie is not None and historie.exists():
        # Signale der letzten Tage aus der Signalhistorie nachtragen (Zone/Ziel vom heutigen Stand)
        try:
            with open(historie, newline="", encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))
            for row in rows:
                r = by_sym.get(row["symbol"])
                if not r or row["status_neu"] not in ENTRY or row["status_alt"] in ENTRY or not row["status_alt"]:
                    continue
                if (r["symbol"], "lang") in offen_ids:
                    continue
                t = _neuer_trade(r, r, "lang", row["datum"], float(row["kurs"]), False, nachgetragen=True)
                if t:
                    j["trades"].append(t)
                    offen_ids.add((r["symbol"], "lang"))
            if j["trades"]:
                j["start"] = min(t["datum"] for t in j["trades"])
        except Exception as e:
            print(f"Live-Bilanz: Historie nicht nachtragbar ({e})")

    for r in results:
        z = j["zustand"].setdefault(r["symbol"], {})
        for hz, v in (("lang", r), ("kurz", r.get("kurz"))):
            if not v:
                continue
            alt, neu = z.get(hz), v.get("status")
            z[hz] = neu
            if erstlauf or alt is None:
                continue  # beim ersten Lauf nur den Zustand merken
            if neu in ENTRY and alt not in ENTRY and (r["symbol"], hz) not in offen_ids:
                t = _neuer_trade(r, v, hz, r["stand"], float(r["kurs"]), r["symbol"] in empfohlen and hz == "lang")
                if t and not any(x["id"] == t["id"] for x in j["trades"]):
                    j["trades"].append(t)
                    offen_ids.add((r["symbol"], hz))

    for t in j["trades"]:
        try:
            _bewerten(t, kurse.get(t["symbol"]))
        except Exception as e:
            print(f"Live-Bilanz: {t['id']} nicht bewertbar ({e})")

    ts = j["trades"]
    j["statistik"] = {
        "alle": _statistik(ts),
        "lang": _statistik([t for t in ts if t["horizont"] == "lang"]),
        "kurz": _statistik([t for t in ts if t["horizont"] == "kurz"]),
        "empfohlen": _statistik([t for t in ts if t.get("empfohlen")]),
    }
    pfad.write_text(json.dumps(j, ensure_ascii=False), encoding="utf-8")
    return j
