"""매치업 포스터 양식(90×120cm)에 착석 보조 알고리즘 포스터를 만든다.

그림 중 H10 · 할머니 · 근육 이미지는 Figma 발표 자료에서 받아 poster/assets/에 둔다(저장소 제외).
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
from pptx.enum.dml import MSO_LINE
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.oxml.ns import qn
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
TOP = "2025 <H10 Control Algorithm>"
COURSE = "교과목명 / 제어알고리즘설계및실습(고찬영 교수님)"
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


def table(slide, x, y, w, rows, col_w, row_h, size=24, highlight_last=False, marks=False):
    """머리줄은 와인색 둥근 띠, 본문은 얇은 구분선만. marks=True면 O/X를 ●/–로 바꾼다."""
    n = len(rows)
    box(slide, x, y, w, row_h, [""], fill=WINE, line=None)
    for i, row in enumerate(rows):
        yy = y + i * row_h
        hl = highlight_last and i == n - 1
        if hl:
            box(slide, x, yy + 0.08, w, row_h - 0.16, [""], fill=PINK, line=WINE)
        elif 0 < i < n - 1 or (i == n - 1 and not highlight_last):
            box(slide, x + 0.2, yy + row_h - 0.03, w - 0.4, 0.04, [""], fill=RGBColor(0xE6, 0xD6, 0xDA), line=None,
                shape=MSO_SHAPE.RECTANGLE)
        cx = x
        for j, val in enumerate(row):
            txt, color = str(val), (WHITE if i == 0 else BLACK)
            if marks and i > 0 and j > 0:
                txt, color = ("●", WINE) if val == "O" else ("–", RGBColor(0xB5, 0xB5, 0xB5))
            text(slide, cx + (0.3 if j == 0 else 0), yy, col_w[j] - (0.3 if j == 0 else 0), row_h,
                 [{"t": txt, "color": color, "bold": i == 0 or hl or (marks and txt == "●"),
                   "align": PP_ALIGN.LEFT if j == 0 else PP_ALIGN.CENTER}],
                 size=size, anchor=MSO_ANCHOR.MIDDLE, space_after=0)
            cx += col_w[j]


def link(slide, pts, color=RGBColor(0x9A, 0x8A, 0x8E)):
    """점선 연결선. 마지막 구간 끝에 화살촉."""
    segs = list(zip(pts, pts[1:]))
    for k, ((x1, y1), (x2, y2)) in enumerate(segs):
        c = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Cm(x1), Cm(y1), Cm(x2), Cm(y2))
        c.name = "PIPE link"
        c.line.color.rgb = color
        c.line.width = Pt(2.5)
        c.line.dash_style = MSO_LINE.DASH
        if k == len(segs) - 1:
            ln = c.line._get_or_add_ln()
            ln.append(ln.makeelement(qn("a:tailEnd"), {"type": "triangle", "w": "med", "len": "med"}))


def pipeline(slide, y0):
    """제어 파이프라인: 측정 → 평소와 비교 → 단계 판단 → 두 가지 힘 → H10 (발표 14쪽과 같은 구성)."""
    DASH, DARK, SUB = RGBColor(0x9A, 0x8A, 0x8E), RGBColor(0x55, 0x16, 0x25), RGBColor(0x66, 0x66, 0x66)
    shapes = []

    def group(x, w, label):
        g = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Cm(x), Cm(y0 + 0.6), Cm(w), Cm(6.4))
        g.adjustments[0] = 0.08
        g.fill.background()
        g.line.color.rgb = DASH
        g.line.width = Pt(2)
        g.line.dash_style = MSO_LINE.DASH
        g.shadow.inherit = False
        shapes.append(g)
        shapes.append(box(slide, x + w / 2 - 2.0, y0 + 0.1, 4.0, 1.0, [label], fill=WHITE, line=DASH, size=20, bold=True))

    def card(x, y, w, h, head, sub, fill=WHITE, line=RGBColor(0xE6, 0xD6, 0xDA), hc=BLACK, sc=SUB, inline=False):
        paras = ([[(head, {"bold": True, "color": hc, "size": 20}), ("   " + sub, {"color": sc, "size": 16})]] if inline
                 else [[(head, {"bold": True, "color": hc, "size": 22})], [(sub, {"color": sc, "size": 17})]])
        shapes.append(box(slide, x, y, w, h, paras, fill=fill, line=line))

    def circle(x, y, d, head, sub, grad=False):
        c = slide.shapes.add_shape(MSO_SHAPE.OVAL, Cm(x), Cm(y), Cm(d), Cm(d))
        c.shadow.inherit = False
        if grad:
            c.fill.gradient()
            c.fill.gradient_angle = 45
            c.fill.gradient_stops[0].color.rgb = RGBColor(0xC9, 0x7A, 0x8A)
            c.fill.gradient_stops[1].color.rgb = WINE
            c.line.fill.background()
        else:
            c.fill.solid()
            c.fill.fore_color.rgb = PINK
            c.line.color.rgb = WINE
            c.line.width = Pt(2)
        tf = c.text_frame
        tf.word_wrap = True
        tf.vertical_anchor = MSO_ANCHOR.MIDDLE
        tf.margin_left = tf.margin_right = Cm(0.2)
        lines = [(t, 20, True) for t in head.split("\n")] + ([(sub, 14, False)] if sub else [])
        for i, (t, sz, b) in enumerate(lines):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            p.alignment = PP_ALIGN.CENTER
            _runs(p, t, sz, b, WHITE if grad else (WINE if b else SUB))
        shapes.append(c)

    group(2.6, 19.0, "측정")
    card(3.4, y0 + 1.5, 17.4, 1.6, "H10 센서", "허벅지 IMU · 고관절 엔코더", inline=True)
    card(3.4, y0 + 3.3, 17.4, 1.6, "잡음 제거", "빠른 떨림을 걸러 냄", inline=True)
    card(3.4, y0 + 5.1, 17.4, 1.6, "자세 계산", "굽힘 · 속도 · 상체 숙임", inline=True)
    card(24.6, y0, 11.0, 1.7, "평소 기준값", "내 평소 착석 10회")
    circle(27.6, y0 + 2.0, 5.0, "평소보다\n얼마나\n빠른가", "", grad=True)
    shapes.append(box(slide, 37.0, y0 + 3.0, 11.5, 3.2, [[("지금 어느 단계인가", {"bold": True, "color": WHITE, "size": 22})],
                                                          [("서 있음 · 앉는 중 · 낮은 의자 · 앉음", {"color": PINK, "size": 16})]],
                      fill=DARK, line=None))
    group(50.4, 20.0, "출력")
    circle(52.6, y0 + 1.0, 5.6, "상체 지지", "숙인 상체를 받침")
    circle(62.6, y0 + 1.0, 5.6, "하강 제동", "평소보다 빠를 때만")
    card(72.6, y0 + 1.9, 14.8, 4.4, "H10 보조 힘", "두 힘을 더해 최대 10 Nm\n천천히 켜고 앉으면 풀기", hc=WINE, sc=BLACK)
    link(slide, [(21.6, y0 + 4.5), (27.5, y0 + 4.5)])
    link(slide, [(30.1, y0 + 1.7), (30.1, y0 + 1.95)])
    link(slide, [(32.6, y0 + 4.5), (36.9, y0 + 4.5)])
    link(slide, [(48.5, y0 + 4.6), (50.3, y0 + 4.6)])
    link(slide, [(70.4, y0 + 4.1), (72.5, y0 + 4.1)])
    for sh in shapes:
        sh.name = "PIPE " + sh.name


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

def build(template: Path, out: Path, figs: Path, metrics_csv: Path, real_dir: Path, assets: Path):
    st = real_stats(real_dir)
    prs = Presentation(str(template))
    s = prs.slides[0]
    tree = s.shapes._spTree
    keep = {sh._element for sh in s.shapes if sh.shape_id in KEEP_IDS}
    for el in list(tree):          # 수식 개체(mc:AlternateContent)는 shapes에 안 잡혀서 트리에서 직접 지운다
        tag = el.tag.split("}")[1]
        if tag not in ("nvGrpSpPr", "grpSpPr") and el not in keep:
            tree.remove(el)

    top = next(sh for sh in s.shapes if sh.shape_id == 2)      # 상단 제목줄
    set_paragraph(top.text_frame.paragraphs[0], TOP)

    # 제목 표: 제목 / (빈 줄) / 교과목명 / 팀명 / 팀원
    tbl = next(sh for sh in s.shapes if sh.shape_id == 7).table
    paras = tbl.cell(0, 0).text_frame.paragraphs
    set_paragraph(paras[0], TITLE[0])
    paras[1].alignment = paras[0].alignment          # 빈 줄을 제목 둘째 줄로 사용
    paras[1]._p.append(copy.deepcopy(paras[0].runs[0]._r))
    paras[1].runs[0].text = TITLE[1]
    set_paragraph(paras[2], COURSE)
    set_paragraph(paras[3], TEAM)
    set_paragraph(paras[4], MEMBERS)

    L, R, CW = 2.6, 46.8, 40.6

    # 1. 주제 선정 배경 --------------------------------------------------------
    section(s, L, 18.8, CW, "1. 주제 선정 배경")
    text(s, L, 22.2, CW, 1.8, ["출발점: 할머니의 착석"], size=34, bold=True)
    text(s, L, 24.0, 31.6, 4.6, [[
        "할머니께서 의자에 ", ("털썩 주저앉으시는", {"bold": True, "color": WINE}),
        " 모습을 보았다. 의자가 낮을수록 더 힘들어하셨고, 테이블이나 의자 손잡이를 ",
        ("팔 힘으로 짚고 버티며", {"bold": True}), " 내려가셨다. 하지만 의자가 낮거나 짚을 곳이 없으면 ",
        ("그마저도 할 수 없다.", {"bold": True, "color": WINE}), " 이 문제를 H10으로 풀어 보고자 했다."]], size=24)
    picture(s, assets / "grandma_sit.png", L + 32.4, 22.0, 8.1)
    text(s, L, 28.9, 31.6, 1.5, ["왜 낮은 의자인가?"], size=30, bold=True)
    text(s, L, 30.4, 31.6, 5.0, [
        [("① 더 깊이 굽혀야 한다: ", {"bold": True}), "30 cm 의자는 45 cm보다 허벅지가 9° 더 굽혀진다."],
        [("② 더 오래, 더 숙여서 버텨야 한다: ", {"bold": True}), "낮을수록 길고(1.6→2.0초) 더 숙인다.[3]"],
        [("③ 마지막 순간이 가장 빠르다: ", {"bold": True}),
         ("털썩 주저앉거나 뒤로 넘어지기 쉽다.", {"bold": True, "color": WINE}), "[1]"],
        [("④ 생활 곳곳에 있다: ", {"bold": True}), "팔걸이 없는 소파 · 좌변기 (손 짚기는 보상 전략[7])"]], size=24, space_after=3)
    box(s, L, 35.6, CW, 1.8, [[("타깃: ", {"bold": True}), "착석 제어가 어려운 근감소증 위험 고령자 (AWGS 2019[2]: 5회 의자 일어서기 ≥ 12초)"]],
        size=22, align=PP_ALIGN.LEFT)
    text(s, L, 37.6, CW, 1.5, ["기존 방법은 측정과 개입을 동시에 하지 못한다"], size=28, bold=True)
    table(s, L, 39.2, CW, [
        ["방법", "움직임 측정", "즉각 보조", "고관절 직접", "장소 무관"],
        ["높은 의자 · 팔걸이", "X", "O", "X", "X"],
        ["지팡이 · 워커", "X", "O", "X", "O"],
        ["IMU", "O", "X", "X", "O"],
        ["카메라", "O", "X", "X", "X"],
        ["H10 (제안)", "O", "O", "O", "O"]],
        col_w=[11.6, 7.25, 7.25, 7.25, 7.25], row_h=1.15, size=21, highlight_last=True, marks=True)

    # 2. 생체역학적 관점에서의 문제정의 ----------------------------------------
    section(s, R, 18.8, CW, "2. 생체역학적 관점에서의 문제정의")
    text(s, R, 22.2, CW, 1.8, ["어째서 낙상 위험이 생기는가?"], size=34, bold=True)
    picture(s, assets / "muscles_wine.png", R + 1.3, 23.9, 38.0)
    text(s, R, 38.4, CW, 4.4, [
        ["고관절 신전근¹은 편심성 수축²으로 ", ("① 숙인 상체를 버티고 ② 하강 속도를 제동", {"bold": True}),
         "한다. 고령자는 상체를 약 10° 덜 숙이고[5], 근력이 약하면 빠르게 내려가며 ",
         ("무게중심이 발 뒤로 빠진다", {"bold": True, "color": WINE}), " (고령자 낙상의 17.6%가 뒤로 주저앉음[6])."]])
    hb = box(s, R, 42.7, CW, 3.7, [["H10 ", ("신전 토크", {"bold": True}), " 하나로 ",
                               ("상체 지지 + 하강 제동", {"bold": True, "color": WINE}), "을 동시에 보조"],
                              ["선행 연구: 하지 착석 보조 시 팔 지지 힘 약 70% 감소[8]"]], size=28)
    hb.text_frame.margin_left = Cm(4.6)
    picture(s, assets / "h10.png", R + 0.6, 42.95, 3.3)

    # 3. 알고리즘 설계 ---------------------------------------------------------
    section(s, 2.5, 47.8, 84.9, "3. 알고리즘 설계")
    text(s, L, 51.0, 84.8, 2.0, ["제어 파이프라인: 재고 → 평소와 비교하고 → 단계를 판단해 → 두 가지 힘으로 돕는다"], size=34, bold=True)
    pipeline(s, 53.2)

    text(s, L, 60.6, 42.0, 1.9, ["착석 단계 판단 (4단계)"], size=32, bold=True)
    states = [("서 있음", RGBColor(0x80, 0x80, 0x80), "평소 서 있는 자세를 기억한다"),
              ("앉는 중", WINE, "평소 속도와 비교하며 보조한다"),
              ("낮은 의자", RGBColor(0xC0, 0x39, 0x4B), "평소 앉던 속도까지 더 세게 늦춘다"),
              ("앉음", RGBColor(0x4A, 0x4A, 0x4A), "0.3초에 걸쳐 힘을 풀고, 일어서면 처음으로")]
    trans = ["양쪽 허벅지가 굽혀지기 시작하면",
             "평소 앉던 각도보다 더 깊이 내려가면",
             "움직임이 멈추면 (의자에 닿음)"]
    y = 62.7
    for i, (name, col, desc) in enumerate(states):
        box(s, 3.2, y, 10.0, 2.4, [name], fill=col, line=None, size=28, bold=True, color=WHITE)
        text(s, 13.8, y, 29.0, 2.4, [desc], size=24, anchor=MSO_ANCHOR.MIDDLE)
        if i < 3:
            arrow(s, 7.6, y + 2.5, 1.0, 1.0)
            text(s, 9.0, y + 2.4, 33.0, 1.2, [[("▶ ", {"color": WINE}), trans[i]]], size=21, color=GRAY,
                 anchor=MSO_ANCHOR.MIDDLE)
        y += 3.6
    text(s, 3.2, y - 1.0, 40.0, 1.3, ["※ 앉다가 다시 일어서면 바로 '서 있음'으로 돌아가고 힘을 끈다"], size=20, color=GRAY)
    text(s, L, 77.5, 42.0, 1.8, ["개인 기준: 내 평소 착석이 기준"], size=30, bold=True)
    text(s, L, 79.3, 42.0, 6.0, [
        [f"보조 없이 평소처럼 앉은 기록(30 cm {st['n_used']}회)을 허벅지 각도 5°마다 나눠 저장"],
        [("• 각 각도에서의 평소 내려가는 속도와 그 흔들림 폭", {"bold": True})],
        [("• 각 각도에서의 평소 상체 숙임", {"bold": True})],
        ["• 평소 앉는 깊이 (45 cm 의자 착석 각도)"],
        ["→ 같은 속도라도 사람마다 '빠르다'의 기준이 다르다"]], size=22, space_after=2)

    text(s, 46.3, 60.6, 41.5, 1.9, ["보조 힘은 이렇게 정한다"], size=32, bold=True)
    expl = [("① 상체 지지", "상체를 숙인 만큼 고관절을 펴는 힘을 더해, 숙인 자세를 버티는 엉덩이 근육의 부담을 덜어 준다."),
            ("② 적응형 하강 제동", "내려가는 속도를 같은 자세의 평소 속도와 비교해, 평소보다 훨씬 빠를 때만 브레이크를 건다. "
                                "낮은 의자에서는 더 세게 건다."),
            ("③ 안전 제한", "최대 10 Nm까지만, 힘은 천천히 올린다. 앉으면 0.3초에 걸쳐 풀고, 일어서면 바로 끈다.")]
    y = 62.6
    for head, body in expl:
        text(s, 46.8, y, 41.0, 1.5, [head], size=28, bold=True, color=WINE)
        text(s, 46.8, y + 1.45, 41.0, 2.6, [body], size=22)
        y += 3.9
    picture(s, figs / "fig_profile.png", 53.0, 74.6, 28.0)

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
              "² 편심성 수축: 근육이 늘어나면서 힘을 내는 수축(착석 시 브레이크)",
         "size": 15, "color": R_},
        {"t": "[1] Robinovitch SN et al. Lancet. 2013;381(9860):47–54.   "
              "[2] Chen LK et al. J Am Med Dir Assoc. 2020;21(3):300–307.   "
              "[3] Yoshioka S et al. BioMed Eng OnLine. 2014;13:27.   "
              "[4] Balasubramanian S et al. J NeuroEng Rehabil. 2015;12:112.", "size": 15, "color": R_},
        {"t": "[5] Dubost V et al. Phys Ther. 2005;85(5):404–412.   "
              "[6] Stevens JA et al. Inj Epidemiol. 2014;1:5.   "
              "[7] van der Kruk E et al. J Biomech. 2021;122:110411.   "
              "[8] Chang SR et al. J NeuroEng Rehabil. 2016;13:27.", "size": 15, "color": R_}],
        size=15, space_after=2)

    # 5. 결과 및 기대 효과 --------------------------------------------------------
    section(s, 51.2, 86.7, 36.2, "5. 결과 및 기대 효과")
    text(s, 51.2, 89.8, 36.2, 1.3, ["같은 사람의 H10 실측: 45 cm 2회(보행 보조 ON) vs 30 cm 10회"], size=20, color=GRAY)
    table(s, 51.2, 91.1, 36.2, result_rows(metrics_csv), col_w=[14.6, 7.2, 7.2, 7.2], row_h=1.2, size=21, highlight_last=True)
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

    # 한글이 글자 단위로 끊기지 않게 모든 문단을 단어 단위 줄바꿈으로 둔다
    from pptx.oxml.ns import qn
    for p in tree.iter(qn("a:p")):
        p.get_or_add_pPr().set("eaLnBrk", "0")

    out.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(out))
    print(f"저장: {out}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--template", required=True)
    ap.add_argument("--out", default=str(HERE / "착석보조_포스터.pptx"))
    ap.add_argument("--figs", default=str(HERE / "figs"))
    ap.add_argument("--assets", default=str(HERE / "assets"))   # 발표 자료 이미지(H10 · 할머니 · 근육), 저장소에 올리지 않음
    ap.add_argument("--metrics", default=str(HERE.parent / "results" / "real" / "chair_metrics.csv"))
    ap.add_argument("--real", default=str(HERE.parent / "data" / "real" / "chair30"))
    args = ap.parse_args()
    build(Path(args.template), Path(args.out), Path(args.figs), Path(args.metrics), Path(args.real), Path(args.assets))


if __name__ == "__main__":
    main()
