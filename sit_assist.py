"""H10 적응형 착석 보조 (Adaptive Sit-Down Braking + 상체 숙임 지지).

표준 높이 의자에서 평소처럼 10~15번 앉은 데이터로 사용자 기준을 만든다.
    - 허벅지 각도 구간별 평소 허벅지 굴곡 속도
    - 허벅지 각도 구간별 평소 상체 숙임 각도 (허리 IMU)
착석 중에는 두 가지 신전 방향 토크를 더해서 준다.
    1) 상체 지지: 상체를 숙이고 버티는 고관절 신전근 부담을 덜어 '숙이고 앉는' 자세를 유지하게 함
    2) 하강 제동: 허벅지가 평소보다 빨리 굽혀지면 제동. 평소 착석 각도를 지나서도 계속
       내려가면(낮은 의자) 더 강하게, 상체가 평소보다 서 있으면(뒤로 주저앉는 자세) 더 강하게.
두 토크 모두 신전 방향이라 서로 부딪치지 않는다.

입력: 시간(s), 좌/우 허벅지 굴곡 각도(deg, 수직 기준, 굽힐수록 +),
      상체 숙임 각도(deg, 허리 IMU, 앞으로 숙일수록 +, 선택), 의자 압력센서 0/1(선택)
출력: 좌/우 신전 토크 크기(Nm, 0 이상). 실제 부호는 H10 SDK 규약에 맞춰 바꾼다.
"""
from __future__ import annotations

import json
import warnings
from dataclasses import asdict, dataclass
from enum import IntEnum
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.signal import butter


class Phase(IntEnum):
    STANDING = 0
    DESCENT = 1     # 내려가는 중
    DEEP = 2        # 평소 착석 각도를 넘어서도 계속 내려가는 중 (낮은 의자)
    SEATED = 3


class Level(IntEnum):
    NONE = 0        # 정상 범위 → 제동 없음
    WEAK = 1        # 기준보다 조금 빠름 → 약한 제동
    STRONG = 2      # 기준보다 매우 빠름 / 급가속 → 강한 제동


class Posture(IntEnum):
    OK = 0          # 평소처럼 상체를 숙이고 내려감
    UPRIGHT = 1     # 상체가 평소보다 서 있음 → 뒤로 주저앉기 쉬운 자세


@dataclass
class Config:
    fs: float = 100.0
    angle_cutoff_hz: float = 6.0
    accel_cutoff_hz: float = 3.0     # 각가속도는 잡음이 커서 더 세게 거른다
    trunk_cutoff_hz: float = 4.0
    # 착석 시작 / 착석 판단
    onset_vel: float = 5.0          # deg/s, 양쪽이 이보다 빠르게 굽히면 시작
    onset_hold_s: float = 0.1
    seat_vel: float = 8.0           # 압력센서가 없을 때: |ω|가 이보다 작으면 앉은 것 (앉은 뒤에도 몸이 조금 흔들림)
    seat_hold_s: float = 0.15
    min_seat_depth: float = 20.0    # deg, 이보다 얕게 멈추면 앉은 것으로 보지 않음
    stand_depth: float = 10.0       # deg, 앉은 뒤 이만큼 펴지면 일어선 것
    # 개인 기준값
    bin_deg: float = 5.0
    min_sd: float = 25.0            # deg/s, 정상 착석 30회도 같은 각도에서 이만큼은 흔들림 (11/4 실측)
    min_sd_ratio: float = 0.1
    min_lean_sd: float = 3.0        # deg
    # 하강 제동
    z_weak: float = 3.5             # 이 점수부터 약한 제동
    z_strong: float = 5.0           # 이 점수부터 강한 제동
    gain: float = 2.5               # Nm / 점수
    brake_from_ratio: float = 0.5   # 평소 착석 각도의 절반을 지나서부터 제동 (털썩은 착석 직전에 일어남)
    deep_gain: float = 1.5          # DEEP 구간에서 gain에 곱하는 값
    deep_margin_sd: float = 2.0     # 평소 착석 각도 + 2SD를 넘으면 DEEP
    deep_min_margin: float = 3.0    # deg
    deep_target_ratio: float = 1.0  # DEEP에서는 평소 착석 순간 속도를 넘지 않도록 요구
    alpha_sd: float = 3.0           # 각가속도가 평소 최대 + 3SD를 넘으면 급가속
    lookahead_s: float = 0.05       # 0.05초 뒤 속도와 기준을 예측해서 미리 반응
    # 자세 (허리 IMU가 있을 때만)
    support_gain: float = 0.0       # Nm, 상체 지지 토크 = support_gain × sin(상체 숙임). 실측 후 사용하지 않기로 함 (0)
    upright_margin_sd: float = 2.0  # 평소 숙임 − 2SD보다 덜 숙이면 UPRIGHT
    upright_min_margin: float = 6.0 # deg
    upright_gain: float = 1.5       # UPRIGHT일 때 제동 gain에 곱하는 값
    # 출력
    tau_max: float = 10.0           # Nm. H10 사양 이하로, 실험은 낮은 값부터 올린다
    rise_rate: float = 60.0         # Nm/s, 토크가 늘어나는 최대 속도
    release_s: float = 0.3          # tau_max에서 0까지 내리는 데 걸리는 시간


# ---------------------------------------------------------------- 신호 처리

class _Lowpass:
    """2차 Butterworth 저역통과. 샘플 하나씩 넣는다 (scipy 호출보다 훨씬 빠름)."""

    def __init__(self, fs: float, cutoff: float):
        b, a = butter(2, cutoff / (fs / 2))
        self.b0, self.b1, self.b2 = b
        self.a1, self.a2 = a[1], a[2]
        self.z1 = self.z2 = None

    def __call__(self, x: float) -> float:
        if self.z1 is None:      # 첫 값에서 멈춰 있던 것처럼 시작 (출발 튐 방지)
            self.z1 = x * (1 - self.b0)
            self.z2 = x * (self.b2 - self.a2)
        y = self.b0 * x + self.z1
        self.z1 = self.b1 * x - self.a1 * y + self.z2
        self.z2 = self.b2 * x - self.a2 * y
        return y


class Kinematics:
    """한쪽 허벅지 각도 → (필터된 각도, 각속도, 각가속도). 인과적(실시간용)."""

    def __init__(self, cfg: Config):
        self.fs = cfg.fs
        self.f_angle = _Lowpass(cfg.fs, cfg.angle_cutoff_hz)
        self.f_accel = _Lowpass(cfg.fs, cfg.accel_cutoff_hz)
        self.prev_th = None
        self.prev_w = 0.0

    def __call__(self, x: float) -> tuple[float, float, float]:
        th = self.f_angle(x)
        w = 0.0 if self.prev_th is None else (th - self.prev_th) * self.fs
        a = self.f_accel((w - self.prev_w) * self.fs)
        self.prev_th, self.prev_w = th, w
        return th, w, a


class Segmenter:
    """서 있음 → 내려감 → 앉음을 판단한다. 양쪽 허벅지 평균 움직임을 본다."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.phase = Phase.STANDING
        self.stand = None            # 서 있을 때 허벅지 각도 (좌, 우)
        self.stand_trunk = None      # 서 있을 때 상체 각도
        self.onset_t = None
        self.contact_t = None
        self._n_onset = self._n_seat = self._n_rise = 0
        self._cand_t = None

    def update(self, t: float, th: np.ndarray, w: np.ndarray, seat: float,
               trunk: float = np.nan) -> tuple[np.ndarray, float]:
        """서 있을 때 대비 허벅지 굴곡 Δθ (좌, 우)와 상체 숙임 Δ를 돌려준다."""
        c = self.cfg
        hold_on = round(c.onset_hold_s * c.fs)
        hold_seat = round(c.seat_hold_s * c.fs)
        if self.stand is None:
            self.stand = th.copy()
            self.stand_trunk = trunk
        d = th - self.stand
        lean = trunk - self.stand_trunk
        wm, dm = w.mean(), d.mean()

        if self.phase == Phase.STANDING:
            if abs(wm) < c.onset_vel:                     # 가만히 서 있을 때만 기준 자세 갱신
                self.stand += 0.02 * (th - self.stand)
                self.stand_trunk += 0.02 * (trunk - self.stand_trunk)
            if (w > c.onset_vel).all():
                self._n_onset += 1
                if self._n_onset == 1:
                    self._cand_t = t
                if self._n_onset >= hold_on:
                    self.phase, self.onset_t, self.contact_t = Phase.DESCENT, self._cand_t, None
                    self._n_onset = self._n_seat = self._n_rise = 0
            else:
                self._n_onset = 0

        elif self.phase in (Phase.DESCENT, Phase.DEEP):
            if not np.isnan(seat):                        # 의자 압력센서가 있으면 그것을 믿는다
                if seat > 0.5:
                    self.phase, self.contact_t = Phase.SEATED, t
            elif abs(wm) < c.seat_vel and dm > c.min_seat_depth:
                self._n_seat += 1
                if self._n_seat == 1:
                    self._cand_t = t
                if self._n_seat >= hold_seat:
                    self.phase, self.contact_t = Phase.SEATED, self._cand_t
            else:
                self._n_seat = 0
            self._n_rise = self._n_rise + 1 if wm < -c.onset_vel else 0
            if self._n_rise >= hold_on:                   # 펴지기 시작함
                if dm > c.min_seat_depth:                 # 깊이 내려간 뒤면 착석을 놓친 것 → 앉은 것으로 처리
                    self.phase, self.contact_t = Phase.SEATED, t
                else:                                     # 얕을 때면 앉다가 다시 일어섬 → 취소
                    self.phase = Phase.STANDING

        elif self.phase == Phase.SEATED and dm < c.stand_depth:
            self.phase = Phase.STANDING
        return d, lean


def _column(df: pd.DataFrame, name: str) -> np.ndarray:
    if name in df:
        return df[name].to_numpy(dtype=float)
    return np.full(len(df), np.nan)


def segment_trial(df: pd.DataFrame, cfg: Config = Config()) -> dict:
    """한 시행을 실시간과 같은 방식으로 처리해 Δθ, ω, α, 상체 숙임과 착석 시작/종료 시점을 구한다."""
    kin = [Kinematics(cfg), Kinematics(cfg)]
    f_trunk = _Lowpass(cfg.fs, cfg.trunk_cutoff_hz)
    seg = Segmenter(cfg)
    t = df["time_s"].to_numpy(dtype=float)
    thighs = df[["thigh_l_deg", "thigh_r_deg"]].to_numpy(dtype=float)
    trunk, seat = _column(df, "trunk_deg"), _column(df, "seat")
    n = len(t)
    d, w, a = np.zeros((n, 2)), np.zeros((n, 2)), np.zeros((n, 2))
    lean = np.full(n, np.nan)
    onset_t = contact_t = None
    for k in range(n):
        out = [kin[i](thighs[k, i]) for i in (0, 1)]
        th = np.array([o[0] for o in out])
        w[k] = [o[1] for o in out]
        a[k] = [o[2] for o in out]
        tr = f_trunk(trunk[k]) if not np.isnan(trunk[k]) else np.nan
        d[k], lean[k] = seg.update(t[k], th, w[k], seat[k], tr)
        if onset_t is None and seg.onset_t is not None:
            onset_t = seg.onset_t
        if onset_t is not None and contact_t is None and seg.contact_t is not None:
            contact_t = seg.contact_t
    return {"t": t, "dtheta": d, "omega": w, "alpha": a, "lean": lean,
            "onset_t": onset_t, "contact_t": contact_t}


# ---------------------------------------------------------------- 개인 기준값

@dataclass
class Profile:
    """표준 의자 착석 10~15회로 만든 개인 기준."""
    centers: list           # 허벅지 Δθ 구간 중심 (deg)
    mu_l: list              # 구간별 평소 허벅지 굴곡 속도 평균 (deg/s)
    sd_l: list
    mu_r: list
    sd_r: list
    contact_mean: float     # 평소 엉덩이가 닿는 Δθ (deg)
    contact_sd: float
    alpha_max: float        # 이보다 큰 각가속도는 급가속 (deg/s²)
    n_trials: int
    lean_mu: list | None = None   # 구간별 평소 상체 숙임 (deg). 허리 IMU가 없으면 None
    lean_sd: list | None = None

    def ref(self, side: int, d: float) -> tuple[float, float]:
        mu, sd = (self.mu_l, self.sd_l) if side == 0 else (self.mu_r, self.sd_r)
        return float(np.interp(d, self.centers, mu)), float(np.interp(d, self.centers, sd))

    def end_ref(self, side: int) -> tuple[float, float]:
        """평소 엉덩이가 닿는 각도에서의 속도 (DEEP 구간의 목표 계산용)."""
        return self.ref(side, self.contact_mean)

    def lean_ref(self, d: float) -> tuple[float, float]:
        return float(np.interp(d, self.centers, self.lean_mu)), float(np.interp(d, self.centers, self.lean_sd))

    def deep_threshold(self, cfg: Config = Config()) -> float:
        return self.contact_mean + max(cfg.deep_margin_sd * self.contact_sd, cfg.deep_min_margin)

    @classmethod
    def from_trials(cls, dfs: list[pd.DataFrame], cfg: Config = Config()) -> "Profile":
        segs = []
        for df in dfs:
            s = segment_trial(df, cfg)
            if s["onset_t"] is None or s["contact_t"] is None:
                print("[경고] 착석 시작/종료를 못 찾은 시행을 기준값에서 뺐습니다.")
                continue
            segs.append(s)
        if len(segs) < 3:
            raise ValueError(f"기준값을 만들 착석 시행이 부족합니다 ({len(segs)}회). 최소 3회, 권장 10~15회.")

        contacts, alphas = [], []
        for s in segs:
            m = (s["t"] >= s["onset_t"]) & (s["t"] <= s["contact_t"])
            s["mask"] = m
            contacts.append(s["dtheta"][m][-1].mean())
            alphas.append(s["alpha"][m].max())
        contacts = np.array(contacts)

        edges = np.arange(0.0, contacts.max() + cfg.bin_deg, cfg.bin_deg)
        centers = (edges[:-1] + edges[1:]) / 2

        def binned(values) -> tuple[np.ndarray, np.ndarray]:
            """values(s) → 시행별 구간 평균 → 시행 사이 평균, SD. 3회 미만 구간은 이웃 값으로 채움."""
            per_trial = np.full((len(segs), len(centers)), np.nan)
            for k, s in enumerate(segs):
                d, v = s["dtheta"][s["mask"]].mean(axis=1), values(s)[s["mask"]]
                idx = np.digitize(d, edges) - 1
                for b in range(len(centers)):
                    if (idx == b).any():
                        per_trial[k, b] = v[idx == b].mean()
            ok = np.sum(~np.isnan(per_trial), axis=0) >= 3
            with warnings.catch_warnings():               # 아무도 안 지나간 구간은 nan
                warnings.simplefilter("ignore", RuntimeWarning)
                mu = np.nanmean(per_trial, axis=0)
                sd = np.nanstd(per_trial, axis=0, ddof=1)
            return np.interp(centers, centers[ok], mu[ok]), np.interp(centers, centers[ok], sd[ok])

        mus, sds = [], []
        for side in (0, 1):
            mu, sd = binned(lambda s: s["omega"][:, side])
            sd = np.maximum.reduce([sd, np.full_like(sd, cfg.min_sd), cfg.min_sd_ratio * np.abs(mu)])
            mus.append(mu)
            sds.append(sd)

        lean_mu = lean_sd = None
        if not np.isnan(segs[0]["lean"]).all():
            lmu, lsd = binned(lambda s: s["lean"])
            lean_mu, lean_sd = lmu.round(3).tolist(), np.maximum(lsd, cfg.min_lean_sd).round(3).tolist()

        alphas = np.array(alphas)
        return cls(centers=centers.round(2).tolist(),
                   mu_l=mus[0].round(3).tolist(), sd_l=sds[0].round(3).tolist(),
                   mu_r=mus[1].round(3).tolist(), sd_r=sds[1].round(3).tolist(),
                   contact_mean=round(float(contacts.mean()), 3),
                   contact_sd=round(float(contacts.std(ddof=1)), 3),
                   alpha_max=round(float(alphas.mean() + cfg.alpha_sd * alphas.std(ddof=1)), 3),
                   n_trials=len(segs), lean_mu=lean_mu, lean_sd=lean_sd)

    def save(self, path: Path) -> None:
        Path(path).write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False))

    @classmethod
    def load(cls, path: Path) -> "Profile":
        return cls(**json.loads(Path(path).read_text()))


# ---------------------------------------------------------------- 실시간 제어

class SitAssistController:
    """H10 제어 루프에서 샘플마다 update()를 부른다.

        ctrl = SitAssistController(Profile.load("profile.json"))
        while running:
            t, thigh_l, thigh_r = h10.read_thigh_angles()   # ← H10 SDK 호출로 바꾸기
            trunk = h10.read_waist_pitch()
            tau_l, tau_r = ctrl.update(t, thigh_l, thigh_r, trunk=trunk, seat=fsr.read())
            h10.set_extension_torque(tau_l, tau_r)

    shadow=True면 계산과 기록은 하되 출력 토크는 0이다 (보조 OFF 조건용).
    """

    def __init__(self, profile: Profile, cfg: Config = Config(), shadow: bool = False):
        self.p, self.cfg, self.shadow = profile, cfg, shadow
        self.kin = [Kinematics(cfg), Kinematics(cfg)]
        self.f_trunk = _Lowpass(cfg.fs, cfg.trunk_cutoff_hz)
        self.seg = Segmenter(cfg)
        self.tau = np.zeros(2)
        self.deep_thr = profile.deep_threshold(cfg)
        self.info: dict = {}

    def update(self, t: float, thigh_l: float, thigh_r: float,
               trunk: float | None = None, seat: float | None = None) -> tuple[float, float]:
        c, p = self.cfg, self.p
        out = [self.kin[0](thigh_l), self.kin[1](thigh_r)]
        th = np.array([o[0] for o in out])
        w = np.array([o[1] for o in out])
        a = np.array([o[2] for o in out])
        has_trunk = trunk is not None and not np.isnan(trunk) and p.lean_mu is not None
        tr = self.f_trunk(trunk) if has_trunk else np.nan
        d, lean = self.seg.update(t, th, w, np.nan if seat is None else float(seat), tr)

        if self.seg.phase == Phase.DESCENT and d.mean() > self.deep_thr:
            self.seg.phase = Phase.DEEP
        phase = self.seg.phase
        dm, wm = d.mean(), w.mean()
        moving = phase in (Phase.DESCENT, Phase.DEEP) and wm > 0
        late = dm > c.brake_from_ratio * p.contact_mean

        # 자세: 평소보다 상체를 덜 숙였는가 (뒤로 주저앉는 패턴)
        posture, lean_ref = Posture.OK, np.nan
        if has_trunk and moving and late:
            lean_ref, lean_sd = p.lean_ref(dm)
            if lean < lean_ref - max(c.upright_margin_sd * lean_sd, c.upright_min_margin):
                posture = Posture.UPRIGHT

        # 1) 상체 지지 토크: 숙인 상체를 버티는 신전근 부담을 일부 덜어 줌
        support = 0.0
        if has_trunk and moving:
            support = c.support_gain * np.sin(np.radians(max(lean, 0.0)))

        # 2) 하강 제동 토크
        brake, z, ref = np.zeros(2), np.zeros(2), np.zeros(2)
        if moving and late:
            for i in (0, 1):
                if phase == Phase.DEEP:
                    mu_end, sd = p.end_ref(i)
                    ref[i], g = c.deep_target_ratio * mu_end, c.gain * c.deep_gain
                else:   # 0.05초 뒤 도착할 각도의 기준과 비교 (평소의 정상 가속은 기준에 이미 들어 있음)
                    # 기준은 좌우 평균 Δθ 구간으로 만들었으므로 조회도 평균 Δθ로 한다 (좌우 각도 차이에 강함)
                    (ref[i], sd), g = p.ref(i, dm + wm * c.lookahead_s), c.gain
                if posture == Posture.UPRIGHT:
                    g *= c.upright_gain
                w_pred = w[i] + a[i] * c.lookahead_s
                z[i] = (w_pred - ref[i]) / sd
                if a[i] > p.alpha_max and w[i] > ref[i]:     # 털썩 내려앉는 급가속
                    z[i] = max(z[i], c.z_strong)
                brake[i] = max(g * (z[i] - c.z_weak), 0.0)

        target = np.clip(support + brake, 0.0, c.tau_max)
        # 토크가 갑자기 걸리거나 빠지지 않도록 변화 속도 제한
        up, down = c.rise_rate / c.fs, c.tau_max / (c.release_s * c.fs)
        self.tau = np.clip(target, self.tau - down, self.tau + up)

        zmax = z.max()
        level = Level.STRONG if zmax >= c.z_strong else Level.WEAK if zmax >= c.z_weak else Level.NONE
        self.info = {"phase": int(phase), "level": int(level), "posture": int(posture),
                     "dtheta_l": d[0], "dtheta_r": d[1], "omega_l": w[0], "omega_r": w[1],
                     "alpha_l": a[0], "alpha_r": a[1], "omega_ref_l": ref[0], "omega_ref_r": ref[1],
                     "z_l": z[0], "z_r": z[1], "lean": lean, "lean_ref": lean_ref,
                     "tau_support": support, "tau_brake": brake.max(),
                     "tau_cmd_l": self.tau[0], "tau_cmd_r": self.tau[1]}
        if self.shadow:
            return 0.0, 0.0
        return float(self.tau[0]), float(self.tau[1])


def run_trial(df: pd.DataFrame, profile: Profile, cfg: Config = Config(),
              shadow: bool = True) -> pd.DataFrame:
    """기록된 시행에 컨트롤러를 그대로 다시 돌려 샘플별 판단 기록을 만든다."""
    ctrl = SitAssistController(profile, cfg, shadow=shadow)
    trunk, seat = _column(df, "trunk_deg"), _column(df, "seat")
    rows = []
    for t, tl, tr, tk, s in zip(df["time_s"], df["thigh_l_deg"], df["thigh_r_deg"], trunk, seat):
        ctrl.update(t, tl, tr, None if np.isnan(tk) else tk, None if np.isnan(s) else s)
        rows.append({"time_s": t, **ctrl.info})
    return pd.DataFrame(rows)
