"""온보딩 예제 자산 계약 — `https://github.com/rfastball/hwpx-filler/blob/5f51e442dde87891b68fbbdc1519a04e01211b8e/docs/ONBOARDING_TUTORIAL.md` §2 의 검사 가능한 얼굴.

동결된 옛 생성 자산에 대해 지키는 것은 여섯이다. 새 매뉴얼 기반 자산의 시트 계약은 마지막 테스트가 검사한다.

1. **재생성 결정론** — `examples/onboarding/make_assets.py` 를 임시 폴더에 다시 돌리면
   커밋된 자산과 **bytes 가 같다**. 손편집이 끼면 여기서 갈라진다.
2. **CSV 스키마** — 헤더 8열이 §2.3 표와 정확히 일치하고(헤더 = 필드명 일치가 자동
   제안의 조건), 행 수와 **의도 결측의 자리**(계약목록_2 둘째 행의 `납품조건` 만 빈
   값)가 선언대로다.
3. **누름틀 필드 집합** — 컴파일된 두 템플릿의 필드가 스펙과 정확 일치(7/5).
4. **미컴파일 연습본** — `공고서_연습` 은 필드 토큰과 구간 표기를 **둘 다** 들고 있고,
   두 축 컴파일(필드 먼저·구간 다음)이 차단 사유 없이 성립한다. 이것이 고급·심화
   티어(T15·T17)의 재료가 실제로 서 있다는 증거다.
5. **값 유형 정합(§2.3, #915)** — 이름이 선언한 값 유형과 CSV 값이 어긋나지 않는다.
   어긋나면 관리 경로가 「먼저 데이터 문제를 확인하세요」로 막아, 커리큘럼에 없는
   데이터 게이트를 고급·심화 티어 사용자 전원이 만난다.
6. **허구화 규칙(§2.1)** — 원형 실문서의 식별 가능한 값이 자산 어디에도 없다.
"""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import shutil
import sys
import zipfile
from pathlib import Path

import pytest
from openpyxl import load_workbook

from hwpxfiller.application.field_binding_input import (
    LegacyFieldBindingEntry,
    prepare_legacy_field_binding_migration,
)
from hwpxfiller.domain.authoring import scan_structure
from hwpxfiller.domain.lint import similarity
from hwpxfiller.domain.mapping import SUGGEST_THRESHOLD
from hwpxfiller.domain.raw_data_record import SourceText
from hwpxfiller.domain.schema import extract_schema
from hwpxfiller.domain.text_render import template_fields
from hwpxfiller.external.hwpx_package_io import read_hwpx_package
from hwpxfiller.viewmodel.mapping_state import MappingModel
from hwpxfiller.external.template_inspection import (
    compile_structure_file,
    compile_template_file,
    inspect_hwpx_template,
    scan_template_tokens,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
ASSETS = REPO_ROOT / "examples" / "onboarding"
SCRIPT = ASSETS / "make_assets.py"
TUTORIAL_ASSETS = REPO_ROOT / "examples" / "tutorial"

#: §2.3 의 CSV 열 8개 — 순서까지 계약이다.
HEADER = [
    "공고번호",
    "수요기관",
    "품명",
    "사업명",
    "계약방법",
    "계약상대자",
    "계약금액",
    "납품조건",
]

#: 자산 census — 생성 스크립트가 낳는 파일 전부(결정론 비교의 대상 집합).
GENERATED = (
    "templates/계약체결안내.hwpx",
    "templates/구매추진안내.hwpx",
    "templates/공고서_연습.hwpx",
    "text_templates/계약안내_기안.txt",
    "text_templates/오류연습_보증금.txt",
    "data/계약목록.csv",
    "data/계약목록_2.csv",
)

CONTRACT_FIELDS = {
    "공고번호",
    "수요기관",
    "품명",
    "사업명",
    "계약상대자",
    "계약금액",
    "납품조건",
}
PURCHASE_FIELDS = {"공고번호", "수요기관", "품명", "계약방법", "납품조건"}
NOTICE_TOKENS = {"공고번호", "수요기관", "품명", "계약방법", "납품조건"}

#: §2.1 금지 목록의 대표 문자열 — 실기관·실업체·실인명·실번호·실연락처.
FORBIDDEN = (
    "조달청",
    "대전지방조달청",
    "나라장터",
    "루나이엔씨",
    "루나이앤씨",
    "육군군수사령부",
    "경제인문사회연구회",
    "방위사업청",
    "안준명",
    "황민오",
    "이순주",
    "조다래",
    "김성우",
    "korea.kr",
    "R26BK01666828",
    "25224100200",
)


def _load_script():
    """`make_assets.py` 를 경로로 적재한다(examples/ 는 패키지가 아니다)."""
    spec = importlib.util.spec_from_file_location("onboarding_make_assets", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _read_csv(path: Path) -> "tuple[list[str], list[list[str]]]":
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    return rows[0], rows[1:]


def _asset_texts() -> "dict[str, str]":
    """자산의 사람이 읽는 내용 전부 — hwpx 는 ZIP 엔트리를 전부 펼쳐 본다."""
    texts: dict[str, str] = {}
    for name in GENERATED:
        path = ASSETS / name
        if path.suffix == ".hwpx":
            with zipfile.ZipFile(path) as archive:
                for entry in archive.namelist():
                    blob = archive.read(entry)
                    texts[f"{name}!{entry}"] = blob.decode("utf-8", "ignore")
        else:
            texts[name] = path.read_text(encoding="utf-8-sig")
    texts["make_assets.py"] = SCRIPT.read_text(encoding="utf-8")
    return texts


# ------------------------------------------------------------------ 1. 결정론
def test_regeneration_reproduces_committed_bytes(tmp_path: Path) -> None:
    """임시 폴더 재생성 = 커밋 자산 bytes 동일 — 손편집이 끼면 여기서 갈라진다."""
    _load_script().main(tmp_path)

    regenerated = sorted(
        path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*") if path.is_file()
    )
    assert regenerated == sorted(GENERATED)

    for name in GENERATED:
        committed = (ASSETS / name).read_bytes()
        fresh = (tmp_path / name).read_bytes()
        assert hashlib.sha256(fresh).hexdigest() == hashlib.sha256(committed).hexdigest(), (
            f"{name}: 재생성 산출이 커밋 자산과 다르다 — 손편집이거나 스크립트가 비결정적이다"
        )


# ------------------------------------------------------------------ 2. CSV 스키마
@pytest.mark.parametrize(("name", "rows_n"), [("계약목록.csv", 3), ("계약목록_2.csv", 2)])
def test_csv_header_matches_field_names(name: str, rows_n: int) -> None:
    """헤더 8열 정확 일치(순서 포함) + 행 수 — 자동 제안이 서는 조건."""
    header, rows = _read_csv(ASSETS / "data" / name)
    assert header == HEADER
    assert len(rows) == rows_n
    assert all(len(row) == len(HEADER) for row in rows)


def test_only_the_declared_cell_is_missing() -> None:
    """결측은 한 자리뿐 — 계약목록_2 둘째 행의 `납품조건`(§2.2 데이터측 결핍)."""
    _, primary = _read_csv(ASSETS / "data" / "계약목록.csv")
    assert all(cell.strip() for row in primary for cell in row), "계약목록.csv 에는 결측이 없다"

    _, second = _read_csv(ASSETS / "data" / "계약목록_2.csv")
    blanks = {
        (index, HEADER[column])
        for index, row in enumerate(second)
        for column, cell in enumerate(row)
        if not cell.strip()
    }
    assert blanks == {(1, "납품조건")}


# ------------------------------------------------------------------ 3. 누름틀 필드
@pytest.mark.parametrize(
    ("name", "fields"),
    [("계약체결안내.hwpx", CONTRACT_FIELDS), ("구매추진안내.hwpx", PURCHASE_FIELDS)],
)
def test_compiled_templates_carry_the_declared_fields(name: str, fields: "set[str]") -> None:
    """컴파일된 두 템플릿의 필드 집합이 스펙과 정확 일치하고 CSV 열의 부분집합이다."""
    inspection = inspect_hwpx_template(str(ASSETS / "templates" / name))
    assert set(inspection.fields) == fields
    assert fields <= set(HEADER)
    assert inspection.status.stray_n == 0
    assert inspection.status.structure_marker_n == 0


# ------------------------------------------------- 4. 미컴파일 연습본(고급·심화 재료)
def test_practice_notice_reports_tokens_and_regions() -> None:
    """스캔이 미해결 필드 토큰과 구간 표기를 **둘 다** 보고한다(항목 1 · 그 안의 갈래 2).

    갈래를 둘 둔 것은 선택 정책이 Slot 당 `EXACTLY_ONE` 이기 때문이다 — 갈래 없는
    항목은 「고를 수 있는 것이 없는 항목」이라 넣고 빼는 연습이 서지 않는다.
    """
    path = ASSETS / "templates" / "공고서_연습.hwpx"

    assert {site.name for site in scan_template_tokens(str(path))} == NOTICE_TOKENS

    scan = scan_structure(read_hwpx_package(path))
    assert scan.diagnostics == ()
    assert (scan.summary.slots, scan.summary.options, scan.summary.fields) == (1, 2, 5)

    (slot,) = scan.slots
    assert slot.id == "현장설명회"
    assert [option.id for option in slot.options] == ["실시", "생략"]


def test_practice_notice_compiles_on_both_axes(tmp_path: Path) -> None:
    """필드 먼저 · 구간 다음의 두 축이 차단 사유 없이 성립한다(T15 의 재료)."""
    work = tmp_path / "공고서_연습.hwpx"
    shutil.copy(ASSETS / "templates" / "공고서_연습.hwpx", work)

    field_report = compile_template_file(str(work))
    assert field_report.modified is True
    assert field_report.skipped == []
    assert set(field_report.compiled) == NOTICE_TOKENS

    structure_report = compile_structure_file(str(work))
    assert structure_report.refusal is None
    assert structure_report.modified is True
    assert structure_report.options == 2

    assert scan_structure(read_hwpx_package(work)).summary.markers == 0


# ------------------------------------------------- 4-B. T14 비움 확정 게이트(#908)
def test_deposit_token_draws_no_suggestion_so_the_blank_gate_stands() -> None:
    """`계약보증금` 은 실 8열 어디에도 안 붙어 **무제안**으로 남고, 비움 확정이 선다.

    T14 의 전제는 '열이 없으면 묻는다'인데, 퍼지 임계 0.6 시절엔 `계약보증금` 이
    `계약금액` 을 0.6667 로 물어 **오답이 제안된 채** 게이트를 지났다(#908). 보증금
    자리의 계약금액은 법적 문서에서 위험한 초안이라 임계를 그 위로 올렸다.

    실자산으로 단언하는 이유는 이 결함이 합성 코퍼스가 아니라 실완주 게이트(#895)에서
    나왔기 때문이다 — 커밋된 TXT 와 CSV 를 그대로 읽어 그 경로를 되짚는다.
    """
    text = (ASSETS / "text_templates" / "오류연습_보증금.txt").read_text(encoding="utf-8")
    tokens = template_fields(text)
    assert "계약보증금" in tokens  # 자산이 결핍 재료를 실제로 들고 있다

    with (ASSETS / "data" / "계약목록.csv").open(encoding="utf-8-sig", newline="") as fh:
        headers = next(csv.reader(fh))
    assert headers == HEADER

    model = MappingModel.from_field_names(tokens, headers)
    by_field = {row.template_field: row for row in model.rows}

    # 정확 일치 토큰은 자동 결속·확정된다 — 결핍 자리의 대조군.
    assert by_field["공고번호"].source == "공고번호"
    assert by_field["계약상대자"].source == "계약상대자"
    assert sum(row.auto_confirmed_exact for row in model.rows) == 3

    # 결핍 자리: 결속도 제안도 없다. 특히 '계약금액' 이 밀려들지 않는다.
    deposit = by_field["계약보증금"]
    assert deposit.source == ""
    assert model.suggestions().get("계약보증금") is None
    assert similarity("계약보증금", "계약금액") < SUGGEST_THRESHOLD

    # 그래서 게이트가 선다 — 사람이 그 행에서 열을 고르거나 **빈 고정값**을 선언해야
    # 넘어간다. 일괄 승격(`confirm_suggested`)은 이 행을 건드리지 않는다(U6-C #977 —
    # 구 ADR-E 이름게이트의 후계: 확인의 자리가 모달에서 그 행으로 옮겨 왔다).
    assert deposit.status() == "needs_source"
    assert model.confirm_suggested() == 0 and deposit.is_declared_empty() is False
    assert not model.is_complete()
    index = model.index_of("계약보증금")
    model.set_display(index, "const", "")
    model.set_confirmed(index)
    assert deposit.is_declared_empty() is True
    assert model.is_complete()


# ------------------------------------------- 5. 값 정합은 사람 몫(#915 게이트 퇴역)
def _bound_source_keys(template: Path) -> "set[str]":
    """제품이 실제로 쓰는 사슬로 **결속된 소스 열**을 낸다.

    `infer_type`(이름 휴리스틱) → `MappingModel` 기본 유형 → 저장 매핑 → legacy migration
    후보 규칙. 종전에는 이 사슬의 마지막 단계가 열마다 `value_type` 을 선언했고 그것이
    데이터 값과 어긋나면 생성이 막혔다 — 값 유형 어휘 퇴역으로 그 축이 사라졌으므로
    남는 것은 「어떤 열이 문서로 흐르는가」다.
    """
    schema = extract_schema(read_hwpx_package(template))
    model = MappingModel.from_suggestions(schema, list(HEADER))
    draft = prepare_legacy_field_binding_migration(
        work_authority_id="onboarding",
        base_template_application_id="asset",
        legacy_entries=[
            LegacyFieldBindingEntry(
                row.template_field, row.type, row.source, row.const, row.fmt
            )
            for row in model.rows
        ],
        captured_at="2026-08-26T00:00:00Z",
    )
    assert all(
        not hasattr(candidate, "value_type") for candidate in draft.candidate_rules
    ), "migration 후보가 아직 값 유형을 선언한다(어휘 퇴역 위반)"
    return {
        candidate.source_key
        for candidate in draft.candidate_rules
        if candidate.source_key
    }


@pytest.fixture(scope="module")
def compiled_notice(tmp_path_factory) -> Path:
    """T15 가 만드는 것과 같은 **변환본** — 심화 티어가 실제로 생성에 쓰는 템플릿이다."""
    work = tmp_path_factory.mktemp("notice") / "공고서_연습.hwpx"
    shutil.copy(ASSETS / "templates" / "공고서_연습.hwpx", work)
    compile_template_file(str(work))
    compile_structure_file(str(work))
    return work


def test_every_template_field_accepts_every_committed_data_value(
    compiled_notice: Path,
) -> None:
    """동봉 3행이 **한 행도 빠지지 않고** 세 템플릿 전부를 통과한다(#915).

    종전 자산은 `납품기한` 이라는 **이름**이 날짜 유형을 선언했는데 값 2행이 자유서식
    (「계약 후 90일 이내」 — 원 공문의 실표현)이라, 관리 경로가 그 행들을 「먼저 데이터
    문제를 확인하세요」로 막았다. 커리큘럼에 없는 게이트를 고급·심화 티어 사용자 전원이
    만난 것이 #915 다. 그 게이트는 값 유형 어휘째 퇴역했다 — 소스 값은 언제나 타입 없는
    텍스트이고, 값이 맞는지는 사람이 본다. 여기서 재는 것은 결속된 열의 값이 **하나도
    남김없이** 문서 값으로 성립하는가다(빈/공백만 아니어야 한다 — 그 게이트는 존치).
    """
    _, rows = _read_csv(ASSETS / "data" / "계약목록.csv")
    records = [dict(zip(HEADER, row, strict=True)) for row in rows]

    for template in (
        ASSETS / "templates" / "계약체결안내.hwpx",
        ASSETS / "templates" / "구매추진안내.hwpx",
        compiled_notice,
    ):
        bound = _bound_source_keys(template)
        assert bound, f"{template.name}: 결속된 소스 열이 하나도 나오지 않았다"
        refused = [
            (index, key, record[key])
            for index, record in enumerate(records)
            for key in bound
            if SourceText(record[key]).text.strip() == ""
        ]
        assert refused == [], (
            f"{template.name}: 결속 열의 값이 빈/공백만이라 게이트가 선다 — {refused}"
        )


# ------------------------------------------------------------------ 6. 허구화 규칙
@pytest.mark.parametrize("needle", FORBIDDEN)
def test_no_real_world_identifier_survives_in_the_assets(needle: str) -> None:
    """원형 실문서의 식별 가능한 값이 자산 어디에도 없다(§2.1, 예외 없음)."""
    hits = [where for where, text in _asset_texts().items() if needle in text]
    assert hits == [], f"금지 문자열 「{needle}」 이 남아 있다: {hits}"


def test_shipped_manual_workbook_has_the_practice_rows_without_blanks() -> None:
    """새 튜토리얼의 시트·행과 별도 결측 연습본의 필요성을 원본으로 확인한다."""
    workbook = load_workbook(TUTORIAL_ASSETS / "공고목록.xlsx", read_only=True, data_only=True)
    try:
        assert workbook.sheetnames == ["공고", "계약"]
        for name, expected_rows in (("공고", 12), ("계약", 6)):
            rows = list(workbook[name].values)
            assert len(rows) == expected_rows + 1  # 헤더 한 행
            assert all(value is not None and str(value).strip() for row in rows for value in row)
    finally:
        workbook.close()


def test_practice_cleanup_preserves_changed_and_referenced_files(tmp_path: Path) -> None:
    """A fresh batch is independent; cleanup only removes intact, unreferenced copies."""
    from types import SimpleNamespace

    from hwpxfiller.external.tutorial_practice import PracticeFiles

    jobs = SimpleNamespace(list_jobs=lambda: [])
    practice = PracticeFiles(tmp_path / "templates", tmp_path / "home", jobs)
    first = practice.prepare()
    second = practice.prepare(derived="blank")
    assert practice.latest("공고목록.xlsx") == second["entries"][0]
    assert practice.latest("없는 예제.xlsx") is None
    assert {entry["name"] for entry in first["entries"]} == {
        "물품 구매입찰 공고.hwpx", "낙찰자 선정 및 계약체결 안내.txt",
        "계약방법 결정 및 구매추진 안내.txt", "공고목록.xlsx",
    }
    assert second["entries"][0]["path"] != first["entries"][-1]["path"]
    blank = load_workbook(second["entries"][0]["path"], read_only=True, data_only=True)
    try:
        assert blank["계약"]["K2"].value is None
    finally:
        blank.close()

    edited = Path(first["entries"][1]["path"])
    edited.write_text(edited.read_text(encoding="utf-8") + "\n사용자 편집", encoding="utf-8")
    linked = Path(first["entries"][0]["path"])
    jobs.list_jobs = lambda: [SimpleNamespace(template_path=str(linked), data_path="")]
    preview = practice.cleanup_preview()
    rows = {row["path"]: row for row in preview["rows"]}
    assert not rows[str(edited)]["delete"] and "수정" in rows[str(edited)]["reason"]
    assert not rows[str(linked)]["delete"] and "참조" in rows[str(linked)]["reason"]
    assert preview["delete_count"] == 3
    assert practice.cleanup(preview["token"])["removed"] == 3
    assert edited.is_file() and linked.is_file()


def test_practice_cleanup_fails_closed_on_changed_preview_or_escape(tmp_path: Path) -> None:
    from types import SimpleNamespace

    from hwpxfiller.external import settings
    from hwpxfiller.external.tutorial_practice import PracticeFiles

    practice = PracticeFiles(tmp_path / "templates", tmp_path / "home",
                             SimpleNamespace(list_jobs=lambda: []))
    batch = practice.prepare()
    preview = practice.cleanup_preview()
    changed = Path(batch["entries"][0]["path"])
    changed.write_bytes(changed.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="상태가 바뀌었습니다"):
        practice.cleanup(preview["token"])
    assert all(Path(entry["path"]).exists() for entry in batch["entries"])

    outside = tmp_path / "keep.txt"
    outside.write_text("keep", encoding="utf-8")
    manifest = settings.load_tutorial_practice()
    manifest["entries"].append({"name": "낙찰자 선정 및 계약체결 안내.txt",
                                "path": str(outside), "sha256": "irrelevant", "batch": "forged"})
    settings.save_tutorial_practice(manifest)
    forged = next(row for row in practice.cleanup_preview()["rows"] if row["path"] == str(outside))
    assert not forged["delete"]
    assert outside.read_text(encoding="utf-8") == "keep"


def test_practice_entry_validation_rejects_missing_malformed_and_parent_escape(tmp_path: Path) -> None:
    from types import SimpleNamespace

    from hwpxfiller.external.tutorial_practice import PracticeFiles

    practice = PracticeFiles(tmp_path / "templates", tmp_path / "home",
                             SimpleNamespace(list_jobs=lambda: []))
    entry = practice.prepare()["entries"][0]
    assert practice.validate(entry) == (True, "")
    assert not practice.validate({"name": entry["name"]})[0]

    copied = Path(entry["path"])
    copied.unlink()
    ready, reason = practice.validate(entry)
    assert not ready and "없거나 이동" in reason

    outside = tmp_path / "outside.hwpx"
    outside.write_bytes(b"user document")
    forged = {**entry, "path": str(practice.template_root / ".." / outside.name)}
    ready, reason = practice.validate(forged)
    assert not ready and "다른 위치" in reason
    assert outside.read_bytes() == b"user document"


def test_practice_prepare_fails_closed_and_rolls_back_partial_copies(tmp_path: Path, monkeypatch) -> None:
    from types import SimpleNamespace

    from hwpxfiller.external import tutorial_practice

    practice = tutorial_practice.PracticeFiles(tmp_path / "templates", tmp_path / "home",
                                               SimpleNamespace(list_jobs=lambda: []))
    with pytest.raises(ValueError, match="알 수 없는"):
        practice.prepare(derived="user-file")

    source = tmp_path / "bundle"
    source.mkdir()
    monkeypatch.setattr(tutorial_practice, "asset_root", lambda: source)
    with pytest.raises(FileNotFoundError, match="동봉 예제"):
        practice.prepare()
    assert not practice.template_root.exists() and not practice.data_root.exists()

    for name in tutorial_practice.ORIGINALS:
        shutil.copyfile(TUTORIAL_ASSETS / name, source / name)
    monkeypatch.setattr(tutorial_practice.settings, "save_tutorial_practice",
                        lambda _value: (_ for _ in ()).throw(OSError("settings disk failed")))
    with pytest.raises(OSError, match="settings disk failed"):
        practice.prepare()
    assert not list(practice.template_root.iterdir())
    assert not list(practice.data_root.iterdir())


def test_practice_cleanup_stops_for_unknown_registry_or_changed_preflight(tmp_path: Path, monkeypatch) -> None:
    from types import SimpleNamespace

    from hwpxfiller.external import tutorial_practice

    jobs = SimpleNamespace(list_jobs=lambda: [])
    practice = tutorial_practice.PracticeFiles(tmp_path / "templates", tmp_path / "home", jobs)
    batch = practice.prepare()
    paths = [Path(entry["path"]) for entry in batch["entries"]]
    jobs.list_jobs = lambda: (_ for _ in ()).throw(OSError("job registry unreadable"))
    with pytest.raises(OSError, match="job registry unreadable"):
        practice.cleanup_preview()
    assert all(path.exists() for path in paths)

    jobs.list_jobs = lambda: []
    preview = practice.cleanup_preview()
    validate = practice.validate
    calls = 0

    def changes_after_preview(entry):
        nonlocal calls
        calls += 1
        return (False, "연습 파일이 수정됐습니다.") if calls == 5 else validate(entry)

    monkeypatch.setattr(practice, "validate", changes_after_preview)
    with pytest.raises(ValueError, match="상태가 바뀌었습니다"):
        practice.cleanup(preview["token"])
    assert all(path.exists() for path in paths)


def test_practice_manifest_corruption_blocks_cleanup_and_frozen_assets_use_bundle(tmp_path: Path, monkeypatch) -> None:
    from types import SimpleNamespace

    from hwpxfiller.external import tutorial_practice

    practice = tutorial_practice.PracticeFiles(tmp_path / "templates", tmp_path / "home",
                                               SimpleNamespace(list_jobs=lambda: []))
    monkeypatch.setattr(tutorial_practice.settings, "load_tutorial_practice",
                        lambda: {"version": 1, "entries": [None]})
    assert practice.latest("공고목록.xlsx") is None  # 손상 항목을 사본으로 오인하지 않는다.
    with pytest.raises(ValueError, match="손상"):
        practice.cleanup_preview()
    monkeypatch.setattr(tutorial_practice.settings, "load_tutorial_practice",
                        lambda: {"version": 99, "entries": []})
    with pytest.raises(ValueError, match="기록"):
        practice.prepare()

    bundle = tmp_path / "frozen"
    monkeypatch.setattr(tutorial_practice.sys, "frozen", True, raising=False)
    monkeypatch.setattr(tutorial_practice.sys, "_MEIPASS", str(bundle), raising=False)
    assert tutorial_practice.asset_root() == bundle / "examples" / "tutorial"
