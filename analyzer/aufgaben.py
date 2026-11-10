"""
Tagesaufgaben mit Gedächtnis: jede Aufgabe kommt nur einmal.

Pro Aktie wird ein Zyklus mitgeschrieben (docs/aufgaben_zustand.json):
  Kaufen:   Erreicht die Aktie zum ersten Mal eine Kaufstufe, gibt es Teilkauf 1. Jede tiefere
            Stufe, die im selben Zyklus neu erreicht wird, bringt den nächsten Teilkauf (max. 3).
            Pendeln zwischen bereits erreichten Stufen löst nichts mehr aus.
            Stufen: In Zone (1) < In Zone (unten) (2) < Nachkaufbereich (3).
  Verkaufen: Ziel 1 (1) < Ziel 2 (2) < Impuls vollendet (3) – jede Stufe einmal pro Zyklus.
            Abwärtstrend (Invalidierung) = Restposition auflösen, nur wenn im Zyklus gekauft wurde.
  Neuer Zyklus: nach Abwärtstrend oder nach vollendetem Impuls bzw. neuem Hoch.

Der Zustand wird pro Börsentag gespeichert: ein zweiter Lauf am selben Tag liefert dieselben
Aufgaben, am nächsten Börsentag sind sie erledigt und werden ersetzt.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

KAUF = {"In Zone": 1, "In Zone (unten)": 2, "Nachkaufbereich": 3}
VERKAUF = {"Ziel 1 erreicht": 1, "Ziel 2 erreicht": 2, "Impuls vollendet": 3}
ZYKLUS_ENDE = ("Abwärtstrend", "Impuls vollendet", "Neues Hoch / Trend läuft")


def _leer() -> dict:
    return {"status": None, "kauf_stufe": 0, "tranchen": 0, "verkauf_stufe": 0, "aufgeloest": False}


def _schritt(z: dict, status: str, blockiert: bool = False):
    """Wendet den Status eines Börsentags auf den Zyklus an. Gibt (neuer Zustand, Aufgabe|None) zurück."""
    z = dict(z)
    alt = z.get("status")
    aufgabe = None
    if status in KAUF:
        if z.get("aufgeloest"):  # nach Ausstieg beginnt ein neuer Zyklus
            z.update(_leer())
        stufe = KAUF[status]
        if stufe > z["kauf_stufe"]:
            z["kauf_stufe"] = stufe
            if z["tranchen"] < 3:
                if blockiert:
                    aufgabe = {"typ": "kauf", "tranche": z["tranchen"] + 1, "blockiert": True}
                else:
                    z["tranchen"] += 1
                    aufgabe = {"typ": "kauf", "tranche": z["tranchen"], "blockiert": False}
    elif status in VERKAUF:
        stufe = VERKAUF[status]
        if stufe > z["verkauf_stufe"]:
            z["verkauf_stufe"] = stufe
            aufgabe = {"typ": "verkauf", "stufe": stufe}
    elif status == "Abwärtstrend":
        if z["tranchen"] > 0 and not z.get("aufgeloest") and alt != "Abwärtstrend":
            aufgabe = {"typ": "verkauf", "stufe": 4}
    if status in ZYKLUS_ENDE and alt != status:
        z["aufgeloest"] = True
    z["status"] = status
    return z, aufgabe


def _bootstrap(historie: Path, bis: str) -> dict:
    """Zyklen aus der Signalhistorie nachspielen (alles vor dem Datum 'bis')."""
    zust = {}
    if not historie.exists():
        return zust
    with open(historie, newline="", encoding="utf-8") as fh:
        rows = sorted(csv.DictReader(fh), key=lambda r: r["datum"])
    for row in rows:
        if row["datum"] >= bis:
            continue
        z = zust.get(row["symbol"], _leer())
        zust[row["symbol"]], _ = _schritt(z, row["status_neu"])
    return zust


def aktualisieren(pfad: Path, results: list[dict], historie: Path) -> list[dict]:
    """Berechnet die heutigen Aufgaben und schreibt den Zustand. Rückgabe: Aufgabenliste."""
    try:
        j = json.loads(pfad.read_text(encoding="utf-8")) if pfad.exists() else None
    except Exception:
        j = None
    if j is None:
        erster = min((r["stand"] for r in results), default="9999")
        boot = _bootstrap(historie, erster)
        j = {"aktien": {s: {"basis": z, "heute": None} for s, z in boot.items()}}
        # Aktien ohne Historie: gestrigen Status als Ausgangspunkt nehmen (löst keine Aufgabe aus)
        for r in results:
            if r["symbol"] not in j["aktien"] and r.get("status_vorher"):
                z, _ = _schritt(_leer(), r["status_vorher"])
                j["aktien"][r["symbol"]] = {"basis": z, "heute": None}

    aufgaben = []
    for r in results:
        e = j["aktien"].setdefault(r["symbol"], {"basis": None, "heute": None})
        h = e.get("heute")
        if h and h["datum"] != r["stand"]:
            e["basis"] = h["zustand"]  # neuer Börsentag: gestriges Ergebnis wird zur Basis
        basis = e.get("basis")
        if basis is None:
            # ganz neue Aktie: erster Tag wird nur gemerkt, keine Aufgabe
            z, _ = _schritt(_leer(), r["status"])
            e["heute"] = {"datum": r["stand"], "zustand": z, "aufgabe": None}
            continue
        blockiert = bool((r.get("markt_filter") or {}).get("blockiert"))
        z, a = _schritt(basis, r["status"], blockiert)
        if a:
            a.update(symbol=r["symbol"], datum=r["stand"], status=r["status"], status_vorher=basis.get("status"))
            aufgaben.append(a)
        e["heute"] = {"datum": r["stand"], "zustand": z, "aufgabe": a}
    pfad.write_text(json.dumps(j, ensure_ascii=False), encoding="utf-8")
    return aufgaben
