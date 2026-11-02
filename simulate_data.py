"""실제 데이터가 오기 전에 코드 전체를 돌려 보기 위한 가짜 착석 데이터 생성기.

실험 프로토콜과 같은 파일 구조로 만든다.
    data/P01/meta.json
    data/P01/calib_rep01.csv ... calib_rep15.csv   표준 의자, 피로 전, 보조 OFF
    data/P01/profile.json                          calib로 만든 개인 기준
    data/P01/cond1_rep01.csv ...                   낮은 의자, Normal (보조 OFF)
    data/P01/cond2_rep01.csv ...                   낮은 의자, Fatigue + H10 OFF
    data/P01/cond3_rep01.csv ...                   낮은 의자, Fatigue + Adaptive H10

하강 모델 (한쪽 허벅지, deg 단위):
    dω/dt = k·(ω_의도 − ω) + b·(근력 부족 토크 − H10 토크)
- ω_의도: 사람이 내려가려는 속도. 중간에 가장 빠르고 의자 근처에서 느려짐
- 근력 부족 토크: 피로하면 착석 후반부에, 낮은 의자면 평소 착석 각도 이후에,
  상체를 평소보다 덜 숙이면(뒤로 주저앉는 자세) 중반 이후에 생김
상체 숙임 모델: 피로하면 숙인 상체를 버티기 힘들어 덜 숙이고, H10 신전 토크가 그 부담을 덜어 준다.
OFF 조건에서도 컨트롤러를 그림자 모드로 돌려 tau_cmd(계산만 한 토크)를 같이 기록한다.

    python simulate_data.py --out data --participants 12
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from sit_assist import Config, Profile, SitAssistController

FS = 100.0
B = 10.0            # deg/s² per Nm, 토크가 고관절 각가속도에 주는 영향
K_TRACK = 8.0       # 1/s, 사람이 의도한 속도를 따라가는 정도
CALIB_REPS = 15
LOG_COLS = ["phase", "level", "posture", "z_l", "z_r", "omega_ref_l", "omega_ref_r", "lean_ref",
            "tau_support", "tau_brake", "tau_cmd_l", "tau_cmd_r"]


def _smoothstep(x):
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3 - 2 * x)


def make_person(rng, pid: str) -> dict:
    knee = rng.uniform(44, 52)
    return {"id": pid,
            "knee_height_cm": round(knee, 1),
            "chair_standard_cm": round(knee, 1),           # 무릎 높이 100%
            "chair_low_cm": round(knee * 0.78, 1),         # 무릎 높이 약 78%
            "stand": rng.uniform(0, 6, 2),                 # 서 있을 때 허벅지 각도 (좌, 우)
            "trunk_stand": rng.uniform(0, 6),              # 서 있을 때 상체 각도
            "lean_peak": rng.uniform(30, 40),              # 평소 착석 중 최대 상체 숙임
            "w_peak": rng.uniform(55, 80),                 # 평소 최대 허벅지 굴곡 속도
            "contact_std": rng.uniform(65, 75),            # 표준 의자에서 엉덩이 닿는 Δθ
            "low_extra": rng.uniform(10, 15),              # 낮은 의자에서 더 굽혀지는 각도
            "side": 1 + np.array([-1, 1]) * rng.uniform(0, 0.1),   # 좌우 근력 차이
            "deficit": rng.uniform(20, 30),                # 피로 시 착석 후반부 부족 토크 (Nm)
            "deficit_deep": rng.uniform(10, 15),           # 낮은 의자 깊은 구간 부족 토크 (Nm)
            "deficit_upright": rng.uniform(10, 15)}        # 상체를 못 숙였을 때 추가 부족 토크 (Nm)


def _lean_intent(person: dict, p: float) -> float:
    """허벅지 진행률 p(0~1)에 따른 의도한 상체 숙임: 중반에 가장 숙이고 의자 근처에서 펴기 시작."""
    rise = np.sin(np.pi / 2 * min(p / 0.6, 1.0))
    return person["lean_peak"] * (rise - 0.5 * _smoothstep((p - 0.6) / 0.4))


def simulate_sit(rng, person: dict, chair: str, fatigue: float,
                 ctrl: SitAssistController | None = None) -> pd.DataFrame:
    dt = 1 / FS
    t0 = rng.uniform(0.8, 1.2)                             # 이때 앉기 시작
    depth = person["contact_std"] + (person["low_extra"] if chair == "low" else 0.0)
    depth += rng.normal(0, 1.5)
    w_peak = person["w_peak"] * (1 + rng.normal(0, 0.06))
    lean_scale = 1 + rng.normal(0, 0.06)
    k_track = K_TRACK * (1 - 0.25 * fatigue)
    cstd = person["contact_std"]

    n = int((t0 + 4.0) * FS)
    th, w = np.zeros(2), np.zeros(2)
    lean = 0.0
    tau = np.zeros(2)
    seated = False
    sway = np.interp(np.arange(n), np.linspace(0, n - 1, 8), rng.normal(0, 0.3, 8))
    rows = []
    for k in range(n):
        t = k * dt
        if t >= t0 and not seated:
            start = _smoothstep((t - t0) / 0.3)
            p_mean = np.clip(th.mean() / cstd, 0, 1)
            # 피로하면 숙인 상체를 버티기 힘들어 덜 숙인다. H10 신전 토크가 그 부담을 일부 덜어 준다
            relief = min(tau.mean() / 8.0, 1.0)
            lean_goal = _lean_intent(person, p_mean) * lean_scale * (1 - 0.55 * fatigue * (1 - relief))
            lean += (start * lean_goal - lean) * dt / 0.15
            upright = max(_lean_intent(person, p_mean) - lean, 0.0) / person["lean_peak"]
            for i in (0, 1):
                p = np.clip(th[i] / depth, 0, 1)
                w_int = start * w_peak * (0.25 + 0.75 * np.sin(np.pi * p))
                lack = (fatigue * person["deficit"] * person["side"][i]
                        * _smoothstep((th[i] - 0.55 * cstd) / 12)
                        + person["deficit_deep"] * (0.3 + fatigue) * _smoothstep((th[i] - cstd) / 8)
                        + person["deficit_upright"] * upright * _smoothstep((th[i] - 0.4 * cstd) / 12))
                acc = k_track * (w_int - w[i]) + B * (lack - tau[i])
                w[i] = max(w[i] + acc * dt, 0.0)           # H10은 사람을 들어 올리지 못한다
            th += w * dt
            if th.mean() >= depth:
                seated = True
        elif seated:
            w *= np.exp(-dt / 0.06)                        # 의자 쿠션에서 멈춤
            th += w * dt
            lean += (8.0 - lean) * dt / 0.4                # 앉은 뒤 상체를 세움

        thigh = person["stand"] + th + sway[k] + rng.normal(0, 0.15, 2)
        trunk = person["trunk_stand"] + lean + rng.normal(0, 0.3)
        row = {"time_s": round(t, 4), "thigh_l_deg": round(thigh[0], 3),
               "thigh_r_deg": round(thigh[1], 3), "trunk_deg": round(trunk, 3), "seat": int(seated)}
        if ctrl is not None:
            tau = np.array(ctrl.update(t, thigh[0], thigh[1], trunk, float(seated)))
            row.update({c: ctrl.info[c] for c in LOG_COLS})
        rows.append(row)
    df = pd.DataFrame(rows)
    return df.round({c: 3 for c in LOG_COLS if c in df})


def make_participant(rng, out: Path, pid: str, reps: int, cfg: Config = Config()) -> None:
    person = make_person(rng, pid)
    pdir = out / pid
    pdir.mkdir(parents=True, exist_ok=True)
    meta = {k: person[k] for k in ("id", "knee_height_cm", "chair_standard_cm", "chair_low_cm")}
    meta["simulated"] = True
    (pdir / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False))

    calib = [simulate_sit(rng, person, "standard", 0.0) for _ in range(CALIB_REPS)]
    for r, df in enumerate(calib, 1):
        df.to_csv(pdir / f"calib_rep{r:02d}.csv", index=False)
    profile = Profile.from_trials(calib, cfg)
    profile.save(pdir / "profile.json")

    for r in range(1, reps + 1):
        for cond, fatigue, shadow in ((1, 0.0, True), (2, 1.0, True), (3, 1.0, False)):
            f = fatigue * rng.uniform(0.8, 1.0)
            df = simulate_sit(rng, person, "low", f, SitAssistController(profile, cfg, shadow=shadow))
            df.to_csv(pdir / f"cond{cond}_rep{r:02d}.csv", index=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data")
    ap.add_argument("--participants", type=int, default=12)
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    rng = np.random.default_rng(args.seed)
    out = Path(args.out)
    for k in range(1, args.participants + 1):
        make_participant(rng, out, f"P{k:02d}", args.reps)
        print(f"P{k:02d} 완료")
    print(f"{out}/ 에 저장했습니다.")


if __name__ == "__main__":
    main()
