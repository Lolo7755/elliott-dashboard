"""Erzeugt docs/data.json mit synthetischen Demo-Werten (für die Vorschau vor dem ersten echten Lauf)."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analyzer.elliott import analyze  # noqa: E402
from tests.test_synthetic import GOOGL, path_through  # noqa: E402

BASE = [("2016-11-01", 20.0), ("2019-01-02", 30.0), ("2020-03-20", 18.0), ("2021-06-01", 45.0),
        ("2022-10-14", 22.0), ("2023-08-01", 40.0), ("2023-10-27", 33.0), ("2024-07-15", 60.0),
        ("2024-09-06", 48.0), ("2025-07-10", 85.0), ("2025-09-01", 74.0), ("2026-03-02", 100.0)]

SZENARIEN = {
    "DEMO-ZUL": ("Demo: zulaufend", BASE + [("2026-06-15", 82.0), ("2026-08-01", 92.0), ("2026-10-29", 86.0)]),
    "DEMO-W5": ("Demo: Welle 5 läuft", BASE + [("2026-06-15", 66.0), ("2026-10-29", 88.0)]),
    "DEMO-INV": ("Demo: invalidiert", BASE + [("2026-06-15", 50.0), ("2026-08-01", 58.0), ("2026-10-29", 32.0)]),
    "DEMO-Z1": ("Demo: Ziel 1 erreicht", BASE + [("2026-06-15", 68.0), ("2026-10-29", 99.0)]),
    "DEMO-NK": ("Demo: Nachkaufbereich", BASE + [("2026-06-15", 79.0), ("2026-07-20", 85.0), ("2026-10-29", 49.0)]),
}

out = [analyze(path_through(GOOGL), "GOOGL", "Alphabet (Demo)", "USD")]
for sym, (name, pts) in SZENARIEN.items():
    out.append(analyze(path_through(pts, seed=hash(sym) % 1000), sym, name, "EUR"))
for a in out:
    a["kommentar"] = None
    a["signal_vorher"] = a["status_vorher"] = None
out[0]["kommentar"] = ("Deckt sich mit HKCM (Analyse 22.10.2026): Korrektur als Welle [4] in die Zone 284,36–245,98 $, "
                       "danach neue Hochs über 408,61 $ erwartet. Alternativen laut HKCM: Korrektur schon beendet (35 %) "
                       "oder Abwärtstrend unter 256 $ (30 %).")
for a in out:
    print(f"{a['symbol']:9s} {a['status']:30s} {a['signal']}")
(Path(__file__).resolve().parents[1] / "docs" / "data.json").write_text(
    json.dumps({"erstellt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "demo": True,
                "aktien": out, "fehler": []}, ensure_ascii=False), encoding="utf-8")
