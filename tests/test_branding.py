"""제품 브랜딩 가드(#258) — 사용자 노출 제품명 = 문서나르미, 기술 식별자 = hwpx-filler.

두 이름의 국경을 정적으로 못박는다: 사용자 표면(셸 타이틀·창 제목·exe 메타데이터·설치
마법사 표기)에는 문서나르미만, 업그레이드·릴리스 연속성이 걸린 식별자(설치 폴더·산출
파일명·release.yml 이 수집하는 Setup 이름)에는 hwpx-filler 계열만. 어느 쪽으로든
새는 개명은 여기서 잡힌다. 파일 텍스트 기반이라 gui extra 없이 돈다.
"""
from __future__ import annotations

from _web_source import REPO_ROOT, source_text

ROOT = REPO_ROOT

PRODUCT = "문서나르미"


def _read(*parts: str) -> str:
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


#: 심벌 정본은 **크기 3단**이다 — 한 그림으로 16~256px 을 덮을 수 없어 프레임마다 다른
#: 파일을 싣는다. 어느 크기가 어느 단을 쓰는지는 생성기 ``tier_for`` 가 단일 출처이고,
#: 여기서는 파일 실재·짝·소비 사본 동일성만 잰다.
BRANDING = ("docs", "branding")
MARK_TIERS = ("micro", "small", "full")
RAIL_TIER = "micro"  # 레일 심벌은 24px — 축약형이 담당하는 크기다.


def mark_svg(tier: str, reversed_: bool = False) -> str:
    suffix = "-reversed" if reversed_ else ""
    return _read(*BRANDING, f"document-narmi-mark-{tier}{suffix}.svg")


def svg_paths(svg: str) -> list[str]:
    """SVG 의 ``<path …/>`` 열 — 형상을 통짜 문자열이 아니라 요소 단위로 센다."""
    import re

    return re.findall(r"<path\b[^>]*/>", svg)


def test_web_shell_shows_product_name_only() -> None:
    """셸 타이틀·레일 락업이 문서나르미이고 옛 표기(HWPX Filler)가 남지 않는다."""
    html = source_text("index.html")
    assert f"<title>{PRODUCT}</title>" in html
    assert 'class="brand-mark"' in html, "레일 락업에 심벌 SVG 가 없다"
    # 레일 심벌은 정본 파일의 path 열을 **그대로** 싣는다. 개수만 세면(옛 계약: 「세 면」)
    # 형상이 갈려도 초록이라, 화면과 exe 아이콘이 다른 로고를 쓰는 드리프트를 못 본다
    # — 심벌 v2 때 실제로 갈렸다. path 에 class 를 달면 규칙이 한 줄도 없는 고아가 된다
    # (test_web_css_orphan_classes).
    mark = html.split('class="brand-mark"', 1)[1].split("</svg>", 1)[0]
    canonical = svg_paths(mark_svg(RAIL_TIER))
    for path in canonical:
        assert path in mark, f"레일 심벌이 정본과 다르다: {path[:60]}…"
    assert len(svg_paths(mark)) == len(canonical), "레일 심벌에 정본에 없는 path 가 있다"
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
    """기존 브랜드 토큰은 세 테마에 남고, 다색 심벌은 고정 제품색을 직접 싣는다."""
    tokens = source_text("css", "tokens.css")
    assert tokens.count("--a-brand:") == 3
    html = source_text("index.html")
    # 속성 이름을 고정하지 않는다 — 축약형은 fill 로, 32px 판은 stroke 로 같은 색을 낸다.
    for color in ("#0E3FAE", "#1857D8", "#43C9A8"):
        assert color in html, f"레일 심벌에 제품색 {color} 이 없다"


def test_root_readme_is_product_entry() -> None:
    """루트 README = 문서나르미 제품 진입점(#259) — 제품명·로고·101 링크·파일명 계약.

    상대 링크(문서·이미지)는 실물 존재를 기계로 비준한다 — 링크 썩음이 조용히 남지 않게.
    """
    import re

    md = _read("README.md")
    assert f"# {PRODUCT}" in md, "제품명 헤딩이 없다"
    assert "document-narmi-mark-full.svg" in md, "로고(심벌)가 없다"
    assert "examples/quickstart-101/README.md" in md, "101 사용설명서 링크가 없다"
    assert "HWPX-Filler-*-Setup.exe" in md, "설치본 파일명 계약 표기가 없다"
    rels = set(re.findall(r"\]\(([^)#]+)\)", md)) | set(re.findall(r'src="([^"]+)"', md))
    for rel in rels:
        if rel.startswith(("http://", "https://", "../../")):
            continue  # 외부 URL·저장소 상대 GitHub 경로(releases)는 대상 밖
        assert (ROOT / rel).exists(), f"README 링크 썩음: {rel}"


def test_favicon_is_the_canonical_micro_mark() -> None:
    """파비콘은 정본 축약형의 사본이 아니라 **같은 바이트**다.

    사본이면 정본만 고쳤을 때 파비콘이 낡은 채 남는다 — 옛 계약은 「path 세 개·세 색」만
    세서 형상이 갈려도 초록이었다.
    """
    assert source_text("img", "narmi-mark.svg") == mark_svg(RAIL_TIER), (
        "파비콘이 정본 축약형과 다르다 — docs/branding 정본을 그대로 복사하라"
    )


def test_mark_tiers_pair_with_reversed_one_to_one() -> None:
    """3단 정본마다 반전판이 있고 **path 구성이 1:1** 이다.

    반전은 색만 다른 같은 그림이어야 한다. 인계 1라운드 반전판은 본문 줄 세 개를 통째로
    빠뜨린 채 왔다 — 개수가 갈리면 정본을 고칠 때 두 그림이 소리 없이 벌어진다.
    """
    for tier in MARK_TIERS:
        positive = svg_paths(mark_svg(tier))
        reverse = svg_paths(mark_svg(tier, reversed_=True))
        assert positive, f"{tier}: 정본이 비었다"
        assert len(positive) == len(reverse), (
            f"{tier}: 반전판 path {len(reverse)}개 != 정본 {len(positive)}개 — "
            "색만 다른 같은 그림이어야 한다"
        )


def test_micro_mark_paints_no_background() -> None:
    """축약형은 배경색을 칠하지 않는다 — 면 사이 틈은 도형을 깎아서 낸다.

    인계 2라운드는 뒤 면을 흰색으로 덮어 틈을 만들었다. 아이콘은 투명 배경으로 출하되고
    Windows 작업표시줄은 어두워서 그 칠이 흰 덩어리로 드러났다. 금지는 축약형 **정본**에만
    건다 — 반전판 앞면의 흰색과 32px 판 종이 안쪽의 흰색은 배경이 아니라 그림이다.
    """
    assert 'fill="#FFFFFF"' not in mark_svg("micro"), (
        "축약형이 흰색을 칠한다 — 어두운 표면에서 덩어리로 드러난다"
    )


def _generator_constants() -> dict[str, object]:
    """생성기의 정본 이름·프레임 상수 — ast 로 읽는다.

    import 하지 않는 이유: 그 스크립트는 Pillow·Playwright(둘 다 프로젝트 런타임 의존성이
    아니다)를 최상단에서 쓰는 dev 전용 생성기다. 이름만 필요하므로 실행하지 않는다.
    """
    import ast

    src = _read("scripts", "render_document_narmi_branding.py")
    wanted = {"MARK_MICRO", "MARK_SMALL", "MARK_FULL", "LOCKUP", "ICO_SIZES"}
    found: dict[str, object] = {}
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id in wanted:
                found[target.id] = ast.literal_eval(node.value)
    assert wanted <= set(found), f"생성기 상수 누락: {sorted(wanted - set(found))}"
    return found


def test_generator_consumes_the_canonical_svgs() -> None:
    """생성기가 부르는 정본이 실재하고 ICO 프레임이 3단을 다 덮는다.

    생성기는 좌표를 복제하지 않고 정본 SVG 를 읽어 래스터한다 — 옛 계약이 대조하던
    ``STROKES`` 상수는 그 복제본이었고, 복제 자체가 드리프트 원인이었다. 그래서 이제
    대조 대상은 좌표가 아니라 **이름과 크기 매핑**이다. 이름이 어긋나면 생성기는 실행 시점에
    죽지만 커밋된 비트맵은 낡은 채 남으므로 정적으로도 잰다.
    """
    constants = _generator_constants()
    for key in ("MARK_MICRO", "MARK_SMALL", "MARK_FULL", "LOCKUP"):
        stem = constants[key]
        assert ROOT.joinpath(*BRANDING, f"{stem}.svg").exists(), f"{key}={stem} 정본이 없다"
    sizes = set(constants["ICO_SIZES"])
    assert {16, 24, 32}.issubset(sizes), f"ICO 소형 프레임 누락: {sorted(sizes)}"
    assert max(sizes) == 256, "ICO 256px 프레임 누락"


def test_shell_and_gallery_carry_the_same_symbol() -> None:
    """셸과 디자인 갤러리가 같은 정본 심벌을 싣는다.

    갤러리는 실 CSS 를 링크해 현재 앱을 보여 주는 표면이라, 심벌만 낡으면 「지금 앱」을
    잘못 증언한다.
    """
    canonical = svg_paths(mark_svg(RAIL_TIER))
    for text, where in ((source_text("index.html"), "frontend/index.html"),
                        (_read("docs", "UI_GALLERY.html"), "docs/UI_GALLERY.html")):
        for path in canonical:
            assert path in text, f"{where} 가 정본과 다른 심벌을 쓴다: {path[:60]}…"


def test_generated_bitmaps_match_generator_source() -> None:
    """커밋된 비트맵(.png/.ico)이 **현재 생성기가 만든 것**임을 매니페스트로 대조(리뷰 2R·3R P2).

    위 텍스트 게이트는 SVG/HTML 만 본다 — 정본 SVG 를 고치고 생성기를 안 돌리면 exe·설치본이
    낡은 아이콘을 실은 채 게이트가 침묵한다. Pillow·Chrome 없이 픽셀을 재생성할 수 없으므로
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
        "docs/branding/document-narmi-mark-full.png",
        "docs/branding/document-narmi-board.png",
        "packaging/hwpx-filler.ico",
    }
    for rel, expected in files.items():
        actual = hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()
        assert actual == expected, f"{rel} 이 매니페스트와 다르다 — 생성기 재실행으로 함께 갱신하라"
