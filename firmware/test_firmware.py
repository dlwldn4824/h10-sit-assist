"""C 펌웨어 구현이 Python 구현과 같은 토크를 내는지 실측 착석으로 확인한다.

    python -m pytest -q firmware/test_firmware.py
"""
import ctypes
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sit_assist import Config, Profile, run_trial  # noqa: E402

FW = ROOT / "firmware"
PROFILE = ROOT / "results" / "real" / "profile_45ref.json"
TRIALS = sorted((ROOT / "data" / "real" / "chair30").glob("calib_rep*.csv")) + \
    sorted((ROOT / "data" / "real" / "chair45").glob("calib_rep*.csv"))

pytestmark = pytest.mark.skipif(not (PROFILE.exists() and TRIALS and shutil.which("cc")),
                                reason="실측 데이터(compare_chairs.py 결과) 또는 C 컴파일러 없음")


def build(tmp: Path, double: bool) -> ctypes.CDLL:
    subprocess.run([sys.executable, str(FW / "export_params.py"), "--profile", str(PROFILE),
                    "--out", str(tmp / "sit_assist_params.h")], check=True, capture_output=True)
    lib = tmp / ("libsa_d.so" if double else "libsa_f.so")
    cmd = ["cc", "-O2", "-shared", "-fPIC", "-I", str(tmp), "-o", str(lib), str(FW / "sit_assist.c")]
    if double:
        cmd.insert(1, "-DSA_USE_DOUBLE")
    cmd.insert(1, "-DSA_TAU_LIMIT=1000")      # 비교할 때는 안전 상한을 풀어 둔다
    subprocess.run(cmd, check=True)
    return ctypes.CDLL(str(lib))


def run_c(lib, df: pd.DataFrame, double: bool) -> np.ndarray:
    real = ctypes.c_double if double else ctypes.c_float
    lib.sa_update_100hz.argtypes = [ctypes.c_void_p, real, real, real, real, real, ctypes.c_int, ctypes.POINTER(real)]
    state = ctypes.create_string_buffer(lib.sa_state_size())
    lib.sa_init(state)
    out = (real * 2)()
    taus = []
    acc = df["acc_ms2"] if "acc_ms2" in df else [float("nan")] * len(df)
    for tl, tr, tk, ac in zip(df.thigh_l_deg, df.thigh_r_deg, df.trunk_deg, acc):
        lib.sa_update_100hz(state, tl, tr, tk, float("nan"), ac, 0, out)
        taus.append((out[0], out[1]))
    return np.array(taus)


@pytest.mark.parametrize("double,tol", [(True, 1e-6), (False, 0.05)])
def test_c_matches_python(tmp_path, double, tol):
    lib = build(tmp_path, double)
    prof = Profile.load(PROFILE)
    worst = 0.0
    for f in TRIALS:
        df = pd.read_csv(f)
        py = run_trial(df, prof, Config(), shadow=True)[["tau_cmd_l", "tau_cmd_r"]].to_numpy()
        worst = max(worst, float(np.abs(run_c(lib, df, double) - py).max()))
    assert worst < tol, f"최대 차이 {worst:.6f} Nm"


LOGS = sorted((ROOT / "data" / "video").glob("h10_*.csv"))   # 끊기지 않은 실측 로그 (서 있음 · 멈칫 · 일어섬 포함)


@pytest.mark.skipif(not LOGS, reason="끊기지 않은 실측 로그(data/video/h10_*.csv) 없음")
def test_c_matches_python_on_continuous_logs(tmp_path):
    """잘라낸 앉기만으로는 '멈칫 뒤 다시 내려감' 같은 상태 전환이 잘 안 나온다. 전체 로그로도 같은지 본다."""
    from preprocess_h10 import to_100hz
    lib = build(tmp_path, True)
    prof = Profile.load(PROFILE)
    worst = 0.0
    for f in LOGS:
        df = to_100hz(pd.read_csv(f))
        py = run_trial(df, prof, Config(), shadow=True)[["tau_cmd_l", "tau_cmd_r"]].to_numpy()
        worst = max(worst, float(np.abs(run_c(lib, df, True) - py).max()))
    assert worst < 1e-6, f"최대 차이 {worst:.6f} Nm"
