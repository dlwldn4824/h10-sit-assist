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
from scipy.signal import butter, medfilt, sosfiltfilt

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

DEFAULT_MODEL = Path(__file__).resolve().parent / "data" / "models" / "pose_landmarker_heavy.task"
ROTATIONS = (0, 90, 180, 270)            # 시계 방향 회전 각도


def _rotate(frame, deg: int):
    import cv2
    codes = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180, 270: cv2.ROTATE_90_COUNTERCLOCKWISE}
    return cv2.rotate(frame, codes[deg]) if deg else frame


def _detector(model: Path | None, video_mode: bool):
    """프레임(RGB) → 33점 목록 또는 None. 예전 mp.solutions.pose가 있으면 그걸, 없으면 Tasks 모델을 쓴다."""
    import mediapipe as mp
    legacy = getattr(getattr(mp, "solutions", None), "pose", None)
    if model is None and legacy is not None:
        pose = legacy.Pose(static_image_mode=not video_mode, model_complexity=2, smooth_landmarks=video_mode,
                           min_detection_confidence=0.5)
        return lambda rgb, ms: (lambda r: r.pose_landmarks.landmark if r.pose_landmarks else None)(pose.process(rgb))
    model = model or DEFAULT_MODEL
    if not Path(model).exists():
        raise SystemExit("이 mediapipe 버전에는 예전 Pose API가 없어 Tasks 모델이 필요합니다. "
                         f"pose_landmarker_heavy.task를 {DEFAULT_MODEL}에 두거나 --model로 주세요 "
                         "(https://developers.google.com/mediapipe/solutions/vision/pose_landmarker).")
    from mediapipe.tasks import python as mpt
    from mediapipe.tasks.python import vision
    mode = vision.RunningMode.VIDEO if video_mode else vision.RunningMode.IMAGE
    lmk = vision.PoseLandmarker.create_from_options(vision.PoseLandmarkerOptions(
        base_options=mpt.BaseOptions(model_asset_path=str(model)), running_mode=mode, num_poses=1))

    def detect(rgb, ms):
        img = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
        r = lmk.detect_for_video(img, ms) if video_mode else lmk.detect(img)
        return r.pose_landmarks[0] if r.pose_landmarks else None
    return detect


def guess_rotation(video: Path, model: Path | None = None, n: int = 8) -> int:
    """폰을 눕혀 찍은 영상을 바로 세울 회전 각도. 몇 프레임을 네 방향으로 돌려 보고,
    사람이 잘 잡히고 엉덩이가 발목보다 위에 오는 방향을 고른다."""
    import cv2
    cap = cv2.VideoCapture(str(video))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    frames = []
    for k in range(n):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(total * (k + 0.5) / n))
        ok, f = cap.read()
        if ok:
            frames.append(cv2.cvtColor(f, cv2.COLOR_BGR2RGB))
    cap.release()
    detect = _detector(model, video_mode=False)
    score = {}
    for deg in ROTATIONS:
        s = 0.0
        for f in frames:
            lm = detect(_rotate(f, deg), 0)
            if lm is None:
                continue
            hip = (lm[23].y + lm[24].y) / 2
            ankle = (lm[27].y + lm[28].y) / 2
            s += 1.0 + (1.0 if ankle > hip + 0.1 else -1.0)      # 이미지 y는 아래로 +
        score[deg] = s
    return max(score, key=score.get)


def extract_pose(video: Path, model: Path | None = None, rotate: int | str = "auto") -> pd.DataFrame:
    """영상 프레임마다 관절 좌표(px)와 보이는 정도(0~1)를 뽑는다. mediapipe, opencv-python이 필요하다.

    rotate: 시계 방향 회전 각도(0/90/180/270) 또는 "auto"(폰을 눕혀 찍은 영상 자동 감지).
    """
    try:
        import cv2
        import mediapipe  # noqa: F401
    except ImportError as e:
        raise SystemExit("영상 처리에는 mediapipe와 opencv-python이 필요합니다: pip install mediapipe opencv-python") from e

    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise SystemExit(f"영상을 열 수 없습니다: {video}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    deg = guess_rotation(video, model) if rotate == "auto" else int(rotate)
    detect = _detector(model, video_mode=True)

    rows, i = [], 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        frame = _rotate(frame, deg)
        h, w = frame.shape[:2]
        t = i / fps
        lm = detect(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB), int(round(t * 1000)))
        row = {"time_s": t, "frame_w": w, "frame_h": h}
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
    df = pd.DataFrame(rows)
    df.insert(1, "rotate", deg)          # overlay가 같은 방향으로 돌릴 수 있게 남긴다
    df.attrs["rotate"] = deg
    return df


# ---------------------------------------------------------------- 2) 관절 좌표 → CoM

def _lowpass(x: np.ndarray, fs: float, fc: float = 6.0) -> np.ndarray:
    if fs <= 2.5 * fc or len(x) < 16:
        return x
    return sosfiltfilt(butter(4, fc / (fs / 2), output="sos"), x, axis=0)


def pick_side(lm: pd.DataFrame) -> str:
    """카메라 쪽(더 잘 보이는) 다리를 고른다. 반대쪽은 몸에 가려 좌표가 흔들린다."""
    vis = {s: np.nanmean([lm[f"{n}_{s}_v"].mean() for n in ("hip", "knee", "ankle", "heel", "toe")]) for s in SIDES}
    return max(vis, key=vis.get)


def clean_landmarks(lm: pd.DataFrame, side: str, min_vis: float = 0.5, min_frac: float = 0.5) -> dict[str, np.ndarray]:
    """고른 쪽 관절 좌표를 (N, 2) 배열로. 위쪽이 +y가 되게 뒤집고, 안 보이는 프레임은 보간 후 6 Hz 저역통과.

    min_frac보다 적은 프레임에서만 보이는 점(화면 밖으로 잘린 머리 · 발 등)은 결과에서 뺀다.
    """
    t = lm["time_s"].to_numpy(dtype=float)
    fs = 1.0 / np.median(np.diff(t)) if len(t) > 1 else 30.0
    pts = {}
    for name in LANDMARKS:
        x = lm[f"{name}_{side}_x"].to_numpy(dtype=float).copy()
        y = -lm[f"{name}_{side}_y"].to_numpy(dtype=float).copy()
        v = lm.get(f"{name}_{side}_v", pd.Series(np.ones(len(lm)))).to_numpy(dtype=float)
        bad = ~np.isfinite(x) | ~np.isfinite(y) | (v < min_vis)
        # MediaPipe는 화면 밖으로 잘린 머리 · 발도 '보인다'며 추측 좌표를 낸다. 화면 밖이면 안 보인 것으로 친다.
        bad |= (x < 0) | (y > 0)                       # y는 이미 뒤집혀 있어 화면 위쪽 밖이면 y > 0
        if "frame_w" in lm:
            bad |= (x > lm["frame_w"].to_numpy(float)) | (-y > lm["frame_h"].to_numpy(float))
        if (~bad).mean() < min_frac:
            continue
        for arr in (x, y):
            arr[bad] = np.interp(t[bad], t[~bad], arr[~bad])
        k = max(3, int(0.2 * fs) | 1)                  # 0.2 s 중앙값 필터: 한두 프레임 튀는 좌표(좌우 뒤바뀜 등) 제거
        if len(x) > k:
            x, y = medfilt(x, k), medfilt(y, k)
        pts[name] = _lowpass(np.column_stack([x, y]), fs)
    if "hip" not in pts:
        raise ValueError("엉덩이 좌표가 대부분 프레임에서 보이지 않습니다. 엉덩이 · 다리가 화면에 들어와야 합니다.")
    return pts


def fill_missing(pts: dict[str, np.ndarray]) -> list[str]:
    """화면 밖으로 잘린 작은 분절을 근사해서 채운다. 채운 점 이름을 돌려준다.

    머리 · 목 CoM(귀)  ≈ 어깨에서 몸통 방향으로 몸통 길이의 25% 위
    검지 끝           ≈ 손목에서 아래팔 방향으로 아래팔 길이의 25% 더
    발뒤꿈치 · 발끝    ≈ 발목 (발은 몸무게의 1.5%라 영향이 작다)
    몸통 · 다리 · 팔처럼 무거운 분절은 채우지 않는다. 없으면 CoM을 계산하지 않는다.
    """
    filled = []
    if "ear" not in pts and {"shoulder", "hip"} <= set(pts):
        pts["ear"] = pts["shoulder"] + 0.25 * (pts["shoulder"] - pts["hip"])
        filled.append("ear")
    if "index" not in pts and {"wrist", "elbow"} <= set(pts):
        pts["index"] = pts["wrist"] + 0.25 * (pts["wrist"] - pts["elbow"])
        filled.append("index")
    for f in ("heel", "toe"):
        if f not in pts and "ankle" in pts:
            pts[f] = pts["ankle"].copy()
            filled.append(f)
    return filled


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


def _facing(pts: dict[str, np.ndarray], filled: list[str]) -> float:
    """바라보는 방향(+1: 화면 오른쪽). 발이 보이면 발끝 방향, 아니면 앉았을 때 무릎이 나가는 방향."""
    if "toe" not in filled and {"toe", "heel"} <= set(pts):
        return 1.0 if np.median(pts["toe"][:, 0] - pts["heel"][:, 0]) >= 0 else -1.0
    for far in ("knee", "shoulder"):          # 앉으면 무릎이 앞으로 나가고, 상체는 앞으로 숙인다
        if far in pts:
            dx = pts[far][:, 0] - pts["hip"][:, 0]
            top = dx[np.abs(dx) >= np.quantile(np.abs(dx), 0.8)]
            return 1.0 if np.median(top) >= 0 else -1.0
    return 1.0


def com_frame(lm: pd.DataFrame, leg_cm: float | None = None, side: str | None = None) -> pd.DataFrame:
    """프레임별 CoM과 CoM–발목 앞뒤 거리. 몸 일부가 잘린 영상이면 보이는 부분으로 계산할 수 있는 것만 낸다.

    com_ankle_dx: (CoM x − 발목 x), 바라보는 방향이 +. 다리 길이(엉덩이–무릎–발목)로 나눈 값.
                  음수면 CoM이 발목보다 뒤에 있다. (몸통 · 팔 · 다리가 다 보여야 계산)
    com_vz:       CoM 위아래 속도 (다리 길이/s, 아래로 내려가면 음수)
    hip_ankle_dx: 엉덩이–발목 앞뒤 거리 (다리 길이 단위). 상체가 안 보여도 계산된다.
    trunk_lean_deg: 엉덩이→어깨 선의 앞쪽 기울기 (수직 0°, 앞으로 숙이면 +). 카메라로 잰 상체 숙임.
    thigh_deg:    엉덩이→무릎 선의 각도 (선 자세 0°, 허벅지가 수평이면 90°).
    leg_cm를 주면 cm, m/s 단위 열과 외삽 CoM(Hof 2005: x + v/√(g/l))도 계산한다.

    attrs["mode"]: "full"(다 보임) / "estimated"(머리 · 손 · 발 일부를 근사) / "partial"(CoM 없이 관절 지표만)
    """
    side = side or pick_side(lm)
    pts = clean_landmarks(lm, side)
    seen = sorted(pts)
    filled = fill_missing(pts)
    t = lm["time_s"].to_numpy(dtype=float)
    facing = _facing(pts, filled)
    thigh_len = np.linalg.norm(pts["knee"] - pts["hip"], axis=1) if "knee" in pts else None
    if {"knee", "ankle"} <= set(pts):
        leg_px = float(np.median(thigh_len + np.linalg.norm(pts["ankle"] - pts["knee"], axis=1)))
        leg_from = "hip-knee-ankle"
    elif thigh_len is not None:
        leg_px = float(2 * np.median(thigh_len))       # 정강이 ≈ 허벅지 길이로 가정
        leg_from = "2 x thigh"
    elif "shoulder" in pts:
        # 다리가 다 잘린 영상: 다리 길이 ≈ 엉덩이–어깨 길이 × 1.8 (Winter 2009 신체 비율: 0.53H / 0.29H)
        leg_px = float(1.8 * np.median(np.linalg.norm(pts["shoulder"] - pts["hip"], axis=1)))
        leg_from = "1.8 x trunk"
    else:
        raise ValueError("무릎도 어깨도 보이지 않아 길이 기준을 잡을 수 없습니다.")

    # 손에 들고 찍으면 화면 자체가 움직인다. 발이 보이면 발목 기준 엉덩이 높이를 써서 카메라 흔들림을 뺀다.
    ref_y = pts["ankle"][:, 1] if "ankle" in pts else 0.0
    hip_z = (pts["hip"][:, 1] - ref_y) / leg_px
    out = pd.DataFrame({"time_s": t, "hip_z": hip_z, "hip_vz": np.gradient(hip_z, t)})
    warnings = []
    can_com = all(n in pts for n in LANDMARKS)
    if can_com:
        com = segment_com(pts)
        dx = (com[:, 0] - pts["ankle"][:, 0]) * facing / leg_px
        z = (com[:, 1] - ref_y) / leg_px
        vx, vz = np.gradient(dx, t), np.gradient(z, t)
        out = out.assign(com_x_px=com[:, 0], com_y_px=-com[:, 1], com_ankle_dx=dx,
                         com_z=z - z[: max(1, len(z) // 20)].mean(), com_vx=vx, com_vz=vz)
    else:
        missing = [n for n in LANDMARKS if n not in pts]
        warnings.append(f"CoM 계산 불가: {', '.join(missing)}이(가) 화면에 거의 안 보임")
    if "ankle" in pts:
        out["hip_ankle_dx"] = (pts["hip"][:, 0] - pts["ankle"][:, 0]) * facing / leg_px
    if "shoulder" in pts:
        d = pts["shoulder"] - pts["hip"]
        out["trunk_lean_deg"] = np.degrees(np.arctan2(d[:, 0] * facing, d[:, 1]))
    if "knee" in pts:
        d = pts["knee"] - pts["hip"]
        out["thigh_deg"] = np.degrees(np.arctan2(d[:, 0] * facing, -d[:, 1]))
    if "toe" not in filled and {"toe", "heel"} <= set(pts):
        foot = np.median(np.abs(pts["toe"][:, 0] - pts["heel"][:, 0])) / leg_px
        if foot < 0.12:
            warnings.append(f"발 길이가 화면에서 다리 길이의 {foot:.0%}뿐: 옆이 아니라 앞/뒤에서 찍은 것 같음 "
                            "(앞뒤 거리 값을 믿기 어려움)")
    if filled and can_com:
        warnings.append(f"근사해서 채운 점: {', '.join(filled)}")
    mode = "partial" if not can_com else ("estimated" if set(filled) & {"ear", "index"} else "full")
    out.attrs.update(side=side, facing=facing, leg_px=leg_px, leg_from=leg_from, mode=mode,
                     seen=seen, filled=filled, warnings=warnings)
    if leg_cm:
        L = leg_cm / 100.0
        if can_com:
            out["com_ankle_dx_cm"] = out["com_ankle_dx"] * leg_cm
            out["com_vz_ms"] = out["com_vz"] * L
            out["xcom_ankle_dx_cm"] = (out["com_ankle_dx"] + out["com_vx"] / np.sqrt(G / L)) * leg_cm
        if "hip_ankle_dx" in out:
            out["hip_ankle_dx_cm"] = out["hip_ankle_dx"] * leg_cm
    return out


# ---------------------------------------------------------------- 3) 착석 순간 · 시간 맞추기

def _rise_events(t: np.ndarray, sig: np.ndarray, low: float, high: float, max_jump: float,
                 min_gap_s: float = 1.0) -> list[dict]:
    """sig가 low 아래(선 자세)에서 high 위(앉은 자세)로 넘어간 구간마다 (시작, 속도 최대, 멈춤) 프레임을 찾는다.

    - 2 Hz로 부드럽게 한 신호로 판단한다. 천천히 앉다 잠깐 멈췄다 다시 앉아도 한 번으로 센다.
    - 시작 / 멈춤 = 속도 최대점 앞 / 뒤에서 속도가 최대의 10% 아래로 떨어진 프레임.
    - 그 구간 안에서 원래 신호가 부드러운 신호와 max_jump 넘게 어긋나면(사람을 잘못 잡은 프레임) 버린다.
    """
    n = len(t)
    fs = 1.0 / np.median(np.diff(t)) if n > 1 else 30.0
    ss = _lowpass(sig, fs, fc=2.0)
    vs = np.gradient(ss, t)
    events, state, last_low = [], "unknown", None
    for i in range(n):
        if ss[i] < low:
            state, last_low = "low", i
        elif ss[i] > high and state == "low":
            state = "high"
            hi = i
            while hi < n - 1 and ss[hi + 1] >= ss[hi] - 1e-9:      # 계속 오르는 동안 끝까지
                hi += 1
            lo = last_low
            pk = lo + int(np.argmax(vs[lo:hi + 1]))
            slow = np.nonzero(vs[pk:] < 0.1 * vs[pk])[0]
            contact = pk + int(slow[0]) if len(slow) else n - 1
            back = np.nonzero(vs[:pk][::-1] < 0.1 * vs[pk])[0]
            start = pk - int(back[0]) if len(back) else lo
            if np.nanmax(np.abs(sig[start:contact + 1] - ss[start:contact + 1])) > max_jump:
                continue
            ev = {"start": start, "peak": pk, "contact": contact, "start_t": t[start], "contact_t": t[contact],
                  "rise": float(ss[contact] - ss[start])}
            if events and ev["start_t"] - events[-1]["contact_t"] < min_gap_s:
                continue
            events.append(ev)
    return events


def video_sit_events(cf: pd.DataFrame, min_gap_s: float = 1.0) -> list[dict]:
    """영상의 착석 구간 (시작 · 착석 순간).

    무릎이 보이면 허벅지 각도로 찾는다: 25° 아래(선 자세)에서 55° 위(앉은 자세)로 넘어간 구간마다,
    굽힘 속도가 최대의 10% 아래로 줄어든 순간 = 착석. H10도 허벅지 각도로 착석을 찾으니 같은 기준이고,
    각도라 카메라 흔들림 · 거리에 영향이 없다.
    무릎이 없으면 엉덩이 높이로 (서 있을 때 대비 다리 길이의 10% → 30% 아래).
    """
    t = cf["time_s"].to_numpy()
    if "thigh_deg" in cf:
        return _rise_events(t, cf["thigh_deg"].to_numpy(), low=25.0, high=55.0, max_jump=25.0, min_gap_s=min_gap_s)
    drop = np.nanpercentile(cf["hip_z"], 95) - cf["hip_z"].to_numpy()
    return _rise_events(t, drop, low=0.10, high=0.30, max_jump=0.1, min_gap_s=min_gap_s)


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


def thigh_xcorr(cf: pd.DataFrame, d: pd.DataFrame, fs: float = 20.0, min_overlap: float = 0.7,
                video_col: str = "thigh_deg") -> tuple[float, float]:
    """영상 허벅지 각도와 H10 허벅지 각도(양쪽 평균) 곡선을 통째로 겹쳐 본다.
    video_col="trunk_lean_deg"이면 카메라 상체 숙임과 H10 상체 각도(trunk_deg)를 겹친다(다리가 잘린 영상).

    두 곡선을 fs로 맞추고, 영상 길이의 min_overlap 이상 겹치는 모든 시간차에서 상관계수를 계산해
    가장 높은 (offset, r)을 돌려준다. H10 시간 = 영상 시간 + offset.
    착석 시각 몇 개만 맞추는 것보다 훨씬 강한 증거다: 앉는 속도, 멈칫한 순간, 서 있던 시간까지 같아야 r이 높다.
    """
    tv = np.arange(cf["time_s"].iloc[0], cf["time_s"].iloc[-1], 1 / fs)
    x = np.interp(tv, cf["time_s"], cf[video_col])
    th = (d[["thigh_l_deg", "thigh_r_deg"]].mean(axis=1) if video_col == "thigh_deg" else d["trunk_deg"]).to_numpy(float)
    th = _lowpass(th, 1 / np.median(np.diff(d["time_s"])), fc=6.0)
    th_t = np.arange(d["time_s"].iloc[0], d["time_s"].iloc[-1], 1 / fs)
    y = np.interp(th_t, d["time_s"], th)
    n, m = len(x), len(y)
    need = int(min_overlap * n)
    best = (np.nan, -np.inf)
    for lag in range(-(n - need), m - need + 1):           # 영상 0번 샘플이 H10의 lag번 샘플
        i0, j0 = max(0, -lag), max(0, lag)
        L = min(n - i0, m - j0)
        if L < need:
            continue
        a, b = x[i0:i0 + L], y[j0:j0 + L]
        if np.std(a) == 0 or np.std(b) == 0:
            continue
        r = float(np.corrcoef(a, b)[0, 1])
        if r > best[1]:
            best = (lag / fs + tv[0] - th_t[0], r)
    return best


def match_score(video_t: list[float], h10_t: list[float], h10_dur: float | None = None,
                tol: float = 0.3) -> dict:
    """영상 착석 시각과 H10 착석 시각이 얼마나 잘 겹치는지.

    matched_frac: 짝지어진 착석 / 둘 중 적은 쪽 착석 수
    resid_sd:     짝지어진 착석의 시간 차이 표준편차(s). 같은 실험이면 영상 프레임 · 판정 기준 차이만큼(~0.1 s)만 흔들린다.
    gap_r:        짝지어진 착석들 사이 간격(영상 vs H10)의 상관. 착석 간격이 비슷하게 규칙적인 실험끼리는
                  offset만으로 우연히 겹칠 수 있어서, 간격의 들쭉날쭉한 패턴까지 같은지 본다.
    """
    v, h = np.asarray(video_t, float), np.asarray(h10_t, float)
    out = {"n_video": len(v), "n_h10": len(h), "matched": 0, "matched_frac": 0.0, "offset_s": np.nan,
           "resid_sd": np.nan, "gap_r": np.nan}
    if len(v) == 0 or len(h) == 0:
        return out
    off, _ = find_offset(v, h, tol)
    pv, ph = [], []
    for tv in v:
        k = int(np.argmin(np.abs(h - (tv + off))))
        if abs(h[k] - (tv + off)) <= tol and k not in ph:
            pv.append(tv)
            ph.append(k)
    ph = h[ph]
    res = ph - np.array(pv) - off
    out.update(matched=len(pv), matched_frac=len(pv) / min(len(v), len(h)), offset_s=off,
               resid_sd=float(np.std(res)) if len(res) > 1 else np.nan)
    if len(pv) >= 4:
        gv, gh = np.diff(pv), np.diff(ph)
        if np.std(gv) > 0 and np.std(gh) > 0:
            out["gap_r"] = float(np.corrcoef(gv, gh)[0, 1])
    if h10_dur is not None:
        out["video_in_log"] = bool(off > -2 and off < h10_dur)
    return out


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

def sit_table(cf: pd.DataFrame, vev: list[dict], hev: list[dict] | None = None, offset: float = 0.0,
              tol: float = SYNC_TOL_S) -> pd.DataFrame:
    """영상 착석과 H10 착석을 짝지어 앉기별 지표를 한 줄씩 만든다. hev가 없으면 영상 지표만."""
    h_t = np.array([e["contact_t"] for e in hev]) if hev else None
    rows = []
    for e in vev:
        s, c = e["start"], e["contact"]
        r = {"video_start_t": e["start_t"], "video_contact_t": e["contact_t"]}
        k = None
        if h_t is not None:
            k = int(np.argmin(np.abs(h_t - (e["contact_t"] + offset))))
            lag = h_t[k] - (e["contact_t"] + offset)
            if abs(lag) > tol:
                continue
            r.update(h10_contact_t=h_t[k], sync_lag_s=lag)
        win = cf.iloc[s:c + 1]
        pre = max(c - 1, s)
        if "com_ankle_dx" in cf:
            r.update(dx_contact=cf["com_ankle_dx"].iloc[c], dx_min=win["com_ankle_dx"].min(),
                     com_vz_contact=cf["com_vz"].iloc[pre], com_drop=win["com_z"].iloc[0] - win["com_z"].iloc[-1])
        if "com_ankle_dx_cm" in cf:
            r.update(dx_contact_cm=cf["com_ankle_dx_cm"].iloc[c], dx_min_cm=win["com_ankle_dx_cm"].min(),
                     com_vz_contact_ms=cf["com_vz_ms"].iloc[pre], xcom_min_cm=win["xcom_ankle_dx_cm"].min())
        if "hip_ankle_dx" in cf:
            r.update(hip_dx_contact=cf["hip_ankle_dx"].iloc[c], hip_dx_min=win["hip_ankle_dx"].min())
        if "trunk_lean_deg" in cf:
            base = cf["trunk_lean_deg"].iloc[s]
            r.update(lean_start=base, lean_max=win["trunk_lean_deg"].max() - base,
                     lean_contact=cf["trunk_lean_deg"].iloc[c] - base)
        if "thigh_deg" in cf:
            r.update(thigh_contact=cf["thigh_deg"].iloc[c], thigh_dtheta=cf["thigh_deg"].iloc[c] - cf["thigh_deg"].iloc[s])
        r.update(hip_vz_contact=cf["hip_vz"].iloc[pre], hip_vz_peak=cf["hip_vz"].iloc[s:c + 1].min(),
                 descent_s=e["contact_t"] - e["start_t"])
        if k is not None:
            r.update({f"h10_{key}": val for key, val in hev[k].items() if key not in ("onset_t", "contact_t")})
        rows.append(r)
    return pd.DataFrame(rows)


PAIRS = [("lean_max", "h10_peak_lean", "카메라 상체 숙임 vs H10 상체 숙임 (같은 걸 잰 것)"),
         ("thigh_dtheta", "h10_contact_dtheta", "카메라 허벅지 각도 변화 vs H10 착석 각도"),
         ("dx_min", "h10_peak_lean", "가장 뒤로 간 CoM–발목 거리 vs H10 최대 상체 숙임"),
         ("dx_contact", "h10_peak_lean", "착석 순간 CoM–발목 거리 vs H10 최대 상체 숙임"),
         ("com_vz_contact", "h10_contact_vel", "착석 순간 CoM 하강 속도 vs H10 착석 속도"),
         ("com_vz_contact", "h10_late_vel", "착석 순간 CoM 하강 속도 vs H10 후반 하강 속도"),
         ("hip_dx_min", "h10_peak_lean", "가장 뒤로 간 엉덩이–발목 거리 vs H10 최대 상체 숙임 (CoM 없을 때)"),
         ("hip_vz_contact", "h10_contact_vel", "착석 순간 엉덩이 하강 속도 vs H10 착석 속도 (CoM 없을 때)")]


def correlations(sits: pd.DataFrame) -> pd.DataFrame:
    from scipy.stats import pearsonr, spearmanr
    rows = []
    for chair, g in [("전체", sits)] + list(sits.groupby("chair")):
        for a, b, desc in PAIRS:
            if a not in g or b not in g:
                continue
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
    pairs = [p for p in PAIRS if p[0] in sits and p[1] in sits]
    if not pairs:
        return
    fig, axes = plt.subplots(1, len(pairs), figsize=(4.2 * len(pairs), 3.8), squeeze=False)
    axes = axes[0]
    colors = {"45 cm": "#8a8f8c", "30 cm": "#3f9d63"}
    for ax, (a, b, desc) in zip(axes, pairs):
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
    rot = a.rotate if a.rotate == "auto" else int(a.rotate)
    lm = extract_pose(Path(a.video), Path(a.model) if a.model else None, rot)
    out = Path(a.out or Path(a.video).with_name(Path(a.video).stem + "_pose.csv"))
    out.parent.mkdir(parents=True, exist_ok=True)
    lm.round(2).to_csv(out, index=False)
    seen = lm["hip_l_v"].gt(0).mean()
    print(f"{len(lm)}프레임, 회전 {lm.attrs['rotate']}°, 사람 검출 {seen:.0%} → {out}")


VIDEO_COLS = ("dx_contact", "dx_min", "com_vz_contact", "hip_dx_contact", "hip_dx_min", "lean_max",
              "thigh_dtheta", "hip_vz_contact", "descent_s")


def cmd_analyze(a):
    pose = Path(a.pose)
    lm = extract_pose(pose, Path(a.model) if a.model else None) if pose.suffix.lower() != ".csv" else pd.read_csv(pose)
    cf = com_frame(lm, a.leg_cm)
    vev = video_sit_events(cf)
    print(f"모드 {cf.attrs['mode']} · {'오른' if cf.attrs['side'] == 'r' else '왼'}쪽 다리 기준 · "
          f"보이는 점: {', '.join(cf.attrs['seen'])}")
    for w in cf.attrs["warnings"]:
        print(f"  ! {w}")
    hev, off, n = None, None, 0
    if a.h10:
        hev = h10_sit_events(_h10_table(Path(a.h10)))
        if a.offset is not None:
            off, n = a.offset, -1
        else:
            off, n = find_offset([e["contact_t"] for e in vev], [e["contact_t"] for e in hev])
    sits = sit_table(cf, vev, hev, off or 0.0)
    sits.insert(0, "chair", a.chair)
    sits.insert(1, "source", pose.stem)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    cf.round(4).to_csv(out / f"{pose.stem}_com.csv", index=False)
    sits.round(4).to_csv(out / f"{pose.stem}_sits.csv", index=False)
    info = {k: cf.attrs[k] for k in ("mode", "side", "facing", "leg_px", "leg_from", "seen", "filled", "warnings")}
    info.update(video_sits=len(vev), h10_sits=len(hev) if hev else None, matched=len(sits) if hev else None,
                offset_s=off)
    (out / f"{pose.stem}_sync.json").write_text(json.dumps(info, indent=2, ensure_ascii=False))
    if hev is None:
        print(f"영상 착석 {len(vev)}회 (H10 로그 없이 영상 지표만)")
    else:
        print(f"영상 착석 {len(vev)}회, H10 착석 {len(hev)}회, 짝 {len(sits)}회 (H10 시간 = 영상 + {off:.2f} s)")
        if len(sits) < min(len(vev), len(hev)):
            print("  짝이 안 맞은 착석이 있습니다. 영상과 H10 기록 구간이 같은지, --offset으로 직접 맞출지 확인하세요.")
    if len(sits):
        cols = [c for c in VIDEO_COLS + ("h10_peak_lean", "h10_contact_vel", "h10_late_vel") if c in sits]
        print(sits[cols].describe().loc[["mean", "std"]].round(3).to_string())


def overlay(video: Path, lm: pd.DataFrame, cf: pd.DataFrame, path: Path, n_sits: int = 3):
    """착석마다 시작 · 착석 프레임에 관절 선과 CoM(빨간 점)을 그려 한 장으로 붙인다. 눈으로 검증하는 용도."""
    import cv2
    rot = int(lm["rotate"].iloc[0]) if "rotate" in lm else 0
    side = cf.attrs["side"]
    ev = video_sit_events(cf)[:n_sits]
    idx = [i for e in ev for i in (e["start"], e["contact"])] or list(np.linspace(0, len(lm) - 1, 4, dtype=int))
    cap = cv2.VideoCapture(str(video))
    tiles = []
    for i in idx:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(i))
        ok, f = cap.read()
        if not ok:
            continue
        f = _rotate(f, rot)
        P = lambda n: lm.loc[i, [f"{n}_{side}_x", f"{n}_{side}_y"]].to_numpy(float)
        chain = [("ear", "shoulder"), ("shoulder", "hip"), ("hip", "knee"), ("knee", "ankle"), ("heel", "toe"),
                 ("shoulder", "elbow"), ("elbow", "wrist")]
        for u, v in chain:
            pu, pv = P(u), P(v)
            if np.isfinite(pu).all() and np.isfinite(pv).all() and lm.loc[i, f"{u}_{side}_v"] >= 0.5 \
                    and lm.loc[i, f"{v}_{side}_v"] >= 0.5:
                cv2.line(f, tuple(map(int, pu)), tuple(map(int, pv)), (60, 220, 60), 4)
        if "com_x_px" in cf:
            c = (int(cf["com_x_px"].iloc[i]), int(cf["com_y_px"].iloc[i]))
            cv2.circle(f, c, 14, (0, 0, 255), -1)
            ax = P("ankle")
            if np.isfinite(ax).all():
                cv2.line(f, (int(ax[0]), 0), (int(ax[0]), f.shape[0]), (255, 160, 0), 2)
        label = f"t={cf['time_s'].iloc[i]:.1f}s"
        if "trunk_lean_deg" in cf:
            label += f" lean={cf['trunk_lean_deg'].iloc[i]:.0f}"
        cv2.putText(f, label, (20, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (255, 255, 255), 4)
        tiles.append(cv2.resize(f, (int(f.shape[1] * 480 / f.shape[0]), 480)))
    cap.release()
    if tiles:
        path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(path), cv2.hconcat(tiles))


def cmd_overlay(a):
    lm = pd.read_csv(a.pose)
    out = Path(a.out or Path("results/video") / f"{Path(a.pose).stem}_overlay.jpg")
    overlay(Path(a.video), lm, com_frame(lm), out)
    print(f"→ {out}")


def cmd_match(a):
    """영상 여러 개 × H10 로그 여러 개를 착석 시각으로 짝짓는다."""
    logs = {}
    for f in a.h10:
        d = _h10_table(Path(f))
        logs[Path(f).name] = ([e["contact_t"] for e in h10_sit_events(d)], float(d["time_s"].iloc[-1]), d)
    rows = []
    for pose in a.pose:
        lm = pd.read_csv(pose)
        try:
            cf = com_frame(lm)
        except ValueError as e:
            print(f"{Path(pose).stem}: 건너뜀 ({e})")
            continue
        vt = [e["contact_t"] for e in video_sit_events(cf)]
        for name, (ht, dur, d) in logs.items():
            r = {"video": Path(pose).stem.replace("_pose", ""), "h10": name, **match_score(vt, ht, dur, a.tol)}
            col = "thigh_deg" if "thigh_deg" in cf else ("trunk_lean_deg" if "trunk_lean_deg" in cf else None)
            if col:
                r["xcorr_signal"] = col
                r["xcorr_offset_s"], r["xcorr_r"] = thigh_xcorr(cf, d, video_col=col)
            rows.append(r)
    if not rows:
        raise SystemExit("짝지을 영상이 없습니다.")
    m = pd.DataFrame(rows)
    m["score"] = m["xcorr_r"] if "xcorr_r" in m else m["matched_frac"]
    m = m.sort_values(["video", "score"], ascending=[True, False])
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    m.round(3).to_csv(out / "video_h10_match.csv", index=False)
    for v, g in m.groupby("video", sort=False):
        b = g.iloc[0]
        second = g.iloc[1]["score"] if len(g) > 1 else 0
        print(f"{v}: {'허벅지' if b.get('xcorr_signal') == 'thigh_deg' else '상체'} 곡선 r={b.score:.2f} (2등 {second:.2f}) → {b.h10}, H10 = 영상 + {b.get('xcorr_offset_s', np.nan):.2f} s"
              f" | 착석 시각: {int(b.matched)}/{min(int(b.n_video), int(b.n_h10))} 짝, offset {b.offset_s:.2f} s")
    print(f"→ {out / 'video_h10_match.csv'}")


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
    by = sits.groupby("chair")[[c for c in VIDEO_COLS if c in sits]].agg(["mean", "std", "count"])
    print(by.round(3).to_string())
    if len(corr):
        print()
        print(corr[[c for c in ("chair", "설명", "n", "pearson_r", "spearman_r", "spearman_p") if c in corr]]
              .round(3).to_string(index=False))
    print(f"\n→ {d / 'com_vs_h10_correlations.csv'}, {d / 'com_vs_h10.png'}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("extract", help="영상 → 관절 좌표 CSV")
    p.add_argument("video")
    p.add_argument("--out")
    p.add_argument("--model", help=f"MediaPipe Tasks 모델(.task). 기본 {DEFAULT_MODEL.relative_to(DEFAULT_MODEL.parents[2])}")
    p.add_argument("--rotate", default="auto", choices=["auto", "0", "90", "180", "270"],
                   help="시계 방향 회전. 기본 auto(눕혀 찍은 영상 자동 감지)")
    p.set_defaults(fn=cmd_extract)
    p = sub.add_parser("analyze", help="관절 좌표(또는 영상) + H10 로그 → 앉기별 표")
    p.add_argument("pose", help="extract가 만든 CSV 또는 영상 파일")
    p.add_argument("h10", nargs="?", help="같은 시간에 기록한 H10 로그 (앱 CSV 또는 SUIT 로그). 없으면 영상 지표만")
    p.add_argument("--chair", required=True, help='예: "45 cm"')
    p.add_argument("--leg-cm", type=float, help="다리 길이(대전자~바깥 복사뼈, cm). 주면 cm 단위도 계산")
    p.add_argument("--offset", type=float, help="H10 시간 = 영상 시간 + offset (자동 맞춤 대신)")
    p.add_argument("--model")
    p.add_argument("--out", default="results/video")
    p.set_defaults(fn=cmd_analyze)
    p = sub.add_parser("overlay", help="착석 프레임에 관절 · CoM을 그린 확인용 그림")
    p.add_argument("video")
    p.add_argument("pose", help="extract가 만든 CSV")
    p.add_argument("--out")
    p.set_defaults(fn=cmd_overlay)
    p = sub.add_parser("match", help="영상들 × H10 로그들을 착석 시각으로 짝짓기")
    p.add_argument("--pose", nargs="+", required=True, help="extract가 만든 CSV들")
    p.add_argument("--h10", nargs="+", required=True, help="후보 H10 로그들")
    p.add_argument("--tol", type=float, default=0.3, help="같은 착석으로 볼 시간차(s)")
    p.add_argument("--out", default="results/video")
    p.set_defaults(fn=cmd_match)
    p = sub.add_parser("summary", help="앉기별 표를 모아 의자별 상관 분석")
    p.add_argument("dir", nargs="?", default="results/video")
    p.set_defaults(fn=cmd_summary)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
