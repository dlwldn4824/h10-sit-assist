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


def table(slide, x, y, w, rows, col_w, row_h, size=24, highlight_last=False):
    """머리줄은 와인색, 본문은 흰 바탕에 얇은 가로줄. O/X/△는 ●/–/△로 바꾼다."""
    shp = slide.shapes.add_table(len(rows), len(rows[0]), Cm(x), Cm(y), Cm(w), Cm(row_h * len(rows)))
    tb = shp.table
    tb.first_row = tb.horz_banding = False
    marks = {"O": ("●", WINE), "X": ("–", RGBColor(0xAA, 0xAA, 0xAA)), "△": ("△", GRAY)}
    for j, cw in enumerate(col_w):
        tb.columns[j].width = Cm(cw)
    for i, row in enumerate(rows):
        tb.rows[i].height = Cm(row_h)
        for j, val in enumerate(row):
            cell = tb.cell(i, j)
            head, hl = i == 0, highlight_last and i == len(rows) - 1
            cell.fill.solid()
            cell.fill.fore_color.rgb = WINE if head else (PINK if hl else WHITE)
            cell.margin_left = cell.margin_right = Cm(0.25)
            cell.margin_top = cell.margin_bottom = Cm(0.03)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            txt, color = str(val), (WHITE if head else BLACK)
            if not head and j > 0 and txt in marks:
                txt, color = marks[txt]
            p = cell.text_frame.paragraphs[0]
            p.alignment = PP_ALIGN.LEFT if j == 0 else PP_ALIGN.CENTER
            _runs(p, txt, size, bold=head or hl, color=color)
            tcPr = cell._tc.get_or_add_tcPr()
            for tag in ("a:lnL", "a:lnR", "a:lnT", "a:lnB"):
                ln = tcPr.makeelement(qn(tag), {"w": "9525" if tag == "a:lnB" else "0"})
                fill = ln.makeelement(qn("a:solidFill" if tag == "a:lnB" else "a:noFill"), {})
                if tag == "a:lnB":
                    fill.append(fill.makeelement(qn("a:srgbClr"), {"val": "C8C8C8"}))
                ln.append(fill)
                tcPr.insert(("a:lnL", "a:lnR", "a:lnT", "a:lnB").index(tag), ln)
    return tb


def link(slide, pts, color=RGBColor(0x55, 0x55, 0x55)):
    """연결선. 마지막 구간 끝에 화살촉."""
    segs = list(zip(pts, pts[1:]))
    for k, ((x1, y1), (x2, y2)) in enumerate(segs):
        c = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Cm(x1), Cm(y1), Cm(x2), Cm(y2))
        c.name = "PIPE link"
        c.line.color.rgb = color
        c.line.width = Pt(2)
        if k == len(segs) - 1:
            ln = c.line._get_or_add_ln()
            ln.append(ln.makeelement(qn("a:tailEnd"), {"type": "triangle", "w": "med", "len": "med"}))


def pipeline(slide, y0):
    """제어 파이프라인 블록도: 측정 → 속도 비교 → 단계 판단 → 두 가지 힘 → H10."""
    EDGE, DARK, SUB = RGBColor(0xAA, 0xAA, 0xAA), RGBColor(0x55, 0x16, 0x25), RGBColor(0x55, 0x55, 0x55)

    def group(x, w, label):
        g = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Cm(x), Cm(y0), Cm(w), Cm(7.6))
        g.fill.solid()
        g.fill.fore_color.rgb = RGBColor(0xF7, 0xF4, 0xF5)
        g.line.color.rgb = EDGE
        g.line.width = Pt(1.5)
        g.line.dash_style = MSO_LINE.DASH
        g.shadow.inherit = False
        text(slide, x + 0.2, y0 + 0.1, w - 0.4, 1.0, [label], size=17, bold=True, color=SUB, space_after=0)

    def block(x, y, w, h, head, body, fill=WHITE, line=EDGE, hc=BLACK, bc=SUB):
        box(slide, x, y, w, h, [[(head, {"bold": True, "color": hc, "size": 21})], [(body, {"color": bc, "size": 16})]],
            fill=fill, line=line, shape=MSO_SHAPE.RECTANGLE)

    group(2.6, 17.6, "측정")
    block(3.2, y0 + 1.1, 16.4, 1.9, "H10 센서", "허벅지 IMU · 고관절 엔코더")
    block(3.2, y0 + 3.2, 16.4, 1.9, "잡음 제거 · 100 Hz", "빠른 떨림을 걸러 냄")
    block(3.2, y0 + 5.3, 16.4, 1.9, "자세 계산", "허벅지 굽힘 · 속도 · 상체 숙임")
    block(23.2, y0, 13.6, 2.4, "평소 기준값", "보조 없이 앉은 10회")
    block(23.2, y0 + 3.6, 13.6, 4.0, "속도 비교", "같은 자세의 평소 속도보다\n얼마나 빠른가", fill=WINE, line=None,
          hc=WHITE, bc=PINK)
    block(39.8, y0 + 3.6, 13.6, 4.0, "단계 판단", "서 있음 · 앉는 중\n낮은 의자 · 앉음", fill=DARK, line=None,
          hc=WHITE, bc=PINK)
    group(56.4, 15.6, "출력")
    block(57.0, y0 + 1.1, 14.4, 2.9, "상체 지지", "숙인 상체를 받친다", line=WINE, hc=WINE)
    block(57.0, y0 + 4.4, 14.4, 2.9, "하강 제동", "평소보다 빠를 때만 건다", line=WINE, hc=WINE)
    block(75.0, y0 + 1.6, 12.4, 4.4, "H10 보조 토크", "두 힘의 합 · 최대 10 Nm\n천천히 켜고 앉으면 푼다", line=WINE, hc=WINE,
          bc=BLACK)
    link(slide, [(20.2, y0 + 5.6), (23.2, y0 + 5.6)])
    link(slide, [(30.0, y0 + 2.4), (30.0, y0 + 3.6)])
    link(slide, [(36.8, y0 + 5.6), (39.8, y0 + 5.6)])
    link(slide, [(53.4, y0 + 5.6), (56.4, y0 + 5.6)])
    link(slide, [(72.0, y0 + 3.8), (75.0, y0 + 3.8)])


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
    INK = RGBColor(0x22, 0x22, 0x22)

    def sub(x, y, w, title):
        """소제목 (1-1. …)."""
        text(s, x, y, w, 1.6, [title], size=30, bold=True, space_after=0)

    def para(x, y, w, h, parts, size=24, space_after=4):
        text(s, x, y, w, h, parts if isinstance(parts[0], list) else [parts], size=size, color=INK,
             space_after=space_after)

    def vrule(x, y1, y2):
        box(s, x, y1, 0.05, y2 - y1, [""], fill=RGBColor(0xBB, 0xBB, 0xBB), line=None, shape=MSO_SHAPE.RECTANGLE)

    # 1. 주제 선정 배경 --------------------------------------------------------
    section(s, L, 18.8, CW, "1. 주제 선정 배경")
    sub(L, 22.0, 33.0, "1-1. 할머니의 착석에서 시작했다")
    para(L, 23.7, 33.4, 6.6, [
        "할머니께서 의자에 ", ("털썩 주저앉으시는", {"bold": True, "color": WINE}),
        " 모습을 보았다. 의자가 낮을수록 더 힘들어하셨고, 테이블이나 의자 손잡이를 ",
        ("팔 힘으로 짚고 버티며", {"bold": True}), " 내려가셨다. 하지만 의자가 낮거나 짚을 곳이 없으면 ",
        ("그마저도 할 수 없다.", {"bold": True}), " 손으로 짚는 것도 약해진 하체를 팔로 대신하는 보상 전략일 뿐이다.[7] "
        "이 문제를 H10으로 풀어 보고자 했다."], size=25)
    picture(s, assets / "grandma_sit.png", L + 33.8, 21.8, 6.8)
    sub(L, 30.5, CW, "1-2. 왜 낮은 의자인가")
    para(L, 32.2, CW, 6.4, [
        [("① 더 깊이 굽힌다. ", {"bold": True}), "30 cm 의자는 45 cm보다 허벅지가 9° 더 굽혀진다(실측)."],
        [("② 더 오래 버틴다. ", {"bold": True}), "낮을수록 동작이 길고(1.6→2.0초) 상체를 더 숙인다.[3]"],
        [("③ 마지막이 가장 빠르다. ", {"bold": True}), "털썩 주저앉거나 뒤로 넘어지기 쉽다.[1]"],
        [("④ 대상: ", {"bold": True}), "착석 제어가 어려운 근감소증 위험 고령자 (5회 의자 일어서기 ≥ 12초)[2]"]],
        size=24, space_after=3)
    sub(L, 38.6, CW, "1-3. 기존 방법은 측정과 개입을 동시에 하지 못한다")
    table(s, L, 40.3, CW, [
        ["방법", "움직임 측정", "즉각 보조", "고관절 직접", "장소 무관"],
        ["높은 의자 · 팔걸이", "X", "O", "X", "X"],
        ["지팡이 · 워커", "X", "O", "X", "O"],
        ["IMU · 카메라", "O", "X", "X", "△"],
        ["H10 (제안)", "O", "O", "O", "O"]],
        col_w=[12.6, 7.0, 7.0, 7.0, 7.0], row_h=1.3, size=21, highlight_last=True)

    vrule(45.0, 19.0, 46.8)

    # 2. 생체역학적 관점에서의 문제정의 ----------------------------------------
    section(s, R, 18.8, CW, "2. 생체역학적 관점에서의 문제정의")
    sub(R, 22.0, CW, "2-1. 앉을 때 고관절에서 일어나는 일")
    picture(s, assets / "muscles_wine.png", R, 23.7, CW)
    para(R, 38.9, CW, 3.9, [
        "고관절 신전근¹은 편심성 수축²으로 ", ("① 숙인 상체를 버티고 ② 내려가는 속도를 늦춘다.", {"bold": True}),
        " 고령자는 상체를 약 10° 덜 숙이고[5], 근력이 약하면 빠르게 내려가며 무게중심이 발 뒤로 빠진다"
        " (고령자 낙상의 17.6%가 뒤로 주저앉음[6])."], size=23)
    sub(R, 42.9, CW, "2-2. H10으로 같은 방향의 힘을 더한다")
    picture(s, assets / "h10.png", R, 44.4, 2.6)
    para(R + 3.0, 44.5, CW - 3.0, 2.4, [
        "고관절을 펴는 토크 하나로 ", ("상체 지지와 하강 제동", {"bold": True, "color": WINE}),
        "을 함께 돕는다. 하지 착석을 보조하면 팔로 짚는 힘이 약 70% 줄었다는 보고가 있다.[8]"], size=21)

    # 3. 알고리즘 설계 ---------------------------------------------------------
    section(s, 2.5, 47.8, 84.9, "3. 알고리즘 설계")
    sub(L, 51.0, 84.8, "3-1. 제어 파이프라인")
    pipeline(s, 52.8)

    sub(L, 61.0, CW, "3-2. 착석 단계 판단")
    states = [("서 있음", RGBColor(0x80, 0x80, 0x80), "평소 서 있는 자세를 기억한다"),
              ("앉는 중", WINE, "평소 속도와 비교하며 보조한다"),
              ("낮은 의자", RGBColor(0xC0, 0x39, 0x4B), "평소 앉던 속도까지 더 세게 늦춘다"),
              ("앉음", RGBColor(0x4A, 0x4A, 0x4A), "0.3초에 걸쳐 힘을 풀고, 일어서면 처음으로")]
    trans = ["양쪽 허벅지가 굽혀지기 시작하면", "평소 앉던 각도보다 더 깊이 내려가면", "움직임이 멈추면 (의자에 닿음)"]
    y = 62.8
    for i, (name, col, desc) in enumerate(states):
        box(s, L, y, 9.0, 2.2, [name], fill=col, line=None, size=25, bold=True, color=WHITE,
            shape=MSO_SHAPE.RECTANGLE)
        text(s, L + 9.6, y, 31.0, 2.2, [desc], size=23, color=INK, anchor=MSO_ANCHOR.MIDDLE)
        if i < 3:
            arrow(s, L + 4.0, y + 2.3, 1.0, 1.0)
            text(s, L + 5.4, y + 2.2, 35.0, 1.4, [trans[i]], size=20, color=GRAY, anchor=MSO_ANCHOR.MIDDLE)
        y += 3.9
    para(L, 76.9, CW, 1.2, [("앉다가 다시 일어서면 바로 '서 있음'으로 돌아가고 힘을 끈다.", {"color": GRAY})], size=20)
    sub(L, 78.4, CW, "3-3. 개인 기준")
    para(L, 80.1, CW, 4.6, [
        [f"보조 없이 평소처럼 앉은 기록(30 cm {st['n_used']}회)을 허벅지 각도 5°마다 나눠, "
         "각 각도에서의 평소 내려가는 속도와 그 흔들림 폭, 평소 상체 숙임을 저장한다. "
         "같은 속도라도 사람마다 '빠르다'의 기준이 다르기 때문이다."]], size=25)

    vrule(45.0, 61.0, 84.6)

    sub(R, 61.0, CW, "3-4. 보조 힘 결정")
    expl = [("① 상체 지지", "상체를 숙인 만큼 고관절을 펴는 힘을 더해, 숙인 자세를 버티는 엉덩이 근육의 부담을 덜어 준다."),
            ("② 적응형 하강 제동", "내려가는 속도를 같은 자세의 평소 속도와 비교해, 평소보다 훨씬 빠를 때만 브레이크를 건다. "
                                "낮은 의자에서는 더 세게 건다."),
            ("③ 안전 제한", "최대 10 Nm까지만 내고, 힘은 천천히 올린다. 앉으면 0.3초에 걸쳐 풀고, 일어서면 바로 끈다.")]
    y = 62.7
    for (head, body), h in zip(expl, (2.4, 3.3, 2.4)):
        para(R, y, CW, h, [[(head + ". ", {"bold": True, "color": WINE}), body]], size=22)
        y += h
    picture(s, figs / "fig_profile.png", R + 3.3, 70.6, 34.0)
    para(R, 83.8, CW, 1.4, [("그림 2. 개인 기준 — 허벅지 각도별 평소 하강 속도(왼쪽)와 상체 숙임(오른쪽), 실측 30 cm 10회",
                             {"color": GRAY})], size=18)

    # 4. 작동 검증 (실측) ------------------------------------------------------------
    section(s, 2.4, 86.7, 46.8, "4. 작동 검증 (실측 H10 데이터)")
    sub(L, 89.9, 44.0, "4-1. 실측 착석을 알고리즘에 다시 재생")
    picture(s, figs / "fig_trial_real.png", L, 91.6, 25.0)
    para(L, 109.6, 25.0, 1.3, [("그림 3. 빠르게 앉은 rep05를 나머지 9회 기준에 재생 (토크는 계산값)", {"color": GRAY})], size=17)
    steps = [("① 로그 디코딩", "H10 SUIT 로그 1 kHz → 100 Hz"),
             ("② 앉기 검출", f"45 cm {st['chair']['n45']}회 · 30 cm {st['chair']['n30']}회"),
             ("③ 개인 기준", f"평균 {st['dur']:.1f}초 · 최대 {st['peak']:.0f}°/s"),
             ("④ 정상 착석", f"{st['quiet']}/{st['n_used']}회 제동 없음"),
             ("⑤ 낮은 의자", f"30 cm {st['chair']['deep30']}/{st['chair']['n30']}회 감지")]
    y = 91.8
    for head, body in steps:
        text(s, 28.4, y, 20.6, 1.4, [head], size=23, bold=True, color=WINE, space_after=0)
        text(s, 28.4, y + 1.3, 20.6, 1.4, [body], size=21, color=INK, space_after=0)
        y += 3.6
    text(s, L, 111.0, 46.4, 3.8, [
        {"t": "¹ 고관절 신전근: 엉덩이 · 허벅지 뒤 근육(대둔근 · 햄스트링)   "
              "² 편심성 수축: 근육이 늘어나면서 힘을 내는 수축(착석 시 브레이크)", "size": 14, "color": GRAY},
        {"t": "[1] Robinovitch SN et al. Lancet. 2013;381:47–54.  [2] Chen LK et al. JAMDA. 2020;21:300–307.  "
              "[3] Yoshioka S et al. BioMed Eng OnLine. 2014;13:27.  [4] Balasubramanian S et al. JNER. 2015;12:112.  "
              "[5] Dubost V et al. Phys Ther. 2005;85:404–412.  [6] Stevens JA et al. Inj Epidemiol. 2014;1:5.  "
              "[7] van der Kruk E et al. J Biomech. 2021;122:110411.  [8] Chang SR et al. JNER. 2016;13:27.",
         "size": 14, "color": GRAY}], size=14, space_after=1)

    # 5. 결과 및 기대 효과 --------------------------------------------------------
    section(s, 51.2, 86.7, 36.2, "5. 결과 및 기대 효과")
    sub(51.2, 89.9, 36.2, "5-1. 같은 사람의 45 cm vs 30 cm 착석")
    table(s, 51.2, 91.6, 36.2, result_rows(metrics_csv), col_w=[15.2, 7.0, 7.0, 7.0], row_h=1.15, size=20,
          highlight_last=True)
    sub(51.2, 100.0, 36.2, "5-2. 기대 효과")
    para(51.2, 101.6, 36.2, 3.4, [
        [("낮은 의자 자동 감지 · ", {"bold": True}), "의자 높이를 몰라도 착석 각도로 판단 (실측 9/10)"],
        [("개인 맞춤 · ", {"bold": True}), "평소 착석 10~15회만으로 기준 생성"],
        [("장소 무관 · ", {"bold": True}), "몸에 입는 장치라 짚을 곳이 없는 곳에서도 고관절을 직접 보조"]], size=21, space_after=2)

    # 6. 결론 ---------------------------------------------------------------------
    section(s, 51.2, 105.2, 36.2, "6. 결론")
    para(51.2, 108.3, 36.2, 6.5, [
        [("실측 · ", {"bold": True}), f"30 cm에서 {st['chair']['deeper_by']:.0f}° 더 깊게 앉았고, 낮은 의자를 "
                                        f"{st['chair']['deep30']}/{st['chair']['n30']}회 감지했으며, 정상 착석 "
                                        f"{st['quiet']}/{st['n_used']}회는 제동하지 않았다."],
        [("H10 적용 · ", {"bold": True}), "실측 기준값을 넣은 C 코드로 30 cm 의자에서 보조 OFF/ON을 비교한다."],
        [("주장 범위 · ", {"bold": True}), "낮은 의자 착석 후반부의 급하강 감소까지이며, 낙상 예방 자체는 입증하지 않았다."]],
        size=23, space_after=4)

    # 한글이 글자 단위로 끊기지 않게 모든 문단을 단어 단위 줄바꿈으로 둔다
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
