/* H10 적응형 착석 보조 — sit_assist.py의 SitAssistController와 같은 계산 */
#include <math.h>
#include <string.h>

#include "sit_assist.h"
#include "sit_assist_params.h"

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
                s->n_onset = s->n_seat = s->n_rise = 0;
            }
        } else {
            s->n_onset = 0;
        }
    } else if (s->phase == SA_DESCENT || s->phase == SA_DEEP) {
        if (!isnan(seat)) {                      /* 의자 압력센서가 있으면 그것을 믿는다 */
            if (seat > 0.5) s->phase = SA_SEATED;
        } else if (!isnan(impact) && impact > SA_IMPACT_THR && dm > SA_MIN_SEAT_DEPTH) {
            s->phase = SA_SEATED;                /* IMU 충격 = 엉덩이가 의자에 닿음 */
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
    int moving = (s->phase == SA_DESCENT || s->phase == SA_DEEP) && wm > 0;
    int late = dm > SA_BRAKE_FROM_RATIO * SA_CONTACT_MEAN;

    /* 자세: 평소보다 상체를 덜 숙였는가 */
    s->upright = 0;
    if (has_trunk && moving && late) {
        sa_real lr = sa_interp(dm, SA_CENTERS, SA_LEAN_MU, SA_NBINS);
        sa_real ls = sa_interp(dm, SA_CENTERS, SA_LEAN_SD, SA_NBINS);
        if (lean < lr - sa_max(SA_UPRIGHT_MARGIN_SD * ls, SA_UPRIGHT_MIN_MARGIN)) s->upright = 1;
    }
    /* 1) 상체 지지 */
    sa_real support = (has_trunk && moving) ? SA_SUPPORT_GAIN * sin(sa_max(lean, 0) * 3.14159265358979 / 180) : 0;
    /* 2) 적응형 하강 제동 */
    sa_real brake[2] = {0, 0}, zmax = 0;
    if (moving && late) {
        for (int i = 0; i < 2; i++) {
            const sa_real *mu = i == 0 ? SA_MU_L : SA_MU_R, *sd_t = i == 0 ? SA_SD_L : SA_SD_R;
            sa_real ref, sd, g;
            if (s->phase == SA_DEEP) {
                ref = SA_DEEP_TARGET_RATIO * sa_interp(SA_CONTACT_MEAN, SA_CENTERS, mu, SA_NBINS);
                sd = sa_interp(SA_CONTACT_MEAN, SA_CENTERS, sd_t, SA_NBINS);
                g = SA_GAIN * SA_DEEP_GAIN;
            } else {
                sa_real dq = dm + wm * SA_LOOKAHEAD;
                ref = sa_interp(dq, SA_CENTERS, mu, SA_NBINS);
                sd = sa_interp(dq, SA_CENTERS, sd_t, SA_NBINS);
                g = SA_GAIN;
            }
            if (s->upright) g *= SA_UPRIGHT_GAIN;
            sa_real z = (w[i] + a[i] * SA_LOOKAHEAD - ref) / sd;
            if (a[i] > SA_ALPHA_MAX && w[i] > ref) z = sa_max(z, SA_Z_STRONG);   /* 털썩 내려앉는 급가속 */
            brake[i] = sa_max(g * (z - SA_Z_WEAK), 0);
            if (s->upright && SA_UPRIGHT_BRAKE > 0) brake[i] = sa_max(brake[i], SA_UPRIGHT_BRAKE);  /* 2차: 자세 판정 즉시 제동 */
            zmax = i == 0 ? z : sa_max(zmax, z);
        }
    }
    sa_real up = SA_RISE_RATE / SA_FS, down = SA_TAU_MAX / (SA_RELEASE_S * SA_FS);
    for (int i = 0; i < 2; i++) {
        sa_real target = sa_clip(support + brake[i], 0, SA_TAU_MAX);
        s->tau[i] = sa_clip(target, s->tau[i] - down, s->tau[i] + up);
        s->out[i] = shadow ? 0 : sa_min(s->tau[i], SA_TAU_LIMIT);
        out[i] = s->out[i];
    }
    s->support = support;
    s->brake_max = sa_max(brake[0], brake[1]);
    s->level = zmax >= SA_Z_STRONG ? 2 : (zmax >= SA_Z_WEAK ? 1 : 0);
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
int sa_state_size(void) { return (int)sizeof(SA_State); }
