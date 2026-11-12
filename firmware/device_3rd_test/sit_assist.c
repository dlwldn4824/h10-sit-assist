/* H10 착석 보조 — 3차 실측용.
 *
 * 2차 실측(11/9)의 '구간 제동'을 그대로 뼈대로 둔다:
 *   허벅지 25°~70°, 두 허벅지가 함께 10°/s 넘게 굽혀질 때 구간이 열리고,
 *   한 번 내려갈 때 한 번, 70° · 착석 · 60 ms 멈춤이면 끝, 구간 밖 토크 0.
 * 바뀐 것은 구간 '안'의 세기다. 2차는 언제나 9 Nm였고, 3차는 연구 결과로 위험도를 매겨
 *   토크 = 기본 제동 + (최대 − 기본) × 위험도(0~1)
 * 로 정한다. 위험도는 아래 셋 중 가장 큰 값이다.
 *   ① 속도: 허벅지 굽힘 속도가 평소 30회보다 빠른 정도 (z 점수)       — 카메라 CoM과 ρ −0.60
 *   ② 추정 CoM: H10 각도로 계산한 CoM이 평소보다 뒤로 빠진 정도        — 카메라 CoM과 r 0.74.
 *      상체를 덜 숙이면 커지며, 털썩 주저앉기를 착석 약 1초 전에 알려 줌
 *   ③ 낮은 의자: 평소 최대 깊이(69.4°)를 넘으면 위험도 1, 구간을 착석까지 연장
 */
#include <math.h>
#include <string.h>

#include "sit_assist.h"
#include "sit_assist_params.h"

/* 구간 제동 (2차와 동일) */
#define SA_BRAKE_START_DEPTH 25.0
#define SA_BRAKE_STOP_DEPTH 70.0
#define SA_BRAKE_MIN_VEL 10.0
#define SA_BRAKE_HOLD_VEL 3.0
#define SA_BRAKE_PAUSE_HOLD 6  /* 60 ms at 100 Hz */

/* 3차: 위험도에 따른 세기 (-D로 바꿀 수 있음) */
#ifndef SA_BASE_BRAKE
#define SA_BASE_BRAKE 3.0      /* 평소 착석: 구간이 열리면 이만큼만 (Nm) */
#endif
#ifndef SA_RISK_BRAKE
#define SA_RISK_BRAKE 9.0      /* 위험도 1일 때 (Nm). 2차 실측 세기 */
#endif
#ifndef SA_RISK_Z_LO
#define SA_RISK_Z_LO 1.0       /* 속도 z가 이 값부터 위험도가 오르기 시작 */
#endif
#ifndef SA_RISK_Z_HI
#define SA_RISK_Z_HI 3.5       /* 이 값에서 위험도 1 */
#endif
#ifndef SA_RISK_COM_LO
#define SA_RISK_COM_LO 0.010   /* 추정 CoM이 평소보다 다리 길이의 1%만큼 뒤 → 위험도 0부터 */
#endif
#ifndef SA_RISK_COM_HI
#define SA_RISK_COM_HI 0.030   /* 3% 뒤 → 위험도 1 */
#endif
#ifndef SA_DEEP_STOP_DEPTH
#define SA_DEEP_STOP_DEPTH 95.0 /* 낮은 의자로 판정되면 구간을 여기(또는 착석)까지 연장 */
#endif
#ifndef SA_IMPACT_CONFIRM_VEL
#define SA_IMPACT_CONFIRM_VEL 20.0 /* 충격 뒤 허벅지가 이 속도(°/s) 아래로 멈춰야 착석으로 본다 */
#endif
#ifndef SA_IMPACT_STILL_N
#define SA_IMPACT_STILL_N 8        /* 그 속도 아래가 연속 0.08 s 이어져야 멈춘 것으로 본다 (제동 순간의 짧은 출렁임 제외) */
#endif
#ifndef SA_IMPACT_CONFIRM_N
#define SA_IMPACT_CONFIRM_N 30     /* 충격 뒤 확인을 기다리는 샘플 수 (0.3 s) */
#endif
#define SA_COM_SHANK_DEG 17.0  /* H10에 정강이 센서가 없어 평소 정강이 기울기를 가정 */

/* H10 각도만으로 계산한 CoM–발목 앞뒤 거리 (다리 길이 배, 앞이 +). sit_assist.py h10_com_dx와 같음.
   Winter(2009) 분절 무게 비율, 옆에서 본 막대 인형 모델. */
static sa_real sa_com_dx(sa_real thigh_deg, sa_real trunk_deg)
{
    const sa_real D2R = 3.14159265358979 / 180;
    const sa_real m_foot = 2 * 0.0145, m_shank = 2 * 0.0465, m_thigh = 2 * 0.100,
                  m_trunk = 0.497 + 2 * 0.050, m_head = 0.081;
    sa_real knee = 0.5 * sin(SA_COM_SHANK_DEG * D2R);
    sa_real hip = knee - 0.5 * sin(thigh_deg * D2R);
    sa_real p = trunk_deg * D2R;
    sa_real x = m_foot * 0.1 + m_shank * 0.567 * knee + m_thigh * (hip + 0.433 * (knee - hip))
              + m_trunk * (hip + 0.5 * 0.55 * sin(p)) + m_head * (hip + 0.75 * sin(p));
    return x / (m_foot + m_shank + m_thigh + m_trunk + m_head);
}

static sa_real sa_max(sa_real a, sa_real b) { return a > b ? a : b; }
static sa_real sa_min(sa_real a, sa_real b) { return a < b ? a : b; }
static sa_real sa_clip(sa_real x, sa_real lo, sa_real hi) { return sa_min(sa_max(x, lo), hi); }

/* np.interp와 같음: 범위 밖이면 양 끝 값 */
static sa_real sa_interp(sa_real x, const sa_real *xs, const sa_real *ys, int n)
{
    if (x <= xs[0]) return ys[0];
    if (x >= xs[n - 1]) return ys[n - 1];
    for (int i = 1; i < n; i++) {
        if (x <= xs[i]) {
            sa_real t = (x - xs[i - 1]) / (xs[i] - xs[i - 1]);
            return ys[i - 1] + t * (ys[i] - ys[i - 1]);
        }
    }
    return ys[n - 1];
}

static void biquad_init(SA_Biquad *f, const sa_real c[5])
{
    f->b0 = c[0]; f->b1 = c[1]; f->b2 = c[2]; f->a1 = c[3]; f->a2 = c[4];
    f->init = 0;
}

static sa_real biquad(SA_Biquad *f, sa_real x)
{
    if (!f->init) {              /* 첫 값에서 멈춰 있던 것처럼 시작 */
        f->z1 = x * (1 - f->b0);
        f->z2 = x * (f->b2 - f->a2);
        f->init = 1;
    }
    sa_real y = f->b0 * x + f->z1;
    f->z1 = f->b1 * x - f->a1 * y + f->z2;
    f->z2 = f->b2 * x - f->a2 * y;
    return y;
}

static sa_real highpass(SA_Highpass *f, sa_real x)
{
    if (!f->init) {              /* 첫 값에서 출력 0으로 시작 */
        f->x1 = x;
        f->y1 = 0;
        f->init = 1;
    }
    sa_real y = SA_ACC_HP_B0 * x + SA_ACC_HP_B1 * f->x1 - SA_ACC_HP_A1 * f->y1;
    f->x1 = x;
    f->y1 = y;
    return y;
}

static void kin_step(SA_Kin *k, sa_real x, sa_real *th, sa_real *w, sa_real *a)
{
    *th = biquad(&k->f_angle, x);
    *w = k->has_prev ? (*th - k->prev_th) * SA_FS : 0;
    *a = biquad(&k->f_accel, (*w - k->prev_w) * SA_FS);
    k->prev_th = *th;
    k->prev_w = *w;
    k->has_prev = 1;
}

void sa_init(SA_State *s)
{
    memset(s, 0, sizeof(*s));
    for (int i = 0; i < 2; i++) {
        biquad_init(&s->kin[i].f_angle, SA_LPF_ANGLE);
        biquad_init(&s->kin[i].f_accel, SA_LPF_ACCEL);
    }
    biquad_init(&s->f_trunk, SA_LPF_TRUNK);
    s->phase = SA_STANDING;
}

/* Segmenter.update: 서 있을 때 대비 굴곡 각도 d[2]와 상체 숙임 lean을 돌려준다 */
static void segment(SA_State *s, const sa_real th[2], const sa_real w[2], sa_real seat, sa_real trunk,
                    sa_real impact, sa_real d[2], sa_real *lean)
{
    if (!s->stand_init) {
        s->stand[0] = th[0]; s->stand[1] = th[1]; s->stand_trunk = trunk;
        s->stand_init = 1;
    }
    d[0] = th[0] - s->stand[0];
    d[1] = th[1] - s->stand[1];
    *lean = trunk - s->stand_trunk;
    sa_real wm = (w[0] + w[1]) / 2, dm = (d[0] + d[1]) / 2;

    if (s->phase == SA_STANDING) {
        if (fabs(wm) < SA_ONSET_VEL) {           /* 가만히 서 있을 때만 기준 자세 갱신 */
            s->stand[0] += 0.02 * (th[0] - s->stand[0]);
            s->stand[1] += 0.02 * (th[1] - s->stand[1]);
            s->stand_trunk += 0.02 * (trunk - s->stand_trunk);
        }
        if (w[0] > SA_ONSET_VEL && w[1] > SA_ONSET_VEL) {
            if (++s->n_onset >= SA_ONSET_HOLD) {
                s->phase = SA_DESCENT;
                s->n_onset = s->n_seat = s->n_rise = s->n_impact = s->n_still = 0;
            }
        } else {
            s->n_onset = 0;
        }
    } else if (s->phase == SA_DESCENT || s->phase == SA_DEEP) {
        if (!isnan(seat)) {                      /* 의자 압력센서가 있으면 그것을 믿는다 */
            if (seat > 0.5) s->phase = SA_SEATED;
        } else if (!isnan(impact) && impact > SA_IMPACT_THR && dm > SA_MIN_SEAT_DEPTH && s->n_impact == 0) {
            /* IMU 충격만으로는 착석으로 보지 않는다. 3차 실측(11/12)에서 제동이 걸릴 때 몸이 갑자기
               느려지는 흔들림이 충격으로 잡혀, 내려가는 도중(37~69°)에 제동이 풀렸다.
               충격 뒤 0.3 s 안에 허벅지가 실제로 멈춰야 착석으로 본다. */
            s->n_impact = SA_IMPACT_CONFIRM_N;
        }
        if (s->phase != SA_SEATED && s->n_impact > 0) {
            s->n_still = fabs(wm) < SA_IMPACT_CONFIRM_VEL ? s->n_still + 1 : 0;
            if (s->n_still >= SA_IMPACT_STILL_N) {
                s->phase = SA_SEATED;            /* 충격 + 멈춤 = 엉덩이가 의자에 닿음 */
                s->n_impact = s->n_still = 0;
            } else if (--s->n_impact == 0) {
                s->n_still = 0;                  /* 멈추지 않고 계속 내려감 → 충격 무시, 제동 유지 */
            }
        }
        if (s->phase == SA_SEATED || !isnan(seat)) {
            /* 위에서 착석 판정됨 */
        } else if (fabs(wm) < SA_SEAT_VEL && dm > SA_MIN_SEAT_DEPTH) {
            if (++s->n_seat >= SA_SEAT_HOLD) {
                s->phase = SA_SEATED;
                s->seat_by_vel = 1;              /* 압력센서 · 충격 없이 멈춤만 보고 착석으로 봄 */
                s->n_resume = 0;
            }
        } else {
            s->n_seat = 0;
        }
        s->n_rise = wm < -SA_ONSET_VEL ? s->n_rise + 1 : 0;
        if (s->n_rise >= SA_ONSET_HOLD)
            s->phase = dm > SA_MIN_SEAT_DEPTH ? SA_SEATED : SA_STANDING;
    } else if (s->phase == SA_SEATED) {
        if (dm < SA_STAND_DEPTH) {
            s->phase = SA_STANDING;
            s->seat_by_vel = 0;
        } else if (s->seat_by_vel && SA_RESUME_VEL > 0) {
            int hit = (!isnan(seat) && seat > 0.5) || (!isnan(impact) && impact > SA_IMPACT_THR);
            if (hit) {
                s->seat_by_vel = 0;              /* 진짜로 닿았다 → 더는 되돌리지 않음 */
            } else if (w[0] > SA_RESUME_VEL && w[1] > SA_RESUME_VEL) {
                if (++s->n_resume >= SA_ONSET_HOLD) {   /* 멈칫 뒤 다시 내려감 → 하강으로 되돌림 */
                    s->phase = SA_DESCENT;
                    s->seat_by_vel = 0;
                    s->n_seat = s->n_rise = 0;
                }
            } else {
                s->n_resume = 0;
            }
        }
    }
}

void sa_update_100hz(SA_State *s, sa_real thigh_l, sa_real thigh_r, sa_real trunk_in, sa_real seat, sa_real acc,
                     int shadow, sa_real out[2])
{
    sa_real th[2], w[2], a[2], d[2], lean;
    kin_step(&s->kin[0], thigh_l, &th[0], &w[0], &a[0]);
    kin_step(&s->kin[1], thigh_r, &th[1], &w[1], &a[1]);
    int has_trunk = !isnan(trunk_in) && SA_HAS_LEAN;
    sa_real trunk = has_trunk ? biquad(&s->f_trunk, trunk_in) : NAN;
    s->impact = isnan(acc) ? NAN : highpass(&s->f_acc, acc);
    segment(s, th, w, seat, trunk, s->impact, d, &lean);

    sa_real dm = (d[0] + d[1]) / 2, wm = (w[0] + w[1]) / 2;
    if (s->phase == SA_DESCENT && dm > SA_DEEP_THRESHOLD) s->phase = SA_DEEP;
    /* Do not reopen the brake after the descent reaches the seated region.
       In other.csv the previous controller pulsed nine times after the angle
       peak while the wearer was already near the chair. */
    if (s->phase == SA_STANDING && dm < SA_STAND_DEPTH) {
        s->brake_done = s->brake_active = s->n_brake_pause = 0;
    }
    /* ③ 낮은 의자: 평소 최대 깊이를 넘으면 구간을 착석(또는 SA_DEEP_STOP_DEPTH)까지 연장 */
    sa_real stop_depth = s->phase == SA_DEEP ? SA_DEEP_STOP_DEPTH : SA_BRAKE_STOP_DEPTH;
    if (s->phase == SA_SEATED || dm >= stop_depth) {
        s->brake_done = 1;
        s->brake_active = s->n_brake_pause = 0;
    }
    int in_depth = dm >= SA_BRAKE_START_DEPTH && dm < stop_depth;
    int descending = (s->phase == SA_DESCENT || s->phase == SA_DEEP);
    if (!s->brake_done && descending && in_depth) {
        if (!s->brake_active && w[0] > SA_BRAKE_MIN_VEL && w[1] > SA_BRAKE_MIN_VEL)
            s->brake_active = 1;
        if (s->brake_active) {
            /* Bridge brief velocity dips without holding torque at a stop. */
            s->n_brake_pause = wm < SA_BRAKE_HOLD_VEL ? s->n_brake_pause + 1 : 0;
            if (s->n_brake_pause >= SA_BRAKE_PAUSE_HOLD) {
                s->brake_done = 1;
                s->brake_active = 0;
            }
        }
    } else if (s->brake_active) {
        s->brake_done = 1;
        s->brake_active = 0;
    }
    int brake_window = s->brake_active && !s->brake_done;
    int late = dm > SA_BRAKE_FROM_RATIO * SA_CONTACT_MEAN;

    /* ② 추정 CoM: 같은 허벅지 각도에서, 평소 상체 숙임일 때의 CoM보다 얼마나 뒤로 빠졌는가 */
    sa_real com_behind = 0;
    s->upright = 0;
    if (has_trunk && brake_window && late) {
        sa_real lr = sa_interp(dm, SA_CENTERS, SA_LEAN_MU, SA_NBINS);
        sa_real ls = sa_interp(dm, SA_CENTERS, SA_LEAN_SD, SA_NBINS);
        com_behind = sa_com_dx(dm, lr) - sa_com_dx(dm, lean);
        if (lean < lr - sa_max(SA_UPRIGHT_MARGIN_SD * ls, SA_UPRIGHT_MIN_MARGIN)) s->upright = 1;
    }
    sa_real risk_com = sa_clip((com_behind - SA_RISK_COM_LO) / (SA_RISK_COM_HI - SA_RISK_COM_LO), 0, 1);
    sa_real risk_deep = s->phase == SA_DEEP ? 1 : 0;
    /* 1) 상체 지지 (기본 0) */
    sa_real support = (has_trunk && brake_window) ? SA_SUPPORT_GAIN * sin(sa_max(lean, 0) * 3.14159265358979 / 180) : 0;
    /* 2) 구간 제동: 기본 + 위험도만큼 */
    sa_real brake[2] = {0, 0}, zmax = 0, risk_max = 0;
    if (brake_window) {
        for (int i = 0; i < 2; i++) {
            const sa_real *mu = i == 0 ? SA_MU_L : SA_MU_R, *sd_t = i == 0 ? SA_SD_L : SA_SD_R;
            sa_real ref, sd;
            if (s->phase == SA_DEEP) {
                ref = SA_DEEP_TARGET_RATIO * sa_interp(SA_CONTACT_MEAN, SA_CENTERS, mu, SA_NBINS);
                sd = sa_interp(SA_CONTACT_MEAN, SA_CENTERS, sd_t, SA_NBINS);
            } else {
                sa_real dq = dm + wm * SA_LOOKAHEAD;
                ref = sa_interp(dq, SA_CENTERS, mu, SA_NBINS);
                sd = sa_interp(dq, SA_CENTERS, sd_t, SA_NBINS);
            }
            /* ① 속도: 평소보다 얼마나 빠른가 */
            sa_real z = (w[i] + a[i] * SA_LOOKAHEAD - ref) / sd;
            if (a[i] > SA_ALPHA_MAX && w[i] > ref) z = sa_max(z, SA_Z_STRONG);   /* 털썩 내려앉는 급가속 */
            sa_real risk_v = sa_clip((z - SA_RISK_Z_LO) / (SA_RISK_Z_HI - SA_RISK_Z_LO), 0, 1);
            sa_real risk = sa_max(risk_v, sa_max(risk_com, risk_deep));
            brake[i] = SA_BASE_BRAKE + (SA_RISK_BRAKE - SA_BASE_BRAKE) * risk;
            zmax = i == 0 ? z : sa_max(zmax, z);
            risk_max = sa_max(risk_max, risk);
        }
    }
    s->risk = risk_max;
    sa_real up = SA_RISE_RATE / SA_FS, down = SA_TAU_MAX / (SA_RELEASE_S * SA_FS);
    for (int i = 0; i < 2; i++) {
        if (!brake_window) {
            /* The 1 kHz wrapper already slews motor current to zero. Do not
               carry an internal torque tail into the chair-contact region. */
            s->tau[i] = s->out[i] = out[i] = 0;
            continue;
        }
        sa_real target = sa_clip(support + brake[i], 0, SA_TAU_MAX);
        s->tau[i] = sa_clip(target, s->tau[i] - down, s->tau[i] + up);
        s->out[i] = shadow ? 0 : sa_min(s->tau[i], SA_TAU_LIMIT);
        out[i] = s->out[i];
    }
    s->support = support;
    s->brake_max = sa_max(brake[0], brake[1]);
    s->level = risk_max >= 0.67 ? 2 : (risk_max >= 0.33 ? 1 : 0);   /* 로그: 위험도 낮음 0 · 중간 1 · 높음 2 */
    (void)zmax;
}

void sa_step_1khz(SA_State *s, float thighDeg_LH, float thighDeg_RH, float incPosDeg_LH, float incPosDeg_RH,
                  float accX_LH, float accY_LH, float accX_RH, float accY_RH, float tau_out[2])
{
    s->acc_imu += (sqrt(accX_LH * accX_LH + accY_LH * accY_LH) + sqrt(accX_RH * accX_RH + accY_RH * accY_RH)) / 2;
    s->acc_th[0] += thighDeg_LH;
    s->acc_th[1] += thighDeg_RH;
    s->acc_inc[0] += incPosDeg_LH;
    s->acc_inc[1] += incPosDeg_RH;
    if (++s->sub >= 10) {
        sa_real tl = s->acc_th[0] / 10, tr = s->acc_th[1] / 10;
        sa_real trunk = ((s->acc_inc[0] / 10 - tl) + (s->acc_inc[1] / 10 - tr)) / 2;
        sa_real out[2];
        sa_update_100hz(s, tl, tr, trunk, NAN, s->acc_imu / 10, SA_SHADOW, out);
        s->sub = 0;
        s->acc_th[0] = s->acc_th[1] = s->acc_inc[0] = s->acc_inc[1] = s->acc_imu = 0;
    }
    tau_out[0] = (float)s->out[0];
    tau_out[1] = (float)s->out[1];
}

float sa_log_state(const SA_State *s) { return (float)(s->phase * 10 + s->level + 5 * s->upright); }
float sa_log_torque(const SA_State *s) { return (float)sa_max(s->tau[0], s->tau[1]); }
float sa_log_risk(const SA_State *s) { return (float)s->risk; }
int sa_state_size(void) { return (int)sizeof(SA_State); }
