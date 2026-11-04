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
MEMBERS = "팀원 / 이지우, 이지섭, 박수민"


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


TINT = RGBColor(0xF7, 0xF1, 0xF2)     # 카드 바탕 (발표 자료의 연한 카드와 같은 역할)
INK = RGBColor(0x1E, 0x1E, 0x1E)
SUBG = RGBColor(0x5E, 0x5E, 0x5E)
DARKW = RGBColor(0x55, 0x16, 0x25)


def card(slide, x, y, w, h, fill=TINT, radius_cm=0.6):
    """둥근 카드. 테두리와 그림자 없이 연한 바탕만."""
    c = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Cm(x), Cm(y), Cm(w), Cm(h))
    c.adjustments[0] = min(0.5, radius_cm / min(w, h))
    c.fill.solid()
    c.fill.fore_color.rgb = fill
    c.line.fill.background()
    c.shadow.inherit = False
    return c


def head(slide, x, y, w, num, eyebrow, title, size=40):
    """발표 자료처럼 작은 영문 라벨 + 굵은 제목."""
    text(slide, x, y, w, 1.1, [[(f"{num}  {eyebrow}", {"color": WINE})]], size=20, bold=True, space_after=0)
    text(slide, x, y + 1.0, w, 2.2, [title], size=size, bold=True, color=INK, space_after=0)


def stat(slide, x, y, w, h, big, label):
    card(slide, x, y, w, h)
    text(slide, x + 0.5, y + 0.3, w - 1.0, 2.8, [big], size=60, bold=True, color=WINE, space_after=0)
    text(slide, x + 0.5, y + 3.1, w - 1.0, h - 3.2, [label], size=21, color=SUBG, space_after=0)


def link(slide, pts, color=WINE):
    """연결선. 마지막 구간 끝에 화살촉."""
    segs = list(zip(pts, pts[1:]))
    for k, ((x1, y1), (x2, y2)) in enumerate(segs):
        c = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Cm(x1), Cm(y1), Cm(x2), Cm(y2))
        c.name = "PIPE link"
        c.line.color.rgb = color
        c.line.width = Pt(2.5)
        if k == len(segs) - 1:
            ln = c.line._get_or_add_ln()
            ln.append(ln.makeelement(qn("a:tailEnd"), {"type": "triangle", "w": "med", "len": "med"}))


def pipeline(slide, y0):
    """제어 파이프라인: 발표 자료처럼 STEP 카드 여섯 개를 가로로 잇는다."""
    card(slide, 2.6, y0, 84.8, 8.8)
    steps = [("STEP 1", "H10 센서", "허벅지 IMU와 고관절 엔코더를 100 Hz로 읽는다", None),
             ("STEP 2", "자세 계산", "잡음을 걸러 허벅지 각도·속도와 상체 숙임을 낸다", None),
             ("STEP 3", "평소와 비교", "같은 각도에서 평소보다 얼마나 빠른지 본다", WINE),
             ("STEP 4", "단계 판단", "서 있음 → 앉는 중 → 낮은 의자 → 앉음", None),
             ("STEP 5", "두 가지 힘", "상체 지지 + 빠를 때만 하강 제동", None),
             ("OUTPUT", "H10 보조 토크", "최대 10 Nm, 천천히 켜고 앉으면 푼다", DARKW)]
    w, gap = 11.4, 2.88
    for i, (lab, title, desc, fill) in enumerate(steps):
        x = 3.6 + i * (w + gap)
        card(slide, x, y0 + 1.1, w, 6.6, fill=fill or WHITE, radius_cm=0.4)
        hc, dc, lc = (WHITE, PINK, PINK) if fill else (INK, SUBG, WINE)
        text(slide, x + 0.4, y0 + 1.5, w - 0.8, 1.0, [lab], size=16, bold=True, color=lc, space_after=0)
        text(slide, x + 0.4, y0 + 2.4, w - 0.8, 1.6, [title], size=25, bold=True, color=hc, space_after=0)
        text(slide, x + 0.4, y0 + 4.1, w - 0.8, 3.4, [desc], size=18, color=dc, space_after=0)
        if i < 5:
            link(slide, [(x + w + 0.45, y0 + 4.4), (x + w + gap - 0.45, y0 + 4.4)])


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
    """실측 착석 기록(45 cm, 개인 기준)과 compare_chairs.py 결과에서 포스터에 쓸 숫자를 뽑는다."""
    from evaluate import load_participant, trial_metrics
    p = load_participant(real_dir)
    m = pd.DataFrame([trial_metrics(df) for df in p["calib"]])
    ch = json.loads((HERE.parent / "results" / "real" / "chair_stats.json").read_text())
    return {"chair": ch, "n_used": len(p["calib"]), "dur": m.descent_time.mean(), "peak": m.peak_vel.mean(),
            "quiet": ch["brake_quiet45"], "late": ch["late_caught45"], "late_k": ch["late_k"]}


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
    B = {"bold": True, "color": INK}
    W_ = {"bold": True, "color": WINE}

    # 01 배경 ---------------------------------------------------------------------
    head(s, L, 19.0, CW, "01", "BACKGROUND", "낮은 의자에서 털썩 앉게 된다")
    card(s, L, 23.0, CW, 9.0)
    picture(s, assets / "grandma_sit.png", L + 0.8, 23.5, 6.0)
    text(s, L + 7.4, 23.6, CW - 8.0, 8.2, [
        {"t": ["할머니께서 의자에 ", ("털썩 주저앉으시는", W_), " 모습을 보았다."], "size": 26, "bold": True,
         "color": INK, "space_after": 8},
        {"t": "의자가 낮을수록 더 힘들어하셨고, 테이블이나 손잡이를 팔로 짚고 버티며 내려가셨다. "
              "하지만 의자가 낮거나 짚을 곳이 없으면 그마저도 할 수 없다. "
              "팔로 짚는 것도 약해진 다리를 대신하는 보상 전략일 뿐이다.[7]", "size": 22, "color": SUBG,
         "space_after": 8},
        {"t": [("→ 이 문제를 H10으로 풀어 보기로 했다.", W_)], "size": 22}], space_after=0)
    text(s, L, 32.5, CW, 1.6, ["왜 낮은 의자인가"], size=26, bold=True, color=INK, space_after=0)
    reasons = [("REASON 1", "더 깊이 내려간다",
                f"H10으로 직접 재 보니 30 cm 의자는 45 cm보다 고관절을 {st['chair']['deeper_by']:.0f}° 더 접어야 "
                "엉덩이가 닿았다."),
               ("REASON 2", "오래 버텨야 한다", "의자가 낮을수록 상체를 숙인 채 다리로 몸무게를 받치는 구간이 길어진다.[3]"),
               ("REASON 3", "마지막에 힘이 풀린다", "다리가 끝까지 못 버티면 착석 직전 속도가 붙어 털썩 앉거나 뒤로 넘어진다.[1]")]
    for i, (lab, title, body) in enumerate(reasons):
        x = L + i * 13.8
        card(s, x, 34.3, 13.0, 8.1)
        text(s, x + 0.5, 34.8, 12.0, 0.9, [lab], size=16, bold=True, color=WINE, space_after=0)
        text(s, x + 0.5, 35.6, 12.0, 1.5, [title], size=25, bold=True, color=INK, space_after=0)
        text(s, x + 0.5, 37.3, 12.0, 5.0, [body], size=21, color=SUBG, space_after=0)
    card(s, L, 42.9, CW, 3.1, fill=WINE)
    text(s, L + 0.6, 42.9, CW - 1.2, 3.1, [[("대상  ", {"bold": True}),
                                           "다리 근력이 약한 근감소증 위험 고령자 · 의자에서 다섯 번 일어서는 데 12초 이상[2]"]],
         size=22, color=WHITE, anchor=MSO_ANCHOR.MIDDLE, space_after=0)

    # 02 문제 정의 -----------------------------------------------------------------
    head(s, R, 19.0, CW, "02", "PROBLEM", "앉을 때 고관절이 브레이크를 건다")
    picture(s, assets / "muscles_wine.png", R + 1.3, 23.0, 38.0)
    text(s, R, 37.4, CW, 4.2, [[
        "엉덩이와 허벅지 뒤 근육(고관절 신전근)이 늘어나면서 힘을 내 ",
        ("숙인 상체를 받치고 내려가는 속도를 늦춘다.", B),
        " 힘이 약하면 마지막에 속도가 붙고 무게중심이 발 뒤로 빠진다.[5][6] "
        "하지 착석을 보조하면 팔로 짚는 힘이 약 70% 줄었다는 보고도 있다.[8]"]], size=21, color=SUBG, space_after=0)
    table(s, R, 41.6, CW, [
        ["기존 방법", "움직임 측정", "즉각 보조", "고관절 직접", "장소 무관"],
        ["높은 의자 · 팔걸이", "X", "O", "X", "X"],
        ["지팡이 · 워커", "X", "O", "X", "O"],
        ["IMU · 카메라", "O", "X", "X", "△"],
        ["H10 (이번 연구)", "O", "O", "O", "O"]],
        col_w=[12.6, 7.0, 7.0, 7.0, 7.0], row_h=0.88, size=18, highlight_last=True)

    # 03 알고리즘 -------------------------------------------------------------------
    head(s, L, 47.6, 84.8, "03", "ALGORITHM", "평소의 나와 비교해, 빠를 때만 브레이크를 건다")
    pipeline(s, 51.4)

    card(s, L, 61.0, 41.6, 23.6)
    text(s, L + 1.0, 61.6, 39.6, 1.6, ["착석 단계 판단"], size=26, bold=True, color=INK, space_after=0)
    states = [("서 있음", RGBColor(0x9A, 0x9A, 0x9A), "평소 서 있는 자세를 기억한다"),
              ("앉는 중", WINE, "평소 속도와 비교하며 보조한다"),
              ("낮은 의자", RGBColor(0xC0, 0x39, 0x4B), "평소 앉던 속도까지 더 세게 늦춘다"),
              ("앉음", RGBColor(0x4A, 0x4A, 0x4A), "0.3초에 걸쳐 힘을 풀고, 일어서면 처음으로")]
    trans = ["양쪽 허벅지가 굽혀지기 시작하면", "평소 앉던 각도보다 더 깊이 내려가면", "움직임이 멈추면 (의자에 닿음)"]
    y = 63.6
    for i, (name, col, desc) in enumerate(states):
        card(s, L + 1.0, y, 8.6, 2.3, fill=col, radius_cm=1.15)
        text(s, L + 1.0, y, 8.6, 2.3, [name], size=22, bold=True, color=WHITE, align=PP_ALIGN.CENTER,
             anchor=MSO_ANCHOR.MIDDLE, space_after=0)
        text(s, L + 10.2, y, 31.0, 2.3, [desc], size=24, color=INK, anchor=MSO_ANCHOR.MIDDLE, space_after=0)
        if i < 3:
            text(s, L + 1.6, y + 2.3, 38.0, 1.3, [f"↓  {trans[i]}"], size=19, color=SUBG,
                 anchor=MSO_ANCHOR.MIDDLE, space_after=0)
        y += 3.6
    text(s, L + 1.0, 78.2, 39.6, 6.0, [
        {"t": [("개인 기준", W_)], "size": 23, "space_after": 2},
        {"t": f"보조 없이 45 cm 의자에 앉은 {st['n_used']}회를 허벅지 각도 5°마다 나눠 평소 속도와 흔들림 폭, 상체 숙임을 저장한다. "
              "사람마다 '빠르다'의 기준이 다르기 때문이다.", "size": 21, "color": SUBG}], space_after=0)

    card(s, 45.8, 61.0, 41.6, 23.6)
    text(s, 46.8, 61.6, 39.6, 1.6, ["보조 힘은 이렇게 정한다"], size=26, bold=True, color=INK, space_after=0)
    text(s, 46.8, 63.6, 39.6, 7.6, [
        {"t": [("① 상체 지지  ", W_), "숙인 만큼 고관절을 펴는 힘을 더해 엉덩이 근육의 부담을 던다."], "space_after": 10},
        {"t": [("② 하강 제동  ", W_), "같은 자세의 평소 속도보다 훨씬 빠를 때만 건다. 낮은 의자에서는 더 세게."],
         "space_after": 10},
        {"t": [("③ 안전 제한  ", W_), "최대 10 Nm, 천천히 올리고, 앉으면 0.3초에 걸쳐 푼다."]}],
        size=22, color=INK, space_after=0)
    picture(s, figs / "fig_profile.png", 49.6, 71.2, 34.0)

    # 04 검증 -----------------------------------------------------------------------
    head(s, L, 86.4, 45.0, "04", "VALIDATION", "실측 착석을 알고리즘에 다시 재생했다", size=36)
    picture(s, figs / "fig_trial_real.png", L, 90.3, 25.0)
    stats4 = [(f"{st['quiet']}/{st['n_used']}", "45 cm 정상 착석에서는 제동이 걸리지 않았다"),
              (f"{st['late']}/{st['n_used']}", f"후반을 {st['late_k']:g}배 빠르게 만든 가상 착석에서 제동했다"),
              (f"{st['chair']['deep30']}/{st['chair']['n30']}", "30 cm 착석을 낮은 의자로 감지했다")]
    for i, (big, label) in enumerate(stats4):
        stat(s, 28.4, 90.3 + i * 6.05, 19.2, 5.6, big, label)
    text(s, L, 108.6, 45.0, 6.0, [
        {"t": f"그래프: 45 cm 착석 한 회의 후반을 {st['late_k']:g}배 빠르게 만든 가상 착석을 나머지 {st['n_used'] - 1}회 기준에 재생 (토크는 계산값).   "
              "고관절 신전근: 대둔근 · 햄스트링.   편심성 수축: 근육이 늘어나면서 힘을 내는 수축.", "size": 13},
        {"t": "[1] Robinovitch SN et al. Lancet. 2013;381:47–54.  [2] Chen LK et al. JAMDA. 2020;21:300–307.  "
              "[3] Yoshioka S et al. BioMed Eng OnLine. 2014;13:27.  [5] Dubost V et al. Phys Ther. 2005;85:404–412.  "
              "[6] Stevens JA et al. Inj Epidemiol. 2014;1:5.  [7] van der Kruk E et al. J Biomech. 2021;122:110411.  "
              "[8] Chang SR et al. JNER. 2016;13:27.", "size": 13}], color=SUBG, space_after=2)

    # 05 결과 · 06 결론 ----------------------------------------------------------------
    X5, W5 = 50.0, 37.4
    head(s, X5, 86.4, W5, "05", "RESULT", f"낮은 의자에서 {st['chair']['deeper_by']:.0f}° 더 깊이 앉았다", size=36)
    table(s, X5, 90.3, W5, result_rows(metrics_csv), col_w=[16.4, 7.0, 7.0, 7.0], row_h=0.98, size=19,
          highlight_last=True)
    card(s, X5, 97.6, W5, 5.6)
    text(s, X5 + 0.6, 97.9, W5 - 1.2, 5.0, [
        [("낮은 의자 자동 감지  ", W_), "의자 높이를 몰라도 착석 각도로 판단"],
        [("개인 맞춤  ", W_), "평소 착석 10~15회만으로 기준 생성"],
        [("장소 무관  ", W_), "짚을 곳이 없어도 고관절을 직접 보조"]], size=22, color=INK, space_after=6)
    head(s, X5, 103.8, W5, "06", "CONCLUSION", "확인한 것과 남은 것", size=30)
    text(s, X5, 106.8, W5, 7.8, [
        [("확인 ", B), f"30 cm에서 {st['chair']['deeper_by']:.0f}° 더 깊게 앉았고, 낮은 의자를 "
                      f"{st['chair']['deep30']}/{st['chair']['n30']}회 감지했으며, 정상 착석 "
                      f"{st['quiet']}/{st['n_used']}회는 제동하지 않았다."],
        [("다음 ", B), "실측 기준값을 넣은 C 코드로 30 cm 의자에서 보조 OFF/ON을 비교한다."],
        [("한계 ", B), "한 사람의 기록이며, 낙상 예방 자체는 아직 입증하지 않았다."]],
        size=21, color=SUBG, space_after=6)

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
    ap.add_argument("--real", default=str(HERE.parent / "data" / "real" / "chair45"))
    args = ap.parse_args()
    build(Path(args.template), Path(args.out), Path(args.figs), Path(args.metrics), Path(args.real), Path(args.assets))


if __name__ == "__main__":
    main()
