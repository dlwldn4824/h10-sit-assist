"""가짜 데이터 한 명분으로 착석 보조가 설계대로 반응하는지 확인한다."""
import numpy as np
import pandas as pd
import pytest

from evaluate import calib_loo, trial_metrics
from simulate_data import make_person, simulate_sit
from dataclasses import replace

from sit_assist import Config, Phase, Profile, SitAssistController, run_trial

# 가짜 사람은 실측보다 천천히 앉아서(최대 ~50°/s) 실측으로 정한 허용 폭 하한(25°/s)과 제동 시작 지점이 맞지 않는다.
# 여기서는 조정값이 아니라 제어 논리를 보므로 예전 값으로 돌린다.
SIM_CFG = replace(Config(), min_sd=5.0, brake_from_ratio=0.25)


@pytest.fixture(scope="module")
def person():
    return make_person(np.random.default_rng(1), "T01")


@pytest.fixture(scope="module")
def calib(person):
    rng = np.random.default_rng(2)
    return [simulate_sit(rng, person, "standard", 0.0) for _ in range(15)]


@pytest.fixture(scope="module")
def profile(calib):
    return Profile.from_trials(calib, SIM_CFG)


def sit(person, profile, chair, weakness, shadow, seed=3):
    ctrl = SitAssistController(profile, SIM_CFG, shadow=shadow)
    return simulate_sit(np.random.default_rng(seed), person, chair, weakness, ctrl)


def test_profile_shape(profile):
    assert profile.n_trials == 15
    assert 60 < profile.contact_mean < 80
    assert max(profile.mu_l) > 40                  # 중간에 가장 빠름
    assert profile.mu_l[-1] < max(profile.mu_l)    # 의자 근처에서 느려짐
    assert profile.lean_mu is not None and max(profile.lean_mu) > 25   # 중간에 상체를 숙임


def test_profile_save_load(profile, tmp_path):
    profile.save(tmp_path / "p.json")
    assert Profile.load(tmp_path / "p.json") == profile


def test_normal_sitting_rarely_brakes(calib):
    loo = calib_loo(calib, SIM_CFG)
    assert loo.triggered.mean() <= 0.2
    assert loo.deep.sum() <= 1                  # 평소 착석 각도 +2SD라 가끔은 넘을 수 있음
    assert loo.upright.sum() <= 1


def test_standing_still_no_torque(profile):
    ctrl = SitAssistController(profile, SIM_CFG)
    rng = np.random.default_rng(0)
    for k in range(300):
        tau = ctrl.update(k / 100, 5 + rng.normal(0, 0.15), 6 + rng.normal(0, 0.15))
        assert tau == (0.0, 0.0)
    assert ctrl.seg.phase == Phase.STANDING


def test_low_chair_enters_deep(person, profile):
    df = sit(person, profile, "low", 0.0, shadow=True)
    assert (df.phase == Phase.DEEP).any()


def test_shadow_mode_logs_but_outputs_nothing(person, profile):
    df = sit(person, profile, "low", 1.0, shadow=True)
    assert df.tau_brake.max() > 1                               # 제동을 계산은 했지만
    replay = run_trial(df, profile, SIM_CFG, shadow=True)                # 같은 결과가 재현됨
    assert np.allclose(replay.tau_cmd_l, df.tau_cmd_l, atol=0.01)   # 저장 시 입력 반올림 오차


def test_less_trunk_lean_flags_upright(profile, calib):
    df = calib[0]
    upright = df.copy()
    base = df.trunk_deg.iloc[:50].mean()
    upright["trunk_deg"] = base + (df.trunk_deg - base) * 0.4      # 평소보다 상체를 60% 덜 숙임
    assert (run_trial(df, profile, SIM_CFG).posture == 0).all()
    assert (run_trial(upright, profile, SIM_CFG).posture == 1).any()


def test_without_waist_imu_still_brakes(person, profile, calib):
    df = sit(person, profile, "low", 1.0, shadow=True).drop(columns=["trunk_deg"])
    log = run_trial(df, profile, SIM_CFG, shadow=True)
    assert log.tau_support.max() == 0 and log.tau_brake.max() > 5


def test_adaptive_reduces_fast_descent(person, profile):
    off = trial_metrics(sit(person, profile, "low", 1.0, shadow=True))
    on = trial_metrics(sit(person, profile, "low", 1.0, shadow=False))
    assert on["contact_vel"] < off["contact_vel"] * 0.95   # 상체 지지 없이 제동만으로 (실측에서도 후반 감속이 부족했음)
    assert on["rms_jerk"] < off["rms_jerk"]
    assert on["descent_time"] < off["descent_time"] * 1.2      # 지나치게 느려지지 않음


def test_torque_released_after_seated(person, profile):
    df = sit(person, profile, "low", 1.0, shadow=False)
    seated_at = df.time_s[df.seat == 1].iloc[0]
    late = df[df.time_s > seated_at + 0.5]
    assert (late[["tau_cmd_l", "tau_cmd_r"]] == 0).all().all()


def test_standing_up_gets_no_torque(person, profile, calib):
    # 앉아 있다가 일어서는 동작 = 착석 시행을 시간 역순으로
    df = calib[0]
    rev = pd.DataFrame({"time_s": df.time_s, "thigh_l_deg": df.thigh_l_deg[::-1].to_numpy(),
                        "thigh_r_deg": df.thigh_r_deg[::-1].to_numpy(),
                        "trunk_deg": df.trunk_deg[::-1].to_numpy()})
    log = run_trial(rev, profile, SIM_CFG, shadow=True)
    assert log[["tau_cmd_l", "tau_cmd_r"]].max().max() == 0


# ---------------------------------------------------------------- CoM 추정 · 멈칫 착석

def test_h10_com_model_directions():
    from sit_assist import h10_com_dx
    stand = h10_com_dx(0.0, 0.0, 0.0)
    assert abs(stand) < 0.02                          # 똑바로 서면 CoM은 발목 위
    assert h10_com_dx(75.0, 0.0) < -0.15              # 상체를 세운 채 앉으면 CoM이 발목 뒤
    assert h10_com_dx(75.0, 30.0) > h10_com_dx(75.0, 0.0)   # 숙이면 앞으로
    assert h10_com_dx(75.0, 10.0, shank_deg=-15) < h10_com_dx(75.0, 10.0, shank_deg=15)   # 다리를 뻗으면 뒤로


def test_profile_has_com_reference(profile):
    assert profile.com_mu is not None and len(profile.com_mu) == len(profile.centers)
    assert profile.com_mu[-1] < profile.com_mu[0]     # 앉을수록 CoM이 뒤로 감
    assert min(profile.com_sd) >= SIM_CFG.min_com_sd


def test_com_gain_off_by_default_keeps_old_output(calib, profile):
    df = calib[0]
    a = run_trial(df, profile, SIM_CFG, shadow=False)
    b = run_trial(df, profile, replace(SIM_CFG, com_gain=0.0), shadow=False)
    assert np.allclose(a.tau_cmd_l, b.tau_cmd_l)
    assert "z_com" in a and "xcom" in a


def _pause_then_drop(fs=100.0):
    """서 있다가 40°까지 내려가 0.6초 멈춘 뒤 마지막 40°를 0.4초에 떨어지는 착석 (압력센서 · 충격 없음)."""
    seg = [np.zeros(int(1.0 * fs)), np.linspace(0, 40, int(0.8 * fs)), np.full(int(0.6 * fs), 40.0),
           40 + 40 * (0.5 - 0.5 * np.cos(np.linspace(0, np.pi, int(0.4 * fs)))), np.full(int(1.0 * fs), 80.0)]
    th = np.concatenate(seg)
    t = np.arange(len(th)) / fs
    return pd.DataFrame({"time_s": t, "thigh_l_deg": th, "thigh_r_deg": th, "trunk_deg": 0.0})


def test_pause_mid_descent_is_not_final_seat():
    from sit_assist import Segmenter, Kinematics
    df = _pause_then_drop()
    for resume, expect_descent_after_pause in ((15.0, True), (0.0, False)):
        cfg = replace(Config(), resume_vel=resume)
        kin, seg = [Kinematics(cfg), Kinematics(cfg)], Segmenter(cfg)
        phases = []
        for x in df.thigh_l_deg:
            o = [k(x) for k in kin]
            seg.update(0.0, np.array([o[0][0], o[1][0]]), np.array([o[0][1], o[1][1]]), np.nan)
            phases.append(seg.phase)
        phases = np.array(phases)
        drop = slice(int(2.5 * 100), int(2.75 * 100))           # 마지막으로 떨어지는 구간
        assert (phases[int(2.3 * 100):int(2.4 * 100)] == Phase.SEATED).any()   # 멈춘 동안은 앉은 것으로 판정됨
        assert ((phases[drop] == Phase.DESCENT).any()) == expect_descent_after_pause
