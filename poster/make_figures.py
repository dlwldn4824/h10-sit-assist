"""포스터에 들어갈 그림을 만든다. 가짜 데이터(data/)와 결과(results/)가 먼저 있어야 한다.

    python simulate_data.py --out data && python evaluate.py data --out results
    python poster/make_figures.py --data data --results results --out poster/figs
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evaluate import descent_window, load_participant, offline_kinematics  # noqa: E402
from sit_assist import Config, Phase, Profile, run_trial  # noqa: E402

matplotlib.rcParams.update({"font.family": "AppleGothic", "axes.unicode_minus": False,
                            "font.size": 19, "legend.fontsize": 16, "axes.titlesize": 20, "axes.spines.top": False, "axes.spines.right": False})
WINE, GRAY, GREEN, RED, BLUE, PURPLE = "#772235", "#9a9a9a", "#2e8b57", "#d1495b", "#2f6db5", "#7b4fa0"
COND_COLOR = {1: GREEN, 2: RED, 3: BLUE}
COND_LABEL = {1: "Normal", 2: "Fatigue + H10 OFF", 3: "Fatigue + Adaptive H10"}


# ---------------------------------------------------------------- 1. 올바른 / 잘못된 착석 자세

def _pose(shank, thigh, trunk):
    """시상면 막대 인형. 각도는 수직 기준(deg). 발목이 원점, 앞쪽이 +x."""
    s, t, f = np.radians([shank, thigh, trunk])
    ankle = np.array([0.0, 0.0])
    knee = ankle + 0.45 * np.array([np.sin(s), np.cos(s)])
    hip = knee + 0.45 * np.array([-np.sin(t), np.cos(t)])
    shoulder = hip + 0.55 * np.array([np.sin(f), np.cos(f)])
    head = shoulder + 0.13 * np.array([np.sin(f), np.cos(f)])
    com = 0.12 * (ankle + knee) / 2 + 0.2 * (knee + hip) / 2 + 0.68 * (hip + shoulder) / 2
    return ankle, knee, hip, shoulder, head, com


def _draw_person(ax, x0, angles, color, chair=False, h10=False, com_ok=True):
    ankle, knee, hip, shoulder, head, com = (p + [x0, 0] for p in _pose(*angles))
    if chair:
        ax.add_patch(plt.Rectangle((x0 - 0.62, 0), 0.4, 0.42, color="#d9c7b8", zorder=0))
    ax.plot([x0 - 0.06, x0 + 0.2], [0, 0], c=color, lw=6, solid_capstyle="round")   # 발
    pts = np.array([ankle, knee, hip, shoulder])
    ax.plot(pts[:, 0], pts[:, 1], c=color, lw=7, solid_capstyle="round", solid_joinstyle="round")
    ax.add_patch(plt.Circle(head, 0.09, color=color))
    if h10:
        ax.add_patch(plt.Circle(hip, 0.06, color="#f2a541", zorder=5))
    ax.plot([com[0]] * 2, [com[1], 0], ls=":", c="k", lw=1.5)
    ax.plot(com[0], com[1], "o", ms=9, mfc="white", mec="k", zorder=6)
    if not com_ok:
        ax.annotate("", xy=(com[0] - 0.22, com[1] - 0.05), xytext=(com[0], com[1]),
                    arrowprops=dict(arrowstyle="-|>", color=RED, lw=3))


def fig_posture(out: Path):
    fig, axes = plt.subplots(1, 2, figsize=(14, 4.9))
    good = [(0, 2, 2), (12, 40, 35), (10, 85, 15)]
    bad = [(0, 2, 2), (18, 40, 6), (12, 80, -10)]
    for ax, poses, color, title, ok in ((axes[0], good, GREEN, "올바른 착석: 상체를 숙여 무게중심을 발 위에", True),
                                        (axes[1], bad, RED, "잘못된 착석: 상체를 세운 채 뒤로 털썩", False)):
        for k, ang in enumerate(poses):
            _draw_person(ax, k * 1.25, ang, color, chair=(k == 2), h10=ok and k == 1,
                         com_ok=ok or k == 0)
            if k < 2:
                ax.annotate("", xy=(k * 1.25 + 0.95, 0.9), xytext=(k * 1.25 + 0.6, 0.9),
                            arrowprops=dict(arrowstyle="-|>", color=GRAY, lw=2))
        ax.set_title(title, color=color, fontsize=22, fontweight="bold", pad=4)
        ax.set_xlim(-0.8, 3.0)
        ax.set_ylim(-0.08, 1.75)
        ax.set_aspect("equal")
        ax.axis("off")
    axes[0].text(1.25, -0.06, "● H10 (고관절)", color="#f2a541", ha="center", va="top", fontsize=17)
    axes[1].text(2.5, 1.2, "무게중심이\n발 뒤로", color=RED, ha="center", fontsize=19, fontweight="bold")
    fig.tight_layout()
    fig.savefig(out / "fig_posture.png", dpi=200, facecolor="white")
    plt.close(fig)


# ---------------------------------------------------------------- 2. 개인 기준값

def fig_profile(p: dict, prof: Profile, out: Path, cfg: Config = Config()):
    fig, ax = plt.subplots(1, 2, figsize=(14, 5.4))
    c = np.array(prof.centers)
    for df in p["calib"]:
        s = run_trial(df, prof, cfg)
        m = s["phase"] == Phase.DESCENT
        d = s.loc[m, ["dtheta_l", "dtheta_r"]].mean(axis=1)
        ax[0].plot(d, s.loc[m, ["omega_l", "omega_r"]].mean(axis=1), c=GRAY, lw=0.8, alpha=0.6)
        ax[1].plot(d, s.loc[m, "lean"], c=GRAY, lw=0.8, alpha=0.6)
    mu, sd = (np.array(prof.mu_l) + prof.mu_r) / 2, (np.array(prof.sd_l) + prof.sd_r) / 2
    ax[0].plot(c, mu, c=WINE, lw=3, label="개인 평균 속도 ω_ref(θ)")
    ax[0].fill_between(c, mu - cfg.z_weak * sd, mu + cfg.z_weak * sd, color=WINE, alpha=0.15,
                       label=f"정상 범위 (±{cfg.z_weak}σ)")
    lm, ls = np.array(prof.lean_mu), np.array(prof.lean_sd)
    ax[1].plot(c, lm, c=PURPLE, lw=3, label="개인 평균 상체 숙임 φ_ref(θ)")
    lo = lm - np.maximum(cfg.upright_margin_sd * ls, cfg.upright_min_margin)
    ax[1].fill_between(c, lo, lm + 12, where=c > cfg.brake_from_ratio * prof.contact_mean,
                       color=PURPLE, alpha=0.12, label="정상 자세 범위")
    for a in ax:
        a.axvline(prof.contact_mean, ls="--", c="k", lw=1)
        a.axvline(prof.deep_threshold(cfg), ls=":", c=RED, lw=1.5)
        a.set_xlabel("허벅지 굴곡 Δθ (deg)")
    ax[0].legend(loc="upper left", frameon=False)
    ax[1].legend(loc="lower right", frameon=False)
    ax[0].text(prof.deep_threshold(cfg) + 0.5, 5, "DEEP\n(낮은 의자)", color=RED, fontsize=16)
    ax[0].text(prof.contact_mean - 0.5, 5, "평소 착석", ha="right", fontsize=16)
    ax[0].set_ylabel("허벅지 굴곡 속도 (deg/s)")
    ax[1].set_ylabel("상체 숙임 (deg)")
    ax[1].set_ylim(-3, 50)
    ax[0].set_title("① 하강 속도 기준 (표준 의자 15회)")
    ax[1].set_title("② 상체 숙임 기준 (허리 IMU)")
    fig.tight_layout()
    fig.savefig(out / "fig_profile.png", dpi=200, facecolor="white")
    plt.close(fig)


# ---------------------------------------------------------------- 3. 조건 비교 (같은 참가자)

def fig_compare(p: dict, prof: Profile, out: Path, cfg: Config = Config()):
    fig, ax = plt.subplots(1, 2, figsize=(12, 4.6))
    seen = set()
    for tr in p["trials"]:
        df, cond = tr["df"], tr["cond"]
        k = offline_kinematics(df, cfg.fs)
        s, e = descent_window(k, df["seat"].to_numpy(dtype=float), cfg)
        d = df[["thigh_l_deg", "thigh_r_deg"]].mean(axis=1).to_numpy()
        d = d[s:e] - d[s]
        label = None if cond in seen else COND_LABEL[cond]
        seen.add(cond)
        ax[0].plot(d, k["wm"][s:e], c=COND_COLOR[cond], lw=1.4, alpha=0.8, label=label)
        ax[1].plot(d, k["lean"][s:e], c=COND_COLOR[cond], lw=1.4, alpha=0.8, label=label)
    for a in ax:
        a.axvline(prof.contact_mean, ls="--", c="k", lw=1)
        a.set_xlabel("허벅지 굴곡 Δθ (deg)")
    ax[0].set_ylabel("허벅지 굴곡 속도 (deg/s)")
    ax[1].set_ylabel("상체 숙임 (deg)")
    ax[0].set_title("하강 속도: 후반부 급가속이 줄어듦")
    ax[1].set_title("상체 숙임: 피로로 줄어든 숙임이 회복됨")
    ax[0].legend(loc="upper left", frameon=False)
    fig.tight_layout()
    fig.savefig(out / "fig_compare.png", dpi=200, facecolor="white")
    plt.close(fig)


# ---------------------------------------------------------------- 4. 한 시행의 실시간 동작

def fig_trial(df: pd.DataFrame, prof: Profile, out: Path, cfg: Config = Config()):
    log = run_trial(df, prof, cfg, shadow=True)
    log[["tau_cmd_l", "tau_cmd_r"]] = df[["tau_cmd_l", "tau_cmd_r"]].to_numpy()
    t = log["time_s"]
    keep = (t > 0.6) & (t < 4.6)
    log, t = log[keep], t[keep]
    fig, ax = plt.subplots(3, 1, figsize=(12, 8.6), sharex=True)
    ax[0].plot(t, log["omega_l"], c=BLUE, lw=2, label="허벅지 굴곡 속도 ω")
    m = log["omega_ref_l"] > 0
    ax[0].plot(t[m], log["omega_ref_l"][m], c="k", lw=1.5, ls="--", label="개인 기준 ω_ref")
    ax[0].set_ylabel("deg/s")
    ax[1].plot(t, log["lean"], c=PURPLE, lw=2, label="상체 숙임 φ")
    m = log["lean_ref"].notna()
    ax[1].plot(t[m], log["lean_ref"][m], c="k", lw=1.5, ls="--", label="개인 기준 φ_ref")
    up = (log["posture"] == 1).to_numpy()
    ax[1].scatter(t[up], log["lean"][up], s=10, c=RED, zorder=3, label="UPRIGHT 판단")
    ax[1].set_ylabel("deg")
    ax[2].stackplot(t, np.minimum(log["tau_support"], log["tau_cmd_l"]),
                    np.maximum(log["tau_cmd_l"] - log["tau_support"], 0),
                    colors=[PURPLE, WINE], alpha=0.75, labels=["상체 지지 토크", "하강 제동 토크"])
    ax[2].plot(t, log["tau_cmd_l"], c="k", lw=1.2, label="최종 신전 토크 (왼쪽)")
    ax[2].set_ylabel("Nm")
    ax[2].set_xlabel("시간 (s)")
    colors = {Phase.DESCENT: "#f6e7c1", Phase.DEEP: "#f4c7c3", Phase.SEATED: "#e3e3e3"}
    names = {Phase.DESCENT: "DESCENT", Phase.DEEP: "DEEP", Phase.SEATED: "SEATED"}
    for ph, col in colors.items():
        on = (log["phase"] == ph).to_numpy()
        if on.any():
            t0, t1 = t[on].iloc[0], t[on].iloc[-1]
            for a in ax:
                a.axvspan(t0, t1, color=col, alpha=0.6, zorder=0)
            ax[0].text((t0 + t1) / 2, ax[0].get_ylim()[1] * 0.93, names[ph], ha="center", fontsize=16,
                       fontweight="bold")
    for a in ax:
        a.legend(loc="upper left", frameon=False)
    fig.tight_layout()
    fig.savefig(out / "fig_trial.png", dpi=200, facecolor="white")
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--results", default="results")
    ap.add_argument("--out", default="poster/figs")
    ap.add_argument("--pid", default="P01")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    p = load_participant(Path(args.data) / args.pid)
    prof = Profile.from_trials(p["calib"])
    fig_posture(out)
    fig_profile(p, prof, out)
    fig_compare(p, prof, out)
    tr = next(t for t in p["trials"] if t["cond"] == 3 and t["rep"] == 1)
    fig_trial(tr["df"], prof, out)
    print(f"{out}/ 에 그림 4개를 저장했습니다.")


if __name__ == "__main__":
    main()
