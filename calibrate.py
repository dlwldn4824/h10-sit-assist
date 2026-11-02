"""실험 현장에서 쓰는 캘리브레이션: calib 착석 데이터로 개인 기준(profile.json)을 만든다.

    python calibrate.py data/P01

Fatigue + Adaptive 조건을 시작하기 전에 돌려서, 정상 착석에서 제동이 잘못 켜지는
비율이 낮은지(leave-one-out) 먼저 확인한다.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

from evaluate import calib_loo
from sit_assist import Config, Profile


def main():
    if len(sys.argv) != 2:
        raise SystemExit("사용법: python calibrate.py data/P01")
    pdir = Path(sys.argv[1])
    files = sorted(pdir.glob("calib_rep*.csv"))
    if not files:
        raise SystemExit(f"{pdir} 안에 calib_rep*.csv가 없습니다.")
    cfg = Config()
    calib = [pd.read_csv(f) for f in files]
    prof = Profile.from_trials(calib, cfg)
    prof.save(pdir / "profile.json")

    print(f"착석 {prof.n_trials}회로 기준을 만들었습니다 → {pdir / 'profile.json'}")
    print(f"평소 착석 각도 Δθ {prof.contact_mean:.1f} ± {prof.contact_sd:.1f} deg, "
          f"DEEP 기준 {prof.deep_threshold(cfg):.1f} deg, 급가속 기준 {prof.alpha_max:.0f} deg/s²\n")
    print(pd.DataFrame({"Δθ(deg)": prof.centers, "왼쪽 평균": prof.mu_l, "왼쪽 SD": prof.sd_l,
                        "오른쪽 평균": prof.mu_r, "오른쪽 SD": prof.sd_r,
                        "상체 숙임": prof.lean_mu or None}).round(1).to_string(index=False))

    loo = calib_loo(calib, cfg)
    print(f"\n정상 착석 leave-one-out: 제동 켜짐 {loo.triggered.sum()}/{len(loo)}회, UPRIGHT 오감지 {loo.upright.sum()}회, "
          f"강한 제동 {loo.strong.sum()}회, DEEP 오감지 {loo.deep.sum()}회")
    if loo.triggered.mean() > 0.2:
        print("[주의] 정상 착석에서도 제동이 자주 켜집니다. 착석 지시를 일정하게 했는지 확인하고, "
              "calib를 더 모으거나 Config.z_weak을 올리세요.")


if __name__ == "__main__":
    main()
