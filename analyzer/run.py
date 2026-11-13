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

import copy
import csv
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from analyzer.analysts import fetch_analysts
from analyzer.backtest import backtest
from analyzer.elliott import analyze
from analyzer.extras import fetch_meta, fetch_news, fetch_quartale, fetch_termine
from analyzer.market import fetch_market
from analyzer.scenarios import build as build_scenarios
from analyzer.score import entscheidungscheck
from analyzer import marktfilter as MF
from analyzer import journal as J
from analyzer import aufgaben as AUF
from analyzer.kommentar import abendkommentar
from analyzer.statistik import saison, uebernacht


def _perf(close: pd.Series, tage: int):
    if len(close) <= tage:
        return None
    return round((float(close.iloc[-1]) / float(close.iloc[-1 - tage]) - 1) * 100, 2)


def performance(df: pd.DataFrame) -> dict:
    c = df["Close"].dropna()
    vorjahr = c[c.index.year < c.index[-1].year]
    return {"tag": _perf(c, 1), "woche": _perf(c, 5), "monat": _perf(c, 21), "jahr": _perf(c, 252),
            "ytd": round((float(c.iloc[-1]) / float(vorjahr.iloc[-1]) - 1) * 100, 2) if len(vorjahr) else None}


def datei(sym: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "_", sym) + ".json"

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
    # Yahoo liefert bei langen Zeiträumen den letzten Handelstag manchmal verspätet.
    # Darum die letzten Tage separat holen und anhängen (neuere Werte gewinnen).
    try:
        neu = t.history(period="5d", interval="1d", auto_adjust=False)
        if neu is not None and not neu.empty:
            df = pd.concat([df, neu])
    except Exception:
        pass
    df.index = pd.DatetimeIndex(df.index).tz_localize(None).normalize()
    df = df[~df.index.duplicated(keep="last")].sort_index()
    try:
        cur = t.fast_info.get("currency") or ""
    except Exception:
        cur = ""
    return df[["Open", "High", "Low", "Close"]], cur, t


SCHNELL = os.environ.get("BACKTEST_MODUS", "voll") == "schnell"


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

    try:
        mkt = MF.lade_markt()
    except Exception as e:
        mkt = None
        print(f"Marktfilter: keine Marktdaten ({e})", file=sys.stderr)
    closes_rs = {}
    kurse = {}

    t_start = time.time()
    print(f"Modus: {'schnell (Backtest vom Vortag)' if SCHNELL else 'voll'}")
    results, errors = [], []
    for item in load_watchlist():
        sym = item["symbol"]
        try:
            df, cur, ticker = fetch(sym)
            kurse[sym] = df
            res = analyze(df, sym, item["name"], cur, alt=True)
            try:
                res["kurz"] = analyze(df, sym, item["name"], cur, horizon="kurz", alt=True)
            except Exception as e:
                res["kurz"] = None
                print(f"     {sym}: Kurzfrist-Fehler {e}", file=sys.stderr)
            res["perf"] = performance(df)
            try:
                res["uebernacht"] = uebernacht(df)
                res["saison"] = saison(df["Close"])
            except Exception as e:
                res["uebernacht"], res["saison"] = None, None
                print(f"     {sym}: Statistik-Fehler {e}", file=sys.stderr)
            closes_rs[sym] = MF.rs20(mkt, sym, df["Close"].dropna())
            res["datei"] = datei(sym)
            res["quartale"] = fetch_quartale(ticker)
            res["analysten"] = fetch_analysts(ticker, res["kurs"])
            res["meta"] = fetch_meta(ticker)
            res["termine"] = fetch_termine(ticker)
            res["news"] = fetch_news(ticker, name=item["name"])
            try:
                alt_bt = None
                if SCHNELL and (DOCS / "aktien" / datei(sym)).exists():
                    # Schnell-Lauf: Backtest vom letzten Voll-Lauf übernehmen (ändert sich von Tag zu Tag kaum)
                    alt_bt = json.loads((DOCS / "aktien" / datei(sym)).read_text(encoding="utf-8")).get("backtest")
                res["backtest"] = alt_bt if alt_bt and "signale" in alt_bt else backtest(df, sym, mkt)
            except Exception as e:
                res["backtest"] = None
                print(f"     {sym}: Backtest-Fehler {e}", file=sys.stderr)
            res["kommentar"] = kommentare.get(sym)
            prev = old.get(sym)
            if prev and prev.get("stand") == res["stand"]:
                # erneuter Lauf am selben Börsentag: weiterhin gegen den Vortag vergleichen,
                # damit die Tagesaufgaben bei manuellen Zusatzläufen nicht verschwinden
                res["status_vorher"], res["signal_vorher"] = prev.get("status_vorher"), prev.get("signal_vorher")
            else:
                res["status_vorher"] = prev["status"] if prev else None
                res["signal_vorher"] = prev["signal"] if prev else None
            res["status_letzter_lauf"] = prev["status"] if prev else None
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
    vt = sum((((r.get("backtest") or {}).get("verkauf") or {}).get("treffer", 0)) for r in results)
    vf = sum((((r.get("backtest") or {}).get("verkauf") or {}).get("fehler", 0)) for r in results)
    ah = sum((((r.get("backtest") or {}).get("abwaerts") or {}).get("haelt", 0)) for r in results)
    aa = sum((((r.get("backtest") or {}).get("abwaerts") or {}).get("ausbruch", 0)) for r in results)
    rates = {"zone_erfolg": t / (t + f) if (t + f) else None, "zulauf_zone": zz / (zz + zd) if (zz + zd) else None,
             "verkauf_erfolg": vt / (vt + vf) if (vt + vf) else None,
             "abwaerts_haelt": ah / (ah + aa) if (ah + aa) else None}
    gesamt["abwaerts_haelt_pct"] = round(rates["abwaerts_haelt"] * 100) if rates["abwaerts_haelt"] is not None else None
    gesamt["verkauf"] = {"treffer": vt, "fehler": vf, "quote_pct": round(vt / (vt + vf) * 100) if (vt + vf) else None}
    gesamt["zulauf_zone_pct"] = round(rates["zulauf_zone"] * 100) if rates["zulauf_zone"] is not None else None
    for r in results:
        try:
            r["szenarien"] = build_scenarios(r, rates)
            if r.get("kurz"):
                r["kurz"]["szenarien"] = build_scenarios(r["kurz"], rates)
        except Exception as e:
            r["szenarien"] = None
            print(f"     {r['symbol']}: Szenario-Fehler {e}", file=sys.stderr)

    try:
        markt = fetch_market(results, old_markt.get("stimmung"))
    except Exception as e:
        markt = None
        print(f"Markt-Fehler {e}", file=sys.stderr)

    # Marktfilter: Lage heute + Backtest-Auswertung je Marktlage, dann Kaufsignale anpassen
    mf_test = MF.auswerten(results)
    mf_lage = MF.lage_heute(mkt)
    for r in results:
        try:
            MF.anwenden(r, mf_lage, mf_test, closes_rs.get(r["symbol"]))
        except Exception as e:
            print(f"     {r['symbol']}: Marktfilter-Fehler {e}", file=sys.stderr)
    marktfilter = {"lage": mf_lage, **mf_test,
                   "regeln": {"min_signale": MF.MIN_N, "min_abstand_pp": MF.MIN_ABSTAND,
                              "rs_grenze_pp": round(MF.RS_GRENZE * 100)}}
    print("Marktfilter:", json.dumps(marktfilter, ensure_ascii=False))

    for r in results:
        try:
            r["check"] = entscheidungscheck(r)
        except Exception as e:
            r["check"] = None
            print(f"     {r['symbol']}: Score-Fehler {e}", file=sys.stderr)

    # Chance/Risiko und Erwartungswert (Trefferquote dieser Aktie, zur Gesamtquote hin gemittelt)
    p0 = (gesamt["quote_pct"] or 55) / 100
    for r in results:
        r["crv"] = J.crv(r, r["kurs"])
        bt = r.get("backtest") or {}
        t_, f_ = bt.get("treffer", 0), bt.get("fehler", 0)
        p = (t_ + 10 * p0) / (t_ + f_ + 10)
        r["ev"] = round(p * r["crv"] - (1 - p), 2) if r["crv"] is not None else None
        r["ev_p_pct"] = round(p * 100)

    # Tagesaufgaben mit Gedächtnis: jeder Teilkauf/Teilverkauf kommt pro Zyklus nur einmal
    try:
        aufgaben = AUF.aktualisieren(DOCS / "aufgaben_zustand.json", results, DOCS / "signal_historie.csv")
    except Exception as e:
        aufgaben = None
        print(f"Aufgaben-Fehler {e}", file=sys.stderr)
    kauf_heute = {a["symbol"] for a in (aufgaben or []) if a["typ"] == "kauf" and not a.get("blockiert")}
    print(f"Aufgaben heute: {len(aufgaben or [])} ({len(kauf_heute)} Käufe)")

    # Top-Empfehlungen: nur unter den heutigen neuen Kaufaufgaben, ergänzt um den Erwartungswert
    def _kat(r):
        sg = (r.get("signal") or "").lower()
        if r["status"] == "Abwärtstrend":
            return "rot"
        return "kauf" if sg.startswith(("teilkauf", "letzter nachkauf", "kleine position")) else "andere"
    kand = []
    for r in results:
        sc = (r.get("check") or {}).get("score")
        if aufgaben is not None and r["symbol"] not in kauf_heute:
            continue
        if _kat(r) != "kauf" or (r.get("markt_filter") or {}).get("blockiert") or sc is None or sc < 55 \
                or r["crv"] is None or r["crv"] < 1 or (r["ev"] is not None and r["ev"] <= 0):
            continue
        neu = bool(r.get("status_vorher")) and r["status"] != r.get("status_vorher")
        ev_bonus = max(-5, min(5, round((r["ev"] or 0) * 5)))
        kand.append((sc + (5 if r["crv"] >= 2 else 0) + (5 if neu else 0) + ev_bonus, r["crv"], r["symbol"]))
    empfehlungen = [x[2] for x in sorted(kand, key=lambda x: (-x[0], -x[1]))[:3]]
    try:
        AUF.verlauf(DOCS / "aufgaben_historie.json", aufgaben, results, empfehlungen, DOCS / "signal_historie.csv")
    except Exception as e:
        print(f"Aufgaben-Verlauf-Fehler {e}", file=sys.stderr)

    # Live-Bilanz: neue Kaufsignale aufnehmen und mit echten Kursen nachhalten
    try:
        lb = J.aktualisieren(DOCS / "live_bilanz.json", results, kurse, set(empfehlungen), DOCS / "signal_historie.csv")
        live_stat = lb.get("statistik")
        print("Live-Bilanz:", json.dumps(live_stat.get("alle"), ensure_ascii=False))
    except Exception as e:
        live_stat = None
        print(f"Live-Bilanz-Fehler {e}", file=sys.stderr)

    # Chancen-Finder außerhalb der Watchlist
    try:
        from analyzer.chancen import suchen
        t_ch = time.time()
        chancen = suchen({r["symbol"] for r in results})
        chancen["dauer_s"] = round(time.time() - t_ch)
        print(f"Chancen-Finder: {chancen['geprueft']} Aktien geprüft, {len(chancen['ruecksetzer'])} Rücksetzer, "
              f"{len(chancen['ausbruch'])} Ausbruch-Kandidaten ({chancen['dauer_s']} s)")
    except Exception as e:
        chancen = None
        print(f"Chancen-Finder-Fehler {e}", file=sys.stderr)

    # Wichtige News: nur Aktien, die sich heute deutlich bewegt haben
    wichtige_news = []
    for r in sorted(results, key=lambda r: -abs((r.get("perf") or {}).get("tag") or 0)):
        tg = (r.get("perf") or {}).get("tag")
        if tg is None or abs(tg) < 4:
            break
        n0 = next((n for n in (r.get("news") or []) if n.get("datum") and n["datum"] >= (pd.Timestamp(r["stand"]) - pd.Timedelta(days=4)).strftime("%Y-%m-%d")), None) \
            or ((r.get("news") or [None])[0])
        wichtige_news.append({"symbol": r["symbol"], "name": r["name"], "tag_pct": tg, "woche_pct": r["perf"].get("woche"),
                              "kurs": r["kurs"], "currency": r.get("currency"), "status": r["status"], "ampel": r["ampel"],
                              "zone": r["zone"], "news": n0, "news_weitere": (r.get("news") or [])[1:3]})
        if len(wichtige_news) >= 15:
            break

    # Detaildatei pro Aktie (Charts, Wellen, News) – data.json bleibt schlank
    (DOCS / "aktien").mkdir(exist_ok=True)
    summary = []
    for r in results:
        (DOCS / "aktien" / r["datei"]).write_text(json.dumps(r, ensure_ascii=False), encoding="utf-8")
        s = copy.deepcopy(r)
        for key in ("chart", "news", "szenarien"):
            s.pop(key, None)
        if s.get("kurz"):
            s["kurz"] = {k: s["kurz"].get(k) for k in ("status", "ampel", "signal", "zone", "ziele")}
        if s.get("backtest"):
            s["backtest"].pop("signale", None)
            (s["backtest"].get("verkauf") or {}).pop("signale", None)
        s["welle"].pop("labels", None)
        s["welle"].pop("alternative", None)
        if s.get("saison"):
            mon = int(r["stand"][5:7])
            s["saison_monat"] = next((x for x in s["saison"] if x["m"] == mon), None)
        s.pop("saison", None)
        summary.append(s)

    # Ausreißer des Tages (ab ±10 %)
    beweg = sorted((r for r in results if (r.get("perf") or {}).get("tag") is not None),
                   key=lambda r: abs(r["perf"]["tag"]), reverse=True)
    ausreisser = [{"symbol": r["symbol"], "name": r["name"], "tag": r["perf"]["tag"], "kurs": r["kurs"],
                   "currency": r["currency"], "status": r["status"], "ampel": r["ampel"]}
                  for r in beweg if abs(r["perf"]["tag"]) >= 10]
    top = [{"symbol": r["symbol"], "name": r["name"], "tag": r["perf"]["tag"]} for r in beweg[:6]]

    def _aufgabe(r, typ):
        kauf = r["status"] in J.ENTRY
        halten = J.ENTRY + ("Welle 5 läuft", "Ziel 1 erreicht", "Ziel 2 erreicht", "Impuls vollendet", "Neues Hoch / Trend läuft")
        verk = r["status"] in ("Impuls vollendet", "Ziel 1 erreicht", "Ziel 2 erreicht") or \
            (r["status"] == "Abwärtstrend" and r.get("status_vorher") in halten)
        return r.get("status_vorher") and r["status"] != r["status_vorher"] and (kauf if typ == "kauf" else verk)
    try:
        if aufgaben is not None:
            n_k, n_v = len(kauf_heute), sum(a["typ"] == "verkauf" for a in aufgaben)
        else:
            n_k = sum(bool(_aufgabe(r, "kauf")) and not (r.get("markt_filter") or {}).get("blockiert") for r in results)
            n_v = sum(bool(_aufgabe(r, "verkauf")) for r in results)
        kommentar = abendkommentar(markt, results, mf_lage, [next(r["name"] for r in results if r["symbol"] == e) for e in empfehlungen], n_k, n_v)
    except Exception as e:
        kommentar = None
        print(f"Kommentar-Fehler {e}", file=sys.stderr)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    (DOCS / "data.json").write_text(
        json.dumps({"erstellt": now, "modus": "schnell" if SCHNELL else "voll", "dauer_s": round(time.time() - t_start), "trefferquote": gesamt, "markt": markt, "ausreisser": ausreisser,
                    "top_bewegungen": top, "marktfilter": marktfilter, "empfehlungen": empfehlungen, "aufgaben": aufgaben, "kommentar": kommentar,
                    "live_bilanz": live_stat, "chancen": chancen, "wichtige_news": wichtige_news,
                    "aktien": summary, "fehler": errors}, ensure_ascii=False),
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
            if r["status"] != r.get("status_letzter_lauf"):
                wr.writerow([r["stand"], r["symbol"], r["kurs"], r.get("status_letzter_lauf") or "", r["status"], r["signal"]])
    print(f"{len(results)} analysiert, {len(errors)} Fehler, Trefferquote gesamt: {gesamt}")
    return 0 if results else 1


if __name__ == "__main__":
    sys.exit(main())
