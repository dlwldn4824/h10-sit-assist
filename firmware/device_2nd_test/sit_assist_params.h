/* export_params.py가 만든 파일 — 직접 고치지 말 것 */
/* 기준: profile_45ref.json, 착석 30회 */
#ifndef SIT_ASSIST_PARAMS_H
#define SIT_ASSIST_PARAMS_H

#define SA_FS 100.0
#define SA_ONSET_VEL 5.0
#define SA_ONSET_HOLD 10
#define SA_SEAT_VEL 8.0
#define SA_SEAT_HOLD 15
#define SA_MIN_SEAT_DEPTH 20.0
#define SA_STAND_DEPTH 10.0
#define SA_IMPACT_THR 3.0
#define SA_RESUME_VEL 15.0
#define SA_ACC_HP_B0 0.969531252908746
#define SA_ACC_HP_B1 -0.969531252908746
#define SA_ACC_HP_A1 -0.939062505817492
#define SA_Z_WEAK 3.5
#define SA_Z_STRONG 5.0
#define SA_GAIN 2.5
#define SA_BRAKE_FROM_RATIO 0.5
#define SA_DEEP_GAIN 1.5
#define SA_DEEP_TARGET_RATIO 1.0
#define SA_LOOKAHEAD 0.05
#define SA_SUPPORT_GAIN 0.0
#define SA_UPRIGHT_MARGIN_SD 2.0
#define SA_UPRIGHT_MIN_MARGIN 6.0
#define SA_UPRIGHT_GAIN 1.5
#define SA_UPRIGHT_BRAKE 1.5
#define SA_TAU_MAX 10.0
#define SA_RISE_RATE 60.0
#define SA_RELEASE_S 0.3

#define SA_CONTACT_MEAN 65.637000   /* 평소 착석 각도 (deg) */
#define SA_DEEP_THRESHOLD 69.423000 /* 이 각도를 넘으면 낮은 의자(DEEP) */
#define SA_ALPHA_MAX 1247.459000
#define SA_NBINS 14
#define SA_HAS_LEAN 1
static const sa_real SA_CENTERS[] = {2.5, 7.5, 12.5, 17.5, 22.5, 27.5, 32.5, 37.5, 42.5, 47.5, 52.5, 57.5, 62.5, 67.5};
static const sa_real SA_MU_L[] = {41.553, 84.304, 100.331, 101.477, 109.902, 113.375, 100.979, 85.734, 71.112, 64.855, 66.118, 68.731, 80.137, 90.392};
static const sa_real SA_SD_L[] = {25, 25, 25, 25.534, 25, 25, 25, 25, 25, 25, 25, 25, 25, 25};
static const sa_real SA_MU_R[] = {35.051, 80.743, 109.43, 121.044, 119.506, 110.311, 92.807, 73.637, 65.026, 62.783, 57.383, 64.371, 81.026, 93.385};
static const sa_real SA_SD_R[] = {25, 25, 25, 25, 25, 27.36, 25, 25, 25, 25, 25, 25, 25, 25};
static const sa_real SA_LEAN_MU[] = {1.816, 3.589, 5.337, 6.978, 8.518, 9.974, 11.402, 12.771, 13.747, 14.018, 13.396, 11.303, 7.852, 3.9};
static const sa_real SA_LEAN_SD[] = {3, 3, 3.109, 3, 3, 3, 3, 3, 3, 3.035, 3.13, 3.081, 3, 3};
static const sa_real SA_LPF_ANGLE[] = {0.027859766117136, 0.0557195322342721, 0.027859766117136, -1.47548044359265, 0.58691950806119};
static const sa_real SA_LPF_ACCEL[] = {0.00782020803349719, 0.0156404160669944, 0.00782020803349719, -1.73472576880927, 0.766006600943264};
static const sa_real SA_LPF_TRUNK[] = {0.0133592000278565, 0.026718400055713, 0.0133592000278565, -1.64745998107698, 0.700896781188403};

#endif
