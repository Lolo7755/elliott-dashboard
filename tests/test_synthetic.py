"""
Tests mit synthetischen Kursverläufen.

1) Google-ähnlicher Verlauf mit den echten Eckpunkten (Tief 03.11.2022 = 83,34 $,
   Allzeithoch 408,61 $). HKCM-Langfrist-Zone laut Analyse vom 22.10.2026:
   284,36 – 245,98 $. Die Engine muss diese Zone exakt reproduzieren.
2) Zufallsverläufe: Engine darf nie abstürzen und muss gültiges JSON liefern.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analyzer.elliott import analyze  # noqa: E402


def path_through(points, noise=0.012, seed=1):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(points[0][0], points[-1][0]).as_unit("ns")
    xi = idx.asi8.astype(float)
    t = np.array([pd.Timestamp(d).as_unit("ns").value for d, _ in points], dtype=float)
    lp = np.log([p for _, p in points])
    base = np.exp(np.interp(xi, t, lp))
    # Rauschen, das an den Eckpunkten auf 0 geht (damit Extreme exakt bleiben)
    dist = np.min(np.abs(xi[:, None] - t[None, :]), axis=1) / (86400e9 * 20)
    damp = np.clip(dist, 0, 1)
    close = base * np.exp(rng.normal(0, noise, len(idx)) * damp)
    high = np.maximum(close, base) * (1 + 0.004 * damp)
    low = np.minimum(close, base) * (1 - 0.004 * damp)
    df = pd.DataFrame({"Open": close, "High": high, "Low": low, "Close": close}, index=idx)
    for d, p in points:  # Eckpunkte exakt setzen
        ts = pd.Timestamp(d)
        if ts in df.index:
            df.loc[ts, ["High", "Low"]] = max(df.loc[ts, "High"], p), min(df.loc[ts, "Low"], p)
    return df


GOOGL = [
    ("2016-11-01", 38.0), ("2018-07-25", 64.0), ("2018-12-24", 49.0),
    ("2020-02-19", 76.0), ("2020-03-23", 52.0), ("2021-11-19", 151.5),
    ("2022-11-03", 83.34), ("2023-07-18", 130.0), ("2023-10-26", 120.0),
    ("2024-07-10", 191.0), ("2024-08-05", 148.0), ("2025-02-04", 207.0),
    ("2025-04-07", 140.53), ("2025-12-03", 330.0), ("2026-04-08", 266.0),
    ("2026-05-20", 408.61), ("2026-07-15", 312.0), ("2026-08-12", 376.0),
    ("2026-10-29", 283.77),
]


def test_googl_reproduces_hkcm_zone():
    df = path_through(GOOGL)
    res = analyze(df, "GOOGL", "Alphabet", "USD")
    z = res["zone"]
    print(json.dumps({k: res[k] for k in ("kurs", "status", "signal", "zone", "ziele")}, indent=1, ensure_ascii=False))
    print("Start:", res["welle"]["start"], "Hoch:", res["welle"]["hoch"], "Zählung:", res["welle"]["labels"])
    assert abs(res["welle"]["start"]["price"] - 83.34) < 0.05
    assert abs(res["welle"]["hoch"]["price"] - 408.61) < 0.05
    assert abs(z["oben"] - 284.36) < 0.05, z
    assert abs(z["unten"] - 245.98) < 0.05, z
    assert res["status"].startswith("In Zone")


def test_random_paths_never_crash():
    rng = np.random.default_rng(7)
    for s in range(40):
        n = 2500
        r = rng.normal(0.0003 * rng.choice([-1, 1]), rng.uniform(0.01, 0.04), n)
        c = 50 * np.exp(np.cumsum(r))
        idx = pd.bdate_range("2016-01-01", periods=n)
        df = pd.DataFrame({"Open": c, "High": c * 1.01, "Low": c * 0.99, "Close": c}, index=idx)
        res = analyze(df, f"RND{s}")
        json.dumps(res)
        assert res["ampel"] in ("gruen", "orange", "rot")
        assert res["zone"]["oben"] >= res["zone"]["unten"] >= res["zone"]["nachkauf"]


if __name__ == "__main__":
    test_googl_reproduces_hkcm_zone()
    test_random_paths_never_crash()
    print("OK")
