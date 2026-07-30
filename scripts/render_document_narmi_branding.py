"""문서나르미 브랜딩 자산 렌더(#258) — 심벌 PNG·파이널 보드·실행 파일 .ico.

원본 기하는 docs/branding/document-narmi-mark-final.svg 와 같은 세 장의 문서 면
(SHEETS). SVG 가 정본이고 이 스크립트는 같은 좌표를 Pillow 로 다시 그린다 —
둘이 갈리면 커밋된 .png/.ico 가 화면 심벌과 다른 형상이 된다.
Pillow 는 프로젝트 의존성이 아니다 — 산출물(.png/.ico)을 커밋하는 dev 전용 생성기라
재생성 시에만 임시로 얹어 돌린다:

    uv run --with pillow python scripts/render_document_narmi_branding.py
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "branding"
DEEP_BLUE = "#0E3FAE"
BLUE = "#1857D8"
MINT = "#43C9A8"
BRAND_COLORS = (DEEP_BLUE, BLUE, MINT)
REVERSED_COLORS = ("#A9C1FF", "#D4E0FF", "#FFFFFF")
INK = "#111827"
MUTED = "#667085"
PANEL = "#FFFFFF"
CANVAS = "#F4F6F9"
FONT_REGULAR = Path(r"C:\Windows\Fonts\malgun.ttf")
FONT_BOLD = Path(r"C:\Windows\Fonts\malgunbd.ttf")


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_BOLD if bold else FONT_REGULAR), size)


# 심벌 기하 — SVG 와 같은 64 단위 좌표계. 세 열린 문서 면이 오른쪽 위로 기울며
# 원본 → 처리 → 결과의 흐름을 만든다. 사선 윗변과 단계별 이동이 화살표 없이 전진감을 준다.
STROKES = (
    ((10, 50), (10, 17), (11, 13), (14, 11), (18, 10), (40, 15)),
    ((22, 57), (22, 30), (23, 27), (26, 24), (31, 23), (51, 28)),
    ((36, 58), (36, 44), (37, 41), (40, 38), (45, 37), (58, 41)),
)
MARK_STROKE_WIDTH = 10
MARK_BBOX = (5, 5, 63, 63)


def draw_mark(draw: ImageDraw.ImageDraw, origin, scale=1.0, color=None):
    ox, oy = origin

    if color is None:
        colors = BRAND_COLORS
    elif isinstance(color, tuple):
        colors = color
    else:
        colors = (color,) * len(STROKES)
    width = round(MARK_STROKE_WIDTH * scale)
    radius = width / 2
    for stroke, fill in zip(STROKES, colors, strict=True):
        points = [(ox + x * scale, oy + y * scale) for x, y in stroke]
        draw.line(points, fill=fill, width=width, joint="curve")
        for x, y in (points[0], points[-1]):
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=fill)


def mark_image(width: int, color=None, ss: int = 8) -> Image.Image:
    """폭 `width` px 의 마크 이미지 — ss 배로 그린 뒤 LANCZOS 축소한다.

    모서리 곡선은 등배로 그리면 소형에서 계단이 남는다. 보드의 16/24/32px 견본과
    .ico 가 같은 이 함수를 쓴다(견본이 실제 산출물과
    다른 파이프라인으로 그려지면 「16px에서도 선명하다」는 주장이 자기 증명이 된다).
    """
    x0, y0, x1, y1 = MARK_BBOX
    w, h = x1 - x0, y1 - y0
    scale = width * ss / w
    image = Image.new("RGBA", (round(w * scale), round(h * scale)), (0, 0, 0, 0))
    draw_mark(ImageDraw.Draw(image), (-x0 * scale, -y0 * scale), scale=scale, color=color)
    return image.resize((width, round(width * h / w)), Image.LANCZOS)


def ico_frame(size: int, ss: int = 8) -> Image.Image:
    """`size`×`size` 캔버스에 마크를 94% 폭으로 중앙 배치한 프레임 — .ico 의 실제 픽셀.

    보드의 16/24/32px 견본이 이 함수를 그대로 쓴다: `mark_image(px)` 는 타이트 bbox 를
    `px` 폭으로 그리는데, 출하 자산은 여백을 품는다(SVG 64 viewBox 안 56 폭 = 87.5%,
    ICO 는 94%) — 견본이 여백 없는 확대판이면 소형 판독성 주장이 실물보다 후해진다.
    """
    x0, y0, x1, y1 = MARK_BBOX
    mark_w = x1 - x0
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    canvas = size * ss
    image = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    scale = canvas * 0.94 / mark_w
    draw_mark(ImageDraw.Draw(image), (canvas / 2 - cx * scale, canvas / 2 - cy * scale),
              scale=scale)
    return image.resize((size, size), Image.LANCZOS)


def rounded_panel(draw: ImageDraw.ImageDraw, box, radius=28, fill=PANEL):
    draw.rounded_rectangle(box, radius=radius, fill=fill)


def render_mark() -> None:
    image = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    mark = mark_image(448)                    # 512 캔버스 안 여백 32px
    image.paste(mark, (32, (512 - mark.height) // 2), mark)
    image.save(OUT / "document-narmi-mark-final.png")


def render_board() -> None:
    image = Image.new("RGB", (1440, 980), CANVAS)
    draw = ImageDraw.Draw(image)

    draw.text((96, 76), "문서나르미 · FLOW SHEETS", fill=INK, font=font(24, bold=True))
    draw.text(
        (96, 121),
        "세 열린 문서 면이 오른쪽 위로 흐르며 원본에서 결과물까지 이어집니다.",
        fill=MUTED,
        font=font(17),
    )

    rounded_panel(draw, (96, 194, 1344, 520))
    hero = mark_image(123)
    image.paste(hero, (180, 285), hero)
    draw.text((342, 305), "문서나르미", fill=INK, font=font(72, bold=True))
    draw.text((345, 410), "HWPX 문서 자동화", fill=MUTED, font=font(18))

    rounded_panel(draw, (96, 552, 704, 882))
    draw.text((144, 590), "SMALL SIZE", fill=INK, font=font(20, bold=True))
    draw.text((144, 630), "세 면의 색과 사선 외곽은 16 px에서도 구분됩니다.", fill=MUTED, font=font(15))
    # 출하 .ico 프레임 그대로 — 캔버스 여백까지 포함해야 소형 판독성 주장이 실물 증명이
    # 된다(타이트 bbox 확대판은 16px 사용 시 실제보다 큰 마크를 보여 준다 — 리뷰 1R P2).
    for px, x in ((32, 150), (24, 275), (16, 393)):
        sample = ico_frame(px)
        image.paste(sample, (x, 740 - sample.height), sample)
        draw.text((x, 771), f"{px} px", fill="#98A2B3", font=font(14))

    rounded_panel(draw, (736, 552, 1344, 882), fill=DEEP_BLUE)
    draw.text((784, 590), "TONAL REVERSED", fill="white", font=font(20, bold=True))
    draw.text((784, 630), "어두운 면에서는 겹침을 살리는 밝은 세 톤으로 반전합니다.",
              fill="#DCEBFA", font=font(15))
    reversed_mark = mark_image(70, color=REVERSED_COLORS)
    image.paste(reversed_mark, (800, 700), reversed_mark)
    draw.text((900, 704), "문서나르미", fill="white", font=font(42, bold=True))

    draw.ellipse((102, 918, 124, 940), fill=DEEP_BLUE)
    draw.text((137, 914), "Deep Blue  #0E3FAE", fill="#475467", font=font(16))
    draw.ellipse((336, 918, 358, 940), fill=BLUE)
    draw.text((371, 914), "Flow Blue  #1857D8", fill="#475467", font=font(16))
    draw.ellipse((582, 918, 604, 940), fill=MINT)
    draw.text((617, 914), "Result Mint  #43C9A8", fill="#475467", font=font(16))

    image.save(OUT / "document-narmi-final-board.png")


def render_ico() -> None:
    """packaging/hwpx-filler.ico — 실행 파일·설치 마법사 아이콘(#258).

    각 크기를 8배 슈퍼샘플로 그린 뒤 LANCZOS 축소해 앨리어싱을 죽인다. 프레임 기하
    (94% 채움·중앙 배치)는 :func:`ico_frame` 단일 출처 — 보드 소형 견본과 같은 픽셀이다
    (소형에서도 세 문서 면의 사선과 어긋남이 식별되는 여백 — 완료 조건 16/24/32px).
    """
    sizes = (16, 24, 32, 48, 64, 128, 256)
    frames = [ico_frame(size) for size in sizes]
    frames[-1].save(
        ROOT / "packaging" / "hwpx-filler.ico",
        format="ICO",
        sizes=[(s, s) for s in sizes],
        append_images=frames[:-1],
    )


# 게이트(test_branding)가 대조하는 비트맵 산출물 — 렌더 로직이 바뀌었는데 생성기를 안
# 돌리면 커밋된 .png/.ico 가 낡은 형상인 채 조용히 남는다(심벌 v2 때 실제로 갈린 결함류).
# 픽셀을 게이트에서 재생성할 수 없으므로(Pillow 는 프로젝트 의존성이 아님), 생성 시점의
# **이 파일 소스 전체** 다이제스트와 산출물 해시를 매니페스트로 함께 커밋하고 게이트가
# 양쪽을 대조한다(리뷰 2R·3R P2 — 기하 상수만 재면 0.94 채움·색·보드 배치 같은 렌더
# 레시피 드리프트가 샌다). 소스가 한 글자라도 바뀌면 재실행이 곧 규율이다.
MANIFEST = OUT / "branding-manifest.json"
BITMAP_ARTIFACTS = (
    OUT / "document-narmi-mark-final.png",
    OUT / "document-narmi-final-board.png",
    ROOT / "packaging" / "hwpx-filler.ico",
)


def generator_digest() -> str:
    # read_text 의 유니버설 뉴라인이 CRLF 를 \n 으로 접는다 — 게이트(_read)와 같은 정규화.
    source = Path(__file__).read_text(encoding="utf-8")
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def write_manifest() -> None:
    manifest = {
        "generator_sha256": generator_digest(),
        "files": {
            p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in BITMAP_ARTIFACTS
        },
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    render_mark()
    render_board()
    render_ico()
    write_manifest()
