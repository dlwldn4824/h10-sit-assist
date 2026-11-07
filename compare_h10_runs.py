"""H10에 알고리즘을 넣고 받은 로그로 OFF와 ON을 비교한다.

    python compare_h10_runs.py --off SUIT_LOGGED_DATA-40.csv SUIT_LOGGED_DATA-41.csv \\
                               --on  SUIT_LOGGED_DATA-42.csv SUIT_LOGGED_DATA-43.csv --out results/h10_onoff

- 원본 hex 로그(SUIT_LOGGED_DATA-*.csv)와 디코딩된 CSV(loopCnt 열이 있는 파일) 모두 받는다.
- 앉기를 자동으로 찾아 지표를 계산한다. ON 조건은 토크가 켜져 있으므로 보조 여부로 걸러내지 않는다.
- free_var1(단계*10 + 제동 단계 + 5·상체 덜 숙임)와 free_var2(계산 토크)가 기록돼 있으면 DEEP 판정과 최대 토크도 함께 본다.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from evaluate import trial_metrics
from h10_decode import decode_file
from preprocess_h10 import FS, POST_S, PRE_S, find_sit_downs, to_100hz

METRICS = {"peak_vel": "최대 허벅지 굴곡 속도 (°/s)", "contact_vel": "착석 순간 속도 (°/s)",
           "peak_acc": "최대 각가속도 (°/s²)", "rms_jerk": "RMS jerk (°/s³)",
           "descent_time": "착석 시간 (s)", "peak_lean": "최대 상체 숙임 (°)"}


def load_log(path: Path) -> pd.DataFrame:
    with open(path, "rb") as f:
        head = f.read(64)
    if head.lstrip().startswith(b"loopCnt"):
        return pd.read_csv(path)
    return decode_file(path)


def sit_trials(path: Path) -> list[pd.DataFrame]:
    raw = load_log(path)
    d = to_100hz(raw)
    has_log = "free_var1" in raw
    if has_log:
        k = len(raw) // 10 * 10
        for col in ("free_var1", "free_var2"):
            d[col] = raw[col].to_numpy(dtype=float)[:k].reshape(-1, 10)[:, -1]
    out = []
    for ev in find_sit_downs(d):
        a = max(ev["onset"] - int(PRE_S * FS), ev["upright"])
        b = min(ev["end"] + int(POST_S * FS), ev["stand_up"] + int(0.3 * FS), len(d))
        seg = d.iloc[a:b].copy()
        seg["time_s"] = seg["time_s"] - seg["time_s"].iloc[0]
        seg.attrs["source"] = path.name
        out.append(seg)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--off", nargs="+", required=True)
    ap.add_argument("--on", nargs="+", required=True)
    ap.add_argument("--out", default="results/h10_onoff")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    rows = []
    for cond, files in (("OFF", args.off), ("ON", args.on)):
        for f in files:
            for k, seg in enumerate(sit_trials(Path(f)), 1):
                m = trial_metrics(seg[["time_s", "thigh_l_deg", "thigh_r_deg", "trunk_deg"]])
                row = {"cond": cond, "source": seg.attrs["source"], "rep": k, **{c: m[c] for c in METRICS}}
                if "free_var1" in seg:
                    row["deep"] = bool(((seg["free_var1"] // 10) == 2).any())
                    row["upright"] = bool((np.round(seg["free_var1"]) % 10 >= 5).any())   # 2차: 상체 덜 숙임 판정
                    row["peak_tau_log"] = float(seg["free_var2"].max())
                rows.append(row)
    m = pd.DataFrame(rows)
    m.round(3).to_csv(out / "onoff_metrics.csv", index=False)
    g = m.groupby("cond")
    lines = [f"OFF {int((m.cond == 'OFF').sum())}회, ON {int((m.cond == 'ON').sum())}회", "",
             "| 지표 | OFF | ON | 변화 |", "|---|---|---|---|"]
    for k, name in METRICS.items():
        a, b = g[k].mean().get("OFF", np.nan), g[k].mean().get("ON", np.nan)
        lines.append(f"| {name} | {a:.2f} ± {g[k].std().get('OFF', np.nan):.2f} | "
                     f"{b:.2f} ± {g[k].std().get('ON', np.nan):.2f} | {(b - a) / abs(a) * 100:+.1f}% |")
    if "deep" in m:
        lines += ["", "DEEP 판정: " + ", ".join(f"{c} {int(x.deep.sum())}/{len(x)}" for c, x in g)]
    report = "\n".join(lines)
    (out / "onoff_report.md").write_text(report + "\n")
    print(report)


if __name__ == "__main__":
    main()
