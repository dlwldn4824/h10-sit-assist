"""개인 기준(profile.json)과 Config를 펌웨어용 헤더(sit_assist_params.h)로 내보낸다.

    python firmware/export_params.py --profile results/real/profile_45ref.json

profile_45ref.json = 30 cm 착석 10회의 하강 속도 기준 + 45 cm 착석 각도(DEEP 기준). compare_chairs.py가 만든다.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from scipy.signal import butter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sit_assist import Config, Profile  # noqa: E402


def arr(name: str, vals) -> str:
    body = ", ".join(f"{v:.15g}" for v in vals)
    return f"static const sa_real {name}[] = {{{body}}};"


def biquad(cutoff: float, fs: float) -> list[float]:
    b, a = butter(2, cutoff / (fs / 2))
    return [b[0], b[1], b[2], a[1], a[2]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default=str(ROOT / "results" / "real" / "profile_45ref.json"))
    ap.add_argument("--out", default=str(ROOT / "firmware" / "sit_assist_params.h"))
    args = ap.parse_args()
    p, c = Profile.load(Path(args.profile)), Config()
    has_lean = p.lean_mu is not None
    lines = [
        "/* export_params.py가 만든 파일 — 직접 고치지 말 것 */",
        f"/* 기준: {Path(args.profile).name}, 착석 {p.n_trials}회 */",
        "#ifndef SIT_ASSIST_PARAMS_H", "#define SIT_ASSIST_PARAMS_H", "",
        f"#define SA_FS {c.fs:.1f}",
        f"#define SA_ONSET_VEL {c.onset_vel}", f"#define SA_ONSET_HOLD {round(c.onset_hold_s * c.fs)}",
        f"#define SA_SEAT_VEL {c.seat_vel}", f"#define SA_SEAT_HOLD {round(c.seat_hold_s * c.fs)}",
        f"#define SA_MIN_SEAT_DEPTH {c.min_seat_depth}", f"#define SA_STAND_DEPTH {c.stand_depth}",
        f"#define SA_Z_WEAK {c.z_weak}", f"#define SA_Z_STRONG {c.z_strong}", f"#define SA_GAIN {c.gain}",
        f"#define SA_BRAKE_FROM_RATIO {c.brake_from_ratio}", f"#define SA_DEEP_GAIN {c.deep_gain}",
        f"#define SA_DEEP_TARGET_RATIO {c.deep_target_ratio}", f"#define SA_LOOKAHEAD {c.lookahead_s}",
        f"#define SA_SUPPORT_GAIN {c.support_gain}", f"#define SA_UPRIGHT_MARGIN_SD {c.upright_margin_sd}",
        f"#define SA_UPRIGHT_MIN_MARGIN {c.upright_min_margin}", f"#define SA_UPRIGHT_GAIN {c.upright_gain}",
        f"#define SA_TAU_MAX {c.tau_max}", f"#define SA_RISE_RATE {c.rise_rate}", f"#define SA_RELEASE_S {c.release_s}",
        "",
        f"#define SA_CONTACT_MEAN {p.contact_mean:.6f}   /* 평소 착석 각도 (deg) */",
        f"#define SA_DEEP_THRESHOLD {p.deep_threshold(c):.6f} /* 이 각도를 넘으면 낮은 의자(DEEP) */",
        f"#define SA_ALPHA_MAX {p.alpha_max:.6f}",
        f"#define SA_NBINS {len(p.centers)}",
        f"#define SA_HAS_LEAN {1 if has_lean else 0}",
        arr("SA_CENTERS", p.centers), arr("SA_MU_L", p.mu_l), arr("SA_SD_L", p.sd_l),
        arr("SA_MU_R", p.mu_r), arr("SA_SD_R", p.sd_r),
        arr("SA_LEAN_MU", p.lean_mu if has_lean else [0] * len(p.centers)),
        arr("SA_LEAN_SD", p.lean_sd if has_lean else [1] * len(p.centers)),
        arr("SA_LPF_ANGLE", biquad(c.angle_cutoff_hz, c.fs)),
        arr("SA_LPF_ACCEL", biquad(c.accel_cutoff_hz, c.fs)),
        arr("SA_LPF_TRUNK", biquad(c.trunk_cutoff_hz, c.fs)),
        "", "#endif", "",
    ]
    Path(args.out).write_text("\n".join(lines))
    print(f"저장: {args.out} (DEEP 기준 {p.deep_threshold(c):.1f}°, 구간 {len(p.centers)}개)")


if __name__ == "__main__":
    main()
