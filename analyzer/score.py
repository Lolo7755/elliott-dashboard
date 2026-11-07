"""
Entscheidungscheck: Score 0–100 pro Aktie mit Argumenten dafür und dagegen.

Punkte (max. 100):
  Elliott langfristig  30   Status der großen Welle (Zone = beste Chance)
  Elliott kurzfristig  10   Status im Tageschart
  Analysten            20   Rating (12) + Kurspotenzial (8)
  Trefferquote         15   Backtest der Zonen-Signale dieser Aktie
  Trend                15   Lage zu 50- und 200-Tage-Linie
  Quartalszahlen       10   Beats der letzten 4 Quartale
"""
from __future__ import annotations

ELLIOTT = {
    "In Zone": 30, "In Zone (unten)": 30, "Nachkaufbereich": 22, "Welle 5 läuft": 22,
    "Zulaufend": 15, "Alternativ: Korrektur beendet": 15, "Neues Hoch / Trend läuft": 12,
    "Ziel 1 erreicht": 8, "Impuls vollendet": 6, "Ziel 2 erreicht": 4, "Abwärtstrend": 0,
}


def _clip(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def entscheidungscheck(r: dict) -> dict:
    pro, contra, teile = [], [], {}

    st = r.get("status")
    p = ELLIOTT.get(st, 12)
    teile["Elliott lang"] = (p, 30)
    if p >= 22:
        pro.append(f"Langfristig: {st} – günstige Einstiegsphase")
    elif p <= 8:
        contra.append(f"Langfristig: {st}")

    k = (r.get("kurz") or {}).get("status")
    pk = round(ELLIOTT.get(k, 12) / 3)
    teile["Elliott kurz"] = (pk, 10)
    if k and pk >= 7:
        pro.append(f"Kurzfristig: {k}")
    elif k and pk <= 2:
        contra.append(f"Kurzfristig: {k}")

    an = r.get("analysten") or {}
    pa = 0
    if an.get("score"):
        pa += round(12 * _clip((5 - an["score"]) / 4))
    pot = an.get("potenzial_pct")
    if pot is not None:
        pa += round(8 * _clip((pot + 5) / 35))
    elif not an.get("score"):
        pa = 10
    teile["Analysten"] = (pa, 20)
    if an.get("rating") in ("Strong Buy", "Buy"):
        pro.append(f"Analysten: {an['rating']}" + (f", Potenzial {pot:+.0f} %".replace(".", ",") if pot is not None else ""))
    elif an.get("rating") in ("Sell", "Strong Sell"):
        contra.append(f"Analysten: {an['rating']}")
    if pot is not None and pot < 0:
        contra.append(f"Kurs liegt über dem Ø-Kursziel ({pot:+.0f} %)".replace(".", ","))

    bt = r.get("backtest") or {}
    q = bt.get("quote_pct")
    pq = 7 if q is None else round(15 * _clip((q - 40) / 40))
    teile["Trefferquote"] = (pq, 15)
    if q is not None and q >= 70 and bt.get("treffer", 0) + bt.get("fehler", 0) >= 3:
        pro.append(f"Elliott-Signale hier zuverlässig ({q} % Treffer)")
    elif q is not None and q < 50:
        contra.append(f"Elliott-Signale hier unzuverlässig ({q} % Treffer)")

    kurs, s50, s200 = r.get("kurs"), r.get("sma50"), r.get("sma200")
    pt = 0
    if kurs and s200:
        pt += 8 if kurs > s200 else 0
        pt += 3 if s50 and kurs > s50 else 0
        pt += 4 if s50 and s50 > s200 else 0
        if kurs > s200 and s50 and s50 > s200:
            pro.append("Intakter Aufwärtstrend (über 50- und 200-Tage-Linie)")
        elif kurs < s200:
            contra.append("Kurs unter der 200-Tage-Linie")
    else:
        pt = 7
    teile["Trend"] = (pt, 15)

    qs = r.get("quartale") or []
    bewertet = [x for x in qs if x.get("beat") is not None]
    if bewertet:
        beats = sum(x["beat"] for x in bewertet)
        pe = round(10 * beats / len(bewertet))
        if beats == len(bewertet):
            pro.append(f"Alle letzten {beats} Quartale über den Erwartungen")
        elif beats <= len(bewertet) / 2:
            contra.append(f"Nur {beats} von {len(bewertet)} Quartalen über den Erwartungen")
    else:
        pe = 5
    teile["Quartale"] = (pe, 10)

    t = (r.get("termine") or {}).get("earnings_in_tagen")
    if t is not None and t <= 7:
        contra.append(f"Quartalszahlen in {t} Tagen – erhöhte Schwankung")

    mf = r.get("markt_filter") or {}
    if mf.get("blockiert") or mf.get("reduziert"):
        contra.insert(0, "Marktfilter: " + (mf.get("hinweise") or ["Marktlage ungünstig"])[0])

    score = int(sum(v[0] for v in teile.values()))
    label = ("Stark" if score >= 75 else "Solide" if score >= 60 else "Neutral" if score >= 45
             else "Schwach" if score >= 30 else "Meiden")
    return {"score": score, "label": label, "pro": pro[:5], "contra": contra[:5],
            "teile": {k2: {"punkte": v[0], "max": v[1]} for k2, v in teile.items()}}
