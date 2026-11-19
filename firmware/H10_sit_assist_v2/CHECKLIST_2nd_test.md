# 2차 실측 체크리스트 (2차 보조 알고리즘)

내일 H10에 넣고 바로 켜서 실험할 때 이 순서대로 진행합니다. 명령은 모두 저장소 맨 위 폴더(`h10-sit-assist/`)에서 실행합니다.

## 0. 1차 대비 바뀐 점

| 1차 실측에서 나온 문제 | 2차에서 바꾼 것 | 실측 로그 재생 결과 |
|---|---|---|
| 후반 급하강 제어 부족 (닿기 직전 다시 빨라짐) | ① 펌웨어(C)에 '멈칫 뒤 다시 내려감'을 넣었습니다. 내려가다 멈칫하면 C는 착석으로 판단하고, 마지막에 떨어지는 구간에서 제동을 끊었습니다. Python에는 있었는데 C에 빠져 있었습니다. ② 상체 덜 숙임 판정이 나오면 속도 점수와 상관없이 바로 1.5 Nm로 제동합니다 (`upright_brake`). | 털썩 주저앉기 11회: 닿기 전 제동 **0/11 → 11/11**. 제동 시작은 착석 1.0초 전(중앙값) |
| 앉기 전 선행 작동 | 제동은 평소 착석 각도의 절반을 지난 뒤에만 켭니다(변경 없음). 서 있음 → 내려감 전환은 양쪽 허벅지가 0.1초 동안 함께 굽혀질 때만 일어납니다. | 끊기지 않은 로그 4개에서 서 있음 단계의 토크는 0입니다 |
| 서 있을 때 오작동 | 위와 같습니다. | 같음. 단, 재생으로만 확인했으니 1단계 그림자 모드에서 꼭 다시 봅니다 |

평소 착석에서도 제동이 늘었습니다. 45 cm 평소 착석 30회 중 1번에서 4번으로 늘었고 최대 1.5 Nm입니다. 30 cm 의자에서는 30번 중 18번입니다. 낮은 의자에서는 원래 제동을 더 주려는 설계라 그대로 둡니다.

로그 `free_var1`의 값은 `단계*10 + 제동 단계 + 5(상체 덜 숙임)`입니다.

| 단계 값 | 뜻 |
|---|---|
| 0x | 서 있음 |
| 1x | 내려감 |
| 2x | 낮은 의자(DEEP) |
| 3x | 착석 |

끝자리는 0 = 제동 없음, 1 = 약한 제동, 2 = 강한 제동입니다. 상체 덜 숙임으로 판정되면 끝자리에 5가 더해집니다(예: 15, 26).

## 1. 전날 확인 (완료)

```bash
python -m pytest -q firmware/test_firmware.py test_sit_assist.py
```

- 18개 테스트를 모두 통과합니다.
- 실측 착석 60회와 끊기지 않은 로그 4개(11/7)에서 C와 Python의 토크 차이는 1e-6 Nm 이하입니다.
- `cc -std=c99 -Wall -Wextra -pedantic`로 컴파일할 때 경고가 없습니다.

## 2. SDK에 넣기

`firmware/`의 `sit_assist.h`, `sit_assist.c`, `sit_assist_params.h` 세 파일을 H10 SDK 프로젝트에 복사합니다.

```c
#include "sit_assist.h"
static SA_State sa;

void controller_init(void) { sa_init(&sa); }

void controller_1khz(void)                   /* H10 제어 루프 (1 kHz) */
{
    float tau[2];                             /* 왼쪽 · 오른쪽 신전 토크 (Nm, 0 이상) */
    sa_step_1khz(&sa, thighDeg_LH, thighDeg_RH, incPosDeg_LH, incPosDeg_RH,
                 accX_Calib_LH, accY_Calib_LH, accX_Calib_RH, accY_Calib_RH, tau);
    u_LH = SA_EXT_SIGN_L * SA_TORQUE_TO_U * tau[0];
    u_RH = SA_EXT_SIGN_R * SA_TORQUE_TO_U * tau[1];
    free_var1 = sa_log_state(&sa);           /* 단계*10 + 제동 단계 + 5(상체 덜 숙임) */
    free_var2 = sa_log_torque(&sa);          /* 계산한 토크 (Nm, 큰 쪽) */
}
```

컴파일 옵션(`-D`)으로 바꾸는 값입니다.

| 옵션 | 기본 | 설명 |
|---|---|---|
| `SA_SHADOW` | 0 | 1이면 계산과 로그만 하고 토크는 0입니다. **OFF 조건과 기준값 수집**에 씁니다 |
| `SA_TAU_LIMIT` | 2.0 | 안전 상한(Nm)입니다. 0.5에서 시작합니다 |
| `SA_TORQUE_TO_U` | 1.0 | Nm를 `u_RH/u_LH`로 바꾸는 계수입니다. **SDK 단위를 확인해 넣습니다** |
| `SA_EXT_SIGN_L/R` | −1 | 신전 방향 부호입니다. 4단계에서 확인합니다 |

## 3. 디버그: 그림자 모드로 판정만 확인 (`-DSA_SHADOW=1`)

토크는 0인 상태로 서기 → 앉기 → 일어서기를 5번 하면서 `free_var1`을 봅니다.

- [ ] 가만히 서 있을 때와 고개만 돌릴 때 0을 유지하는가 (1차 문제 3)
- [ ] 앉기 시작 전에는 10이 되지 않는가 (1차 문제 2)
- [ ] 앉을 때 0 → 10 → 30으로 바뀌는가
- [ ] 일어서면 0으로 돌아오는가
- [ ] `free_var2`(계산 토크)가 평소 착석에서 대부분 0인가

값이 이상하면 로그를 받아 Python으로 같은 판정을 재생해 봅니다.

```bash
python -c "import pandas as pd; from preprocess_h10 import to_100hz; from sit_assist import *; \
d=to_100hz(pd.read_csv('로그.csv')); r=run_trial(d, Profile.load('results/real/profile_45ref.json')); \
print(r[['time_s','phase','posture','tau_brake']].to_string())"
```

## 4. 피험자 기준값 만들기 (기준을 만든 사람과 다른 사람이면 필수)

지금 `sit_assist_params.h`의 기준은 11/4 데이터(45 cm 착석 30회, `profile_45ref.json`)로 만든 것입니다. 다른 사람이 입으면 아래 순서로 다시 만듭니다.

1. 그림자 모드로 45 cm 의자에 평소처럼 30번 앉아 로그를 받습니다.
2. 앉기를 잘라냅니다.
   ```bash
   python preprocess_h10.py SUIT_LOGGED_DATA-XX.csv --out data/real/S02
   ```
3. 기준값을 만들고, 평소 착석에서 제동이 잘못 켜지는 비율을 확인합니다. 20%를 넘으면 경고가 나옵니다.
   ```bash
   python calibrate.py data/real/S02
   ```
4. 헤더를 다시 만들고, 펌웨어를 다시 빌드해 올립니다.
   ```bash
   python firmware/export_params.py --profile data/real/S02/profile.json
   ```

## 5. 토크 방향과 크기 (`-DSA_SHADOW=0`)

- [ ] `SA_TAU_LIMIT=0.5`로 앉으면서 다리를 뒤로 미는(신전) 방향인지 확인합니다. 반대면 `SA_EXT_SIGN_L/R`의 부호를 바꿉니다.
- [ ] `SA_TORQUE_TO_U`를 넣은 뒤 `free_var2`(Nm)와 실제 모터 전류가 같은 방향 · 비례인지 봅니다.
- [ ] 상한을 0.5 → 1.0 → 2.0 Nm 순서로 올립니다. 단계마다 평소 착석 3번을 해서 불편하지 않은지 확인합니다.
- [ ] 보조자가 옆에 서 있고, 긴급 정지 버튼이 손에 닿는지 확인합니다.

## 6. 본 실험

| 조건 | 내용 |
|---|---|
| 의자 | 45 cm, 30 cm |
| 보조 | OFF(`SA_SHADOW=1`) → ON(`SA_SHADOW=0`) |
| 앉는 방식 | 그냥 앉기, 털썩 주저앉기 |
| 횟수 | 조건당 10회 |
| 카메라 | 옆에서 고정 촬영(머리부터 발끝까지). 조건 하나 = 영상 하나 = H10 로그 하나 |

**로그 이름 규칙:** `날짜_의자_보조_방식` (예: `1109_30_ON_plop.csv`)으로 바로 바꿔 둡니다.

## 7. 분석

OFF와 ON을 비교합니다. 최대 속도, 착석 순간 속도, jerk, 상체 덜 숙임 판정, 토크가 나옵니다.

```bash
python compare_h10_runs.py --off 1109_30_OFF_*.csv --on 1109_30_ON_*.csv --out results/h10_onoff_1109_30
```

카메라 CoM · 하강 속도도 계산합니다.

```bash
python video_com.py extract 영상.mp4
python video_com.py analyze results/video/영상_pose.csv 1109_30_ON_plop.csv --chair "30 cm"
```

**확인할 것**
1. 털썩 주저앉기에서 제동이 의자에 닿기 전에 걸렸는가 (`free_var1` 끝자리가 1·2·5 이상이 된 시각 vs 착석 시각)
2. 닿는 순간 하강 속도와 충격이 OFF보다 줄었는가
3. 평소 착석과 서 있을 때 오작동이 없었는가

사람 데이터(로그, 영상)는 `data/` 아래에 두며, 저장소에는 올라가지 않습니다(gitignore).
