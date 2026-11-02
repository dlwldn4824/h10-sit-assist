"""실측 45 cm 의자와 30 cm 의자 착석을 비교하고, 낮은 의자(DEEP) 판정을 실측으로 확인한다.

    python preprocess_h10.py SUIT-4 SUIT-5 --out data/real/chair45 --include-assist
    python preprocess_h10.py SUIT-22 SUIT-33 --out data/real/chair30
    python compare_chairs.py --out results/real

- 평소 착석 각도(DEEP 기준)는 45 cm 착석으로 정한다: 평균 + max(2SD, 3°)
- 하강 속도 기준은 착석 횟수가 많은 30 cm 착석 10회로 만든다 (45 cm는 2회라 기준을 만들 수 없음)
- 45 cm 착석 2회는 H10 보행 보조가 켜진 상태였다. 결과를 볼 때 이 점을 감안한다.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

from evaluate import calib_loo, load_participant, offline_kinematics, descent_window, trial_metrics
from sit_assist import Config, Phase, Profile, run_trial, segment_trial


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

    # 하강 속도 기준은 30 cm 10회, 평소 착석 각도는 45 cm로 바꿔 끼운 기준으로 컨트롤러를 돌린다
    prof = Profile.from_trials(trials["30 cm"], cfg)
    prof45 = replace(prof, contact_mean=round(float(c45.mean()), 3), contact_sd=round(float(c45.std(ddof=1)), 3))
    prof45.save(out / "profile_45ref.json")
    deep = []
    for chair, dfs in trials.items():
        for i, df in enumerate(dfs, 1):
            log = run_trial(df, prof45, cfg, shadow=True)
            deep.append({"chair": chair, "rep": i, "deep": bool((log["phase"] == Phase.DEEP).any())})
    met = met.merge(pd.DataFrame(deep), on=["chair", "rep"])
    loo = calib_loo(trials["30 cm"], cfg)
    met.round(3).to_csv(out / "chair_metrics.csv", index=False)

    summary = met.groupby("chair")[["contact_dtheta", "peak_vel", "contact_vel", "descent_time", "peak_lean"]].agg(["mean", "std"])
    stats = {
        "n45": int((met.chair == "45 cm").sum()), "n30": int((met.chair == "30 cm").sum()),
        "contact45": float(c45.mean()), "contact30": float(met[met.chair == "30 cm"].contact_dtheta.mean()),
        "deep_thr": float(deep_thr),
        "deep30": int(met[met.chair == "30 cm"].deep.sum()), "deep45": int(met[met.chair == "45 cm"].deep.sum()),
        "brake_quiet30": int((~loo.triggered).sum()),
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
              f"30 cm 정상 착석 leave-one-out: {stats['brake_quiet30']}/{stats['n30']}회 제동 없음."]
    (out / "chair_report.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
