"""H10 SUIT 로그에서 앉기 동작을 찾아 알고리즘 입력(calib_repNN.csv)으로 잘라낸다.

1) hex 로그 디코딩 (h10_decode.py)
2) 1 kHz → 100 Hz (10샘플 평균. 알고리즘 Config.fs = 100)
3) 열 만들기
     thigh_l_deg / thigh_r_deg = thighDeg_LH / thighDeg_RH   (IMU 허벅지 절대각)
     trunk_deg = 좌우 평균(incPosDeg − thighDeg)            (고관절 각 − 허벅지 각 = 골반·상체 기울기)
4) 양쪽 허벅지 평균이 20° 아래(서 있음)에서 45° 위(앉음)로 넘어가는 구간을 앉기 1회로 보고,
   직전에 가장 똑바로 선 순간(최대 1초 전) ~ 착석 후 최대 1초(다시 일어서기 전)를 잘라 저장한다. 구간 첫 샘플이
   알고리즘의 '서 있는 자세' 기준이 되므로, 일어서는 동작 중간부터 자르면 안 된다.
5) H10 보조 토크(u_RH/u_LH)가 켜져 있던 앉기는 기본으로 뺀다 (캘리브레이션은 보조 OFF여야 함).

    python preprocess_h10.py ~/Downloads/SUIT_LOGGED_DATA-*.csv --out data/real/S01
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.signal import butter, sosfiltfilt

from h10_decode import decode_file

RAW_FS = 1000
FS = 100
STAND_DEG, SIT_DEG = 20.0, 45.0
PRE_S, POST_S = 1.0, 1.0     # 착석 시작 전 최대 1초, 착석 후 최대 1초 (다시 일어서기 전까지)
ASSIST_U = 0.05         # |u|가 이보다 크면 보조가 켜져 있던 것


def to_100hz(df: pd.DataFrame) -> pd.DataFrame:
    k = RAW_FS // FS
    n = len(df) // k * k
    cols = ["thighDeg_LH", "thighDeg_RH", "incPosDeg_LH", "incPosDeg_RH", "u_LH", "u_RH"]
    x = df[cols].to_numpy(dtype=float)[:n].reshape(-1, k, len(cols)).mean(axis=1)
    out = pd.DataFrame(x, columns=cols)
    out.insert(0, "time_s", np.arange(len(out)) / FS)
    out["thigh_l_deg"] = out["thighDeg_LH"]
    out["thigh_r_deg"] = out["thighDeg_RH"]
    out["trunk_deg"] = ((out["incPosDeg_LH"] - out["thighDeg_LH"]) + (out["incPosDeg_RH"] - out["thighDeg_RH"])) / 2
    return out


def find_sit_downs(d: pd.DataFrame) -> list[dict]:
    """서 있음 → 앉음 전환을 찾는다. 시작/끝은 양방향 필터한 평균 허벅지 속도로 정한다."""
    sos = butter(2, 2.0 / (FS / 2), output="sos")
    m = sosfiltfilt(sos, d[["thigh_l_deg", "thigh_r_deg"]].mean(axis=1).to_numpy())
    w = np.gradient(m) * FS
    events, state, last_low, prev_end = [], None, 0, 0
    for i, v in enumerate(m):
        if v < STAND_DEG:
            state, last_low = "stand", i
        elif v > SIT_DEG:
            if state == "stand":
                pk = last_low + int(np.argmax(w[last_low:i + 50]))
                onset = pk - int(np.argmax(w[:pk][::-1] < 5.0))
                end = pk + int(np.argmax(w[pk:] < 3.0))
                # 이전 앉기 이후 가장 똑바로 선 순간 (실험에서 일어선 뒤 바로 다시 앉아 서 있는 시간이 짧다)
                upright = prev_end + int(np.argmin(m[prev_end:onset]))
                rising = np.nonzero(w[end:] < -10.0)[0]       # 다음 일어서기 시작
                stand_up = end + int(rising[0]) if len(rising) else len(w)
                events.append({"onset": onset, "peak": pk, "end": end, "upright": upright, "stand_up": stand_up})
                prev_end = end
            state = "sit"
    return events


def extract(files: list[Path], out: Path, include_assist: bool = False) -> pd.DataFrame:
    out.mkdir(parents=True, exist_ok=True)
    rows, rep = [], 0
    for f in files:
        d = to_100hz(decode_file(f))
        for ev in find_sit_downs(d):
            on, end = ev["onset"], ev["end"]
            u = d[["u_LH", "u_RH"]].iloc[on:end].abs().to_numpy().max()
            assisted = bool(u > ASSIST_U)
            a = max(on - int(PRE_S * FS), ev["upright"])
            b = min(end + int(POST_S * FS), ev["stand_up"] + int(0.3 * FS), len(d))   # 착석 판정이 끝날 여유
            info = {"source": f.name, "onset_s": on / FS, "duration_s": (end - on) / FS,
                    "standing_before_s": (on - a) / FS,
                    "thigh_start": round(float(d[["thigh_l_deg", "thigh_r_deg"]].iloc[on].mean()), 1),
                    "thigh_end": round(float(d[["thigh_l_deg", "thigh_r_deg"]].iloc[end].mean()), 1),
                    "assist_on": assisted, "used": include_assist or not assisted}
            if info["used"]:
                rep += 1
                seg = d.iloc[a:b][["time_s", "thigh_l_deg", "thigh_r_deg", "trunk_deg"]].copy()
                seg["time_s"] = (seg["time_s"] - seg["time_s"].iloc[0]).round(3)
                name = f"calib_rep{rep:02d}.csv"
                seg.round(3).to_csv(out / name, index=False)
                info["file"] = name
            rows.append(info)
    log = pd.DataFrame(rows)
    log.to_csv(out / "extraction_log.csv", index=False)
    (out / "meta.json").write_text(json.dumps(
        {"source_files": [f.name for f in files], "fs_raw_hz": RAW_FS, "fs_hz": FS,
         "trunk_deg": "mean(incPosDeg - thighDeg) of both sides",
         "n_used": int(log["used"].sum()), "n_found": len(log)}, indent=2, ensure_ascii=False))
    return log


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--out", default="data/real/S01")
    ap.add_argument("--include-assist", action="store_true", help="보조가 켜진 앉기도 포함")
    args = ap.parse_args()
    log = extract([Path(f) for f in args.files], Path(args.out), args.include_assist)
    print(log.to_string(index=False))
    print(f"\n앉기 {len(log)}회 발견, {int(log.used.sum())}회 저장 → {args.out}")


if __name__ == "__main__":
    main()
