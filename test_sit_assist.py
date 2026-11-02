"""가짜 데이터 한 명분으로 착석 보조가 설계대로 반응하는지 확인한다."""
import numpy as np
import pandas as pd
import pytest

from evaluate import calib_loo, trial_metrics
from simulate_data import make_person, simulate_sit
from sit_assist import Phase, Profile, SitAssistController, run_trial


@pytest.fixture(scope="module")
def person():
    return make_person(np.random.default_rng(1), "T01")


@pytest.fixture(scope="module")
def calib(person):
    rng = np.random.default_rng(2)
    return [simulate_sit(rng, person, "standard", 0.0) for _ in range(15)]


@pytest.fixture(scope="module")
def profile(calib):
    return Profile.from_trials(calib)


def sit(person, profile, chair, fatigue, shadow, seed=3):
    ctrl = SitAssistController(profile, shadow=shadow)
    return simulate_sit(np.random.default_rng(seed), person, chair, fatigue, ctrl)


def test_profile_shape(profile):
    assert profile.n_trials == 15
    assert 60 < profile.contact_mean < 80
    assert max(profile.mu_l) > 40                  # 중간에 가장 빠름
    assert profile.mu_l[-1] < max(profile.mu_l)    # 의자 근처에서 느려짐


def test_profile_save_load(profile, tmp_path):
    profile.save(tmp_path / "p.json")
    assert Profile.load(tmp_path / "p.json") == profile


def test_normal_sitting_rarely_brakes(calib):
    loo = calib_loo(calib)
    assert loo.triggered.mean() <= 0.2
    assert loo.deep.sum() <= 1                  # 평소 착석 각도 +2SD라 가끔은 넘을 수 있음


def test_standing_still_no_torque(profile):
    ctrl = SitAssistController(profile)
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
    assert df[["tau_cmd_l", "tau_cmd_r"]].max().max() > 5     # 계산은 했지만
    replay = run_trial(df, profile, shadow=True)                # 같은 결과가 재현됨
    assert np.allclose(replay.tau_cmd_l, df.tau_cmd_l, atol=1e-3)


def test_adaptive_reduces_fast_descent(person, profile):
    off = trial_metrics(sit(person, profile, "low", 1.0, shadow=True))
    on = trial_metrics(sit(person, profile, "low", 1.0, shadow=False))
    assert on["contact_vel"] < off["contact_vel"] * 0.9
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
    rev = pd.DataFrame({"time_s": df.time_s, "hip_l_deg": df.hip_l_deg[::-1].to_numpy(),
                        "hip_r_deg": df.hip_r_deg[::-1].to_numpy()})
    log = run_trial(rev, profile, shadow=True)
    assert log[["tau_cmd_l", "tau_cmd_r"]].max().max() == 0
