"""기록된 착석 데이터 전체로 성능 지표를 계산한다.

    python evaluate.py data --out results
    python evaluate.py data --out results --plot P01 3 1    # 한 시행 그래프

- 기준값은 각 참가자의 calib_rep*.csv로 다시 만든다.
- 지표(최대 굴곡 속도, 각가속도, jerk, 착석 순간 속도, 착석 시간)는 기록된 각도에서
  오프라인(양방향 필터)으로 계산한다. 실시간 판단과는 따로다.
- calib 시행은 한 번씩 빼고 기준을 만든 뒤 빼 둔 시행에 돌려(leave-one-out),
  정상 착석에서 제동이 잘못 켜지는 비율을 본다.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.signal import butter, sosfiltfilt

from sit_assist import Config, Phase, Profile, run_trial

CONDITION_NAMES = {1: "45 cm", 2: "30 cm + H10 OFF", 3: "30 cm + H10"}
TRIAL_RE = re.compile(r"cond(\d+)_rep(\d+)\.csv")
TRIGGER_NM = 1.0        # 계산된 제동 토크가 이보다 크면 '제동이 켜졌다'
METRICS = ["peak_vel", "peak_acc", "rms_jerk", "ldlj", "contact_vel", "descent_time", "peak_lean"]
METRIC_NAMES = {"peak_vel": "최대 허벅지 굴곡 속도 (deg/s)", "peak_acc": "최대 각가속도 (deg/s²)",
                "rms_jerk": "RMS jerk (deg/s³)", "ldlj": "LDLJ (클수록 부드러움)",
                "contact_vel": "착석 순간 속도 (deg/s)", "descent_time": "착석 시간 (s)",
                "peak_lean": "최대 상체 숙임 (deg)"}
BETTER = {"peak_vel": -1, "peak_acc": -1, "rms_jerk": -1, "ldlj": 1,
          "contact_vel": -1, "descent_time": 0, "peak_lean": 1}


# ---------------------------------------------------------------- 지표

def offline_kinematics(df: pd.DataFrame, fs: float = 100.0) -> dict:
    """양쪽 평균 허벅지 각도의 속도·가속도·jerk, 상체 숙임 (양방향 필터라 지연 없음)."""
    sos6 = butter(4, 6.0 / (fs / 2), output="sos")
    sos4 = butter(4, 4.0 / (fs / 2), output="sos")
    th = sosfiltfilt(sos6, df[["thigh_l_deg", "thigh_r_deg"]].to_numpy(dtype=float), axis=0)
    w = np.gradient(th, 1 / fs, axis=0)
    acc = sosfiltfilt(sos4, np.gradient(w.mean(axis=1), 1 / fs))
    jerk = sosfiltfilt(sos4, np.gradient(acc, 1 / fs))
    lean = None
    if "trunk_deg" in df:
        trunk = sosfiltfilt(sos4, df["trunk_deg"].to_numpy(dtype=float))
        lean = trunk - trunk[: int(0.5 * fs)].mean()       # 처음 0.5초(서 있음) 대비
    impact = None
    if "acc_ms2" in df:                                  # 가속도 크기의 빠른 변화 = 착석 충격 (양방향 고역통과)
        a_ = df["acc_ms2"].to_numpy(dtype=float)
        impact = a_ - sosfiltfilt(butter(2, 1.0 / (fs / 2), output="sos"), a_)
    return {"t": df["time_s"].to_numpy(dtype=float), "w": w, "wm": w.mean(axis=1),
            "acc": acc, "jerk": jerk, "lean": lean, "impact": impact}


def descent_window(k: dict, seat: np.ndarray | None, cfg: Config = Config()) -> tuple[int, int]:
    """착석 시작(최대 속도 이전 마지막으로 onset_vel 아래였던 곳) ~ 엉덩이가 닿은 곳."""
    wm = k["wm"]
    peak = int(np.argmax(wm))
    below = np.nonzero(wm[:peak] < cfg.onset_vel)[0]
    start = int(below[-1]) + 1 if len(below) else 0
    if seat is not None and (seat[peak:] > 0.5).any():
        end = peak + int(np.argmax(seat[peak:] > 0.5))
    else:
        slow = np.nonzero(wm[peak:] < cfg.seat_vel)[0]
        end = peak + int(slow[0]) if len(slow) else len(wm) - 1
        if k.get("impact") is not None:            # IMU 충격이 있으면 그 순간이 엉덩이가 닿은 때
            hi = min(end + 30, len(wm))
            j = peak + int(np.argmax(k["impact"][peak:hi]))
            if k["impact"][j] > cfg.impact_thr:
                end = j
    return start, end


def trial_metrics(df: pd.DataFrame, cfg: Config = Config()) -> dict:
    k = offline_kinematics(df, cfg.fs)
    seat = df["seat"].to_numpy(dtype=float) if "seat" in df else None
    s, e = descent_window(k, seat, cfg)
    sl = slice(s, e + 1)
    dur = k["t"][e] - k["t"][s]
    v_peak = k["wm"][sl].max()
    out = {"peak_vel": v_peak,
           "peak_vel_l": k["w"][sl, 0].max(), "peak_vel_r": k["w"][sl, 1].max(),
           "peak_acc": k["acc"][sl].max(),
           "rms_jerk": float(np.sqrt(np.mean(k["jerk"][sl] ** 2))),
           # log dimensionless jerk: 시간·속도 크기에 상관없이 매끄러움을 비교하는 지표
           "ldlj": float(-np.log(dur ** 3 / v_peak ** 2 * np.sum(k["jerk"][sl] ** 2) / cfg.fs)),
           "contact_vel": k["wm"][max(e - 2, s)],
           "descent_time": dur,
           "peak_lean": k["lean"][sl].max() if k["lean"] is not None else np.nan}
    if {"tau_cmd_l", "tau_cmd_r"} <= set(df.columns):
        tau = df[["tau_cmd_l", "tau_cmd_r"]].to_numpy(dtype=float).max(axis=1)
        out["peak_tau"] = tau.max()
        out["assist_time"] = np.sum(tau > TRIGGER_NM) / cfg.fs
    if "tau_brake" in df:
        out["brake_time"] = np.sum(df["tau_brake"] > TRIGGER_NM) / cfg.fs
    if "phase" in df:
        out["deep"] = bool((df["phase"] == Phase.DEEP).any())
    if "posture" in df:     # 내려가는 동안 UPRIGHT로 판단된 시간 비율
        moving = df["phase"].isin([Phase.DESCENT, Phase.DEEP])
        out["upright_pct"] = 100 * float((df.loc[moving, "posture"] == 1).mean()) if moving.any() else 0.0
    return out


# ---------------------------------------------------------------- 데이터

def load_participant(pdir: Path) -> dict:
    calib = [pd.read_csv(f) for f in sorted(pdir.glob("calib_rep*.csv"))]
    trials = []
    for f in sorted(pdir.glob("cond*_rep*.csv")):
        m = TRIAL_RE.fullmatch(f.name)
        if m:
            trials.append({"cond": int(m[1]), "rep": int(m[2]), "df": pd.read_csv(f)})
    return {"calib": calib, "trials": trials}


def speed_up_late(df: pd.DataFrame, k: float = 1.5) -> pd.DataFrame:
    """착석 후반(허벅지가 끝 각도의 절반을 지난 뒤)만 k배 빠르게 만든 가상 시행. 털썩 주저앉기 흉내."""
    t = df["time_s"].to_numpy()
    m = df[["thigh_l_deg", "thigh_r_deg"]].mean(axis=1).to_numpy()
    t0 = t[np.argmax(m > m[0] + 0.5 * (m.max() - m[0]))]
    tn = np.arange(0.0, t0 + (t[-1] - t0) / k, 1.0 / 100)
    src = np.where(tn < t0, tn, t0 + (tn - t0) * k)
    out = pd.DataFrame({"time_s": tn.round(3)})
    for c in ("thigh_l_deg", "thigh_r_deg", "trunk_deg", "acc_ms2", "pelvis_gyro_dps"):
        if c in df:
            out[c] = np.interp(src, t, df[c].to_numpy())
    return out


def calib_loo(calib: list[pd.DataFrame], cfg: Config = Config(), late_k: float | None = None) -> pd.DataFrame:
    """calib 한 회씩 빼고 기준을 만들어 빼 둔 회에 돌린다 (정상 착석 오탐 확인)."""
    rows = []
    for i, df in enumerate(calib):
        prof = Profile.from_trials(calib[:i] + calib[i + 1:], cfg)
        log = run_trial(df, prof, cfg, shadow=True)
        brake = log["tau_brake"]
        row = {}
        if late_k:      # 같은 시행의 후반만 빠르게 만들면 제동이 걸리는가 (민감도)
            row["late_brake"] = run_trial(speed_up_late(df, late_k), prof, cfg, shadow=True)["tau_brake"].max()
            row["late_caught"] = row["late_brake"] > TRIGGER_NM
        rows.append({**row, "rep": i + 1, "peak_brake": brake.max(), "triggered": brake.max() > TRIGGER_NM,
                     "strong": bool((log["level"] == 2).any()),
                     "deep": bool((log["phase"] == Phase.DEEP).any()),
                     "upright": bool((log["posture"] == 1).any())})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- 그래프

def plot_trial(df: pd.DataFrame, prof: Profile, title: str, path: Path, cfg: Config = Config()):
    import matplotlib.pyplot as plt
    log = run_trial(df, prof, cfg, shadow=True)
    if {"tau_cmd_l", "tau_cmd_r"} <= set(df.columns):     # 실제로 기록된 토크가 있으면 그것을 그린다
        log[["tau_cmd_l", "tau_cmd_r"]] = df[["tau_cmd_l", "tau_cmd_r"]].to_numpy()
    t = log["time_s"]
    fig, ax = plt.subplots(4, 1, figsize=(9, 10), sharex=True)
    ax[0].plot(t, log["dtheta_l"], label="left")
    ax[0].plot(t, log["dtheta_r"], label="right")
    ax[0].axhline(prof.contact_mean, ls="--", c="gray", lw=1, label="usual seat angle")
    ax[0].axhline(prof.deep_threshold(cfg), ls=":", c="red", lw=1, label="DEEP threshold")
    ax[0].set_ylabel("thigh flexion Δθ (deg)")
    ax[1].plot(t, log["omega_l"], label="ω left")
    m = log["omega_ref_l"] > 0
    ax[1].plot(t[m], log["omega_ref_l"][m], c="k", lw=1, label="personal reference")
    ax[1].set_ylabel("ω (deg/s)")
    ax[2].plot(t, log["lean"], c="tab:purple", label="trunk lean")
    m = log["lean_ref"].notna()
    ax[2].plot(t[m], log["lean_ref"][m], c="k", lw=1, label="personal reference")
    up = (log["posture"] == 1).to_numpy()
    ax[2].scatter(t[up], log["lean"][up], s=4, c="red", label="UPRIGHT", zorder=3)
    ax[2].set_ylabel("trunk lean (deg)")
    ax[3].plot(t, log["tau_cmd_l"], label="τ total left")
    ax[3].plot(t, log["tau_support"], ls="--", c="tab:purple", lw=1, label="τ trunk support (calc)")
    ax[3].plot(t, log["tau_brake"], ls=":", c="tab:red", lw=1, label="τ brake (calc)")
    ax[3].set_ylabel("extension torque (Nm)")
    ax[3].set_xlabel("time (s)")
    for a in ax:
        for ph, color in ((Phase.DEEP, "red"), (Phase.SEATED, "gray")):
            on = (log["phase"] == ph).to_numpy()
            if on.any():
                a.axvspan(t[on].iloc[0], t[on].iloc[-1], color=color, alpha=0.08)
        a.legend(loc="upper left", fontsize=8)
    ax[0].set_title(title)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def plot_compare(p: dict, prof: Profile, pid: str, path: Path, cfg: Config = Config()):
    """같은 참가자의 ω–Δθ 곡선: calib(회색) / 조건별 색."""
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(8, 5))
    colors = {1: "tab:green", 2: "tab:red", 3: "tab:blue"}
    for df in p["calib"]:
        k = offline_kinematics(df, cfg.fs)
        s, e = descent_window(k, df["seat"].to_numpy(dtype=float) if "seat" in df else None, cfg)
        d = df[["thigh_l_deg", "thigh_r_deg"]].mean(axis=1).to_numpy()
        ax.plot(d[s:e] - d[s], k["wm"][s:e], c="gray", lw=0.7, alpha=0.6)
    seen = set()
    for tr in p["trials"]:
        df = tr["df"]
        k = offline_kinematics(df, cfg.fs)
        s, e = descent_window(k, df["seat"].to_numpy(dtype=float) if "seat" in df else None, cfg)
        d = df[["thigh_l_deg", "thigh_r_deg"]].mean(axis=1).to_numpy()
        label = None if tr["cond"] in seen else CONDITION_NAMES.get(tr["cond"], tr["cond"])
        seen.add(tr["cond"])
        ax.plot(d[s:e] - d[s], k["wm"][s:e], c=colors.get(tr["cond"], "k"), lw=1, label=label)
    ax.axvline(prof.contact_mean, ls="--", c="gray", lw=1)
    ax.axvline(prof.deep_threshold(cfg), ls=":", c="red", lw=1)
    ax.text(prof.contact_mean, ax.get_ylim()[1] * 0.95, " usual seat", fontsize=8)
    ax.set_xlabel("thigh flexion from standing Δθ (deg)")
    ax.set_ylabel("thigh flexion velocity (deg/s)")
    ax.set_title(f"{pid}: calibration (gray, standard chair) vs low-chair trials")
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


# ---------------------------------------------------------------- 실행

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data")
    ap.add_argument("--out", default="results")
    ap.add_argument("--plot", nargs=3, metavar=("PID", "COND", "REP"))
    args = ap.parse_args()
    root, out = Path(args.data), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    cfg = Config()

    if args.plot:
        pid, cond, rep = args.plot[0], int(args.plot[1]), int(args.plot[2])
        p = load_participant(root / pid)
        prof = Profile.from_trials(p["calib"], cfg)
        tr = next(t for t in p["trials"] if t["cond"] == cond and t["rep"] == rep)
        path = out / f"{pid}_cond{cond}_rep{rep}.png"
        plot_trial(tr["df"], prof, f"{pid} cond{cond} ({CONDITION_NAMES.get(cond)}) rep{rep}", path, cfg)
        print(f"저장: {path}")
        return

    rows, loo_rows = [], []
    pdirs = sorted(d for d in root.iterdir() if d.is_dir())
    for n, pdir in enumerate(pdirs):
        p = load_participant(pdir)
        if len(p["calib"]) < 3:
            print(f"[건너뜀] {pdir.name}: calib 시행이 3회 미만")
            continue
        prof = Profile.from_trials(p["calib"], cfg)
        prof.save(out / f"{pdir.name}_profile.json")
        for tr in p["trials"]:
            rows.append({"participant": pdir.name, "cond": tr["cond"], "rep": tr["rep"],
                         **trial_metrics(tr["df"], cfg)})
        loo = calib_loo(p["calib"], cfg)
        loo.insert(0, "participant", pdir.name)
        loo_rows.append(loo)
        if n == 0:
            plot_compare(p, prof, pdir.name, out / f"compare_{pdir.name}.png", cfg)
        print(f"{pdir.name} 완료")

    m = pd.DataFrame(rows)
    loo = pd.concat(loo_rows, ignore_index=True)
    m.to_csv(out / "metrics.csv", index=False)
    loo.to_csv(out / "calib_loo.csv", index=False)

    # 참가자별 평균을 먼저 내고, 참가자 사이 평균(SD)
    per = m.groupby(["participant", "cond"])[METRICS].mean().reset_index()
    summary = per.groupby("cond")[METRICS].agg(["mean", "std"])
    summary.to_csv(out / "summary.csv")

    lines = [f"참가자 {per.participant.nunique()}명, 시행 {len(m)}회\n",
             "| 지표 | " + " | ".join(CONDITION_NAMES[c] for c in sorted(per.cond.unique())) + " |",
             "|---|" + "---|" * per.cond.nunique()]
    for k in METRICS:
        cells = [f"{summary.loc[c, (k, 'mean')]:.2f} ({summary.loc[c, (k, 'std')]:.2f})"
                 for c in sorted(per.cond.unique())]
        lines.append(f"| {METRIC_NAMES[k]} | " + " | ".join(cells) + " |")

    if {2, 3} <= set(per.cond):
        a = per[per.cond == 2].set_index("participant")[METRICS]
        b = per[per.cond == 3].set_index("participant")[METRICS]
        change = (b - a) / a.abs() * 100
        lines += ["", "30 cm + H10 vs 30 cm + H10 OFF (참가자별 변화율 평균, 좋아진 사람 수)"]
        for k in METRICS:
            sign = BETTER[k]
            note = "" if sign == 0 else f", 좋아진 사람 {int((np.sign(b[k] - a[k]) == sign).sum())}/{len(a)}"
            lines.append(f"- {METRIC_NAMES[k]}: {change[k].mean():+.1f}%{note}")

    if "upright_pct" in m:
        lines += ["", "내려가는 동안 UPRIGHT(상체를 덜 숙임) 판단 시간 비율: "
                  + ", ".join(f"{CONDITION_NAMES[c]} {m[m.cond == c].upright_pct.mean():.0f}%"
                              for c in sorted(m.cond.unique()))]
    if "deep" in m:
        lines += ["", "낮은 의자에서 DEEP(평소 착석 각도 초과) 감지율: "
                  + ", ".join(f"{CONDITION_NAMES[c]} {m[m.cond == c].deep.mean() * 100:.0f}%"
                              for c in sorted(m.cond.unique()))]
    lines += ["", f"정상 착석(calib, leave-one-out) 제동 켜짐 {loo.triggered.mean() * 100:.1f}%, "
              f"강한 제동 {loo.strong.mean() * 100:.1f}%, DEEP 오감지 {loo.deep.mean() * 100:.1f}%, "
              f"UPRIGHT 오감지 {loo.upright.mean() * 100:.1f}% "
              f"({len(loo)}회)"]
    report = "\n".join(lines)
    (out / "report.md").write_text(report + "\n")
    print("\n" + report)


if __name__ == "__main__":
    main()
