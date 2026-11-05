/*
 * H10 적응형 착석 보조 (Low-Chair Adaptive Braking) — 펌웨어용 C 구현
 *
 * Python 구현(sit_assist.py)과 같은 계산을 한다. test_firmware.py가 두 결과가 같은지 확인한다.
 * 기준값(개인 하강 속도 표, 평소 착석 각도 등)은 sit_assist_params.h에 있다.
 * 기준값을 바꾸려면 export_params.py로 그 파일을 다시 만든다.
 *
 * 사용법 (H10 제어 루프 1 kHz):
 *
 *     static SA_State sa;
 *     sa_init(&sa);
 *     ...
 *     // 매 제어 주기
 *     float tau[2];                          // [0]=왼쪽, [1]=오른쪽 신전 토크 (Nm, 0 이상)
 *     sa_step_1khz(&sa, thighDeg_LH, thighDeg_RH, incPosDeg_LH, incPosDeg_RH,
 *                  accX_Calib_LH, accY_Calib_LH, accX_Calib_RH, accY_Calib_RH, tau);
 *     u_LH = SA_EXT_SIGN_L * SA_TORQUE_TO_U * tau[0];   // ← 부호와 단위 변환은 H10 SDK에 맞춰 확인
 *     u_RH = SA_EXT_SIGN_R * SA_TORQUE_TO_U * tau[1];
 *     free_var1 = sa_log_state(&sa);         // 비교용 로그: 단계*10 + 제동 단계
 *     free_var2 = sa_log_torque(&sa);        // 비교용 로그: 계산한 토크(Nm, 큰 쪽)
 */
#ifndef SIT_ASSIST_H
#define SIT_ASSIST_H

#ifdef SA_USE_DOUBLE
typedef double sa_real;
#else
typedef float sa_real;
#endif

/* ---- H10 연결 설정: 실제 장비에서 반드시 확인 ---------------------------------- */
#ifndef SA_TORQUE_TO_U
#define SA_TORQUE_TO_U 1.0f       /* Nm → u_RH/u_LH 제어 입력 환산 계수 (SDK 단위 확인 후 수정) */
#endif
#ifndef SA_EXT_SIGN_L
#define SA_EXT_SIGN_L (-1.0f)     /* 왼쪽 신전 방향 부호 (첫 착용 때 확인) */
#endif
#ifndef SA_EXT_SIGN_R
#define SA_EXT_SIGN_R (-1.0f)     /* 오른쪽 신전 방향 부호 */
#endif
#ifndef SA_TAU_LIMIT
#define SA_TAU_LIMIT 2.0f         /* 안전 상한 (Nm). 첫 실험은 낮게 두고 단계적으로 올린다 */
#endif
#ifndef SA_SHADOW
#define SA_SHADOW 0               /* 1이면 계산·로그만 하고 토크는 0 (OFF 조건) */
#endif

enum { SA_STANDING = 0, SA_DESCENT = 1, SA_DEEP = 2, SA_SEATED = 3 };

typedef struct {
    sa_real b0, b1, b2, a1, a2, z1, z2;
    int init;
} SA_Biquad;

typedef struct {
    SA_Biquad f_angle, f_accel;
    sa_real prev_th, prev_w;
    int has_prev;
} SA_Kin;

typedef struct {
    sa_real x1, y1;
    int init;
} SA_Highpass;

typedef struct {
    SA_Kin kin[2];
    SA_Biquad f_trunk;
    SA_Highpass f_acc;            /* 허벅지 IMU 가속도 크기 고역통과 → 착석 충격 */
    sa_real impact;
    int phase, n_onset, n_seat, n_rise, stand_init, level, upright;
    sa_real stand[2], stand_trunk;
    sa_real tau[2];               /* 변화 속도 제한을 거친 토크 */
    sa_real out[2];               /* 실제로 내보내는 토크 (그림자 모드·안전 상한 반영) */
    sa_real support, brake_max;
    /* 1 kHz → 100 Hz: 10샘플 평균 */
    int sub;
    sa_real acc_th[2], acc_inc[2], acc_imu;
} SA_State;

void sa_init(SA_State *s);

/* 100 Hz 한 샘플. thigh: 허벅지 굴곡 각도(deg), trunk: 상체 각도(deg, 없으면 NAN), seat: 의자 센서 0/1(없으면 NAN),
 * acc: 허벅지 IMU 가속도 크기 좌우 평균(m/s², 없으면 NAN). 엉덩이가 의자에 닿는 충격으로 착석을 판정한다.
 * out[2]에 왼쪽·오른쪽 신전 토크(Nm)를 쓴다. shadow=1이면 0을 쓴다. */
void sa_update_100hz(SA_State *s, sa_real thigh_l, sa_real thigh_r, sa_real trunk, sa_real seat, sa_real acc,
                     int shadow, sa_real out[2]);

/* H10 1 kHz 루프용: 10샘플마다 평균을 내서 sa_update_100hz를 부르고, 그 사이에는 직전 토크를 유지한다.
 * trunk = 좌우 평균(incPosDeg - thighDeg). */
void sa_step_1khz(SA_State *s, float thighDeg_LH, float thighDeg_RH, float incPosDeg_LH, float incPosDeg_RH,
                  float accX_LH, float accY_LH, float accX_RH, float accY_RH, float tau_out[2]);

float sa_log_state(const SA_State *s);
float sa_log_torque(const SA_State *s);
int sa_state_size(void);

#endif
