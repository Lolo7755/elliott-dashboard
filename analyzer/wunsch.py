"""
Aktienwunsch: aus einem freien Namen ("Mercedes", "Novo Nordisk, Palantir") die passende Aktie finden
und in watchlist.csv eintragen. Läuft im Workflow wunsch.yml, ausgelöst durch ein GitHub-Issue
mit dem Titel "Aktienwunsch: ...".

Eingaben kommen über Umgebungsvariablen (WUNSCH_TITEL, WUNSCH_TEXT, WUNSCH_ISSUE).
Ausgabe: watchlist.csv (ergänzt), docs/wuensche.json (Verlauf), wunsch_antwort.md (Kommentar fürs Issue),
wunsch_neu.txt ("ja", wenn etwas hinzugefügt wurde).
"""
from __future__ import annotations

import csv
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import yfinance as yf

ROOT = Path(__file__).resolve().parent.parent
WATCHLIST = ROOT / "watchlist.csv"
WUENSCHE = ROOT / "docs" / "wuensche.json"

# Heimatbörsen in Yahoo-Kürzeln, in der Reihenfolge der Bevorzugung (Xetra vor allem anderen in Europa)
BOERSEN = ["NMS", "NYQ", "NGM", "NCM", "ASE", "GER", "PAR", "LSE", "AMS", "MIL", "MCE", "EBS", "VTX",
           "CPH", "STO", "HEL", "OSL", "BRU", "LIS", "VIE", "WSE", "TYO", "HKG", "KSC", "KOE", "TAI",
           "ASX", "TOR", "NSI", "BSE", "SAO", "JNB", "SES"]
BOERSE_NAME = {"NMS": "Nasdaq", "NGM": "Nasdaq", "NCM": "Nasdaq", "NYQ": "NYSE", "ASE": "NYSE American",
               "GER": "Xetra", "PAR": "Paris", "LSE": "London", "AMS": "Amsterdam", "MIL": "Mailand",
               "MCE": "Madrid", "EBS": "Zürich", "VTX": "Zürich", "CPH": "Kopenhagen", "STO": "Stockholm",
               "HEL": "Helsinki", "OSL": "Oslo", "BRU": "Brüssel", "LIS": "Lissabon", "VIE": "Wien",
               "WSE": "Warschau", "TYO": "Tokio", "HKG": "Hongkong", "KSC": "Seoul", "KOE": "Seoul",
               "TAI": "Taiwan", "ASX": "Sydney", "TOR": "Toronto", "NSI": "Indien", "BSE": "Indien",
               "SAO": "São Paulo", "JNB": "Johannesburg", "SES": "Singapur"}
DEUTSCH = re.compile(r"\b(AG|SE|KGaA|GmbH)\b", re.I)


def namen(titel: str, text: str = "") -> list[str]:
    roh = re.sub(r"^\s*aktienwunsch\s*[:\-–]?\s*", "", titel or "", flags=re.I)
    teile = re.split(r"[,;\n]+", roh + "\n" + (text or ""))
    out = []
    for t in teile:
        t = t.strip().strip("\"'`*-• ").strip()
        if 1 <= len(t) <= 60 and t.lower() not in (n.lower() for n in out):
            out.append(t)
    return out[:10]


def _watchlist() -> list[dict]:
    with open(WATCHLIST, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _kandidaten(q: str) -> list[dict]:
    try:
        quotes = yf.Search(q, max_results=12, news_count=0).quotes or []
    except Exception as e:
        print(f"Suche '{q}' fehlgeschlagen: {e}", file=sys.stderr)
        quotes = []
    return [x for x in quotes if x.get("quoteType") == "EQUITY" and x.get("exchange") in BOERSEN and x.get("symbol")]


def waehlen(quotes: list[dict]) -> dict | None:
    """Relevantester Treffer; bei deutschen Gesellschaften die Xetra-Notiz statt ADR/Auslandsnotiz."""
    if not quotes:
        return None
    erster = quotes[0]
    name = erster.get("longname") or erster.get("shortname") or ""
    kern = re.sub(r"[^a-z]", "", name.lower())[:6]
    if DEUTSCH.search(name) and erster.get("exchange") != "GER":
        for x in quotes:
            n2 = re.sub(r"[^a-z]", "", (x.get("longname") or x.get("shortname") or "").lower())[:6]
            if x.get("exchange") == "GER" and kern and n2 == kern:
                return x
    return erster


def _ist_ticker(q: str) -> bool:
    return bool(re.fullmatch(r"[A-Z0-9]{1,6}([.\-][A-Z]{1,3})?", q))


def _pruefen(sym: str) -> tuple[int, str | None, str | None]:
    """Anzahl Handelstage (2 Jahre) + Name + Währung."""
    try:
        t = yf.Ticker(sym)
        h = t.history(period="2y", auto_adjust=True)
        n = int(h["Close"].dropna().shape[0]) if h is not None and not h.empty else 0
        info = {}
        try:
            info = t.info or {}
        except Exception:
            pass
        return n, info.get("longName") or info.get("shortName"), info.get("currency")
    except Exception as e:
        print(f"Prüfung {sym} fehlgeschlagen: {e}", file=sys.stderr)
        return 0, None, None


def _kurzname(name: str) -> str:
    name = re.sub(r",?\s+(Inc\.?|Incorporated|Corporation|Corp\.?|Co\.|Ltd\.?|Limited|plc|PLC|N\.V\.|S\.A\.|SA|"
                  r"AG|SE|KGaA|& Co\.? KGaA|Holdings?|Group|Aktiengesellschaft|Class [A-C]|A/S|ASA|AB)\b\.?", "", name)
    return re.sub(r"\s{2,}", " ", name).strip(" ,.-") or name


def bearbeiten(eingaben: list[str], issue: int | None = None) -> list[dict]:
    wl = _watchlist()
    drin = {r["symbol"].upper(): r["name"] for r in wl}
    jetzt = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    ergebnisse, neue = [], []
    for q in eingaben:
        e = {"datum": jetzt, "eingabe": q, "issue": issue}
        if "." in q and _ist_ticker(q.upper()):  # ausdrückliches Börsenkürzel wie MBG.DE
            treffer = {"symbol": q.upper(), "exchange": None, "longname": None}
        else:
            treffer = waehlen(_kandidaten(q))
            if not treffer and _ist_ticker(q.upper()):
                treffer = {"symbol": q.upper(), "exchange": None, "longname": None}
        if not treffer:
            e["status"] = "nicht_gefunden"
            ergebnisse.append(e)
            continue
        sym = treffer["symbol"].upper()
        e.update(symbol=sym, boerse=BOERSE_NAME.get(treffer.get("exchange"), treffer.get("exchange")))
        if sym in drin:
            e.update(status="schon_drin", name=drin[sym])
            ergebnisse.append(e)
            continue
        n, langname, waehrung = _pruefen(sym)
        name = _kurzname(treffer.get("longname") or treffer.get("shortname") or langname or sym)
        e.update(name=name, currency=waehrung)
        if n < 250:
            e["status"] = "zu_wenig_daten" if n else "nicht_gefunden"
            e["tage"] = n
        else:
            e["status"] = "hinzugefuegt"
            drin[sym] = name
            neue.append({"symbol": sym, "name": name})
        ergebnisse.append(e)
    if neue:
        with open(WATCHLIST, "a", newline="", encoding="utf-8") as fh:
            inhalt = WATCHLIST.read_text(encoding="utf-8")
            if inhalt and not inhalt.endswith("\n"):
                fh.write("\n")
            w = csv.writer(fh, lineterminator="\n")
            for x in neue:
                w.writerow([x["symbol"], x["name"]])
    alt = []
    if WUENSCHE.exists():
        try:
            alt = json.loads(WUENSCHE.read_text(encoding="utf-8")).get("wuensche", [])
        except Exception:
            alt = []
    WUENSCHE.write_text(json.dumps({"wuensche": (ergebnisse[::-1] + alt)[:60]}, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    return ergebnisse


def antwort(ergebnisse: list[dict]) -> str:
    z = []
    for e in ergebnisse:
        s, q = e["status"], e["eingabe"]
        if s == "hinzugefuegt":
            z.append(f"✅ **{q}** → {e['name']} (`{e['symbol']}`, {e.get('boerse') or '–'}) wurde zur Watchlist hinzugefügt.")
        elif s == "schon_drin":
            z.append(f"ℹ️ **{q}** → {e['name']} (`{e['symbol']}`) ist schon in der Watchlist.")
        elif s == "zu_wenig_daten":
            z.append(f"⚠️ **{q}** → `{e['symbol']}` hat nur {e.get('tage', 0)} Handelstage – zu wenig für die Wellenanalyse (mind. 250).")
        else:
            z.append(f"❌ **{q}**: keine passende Aktie gefunden. Tipp: genauer schreiben oder das Börsenkürzel angeben (z. B. `MBG.DE`).")
    if any(e["status"] == "hinzugefuegt" for e in ergebnisse):
        z.append("\nDie Analyse startet jetzt automatisch – in ca. 6–8 Minuten ist die Aktie im Dashboard.")
    elif not ergebnisse:
        z.append("Im Titel stand kein Aktienname. Beispiel: `Aktienwunsch: Mercedes`")
    return "\n".join(z)


def main() -> None:
    issue = os.environ.get("WUNSCH_ISSUE")
    ein = namen(os.environ.get("WUNSCH_TITEL", ""), os.environ.get("WUNSCH_TEXT", ""))
    print("Wünsche:", ein)
    erg = bearbeiten(ein, int(issue) if issue and issue.isdigit() else None) if ein else []
    for e in erg:
        print(e)
    (ROOT / "wunsch_antwort.md").write_text(antwort(erg), encoding="utf-8")
    (ROOT / "wunsch_neu.txt").write_text("ja" if any(e["status"] == "hinzugefuegt" for e in erg) else "nein",
                                         encoding="utf-8")


if __name__ == "__main__":
    main()
