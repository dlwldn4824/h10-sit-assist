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
sys.path.insert(0, str(HERE))
WINE = RGBColor(0x77, 0x22, 0x35)
PINK = RGBColor(0xF6, 0xE6, 0xE9)
GRAY = RGBColor(0x55, 0x55, 0x55)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
BLACK = RGBColor(0, 0, 0)
KEEP_IDS = {2, 3, 7, 10}          # 상단 제목줄, 로고 묶음, 제목 표, 테두리

TITLE = ("엔젤로보틱스 고관절 보조 웨어러블 로봇 H10 기반", "낮은 의자 착석 감지 및 적응형 하강 제동 시스템")
TOP = "2025 <H10 Control Algorithm>"
COURSE = "교과목명 / 제어알고리즘설계및실습(고찬영 교수님)"
TEAM = "팀명 / KWAI"
MEMBERS = "팀원 / 이지우, 이지섭, 박수민"


# ---------------------------------------------------------------- 도형 도우미

FONT = "Noto Sans KR"


def _font(r):
    """라틴·한글 글꼴을 모두 FONT로 (양식 기본 글꼴은 없는 PC에서 다른 글꼴로 바뀜)."""
    r.font.name = FONT
    rPr = r._r.get_or_add_rPr()
    for tag in ("a:ea", "a:cs"):
        el = rPr.find(qn(tag))
        if el is None:
            el = rPr.makeelement(qn(tag), {})
            rPr.append(el)
        el.set("typeface", FONT)


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
        _font(r)


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


def table(slide, x, y, w, rows, col_w, row_h, size=24, highlight_last=False,
          head_fill=RGBColor(0x3A, 0x3A, 0x3A), hl_fill=RGBColor(0xFF, 0xF4, 0xCC)):
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
            cell.fill.fore_color.rgb = head_fill if head else (hl_fill if hl else WHITE)
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
    from make_figures import fig_lead
    import tempfile
    lead = fig_lead(HERE.parent / "data" / "real" / "1107_set", Path(tempfile.mkdtemp()))
    return {"chair": ch, "lead": lead, "n_used": len(p["calib"]), "dur": m.descent_time.mean(), "peak": m.peak_vel.mean(),
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
    for r in list(paras[1].runs):                    # 이미 만든 포스터를 양식으로 다시 쓸 때 둘째 줄이 겹치지 않게
        paras[1]._p.remove(r._r)
    paras[1]._p.append(copy.deepcopy(paras[0].runs[0]._r))
    paras[1].runs[0].text = TITLE[1]
    set_paragraph(paras[2], COURSE)
    set_paragraph(paras[3], TEAM)
    set_paragraph(paras[4], MEMBERS)

    IVORY, LINE, BEIGE, YEL_T, DGRAY = (RGBColor(0xFF, 0xFF, 0xFF), RGBColor(0xE3, 0xE3, 0xE8),
                                        RGBColor(0xF5, 0xF5, 0xF7), RGBColor(0xFF, 0xF6, 0xD5), RGBColor(0x33, 0x36, 0x3D))
    B = {"bold": True, "color": INK}
    W_ = {"bold": True, "color": WINE}

    # 안쪽 바탕: 테두리 색과 어울리는 아이보리. 맨 뒤에 깐다.
    bg = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Cm(1.7), Cm(18.6), Cm(86.6), Cm(96.3))
    bg.fill.solid()
    bg.fill.fore_color.rgb = IVORY
    bg.line.fill.background()
    bg.shadow.inherit = False
    tree.remove(bg._element)
    tree.insert(2, bg._element)

    def band(x, y, w, num, title, bottom):
        """섹션: 흰 패널 위에 와인색 머리띠, 제목은 가운데."""
        outer = card(s, x - 0.5, y, w + 1.0, bottom - y, fill=WHITE, radius_cm=0.5)
        outer.line.color.rgb = LINE
        outer.line.width = Pt(1.2)
        card(s, x - 0.5, y, w + 1.0, 2.2, fill=WINE, radius_cm=0.5)
        sq = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Cm(x - 0.5), Cm(y + 1.1), Cm(w + 1.0), Cm(1.1))
        sq.fill.solid()
        sq.fill.fore_color.rgb = WINE
        sq.line.fill.background()
        sq.shadow.inherit = False
        text(s, x, y, w, 2.2, [title], size=30, bold=True, color=WHITE, align=PP_ALIGN.CENTER,
             anchor=MSO_ANCHOR.MIDDLE, space_after=0)

    def panel(x, y, w, h):
        return card(s, x, y, w, h, fill=BEIGE, radius_cm=0.4)

    def sub(x, y, w, title, size=24):
        """소제목은 [대괄호] 라벨로."""
        text(s, x, y, w, 1.5, [f"[{title.split('. ', 1)[-1]}]"], size=size, bold=True, color=WINE, space_after=0)

    def body(x, y, w, h, paras, size=21, space_after=6, color=SUBG):
        text(s, x, y, w, h, paras, size=size, color=color, space_after=space_after)

    def marker(x, y, w, h):
        """노란 형광펜: 가장 중요한 결과와 수치에만."""
        m = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Cm(x), Cm(y), Cm(w), Cm(h))
        m.adjustments[0] = 0.3
        m.fill.solid()
        m.fill.fore_color.rgb = YEL
        m.line.fill.background()
        m.shadow.inherit = False

    def pill(x, y, w, h, label, fill=WINE, color=WHITE, size=20):
        """알약형은 라벨에만 쓴다."""
        card(s, x, y, w, h, fill=fill, radius_cm=h / 2)
        text(s, x, y, w, h, [label], size=size, bold=True, color=color, align=PP_ALIGN.CENTER,
             anchor=MSO_ANCHOR.MIDDLE, space_after=0)

    def step(x, y, d, num, fill=WINE):
        """원은 단계 번호에만 쓴다."""
        c = s.shapes.add_shape(MSO_SHAPE.OVAL, Cm(x), Cm(y), Cm(d), Cm(d))
        c.fill.solid()
        c.fill.fore_color.rgb = fill
        c.line.fill.background()
        c.shadow.inherit = False
        text(s, x, y, d, d, [num], size=26, bold=True, color=WHITE, align=PP_ALIGN.CENTER,
             anchor=MSO_ANCHOR.MIDDLE, space_after=0)

    def dotted(pts, color=RGBColor(0xBF, 0xC3, 0xC9)):
        for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
            c = s.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Cm(x1), Cm(y1), Cm(x2), Cm(y2))
            c.line.color.rgb = color
            c.line.width = Pt(2.5)
            c.line.dash_style = MSO_LINE.ROUND_DOT

    def chair(x, floor, seat_h, w=4.6, col=RGBColor(0x8C, 0x90, 0x96)):
        """의자 아이콘: 좌판 높이(cm)를 같은 비율로 그린다 (1 cm = 0.12 cm)."""
        k = 0.12
        top = floor - seat_h * k
        for rx, ry, rw, rh in ((x, top, w, 0.45), (x + 0.15, top, 0.35, seat_h * k),
                               (x + w - 0.5, top, 0.35, seat_h * k), (x + w - 0.5, top - 2.4, 0.35, 2.4)):
            r = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Cm(rx), Cm(ry), Cm(rw), Cm(rh))
            r.fill.solid()
            r.fill.fore_color.rgb = col
            r.line.fill.background()
            r.shadow.inherit = False
        return top

    # 01 연구 배경 및 문제 정의 ------------------------------------------------------------
    X1, W1, Y0 = 2.6, 40.6, 18.9
    band(X1, Y0, W1, "01", "연구 배경 및 문제 정의", 48.4)
    sub(X1, 21.5, W1, "문제 정의")
    picture(s, figs / "fig_posture.png", X1, 23.1, W1)
    body(X1, 37.5, W1, 5.6, [[
        "고령자는 착석 후반에 하강 속도를 제어하지 못하고 ", ("상체를 세운 채 뒤로 주저앉기", W_),
        " 쉽습니다.[1][5] 팔걸이를 짚는 보상 전략[7]은 의자가 낮거나 짚을 곳이 없으면 불가능하며, "
        "낮은 의자일수록 고관절을 더 깊이 굽힌 채 오래 버텨야 합니다.[3]"]], size=20)
    sub(X1, 43.1, W1, "연구 목표")
    body(X1, 44.6, W1, 3.7, [
        [("① ", W_), "착석 각도로 낮은 의자 착석을 자동으로 감지합니다."],
        [("② ", W_), "개인의 평소 착석 속도를 기준으로 과도한 하강에만 제동합니다."],
        [("③ ", W_), "카메라 CoM과 비교한 상체 숙임으로 털썩 주저앉기를 착석 전에 알아채 미리 제동합니다."]],
        size=18, space_after=1, color=INK)

    # 02 실험 설계 및 데이터 ----------------------------------------------------------------
    X2, W2 = 46.8, 40.6
    band(X2, Y0, W2, "02", "실험 설계 및 데이터", 48.4)
    sub(X2, 21.5, W2, "실험 구성")
    panel(X2, 23.1, 11.4, 10.6)
    picture(s, assets / "h10.png", X2 + 1.3, 23.4, 8.8)
    pill(X2 + 1.0, 32.0, 9.4, 1.2, "H10 고관절 보조 로봇", size=16)
    panel(X2 + 12.2, 23.1, W2 - 12.2, 10.6)
    floor = 31.2
    t45 = chair(X2 + 17.0, floor, 45)
    t30 = chair(X2 + 29.4, floor, 30)
    dotted([(X2 + 13.0, floor + 0.05), (X2 + W2 - 0.8, floor + 0.05)])
    for xc, top, lab in ((X2 + 17.0, t45, "45 cm"), (X2 + 29.4, t30, "30 cm")):
        dotted([(xc - 0.7, top), (xc - 0.7, floor)], color=WINE)
        text(s, xc - 4.4, (top + floor) / 2 - 0.7, 3.6, 1.4, [lab], size=19, bold=True, color=WINE,
             align=PP_ALIGN.RIGHT, space_after=0)
    pill(X2 + 15.0, 32.0, W2 - 17.8, 1.2, f"의자별 착석 {st['chair']['n45']}회 · 카메라 CoM 검증 60회", fill=DGRAY, size=16)
    sub(X2, 34.4, W2, "측정 데이터")
    picture(s, figs / "fig_session.png", X2, 35.9, W2)

    # 03 시스템 구조 및 제어 방법 -------------------------------------------------------------
    Y3 = 49.2
    band(2.6, Y3, 84.8, "03", "시스템 구조 및 제어 방법", 82.5)
    steps = [("1", "센서 측정", "허벅지 IMU · 고관절 엔코더 100 Hz"),
             ("2", "자세 추정", "굽힘 각도 · 각속도 · 상체 숙임"),
             ("3", "개인 기준 비교", "같은 각도의 평소 속도와 비교"),
             ("4", "착석 단계 판단", "서 있음 · 앉는 중 · 낮은 의자 · 앉음"),
             ("5", "보조 토크 산출", "적응형 하강 제동 + 자세 판정 즉시 제동"),
             ("6", "H10 출력", "고관절 신전 토크 10 Nm 이하")]
    sw6 = (84.8 - 5 * 1.0) / 6
    for i, (num, title, desc) in enumerate(steps):
        x = 2.6 + i * (sw6 + 1.0)
        panel(x, 51.8, sw6, 5.6)
        step(x + 0.5, 52.3, 1.9, num, fill=DGRAY if i == 5 else WINE)
        text(s, x + 2.7, 52.3, sw6 - 3.0, 1.9, [title], size=20, bold=True, color=INK, anchor=MSO_ANCHOR.MIDDLE,
             space_after=0)
        body(x + 0.5, 54.5, sw6 - 1.0, 2.8, [desc], size=16)
        if i < 5:
            dotted([(x + sw6, 54.6), (x + sw6 + 1.0, 54.6)], color=WINE)

    cw3, top3, h3 = 27.6, 58.2, 23.8
    xs = [2.6 + k * (cw3 + 1.0) for k in range(3)]
    for x in xs:
        panel(x, top3, cw3, h3)

    x = xs[0]
    sub(x + 0.8, top3 + 0.6, cw3 - 1.6, "착석 단계 판단", size=22)
    states = [("서 있음", RGBColor(0x8A, 0x8A, 0x8A), "기준 자세를 갱신하며 토크는 0입니다.",
               "양쪽 허벅지가 0.1초간 굽혀지면"),
              ("앉는 중", WINE, "평소 속도 · 상체 숙임과 비교해 제동합니다.", "평소 착석 각도 + 2SD를 넘으면"),
              ("낮은 의자", RGBColor(0xA8, 0x3A, 0x4E), "제동을 1.5배로 강화합니다.", "엉덩이 충격 · 0.15초 멈춤 (다시 내려가면 되돌림)"),
              ("앉음", DGRAY, "0.3초에 걸쳐 토크를 해제합니다.", "")]
    y = top3 + 2.6
    for name, col, desc, cond in states:
        pill(x + 0.8, y, 7.0, 1.7, name, fill=col, size=19)
        body(x + 8.3, y - 0.05, cw3 - 9.0, 1.9, [desc], size=18, color=INK)
        if cond:
            dotted([(x + 4.3, y + 1.8), (x + 4.3, y + 4.3)])
            body(x + 8.3, y + 2.0, cw3 - 9.0, 1.8, [f"↓ {cond}"], size=16)
        y += 4.6
    body(x + 0.8, top3 + 20.4, cw3 - 1.6, 3.2, ["앉다가 다시 일어서면 즉시 '서 있음'으로 돌아가며 토크를 해제합니다."],
         size=16)

    x = xs[1]
    sub(x + 0.8, top3 + 0.6, cw3 - 1.6, "개인 기준", size=22)
    body(x + 0.8, top3 + 2.2, cw3 - 1.6, 3.4, [
        f"보조 없이 앉은 {st['n_used']}회를 허벅지 각도 5° 구간마다 저장해, 사람마다 다른 '평소 속도'를 기준으로 삼습니다."],
        size=17)
    picture(s, figs / "fig_profile.png", x + 0.6, top3 + 5.6, cw3 - 1.2)
    params = [("허용 폭 하한", "25°/s"), ("제동 시작", "평소 착석 각도의 50%"), ("제동 임계 점수", "3.5"),
              ("상체 덜 숙임 판정", "평소 숙임 − 2SD")]
    for k, (nm, val) in enumerate(params):
        yy = top3 + 16.0 + k * 1.85
        body(x + 0.8, yy, 12.0, 1.8, [nm], size=18, color=SUBG)
        body(x + 12.0, yy, cw3 - 12.8, 1.8, [{"t": val, "align": PP_ALIGN.RIGHT}], size=18, color=INK)
        if k < len(params) - 1:
            dotted([(x + 0.9, yy + 1.7), (x + cw3 - 0.9, yy + 1.7)], color=LINE)

    x = xs[2]
    sub(x + 0.8, top3 + 0.6, cw3 - 1.6, "보조 토크 설계", size=22)
    picture(s, assets / "muscles_wine.png", x + 0.6, top3 + 2.4, cw3 - 1.2)
    torques = [("적응형 하강 제동", "착석 후반에 평소보다 크게 빠를 때에만 제동합니다. 낮은 의자면 1.5배."),
               ("자세 판정 즉시 제동 (2차)", "평소보다 상체를 덜 숙이면 속도와 상관없이 바로 1.5 Nm로 제동합니다."),
               ("안전 제한", "10 Nm 이하, 상승 속도 60 Nm/s 이하로 제한합니다.")]
    y = top3 + 12.8
    for i, (title, desc) in enumerate(torques):
        step(x + 0.8, y, 1.5, str(i + 1), fill=WINE)
        body(x + 2.8, y - 0.2, cw3 - 3.6, 3.4, [[(title + "  ", B), desc]], size=17, color=SUBG)
        y += 3.6

    # 04 실측 검증 결과 --------------------------------------------------------------------
    Y4 = 83.2
    X4, W4 = 2.6, 52.4
    band(X4, Y4, W4, "04", "실측 검증 결과", 114.5)
    stats = [(f"+{st['chair']['deeper_by']:.1f}°", "30 cm 착석 각도 증가"),
             (f"{st['chair']['deep30']}/{st['chair']['n30']}", "낮은 의자 판정"),
             (f"{st['quiet']}/{st['n_used']}", "정상 착석 제동 없음"),
             (f"{st['lead']['v2_caught']}/{st['lead']['n_plop']}", "털썩 주저앉기 착석 전 제동")]
    sw = (W4 - 3 * 0.8) / 4
    for i, (big, lab) in enumerate(stats):
        x = X4 + i * (sw + 0.8)
        panel(x, 85.8, sw, 4.4)
        text(s, x, 85.9, sw, 2.5, [big], size=40, bold=True, color=WINE, align=PP_ALIGN.CENTER, space_after=0)
        body(x + 0.3, 88.4, sw - 0.6, 1.6, [{"t": lab, "align": PP_ALIGN.CENTER}], size=16)
    panel(X4, 90.8, 21.0, 19.6)
    sub(X4 + 0.7, 91.1, 19.6, "의자 높이별 착석 각도", size=19)
    picture(s, figs / "fig_chairs.png", X4 + 1.8, 92.6, 17.4)
    panel(X4 + 21.8, 90.8, W4 - 21.8, 19.6)
    sub(X4 + 22.5, 91.1, W4 - 23.2, "털썩 주저앉기 착석 전 판정 (1차 vs 2차)", size=19)
    picture(s, figs / "fig_lead.png", X4 + 23.6, 92.6, 26.6)
    body(X4, 110.7, W4, 3.4, [
        {"t": "[1] Robinovitch SN et al. Lancet. 2013;381:47–54.  [2] Chen LK et al. JAMDA. 2020;21:300–307.  "
              "[3] Yoshioka S et al. BioMed Eng OnLine. 2014;13:27.  [5] Dubost V et al. Phys Ther. 2005;85:404–412.  "
              "[7] van der Kruk E et al. J Biomech. 2021;122:110411."}], size=12, space_after=0)

    # 05 결론 및 고찰 ----------------------------------------------------------------------
    X5, W5 = 56.6, 30.8
    band(X5, Y4, W5, "05", "결론 및 고찰", 114.5)
    sub(X5, 85.7, W5, "핵심 수치 비교", size=20)
    table(s, X5, 87.3, W5, result_rows(metrics_csv), col_w=[13.0, 6.0, 6.0, 5.8], row_h=0.92,
          size=15, highlight_last=True, head_fill=DGRAY, hl_fill=BEIGE)
    c5 = card(s, X5, 94.4, W5, 11.6, fill=YEL_T, radius_cm=0.5)
    c5.line.color.rgb = RGBColor(0xF0, 0xDC, 0x96)
    c5.line.width = Pt(1.2)
    sub(X5 + 0.8, 94.8, W5 - 1.6, "결론", size=20)
    body(X5 + 0.8, 96.4, W5 - 1.6, 9.4, [
        [("낮은 의자 감지  ", B), f"착석 각도가 {st['chair']['deeper_by']:.1f}° 증가했고 {st['chair']['n30']}회 중 "
                                   f"{st['chair']['deep30']}회를 감지했습니다."],
        [("CoM 대리 지표  ", B), "카메라 CoM과 비교한 60회에서 H10 충격 · 속도 ρ ≈ −0.6, H10 추정 CoM r = 0.74였습니다."],
        [("착석 전 제동  ", B), f"2차 알고리즘은 털썩 주저앉기 {st['lead']['n_plop']}회를 모두 착석 약 "
                               f"{st['lead']['lead_med']:.1f}초 전에 제동했습니다 (1차 0회)."]],
        size=20, space_after=12, color=INK)
    panel(X5, 106.6, W5, 7.4)
    sub(X5 + 0.8, 106.9, W5 - 1.6, "1차 실측 → 2차 개선", size=20)
    body(X5 + 0.8, 108.4, W5 - 1.6, 5.4, [
        "1차 H10 ON 실측의 후반 제동 부족 · 앉기 전 보조 · 서 있을 때 오작동을 멈칫 뒤 재하강 처리와 자세 판정 "
        "즉시 제동으로 고쳤고, 2차 실측으로 검증합니다. 피험자 2명 · 2D 카메라의 한계가 있습니다."],
        size=17)

    # 양식의 제목줄 · 제목 표 글꼴도 맞춘다
    for r in tree.iter(qn("a:r")):
        from pptx.text.text import _Run
        _font(_Run(r, None))

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
