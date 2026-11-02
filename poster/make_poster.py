"""매치업 포스터 양식(90×120cm)에 착석 보조 알고리즘 포스터를 만든다.

양식 파일의 상단 제목줄·제목 표·테두리·하단 로고만 남기고 나머지는 새로 채운다.
숫자는 results/metrics.csv에서 읽으므로 데이터가 바뀌면 다시 돌리면 된다.

    python poster/make_figures.py
    python poster/make_poster.py --template "<양식>.pptx" --out poster/착석보조_포스터.pptx
"""
from __future__ import annotations

import argparse
from pathlib import Path

import copy
import json
import sys

import pandas as pd
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Cm, Pt

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
WINE = RGBColor(0x77, 0x22, 0x35)
PINK = RGBColor(0xF6, 0xE6, 0xE9)
GRAY = RGBColor(0x55, 0x55, 0x55)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
BLACK = RGBColor(0, 0, 0)
KEEP_IDS = {2, 3, 7, 10}          # 상단 제목줄, 로고 묶음, 제목 표, 테두리

TITLE = ("낮은 의자 착석에서 털썩 주저앉음을 줄이는", "H10 적응형 하강 제동 알고리즘")
TEAM = "팀명 / KWAI"
MEMBERS = "팀원 / 이지우, 이지석, 박수민"
FAST_REP = 5                      # 실측에서 빠르게 앉은 시행 (make_figures.py --highlight와 같게)


# ---------------------------------------------------------------- 도형 도우미

def _runs(p, parts, size, bold=False, color=BLACK):
    """parts: 문자열 또는 (문자열, {size, bold, color}) 목록."""
    if isinstance(parts, str):
        parts = [parts]
    for part in parts:
        text, opt = (part, {}) if isinstance(part, str) else part
        r = p.add_run()
        r.text = text
        r.font.size = Pt(opt.get("size", size))
        r.font.bold = opt.get("bold", bold)
        r.font.color.rgb = opt.get("color", color)


def text(slide, x, y, w, h, paras, size=28, bold=False, color=BLACK, align=PP_ALIGN.LEFT,
         space_after=6, anchor=MSO_ANCHOR.TOP):
    """paras: 문단 목록. 문단은 문자열 / (문자열, 옵션) 목록 / {"t":..., "size":..., ...}."""
    tb = slide.shapes.add_textbox(Cm(x), Cm(y), Cm(w), Cm(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = Cm(0.2)
    tf.margin_top = tf.margin_bottom = Cm(0.1)
    for i, para in enumerate(paras):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        opt = para if isinstance(para, dict) else {"t": para}
        p.alignment = opt.get("align", align)
        p.space_after = Pt(opt.get("space_after", space_after))
        _runs(p, opt["t"], opt.get("size", size), opt.get("bold", bold), opt.get("color", color))
    return tb


def box(slide, x, y, w, h, paras, fill=PINK, line=WINE, size=28, bold=False, color=BLACK,
        shape=MSO_SHAPE.ROUNDED_RECTANGLE, align=PP_ALIGN.CENTER):
    s = slide.shapes.add_shape(shape, Cm(x), Cm(y), Cm(w), Cm(h))
    s.fill.solid()
    s.fill.fore_color.rgb = fill
    if line is None:
        s.line.fill.background()
    else:
        s.line.color.rgb = line
        s.line.width = Pt(2.5)
    s.shadow.inherit = False
    if shape == MSO_SHAPE.ROUNDED_RECTANGLE:
        s.adjustments[0] = 0.18
    tf = s.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    tf.margin_left = tf.margin_right = Cm(0.3)
    for i, para in enumerate(paras):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        _runs(p, para, size, bold, color)
    return s


def section(slide, x, y, w, title):
    box(slide, x, y, w, 2.9, [title], fill=WINE, line=None, size=54, bold=True, color=WHITE,
        shape=MSO_SHAPE.RECTANGLE)


def arrow(slide, x, y, w=1.2, h=1.4):
    a = slide.shapes.add_shape(MSO_SHAPE.DOWN_ARROW, Cm(x), Cm(y), Cm(w), Cm(h))
    a.fill.solid()
    a.fill.fore_color.rgb = WINE
    a.line.fill.background()
    a.shadow.inherit = False


def picture(slide, path, x, y, w):
    return slide.shapes.add_picture(str(path), Cm(x), Cm(y), width=Cm(w))


def table(slide, x, y, w, rows, col_w, row_h, size=24, highlight_last=False):
    shp = slide.shapes.add_table(len(rows), len(rows[0]), Cm(x), Cm(y), Cm(w), Cm(row_h * len(rows)))
    tb = shp.table
    for j, cw in enumerate(col_w):
        tb.columns[j].width = Cm(cw)
    for i, row in enumerate(rows):
        tb.rows[i].height = Cm(row_h)
        for j, val in enumerate(row):
            cell = tb.cell(i, j)
            head = i == 0
            hl = highlight_last and i == len(rows) - 1
            cell.fill.solid()
            cell.fill.fore_color.rgb = WINE if head else (PINK if hl else (WHITE if i % 2 else RGBColor(0xF4, 0xF4, 0xF4)))
            cell.margin_left = cell.margin_right = Cm(0.15)
            cell.margin_top = cell.margin_bottom = Cm(0.05)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            p = cell.text_frame.paragraphs[0]
            p.alignment = PP_ALIGN.LEFT if j == 0 else PP_ALIGN.CENTER
            _runs(p, str(val), size, bold=head or hl, color=WHITE if head else BLACK)
    return tb


def set_paragraph(p, value):
    """첫 run의 서식을 살려 문단 글자만 바꾼다."""
    runs = p.runs
    runs[0].text = value
    for r in runs[1:]:
        r._r.getparent().remove(r._r)


# ---------------------------------------------------------------- 결과 숫자

def result_rows(metrics_csv: Path) -> list[list[str]]:
    """실측 45 cm vs 30 cm 비교표 (compare_chairs.py의 chair_metrics.csv)."""
    m = pd.read_csv(metrics_csv)
    g = m.groupby("chair")
    items = [("착석 각도 Δθ (°)", "contact_dtheta", 1), ("최대 허벅지 굴곡 속도 (°/s)", "peak_vel", 0),
             ("착석 순간 속도 (°/s)", "contact_vel", 1), ("착석 시간 (s)", "descent_time", 2),
             ("최대 상체 숙임 (°)", "peak_lean", 1)]
    rows = [["지표", "45 cm", "30 cm", "차이"]]
    for name, k, nd in items:
        a, b = g[k].mean()["45 cm"], g[k].mean()["30 cm"]
        rows.append([name, f"{a:.{nd}f}", f"{b:.{nd}f}", f"{b - a:+.{nd}f}"])
    d = g["deep"].agg(["sum", "count"])
    rows.append(["낮은 의자(DEEP) 판정", f"{int(d.loc['45 cm', 'sum'])}/{int(d.loc['45 cm', 'count'])}",
                 f"{int(d.loc['30 cm', 'sum'])}/{int(d.loc['30 cm', 'count'])}", ""])
    return rows


def real_stats(real_dir: Path) -> dict:
    """실측 착석 기록에서 포스터에 쓸 숫자를 뽑는다."""
    from evaluate import calib_loo, load_participant, trial_metrics
    p = load_participant(real_dir)
    m = pd.DataFrame([trial_metrics(df) for df in p["calib"]])
    loo = calib_loo(p["calib"])
    log = pd.read_csv(real_dir / "extraction_log.csv")
    ch = json.loads((HERE.parent / "results" / "real" / "chair_stats.json").read_text())
    return {"chair": ch,"n_found": len(log), "n_used": len(p["calib"]), "dur": m.descent_time.mean(),
            "peak": m.peak_vel.mean(), "lean": m.peak_lean.mean(),
            "quiet": int((~loo.triggered).sum()), "flagged": int(loo.triggered.sum()),
            "fast_dur": m.descent_time.iloc[FAST_REP - 1], "fast_peak": m.peak_vel.iloc[FAST_REP - 1]}


# ---------------------------------------------------------------- 포스터

def build(template: Path, out: Path, figs: Path, metrics_csv: Path, real_dir: Path):
    st = real_stats(real_dir)
    prs = Presentation(str(template))
    s = prs.slides[0]
    tree = s.shapes._spTree
    keep = {sh._element for sh in s.shapes if sh.shape_id in KEEP_IDS}
    for el in list(tree):          # 수식 개체(mc:AlternateContent)는 shapes에 안 잡혀서 트리에서 직접 지운다
        tag = el.tag.split("}")[1]
        if tag not in ("nvGrpSpPr", "grpSpPr") and el not in keep:
            tree.remove(el)

    # 제목 표: 제목 / (빈 줄) / 교과목명 / 팀명 / 팀원
    tbl = next(sh for sh in s.shapes if sh.shape_id == 7).table
    paras = tbl.cell(0, 0).text_frame.paragraphs
    set_paragraph(paras[0], TITLE[0])
    paras[1].alignment = paras[0].alignment          # 빈 줄을 제목 둘째 줄로 사용
    paras[1]._p.append(copy.deepcopy(paras[0].runs[0]._r))
    paras[1].runs[0].text = TITLE[1]
    set_paragraph(paras[3], TEAM)
    set_paragraph(paras[4], MEMBERS)

    L, R, CW = 2.6, 46.8, 40.6

    # 1. 주제 선정 배경 --------------------------------------------------------
    section(s, L, 18.8, CW, "1. 주제 선정 배경")
    text(s, L, 22.2, CW, 1.8, ["왜 낮은 의자인가?"], size=34, bold=True)
    text(s, L, 24.0, CW, 7.6, [
        [("① 더 깊이 굽혀야 한다: ", {"bold": True}), "실측에서 30 cm 의자는 45 cm보다 허벅지가 9° 더 굽혀졌다."],
        [("② 가장 약한 자세에서 버텨야 한다: ", {"bold": True}), "깊게 굽힐수록 고관절 신전근¹이 체중을 버티기 어렵다.[3]"],
        [("③ 마지막 순간이 가장 빠르다: ", {"bold": True}),
         ("털썩 주저앉거나 뒤로 넘어지기 쉽다.", {"bold": True, "color": WINE}), "[1]"],
        [("④ 생활 곳곳에 있다: ", {"bold": True}), "소파 · 좌변기 · 좌식 의자"]], size=27, space_after=6)
    box(s, L, 31.0, CW, 2.2, [[("타깃: ", {"bold": True}), "착석 제어가 어려운 근감소증 위험 고령자 (AWGS 2019[2]: 5회 의자 일어서기 ≥ 12초)"]],
        size=22, align=PP_ALIGN.LEFT)
    text(s, L, 33.5, CW, 1.6, ["기존 방법은 측정과 개입을 동시에 하지 못한다"], size=30, bold=True)
    table(s, L, 35.3, CW, [
        ["방법", "움직임 측정", "즉각 보조", "고관절 직접", "장소 무관"],
        ["높은 의자 · 팔걸이", "X", "O", "X", "X"],
        ["지팡이 · 워커", "X", "O", "X", "O"],
        ["IMU", "O", "X", "X", "O"],
        ["카메라", "O", "X", "X", "X"],
        ["H10 (제안)", "O", "O", "O", "O"]],
        col_w=[11.6, 7.25, 7.25, 7.25, 7.25], row_h=1.8, size=24, highlight_last=True)

    # 2. 생체역학적 관점에서의 문제정의 ----------------------------------------
    section(s, R, 18.8, CW, "2. 생체역학적 관점에서의 문제정의")
    text(s, R, 22.2, CW, 1.8, ["어째서 낙상 위험이 생기는가?"], size=34, bold=True)
    picture(s, figs / "fig_posture.png", R, 24.0, CW)
    text(s, R, 38.4, CW, 4.4, [
        ["고관절 신전근¹은 편심성 수축²으로 ", ("① 숙인 상체를 버티고 ② 하강 속도를 제동", {"bold": True}),
         "한다. 근력이 약하면 둘 다 무너져 상체를 세운 채 빠르게 내려가고, ",
         ("무게중심이 발 뒤로 빠진다.", {"bold": True, "color": WINE})]])
    box(s, R, 43.0, CW, 3.3, [["H10 고관절 ", ("신전 토크", {"bold": True}), " 하나로"],
                              [("상체 지지 + 하강 제동", {"bold": True, "color": WINE}), "을 동시에 보조"]], size=30)

    # 3. 알고리즘 설계 ---------------------------------------------------------
    section(s, 2.5, 47.8, 84.9, "3. 알고리즘 설계")
    text(s, L, 51.0, 42.0, 2.0, ["FSM 상태 전이 [STANDING – DESCENT – DEEP – SEATED]"], size=34, bold=True)
    states = [("STANDING", RGBColor(0x80, 0x80, 0x80), "서 있음 · 기준 자세(허벅지·상체) 갱신"),
              ("DESCENT", WINE, "개인 기준과 비교 → 상체 지지 + 적응형 제동"),
              ("DEEP", RGBColor(0xC0, 0x39, 0x4B), "낮은 의자 · 평소 착석 속도까지 감속, 제동 ×1.5"),
              ("SEATED", RGBColor(0x4A, 0x4A, 0x4A), "토크 0.3 s에 걸쳐 해제 → 일어서면 STANDING")]
    trans = ["양쪽 허벅지 ω > 5°/s, 0.1 s 유지",
             "Δθ > 평소 착석 각도 + 2σ, 아직 착석 전",
             "의자 압력센서 ON 또는 |ω| < 8°/s, 0.15 s"]
    y = 53.6
    for i, (name, col, desc) in enumerate(states):
        box(s, 3.2, y, 11.0, 2.7, [name], fill=col, line=None, size=30, bold=True, color=WHITE)
        text(s, 14.8, y, 28.0, 2.7, [desc], size=26, anchor=MSO_ANCHOR.MIDDLE)
        if i < 3:
            arrow(s, 8.1, y + 2.85, 1.2, 1.6)
            text(s, 9.8, y + 2.8, 33.0, 1.7, [[("▶ ", {"color": WINE}), trans[i]]], size=24, color=GRAY,
                 anchor=MSO_ANCHOR.MIDDLE)
        y += 4.5
    text(s, 3.2, y - 0.2, 40.0, 1.5, ["※ 앉다가 다시 일어서면(ω < −5°/s) 즉시 STANDING, 토크 0"], size=22, color=GRAY)
    text(s, L, 72.8, 42.0, 1.9, [f"개인 기준 (실측 30 cm 착석 {st['n_used']}회 + 45 cm 착석 각도)"], size=32, bold=True)
    text(s, L, 74.8, 42.0, 7.8, [
        ["보조 OFF로 평소처럼 앉은 기록을 허벅지 5° 구간으로 나눠 저장"],
        [("• 평균 하강 속도 ω_ref(θ)와 표준편차 σ(θ)", {"bold": True})],
        [("• 평균 상체 숙임 φ_ref(θ) (허리 IMU)", {"bold": True})],
        ["• 평소 착석 각도와 평소 최대 각가속도"],
        ["→ 사람마다 다른 착석 속도·자세를 그대로 기준으로 사용"]], size=26, space_after=4)

    text(s, 46.3, 51.0, 41.5, 2.0, ["보조 토크 = 상체 지지 + 적응형 제동"], size=34, bold=True)
    eq = [("1. 상체 지지", "τ_s = K_s · sin φ   (K_s = 6 Nm, φ: 엔코더 − 허벅지 IMU)",
           "숙인 상체를 버티는 신전근 부담을 덜어 올바른 숙임 자세 유지"),
          ("2. 적응형 하강 제동", "z³ = (ω̂ − ω_ref(θ̂)) / σ(θ̂),   τ_b = K·g·max(0, z − 3.5)",
           "ω̂ = ω + α·0.05 s로 미리 반응 · DEEP / 상체 덜 숙임이면 g = 1.5 · 급가속이면 z ≥ 5"),
          ("3. 출력 제한", "τ = sat[0, 10 Nm](τ_s + τ_b),   상승 ≤ 60 Nm/s",
           "두 토크 모두 신전 방향이라 서로 상쇄되지 않음 · 일어설 때는 0")]
    y = 53.3
    for head, formula, desc in eq:
        text(s, 46.8, y, 41.0, 1.6, [head], size=30, bold=True, color=WINE)
        text(s, 47.6, y + 1.6, 40.0, 1.5, [formula], size=28)
        text(s, 47.6, y + 3.1, 40.0, 1.5, [desc], size=22, color=GRAY)
        y += 5.0
    picture(s, figs / "fig_profile.png", 49.6, 68.5, 35.0)
    box(s, L, 82.6, 84.8, 3.0,
        ["\"개인 기준이 이상을 찾고, 상체 지지가 자세를 받치고, 적응형 제동이 속도를 잡는다\""],
        size=32, bold=True)

    # 4. 작동 검증 (실측) ------------------------------------------------------------
    section(s, 2.4, 86.7, 46.8, "4. 작동 검증 (실측 H10 데이터)")
    picture(s, figs / "fig_trial_real.png", L + 2.2, 89.8, 25.6)
    steps = [("① SUIT 로그 디코딩", "1 kHz → 100 Hz"),
             ("② 의자별 앉기 검출", f"45 cm {st['chair']['n45']}회 · 30 cm {st['chair']['n30']}회"),
             ("③ 개인 기준 생성", f"평균 {st['dur']:.1f} s · 최대 {st['peak']:.0f}°/s"),
             ("④ 정상 착석 재생", f"{st['quiet']}/{st['n_used']}회 제동 없음"),
             ("⑤ 낮은 의자 판정", f"30 cm {st['chair']['deep30']}/{st['chair']['n30']}회 DEEP 감지")]
    y = 90.0
    for i, (head, sub) in enumerate(steps):
        box(s, 33.8, y, 15.0, 2.7, [[(head, {"bold": True})], [sub]], size=20,
            fill=PINK if i < 4 else RGBColor(0xF4, 0xC7, 0xCF))
        if i < 4:
            arrow(s, 40.9, y + 2.75, 0.8, 0.6)
        y += 3.45

    # 용어 · 출처 각주 (본문 숫자와 연결)
    R_ = RGBColor(0x44, 0x44, 0x44)
    text(s, L, 108.0, 46.4, 6.6, [
        {"t": [("용어 · 출처", {"bold": True, "color": WINE}),
               ("   그래프: 실측 rep05를 나머지 9회 기준에 다시 재생 (토크는 계산값)", {"color": GRAY})], "size": 17},
        {"t": "¹ 고관절 신전근: 엉덩이 · 허벅지 뒤 근육(대둔근 · 햄스트링), 다리를 뒤로 폄   "
              "² 편심성 수축: 근육이 늘어나면서 힘을 내는 수축(착석 시 브레이크)   "
              "³ z: 평소 평균보다 표준편차의 몇 배 빠른지   ⁴ jerk: 가속도 변화의 급격함(작을수록 부드러움)",
         "size": 15, "color": R_},
        {"t": "[1] Robinovitch SN et al. Lancet. 2013;381(9860):47–54.   "
              "[2] Chen LK et al. J Am Med Dir Assoc. 2020;21(3):300–307.   "
              "[3] Rodosky MW et al. J Orthop Res. 1989;7(2):266–271.   "
              "[4] Balasubramanian S et al. J NeuroEng Rehabil. 2015;12:112.", "size": 15, "color": R_}],
        size=15, space_after=2)

    # 5. 결과 및 기대 효과 --------------------------------------------------------
    section(s, 51.2, 86.7, 36.2, "5. 결과 및 기대 효과")
    text(s, 51.2, 89.8, 36.2, 1.3, ["같은 사람의 H10 실측: 45 cm 2회(보행 보조 ON) vs 30 cm 10회"], size=20, color=GRAY)
    table(s, 51.2, 91.1, 36.2, result_rows(metrics_csv), col_w=[14.6, 7.2, 7.2, 7.2], row_h=1.2, size=21)
    text(s, 51.2, 99.7, 36.2, 4.6, [
        [("① 낙상 위험 동작 완화: ", {"bold": True}), "낮은 의자를 착석 각도로 자동 감지 (실측 9/10)"],
        [("② 의자 높이와 무관: ", {"bold": True}), "착용형 + 낮은 의자 자동 감지"],
        [("③ 개인 맞춤: ", {"bold": True}), "평소 착석 10~15회만으로 기준 생성"]], size=24, space_after=1)

    # 6. 결론 ---------------------------------------------------------------------
    section(s, 51.2, 104.4, 36.2, "6. 결론")
    text(s, 51.2, 107.5, 36.2, 7.0, [
        [("# 실측: 45 cm 2회 · 30 cm 10회", {"bold": True})],
        {"t": f"30 cm에서 {st['chair']['deeper_by']:.0f}° 더 깊음 · 낮은 의자 판정 {st['chair']['deep30']}/{st['chair']['n30']} · 정상 착석 {st['quiet']}/{st['n_used']} 제동 없음", "size": 22, "color": GRAY},
        [("# H10 적용", {"bold": True})],
        {"t": "실측 기준값을 넣은 C 코드로 30 cm 의자에서 H10 OFF vs ON 비교", "size": 22, "color": GRAY},
        [("# 주장 범위", {"bold": True})],
        {"t": "낮은 의자 착석 후반부의 급하강 감소 (낙상 예방 자체는 입증하지 않음)", "size": 22, "color": GRAY}],
        size=26, space_after=1)

    out.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(out))
    print(f"저장: {out}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--template", required=True)
    ap.add_argument("--out", default=str(HERE / "착석보조_포스터.pptx"))
    ap.add_argument("--figs", default=str(HERE / "figs"))
    ap.add_argument("--metrics", default=str(HERE.parent / "results" / "real" / "chair_metrics.csv"))
    ap.add_argument("--real", default=str(HERE.parent / "data" / "real" / "chair30"))
    args = ap.parse_args()
    build(Path(args.template), Path(args.out), Path(args.figs), Path(args.metrics), Path(args.real))


if __name__ == "__main__":
    main()
