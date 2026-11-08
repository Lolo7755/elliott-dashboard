"""Abendkommentar: ein paar Sätze, was heute passiert ist – regelbasiert aus den Tagesdaten."""
from __future__ import annotations


def _p(x, d: int = 1) -> str:
    return ("+" if x >= 0 else "−") + f"{abs(x):.{d}f}".replace(".", ",") + " %"


def abendkommentar(markt: dict | None, results: list[dict], lage: dict | None, empf: list[str],
                   n_kauf: int, n_verkauf: int) -> dict:
    markt = markt or {}
    idx = {i["symbol"]: i for i in markt.get("indizes") or []}
    saetze = []

    us = [idx[s]["tag_pct"] for s in ("^GSPC", "^NDX") if s in idx]
    if us:
        m = sum(us) / len(us)
        ton = ("Starker Tag an der Wall Street" if m >= 1 else "Freundlicher Handel in New York" if m >= 0.3
               else "Schwacher Tag an der Wall Street" if m <= -1 else "Leichte Verluste in New York" if m <= -0.3
               else "Ruhiger Handel in New York")
        teile = [f"{idx[s]['name']} {_p(idx[s]['tag_pct'])}" for s in ("^GSPC", "^NDX", "^GDAXI") if s in idx]
        titel = f"{ton}: " + ", ".join(teile)
    else:
        titel = "Tagesrückblick"

    sek = [s for s in markt.get("sektoren") or [] if s.get("tag") is not None]
    if len(sek) >= 2:
        sek.sort(key=lambda s: s["tag"])
        saetze.append(f"Stärkster Sektor war {sek[-1]['name']} ({_p(sek[-1]['tag'])}), am schwächsten lief {sek[0]['name']} ({_p(sek[0]['tag'])}).")

    bew = sorted((r for r in results if (r.get("perf") or {}).get("tag") is not None), key=lambda r: r["perf"]["tag"])
    if bew:
        hoch = [r for r in bew[::-1][:2] if r["perf"]["tag"] >= 3]
        tief = [r for r in bew[:2] if r["perf"]["tag"] <= -3]
        if hoch:
            saetze.append("In der Watchlist legten " + " und ".join(f"{r['name']} ({_p(r['perf']['tag'])})" for r in hoch) + " am stärksten zu.")
        if tief:
            saetze.append(("Deutlich abwärts ging es für " if hoch else "In der Watchlist ging es deutlich abwärts für ")
                          + " und ".join(f"{r['name']} ({_p(r['perf']['tag'])})" for r in tief) + ".")

    st = markt.get("stimmung")
    if st:
        vt = f", am Vortag {st['vortag']}" if st.get("vortag") is not None else ""
        saetze.append(f"Die Stimmung steht bei {st['wert']} ({st['label']}{vt}).")
    if lage:
        saetze.append(f"Marktlage: {lage.get('label', '')}.")

    mak = {m["symbol"]: m for m in markt.get("makro") or []}
    auff = [f"{mak[s]['name']} {_p(mak[s]['tag_pct'])}" for s in ("^TNX", "BZ=F", "GC=F", "BTC-USD")
            if s in mak and abs(mak[s]["tag_pct"]) >= 2]
    if auff:
        saetze.append("Auffällig bei Zinsen und Rohstoffen: " + ", ".join(auff) + ".")

    if n_kauf or n_verkauf:
        saetze.append(f"Heute gibt es {n_kauf} {'neues Kaufsignal' if n_kauf == 1 else 'neue Kaufsignale'} und "
                      f"{n_verkauf} {'Verkaufssignal' if n_verkauf == 1 else 'Verkaufssignale'}"
                      + (f"; empfohlen für heute Abend: {', '.join(empf)}." if empf else "."))
    elif empf:
        saetze.append(f"Keine neuen Signale. Beste Kandidaten im Kaufbereich: {', '.join(empf)}.")
    else:
        saetze.append("Keine neuen Signale – bestehende Positionen halten.")
    return {"titel": titel, "text": " ".join(saetze)}
