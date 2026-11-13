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


# ---------- Verlauf: welche Aufgaben an welchem Tag anstanden ----------
def _eintrag(a: dict, r: dict | None, kurs=None, nachgetragen=False) -> dict:
    e = {k: a.get(k) for k in ("symbol", "typ", "tranche", "stufe", "blockiert", "status", "status_vorher")}
    e.update(name=(r or {}).get("name", a["symbol"]), currency=(r or {}).get("currency", ""),
             kurs=round(float(kurs if kurs is not None else (r or {}).get("kurs") or 0), 4))
    if r and r.get("zone"):
        e["stopp"] = r["zone"].get("invalidierung")
    if nachgetragen:
        e["nachgetragen"] = True
    return {k: v for k, v in e.items() if v is not None}


def verlauf(pfad: Path, aufgaben: list[dict] | None, results: list[dict], empfehlungen: list[str],
            historie: Path) -> None:
    """Schreibt docs/aufgaben_historie.json – pro Börsentag die damaligen Aufgaben (auch leere Tage)."""
    if aufgaben is None:
        return
    by = {r["symbol"]: r for r in results}
    try:
        j = json.loads(pfad.read_text(encoding="utf-8")) if pfad.exists() else None
    except Exception:
        j = None
    if j is None:
        j = {"tage": {}}
        # Erstbefüllung: Signalhistorie mit derselben Logik nachspielen
        from collections import Counter
        erster = (Counter(r["stand"] for r in results).most_common(1) or [("9999", 0)])[0][0]
        if historie.exists():
            with open(historie, newline="", encoding="utf-8") as fh:
                rows = sorted(csv.DictReader(fh), key=lambda x: x["datum"])
            zust = {}
            for row in rows:
                if row["datum"] >= erster:
                    continue
                z0 = zust.get(row["symbol"])
                z, a = _schritt(z0 or _leer(), row["status_neu"])
                zust[row["symbol"]] = z
                j["tage"].setdefault(row["datum"], [])
                if a and z0 is not None and row.get("status_alt"):
                    a.update(symbol=row["symbol"], status=row["status_neu"], status_vorher=row["status_alt"])
                    j["tage"][row["datum"]].append(_eintrag(a, by.get(row["symbol"]), float(row["kurs"]), True))
            # Börsentage ohne Statuswechsel = nichts zu tun (als leere Tage eintragen)
            if j["tage"]:
                import pandas as pd
                for d in pd.bdate_range(min(j["tage"]), erster, inclusive="left"):
                    j["tage"].setdefault(d.strftime("%Y-%m-%d"), [])
    # Haupt-Börsentag dieses Laufs (häufigstes Datum) bekommt immer einen Eintrag, auch wenn er leer ist
    from collections import Counter  # noqa: F811
    tage_lauf = Counter(r["stand"] for r in results)
    haupt = tage_lauf.most_common(1)[0][0] if tage_lauf else None
    neu = {}
    for a in aufgaben:
        e = _eintrag(a, by.get(a["symbol"]))
        if a["symbol"] in empfehlungen and a["typ"] == "kauf":
            e["empfohlen"] = True
        neu.setdefault(a["datum"], []).append(e)
    if haupt:
        neu.setdefault(haupt, [])
    for d, xs in neu.items():
        j["tage"][d] = xs  # gleicher Tag erneut berechnet -> ersetzen (idempotent)
    j["tage"] = dict(sorted(j["tage"].items()))
    pfad.write_text(json.dumps(j, ensure_ascii=False), encoding="utf-8")
