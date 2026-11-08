"""3차 실측 알고리즘(device_3rd_test)을 카메라 CoM과 함께 찍은 착석 60회에 재생해, 2차(device_2nd_test)와 비교한다.

    python firmware/replay_3rd_test.py [-D SA_BASE_BRAKE=3.0 ...]

각 H10 로그를 처음부터 끝까지 실제 장비처럼 100 Hz로 흘려 넣고, 착석마다 엉덩이가 닿기 전 3초 동안의
토크를 본다. 사람 데이터(data/, results/)가 있어야 돌아가며, 결과는 화면에만 출력한다.
"""
import argparse
import ctypes
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from preprocess_h10 import to_100hz  # noqa: E402

LOGMAP = {"IMG_2330_pose": "h10_1107_set.csv", "IMG_2331_pose": "h10_1107_set.csv",
          "IMG_2332_pose": "h10_1107_log1full.csv", "IMG_2333_pose": "h10_1107_log2.csv",
          "IMG_2334_pose": "h10_1107_B30.csv"}
STATE_BYTES = 4096


def build(src: Path, tmp: Path, defs: list[str]) -> ctypes.CDLL:
    lib = tmp / f"lib_{src.name}.so"
    cmd = ["cc", "-O2", "-shared", "-fPIC", "-DSA_USE_DOUBLE", "-DSA_SHADOW=0", "-I", str(src),
           *[f"-D{d}" for d in defs], "-o", str(lib), str(src / "sit_assist.c")]
    subprocess.run(cmd, check=True)
    L = ctypes.CDLL(str(lib))
    L.sa_update_100hz.argtypes = [ctypes.c_void_p] + [ctypes.c_double] * 5 + [ctypes.c_int, ctypes.POINTER(ctypes.c_double)]
    L.sa_log_state.restype = ctypes.c_float
    return L


def run(L, d: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    assert L.sa_state_size() <= STATE_BYTES
    st = ctypes.create_string_buffer(STATE_BYTES)
    L.sa_init(st)
    out = (ctypes.c_double * 2)()
    tau = np.zeros(len(d)); phase = np.zeros(len(d), int)
    for k, r in enumerate(d[["thigh_l_deg", "thigh_r_deg", "trunk_deg", "acc_ms2"]].to_numpy()):
        L.sa_update_100hz(st, r[0], r[1], r[2], float("nan"), r[3], 0, out)
        tau[k] = max(out[0], out[1]); phase[k] = int(L.sa_log_state(st)) // 10
    return tau, phase


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-D", action="append", default=[], help="3차 C 매크로 덮어쓰기 (예: SA_BASE_BRAKE=2.0)")
    ap.add_argument("--fig", default="", help="그림 저장 경로 (예: firmware/device_3rd_test/fig_replay.png)")
    args = ap.parse_args()
    sits = pd.read_csv(ROOT / "results/video/pooled_sits.csv")
    logs = {f: to_100hz(pd.read_csv(ROOT / "data/video" / f)) for f in set(LOGMAP.values())}
    with tempfile.TemporaryDirectory() as t:
        libs = {"2차": build(ROOT / "firmware/device_2nd_test", Path(t), []),
                "3차": build(ROOT / "firmware/device_3rd_test", Path(t), args.D)}
        res = {(n, f): run(L, logs[f]) for n, L in libs.items() for f in logs}
    rows = []
    for _, s in sits.iterrows():
        f = LOGMAP[s.source]; c = int(round(s.h10_contact_t * 100))
        for n in libs:
            tau, _ = res[(n, f)]
            w = tau[max(c - 300, 0):c + 1]
            on = np.flatnonzero(w > 0.1); hi = np.flatnonzero(w >= 6.0)
            seg = np.full(351, np.nan); lo = c - 300
            src = tau[max(lo, 0):c + 51]; seg[max(0, -lo):max(0, -lo) + len(src)] = src
            rows.append(dict(alg=n, group=s.group, type=s.type, dx=s.dx_contact, trace=seg,
                             peak=w.max(), mean_on=w[on].mean() if len(on) else 0.0,
                             braked=len(on) > 0, hi_lead_s=(len(w) - 1 - hi[0]) / 100 if len(hi) else np.nan))
    r = pd.DataFrame(rows)
    pd.set_option("display.width", 160)
    g = r.groupby(["alg", "group", "type"])
    print(g.agg(n=("peak", "size"), 제동=("braked", "mean"), 최대토크=("peak", "mean"),
                평균토크=("mean_on", "mean"), 강제동_선행s=("hi_lead_s", "median")).round(2))
    from scipy.stats import spearmanr
    print()
    for n in libs:
        x = r[r.alg == n]
        rho, p = spearmanr(x.mean_on, x.dx)
        print(f"{n} 평균 토크 vs 카메라 CoM(닿을 때) ρ = {rho:+.2f} (p = {p:.1e})  — 음수: CoM이 뒤로 빠질수록 세게 제동")
    if args.fig:
        plot(r, args.fig)


def plot(r: pd.DataFrame, path: str):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager as fm
    fm.fontManager.addfont("/System/Library/Fonts/AppleSDGothicNeo.ttc")
    plt.rcParams["font.family"] = "Apple SD Gothic Neo"; plt.rcParams["axes.unicode_minus"] = False
    plt.rcParams["font.size"] = 13
    C = {"그냥": "#8a8f8c", "털썩": "#d64545"}; t = np.arange(-300, 51) / 100
    fig, ax = plt.subplots(1, 3, figsize=(16, 4.6), dpi=160, gridspec_kw={"width_ratios": [1, 1, 1.1]})
    one = r.group.str.startswith("첫 번째")
    for k, n in enumerate(["2차", "3차"]):
        a = ax[k]
        for ty in ["그냥", "털썩"]:
            X = np.vstack(r[(r.alg == n) & one & (r.type == ty)].trace)
            m = np.nanmean(X, 0); q1, q3 = np.nanpercentile(X, [25, 75], 0)
            a.fill_between(t, q1, q3, color=C[ty], alpha=.18, lw=0)
            a.plot(t, m, color=C[ty], lw=2.4, label=f"{'그냥 앉기' if ty == '그냥' else '털썩 주저앉기'} (n={len(X)})")
        a.axvline(0, color="#333", lw=1, ls="--"); a.text(0.03, 9.4, "엉덩이가 닿음", fontsize=12)
        a.set_ylim(-0.3, 10); a.set_xlim(-3, 0.5); a.set_xlabel("엉덩이가 닿기까지 시간 (s)")
        a.set_ylabel("H10 제동 토크 (Nm)")
        a.set_title(f"{n} 코드: " + ("구간이 열리면 항상 9 Nm" if n == "2차" else "기본 3 Nm + 위험도만큼 (최대 9)"), fontsize=15)
        a.legend(loc="upper left", fontsize=12.5, frameon=False); a.grid(alpha=.25)
    from scipy.stats import spearmanr
    a = ax[2]
    for n, mk, col in [("2차", "o", "#b9bdbb"), ("3차", "o", "#2e7d4f")]:
        x = r[r.alg == n]; rho, p = spearmanr(x.mean_on, x.dx)
        a.scatter(x.dx, x.mean_on, s=26, marker=mk, color=col, alpha=.85, label=f"{n}  ρ = {rho:+.2f} (p = {p:.0e})")
    a.set_xlabel("카메라 CoM – 발목 거리 (왼쪽일수록 뒤로 빠짐)")
    a.set_ylabel("닿기 전 평균 제동 토크 (Nm)"); a.set_title("CoM이 뒤로 빠질수록 세게 제동하나 (착석 60회)", fontsize=15)
    a.legend(loc="upper right", fontsize=12.5, frameon=False); a.grid(alpha=.25)
    fig.tight_layout(); fig.savefig(path, bbox_inches="tight"); print("그림:", path)


if __name__ == "__main__":
    main()
