"""문서나르미 브랜딩 자산 렌더(#258) — 심벌 PNG·파이널 보드·실행 파일 .ico.

원본 기하는 docs/branding/document-narmi-mark-final.svg 와 같은 두 평면(mark_points).
Pillow 는 프로젝트 의존성이 아니다 — 산출물(.png/.ico)을 커밋하는 dev 전용 생성기라
재생성 시에만 임시로 얹어 돌린다:

    uv run --with pillow python scripts/render_document_narmi_branding.py
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "branding"
BLUE = "#2874A6"
INK = "#111827"
MUTED = "#667085"
PANEL = "#FFFFFF"
CANVAS = "#F4F6F9"
FONT_REGULAR = Path(r"C:\Windows\Fonts\malgun.ttf")
FONT_BOLD = Path(r"C:\Windows\Fonts\malgunbd.ttf")


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_BOLD if bold else FONT_REGULAR), size)


def mark_points(origin: tuple[float, float], scale: float = 1.0):
    ox, oy = origin

    def points(coords):
        return [(ox + x * scale, oy + y * scale) for x, y in coords]

    upper = points([(6, 14.5), (34.5, 8), (38, 10.8), (38, 23.5), (34.6, 27.7), (6, 34.5)])
    lower = points([(26, 38.5), (58, 30.5), (58, 48.7), (54.2, 51.6), (26, 43.8)])
    return upper, lower


def draw_mark(draw: ImageDraw.ImageDraw, origin, scale=1.0, color=BLUE):
    upper, lower = mark_points(origin, scale)
    draw.polygon(upper, fill=color)
    draw.polygon(lower, fill=color)


def rounded_panel(draw: ImageDraw.ImageDraw, box, radius=28, fill=PANEL):
    draw.rounded_rectangle(box, radius=radius, fill=fill)


def render_mark() -> None:
    image = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw_mark(draw, (0, 0), scale=8, color=BLUE)
    image.save(OUT / "document-narmi-mark-final.png")


def render_board() -> None:
    image = Image.new("RGB", (1440, 980), CANVAS)
    draw = ImageDraw.Draw(image)

    draw.text((96, 76), "문서나르미 · FINAL DIRECTION", fill=INK, font=font(24, bold=True))
    draw.text(
        (96, 121),
        "문서가 아니라, 문서가 완성되어 전달되는 움직임을 남겼습니다.",
        fill=MUTED,
        font=font(17),
    )

    rounded_panel(draw, (96, 194, 1344, 520))
    draw_mark(draw, (170, 270), scale=2.2)
    draw.text((342, 305), "문서나르미", fill=INK, font=font(72, bold=True))
    draw.text((345, 410), "HWPX 문서 자동화", fill=MUTED, font=font(18))

    rounded_panel(draw, (96, 552, 704, 882))
    draw.text((144, 590), "SMALL SIZE", fill=INK, font=font(20, bold=True))
    draw.text((144, 630), "두 면의 형태와 간격만 유지합니다.", fill=MUTED, font=font(15))
    draw_mark(draw, (136, 681), scale=0.75)
    draw.text((144, 778), "48 px", fill="#98A2B3", font=font(14))
    draw_mark(draw, (266, 689), scale=0.5)
    draw.text((270, 778), "32 px", fill="#98A2B3", font=font(14))
    draw_mark(draw, (391, 697), scale=0.25)
    draw.text((390, 778), "16 px", fill="#98A2B3", font=font(14))

    rounded_panel(draw, (736, 552, 1344, 882), fill=BLUE)
    draw.text((784, 590), "REVERSED", fill="white", font=font(20, bold=True))
    draw.text((784, 630), "강조 면에서는 흰색 단색으로 반전합니다.", fill="#DCEBFA", font=font(15))
    draw_mark(draw, (784, 681), scale=1.25, color="white")
    draw.text((900, 704), "문서나르미", fill="white", font=font(42, bold=True))

    draw.ellipse((102, 918, 124, 940), fill=BLUE)
    draw.text((137, 914), "Primary Blue  #2874A6", fill="#475467", font=font(16))
    draw.ellipse((354, 918, 376, 940), fill=INK)
    draw.text((389, 914), "Wordmark  #111827", fill="#475467", font=font(16))

    image.save(OUT / "document-narmi-final-board.png")


def render_ico() -> None:
    """packaging/hwpx-filler.ico — 실행 파일·설치 마법사 아이콘(#258).

    각 크기를 8배 슈퍼샘플로 그린 뒤 LANCZOS 축소해 앨리어싱을 죽인다. 마크 실측
    bbox(x 6–58, y 8–51.6)를 캔버스 중앙에 놓고 폭 기준 94% 로 채운다(소형에서도
    두 평면과 간격이 식별되는 여백 — 완료 조건 16/24/32px).
    """
    sizes = (16, 24, 32, 48, 64, 128, 256)
    frames = []
    for size in sizes:
        ss = 8
        canvas = size * ss
        image = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        scale = canvas * 0.94 / 52.0          # 마크 실폭 52 기준
        ox = canvas / 2 - 32.0 * scale        # bbox 중심 (32, 29.8)
        oy = canvas / 2 - 29.8 * scale
        draw_mark(draw, (ox, oy), scale=scale)
        frames.append(image.resize((size, size), Image.LANCZOS))
    frames[-1].save(
        ROOT / "packaging" / "hwpx-filler.ico",
        format="ICO",
        sizes=[(s, s) for s in sizes],
        append_images=frames[:-1],
    )


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    render_mark()
    render_board()
    render_ico()
