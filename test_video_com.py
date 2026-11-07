"""video_com.py 테스트. 옆에서 본 막대 인형으로 관절 좌표를 만들어 쓰므로 mediapipe가 없어도 돈다."""
import numpy as np
import pandas as pd
import pytest

from video_com import (HEAD, LANDMARKS, SEGMENTS, SIDES, TRUNK, com_frame, correlations, find_offset, match_score, thigh_xcorr,
                       h10_sit_events, sit_table, video_sit_events)

FPS = 30.0
SHANK, THIGH, TRUNK_PX = 200.0, 200.0, 260.0


def stick(thigh_deg, shank_deg=0.0, lean_deg=0.0, facing=1, ankle_x=500.0):
    """옆에서 본 자세 하나의 관절 좌표(px, 아래로 +y). facing=1이면 오른쪽을 본다."""
    s, f = facing, np.deg2rad
    ankle = np.array([0.0, 100.0])
    knee = ankle + SHANK * np.array([np.sin(f(shank_deg)), np.cos(f(shank_deg))])
    hip = knee + THIGH * np.array([-np.sin(f(thigh_deg)), np.cos(f(thigh_deg))])
    up = np.array([np.sin(f(lean_deg)), np.cos(f(lean_deg))])
    sh = hip + TRUNK_PX * up
    p = {"ankle": ankle, "knee": knee, "hip": hip, "shoulder": sh, "ear": sh + 60 * up,
         "elbow": sh + [0, -130], "wrist": sh + [0, -250], "index": sh + [0, -290],
         "heel": ankle + [-20, -10], "toe": ankle + [60, -10]}
    return {k: (ankle_x + s * v[0], 1000.0 - v[1]) for k, v in p.items()}


def frames(poses, t0=0.0, hidden=()):
    """hidden에 든 점은 양쪽 다 안 보이게(화면 밖으로 잘린 것처럼) 만든다."""
    rows = []
    for i, p in enumerate(poses):
        r = {"time_s": t0 + i / FPS}
        for name in LANDMARKS:
            for side in SIDES:
                r[f"{name}_{side}_x"], r[f"{name}_{side}_y"] = p[name]
                r[f"{name}_{side}_v"] = 0.05 if name in hidden else (0.99 if side == "r" else 0.3)
        rows.append(r)
    return pd.DataFrame(rows)


def sit_cycle(lean_peak=30.0, stand_s=1.0, down_s=1.0, sit_s=1.0, up_s=1.0):
    """서 있기 → 앉기(허벅지 0→90°, 상체 숙임 0→lean_peak) → 앉아 있기 → 일어서기."""
    poses = []
    for _ in range(int(stand_s * FPS)):
        poses.append(stick(0))
    n = int(down_s * FPS)
    for i in range(n):
        u = 0.5 - 0.5 * np.cos(np.pi * (i + 1) / n)
        poses.append(stick(90 * u, 15 * u, lean_peak * u))
    for _ in range(int(sit_s * FPS)):
        poses.append(stick(90, 15, lean_peak))
    n = int(up_s * FPS)
    for i in range(n):
        u = 0.5 - 0.5 * np.cos(np.pi * (i + 1) / n)
        poses.append(stick(90 * (1 - u), 15 * (1 - u), lean_peak * (1 - u)))
    return poses, stand_s + down_s


def test_mass_fractions_sum_to_one():
    total = 2 * sum(m for _, m, *_ in SEGMENTS) + TRUNK[1] + HEAD[1]
    assert total == pytest.approx(1.0, abs=1e-9)


def test_upright_com_above_ankle_and_mirror_invariant():
    lm = frames([stick(0)] * 40)
    cf = com_frame(lm)
    assert cf.attrs["side"] == "r"
    assert cf.attrs["leg_px"] == pytest.approx(SHANK + THIGH, rel=1e-3)
    dx = cf["com_ankle_dx"].iloc[20]
    assert 0 < dx < 0.02                        # 발 무게만큼 아주 조금 앞
    mirrored = com_frame(frames([stick(0, facing=-1)] * 40))
    assert mirrored.attrs["facing"] == -1
    assert mirrored["com_ankle_dx"].iloc[20] == pytest.approx(dx, abs=1e-6)


def test_leaning_forward_moves_com_forward():
    seated_upright = com_frame(frames([stick(90, 15, 0)] * 40))["com_ankle_dx"].iloc[20]
    seated_lean = com_frame(frames([stick(90, 15, 40)] * 40))["com_ankle_dx"].iloc[20]
    assert seated_upright < 0                   # 상체를 세운 채 앉으면 CoM이 발목 뒤
    assert seated_lean > seated_upright


def test_leg_cm_units():
    cf = com_frame(frames([stick(90, 15, 0)] * 40), leg_cm=80)
    assert cf["com_ankle_dx_cm"].iloc[20] == pytest.approx(cf["com_ankle_dx"].iloc[20] * 80)
    assert "xcom_ankle_dx_cm" in cf


def test_video_contact_at_end_of_descent():
    poses, contacts = [], []
    for _ in range(3):
        p, c = sit_cycle()
        contacts.append(len(poses) / FPS + c)
        poses += p
    cf = com_frame(frames(poses))
    ev = video_sit_events(cf)
    assert len(ev) == 3
    for e, c in zip(ev, contacts):
        assert e["contact_t"] == pytest.approx(c, abs=0.15)
        assert e["start_t"] < e["contact_t"]


def test_find_offset_recovers_shift():
    rng = np.random.default_rng(0)
    video = [2.0, 6.1, 10.4, 14.2, 19.0]
    h10 = [t + 12.34 + rng.normal(0, 0.03) for t in video[1:]] + [5.0, 40.0]   # 첫 착석은 H10 기록 전, 가짜 2개
    off, n = find_offset(video, h10)
    assert n == 4
    assert off == pytest.approx(12.34, abs=0.03)


def h10_log(contacts, lean=20.0, fs=100):
    """100 Hz H10 표: 허벅지 5°→70° 착석, 상체 숙임, 닿는 순간 가속도 충격."""
    n = int((max(contacts) + 3) * fs)
    t = np.arange(n) / fs
    th = np.full(n, 5.0)
    tr = np.zeros(n)
    acc = np.full(n, 9.8)
    for c in contacts:
        s = int((c - 1.0) * fs)
        for i in range(s, int((c + 1.5) * fs)):
            u = min(max((i - s) / fs, 0), 1.0)
            th[i] = 5 + 65 * (0.5 - 0.5 * np.cos(np.pi * u))
            tr[i] = lean * np.sin(np.pi * u)
        a, b = int(round((c + 1.5) * fs)), int(round((c + 2.2) * fs))
        th[a:b] = np.linspace(70, 5, b - a)
        acc[int(c * fs):int(c * fs) + 3] += 8.0
    return pd.DataFrame({"time_s": t, "thigh_l_deg": th, "thigh_r_deg": th, "trunk_deg": tr, "acc_ms2": acc})


def test_h10_events_use_imu_impact():
    ev = h10_sit_events(h10_log([3.0, 8.0], lean=20.0))
    assert len(ev) == 2
    assert ev[0]["contact_t"] == pytest.approx(3.0, abs=0.03)
    assert ev[1]["contact_t"] == pytest.approx(8.0, abs=0.03)
    assert ev[0]["peak_lean"] == pytest.approx(20.0, abs=1.5)
    assert ev[0]["late_vel"] > 0


def test_sit_table_and_correlations_end_to_end():
    poses, contacts, leans = [], [], [10, 20, 30, 40, 50]
    for lp in leans:
        p, c = sit_cycle(lean_peak=lp)
        contacts.append(len(poses) / FPS + c)
        poses += p
    cf = com_frame(frames(poses), leg_cm=85)
    vev = video_sit_events(cf)
    offset = 3.21
    hev = [{"onset_t": c + offset - 1, "contact_t": c + offset, "peak_lean": lp, "contact_vel": 50.0 + lp,
            "late_vel": 80.0, "contact_dtheta": 65.0} for c, lp in zip(contacts, leans)]
    off, n = find_offset([e["contact_t"] for e in vev], [e["contact_t"] for e in hev])
    assert n == 5 and off == pytest.approx(offset, abs=0.15)
    sits = sit_table(cf, vev, hev, off)
    assert len(sits) == 5
    assert {"dx_min_cm", "com_vz_contact_ms", "h10_peak_lean"} <= set(sits.columns)
    sits.insert(0, "chair", "30 cm")
    corr = correlations(sits)
    row = corr[(corr.chair == "30 cm") & (corr.video == "dx_min") & (corr.h10 == "h10_peak_lean")].iloc[0]
    assert row["spearman_r"] > 0.8              # 더 숙일수록 CoM이 덜 뒤로 간다


def test_head_cut_off_estimates_head_from_trunk():
    poses = [stick(90, 15, 30)] * 40
    full = com_frame(frames(poses))
    est = com_frame(frames(poses, hidden=("ear",)))
    assert full.attrs["mode"] == "full"
    assert est.attrs["mode"] == "estimated" and "ear" in est.attrs["filled"]
    # 머리 위치를 근사해도 CoM–발목 거리는 다리 길이의 1% 안
    assert est["com_ankle_dx"].iloc[20] == pytest.approx(full["com_ankle_dx"].iloc[20], abs=0.01)


def test_camera_trunk_lean_and_thigh_angle():
    for facing in (1, -1):
        cf = com_frame(frames([stick(60, 10, 25, facing=facing)] * 40))
        assert cf["trunk_lean_deg"].iloc[20] == pytest.approx(25, abs=0.5)
        assert cf["thigh_deg"].iloc[20] == pytest.approx(60, abs=0.5)


def test_upper_body_cut_off_gives_hip_metrics_only():
    poses, _ = sit_cycle()
    cf = com_frame(frames(poses * 2, hidden=("ear", "shoulder", "elbow", "wrist", "index")))
    assert cf.attrs["mode"] == "partial"
    assert "com_ankle_dx" not in cf and "trunk_lean_deg" not in cf
    assert "hip_ankle_dx" in cf and "thigh_deg" in cf
    vev = video_sit_events(cf)
    assert len(vev) == 2
    sits = sit_table(cf, vev)                       # H10 로그 없이 영상 지표만
    assert len(sits) == 2 and "hip_dx_min" in sits and "h10_contact_t" not in sits
    assert 75 < sits["thigh_dtheta"].iloc[0] <= 92       # 착석 판정은 완전히 멈추기 직전 프레임


def test_feet_cut_off_uses_thigh_length_and_knee_direction():
    poses, _ = sit_cycle(lean_peak=20)
    cf = com_frame(frames(poses * 2, hidden=("ankle", "heel", "toe")))
    assert cf.attrs["mode"] == "partial" and cf.attrs["leg_from"] == "2 x thigh"
    assert cf.attrs["facing"] == 1
    assert "hip_ankle_dx" not in cf
    sits = sit_table(cf, video_sit_events(cf))
    assert len(sits) == 2
    assert sits["lean_max"].iloc[0] == pytest.approx(20, abs=2)


def test_thigh_curve_xcorr_finds_same_session_only():
    rng = np.random.default_rng(1)
    poses, contacts = [], []
    for stand in rng.uniform(0.5, 2.5, 6):              # 서 있는 시간을 들쭉날쭉하게
        p, c = sit_cycle(stand_s=round(stand * FPS) / FPS)
        contacts.append(len(poses) / FPS + c)
        poses += p
    cf = com_frame(frames(poses))
    offset = 7.5
    fs = 100
    n = int((cf["time_s"].iloc[-1] + offset + 5) * fs)
    t = np.arange(n) / fs
    th = np.interp(t - offset, cf["time_s"], cf["thigh_deg"], left=cf["thigh_deg"].iloc[0],
                   right=cf["thigh_deg"].iloc[-1]) + rng.normal(0, 2, n)
    same = pd.DataFrame({"time_s": t, "thigh_l_deg": th, "thigh_r_deg": th, "trunk_deg": 0.0})
    off, r = thigh_xcorr(cf, same)
    assert off == pytest.approx(offset, abs=0.1) and r > 0.95
    other = same.copy()                                  # 같은 동작을 다른 박자로 한 세션
    other["thigh_l_deg"] = other["thigh_r_deg"] = np.interp(t * 1.3 % (t[-1]), t, th)
    assert thigh_xcorr(cf, other)[1] < r - 0.2
    m = match_score([e for e in contacts], [c + offset for c in contacts], h10_dur=t[-1])
    assert m["matched"] == 6 and m["offset_s"] == pytest.approx(offset, abs=0.05)
