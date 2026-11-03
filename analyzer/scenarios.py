"""
Haupt- und Alternativszenario je Aktie, inkl. schematischem Kurspfad für den Chart.

Wahrscheinlichkeiten stammen aus dem Backtest (keine Bauchzahlen):
  - "zone_erfolg": wie oft ein Zonen-Einstieg zum Treffer wurde (alle Aktien),
    pro Aktie mit der eigenen Quote gemischt (bei wenigen Signalen zählt der Durchschnitt mehr)
  - "zulauf_zone": wie oft eine laufende Korrektur tatsächlich die Zone erreicht hat,
    bevor die Aktie ein neues Hoch machte
Für Aktien im Abwärtstrend gibt es keine Backtest-Basis -> keine Prozentzahl.
"""
from __future__ import annotations

from datetime import date, timedelta

ZONE = ("In Zone", "In Zone (unten)", "Nachkaufbereich")
UP = ("Welle 5 läuft", "Ziel 1 erreicht", "Ziel 2 erreicht")
SHRINK = 10  # Gewicht des Gesamtdurchschnitts (in "Signalen")


def _mix(t: int, f: int, base: float | None) -> float | None:
    if base is None:
        return None if t + f == 0 else t / (t + f)
    return (t + SHRINK * base) / (t + f + SHRINK)


def de(x: float) -> str:
    """Zahl im deutschen Format, z. B. 1.234,56"""
    return f"{float(x):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _weeks(d1: str, d2: str) -> int:
    return max(1, (date.fromisoformat(d2) - date.fromisoformat(d1)).days // 7)


def build(res: dict, rates: dict) -> dict | None:
    if not res.get("chart"):
        return None
    t0 = date.fromisoformat(res["chart"][-1]["time"])
    k = float(res["kurs"])
    z, ziel, w = res["zone"], res["ziele"], res["welle"]
    zmid = (z["oben"] + z["unten"]) / 2
    up_w = min(52, max(6, _weeks(w["start"]["date"], w["hoch"]["date"]) // 2))
    since_high = _weeks(w["hoch"]["date"], t0.isoformat())
    corr_w = min(26, max(3, since_high // 2))
    bt = res.get("backtest") or {}

    def p(*pts):
        out, acc = [{"time": t0.isoformat(), "value": round(k, 2)}], 0
        for weeks, val in pts:
            acc += max(1, int(weeks))
            out.append({"time": (t0 + timedelta(weeks=acc)).isoformat(), "value": round(float(val), 2)})
        return out

    st = res["status"]
    if st in ZONE or st in UP:
        prob = _mix(bt.get("treffer", 0), bt.get("fehler", 0), rates.get("zone_erfolg"))
        if st in ZONE:
            haupt = ("Boden in der Zone, Anstieg zum alten Hoch",
                     f"Die Zone hält, danach Anstieg Richtung {de(ziel['t1'])} (altes Hoch) und {de(ziel['t2'])}.",
                     p((up_w, ziel["t1"]), (up_w // 2, ziel["t2"])))
            alt = ("Zone hält nicht",
                   f"Rutscht der Kurs unter {de(z['invalidierung'])}, ist das Szenario invalidiert – weiterer Abverkauf.",
                   p((6, z["invalidierung"]), (6, z["invalidierung"] * 0.9)))
        else:
            nxt = [(up_w // 2, ziel["t2"]), (up_w // 2, ziel["t3"])] if k < ziel["t2"] else [(up_w // 2, ziel["t3"])]
            haupt = ("Aufwärtswelle läuft weiter",
                     f"Weiter Richtung {de(ziel['t2'])} bzw. {de(ziel['t3'])} – dort Teilverkäufe.",
                     p(*nxt))
            alt = ("Rücksetzer in die Zone",
                   f"Neuer Rücksetzer bis in die Zone um {de(zmid)}, bevor es weiter aufwärts geht.",
                   p((8, zmid)))
    elif st == "Abwärtstrend":
        trig = res.get("einstiegs_trigger") or ziel["t1"]
        haupt = ("Abwärtstrend hält an",
                 f"Bodenbildung unter {de(trig)}; erst ein Ausbruch darüber ändert das Bild.",
                 p((8, k * 0.93), (8, k * 0.97)))
        alt = ("Ausbruch über das Zwischenhoch",
               f"Steigt der Kurs über {de(trig)}, beginnt möglicherweise ein neuer Aufwärtszyklus.",
               p((8, trig), (8, trig * 1.12)))
        prob = None
    else:  # Zulaufend, Neues Hoch, Korrektur evtl. beendet
        base = rates.get("zulauf_zone")
        prob = base
        haupt = ("Korrektur läuft bis in die Zone",
                 f"Der Kurs fällt noch in die Zone {de(z['oben'])}–{de(z['unten'])}; dort Teilkäufe, danach Anstieg zum Hoch {de(ziel['t1'])}.",
                 p((corr_w, zmid), (up_w, ziel["t1"])))
        alt = ("Korrektur ist schon beendet",
               f"Die Aktie steigt ohne Zone direkt Richtung {de(ziel['t1'])} – Einstieg dann nur mit kleiner Position.",
               p((max(4, int(up_w * 0.7)), ziel["t1"])))
        if st == "Alternativ: Korrektur beendet" and prob is not None:
            prob = max(prob - 0.15, 0.3)  # die Erholung spricht schon etwas für die Alternative

    if prob is not None and prob < 0.5:  # Hauptszenario = das wahrscheinlichere
        haupt, alt, prob = alt, haupt, 1 - prob
    pct = None if prob is None else round(prob * 100)
    return {
        "haupt": {"name": haupt[0], "text": haupt[1],
                  "prob_pct": pct, "pfad": haupt[2]},
        "alternative": {"name": alt[0], "text": alt[1], "prob_pct": None if pct is None else 100 - pct, "pfad": alt[2]},
        "basis": "Backtest" if pct is not None else "keine Backtest-Basis",
    }
