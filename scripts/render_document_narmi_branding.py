"""문서나르미 브랜딩 자산 렌더(#258) — 심벌 PNG·파이널 보드·실행 파일 .ico.

**정본은 docs/branding 의 SVG 파일이고 이 스크립트는 그것을 그대로 래스터한다.**
이전 판은 SVG 좌표를 ``STROKES`` 상수에 손으로 복제해 Pillow 원시도형으로 다시 그렸다.
심벌이 폴리라인 세 개이던 시절엔 가능했지만, 손글씨에서 온 3단 심벌은 원시도형으로
재작도할 수 없고 무엇보다 **재작도 자체가 드리프트의 원인**이었다(생성기와 화면이
각자 좌표를 들고 갈렸다). 이제 화면·파비콘·exe 아이콘이 모두 같은 파일에서 나온다.

크기 3단 — 한 그림으로 16~256px 을 덮을 수 없어 프레임마다 다른 정본을 쓴다.
ICO 는 원래 프레임별로 다른 그림을 담으라고 있는 포맷이다.

    16·24px → mark-micro    (화살표를 빼고 면을 굵힌 축약형)
    32px    → mark-small    (세 면 + I-빔 + 화살표)
    48px 이상 → mark-full   (얼굴·본문 줄·접힘·속도선까지)

래스터는 **목표 크기에서 네이티브로** 그린다. 크게 그려 축소하면 브라우저가 실제로
그리는 픽셀과 달라져, 16px 판독성 판정이 출하물과 다른 그림을 근거로 서게 된다.

Pillow·Playwright 는 프로젝트 런타임 의존성이 아니다 — 산출물(.png/.ico)을 커밋하는
dev 전용 생성기라 재생성 시에만 얹어 돌린다(Chrome 은 설치본을 쓴다):

    uv run --with playwright --with pillow python scripts/render_document_narmi_branding.py
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "branding"
DEEP_BLUE = "#0E3FAE"
BLUE = "#1857D8"
MINT = "#43C9A8"
BRAND_COLORS = (DEEP_BLUE, BLUE, MINT)
INK = "#111827"
MUTED = "#667085"
PANEL = "#FFFFFF"
CANVAS = "#F4F6F9"
FONT_REGULAR = Path(r"C:\Windows\Fonts\malgun.ttf")
FONT_BOLD = Path(r"C:\Windows\Fonts\malgunbd.ttf")

#: 정본 SVG — 이 이름들이 브랜딩의 단일 출처다.
MARK_MICRO = "document-narmi-mark-micro"
MARK_SMALL = "document-narmi-mark-small"
MARK_FULL = "document-narmi-mark-full"
LOCKUP = "document-narmi-lockup"

#: ICO 프레임 → 정본. 담당 크기 밖의 그림을 쓰면 소형에서 뭉개지거나 대형에서 앙상하다.
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)

#: 프레임 안에서 마크가 차지하는 폭 — 나머지는 여백이다. 작업표시줄·탐색기는 아이콘을
#: 꽉 채우지 않는 것을 전제로 배치하므로 여백 없이 그리면 이웃 아이콘보다 크게 보인다.
ICO_FILL = 0.94


def tier_for(size: int) -> str:
    """`size` px 프레임이 쓸 정본 이름."""
    if size <= 24:
        return MARK_MICRO
    if size <= 32:
        return MARK_SMALL
    return MARK_FULL


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_BOLD if bold else FONT_REGULAR), size)


def svg_text(stem: str) -> str:
    return (OUT / f"{stem}.svg").read_text(encoding="utf-8")


class Renderer:
    """설치된 Chrome 으로 SVG 를 래스터한다."""

    def __init__(self, page, tmp: Path):
        self.page = page
        self.tmp = tmp
        self._boxes: dict[str, tuple[float, float, float, float]] = {}

    def _shoot(self, svg: str, width: int, height: int) -> Image.Image:
        self.page.set_viewport_size({"width": max(width, 8), "height": max(height, 8)})
        self.page.set_content(
            '<html><body style="margin:0;background:transparent">'
            f'<div id="p" style="width:{width}px;height:{height}px">{svg}</div>'
            "</body></html>"
        )
        self.page.locator("#p").screenshot(path=str(self.tmp), omit_background=True)
        return Image.open(self.tmp).convert("RGBA").copy()

    def tight_box(self, stem: str) -> tuple[float, float, float, float]:
        """정본의 실제 잉크 범위를 viewBox 유저 단위로 — 획 두께까지 포함해 잰다.

        ``getBBox()`` 는 획을 빼고 재므로 굵은 획이 프레임 밖으로 새어 잘린다.
        큰 캔버스에 한 번 그려 알파 채널로 재면 획·라운드 캡·겹침이 전부 반영된다.
        이 측정은 배치용이고 출하 픽셀은 :meth:`square` 가 목표 크기에서 다시 그린다.
        """
        if stem in self._boxes:
            return self._boxes[stem]
        probe = 512
        vx, vy, vw, vh = self.viewbox(stem)
        image = self._shoot(svg_text(stem), probe, round(probe * vh / vw))
        box = image.getbbox()
        assert box, f"{stem}: 빈 렌더"
        scale = vw / probe
        self._boxes[stem] = (
            vx + box[0] * scale, vy + box[1] * scale,
            (box[2] - box[0]) * scale, (box[3] - box[1]) * scale,
        )
        return self._boxes[stem]

    @staticmethod
    def viewbox(stem: str) -> tuple[float, float, float, float]:
        raw = svg_text(stem).split('viewBox="', 1)[1].split('"', 1)[0]
        x, y, w, h = (float(v) for v in raw.replace(",", " ").split())
        return x, y, w, h

    def square(self, stem: str, size: int, fill: float = ICO_FILL) -> Image.Image:
        """`size`×`size` 프레임에 마크를 `fill` 비율로 중앙 배치해 **네이티브로** 그린다.

        viewBox 를 다시 계산해 브라우저에 넘기므로 확대·축소가 개입하지 않는다.
        """
        bx, by, bw, bh = self.tight_box(stem)
        side = max(bw, bh) / fill
        cx, cy = bx + bw / 2, by + bh / 2
        vb = f"{cx - side / 2:.4f} {cy - side / 2:.4f} {side:.4f} {side:.4f}"
        return self._shoot(_with_viewbox(svg_text(stem), vb), size, size)

    def wide(self, stem: str, height: int) -> Image.Image:
        """가로형(락업·워드마크)을 높이 기준으로 그린다 — 잉크 범위에 맞춰 자른다."""
        bx, by, bw, bh = self.tight_box(stem)
        vb = f"{bx:.4f} {by:.4f} {bw:.4f} {bh:.4f}"
        width = round(height * bw / bh)
        return self._shoot(_with_viewbox(svg_text(stem), vb), width, height)


def _with_viewbox(svg: str, viewbox: str) -> str:
    """루트 SVG 의 viewBox 를 갈아끼운다 — 원본 파일은 건드리지 않는다."""
    head, rest = svg.split('viewBox="', 1)
    _old, tail = rest.split('"', 1)
    return f'{head}viewBox="{viewbox}"{tail}'


def render_mark(r: Renderer) -> None:
    """대표 심벌 PNG — 문서·README 가 쓰는 256px 풀 디테일."""
    r.square(MARK_FULL, 256, fill=0.92).save(OUT / f"{MARK_FULL}.png")


def rounded_panel(draw: ImageDraw.ImageDraw, box, radius=28, fill=PANEL):
    draw.rounded_rectangle(box, radius=radius, fill=fill)


def render_board(r: Renderer) -> None:
    """브랜드 보드 — 락업·3단 매핑·반전·팔레트를 한 장에 싣는다."""
    image = Image.new("RGB", (1440, 1020), CANVAS)
    draw = ImageDraw.Draw(image)

    draw.text((96, 76), "문서나르미", fill=INK, font=font(24, bold=True))
    draw.text((96, 121), "세 문서 면이 오른쪽 위로 흐르며 원본에서 결과물까지 이어집니다.",
              fill=MUTED, font=font(17))

    rounded_panel(draw, (96, 194, 1344, 520))
    hero = r.wide(LOCKUP, 132)
    image.paste(hero, (180, 285), hero)
    draw.text((184, 452), "HWPX 문서 자동화", fill=MUTED, font=font(18))

    # 크기 3단 — **출하 .ico 프레임 그대로** 붙인다. 견본을 따로 그리면 「16px에서도
    # 읽힌다」는 주장이 실물이 아니라 견본을 근거로 서게 된다(리뷰 1R P2).
    rounded_panel(draw, (96, 552, 704, 922))
    draw.text((144, 590), "SIZE TIERS", fill=INK, font=font(20, bold=True))
    draw.text((144, 630), "프레임마다 다른 정본을 싣는다 — 한 그림은 16px 을 못 버틴다.",
              fill=MUTED, font=font(15))
    for px, x in ((16, 150), (24, 250), (32, 370), (48, 500)):
        sample = r.square(tier_for(px), px)
        image.paste(sample, (x, 780 - sample.height), sample)
        draw.text((x, 800), f"{px} px", fill="#98A2B3", font=font(14))
        draw.text((x, 826), tier_for(px).rsplit("-", 1)[1], fill="#B4BCC8", font=font(13))

    rounded_panel(draw, (736, 552, 1344, 922), fill=DEEP_BLUE)
    draw.text((784, 590), "TONAL REVERSED", fill="white", font=font(20, bold=True))
    draw.text((784, 630), "어두운 면에서는 겹침을 살리는 밝은 세 톤으로 반전합니다.",
              fill="#DCEBFA", font=font(15))
    for px, x in ((24, 800), (32, 900), (64, 1010)):
        stem = f"{tier_for(px)}-reversed"
        sample = r.square(stem, px)
        image.paste(sample, (x, 790 - sample.height), sample)
        draw.text((x, 810), f"{px} px", fill="#9FC0F5", font=font(14))
    draw.text((1130, 742), "문서나르미", fill="white", font=font(36, bold=True))

    for x, color, label in ((102, DEEP_BLUE, "Deep Blue  #0E3FAE"),
                            (336, BLUE, "Flow Blue  #1857D8"),
                            (582, MINT, "Result Mint  #43C9A8")):
        draw.ellipse((x, 958, x + 22, 980), fill=color)
        draw.text((x + 35, 954), label, fill="#475467", font=font(16))

    image.save(OUT / "document-narmi-board.png")


def render_ico(r: Renderer) -> None:
    """packaging/hwpx-filler.ico — 실행 파일·설치 마법사 아이콘(#258).

    프레임마다 담당 정본이 다르다(:func:`tier_for`). 같은 그림을 축소해 채우면
    16·24px 에서 세 면이 한 덩어리로 녹는다 — 3단으로 가른 이유가 그것이다.
    """
    frames = [r.square(tier_for(size), size) for size in ICO_SIZES]
    frames[-1].save(
        ROOT / "packaging" / "hwpx-filler.ico",
        format="ICO",
        sizes=[(s, s) for s in ICO_SIZES],
        append_images=frames[:-1],
    )


# 게이트(test_branding)가 대조하는 비트맵 산출물 — 렌더 로직이 바뀌었는데 생성기를 안
# 돌리면 커밋된 .png/.ico 가 낡은 형상인 채 조용히 남는다(심벌 v2 때 실제로 갈린 결함류).
# 픽셀을 게이트에서 재생성할 수 없으므로(Pillow·Playwright 는 런타임 의존성이 아님),
# 생성 시점의 **이 파일 소스 전체** 다이제스트와 산출물 해시를 매니페스트로 함께 커밋하고
# 게이트가 양쪽을 대조한다. 소스가 한 글자라도 바뀌면 재실행이 곧 규율이다.
MANIFEST = OUT / "branding-manifest.json"
BITMAP_ARTIFACTS = (
    OUT / f"{MARK_FULL}.png",
    OUT / "document-narmi-board.png",
    ROOT / "packaging" / "hwpx-filler.ico",
)

#: 생성기가 읽는 정본 SVG — 비트맵의 **입력**이다. 렌더 기하가 이 스크립트에서 SVG 로
#: 옮겨간 순간, 스크립트 다이제스트만으로는 입력 변경을 못 본다: 정본 SVG 를 고치고
#: 생성기를 안 돌리면 커밋된 .png/.ico 가 낡은 채 게이트가 초록이다. 그래서 입력 해시도
#: 함께 싣는다(#453 P2). 워드마크는 여기 없다 — 락업 SVG 안에 이미 패스로 박혀 있어
#: 생성기가 파일로 읽지 않는다.
SVG_INPUTS = tuple(
    OUT / f"{stem}.svg"
    for stem in (
        MARK_MICRO, f"{MARK_MICRO}-reversed",
        MARK_SMALL, f"{MARK_SMALL}-reversed",
        MARK_FULL, f"{MARK_FULL}-reversed",
        LOCKUP,
    )
)


def generator_digest() -> str:
    # read_text 의 유니버설 뉴라인이 CRLF 를 \n 으로 접는다 — 게이트(_read)와 같은 정규화.
    source = Path(__file__).read_text(encoding="utf-8")
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _text_digests(paths) -> dict[str, str]:
    """텍스트 입력은 **개행을 정규화해서** 잰다.

    SVG 를 바이트로 재면 CRLF 로 체크아웃되는 Windows 작업본과 LF 인 Linux CI 가 갈려
    아무도 손대지 않아도 게이트가 빨개진다. ``read_text`` 의 유니버설 뉴라인이 CRLF 를
    ``\\n`` 으로 접는다 — :func:`generator_digest` 와 게이트(``_read``)가 쓰는 같은 정규화다.
    """
    return {
        p.relative_to(ROOT).as_posix():
            hashlib.sha256(p.read_text(encoding="utf-8").encode("utf-8")).hexdigest()
        for p in paths
    }


def _binary_digests(paths) -> dict[str, str]:
    return {
        p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in paths
    }


def write_manifest() -> None:
    manifest = {
        "generator_sha256": generator_digest(),
        "inputs": _text_digests(SVG_INPUTS),
        "files": _binary_digests(BITMAP_ARTIFACTS),
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = OUT / "_render_tmp.png"
    with sync_playwright() as play:
        browser = play.chromium.launch(channel="chrome")
        page = browser.new_page(device_scale_factor=1)
        renderer = Renderer(page, tmp)
        render_mark(renderer)
        render_board(renderer)
        render_ico(renderer)
        browser.close()
    tmp.unlink(missing_ok=True)
    write_manifest()
