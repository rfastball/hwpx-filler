"""제품 브랜딩 가드(#258) — 사용자 노출 제품명 = 문서나르미, 기술 식별자 = hwpx-filler.

두 이름의 국경을 정적으로 못박는다: 사용자 표면(셸 타이틀·창 제목·exe 메타데이터·설치
마법사 표기)에는 문서나르미만, 업그레이드·릴리스 연속성이 걸린 식별자(설치 폴더·산출
파일명·release.yml 이 수집하는 Setup 이름)에는 hwpx-filler 계열만. 어느 쪽으로든
새는 개명은 여기서 잡힌다. 파일 텍스트 기반이라 gui extra 없이 돈다.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PRODUCT = "문서나르미"


def _read(*parts: str) -> str:
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


def test_web_shell_shows_product_name_only() -> None:
    """셸 타이틀·레일 락업이 문서나르미이고 옛 표기(HWPX Filler)가 남지 않는다."""
    html = _read("web", "index.html")
    assert f"<title>{PRODUCT}</title>" in html
    assert 'class="brand-mark"' in html, "레일 락업에 심벌 SVG 가 없다"
    # 세 면은 class 가 아니라 **자기 색**으로 센다. path 에 class 를 달면 규칙이 한 줄도
    # 없는 고아가 되고(test_web_css_orphan_classes), 원본 SVG 와 마크업도 갈린다.
    mark = html.split('class="brand-mark"', 1)[1].split("</svg>", 1)[0]
    assert mark.count("<path ") == 3, "락업 심벌이 세 면이 아니다"
    assert "class=" not in mark, "심벌 path 에 규칙 없는 class 가 붙었다"
    assert f'<span class="brand-name">{PRODUCT}</span>' in html
    assert "HWPX Filler" not in html


def test_window_title_is_product_name() -> None:
    """창 제목(파일 다이얼로그 소유주 FindWindowW 키와 동일 상수)이 제품명이다."""
    src = _read("src", "hwpxfiller", "webapp", "app.py")
    assert f'WINDOW_TITLE = "{PRODUCT}"' in src


def test_exe_metadata_product_name_but_stable_filenames() -> None:
    """exe 버전 리소스 ProductName 은 제품명, 파일명·internal_name 은 기술 식별자 유지."""
    src = _read("scripts", "generate_build_metadata.py")
    assert f'"product_name": "{PRODUCT}"' in src
    assert '"filename": "hwpx-filler-web.exe"' in src
    assert '"internal_name": "hwpx-filler-web"' in src


def test_installer_display_name_but_stable_identifiers() -> None:
    """설치 마법사 표기는 제품명, 설치 폴더·Setup 파일명은 불변(업그레이드·release.yml 계약)."""
    iss = _read("packaging", "installers", "hwpx-filler.iss")
    assert f'#define AppName "{PRODUCT}"' in iss
    assert r"DefaultDirName={localappdata}\Programs\HWPX Filler" in iss
    assert "OutputBaseFilename=HWPX-Filler-" in iss
    assert "SetupIconFile" in iss


def test_icon_is_multisize_ico_with_small_frames() -> None:
    """hwpx-filler.ico 가 16·24·32px 프레임을 포함한 멀티사이즈 ICO 다(완료 조건 소형 식별)."""
    raw = (ROOT / "packaging" / "hwpx-filler.ico").read_bytes()
    assert raw[:4] == b"\x00\x00\x01\x00", "ICO 헤더가 아니다"
    count = int.from_bytes(raw[4:6], "little")
    widths = {raw[6 + 16 * i] for i in range(count)}  # 엔트리 폭 바이트(0 = 256px)
    assert {16, 24, 32}.issubset(widths), f"소형 프레임 누락: {sorted(widths)}"
    assert 0 in widths, "256px 프레임 누락"


def test_spec_wires_icon() -> None:
    """filler 웹 spec 이 커밋된 아이콘을 exe 에 배선한다."""
    spec = _read("packaging", "hwpx_filler_web.spec")
    assert "hwpx-filler.ico" in spec
    assert "icon=icon_res" in spec


def test_brand_token_defined_and_fixed_logo_palette_shipped() -> None:
    """기존 브랜드 토큰은 세 테마에 남고, 새 다색 락업은 고정 제품색을 직접 싣는다."""
    tokens = _read("web", "css", "tokens.css")
    assert tokens.count("--a-brand:") == 3
    html = _read("web", "index.html")
    for color in ("#0E3FAE", "#1857D8", "#43C9A8"):
        assert f'stroke="{color}"' in html


def test_root_readme_is_product_entry() -> None:
    """루트 README = 문서나르미 제품 진입점(#259) — 제품명·로고·101 링크·파일명 계약.

    상대 링크(문서·이미지)는 실물 존재를 기계로 비준한다 — 링크 썩음이 조용히 남지 않게.
    """
    import re

    md = _read("README.md")
    assert f"# {PRODUCT}" in md, "제품명 헤딩이 없다"
    assert "document-narmi-mark-final.svg" in md, "로고(심벌)가 없다"
    assert "examples/quickstart-101/README.md" in md, "101 사용설명서 링크가 없다"
    assert "HWPX-Filler-*-Setup.exe" in md, "설치본 파일명 계약 표기가 없다"
    rels = set(re.findall(r"\]\(([^)#]+)\)", md)) | set(re.findall(r'src="([^"]+)"', md))
    for rel in rels:
        if rel.startswith(("http://", "https://", "../../")):
            continue  # 외부 URL·저장소 상대 GitHub 경로(releases)는 대상 밖
        assert (ROOT / rel).exists(), f"README 링크 썩음: {rel}"


def test_favicon_asset_bundled() -> None:
    """web/img 심벌 SVG(파비콘)가 세 색의 열린 문서 면을 담는다."""
    svg = _read("web", "img", "narmi-mark.svg")
    for color in ("#0E3FAE", "#1857D8", "#43C9A8"):
        assert f'stroke="{color}"' in svg
    assert svg.count("<path ") == 3
    assert "<rect " not in svg


def _generator_geometry() -> dict[str, object]:
    """render_document_narmi_branding.py 의 기하 상수 — ast 로 읽는다.

    import 하지 않는 이유: 그 스크립트는 Pillow(프로젝트 의존성 아님)를 최상단에서
    쓰는 dev 전용 생성기다. 숫자만 필요하므로 실행하지 않는다.
    """
    import ast

    src = _read("scripts", "render_document_narmi_branding.py")
    wanted = {"STROKES", "MARK_STROKE_WIDTH", "MARK_BBOX"}
    found: dict[str, object] = {}
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id in wanted:
                found[target.id] = ast.literal_eval(node.value)
    assert wanted <= set(found), f"생성기 기하 상수 누락: {sorted(wanted - set(found))}"
    return found


def _stroke_markup(stroke, color: str, width: int) -> str:
    """열린 문서 면 — 생성기 좌표로 SVG path 일부를 다시 만든다."""
    (x0, y0), *rest = stroke
    chunks = [f"M{x0} {y0}"]
    px, py = x0, y0
    for x, y in rest:
        if x == px:
            chunks.append(f"V{y}")
        elif y == py:
            chunks.append(f"H{x}")
        else:
            chunks.append(f"L{x} {y}")
        px, py = x, y
    return (
        f'd="{"".join(chunks)}" fill="none" stroke="{color}" '
        f'stroke-width="{width}"'
    )


def test_branding_generator_geometry_matches_shipped_symbol() -> None:
    """생성기 좌표 == SVG 정본 == 셸 마크업(#258).

    .png/.ico 는 커밋된 정적 자산이라 생성기가 옛 형상을 그대로 그려도 아무도 울지
    않는다 — 심벌 v2 때 실제로 갈렸다. 생성기·SVG·화면의 같은 면 좌표와 색을 묶어
    어느 한쪽만 낡은 로고를 쓰는 드리프트를 막는다.
    """
    geometry = _generator_geometry()
    colors = ("#0E3FAE", "#1857D8", "#43C9A8")
    strokes = list(zip(geometry["STROKES"], colors, strict=True))
    width = geometry["MARK_STROKE_WIDTH"]

    for parts in (("docs", "branding", "document-narmi-mark-final.svg"),
                  ("docs", "branding", "document-narmi-lockup-final.svg"),
                  ("docs", "branding", "document-narmi-final-board.svg"),
                  ("web", "img", "narmi-mark.svg"),
                  ("web", "index.html"),
                  ("docs", "UI_GALLERY.html")):
        text = _read(*parts)
        for stroke, color in strokes:
            markup = _stroke_markup(stroke, color, width)
            assert markup in text, f"{'/'.join(parts)} 가 생성기와 다른 심벌을 쓴다: {markup}"

    x0, y0, x1, y1 = geometry["MARK_BBOX"]
    radius = width / 2
    points = [point for stroke, _ in strokes for point in stroke]
    assert x0 == min(point[0] for point in points) - radius
    assert y0 == min(point[1] for point in points) - radius
    assert x1 == max(point[0] for point in points) + radius
    assert y1 == max(point[1] for point in points) + radius


def test_generated_bitmaps_match_generator_geometry() -> None:
    """커밋된 비트맵(.png/.ico)이 **현재 생성기가 만든 것**임을 매니페스트로 대조(리뷰 2R·3R P2).

    위 텍스트 게이트는 SVG/HTML 만 본다 — 렌더 로직을 바꾸고 생성기를 안 돌리면 exe·설치본이
    낡은 아이콘을 실은 채 게이트가 침묵한다. Pillow 없이 픽셀을 재생성할 수 없으므로
    생성기가 쓰는 매니페스트를 2면으로 대조한다: ①생성기 **소스 전체** 다이제스트 ↔
    매니페스트(재실행 누락 검출 — 기하 상수만 재면 0.94 채움·색·보드 배치 같은 렌더 레시피
    드리프트가 샌다, 3R 정정) ②커밋 파일 ↔ 매니페스트 해시(산출물만 손댄 드리프트 검출).
    어느 쪽이 갈려도 처방은 같다 — 생성기 재실행.
    """
    import hashlib
    import json

    manifest = json.loads(_read("docs", "branding", "branding-manifest.json"))
    source = _read("scripts", "render_document_narmi_branding.py")
    assert manifest["generator_sha256"] == hashlib.sha256(source.encode("utf-8")).hexdigest(), (
        "생성기 소스가 매니페스트와 다르다 — 생성기를 바꿨으면 "
        "render_document_narmi_branding.py 를 다시 돌려 비트맵·매니페스트를 함께 갱신하라"
    )
    files = manifest["files"]
    assert set(files) == {
        "docs/branding/document-narmi-mark-final.png",
        "docs/branding/document-narmi-final-board.png",
        "packaging/hwpx-filler.ico",
    }
    for rel, expected in files.items():
        actual = hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()
        assert actual == expected, f"{rel} 이 매니페스트와 다르다 — 생성기 재실행으로 함께 갱신하라"
