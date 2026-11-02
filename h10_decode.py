"""H10 SUIT 로그(hex 한 줄 = 한 샘플)를 표 형태로 디코딩한다.

수업에서 받은 KW_decoder.py와 같은 필드 순서·환산 상수를 쓴다. 로거 설정에서 필드를
바꾸면 FIELDS도 같이 바꿔야 한다.

    python h10_decode.py SUIT_LOGGED_DATA-5.csv --out decoded/SUIT-5.csv
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

FULL = 65535
DEG = FULL / 720            # deg, -360 ~ +360
CURRENT = FULL / 360        # A, -180 ~ +180
ACC = FULL / 78.4532        # m/s², ±4g
GYRO = FULL / 1000          # deg/s, -500 ~ +500
EMG = FULL / 2
CONTROL = FULL / 30
VELDEG = FULL / 6000

# (이름, 형식, 환산 상수). loopCnt는 uint32
FIELDS = [
    ("loopCnt", "u32", None), ("assist_level", "f16", 100),
    ("thighDeg_RH", "f16", DEG), ("incPosDeg_RH", "f16", DEG), ("MotorActCurrent_RH", "f16", CURRENT),
    ("accX_Calib_RH", "f16", ACC), ("accY_Calib_RH", "f16", ACC), ("gyroZ_Calib_RH", "f16", GYRO),
    ("thighDeg_LH", "f16", DEG), ("incPosDeg_LH", "f16", DEG), ("MotorActCurrent_LH", "f16", CURRENT),
    ("accX_Calib_LH", "f16", ACC), ("accY_Calib_LH", "f16", ACC), ("gyroZ_Calib_LH", "f16", GYRO),
    ("u_RH", "f16", CONTROL), ("u_LH", "f16", CONTROL),
    ("Pvector_ref_RH", "f16", DEG), ("Pvector_ref_LH", "f16", DEG),
    ("extension_control_mode", "u8", None),
    ("emg_R1", "f16", EMG), ("emg_L1", "f16", EMG),
    ("fsr_R1", "u16", None), ("fsr_R2", "u16", None), ("fsr_L1", "u16", None), ("fsr_L2", "u16", None),
    ("free_var1", "f16", VELDEG), ("free_var2", "f16", VELDEG),
]
WIDTH = {"u32": 8, "f16": 4, "u16": 4, "u8": 2}
LINE_LEN = sum(WIDTH[f] for _, f, _ in FIELDS)


def decode_line(hex_str: str) -> list[float] | None:
    if len(hex_str) < LINE_LEN:
        return None                        # 마지막 줄 등 잘린 샘플
    out, cur = [], 0
    try:
        for _, kind, const in FIELDS:
            v = int(hex_str[cur:cur + WIDTH[kind]], 16)
            cur += WIDTH[kind]
            if kind == "f16":
                v = (v - 0x10000 if v > 0x7FFF else v) / const
            out.append(v)
    except ValueError:
        return None
    return out


def decode_file(path: Path) -> pd.DataFrame:
    rows = []
    for raw in Path(path).read_bytes().split(b"\n"):
        line = raw.replace(b"\x00", b"").decode("utf-8", errors="ignore").strip()
        row = decode_line(line)
        if row is not None:
            rows.append(row)
    df = pd.DataFrame(rows, columns=[name for name, _, _ in FIELDS])
    df = df.drop_duplicates("loopCnt").sort_values("loopCnt").reset_index(drop=True)
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--out")
    args = ap.parse_args()
    df = decode_file(Path(args.file))
    out = Path(args.out) if args.out else Path(args.file).with_suffix(".decoded.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    df.round(4).to_csv(out, index=False)
    print(f"{len(df)}개 샘플 → {out}")


if __name__ == "__main__":
    main()
