"""발표용 H10 이미지 만들기: 배경 제거(PNG + SVG 래퍼)와 선화 벡터화(SVG).

    python presentation/make_assets.py <이미지 폴더> --out presentation/assets

입력 파일 이름: lineart (결과지 선화), sitting (착용 사진), front (정면 제품), angle (3/4 제품)
결과지 선화는 그림 부분만 잘라 쓴다. 이름·나이 같은 개인 정보 영역은 버린다.
"""
from __future__ import annotations

import argparse
import base64
from pathlib import Path

import cv2
import numpy as np


def remove_background(img: np.ndarray, grabcut: bool = False, fill_holes: bool = False) -> np.ndarray:
    """밝은 단색 배경을 투명하게 만든 BGRA 이미지를 돌려준다."""
    h, w = img.shape[:2]
    border = np.concatenate([img[0], img[-1], img[:, 0], img[:, -1]]).astype(float)
    bg = np.median(border, axis=0)
    dist = np.linalg.norm(img.astype(float) - bg, axis=2)
    fg = (dist > 28).astype(np.uint8)
    if grabcut:      # 밝은 옷처럼 배경과 비슷한 물체는 GrabCut으로 보완
        mask = np.where(fg > 0, cv2.GC_PR_FGD, cv2.GC_PR_BGD).astype(np.uint8)
        mask[:3, :] = mask[-3:, :] = cv2.GC_BGD
        mask[:, :3] = mask[:, -3:] = cv2.GC_BGD
        bgd, fgd = np.zeros((1, 65)), np.zeros((1, 65))
        cv2.grabCut(img, mask, None, bgd, fgd, 6, cv2.GC_INIT_WITH_MASK)
        fg = np.isin(mask, [cv2.GC_FGD, cv2.GC_PR_FGD]).astype(np.uint8)
    fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(fg)
    keep = np.zeros_like(fg)
    big = max(stats[i, cv2.CC_STAT_AREA] for i in range(1, n))
    for i in range(1, n):            # 작은 얼룩은 버리고 큰 덩어리만 남긴다
        if stats[i, cv2.CC_STAT_AREA] > 0.05 * big:
            keep[lab == i] = 1
    keep = cv2.morphologyEx(keep, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    filled = keep.copy()
    if fill_holes:                   # 사람 사진: 옷 안쪽의 밝은 부분이 뚫리지 않게 구멍을 메운다
        ff = np.zeros((h + 2, w + 2), np.uint8)
        inv = (1 - filled).astype(np.uint8)
        cv2.floodFill(inv, ff, (0, 0), 2)
        filled[inv == 1] = 1
    filled = cv2.erode(filled, np.ones((5, 5), np.uint8))   # 배경색이 섞인 가장자리(흰 테두리) 제거
    alpha = cv2.GaussianBlur((filled * 255).astype(np.uint8), (5, 5), 0)
    out = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
    out[:, :, 3] = alpha
    ys, xs = np.nonzero(alpha > 10)
    pad = 8
    return out[max(ys.min() - pad, 0):ys.max() + pad, max(xs.min() - pad, 0):xs.max() + pad]


def png_svg(png: Path, w: int, h: int) -> str:
    data = base64.b64encode(png.read_bytes()).decode()
    return (f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
            f'width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
            f'<image width="{w}" height="{h}" xlink:href="data:image/png;base64,{data}"/></svg>')


def lineart_svg(img: np.ndarray, color: str, scale: int = 4) -> tuple[str, int, int]:
    """선화를 윤곽선 경로로 바꾼 SVG. 확대 후 추적해 곡선을 부드럽게 한다."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    big = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    big = cv2.GaussianBlur(big, (5, 5), 0)
    _, bw = cv2.threshold(big, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    contours, _ = cv2.findContours(bw, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    paths = []
    for c in contours:
        if cv2.contourArea(c) < 6 * scale * scale and len(c) < 20:
            continue
        c = cv2.approxPolyDP(c, 0.6, True)[:, 0, :] / scale
        paths.append("M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in c) + " Z")
    h, w = gray.shape
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
           f'<path fill="{color}" fill-rule="evenodd" d="{" ".join(paths)}"/></svg>')
    return svg, w, h


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--out", default="presentation/assets")
    args = ap.parse_args()
    src, out = Path(args.src), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    for name, grabcut, holes in (("sitting", True, True), ("front", False, False), ("angle", False, False)):
        f = next(src.glob(name + ".*"))
        cut = remove_background(cv2.imread(str(f)), grabcut, holes)
        png = out / f"h10_{name}.png"
        cv2.imwrite(str(png), cut)
        (out / f"h10_{name}.svg").write_text(png_svg(png, cut.shape[1], cut.shape[0]))
        print(f"{png.name} {cut.shape[1]}x{cut.shape[0]}")

    img = cv2.imread(str(next(src.glob("lineart.*"))))
    h, w = img.shape[:2]
    drawing = img[int(h * 0.45):int(h * 0.93), int(w * 0.36):w]      # 그림만 (위쪽 개인 정보 · 아래 로고 제외)
    for color, suffix in (("#1d2a5b", ""), ("#ffffff", "_white")):
        svg, sw, sh = lineart_svg(drawing, color)
        (out / f"h10_lineart{suffix}.svg").write_text(svg)
    print(f"h10_lineart.svg {sw}x{sh}")


if __name__ == "__main__":
    main()
