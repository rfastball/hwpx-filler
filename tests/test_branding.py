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


def test_brand_token_defined_in_both_themes_and_consumed() -> None:
    """--a-brand 가 라이트+다크(미디어·명시 2블록)에 선언되고 락업이 소비한다."""
    tokens = _read("web", "css", "tokens.css")
    assert tokens.count("--a-brand:") == 3
    app_css = _read("web", "css", "app.css")
    assert "var(--a-brand)" in app_css


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
    """web/img 심벌 SVG(파비콘)가 존재하고 브랜드 파랑 단색이다."""
    svg = _read("web", "img", "narmi-mark.svg")
    assert 'fill="#2874A6"' in svg
