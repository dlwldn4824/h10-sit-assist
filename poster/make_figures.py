"""포스터에 들어갈 그림을 만든다. 실측 데이터와 실측 기반 시뮬레이션 결과가 먼저 있어야 한다.

    python preprocess_h10.py <SUIT 로그들> --out data/real/S01
    python simulate_data.py --out data/sim --from-profile data/real/S01/profile.json
    python evaluate.py data/sim --out results/sim
    python poster/make_figures.py
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
PHASE_COLOR = {Phase.DESCENT: "#f6e7c1", Phase.DEEP: "#f4c7c3", Phase.SEATED: "#e3e3e3"}
H10_DOT = "#f2a541"

# 발표 슬라이드용: 레퍼런스 덱의 초록 + 검정 · 회색
SLIDES_PALETTE = {"WINE": "#3f9d63", "GRAY": "#b5b5b8", "GREEN": "#3f9d63", "RED": "#1a1a1c",
                  "BLUE": "#1a1a1c", "PURPLE": "#6b6b70", "H10_DOT": "#3f9d63",
                  "COND_COLOR": {1: "#b5b5b8", 2: "#1a1a1c", 3: "#3f9d63"},
                  "PHASE_COLOR": {Phase.DESCENT: "#f3f5f3", Phase.DEEP: "#e1f0e6", Phase.SEATED: "#e6e6e8"}}


def use_palette(name: str):
    if name == "slides":
        globals().update(SLIDES_PALETTE)
COND_LABEL = {1: "45 cm", 2: "35 cm + H10 OFF", 3: "35 cm + H10"}


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
        ax.add_patch(plt.Circle(hip, 0.06, color=H10_DOT, zorder=5))
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
    axes[0].text(1.25, -0.06, "● H10 (고관절)", color=H10_DOT, ha="center", va="top", fontsize=17)
    axes[1].text(2.5, 1.2, "무게중심이\n발 뒤로", color=RED, ha="center", fontsize=19, fontweight="bold")
    fig.tight_layout()
    fig.savefig(out / "fig_posture.png", dpi=200, facecolor="white")
    plt.close(fig)


# ---------------------------------------------------------------- 1-2. 용어 설명 (굴곡 · 신전 · 신전근 · 편심성 수축)

def _thigh_back(knee, hip):
    """허벅지 뒤쪽 방향 단위벡터 (오른쪽을 보고 선 사람 기준)."""
    d = (knee - hip) / np.linalg.norm(knee - hip)
    return np.array([d[1], -d[0]])


def _muscles(ax, ankle, knee, hip, shoulder, color, lw=11, alpha=0.55):
    """대둔근(엉덩이 뒤)과 햄스트링(허벅지 뒤)을 굵은 반투명 띠로 그린다."""
    back = _thigh_back(knee, hip)
    trunk = (shoulder - hip) / np.linalg.norm(shoulder - hip)
    trunk_back = np.array([-trunk[1], trunk[0]])          # 몸통 뒤쪽 (오른쪽을 보고 섬)
    pelvis_back = hip + trunk * 0.12 + trunk_back * 0.08
    glute_end = hip + (knee - hip) * 0.30 + back * 0.06
    ham_start = hip + back * 0.06
    ham_end = knee + back * 0.05
    for a, b in ((pelvis_back, glute_end), (ham_start, ham_end)):
        ax.plot([a[0], b[0]], [a[1], b[1]], c=color, lw=lw, alpha=alpha, solid_capstyle="round", zorder=4)
    return pelvis_back, glute_end, ham_start, ham_end


def _stick(ax, x0, angles, color="#1a1a1c"):
    ankle, knee, hip, shoulder, head, _ = (p + [x0, 0] for p in _pose(*angles))
    ax.plot([x0 - 0.06, x0 + 0.2], [0, 0], c=color, lw=6, solid_capstyle="round")
    pts = np.array([ankle, knee, hip, shoulder])
    ax.plot(pts[:, 0], pts[:, 1], c=color, lw=6, solid_capstyle="round", solid_joinstyle="round", zorder=3)
    ax.add_patch(plt.Circle(head, 0.085, color=color, zorder=3))
    ax.add_patch(plt.Circle(hip, 0.035, color="white", ec=color, lw=2, zorder=5))
    return ankle, knee, hip, shoulder


def fig_terms(out: Path):
    from matplotlib.patches import Arc, FancyArrowPatch
    fig, axes = plt.subplots(1, 3, figsize=(15, 5.6))
    acc = WINE
    # ① 굴곡 · 신전: 허벅지가 앞(굴곡)·뒤(신전)로 움직인 모습을 반투명으로
    ax = axes[0]
    ankle, knee, hip, shoulder = _stick(ax, 0.45, (0, 2, 2))
    for ang, col, label, tx in ((55, acc, "굴곡 (굽힘)", 0.62), (-28, "#8a8a8f", "신전 (폄)", -0.55)):
        t = np.radians(ang)
        k2 = hip + 0.45 * np.array([np.sin(t), -np.cos(t)])
        ax.plot([hip[0], k2[0]], [hip[1], k2[1]], c=col, lw=6, alpha=0.45, solid_capstyle="round")
        a0, a1 = (-90, -90 + ang) if ang > 0 else (-90 + ang, -90)
        ax.add_patch(Arc(hip, 0.5, 0.5, theta1=a0, theta2=a1, color=col, lw=2.5))
        ax.text(k2[0] + 0.06 if ang > 0 else tx, k2[1] + (0.05 if ang > 0 else -0.12), label, color=col,
                fontsize=19, fontweight="bold")
    ax.set_title("① 굴곡과 신전", fontsize=21, fontweight="bold")
    # ② 고관절 신전근
    ax = axes[1]
    ankle, knee, hip, shoulder = _stick(ax, 0.75, (0, 2, 2))
    pb, ge, hs, he = _muscles(ax, ankle, knee, hip, shoulder, acc)
    ax.annotate("대둔근 (엉덩이)", xy=(pb + ge) / 2, xytext=(-0.55, 1.2), fontsize=17, color=acc, fontweight="bold",
                arrowprops=dict(arrowstyle="-", color=acc, lw=1.5))
    ax.annotate("햄스트링\n(허벅지 뒤)", xy=(hs + he) / 2, xytext=(-0.55, 0.45), fontsize=17, color=acc,
                fontweight="bold", arrowprops=dict(arrowstyle="-", color=acc, lw=1.5))
    ax.text(0.45, -0.22, "다리를 뒤로 펴는(신전) 근육", fontsize=16, color="#333333", ha="center")
    ax.set_title("② 고관절 신전근", fontsize=21, fontweight="bold")
    # ③ 편심성 수축 + H10 신전 토크
    ax = axes[2]
    ankle, knee, hip, shoulder = _stick(ax, 0.75, (12, 60, 30))
    ax.add_patch(plt.Rectangle((hip[0] - 0.32, 0), 0.42, hip[1] - 0.06, color="#e3e5e3", zorder=0))
    pb, ge, hs, he = _muscles(ax, ankle, knee, hip, shoulder, acc)
    back = _thigh_back(knee, hip)
    d = (he - hs) / np.linalg.norm(he - hs)
    mid = (hs + he) / 2 + back * 0.13
    for sgn in (-1, 1):
        ax.add_patch(FancyArrowPatch(mid + sgn * d * 0.05, mid + sgn * d * 0.22, arrowstyle="-|>",
                                     mutation_scale=18, lw=2.5, color=acc, zorder=6))
    ax.text(0.45, -0.22, "근육이 늘어나면서 힘을 내 하강을 늦춤", fontsize=16, color=acc, fontweight="bold", ha="center")
    ax.add_patch(Arc(hip, 0.42, 0.42, theta1=150, theta2=250, color="#1a1a1c", lw=3))
    tip = hip + 0.21 * np.array([np.cos(np.radians(250)), np.sin(np.radians(250))])
    ax.add_patch(FancyArrowPatch(tip + [-0.04, 0.03], tip + [0.01, -0.01], arrowstyle="-|>", mutation_scale=20,
                                 lw=3, color="#1a1a1c"))
    ax.text(-0.55, 1.3, "H10 신전 토크\n= 하강 브레이크", fontsize=17, color="#1a1a1c", fontweight="bold")
    ax.set_title("③ 편심성 수축 (앉을 때)", fontsize=21, fontweight="bold")
    for ax in axes:
        ax.set_xlim(-0.6, 1.6)
        ax.set_ylim(-0.32, 1.78)
        ax.set_aspect("equal")
        ax.axis("off")
    fig.tight_layout()
    fig.savefig(out / "fig_terms.png", dpi=200, facecolor="white")
    plt.close(fig)


# ---------------------------------------------------------------- 2. 개인 기준값

def fig_profile(p: dict, prof: Profile, out: Path, cfg: Config = Config(), highlight: int | None = None):
    fig, ax = plt.subplots(1, 2, figsize=(14, 5.4))
    c = np.array(prof.centers)
    for k, df in enumerate(p["calib"]):
        s = run_trial(df, prof, cfg)
        m = s["phase"].isin([Phase.DESCENT, Phase.DEEP])
        d = s.loc[m, ["dtheta_l", "dtheta_r"]].mean(axis=1)
        hl = k == highlight
        style = dict(c=RED if hl else GRAY, lw=2.2 if hl else 1.0, alpha=1 if hl else 0.7, zorder=3 if hl else 1,
                     label=f"빠르게 앉은 시행 (rep{k + 1:02d})" if hl else None)
        ax[0].plot(d, s.loc[m, ["omega_l", "omega_r"]].mean(axis=1), **style)
        ax[1].plot(d, s.loc[m, "lean"], **{**style, "label": None})
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
    ax[1].set_ylim(min(-3, float(lo.min()) - 3), max(lm) + 20)
    ax[0].set_title(f"① 하강 속도 기준 (실측 착석 {prof.n_trials}회)")
    ax[1].set_title("② 상체 숙임 기준 (허리 IMU)")
    fig.tight_layout()
    fig.savefig(out / "fig_profile.png", dpi=200, facecolor="white")
    plt.close(fig)


# ---------------------------------------------------------------- 3. 조건 비교 (같은 참가자)

def fig_compare(p: dict, prof: Profile, out: Path, cfg: Config = Config(), tall: bool = False):
    fig, ax = plt.subplots(2, 1, figsize=(8.6, 8.4)) if tall else plt.subplots(1, 2, figsize=(12, 4.6))
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
    ax[0].set_title("하강 속도: 35 cm 후반부 급가속이 줄어듦")
    ax[1].set_title("상체 숙임: 조건 사이 차이는 작음")
    fig.legend(*ax[0].get_legend_handles_labels(), loc="lower center", ncol=3, frameon=False)
    fig.tight_layout(rect=(0, 0.06 if tall else 0.1, 1, 1))
    fig.savefig(out / ("fig_compare_tall.png" if tall else "fig_compare.png"), dpi=200, facecolor="white")
    plt.close(fig)


# ---------------------------------------------------------------- 4. 한 시행의 실시간 동작

def fig_trial(df: pd.DataFrame, prof: Profile, out: Path, cfg: Config = Config(),
              name: str = "fig_trial.png", window: tuple[float, float] = (0.6, 4.6)):
    log = run_trial(df, prof, cfg, shadow=True)
    if {"tau_cmd_l", "tau_cmd_r"} <= set(df.columns):     # 실제로 보조한 시행이면 기록된 토크를 그린다
        log[["tau_cmd_l", "tau_cmd_r"]] = df[["tau_cmd_l", "tau_cmd_r"]].to_numpy()
    t = log["time_s"]
    keep = (t > window[0]) & (t < window[1])
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
    colors = PHASE_COLOR
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
        a.legend(loc="upper right", frameon=False, fontsize=14)
    fig.tight_layout()
    fig.savefig(out / name, dpi=200, facecolor="white")
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--real", default="data/real/S01", help="preprocess_h10.py로 만든 실측 폴더")
    ap.add_argument("--sim", default="data/sim/P01", help="실측 기반 시뮬레이션 참가자 폴더")
    ap.add_argument("--out", default="poster/figs")
    ap.add_argument("--palette", choices=["poster", "slides"], default="poster")
    ap.add_argument("--highlight", type=int, default=5, help="실측에서 강조할 시행 번호")
    args = ap.parse_args()
    use_palette(args.palette)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    fig_posture(out)
    fig_terms(out)

    real = load_participant(Path(args.real))
    prof = Profile.from_trials(real["calib"])
    fig_profile(real, prof, out, highlight=args.highlight - 1)
    # 강조할 시행은 그 시행을 뺀 나머지로 만든 기준에 넣는다 (자기 자신이 기준에 섞이지 않게)
    k = args.highlight - 1
    df = real["calib"][k]
    loo = Profile.from_trials(real["calib"][:k] + real["calib"][k + 1:])
    fig_trial(df, loo, out, name="fig_trial_real.png", window=(0.9, float(df["time_s"].iloc[-1])))

    sim = load_participant(Path(args.sim))
    sim_prof = Profile.from_trials(sim["calib"])
    fig_compare(sim, sim_prof, out)
    fig_compare(sim, sim_prof, out, tall=True)
    tr = next(t for t in sim["trials"] if t["cond"] == 3 and t["rep"] == 1)
    fig_trial(tr["df"], sim_prof, out)
    print(f"{out}/ 에 그림을 저장했습니다.")


if __name__ == "__main__":
    main()
