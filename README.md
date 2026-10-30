# Elliott-Dashboard

Eigenes, kostenloses Elliott-Wellen-Dashboard im Stil der HKCM-Langfrist-Zonen.

- **Bot** (Python, läuft auf GitHub Actions): lädt Kurse (yfinance), findet Wendepunkte,
  zählt die laufende 5-Wellen-Struktur nach den Elliott-Regeln, berechnet die Fibonacci-Zonen
  und leitet Signale ab (Teilkauf / Nachkauf / Halten / Teilverkauf / Invalidiert).
- **Dashboard** (GitHub Pages): Tabelle mit Ampel, „Handlungsbedarf heute Abend“,
  Detailansicht mit Chart, Zonen, Wellenzählung und Handlungsplan.
- **KI-Schicht** (Claude): Kommentare pro Aktie in `docs/kommentare.json`, Szenario-Gewichtung.

## Einrichtung (einmalig, ca. 10 Minuten)

1. Kostenlosen Account anlegen: https://github.com/signup
2. Neues Repository anlegen: https://github.com/new
   Name z. B. `elliott-dashboard`, **Public** (dann sind Actions unbegrenzt kostenlos), ohne README.
3. Auf der leeren Repo-Seite **„uploading an existing file“** anklicken und den **Inhalt** des
   entpackten Ordners hineinziehen (inkl. der Ordner `analyzer`, `docs`, `tests`, `.github`).
   Tipp: Der Ordner `.github` ist auf dem Mac versteckt – im Finder mit `Cmd + Shift + .` einblenden.
   → „Commit changes“.
4. **Settings → Pages**: Source „Deploy from a branch“, Branch `main`, Ordner `/docs` → Save.
5. **Actions**-Tab öffnen → Workflows erlauben → „Elliott-Analyse“ → **Run workflow**.
   Nach ca. 2 Minuten sind echte Daten da.
6. Dashboard aufrufen: `https://<dein-name>.github.io/elliott-dashboard/`

## Bedienung

- **Aktien hinzufügen/entfernen:** Button „Watchlist bearbeiten“ → `watchlist.csv` ändern
  (Yahoo-Symbole, z. B. `TUI1.DE`, `SAP.DE`, `NFLX`) → Speichern. Die Analyse startet automatisch.
- **Automatik:** Mo–Fr um 22:45 Uhr (nach US-Börsenschluss).
- **Sofort analysieren:** Button „Analyse jetzt starten“ → „Run workflow“.
- **Signal-Historie:** jede Statusänderung wird in `docs/signal_historie.csv` angehängt.

## Logik in Kurzform

| Level | Bedeutung | Aktion |
|---|---|---|
| 38,2 % Retracement | Oberkante Einstiegszone | Teilkauf 1 (≈ 1/3) |
| 50 % | Unterkante Einstiegszone | Teilkauf 2 (≈ 1/3) |
| 61,8 % | Nachkauf | Teilkauf 3 (Rest) |
| 78,6 % | Invalidierung | Szenario gekippt |
| altes Hoch / 127,2 % / 161,8 % | Ziele der nächsten Welle | Teilverkäufe |

Die Hauptwelle wird so gewählt: jüngstes Tief, das (a) bis zum Hoch nicht mehr unterschritten wurde,
(b) eine größere Korrektur abschließt als jede Korrektur danach und (c) eine regelkonforme
5-Wellen-Zählung bis zum Hoch erlaubt. Getestet: reproduziert die HKCM-Zone für Alphabet
(284,36–245,98 $) exakt.

## Lokal testen

```
pip install -r requirements.txt
python tests/test_synthetic.py   # Tests
python -m analyzer.run           # echte Analyse -> docs/data.json
```

Keine Anlageberatung. Mechanische Zählungen können falsch sein; Szenarien können jederzeit kippen.
