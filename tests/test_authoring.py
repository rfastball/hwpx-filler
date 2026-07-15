"""저작 보조(토큰→누름틀 컴파일) 테스트 — 라운드트립·멱등·명시성·충실도.

핵심 증명: 작성자가 타이핑한 평문 ``{{X}}`` 를 컴파일하면 기존 파이프라인(schema 인식 +
fields 채우기)이 그대로 동작하고, 재컴파일은 무해(멱등)하다.
"""

from __future__ import annotations

from pathlib import Path

from lxml import etree

from hwpxfiller.core.authoring import compile_document, scan_tokens
from hwpxfiller.core.fields import FieldDocument
from hwpxcore.package import MIMETYPE_NAME, MIMETYPE_VALUE, HwpxPackage
from hwpxfiller.core.schema import extract_schema

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HS = "http://www.hancom.co.kr/hwpml/2011/section"
CORPUS = Path(__file__).parent / "corpus" / "real"
FRAG_CORPUS = Path(__file__).parent / "corpus" / "frag"


def _pkg(section_inner: str) -> HwpxPackage:
    sec = (
        f'<hs:sec xmlns:hs="{HS}" xmlns:hp="{HP}">{section_inner}</hs:sec>'
    ).encode("utf-8")
    pkg = HwpxPackage()
    pkg.entries[MIMETYPE_NAME] = MIMETYPE_VALUE
    pkg.stored.add(MIMETYPE_NAME)
    pkg.entries["Contents/section0.xml"] = sec
    return pkg


def _root(pkg: HwpxPackage) -> etree._Element:
    return etree.fromstring(pkg.entries["Contents/section0.xml"])


def _frag(name: str) -> str:
    return (FRAG_CORPUS / name).read_text(encoding="utf-8")


# --------------------------------------------------------------- 미리보기(scan)
def test_scan_is_readonly_and_lists_compilable():
    """scan 은 워크북을 변형하지 않고 컴파일 가능한 토큰을 나열한다(명시성: 미리보기)."""
    xml = '<hp:p><hp:run><hp:t>계약명: {{계약명}}</hp:t></hp:run></hp:p>'
    pkg = _pkg(xml)
    before = pkg.entries["Contents/section0.xml"]
    sites = scan_tokens(pkg)
    assert pkg.entries["Contents/section0.xml"] == before  # 무변형
    assert [(s.name, s.compilable) for s in sites] == [("계약명", True)]
    assert sites[0].context == "계약명: {{계약명}}"


# ------------------------------------------------------------- 컴파일 + 라운드트립
def test_compile_makes_token_a_real_field():
    """토큰이 진짜 누름틀이 되어 스키마가 인식한다."""
    xml = '<hp:p><hp:run><hp:t>{{공고명}}</hp:t></hp:run></hp:p>'
    pkg, report = compile_document(_pkg(xml))
    assert report.compiled == ["공고명"]
    assert report.modified is True
    assert extract_schema(pkg).field_names() == ["공고명"]


def test_roundtrip_compile_then_fill():
    """컴파일된 필드를 fields.set_field 로 채우면 값이 들어간다(전체 파이프라인)."""
    xml = '<hp:p><hp:run><hp:t>계약명: {{계약명}} / 예산 {{사업예산}}</hp:t></hp:run></hp:p>'
    pkg, report = compile_document(_pkg(xml))
    assert report.compiled == ["계약명", "사업예산"]

    doc = FieldDocument(pkg.entries["Contents/section0.xml"])
    assert doc.set_field("계약명", "정보시스템 구축") is True
    assert doc.set_field("사업예산", "1억원") is True
    filled = doc.to_bytes().decode("utf-8")
    assert "정보시스템 구축" in filled and "1억원" in filled


def test_surrounding_text_preserved():
    """토큰 전후 평문과 순서가 보존된다."""
    xml = '<hp:p><hp:run><hp:t>앞 {{계약명}} 뒤</hp:t></hp:run></hp:p>'
    pkg, _ = compile_document(_pkg(xml))
    # 문단 전체 텍스트(placeholder 유지)가 원문과 동일해야 한다.
    from hwpxcore.text_extract import extract_document, full_text

    assert full_text(extract_document(pkg)) == "앞 {{계약명}} 뒤"


# ------------------------------------------------------------------- 충실도
def test_generated_field_mirrors_corpus_attrs_and_links():
    """생성 누름틀은 실코퍼스 속성(type=CLICK_HERE 등) + begin/end id 링크를 갖는다."""
    xml = '<hp:p><hp:run charPrIDRef="7"><hp:t>{{계약명}}</hp:t></hp:run></hp:p>'
    pkg, _ = compile_document(_pkg(xml))
    root = _root(pkg)
    fb = root.find(f".//{{{HP}}}fieldBegin")
    fe = root.find(f".//{{{HP}}}fieldEnd")
    assert fb.get("type") == "CLICK_HERE"
    assert fb.get("name") == "계약명"
    assert fb.get("editable") == "1"
    # fieldEnd 가 fieldBegin 을 정확히 참조(id 링크 무결성).
    assert fe.get("beginIDRef") == fb.get("id")
    assert fe.get("fieldid") == fb.get("fieldid")
    # 생성 런들이 원본 서식(charPrIDRef)을 승계.
    for run in root.iter(f"{{{HP}}}run"):
        assert run.get("charPrIDRef") == "7"


def test_generated_ids_do_not_collide_with_existing():
    """id 는 기존 정수 id 최댓값 위에서 할당돼 충돌하지 않는다."""
    xml = (
        '<hp:p><hp:run charPrIDRef="1"><hp:t id="9000">{{계약명}}</hp:t></hp:run></hp:p>'
    )
    pkg, _ = compile_document(_pkg(xml))
    fb = _root(pkg).find(f".//{{{HP}}}fieldBegin")
    assert int(fb.get("id")) > 9000


# ------------------------------------------------------------------- 멱등성
def test_idempotent_recompile_noop():
    """이미 누름틀이 된 문서를 재컴파일하면 아무것도 바뀌지 않는다."""
    xml = '<hp:p><hp:run><hp:t>{{계약명}}</hp:t></hp:run></hp:p>'
    pkg, _ = compile_document(_pkg(xml))
    pkg2, report2 = compile_document(pkg)
    assert report2.compiled == []
    assert report2.modified is False


def test_token_already_in_field_not_recompiled():
    """이미 누름틀 값으로 든 ``{{X}}`` 는 이중 래핑하지 않는다(멱등의 핵심)."""
    xml = """
    <hp:p>
      <hp:run><hp:ctrl><hp:fieldBegin name="수요기관"/></hp:ctrl></hp:run>
      <hp:run><hp:t>{{수요기관}}</hp:t></hp:run>
      <hp:run><hp:ctrl><hp:fieldEnd/></hp:ctrl></hp:run>
    </hp:p>
    """
    assert scan_tokens(_pkg(xml)) == []  # 이미 field 영역 안 → 미리보기에 안 뜸
    _, report = compile_document(_pkg(xml))
    assert report.compiled == []


# ----------------------------------------------------- 못 바꾸는 토큰 시끄럽게 신고
def test_same_format_split_token_is_compiled_losslessly():
    """인접·동일 서식 런의 허위 파편은 논리적으로 접어 컴파일한다."""
    from hwpxcore.text_extract import extract_document, full_text

    xml = _frag("same_charpr_split.xml")
    pkg = _pkg(xml)
    before_text = full_text(extract_document(pkg))

    sites = scan_tokens(pkg)
    assert [(site.name, site.compilable) for site in sites] == [("계약명", True)]
    pkg, report = compile_document(pkg)

    assert report.compiled == ["계약명"]
    assert report.skipped == []
    assert full_text(extract_document(pkg)) == before_text
    assert extract_schema(pkg).field_names() == ["계약명"]


def test_fragment_compile_roundtrip_fill_and_idempotence():
    """파편 정규화 뒤에도 compile→fill 라운드트립과 재컴파일 멱등이 성립한다."""
    pkg, report = compile_document(_pkg(_frag("same_charpr_split.xml")))
    assert report.compiled == ["계약명"]
    compiled_bytes = pkg.entries["Contents/section0.xml"]

    _, second_report = compile_document(pkg)
    assert second_report.compiled == []
    assert second_report.modified is False
    assert pkg.entries["Contents/section0.xml"] == compiled_bytes

    doc = FieldDocument(compiled_bytes)
    assert doc.set_field("계약명", "정보시스템 구축") is True
    assert "앞 정보시스템 구축 뒤" in "".join(etree.fromstring(doc.to_bytes()).itertext())


def test_fragment_compile_preserves_each_source_run_attributes():
    """오프셋 역매핑은 charPr 외 런 속성도 원래 토큰 조각별로 보존한다."""
    xml = """
    <hp:p>
      <hp:run charPrIDRef="7" custom="left"><hp:t>{{계약</hp:t></hp:run>
      <hp:run charPrIDRef="7" custom="right"><hp:t>명}}</hp:t></hp:run>
    </hp:p>
    """
    pkg, report = compile_document(_pkg(xml))
    assert report.compiled == ["계약명"]
    value_runs = [
        run
        for run in _root(pkg).iter(f"{{{HP}}}run")
        if any(_local.tag == f"{{{HP}}}t" for _local in run)
    ]
    assert [(run.get("custom"), "".join(run.itertext())) for run in value_runs] == [
        ("left", "{{계약"),
        ("right", "명}}"),
    ]


def test_fragment_pathology_taxonomy_stays_loud():
    """구조/혼합서식 경계는 추측하지 않고 병리별 이유로 skip 한다."""
    expected = {
        "tab_inserted.xml": "탭/줄바꿈",
        "linebreak_inserted.xml": "탭/줄바꿈",
        "mixed_charpr.xml": "혼합 서식",
        "ctrl_between.xml": "제어 요소",
        "noncontiguous_run_boundary.xml": "비연속",
    }
    for fixture, reason in expected.items():
        pkg = _pkg(_frag(fixture))
        before = pkg.entries["Contents/section0.xml"]
        sites = scan_tokens(pkg)
        assert pkg.entries["Contents/section0.xml"] == before
        assert len(sites) == 1
        assert sites[0].compilable is False
        assert reason in sites[0].reason

        _, report = compile_document(pkg)
        assert report.compiled == []
        assert report.modified is False
        assert len(report.skipped) == 1
        assert reason in report.skipped[0].reason


# ------------------------------------------------- 복합 런 skip 축소 (#9)
def test_composite_multi_t_single_run_compiles_losslessly():
    """한 런에 여러 hp:t 로 쪼개진 토큰(복합 런)도 구간이 깨끗하면 무손실 컴파일한다."""
    from hwpxcore.text_extract import extract_document, full_text

    xml = (
        '<hp:p><hp:run charPrIDRef="7">'
        "<hp:t>{{계약</hp:t><hp:t>명}}</hp:t>"
        "</hp:run></hp:p>"
    )
    pkg = _pkg(xml)
    before = full_text(extract_document(pkg))

    sites = scan_tokens(pkg)
    assert [(s.name, s.compilable) for s in sites] == [("계약명", True)]

    pkg, report = compile_document(pkg)
    assert report.compiled == ["계약명"]
    assert report.skipped == []
    assert full_text(extract_document(pkg)) == before
    assert extract_schema(pkg).field_names() == ["계약명"]


def test_composite_preserves_trailing_control_outside_token():
    """토큰 바깥(뒤)의 제어 요소는 복합 컴파일 중에도 원형 보존된다."""
    from hwpxcore.text_extract import extract_document, full_text

    xml = (
        '<hp:p><hp:run charPrIDRef="7">'
        "<hp:t>{{계약명}}</hp:t>"
        '<hp:ctrl><hp:bookmark note="KEEP"/></hp:ctrl>'
        "</hp:run></hp:p>"
    )
    pkg = _pkg(xml)
    before = full_text(extract_document(pkg))

    pkg, report = compile_document(pkg)
    assert report.compiled == ["계약명"]
    out = pkg.entries["Contents/section0.xml"].decode("utf-8")
    assert 'note="KEEP"' in out  # 토큰 밖 구조 보존
    assert full_text(extract_document(pkg)) == before
    assert extract_schema(pkg).field_names() == ["계약명"]


def test_composite_preserves_inline_tab_outside_token():
    """토큰 뒤 인라인 탭·평문(같은 hp:t 안)이 복합 컴파일 중에도 보존된다."""
    from hwpxcore.text_extract import extract_document, full_text

    xml = (
        '<hp:p><hp:run charPrIDRef="7">'
        "<hp:t>{{계약명}}<hp:tab/>뒤</hp:t>"
        "</hp:run></hp:p>"
    )
    pkg = _pkg(xml)
    before = full_text(extract_document(pkg))

    pkg, report = compile_document(pkg)
    assert report.compiled == ["계약명"]
    out = pkg.entries["Contents/section0.xml"].decode("utf-8")
    assert "<hp:tab" in out  # 토큰 밖 탭 보존
    assert full_text(extract_document(pkg)) == before  # "{{계약명}}\t뒤"
    assert extract_schema(pkg).field_names() == ["계약명"]


def test_composite_compile_roundtrip_fill_and_idempotence():
    """복합 컴파일 뒤에도 compile→fill 라운드트립과 재컴파일 멱등이 성립한다."""
    xml = (
        '<hp:p><hp:run charPrIDRef="7">'
        "<hp:t>{{계약</hp:t><hp:t>명}}</hp:t>"
        '<hp:ctrl><hp:bookmark/></hp:ctrl>'
        "</hp:run></hp:p>"
    )
    pkg, report = compile_document(_pkg(xml))
    assert report.compiled == ["계약명"]
    compiled_bytes = pkg.entries["Contents/section0.xml"]

    _, second = compile_document(pkg)
    assert second.compiled == []
    assert second.modified is False
    assert pkg.entries["Contents/section0.xml"] == compiled_bytes  # 멱등

    doc = FieldDocument(compiled_bytes)
    assert doc.set_field("계약명", "정보시스템 구축") is True
    assert "정보시스템 구축" in "".join(etree.fromstring(doc.to_bytes()).itertext())


def test_composite_structure_inside_token_stays_loud():
    """복합 런이라도 토큰 **안**에 구조가 끼면 추측하지 않고 병리별로 skip 한다."""
    xml_tab = (
        '<hp:p><hp:run charPrIDRef="7"><hp:t>{{계약<hp:tab/>명}}</hp:t></hp:run></hp:p>'
    )
    xml_ctrl = (
        "<hp:p>"
        '<hp:run charPrIDRef="7"><hp:t>{{계약</hp:t></hp:run>'
        "<hp:run charPrIDRef=\"7\"><hp:ctrl><hp:bookmark/></hp:ctrl></hp:run>"
        '<hp:run charPrIDRef="7"><hp:t>명}}</hp:t></hp:run>'
        "</hp:p>"
    )
    for xml, reason in ((xml_tab, "탭/줄바꿈"), (xml_ctrl, "제어 요소")):
        pkg = _pkg(xml)
        before = pkg.entries["Contents/section0.xml"]
        sites = scan_tokens(pkg)
        assert pkg.entries["Contents/section0.xml"] == before  # 무변형
        assert len(sites) == 1 and sites[0].compilable is False
        assert reason in sites[0].reason

        _, report = compile_document(pkg)
        assert report.compiled == []
        assert report.modified is False
        assert len(report.skipped) == 1 and reason in report.skipped[0].reason


def test_composite_mixed_format_stays_skipped():
    """복합 런 확장이 혼합 서식(charPrIDRef 상이) 규칙을 느슨하게 만들지 않는다.

    값 서식 상속이 애매하므로 조용히 추측하지 않고 skip 유지(ROADMAP 원칙).
    """
    xml = (
        "<hp:p>"
        '<hp:run charPrIDRef="7"><hp:t>{{계약</hp:t></hp:run>'
        '<hp:run charPrIDRef="8"><hp:t>명}}</hp:t><hp:ctrl><hp:bookmark/></hp:ctrl></hp:run>'
        "</hp:p>"
    )
    pkg = _pkg(xml)
    before = pkg.entries["Contents/section0.xml"]
    _, report = compile_document(pkg)
    assert report.compiled == []
    assert report.modified is False
    assert len(report.skipped) == 1
    assert "혼합 서식" in report.skipped[0].reason
    assert pkg.entries["Contents/section0.xml"] == before  # 무변형


def test_composite_leading_run_level_tab_field_boundary_exact():
    """런의 첫 자식(hp:t 안이 아니라 런-레벨)이 탭인 경우에도 필드 경계가 정확하다.

    회귀: run_base 를 런의 실제 시작이 아니라 첫 hp:t 위치로 잡으면, 선행
    런-레벨 탭이 _clip_run 순회에서 이중 계산돼 한 칸 밀린다 — 탭이 필드값에
    삼켜지고 닫는 중괄호가 값 밖으로 샌다. full_text 비교는 경계-무관이라
    이 손상을 잡지 못하므로 set_field 라운드트립으로 직접 확인한다.
    """
    xml = (
        '<hp:p><hp:run charPrIDRef="7">'
        "<hp:tab/>"
        "<hp:t>{{계약명}}</hp:t>"
        "</hp:run></hp:p>"
    )
    pkg = _pkg(xml)
    pkg, report = compile_document(pkg)
    assert report.compiled == ["계약명"]

    doc = FieldDocument(pkg.entries["Contents/section0.xml"])
    assert doc.set_field("계약명", "정보시스템 구축") is True
    out = etree.fromstring(doc.to_bytes())
    filled = "".join(out.itertext())
    assert "정보시스템 구축" in filled
    assert "}" not in filled  # 닫는 중괄호가 값 밖으로 새면 안 된다
    assert out.find(f".//{{{HP}}}tab") is not None  # 선행 탭 보존


def test_composite_leading_text_preserved_and_field_created():
    """토큰 앞 평문 + 뒤 제어를 동시에 가진 복합 런에서 순서·필드가 모두 옳다."""
    from hwpxcore.text_extract import extract_document, full_text

    xml = (
        '<hp:p><hp:run charPrIDRef="7">'
        "<hp:t>계약: {{계약명}}</hp:t>"
        "<hp:ctrl><hp:bookmark/></hp:ctrl>"
        "</hp:run></hp:p>"
    )
    pkg = _pkg(xml)
    before = full_text(extract_document(pkg))
    pkg, report = compile_document(pkg)
    assert report.compiled == ["계약명"]
    assert full_text(extract_document(pkg)) == before  # "계약: {{계약명}}"
    assert extract_schema(pkg).field_names() == ["계약명"]


def test_dangling_open_brace_reported_not_silent():
    """미완결 여는 괄호({{ 만 있고 닫는 }} 없음)는 조용히 흘리지 않고 신고한다.

    Fix 1 회귀: 병합 경로가 완전 매치에만 신고를 걸어 미완결 {{ 가 조용히 사라졌다.
    """
    xml = '<hp:p><hp:run charPrIDRef="7"><hp:t>계약명 {{ 없음</hp:t></hp:run></hp:p>'
    pkg = _pkg(xml)
    before = pkg.entries["Contents/section0.xml"]
    sites = scan_tokens(pkg)
    assert pkg.entries["Contents/section0.xml"] == before  # 무변형
    assert len(sites) == 1
    assert sites[0].compilable is False
    assert "파편" in sites[0].reason

    _, report = compile_document(_pkg(xml))
    assert report.compiled == []
    assert len(report.skipped) == 1
    assert "파편" in report.skipped[0].reason


def test_empty_attr_run_preserved_through_merge():
    """길이 0 빈 런(속성 포함)이 인접 토큰 병합 중 삼켜지지 않고 보존된다.

    Fix 2 회귀: 슬라이스 재발행이 빈 슬라이스를 건너뛰어 속성 있는 빈 런이 사라졌다.
    """
    xml = (
        "<hp:p>"
        '<hp:run charPrIDRef="7" note="EMPTY_MARKER"><hp:t></hp:t></hp:run>'
        '<hp:run charPrIDRef="7"><hp:t>{{계약명}}</hp:t></hp:run>'
        "</hp:p>"
    )
    pkg, report = compile_document(_pkg(xml))
    assert report.compiled == ["계약명"]
    out = pkg.entries["Contents/section0.xml"].decode("utf-8")
    assert 'note="EMPTY_MARKER"' in out  # 소스 요소·속성 보존
    # 인접 토큰은 여전히 진짜 누름틀로 컴파일된다.
    assert extract_schema(pkg).field_names() == ["계약명"]


# ------------------------------------------------------------- 실제 코퍼스 멱등
def test_corpus_already_compiled_yields_no_new_fields():
    """실제 입찰공고(이미 누름틀 완비)를 스캔하면 새로 컴파일할 토큰이 없다."""
    path = CORPUS / "bid_notice_limited_under100m.hwpx"
    compilable = [s for s in scan_tokens(str(path)) if s.compilable]
    assert compilable == []


# ---------------------------------------------------- 컴파일본 옆저장(compile_to_sibling)
def test_compile_to_sibling_saves_next_to_original_and_keeps_original(tmp_path):
    """컴파일본을 <이름>.compiled.hwpx 로 저장하고 원본은 무변형(RC-28 코어 이관)."""
    from hwpxfiller.core.authoring import compile_to_sibling

    src = tmp_path / "tpl.hwpx"
    _pkg('<hp:p><hp:run><hp:t>{{계약명}}</hp:t></hp:run></hp:p>').save(str(src))
    before = src.read_bytes()

    compiled_path, report = compile_to_sibling(str(src))

    assert compiled_path == str(tmp_path / "tpl.compiled.hwpx")
    assert Path(compiled_path).exists()
    assert report.modified and report.compiled == ["계약명"]
    assert src.read_bytes() == before                        # 원본 무변형
    assert extract_schema(compiled_path).field_names() == ["계약명"]  # 진짜 누름틀


def test_compile_to_sibling_noop_writes_nothing(tmp_path):
    """바꿀 토큰이 없으면 (None, report) — 어떤 파일도 쓰지 않는다(조용한 산출물 금지)."""
    from hwpxfiller.core.authoring import compile_to_sibling

    src = tmp_path / "plain.hwpx"
    _pkg('<hp:p><hp:run><hp:t>토큰 없음</hp:t></hp:run></hp:p>').save(str(src))

    compiled_path, report = compile_to_sibling(str(src))

    assert compiled_path is None
    assert not report.modified
    assert sorted(p.name for p in tmp_path.iterdir()) == ["plain.hwpx"]  # 사이드카 없음


def test_compile_to_sibling_collision_is_loud_until_overwrite(tmp_path):
    """기존 컴파일본이 있으면 FileExistsError(경로 재진술) — overwrite 확정 시에만 덮는다(RC-02)."""
    import pytest

    from hwpxfiller.core.authoring import compile_to_sibling

    src = tmp_path / "tpl.hwpx"
    _pkg('<hp:p><hp:run><hp:t>{{계약명}}</hp:t></hp:run></hp:p>').save(str(src))
    sibling = tmp_path / "tpl.compiled.hwpx"
    sibling.write_bytes(b"human-edited")
    before = sibling.read_bytes()

    with pytest.raises(FileExistsError) as exc:
        compile_to_sibling(str(src))
    assert str(sibling) in str(exc.value)         # 충돌 경로 재진술
    assert sibling.read_bytes() == before          # 무변형(조용한 덮어쓰기 없음)

    compiled_path, report = compile_to_sibling(str(src), overwrite=True)
    assert compiled_path == str(sibling)
    assert report.modified
    assert sibling.read_bytes() != before          # 명시 확정 후에만 교체
