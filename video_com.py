"""옆에서 찍은 영상으로 CoM(몸 전체 무게중심)을 계산하고, H10이 CoM 대신 보는 신호와 비교한다.

H10에는 정강이 · 발 센서가 없어 CoM이 발 뒤로 빠졌는지 직접 알 수 없다. 그래서 실험실에서만
카메라로 CoM 정답을 만들고, H10의 상체 숙임 · 착석 속도가 그 정답을 따라가는지 확인한다.
카메라는 검증용이고 실제 제어에는 쓰지 않는다.

1) 영상 → 관절 좌표 (MediaPipe Pose. 다른 포즈 도구의 좌표 CSV도 받는다)
2) 관절 좌표 → CoM (Winter 2009 분절 질량비, 옆에서 본 2D)
3) 영상의 착석 순간(엉덩이 하강이 멈춘 프레임)과 H10의 착석 충격(허벅지 IMU)으로 시간을 맞춘다
4) 앉기마다 CoM–발목 앞뒤 거리, CoM 하강 속도(영상)와 상체 숙임, 착석 속도(H10)를 비교한다

    # 영상에서 관절 좌표 뽑기 (한 번만, 결과는 CSV로 저장)
    python video_com.py extract data/video/45cm_1.mp4 --out data/video/45cm_1_pose.csv
    # H10 로그와 맞춰 앉기별 표 만들기
    python video_com.py analyze data/video/45cm_1_pose.csv ~/Downloads/11.4_45cm_10times_1.csv \
        --chair "45 cm" --leg-cm 90 --out results/video
    # 모든 앉기를 모아 의자별 상관 분석 + 그래프
    python video_com.py summary results/video

영상 · 좌표 · 결과는 사람 데이터라 data/, results/ 아래에 두고 저장소에 올리지 않는다.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.signal import butter, sosfiltfilt

G = 9.81
SYNC_TOL_S = 0.15

# MediaPipe Pose 33점 중 CoM에 쓰는 점 (번호는 MediaPipe 기준)
LANDMARKS = {
    "ear": (7, 8), "shoulder": (11, 12), "elbow": (13, 14), "wrist": (15, 16), "index": (19, 20),
    "hip": (23, 24), "knee": (25, 26), "ankle": (27, 28), "heel": (29, 30), "toe": (31, 32),
}
SIDES = ("l", "r")

# Winter DA (2009) Biomechanics and Motor Control of Human Movement, Table 4.1
# (분절, 몸무게 비율, 근위점, 원위점, 근위점에서 CoM까지 비율). 팔다리는 한쪽 기준이라 양쪽을 더한다.
SEGMENTS = [
    ("hand", 0.006, "wrist", "index", 0.506),
    ("forearm", 0.016, "elbow", "wrist", 0.430),
    ("upper_arm", 0.028, "shoulder", "elbow", 0.436),
    ("thigh", 0.100, "hip", "knee", 0.433),
    ("shank", 0.0465, "knee", "ankle", 0.433),
    ("foot", 0.0145, "heel", "toe", 0.500),
]
TRUNK = ("trunk", 0.497, "hip", "shoulder", 0.500)      # 대전자 → 어깨
HEAD = ("head_neck", 0.081, "ear")                       # 머리 · 목 CoM ≈ 귓구멍


# ---------------------------------------------------------------- 1) 영상 → 관절 좌표

def extract_pose(video: Path, model: Path | None = None) -> pd.DataFrame:
    """영상 프레임마다 관절 좌표(px)와 보이는 정도(0~1)를 뽑는다. mediapipe, opencv-python이 필요하다."""
    try:
        import cv2
        import mediapipe as mp
    except ImportError as e:
        raise SystemExit("영상 처리에는 mediapipe와 opencv-python이 필요합니다: pip install mediapipe opencv-python") from e

    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise SystemExit(f"영상을 열 수 없습니다: {video}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    w, h = cap.get(cv2.CAP_PROP_FRAME_WIDTH), cap.get(cv2.CAP_PROP_FRAME_HEIGHT)

    legacy = getattr(getattr(mp, "solutions", None), "pose", None)
    if model is None and legacy is not None:
        pose = legacy.Pose(model_complexity=2, smooth_landmarks=True, min_detection_confidence=0.5)
        detect = lambda rgb, ms: (lambda r: r.pose_landmarks.landmark if r.pose_landmarks else None)(pose.process(rgb))
    else:
        if model is None:
            raise SystemExit("이 mediapipe 버전에는 예전 Pose API가 없습니다. --model pose_landmarker_full.task 를 주세요 "
                             "(https://developers.google.com/mediapipe/solutions/vision/pose_landmarker 에서 받기).")
        from mediapipe.tasks import python as mpt
        from mediapipe.tasks.python import vision
        opts = vision.PoseLandmarkerOptions(base_options=mpt.BaseOptions(model_asset_path=str(model)),
                                            running_mode=vision.RunningMode.VIDEO, num_poses=1)
        landmarker = vision.PoseLandmarker.create_from_options(opts)

        def detect(rgb, ms):
            r = landmarker.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), ms)
            return r.pose_landmarks[0] if r.pose_landmarks else None

    rows, i = [], 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        t = i / fps
        lm = detect(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB), int(round(t * 1000)))
        row = {"time_s": t}
        for name, idx in LANDMARKS.items():
            for side, k in zip(SIDES, idx):
                p = lm[k] if lm is not None else None
                row[f"{name}_{side}_x"] = p.x * w if p is not None else np.nan
                row[f"{name}_{side}_y"] = p.y * h if p is not None else np.nan
                vis = getattr(p, "visibility", 1.0) if p is not None else 0.0
                row[f"{name}_{side}_v"] = float(vis) if vis is not None else 1.0
        rows.append(row)
        i += 1
    cap.release()
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- 2) 관절 좌표 → CoM

def _lowpass(x: np.ndarray, fs: float, fc: float = 6.0) -> np.ndarray:
    if fs <= 2.5 * fc or len(x) < 16:
        return x
    return sosfiltfilt(butter(4, fc / (fs / 2), output="sos"), x, axis=0)


def pick_side(lm: pd.DataFrame) -> str:
    """카메라 쪽(더 잘 보이는) 다리를 고른다. 반대쪽은 몸에 가려 좌표가 흔들린다."""
    vis = {s: np.nanmean([lm[f"{n}_{s}_v"].mean() for n in ("hip", "knee", "ankle", "heel", "toe")]) for s in SIDES}
    return max(vis, key=vis.get)


def clean_landmarks(lm: pd.DataFrame, side: str, min_vis: float = 0.5) -> dict[str, np.ndarray]:
    """고른 쪽 관절 좌표를 (N, 2) 배열로. 위쪽이 +y가 되게 뒤집고, 안 보이는 프레임은 보간 후 6 Hz 저역통과."""
    t = lm["time_s"].to_numpy(dtype=float)
    fs = 1.0 / np.median(np.diff(t)) if len(t) > 1 else 30.0
    pts = {}
    for name in LANDMARKS:
        x = lm[f"{name}_{side}_x"].to_numpy(dtype=float).copy()
        y = -lm[f"{name}_{side}_y"].to_numpy(dtype=float).copy()
        v = lm.get(f"{name}_{side}_v", pd.Series(np.ones(len(lm)))).to_numpy(dtype=float)
        bad = ~np.isfinite(x) | ~np.isfinite(y) | (v < min_vis)
        if bad.all():
            raise ValueError(f"{name}({side}) 좌표가 한 프레임도 보이지 않습니다. 몸 전체(발 포함)가 화면에 들어와야 합니다.")
        for a in (x, y):
            a[bad] = np.interp(t[bad], t[~bad], a[~bad])
        pts[name] = _lowpass(np.column_stack([x, y]), fs)
    return pts


def segment_com(pts: dict[str, np.ndarray]) -> np.ndarray:
    """분절 질량비로 가중 평균한 CoM (N, 2). 팔다리는 보이는 쪽을 양쪽으로 쓴다(옆에서 보면 좌우가 거의 겹친다)."""
    com = np.zeros_like(pts["hip"])
    total = 0.0
    for _, m, prox, dist, r in SEGMENTS:
        com += 2 * m * (pts[prox] + r * (pts[dist] - pts[prox]))
        total += 2 * m
    _, m, prox, dist, r = TRUNK
    com += m * (pts[prox] + r * (pts[dist] - pts[prox]))
    _, mh, at = HEAD
    com += mh * pts[at]
    total += m + mh
    return com / total


def com_frame(lm: pd.DataFrame, leg_cm: float | None = None, side: str | None = None) -> pd.DataFrame:
    """프레임별 CoM과 CoM–발목 앞뒤 거리.

    com_ankle_dx: (CoM x − 발목 x), 바라보는 방향이 +. 다리 길이(엉덩이–무릎–발목)로 나눈 값.
                  음수면 CoM이 발목보다 뒤에 있다.
    com_vz:       CoM 위아래 속도 (다리 길이/s, 아래로 내려가면 음수)
    leg_cm를 주면 cm, m/s 단위 열과 외삽 CoM(Hof 2005: x + v/√(g/l))도 계산한다.
    """
    side = side or pick_side(lm)
    pts = clean_landmarks(lm, side)
    t = lm["time_s"].to_numpy(dtype=float)
    com = segment_com(pts)
    leg_px = float(np.median(np.linalg.norm(pts["knee"] - pts["hip"], axis=1)
                             + np.linalg.norm(pts["ankle"] - pts["knee"], axis=1)))
    facing = 1.0 if np.median(pts["toe"][:, 0] - pts["heel"][:, 0]) >= 0 else -1.0
    dx = (com[:, 0] - pts["ankle"][:, 0]) * facing / leg_px
    z = com[:, 1] / leg_px
    vx = np.gradient(dx, t)
    vz = np.gradient(z, t)
    hip_z = pts["hip"][:, 1] / leg_px
    out = pd.DataFrame({"time_s": t, "com_x_px": com[:, 0], "com_y_px": -com[:, 1],
                        "com_ankle_dx": dx, "com_z": z - z[: max(1, len(z) // 20)].mean(),
                        "com_vx": vx, "com_vz": vz,
                        "hip_z": hip_z, "hip_vz": np.gradient(hip_z, t)})
    out.attrs.update(side=side, facing=facing, leg_px=leg_px)
    if leg_cm:
        L = leg_cm / 100.0
        out["com_ankle_dx_cm"] = dx * leg_cm
        out["com_vz_ms"] = vz * L
        w0 = np.sqrt(G / L)
        out["xcom_ankle_dx_cm"] = (dx + vx / w0) * leg_cm      # 외삽 CoM: 속도까지 고려한 '넘어지는 방향'
    return out


# ---------------------------------------------------------------- 3) 착석 순간 · 시간 맞추기

def video_sit_events(cf: pd.DataFrame, min_drop: float = 0.15) -> list[dict]:
    """엉덩이가 내려가다 멈춘 순간 = 영상의 착석 순간.

    엉덩이 높이가 다리 길이의 min_drop 이상 떨어진 하강 구간마다, 하강 속도 최대점 이후 속도가
    최대의 10% 아래로 줄어든 첫 프레임을 착석으로 본다.
    """
    t, z, vz = cf["time_s"].to_numpy(), cf["hip_z"].to_numpy(), cf["hip_vz"].to_numpy()
    down = -vz
    events, i, n = [], 0, len(t)
    thr = 0.15                      # 다리 길이/s, 이보다 빠르게 내려가면 하강 중
    while i < n:
        if down[i] <= thr:
            i += 1
            continue
        j = i
        while j < n and down[j] > 0.3 * thr:
            j += 1
        seg = slice(i, j)
        if z[i] - z[min(j, n - 1)] >= min_drop:
            pk = i + int(np.argmax(down[seg]))
            slow = np.nonzero(down[pk:j] < 0.1 * down[pk])[0]
            contact = pk + int(slow[0]) if len(slow) else min(j, n - 1)
            back = np.nonzero(down[:pk][::-1] < 0.1 * down[pk])[0]
            start = pk - int(back[0]) if len(back) else i
            events.append({"start": start, "peak": pk, "contact": contact,
                           "start_t": t[start], "contact_t": t[contact]})
        i = j + 1
    return events


def find_offset(video_t: list[float], h10_t: list[float], tol: float = SYNC_TOL_S) -> tuple[float, int]:
    """H10 시간 = 영상 시간 + offset. 가장 많은 착석이 tol 안에서 겹치는 offset을 찾는다."""
    v, h = np.asarray(video_t, float), np.asarray(h10_t, float)
    if len(v) == 0 or len(h) == 0:
        raise ValueError("착석이 영상이나 H10 로그에서 한 번도 검출되지 않았습니다.")
    n, err, off = -1, np.inf, 0.0
    for cand in (h[:, None] - v[None, :]).ravel():
        d = np.abs(h[None, :] - (v[:, None] + cand)).min(axis=1)
        hit = d <= tol
        c, e = int(hit.sum()), float(d[hit].mean()) if hit.any() else np.inf
        if c > n or (c == n and e < err):
            n, err, off = c, e, float(cand)
    # 겹친 쌍의 잔차 중앙값으로 다듬기
    res = []
    for tv in v:
        k = int(np.argmin(np.abs(h - (tv + off))))
        if abs(h[k] - (tv + off)) <= tol:
            res.append(h[k] - tv)
    return (float(np.median(res)) if res else float(off)), int(n)


def h10_sit_events(d: pd.DataFrame, impact_thr: float = 3.0) -> list[dict]:
    """100 Hz H10 표(preprocess_h10.to_100hz)에서 앉기마다 착석 순간과 비교 지표를 계산한다.

    contact_t:  엉덩이가 닿은 순간(허벅지 IMU 충격 > impact_thr, 없으면 허벅지 속도가 느려진 순간)
    peak_lean:  서 있을 때 대비 최대 상체 숙임 (deg)
    contact_vel: 닿는 순간 허벅지 굽힘 속도 (deg/s)
    late_vel:   착석 각도의 절반을 넘은 뒤 평균 허벅지 굽힘 속도 (deg/s) = 후반 하강 속도
    각도 기준은 앉기 전 가장 똑바로 선 순간이라, compare_chairs.py의 착석 각도와 몇 도 다를 수 있다.
    """
    from preprocess_h10 import FS, find_sit_downs

    fs = FS
    th = d[["thigh_l_deg", "thigh_r_deg"]].mean(axis=1).to_numpy(dtype=float)
    th = sosfiltfilt(butter(4, 6.0 / (fs / 2), output="sos"), th)
    w = np.gradient(th) * fs
    trunk = sosfiltfilt(butter(4, 4.0 / (fs / 2), output="sos"), d["trunk_deg"].to_numpy(dtype=float))
    impact = None
    if "acc_ms2" in d:
        a = d["acc_ms2"].to_numpy(dtype=float)
        impact = a - sosfiltfilt(butter(2, 1.0 / (fs / 2), output="sos"), a)
    out = []
    for ev in find_sit_downs(d):
        on, pk, end = ev["onset"], ev["peak"], ev["end"]
        contact = end
        if impact is not None:
            hi = min(end + 30, len(w))
            j = pk + int(np.argmax(impact[pk:hi]))
            if impact[j] > impact_thr:
                contact = j
        base_th, base_tr = th[ev["upright"]], trunk[ev["upright"]]
        depth = th[contact] - base_th
        late = np.arange(on, contact + 1)[th[on:contact + 1] - base_th >= depth / 2]
        out.append({"onset_t": on / fs, "contact_t": contact / fs,
                    "contact_dtheta": float(depth),
                    "peak_lean": float((trunk[on:contact + 1] - base_tr).max()),
                    "contact_vel": float(w[max(contact - 2, on)]),
                    "late_vel": float(w[late].mean()) if len(late) else np.nan})
    return out


# ---------------------------------------------------------------- 4) 앉기별 비교

def sit_table(cf: pd.DataFrame, vev: list[dict], hev: list[dict], offset: float,
              tol: float = SYNC_TOL_S) -> pd.DataFrame:
    """영상 착석과 H10 착석을 짝지어 앉기별 지표를 한 줄씩 만든다."""
    h_t = np.array([e["contact_t"] for e in hev])
    cm = "com_ankle_dx_cm" in cf
    rows = []
    for e in vev:
        k = int(np.argmin(np.abs(h_t - (e["contact_t"] + offset))))
        lag = h_t[k] - (e["contact_t"] + offset)
        if abs(lag) > tol:
            continue
        s, c = e["start"], e["contact"]
        win = cf.iloc[s:c + 1]
        r = {"video_contact_t": e["contact_t"], "h10_contact_t": h_t[k], "sync_lag_s": lag,
             "dx_contact": cf["com_ankle_dx"].iloc[c], "dx_min": win["com_ankle_dx"].min(),
             "com_vz_contact": cf["com_vz"].iloc[max(c - 1, s)], "com_drop": win["com_z"].iloc[0] - win["com_z"].iloc[-1]}
        if cm:
            r.update(dx_contact_cm=cf["com_ankle_dx_cm"].iloc[c], dx_min_cm=win["com_ankle_dx_cm"].min(),
                     com_vz_contact_ms=cf["com_vz_ms"].iloc[max(c - 1, s)],
                     xcom_min_cm=win["xcom_ankle_dx_cm"].min())
        r.update({f"h10_{key}": val for key, val in hev[k].items() if key not in ("onset_t", "contact_t")})
        rows.append(r)
    return pd.DataFrame(rows)


PAIRS = [("dx_min", "h10_peak_lean", "가장 뒤로 간 CoM–발목 거리 vs H10 최대 상체 숙임"),
         ("dx_contact", "h10_peak_lean", "착석 순간 CoM–발목 거리 vs H10 최대 상체 숙임"),
         ("com_vz_contact", "h10_contact_vel", "착석 순간 CoM 하강 속도 vs H10 착석 속도"),
         ("com_vz_contact", "h10_late_vel", "착석 순간 CoM 하강 속도 vs H10 후반 하강 속도")]


def correlations(sits: pd.DataFrame) -> pd.DataFrame:
    from scipy.stats import pearsonr, spearmanr
    rows = []
    for chair, g in [("전체", sits)] + list(sits.groupby("chair")):
        for a, b, desc in PAIRS:
            x, y = g[a].to_numpy(float), g[b].to_numpy(float)
            ok = np.isfinite(x) & np.isfinite(y)
            n = int(ok.sum())
            r = {"chair": chair, "video": a, "h10": b, "설명": desc, "n": n}
            if n >= 3 and np.std(x[ok]) > 0 and np.std(y[ok]) > 0:
                pr, pp = pearsonr(x[ok], y[ok])
                sr, sp = spearmanr(x[ok], y[ok])
                r.update(pearson_r=pr, pearson_p=pp, spearman_r=sr, spearman_p=sp)
            rows.append(r)
    return pd.DataFrame(rows)


def plot_summary(sits: pd.DataFrame, path: Path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    for f in ("Noto Sans KR", "AppleGothic", "Malgun Gothic", "NanumGothic"):
        if any(f == x.name for x in font_manager.fontManager.ttflist):
            plt.rcParams["font.family"] = f
            break
    plt.rcParams["axes.unicode_minus"] = False
    fig, axes = plt.subplots(1, len(PAIRS), figsize=(4.2 * len(PAIRS), 3.8))
    colors = {"45 cm": "#8a8f8c", "30 cm": "#3f9d63"}
    for ax, (a, b, desc) in zip(axes, PAIRS):
        for chair, g in sits.groupby("chair"):
            ax.scatter(g[b], g[a], s=22, alpha=0.8, label=chair, color=colors.get(chair))
        ax.set_xlabel(b.replace("h10_", "H10 "))
        ax.set_ylabel(a)
        ax.set_title(desc, fontsize=9)
        ax.grid(alpha=0.3)
    axes[0].legend(frameon=False)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


# ---------------------------------------------------------------- CLI

def _h10_table(path: Path) -> pd.DataFrame:
    from h10_decode import decode_file
    from preprocess_h10 import to_100hz
    return to_100hz(decode_file(path))


def cmd_extract(a):
    lm = extract_pose(Path(a.video), Path(a.model) if a.model else None)
    out = Path(a.out or Path(a.video).with_name(Path(a.video).stem + "_pose.csv"))
    out.parent.mkdir(parents=True, exist_ok=True)
    lm.round(2).to_csv(out, index=False)
    seen = lm["hip_l_v"].gt(0).mean()
    print(f"{len(lm)}프레임, 사람 검출 {seen:.0%} → {out}")


def cmd_analyze(a):
    pose = Path(a.pose)
    lm = extract_pose(pose, Path(a.model) if a.model else None) if pose.suffix.lower() != ".csv" else pd.read_csv(pose)
    cf = com_frame(lm, a.leg_cm)
    vev = video_sit_events(cf)
    hev = h10_sit_events(_h10_table(Path(a.h10)))
    if a.offset is not None:
        off, n = a.offset, -1
    else:
        off, n = find_offset([e["contact_t"] for e in vev], [e["contact_t"] for e in hev])
    sits = sit_table(cf, vev, hev, off)
    sits.insert(0, "chair", a.chair)
    sits.insert(1, "source", pose.stem)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    cf.round(4).to_csv(out / f"{pose.stem}_com.csv", index=False)
    sits.round(4).to_csv(out / f"{pose.stem}_sits.csv", index=False)
    info = {"side": cf.attrs["side"], "facing": cf.attrs["facing"], "leg_px": cf.attrs["leg_px"],
            "video_sits": len(vev), "h10_sits": len(hev), "matched": len(sits), "offset_s": off}
    (out / f"{pose.stem}_sync.json").write_text(json.dumps(info, indent=2, ensure_ascii=False))
    print(f"영상 착석 {len(vev)}회, H10 착석 {len(hev)}회, 짝 {len(sits)}회 (H10 시간 = 영상 + {off:.2f} s)")
    if len(sits) < min(len(vev), len(hev)):
        print("  짝이 안 맞은 착석이 있습니다. 영상과 H10 기록 구간이 같은지, --offset으로 직접 맞출지 확인하세요.")
    if len(sits):
        cols = [c for c in ("dx_contact", "dx_min", "com_vz_contact", "h10_peak_lean", "h10_contact_vel", "h10_late_vel")
                if c in sits]
        print(sits[cols].describe().loc[["mean", "std"]].round(3).to_string())


def cmd_summary(a):
    d = Path(a.dir)
    files = sorted(d.glob("*_sits.csv"))
    if not files:
        raise SystemExit(f"{d}에 *_sits.csv가 없습니다. 먼저 analyze를 돌리세요.")
    sits = pd.concat([pd.read_csv(f) for f in files], ignore_index=True)
    corr = correlations(sits)
    corr.round(4).to_csv(d / "com_vs_h10_correlations.csv", index=False)
    sits.round(4).to_csv(d / "all_sits.csv", index=False)
    plot_summary(sits, d / "com_vs_h10.png")
    by = sits.groupby("chair")[[c for c in ("dx_contact", "dx_min", "com_vz_contact") if c in sits]].agg(["mean", "std", "count"])
    print(by.round(3).to_string())
    print()
    print(corr[["chair", "설명", "n", "pearson_r", "spearman_r", "spearman_p"]].round(3).to_string(index=False))
    print(f"\n→ {d / 'com_vs_h10_correlations.csv'}, {d / 'com_vs_h10.png'}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("extract", help="영상 → 관절 좌표 CSV")
    p.add_argument("video")
    p.add_argument("--out")
    p.add_argument("--model", help="MediaPipe Tasks 모델(.task). 예전 Pose API가 없을 때만 필요")
    p.set_defaults(fn=cmd_extract)
    p = sub.add_parser("analyze", help="관절 좌표(또는 영상) + H10 로그 → 앉기별 표")
    p.add_argument("pose", help="extract가 만든 CSV 또는 영상 파일")
    p.add_argument("h10", help="같은 시간에 기록한 H10 로그 (앱 CSV 또는 SUIT 로그)")
    p.add_argument("--chair", required=True, help='예: "45 cm"')
    p.add_argument("--leg-cm", type=float, help="다리 길이(대전자~바깥 복사뼈, cm). 주면 cm 단위도 계산")
    p.add_argument("--offset", type=float, help="H10 시간 = 영상 시간 + offset (자동 맞춤 대신)")
    p.add_argument("--model")
    p.add_argument("--out", default="results/video")
    p.set_defaults(fn=cmd_analyze)
    p = sub.add_parser("summary", help="앉기별 표를 모아 의자별 상관 분석")
    p.add_argument("dir", nargs="?", default="results/video")
    p.set_defaults(fn=cmd_summary)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
