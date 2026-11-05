"""실측 45 cm 의자와 30 cm 의자 착석을 비교하고, 알고리즘을 실측으로 확인한다.

    python preprocess_h10.py ~/Downloads/11.4_45cm_10times_{1,2,3}.csv --out data/real/chair45
    python preprocess_h10.py ~/Downloads/11.4_30cm_10times_1.csv ~/Downloads/11.4_30cm_12times_{2,3}.csv --out data/real/chair30
    python compare_chairs.py --out results/real

- 개인 기준(하강 속도, 평소 착석 각도)은 매일 앉는 45 cm 착석 30회로 만든다.
- DEEP 기준: 45 cm 착석 각도 평균 + max(2SD, 3°)
- 정상 착석 오작동은 45 cm leave-one-out, 민감도는 같은 시행의 후반을 1.5배 빠르게 만든 가상 시행으로 본다.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from evaluate import TRIGGER_NM, calib_loo, load_participant, offline_kinematics, descent_window, trial_metrics
from sit_assist import Config, Phase, Profile, run_trial, segment_trial

LATE_K = 2.0


def contact_angle(df: pd.DataFrame, cfg: Config = Config()) -> float:
    s = segment_trial(df, cfg)
    m = (s["t"] >= s["onset_t"]) & (s["t"] <= s["contact_t"])
    return float(s["dtheta"][m][-1].mean())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chair45", default="data/real/chair45")
    ap.add_argument("--chair30", default="data/real/chair30")
    ap.add_argument("--out", default="results/real")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    cfg = Config()

    trials = {"45 cm": load_participant(Path(args.chair45))["calib"],
              "30 cm": load_participant(Path(args.chair30))["calib"]}
    rows = []
    for chair, dfs in trials.items():
        for i, df in enumerate(dfs, 1):
            m = trial_metrics(df, cfg)
            rows.append({"chair": chair, "rep": i, "contact_dtheta": contact_angle(df, cfg),
                         "peak_vel": m["peak_vel"], "contact_vel": m["contact_vel"],
                         "descent_time": m["descent_time"], "peak_lean": m["peak_lean"], "rms_jerk": m["rms_jerk"]})
    met = pd.DataFrame(rows)

    c45 = met[met.chair == "45 cm"].contact_dtheta
    deep_thr = c45.mean() + max(cfg.deep_margin_sd * c45.std(ddof=1), cfg.deep_min_margin)

    prof45 = Profile.from_trials(trials["45 cm"], cfg)
    prof45.save(out / "profile_45ref.json")
    deep = []
    for chair, dfs in trials.items():
        for i, df in enumerate(dfs, 1):
            log = run_trial(df, prof45, cfg, shadow=True)
            deep.append({"chair": chair, "rep": i, "deep": bool((log["phase"] == Phase.DEEP).any())})
    met = met.merge(pd.DataFrame(deep), on=["chair", "rep"])
    loo = calib_loo(trials["45 cm"], cfg, late_k=LATE_K)
    loo.round(3).to_csv(out / "loo45.csv", index=False)
    met.round(3).to_csv(out / "chair_metrics.csv", index=False)

    summary = met.groupby("chair")[["contact_dtheta", "peak_vel", "contact_vel", "descent_time", "peak_lean"]].agg(["mean", "std"])
    stats = {
        "n45": int((met.chair == "45 cm").sum()), "n30": int((met.chair == "30 cm").sum()),
        "contact45": float(c45.mean()), "contact30": float(met[met.chair == "30 cm"].contact_dtheta.mean()),
        "deep_thr": float(deep_thr),
        "deep30": int(met[met.chair == "30 cm"].deep.sum()), "deep45": int(met[met.chair == "45 cm"].deep.sum()),
        "brake_quiet45": int((~loo.triggered).sum()), "late_k": LATE_K,
        "late_caught45": int(loo.late_caught.sum()),
        "brake30": int(sum(run_trial(df, prof45, cfg, shadow=True)["tau_brake"].max() > TRIGGER_NM
                           for df in trials["30 cm"])),
    }
    stats["deeper_by"] = stats["contact30"] - stats["contact45"]
    (out / "chair_stats.json").write_text(json.dumps(stats, indent=2, ensure_ascii=False))
    lines = ["| 지표 | 45 cm | 30 cm |", "|---|---|---|"]
    names = {"contact_dtheta": "착석 각도 Δθ (°)", "peak_vel": "최대 허벅지 굴곡 속도 (°/s)",
             "contact_vel": "착석 순간 속도 (°/s)", "descent_time": "착석 시간 (s)", "peak_lean": "최대 상체 숙임 (°)"}
    for k, n in names.items():
        lines.append(f"| {n} | " + " | ".join(f"{summary.loc[c, (k, 'mean')]:.1f} ± {summary.loc[c, (k, 'std')]:.1f}"
                                            for c in ("45 cm", "30 cm")) + " |")
    lines += ["", f"45 cm {stats['n45']}회, 30 cm {stats['n30']}회. 30 cm에서 평균 {stats['deeper_by']:.1f}° 더 깊이 굽혀짐.",
              f"DEEP 기준 {deep_thr:.1f}° (45 cm 평균 + max(2SD, 3°)): 30 cm {stats['deep30']}/{stats['n30']}회 감지, "
              f"45 cm {stats['deep45']}/{stats['n45']}회 오감지.",
              f"45 cm 정상 착석 leave-one-out: {stats['brake_quiet45']}/{stats['n45']}회 제동 없음, "
              f"후반 {LATE_K}배 빠른 가상 착석 {stats['late_caught45']}/{stats['n45']}회 제동."]
    (out / "chair_report.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
