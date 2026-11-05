"""포스터에 들어갈 그림을 만든다. 실측 데이터와 실측 기반 시뮬레이션 결과가 먼저 있어야 한다.

    python preprocess_h10.py <SUIT-22, 33> --out data/real/chair30
    python simulate_data.py --out data/sim --from-profile data/real/chair30/profile.json --chair-stats results/real/chair_stats.json
    python evaluate.py data/sim --out results/sim
    python poster/make_figures.py
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

HERE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE_ROOT))
from evaluate import descent_window, load_participant, offline_kinematics, speed_up_late  # noqa: E402
from sit_assist import Config, Phase, Profile, run_trial  # noqa: E402

matplotlib.rcParams.update({"font.family": "Noto Sans KR", "axes.unicode_minus": False,
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
COND_LABEL = {1: "45 cm", 2: "30 cm + H10 OFF", 3: "30 cm + H10"}


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


def fig_posture(out: Path, ink: str | None = None):
    """ink를 주면 사람·제목을 그 색 하나로 그린다 (포스터용 검정)."""
    fig, axes = plt.subplots(1, 2, figsize=(14, 4.9))
    good = [(0, 2, 2), (12, 40, 35), (10, 85, 15)]
    bad = [(0, 2, 2), (18, 40, 6), (12, 80, -10)]
    for ax, poses, color, title, ok in ((axes[0], good, ink or GREEN, "올바른 착석: 상체를 숙여 무게중심을 발 위에", True),
                                        (axes[1], bad, ink or RED, "잘못된 착석: 상체를 세운 채 뒤로 털썩", False)):
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
    axes[1].text(2.5, 1.2, "무게중심이\n발 뒤로", color=ink or RED, ha="center", fontsize=19, fontweight="bold")
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


# ---------------------------------------------------------------- 1-3. 근육 위치 (착석 단계 + 확대 상자)

MUSCLE, MUSCLE_DARK, SKIN, TENDON = "#d9644f", "#a8412f", "#efe3d6", "#f7f2ea"
ANATOMY: dict = {}      # {"glute": 경로, "ham": 경로} 주면 확대 상자에 실제 해부 이미지를 쓴다 (저작권 자료라 저장소에는 없음)


def _spindle(ax, cx, cy, length, width, angle, fibers=7, z=3):
    """근육 한 갈래(방추형)를 결(fiber) 선과 함께 그린다. angle: 수직 기준(deg)."""
    t = np.linspace(-1, 1, 80)
    half = width / 2 * (1 - t ** 2) ** 0.7
    a = np.radians(angle)
    axis, perp = np.array([np.sin(a), np.cos(a)]), np.array([np.cos(a), -np.sin(a)])
    left = np.c_[t * length / 2, half] @ np.vstack([axis, perp])
    right = np.c_[t * length / 2, -half] @ np.vstack([axis, perp])
    poly = np.vstack([left, right[::-1]]) + [cx, cy]
    ax.fill(poly[:, 0], poly[:, 1], color=MUSCLE, ec=MUSCLE_DARK, lw=1.2, zorder=z)
    for k in np.linspace(-0.7, 0.7, fibers):
        f = np.c_[t * length / 2 * 0.92, half * k] @ np.vstack([axis, perp]) + [cx, cy]
        ax.plot(f[:, 0], f[:, 1], c=MUSCLE_DARK, lw=0.6, alpha=0.6, zorder=z + 1)
    for sgn in (-1, 1):                               # 양 끝 힘줄
        e = np.array([cx, cy]) + axis * sgn * length / 2
        ax.plot([e[0], e[0] + axis[0] * sgn * 0.06], [e[1], e[1] + axis[1] * sgn * 0.06],
                c=TENDON, lw=5, solid_capstyle="round", zorder=z)


def _inset(fig, rect, kind, title):
    """확대 상자: 둥근 테두리 + 피부 실루엣 + 근육."""
    from matplotlib.patches import FancyBboxPatch
    ax = fig.add_axes(rect)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.add_patch(FancyBboxPatch((0.02, 0.02), 0.96, 0.96, boxstyle="round,pad=0,rounding_size=0.08",
                                fc="#f4f5f4", ec=WINE, lw=2.5, transform=ax.transAxes, zorder=0))
    if kind in ANATOMY:       # 해부 이미지: 비율을 지키며 상자 안에 맞춘다
        im = plt.imread(str(ANATOMY[kind]))
        h, w = im.shape[:2]
        bw, bh = rect[2] * fig.get_figwidth(), rect[3] * fig.get_figheight()
        ar = (w / h) / (bw / bh)
        iw, ih = (0.92, 0.92 / ar) if ar > 1 else (0.92 * ar, 0.92)
        art = ax.imshow(im, extent=(0.5 - iw / 2, 0.5 + iw / 2, 0.5 - ih / 2, 0.5 + ih / 2), zorder=1, aspect="auto")
        clip = FancyBboxPatch((0.04, 0.04), 0.92, 0.92, boxstyle="round,pad=0,rounding_size=0.07",
                              transform=ax.transAxes, fc="none", ec="none")
        ax.add_patch(clip)
        art.set_clip_path(clip)
    elif kind == "glute":     # 뒤에서 본 엉덩이: 엉덩이 실루엣 위에 큰 대둔근
        th = np.linspace(0, 2 * np.pi, 100)
        ax.fill(0.5 + 0.36 * np.cos(th), 0.52 + 0.34 * np.sin(th), color=SKIN, zorder=1)
        ax.fill([0.22, 0.78, 0.7, 0.3], [0.3, 0.3, 0.02, 0.02], color=SKIN, zorder=1)
        _spindle(ax, 0.5, 0.55, 0.9, 0.52, 52, fibers=11)
    else:                     # 뒤에서 본 허벅지: 햄스트링 두 갈래
        ax.fill([0.28, 0.72, 0.64, 0.36], [0.98, 0.98, 0.02, 0.02], color=SKIN, zorder=1)
        _spindle(ax, 0.42, 0.5, 0.78, 0.2, 4)
        _spindle(ax, 0.58, 0.5, 0.78, 0.2, -4)
    ax.text(1.08, 0.5, title, ha="left", va="center", fontsize=18, fontweight="bold", color=WINE,
            transform=ax.transAxes, linespacing=1.4)
    return ax


def fig_muscles(out: Path):
    from matplotlib.patches import Arc, FancyArrowPatch
    W, H = 15.0, 5.6
    fig = plt.figure(figsize=(W, H))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, W)
    ax.set_ylim(0, H)
    ax.axis("off")
    S = 2.6                                            # 인형 크기

    def person(x0, angles, chair=False):
        ankle, knee, hip, shoulder, head, _ = (p * S + [x0, 0.85] for p in _pose(*angles))
        if chair:
            ax.add_patch(plt.Rectangle((hip[0] - 0.9, 0.85), 0.75, hip[1] - 0.95, color="#d5d8d5", zorder=0))
        ax.plot([ankle[0] - 0.12, ankle[0] + 0.45], [0.85, 0.85], c="#1a1a1c", lw=7, solid_capstyle="round")
        ax.plot(*np.array([shoulder, hip]).T, c="#1a1a1c", lw=8, solid_capstyle="round", zorder=3)
        ax.plot(*np.array([hip, knee, ankle]).T, c=WINE, lw=9, alpha=0.45, solid_capstyle="round", zorder=3)
        ax.plot(*np.array([hip, knee, ankle]).T, c="#1a1a1c", lw=3, solid_capstyle="round", zorder=4)
        ax.add_patch(plt.Circle(head, 0.24, color="#1a1a1c", zorder=3))
        for j in (hip, knee, ankle):
            ax.add_patch(plt.Circle(j, 0.09, color=WINE, ec="white", lw=1.5, zorder=5))
        return ankle, knee, hip, shoulder

    def tri(x, y):
        ax.add_patch(plt.Polygon([[x, y - 0.25], [x, y + 0.25], [x + 0.32, y]], color=WINE, zorder=6))

    # ① 서 있음
    person(1.0, (0, 2, 2))
    ax.text(1.1, 0.35, "① 서 있음", ha="center", fontsize=18, fontweight="bold")
    tri(2.05, 2.6)
    # ② 내려가는 중 + 확대 상자 2개
    ankle, knee, hip, shoulder = person(3.9, (14, 48, 38))
    ax.text(3.6, 0.35, "② 내려가는 중", ha="center", fontsize=18, fontweight="bold")
    ax.add_patch(FancyArrowPatch(shoulder + [-0.6, 0.5], shoulder + [0.15, 0.55], connectionstyle="arc3,rad=-0.4",
                                 arrowstyle="-|>", mutation_scale=22, lw=3, ls="--", color=WINE))
    back = _thigh_back(knee, hip)
    glute_pt = hip + np.array([-0.16, 0.14])
    ham_pt = (hip + knee) / 2 + back * 0.12
    g_rect, h_rect = [0.37, 0.53, 0.15, 0.40], [0.37, 0.08, 0.15, 0.40]
    _inset(fig, g_rect, "glute", "대둔근\n(엉덩이)")
    _inset(fig, h_rect, "ham", "햄스트링\n(허벅지 뒤)")
    for pt, r in ((glute_pt, g_rect), (ham_pt, h_rect)):
        tgt = (r[0] * W + 0.05, (r[1] + r[3] / 2) * H)
        ax.plot([pt[0], tgt[0]], [pt[1], tgt[1]], c=WINE, lw=2, zorder=6)
        ax.add_patch(plt.Circle(pt, 0.07, color=WINE, zorder=7))
    ax.text(8.45, 2.75, "늘어나면서 힘을 내\n하강을 늦춥니다\n= 편심성 수축", fontsize=16, color="#1a1a1c",
            ha="left", va="center", linespacing=1.5)
    tri(10.3, 2.6)
    # ③ 착석 + H10 신전 토크
    ankle, knee, hip, shoulder = person(13.1, (10, 84, 12), chair=True)
    ax.text(12.6, 0.35, "③ 착석", ha="center", fontsize=18, fontweight="bold")
    ax.add_patch(Arc(hip, 0.9, 0.9, theta1=110, theta2=250, color=WINE, lw=3.5, zorder=6))
    tip = hip + 0.45 * np.array([np.cos(np.radians(250)), np.sin(np.radians(250))])
    ax.add_patch(FancyArrowPatch(tip + [-0.08, 0.06], tip + [0.02, -0.02], arrowstyle="-|>", mutation_scale=24,
                                 lw=3, color=WINE, zorder=6))
    ax.text(11.0, 4.55, "H10 신전 토크가 같은 방향으로 보조", fontsize=16, color=WINE, fontweight="bold",
            ha="left", va="center")
    fig.savefig(out / "fig_muscles.png", dpi=200, facecolor="white")
    plt.close(fig)


# ---------------------------------------------------------------- 2. 개인 기준값

def fig_profile(p: dict, prof: Profile, out: Path, cfg: Config = Config(), highlight: int | None = None,
                extra: pd.DataFrame | None = None, extra_label: str = ""):
    fig, ax = plt.subplots(1, 2, figsize=(14, 5.4))
    c = np.array(prof.centers)
    trials = list(p["calib"]) + ([extra] if extra is not None else [])
    if extra is not None:
        highlight = len(trials) - 1
    for k, df in enumerate(trials):
        s = run_trial(df, prof, cfg)
        m = s["phase"].isin([Phase.DESCENT, Phase.DEEP])
        d = s.loc[m, ["dtheta_l", "dtheta_r"]].mean(axis=1)
        hl = k == highlight
        style = dict(c=RED if hl else GRAY, lw=2.2 if hl else 1.0, alpha=1 if hl else 0.7, zorder=3 if hl else 1,
                     label=(extra_label or f"빠르게 앉은 시행 (rep{k + 1:02d})") if hl else None)
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
    ax[0].set_title("하강 속도: 30 cm 후반부 급가속이 줄어듦")
    ax[1].set_title("상체 숙임: 조건 사이 차이는 작음")
    fig.legend(*ax[0].get_legend_handles_labels(), loc="lower center", ncol=3, frameon=False)
    fig.tight_layout(rect=(0, 0.06 if tall else 0.1, 1, 1))
    fig.savefig(out / ("fig_compare_tall.png" if tall else "fig_compare.png"), dpi=200, facecolor="white")
    plt.close(fig)


# ---------------------------------------------------------------- 3-2. 실측 45 cm vs 30 cm

def fig_chairs(d45: Path, d30: Path, stats: dict, out: Path, cfg: Config = Config()):
    """실측 의자 높이 비교: 위 ω–Δθ 곡선, 아래 착석 각도 점그림 (DEEP 기준선)."""
    fig, ax = plt.subplots(2, 1, figsize=(8.6, 8.4), gridspec_kw={"height_ratios": [1.5, 1]})
    cols = {"45 cm": "#1a1a1c" if WINE != "#772235" else "#555555", "30 cm": WINE}
    for chair, d in (("45 cm", d45), ("30 cm", d30)):
        angles = []
        for k, df in enumerate(load_participant(d)["calib"]):
            log = run_trial(df, Profile.load(Path(stats["_profile"])), cfg, shadow=True)
            m = log["phase"].isin([Phase.DESCENT, Phase.DEEP])
            dm = log.loc[m, ["dtheta_l", "dtheta_r"]].mean(axis=1)
            ax[0].plot(dm, log.loc[m, ["omega_l", "omega_r"]].mean(axis=1), c=cols[chair], lw=1.6, alpha=0.75,
                       label=chair if k == 0 else None)
            seated = log["phase"] == Phase.SEATED
            angles.append(float(log.loc[seated, ["dtheta_l", "dtheta_r"]].mean(axis=1).iloc[0]) if seated.any() else np.nan)
        y = 0 if chair == "45 cm" else 1
        ax[1].scatter(angles, np.full(len(angles), y) + np.random.default_rng(0).uniform(-0.12, 0.12, len(angles)),
                      s=90, c=cols[chair], alpha=0.85, zorder=3)
    for a in ax:
        a.axvline(stats["deep_thr"], ls=":", c="#1a1a1c", lw=1.5)
    ax[0].text(stats["deep_thr"] + 0.6, ax[0].get_ylim()[1] * 0.9, "DEEP 기준", fontsize=15)
    ax[0].set_xlabel("허벅지 굴곡 Δθ (deg)")
    ax[0].set_ylabel("허벅지 굴곡 속도 (deg/s)")
    ax[0].set_title("실측 하강 곡선: 30 cm는 더 깊이 내려감")
    ax[0].legend(loc="upper left", frameon=False)
    ax[1].set_yticks([0, 1], [f"45 cm ({stats['n45']}회)", f"30 cm ({stats['n30']}회)"])
    ax[1].set_ylim(-0.6, 1.6)
    ax[1].set_xlabel("엉덩이가 닿는 순간의 허벅지 굴곡 Δθ (deg)")
    ax[1].set_title(f"착석 각도: 평균 {stats['contact45']:.1f}° → {stats['contact30']:.1f}° (+{stats['deeper_by']:.1f}°)")
    fig.tight_layout()
    fig.savefig(out / "fig_chairs.png", dpi=200, facecolor="white")
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
    if log["tau_support"].max() > 0:
        ax[2].stackplot(t, np.minimum(log["tau_support"], log["tau_cmd_l"]),
                        np.maximum(log["tau_cmd_l"] - log["tau_support"], 0),
                        colors=[PURPLE, WINE], alpha=0.75, labels=["상체 지지 토크", "하강 제동 토크"])
    else:
        ax[2].fill_between(t, log["tau_cmd_l"], color=WINE, alpha=0.75, label="하강 제동 토크")
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


def fig_session(raw45: Path, raw30: Path, out: Path):
    """실측 기록 원본: 허벅지 굽힘 각도와 자동 검출한 착석 구간(음영)."""
    from h10_decode import decode_file
    from preprocess_h10 import find_sit_downs, to_100hz
    fig, ax = plt.subplots(2, 1, figsize=(13, 4.2), sharex=True)
    for a, path, lab in ((ax[0], raw45, "45 cm"), (ax[1], raw30, "30 cm")):
        d = to_100hz(decode_file(path))
        m = d[["thigh_l_deg", "thigh_r_deg"]].mean(axis=1)
        m = m - np.percentile(m, 5)
        t = d["time_s"]
        for ev in find_sit_downs(d):
            a.axvspan(ev["onset"] / 100, ev["end"] / 100, color=WINE, alpha=0.16, lw=0)
        a.plot(t, m, c=WINE if lab == "30 cm" else "#33363d", lw=1.6)
        a.set_ylabel("굽힘 (°)")
        a.set_title(f"{lab} 의자 · 착석 10회 연속 기록", loc="left", fontsize=17, fontweight="bold",
                    color=WINE if lab == "30 cm" else "#33363d", pad=4)
        a.set_xlim(0, min(60, float(t.iloc[-1])))
        a.set_yticks([0, 50, 100])
    ax[1].set_xlabel("시간 (s)")
    fig.tight_layout(h_pad=0.4)
    fig.savefig(out / "fig_session.png", dpi=200, facecolor="white")
    plt.close(fig)


def fig_design(real: dict, out: Path, late_k: float = 1.5):
    """설계 근거: (a) 정상 착석끼리의 속도 편차와 제동 구간, (b) 설계 전후 정상/가속 착석의 최대 이상 점수."""
    from dataclasses import replace as _r
    from evaluate import speed_up_late
    calib = real["calib"]
    new = Config()
    old = _r(new, min_sd=5.0, brake_from_ratio=0.25)
    prof = Profile.from_trials(calib, new)
    c = np.array(prof.centers)
    mu = (np.array(prof.mu_l) + prof.mu_r) / 2
    raw_sd = []
    for cfg_ in (old,):
        p_ = Profile.from_trials(calib, cfg_)
        raw_sd = (np.array(p_.sd_l) + p_.sd_r) / 2
    fig, ax = plt.subplots(2, 1, figsize=(6.4, 7.6), gridspec_kw={"height_ratios": [1, 1.05]})
    a = ax[0]
    for df in calib:
        lg = run_trial(df, prof, new)
        m = lg["phase"].isin([Phase.DESCENT, Phase.DEEP])
        a.plot(lg.loc[m, ["dtheta_l", "dtheta_r"]].mean(axis=1), lg.loc[m, ["omega_l", "omega_r"]].mean(axis=1),
               c="#b9bcc2", lw=0.8)
    zt = new.z_weak + 1.0 / new.gain                      # 제동 1 Nm가 되는 점수
    sd_new = (np.array(prof.sd_l) + prof.sd_r) / 2
    a.plot(c, mu, c="#33363d", lw=2.5, label="평균 속도")
    a.plot(c, mu + zt * raw_sd, c="#8c9096", lw=2, ls="--", label="기존 제동 경계")
    a.plot(c, mu + zt * sd_new, c=WINE, lw=2.4, label="수정 제동 경계")
    half = new.brake_from_ratio * prof.contact_mean
    a.axvspan(half, prof.contact_mean, color="#ffe98a", alpha=0.35, lw=0)
    a.set_ylim(-20, 330)
    a.text(half + 1, 322, "수정 제동 구간 (후반 50%)", fontsize=12, va="top")
    a.set_xlabel("허벅지 굽힘 Δθ (°)")
    a.set_ylabel("굽힘 속도 (°/s)")
    a.set_title("(a) 정상 착석 30회의 속도 편차", loc="left", fontsize=16, fontweight="bold")
    a.legend(loc="upper left", frameon=False, fontsize=11, ncol=1, bbox_to_anchor=(0.0, 1.02))

    def peak_z(cfg_, df, prof_):
        lg = run_trial(df, prof_, cfg_)
        on = lg["tau_brake"] > 0           # 제동 구간 안의 점수만 (구간 밖은 0)
        return float(lg.loc[on, ["z_l", "z_r"]].max(axis=1).max()) if on.any() else \
            float(lg[["z_l", "z_r"]].max(axis=1).clip(upper=new.z_weak).max())

    rows = []
    for name, cfg_ in (("기존 설정", old), ("수정 설정", new)):
        for i, df in enumerate(calib):
            pr = Profile.from_trials(calib[:i] + calib[i + 1:], cfg_)
            rows.append((name, "정상 착석", peak_z(cfg_, df, pr)))
            rows.append((name, f"후반 {late_k:g}배 가속", peak_z(cfg_, speed_up_late(df, late_k), pr)))
    a = ax[1]
    rng = np.random.default_rng(0)
    for k, name in enumerate(("기존 설정", "수정 설정")):
        for j, (kind, col) in enumerate((("정상 착석", "#8c9096"), (f"후반 {late_k:g}배 가속", WINE))):
            z = np.array([r[2] for r in rows if r[0] == name and r[1] == kind])
            x = k * 2.6 + j + rng.uniform(-0.22, 0.22, len(z))
            a.scatter(x, np.clip(z, 0, 14), s=26, c=col, alpha=0.85, lw=0,
                      label=kind if k == 0 else None)
            over = int((z > zt).sum())
            a.text(k * 2.6 + j, 14.6, f"제동 {over}/{len(z)}", ha="center", fontsize=12, color=col, fontweight="bold")
    a.axhline(zt, c="#33363d", ls="--", lw=1.2)
    a.text(1.25, zt - 0.35, "제동 1 Nm 기준", ha="center", va="top", fontsize=12, color="#33363d")
    a.set_xticks([0.5, 3.1])
    a.set_xticklabels(["기존 설정", "수정 설정"], fontsize=14)
    a.set_ylim(0, 15.6)
    a.set_xlim(-0.6, 4.2)
    a.set_ylabel("최대 이상 점수 z")
    a.set_title("(b) 설정 수정 전후 제동 판정", loc="left", fontsize=16, fontweight="bold")
    a.legend(loc="upper center", bbox_to_anchor=(0.58, 0.82), frameon=False, fontsize=11)
    fig.tight_layout(h_pad=1.2)
    fig.savefig(out / "fig_design.png", dpi=200, facecolor="white")
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--real", default="data/real/chair45", help="preprocess_h10.py로 만든 실측 폴더 (45 cm 착석 30회)")
    ap.add_argument("--sim", default="data/sim/P01", help="실측 기반 시뮬레이션 참가자 폴더")
    ap.add_argument("--out", default="poster/figs")
    ap.add_argument("--palette", choices=["poster", "slides"], default="poster")
    ap.add_argument("--anatomy", help="glute.png, hamstring.png가 있는 폴더 (없으면 직접 그린 근육 사용)")
    ap.add_argument("--highlight", type=int, help="후반을 빠르게 만들 실측 시행 번호 (기본: 착석 시간이 중간인 시행)")
    ap.add_argument("--late-k", type=float, default=1.5, help="후반을 몇 배 빠르게 만들지")
    ap.add_argument("--raw45", help="45 cm 원본 기록 하나 (fig_session.png)")
    ap.add_argument("--raw30", help="30 cm 원본 기록 하나 (fig_session.png)")
    args = ap.parse_args()
    use_palette(args.palette)
    if args.anatomy:
        for kind, name in (("glute", "glute.png"), ("ham", "hamstring.png")):
            if (Path(args.anatomy) / name).exists():
                ANATOMY[kind] = Path(args.anatomy) / name
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if args.raw45 and args.raw30:
        fig_session(Path(args.raw45), Path(args.raw30), out)
    fig_posture(out, ink="#1e1e1e" if args.palette == "poster" else None)
    fig_terms(out)
    fig_muscles(out)

    real = load_participant(Path(args.real))
    prof = Profile.from_trials(real["calib"])
    # 실측에는 털썩 앉은 시행이 없어서, 평범한 시행 하나의 후반만 빠르게 만든 가상 시행으로 반응을 보인다
    durs = [float(df["time_s"].iloc[-1]) for df in real["calib"]]
    k = args.highlight - 1 if args.highlight else int(np.argsort(durs)[len(durs) // 2])
    fast = speed_up_late(real["calib"][k], args.late_k)
    loo = Profile.from_trials(real["calib"][:k] + real["calib"][k + 1:])     # 자기 자신이 기준에 섞이지 않게
    label = f"후반 {args.late_k:g}배 빠른 가상 착석 (rep{k + 1:02d})"
    fig_profile(real, prof, out)                    # 개인 기준은 실측 착석만으로 그린다
    fig_design(real, out, args.late_k)
    fig_trial(fast, loo, out, name="fig_trial_real.png", window=(0.4, float(fast["time_s"].iloc[-1])))
    print(f"강조 시행: rep{k + 1:02d}, 후반 {args.late_k:g}배")

    chair_stats = HERE_ROOT / "results" / "real" / "chair_stats.json"
    if chair_stats.exists():
        st = json.loads(chair_stats.read_text())
        st["_profile"] = str(HERE_ROOT / "results" / "real" / "profile_45ref.json")
        fig_chairs(HERE_ROOT / "data" / "real" / "chair45", HERE_ROOT / "data" / "real" / "chair30", st, out)

    sim = load_participant(Path(args.sim))
    sim_prof = Profile.from_trials(sim["calib"])
    fig_compare(sim, sim_prof, out)
    fig_compare(sim, sim_prof, out, tall=True)
    tr = next(t for t in sim["trials"] if t["cond"] == 3 and t["rep"] == 1)
    fig_trial(tr["df"], sim_prof, out)
    print(f"{out}/ 에 그림을 저장했습니다.")


if __name__ == "__main__":
    main()
