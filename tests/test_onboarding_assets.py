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


def _jobs(*jobs):
    """Job registry double: the corruption-aware listing and writer lock cleanup uses."""
    import threading
    from types import SimpleNamespace

    lock = threading.RLock()
    return SimpleNamespace(list_jobs_with_corruption=lambda: (list(jobs), []),
                           write_lock=lambda: lock)


def _pools(*entries):
    """Dataset pool double: ``(slot key, reference)`` entries and no corrupt files."""
    import threading
    from types import SimpleNamespace

    lock = threading.RLock()
    return SimpleNamespace(list_references=lambda: (list(entries), []), write_lock=lambda: lock)


def _legacy_copies(practice, *, derived: str = "") -> dict:
    """Residue exactly as versions before #1126 wrote it into the user's templates folder.

    The product no longer creates these copies (practice has its own workspace); the
    cleanup action stays for what older versions left behind, so the tests seed that residue.
    """
    import uuid

    from hwpxfiller.external import settings
    from hwpxfiller.external.tutorial_practice import ORIGINALS, fingerprint

    manifest = settings.load_tutorial_practice()
    batch = uuid.uuid4().hex[:10]
    entries = []
    for name in (ORIGINALS if not derived else ("공고목록.xlsx",)):
        original = TUTORIAL_ASSETS / name
        root = practice.data_root if name.endswith(".xlsx") else practice.template_root
        root.mkdir(parents=True, exist_ok=True)
        target = root / f"{original.stem} (연습 {batch}){original.suffix}"
        shutil.copyfile(original, target)
        if name.endswith(".xlsx") and derived == "blank":
            workbook = load_workbook(target)
            workbook["계약"]["K2"] = None
            workbook.save(target)
        entries.append({"name": name, "path": str(target), "sha256": fingerprint(target),
                        "batch": batch, "derived": derived})
    manifest["entries"].extend(entries)
    settings.save_tutorial_practice(manifest)
    return {"batch": batch, "entries": entries}


def test_practice_cleanup_preserves_changed_and_referenced_files(tmp_path: Path) -> None:
    """A fresh batch is independent; cleanup only removes intact, unreferenced copies."""
    from types import SimpleNamespace

    from hwpxfiller.external.tutorial_practice import PracticeFiles

    jobs = _jobs()
    practice = PracticeFiles(tmp_path / "templates", tmp_path / "home", jobs, _pools())
    first = _legacy_copies(practice)
    second = _legacy_copies(practice, derived="blank")
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
    jobs.list_jobs_with_corruption = lambda: (
        [SimpleNamespace(template_path=str(linked), data_path="")], [])
    preview = practice.cleanup_preview()
    rows = {row["path"]: row for row in preview["rows"]}
    assert not rows[str(edited)]["delete"] and "수정" in rows[str(edited)]["reason"]
    assert not rows[str(linked)]["delete"] and "참조" in rows[str(linked)]["reason"]
    assert preview["delete_count"] == 3
    assert practice.cleanup(preview["token"])["removed"] == 3
    assert edited.is_file() and linked.is_file()


def test_practice_cleanup_fails_closed_on_changed_preview_or_escape(tmp_path: Path) -> None:

    from hwpxfiller.external import settings
    from hwpxfiller.external.tutorial_practice import PracticeFiles

    practice = PracticeFiles(tmp_path / "templates", tmp_path / "home",
                             _jobs(), _pools())
    batch = _legacy_copies(practice)
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

    from hwpxfiller.external.tutorial_practice import PracticeFiles

    practice = PracticeFiles(tmp_path / "templates", tmp_path / "home",
                             _jobs(), _pools())
    entry = _legacy_copies(practice)["entries"][0]
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


def test_lesson_seed_fails_closed_and_rolls_back_partial_copies(tmp_path: Path, monkeypatch) -> None:
    """#1126: a lesson home is either complete or absent — never a half-seeded practice."""
    from hwpxfiller.external import tutorial_workspace

    workspace = tutorial_workspace.TutorialWorkspace(tmp_path / "tutorial")
    with pytest.raises(ValueError, match="알 수 없는"):
        workspace.seed("first_hwpx", derived="user-file")

    source = tmp_path / "bundle"
    source.mkdir()
    monkeypatch.setattr(tutorial_workspace, "asset_root", lambda: source)
    with pytest.raises(FileNotFoundError, match="동봉 예제"):
        workspace.seed("first_hwpx")
    assert not (tmp_path / "tutorial").exists()

    for name in tutorial_workspace.ORIGINALS:
        shutil.copyfile(TUTORIAL_ASSETS / name, source / name)
    calls = 0
    real = tutorial_workspace.fingerprint

    def fails_on_third(path):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OSError("disk failed")
        return real(path)

    monkeypatch.setattr(tutorial_workspace, "fingerprint", fails_on_third)
    with pytest.raises(OSError, match="disk failed"):
        workspace.seed("first_hwpx")
    assert not list((tmp_path / "tutorial" / "lessons" / "first_hwpx").iterdir())


def test_practice_cleanup_stops_for_unknown_registry_or_changed_preflight(tmp_path: Path, monkeypatch) -> None:

    from hwpxfiller.external import tutorial_practice

    jobs = _jobs()
    practice = tutorial_practice.PracticeFiles(tmp_path / "templates", tmp_path / "home", jobs,
                                               _pools())
    batch = _legacy_copies(practice)
    paths = [Path(entry["path"]) for entry in batch["entries"]]
    jobs.list_jobs_with_corruption = lambda: (_ for _ in ()).throw(
        OSError("job registry unreadable"))
    with pytest.raises(OSError, match="job registry unreadable"):
        practice.cleanup_preview()
    assert all(path.exists() for path in paths)

    jobs.list_jobs_with_corruption = lambda: ([], [])
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

    from hwpxfiller.external import tutorial_practice

    practice = tutorial_practice.PracticeFiles(tmp_path / "templates", tmp_path / "home",
                                               _jobs(), _pools())
    monkeypatch.setattr(tutorial_practice.settings, "load_tutorial_practice",
                        lambda: {"version": 1, "entries": [None]})
    assert practice.latest("공고목록.xlsx") is None  # 손상 항목을 사본으로 오인하지 않는다.
    with pytest.raises(ValueError, match="손상"):
        practice.cleanup_preview()
    monkeypatch.setattr(tutorial_practice.settings, "load_tutorial_practice",
                        lambda: {"version": 99, "entries": []})
    with pytest.raises(ValueError, match="기록"):
        practice.cleanup_preview()

    bundle = tmp_path / "frozen"
    monkeypatch.setattr(tutorial_practice.sys, "frozen", True, raising=False)
    monkeypatch.setattr(tutorial_practice.sys, "_MEIPASS", str(bundle), raising=False)
    assert tutorial_practice.asset_root() == bundle / "examples" / "tutorial"


def _real_practice(tmp_path: Path):
    """Practice files over the real job and dataset pool registries (#1117)."""
    from hwpxfiller.external.dataset_store import DatasetPoolRegistry
    from hwpxfiller.external.job_store import JobRegistry
    from hwpxfiller.external.tutorial_practice import PracticeFiles

    jobs = JobRegistry(tmp_path / "jobs")
    pools = DatasetPoolRegistry(tmp_path / "pool")
    return PracticeFiles(tmp_path / "templates", tmp_path / "home", jobs, pools), jobs, pools


def test_practice_cleanup_refuses_when_a_saved_job_cannot_be_read(tmp_path: Path) -> None:
    """A truncated job file may be the one that needs a copy; unknown is never unreferenced."""
    import json

    practice, jobs, _pools_registry = _real_practice(tmp_path)
    batch = _legacy_copies(practice)
    paths = [Path(entry["path"]) for entry in batch["entries"]]
    preview = practice.cleanup_preview()
    assert preview["delete_count"] == 4

    jobs.directory.mkdir(parents=True)
    # 저장 도중 끊긴 작업: 연습 서식을 참조하지만 JSON 으로 읽히지 않는다.
    (jobs.directory / "연습-작업.job.json").write_text(
        '{"name": "연습 작업", "template_path": ' + json.dumps(str(paths[0])), encoding="utf-8")
    with pytest.raises(ValueError, match="읽을 수 없는 작업"):
        practice.cleanup_preview()
    with pytest.raises(ValueError, match="읽을 수 없는 작업"):
        practice.cleanup(preview["token"])
    assert all(path.is_file() for path in paths)


def test_practice_cleanup_preserves_dataset_pool_registrations(tmp_path: Path) -> None:
    """A copy registered in the dataset pool stays; an unreadable pool entry stops cleanup."""
    from hwpxfiller.domain.dataset_reference import DatasetReference, excel_reference_opts

    practice, _jobs_registry, pools = _real_practice(tmp_path)
    _legacy_copies(practice)
    derived = Path(_legacy_copies(practice, derived="replacement")["entries"][0]["path"])
    pools.add(DatasetReference(name="연습 데이터", kind="excel",
                               opts=excel_reference_opts(str(derived), "공고")))
    preview = practice.cleanup_preview()
    row = next(row for row in preview["rows"] if row["path"] == str(derived))
    assert not row["delete"] and row["reason"] == "등록 데이터가 참조합니다."
    assert practice.cleanup(preview["token"])["removed"] == 4
    assert derived.is_file()

    (pools.directory / "손상.dataset.json").write_text("{", encoding="utf-8")
    with pytest.raises(ValueError, match="등록 데이터"):
        practice.cleanup_preview()
    assert derived.is_file()


def test_practice_cleanup_records_partial_progress_and_recovers_lost_records(
    tmp_path: Path, monkeypatch
) -> None:
    """A failed unlink or manifest save never strands records of copies already deleted."""
    from hwpxfiller.external import settings, tutorial_practice

    practice = tutorial_practice.PracticeFiles(tmp_path / "templates", tmp_path / "home",
                                               _jobs(), _pools())
    paths = [Path(entry["path"]) for entry in _legacy_copies(practice)["entries"]]
    unlink = Path.unlink
    calls = 0

    def locked_third(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise PermissionError("백신이 파일을 잡고 있습니다")
        return unlink(self, *args, **kwargs)

    monkeypatch.setattr(tutorial_practice.Path, "unlink", locked_third)
    with pytest.raises(PermissionError):
        practice.cleanup(practice.cleanup_preview()["token"])
    monkeypatch.setattr(tutorial_practice.Path, "unlink", unlink)
    recorded = {entry["path"] for entry in settings.load_tutorial_practice()["entries"]}
    assert recorded == {str(path) for path in paths if path.exists()}
    assert len(recorded) == 2
    preview = practice.cleanup_preview()
    assert preview["delete_count"] == 2 and all(row["reason"] == "" for row in preview["rows"])
    assert practice.cleanup(preview["token"])["removed"] == 2
    assert not any(path.exists() for path in paths)

    # 매니페스트 저장까지 실패하면 지워진 사본의 기록이 남는다 — 다음 정리가 그 기록만 걷는다.
    paths = [Path(entry["path"]) for entry in _legacy_copies(practice)["entries"]]
    save = settings.save_tutorial_practice
    monkeypatch.setattr(tutorial_practice.settings, "save_tutorial_practice",
                        lambda _value: (_ for _ in ()).throw(OSError("settings disk failed")))
    with pytest.raises(OSError, match="settings disk failed"):
        practice.cleanup(practice.cleanup_preview()["token"])
    monkeypatch.setattr(tutorial_practice.settings, "save_tutorial_practice", save)
    assert not any(path.exists() for path in paths)
    preview = practice.cleanup_preview()
    assert [row["delete"] for row in preview["rows"]] == [True] * 4
    assert {row["reason"] for row in preview["rows"]} == {"연습 파일이 없거나 이동했습니다."}

    # 앱이 만든 이름·위치가 아닌 없는 기록은 증명되지 않으므로 보존 행으로 남는다.
    manifest = settings.load_tutorial_practice()
    manifest["entries"].append({"name": "공고목록.xlsx", "batch": "forged", "sha256": "x",
                                "path": str(practice.data_root / "사용자 사본.xlsx")})
    settings.save_tutorial_practice(manifest)
    preview = practice.cleanup_preview()
    assert preview["delete_count"] == 4
    assert practice.cleanup(preview["token"]) == {"removed": 4, "preserved": 1}
    remaining = settings.load_tutorial_practice()["entries"]
    assert [entry["batch"] for entry in remaining] == ["forged"]


def test_practice_cleanup_holds_job_and_pool_writers_from_scan_to_delete(
    tmp_path: Path, monkeypatch
) -> None:
    """A job save or data registration cannot land between the reference scan and unlink."""
    import threading

    from hwpxfiller.external import tutorial_practice

    practice, jobs, pools = _real_practice(tmp_path)
    paths = [Path(entry["path"]) for entry in _legacy_copies(practice)["entries"]]
    unlink = Path.unlink
    seen: list[tuple[bool, bool]] = []

    def probe(lock) -> bool:
        free = lock.acquire(blocking=False)
        if free:
            lock.release()
        return free

    def unlink_with_probe(self, *args, **kwargs):
        # 다른 스레드(웹 브리지 호출)에서 같은 디렉터리의 writer 잠금을 잡아 본다.
        result: list[bool] = []
        other = threading.Thread(target=lambda: result.extend(
            (probe(jobs.write_lock()), probe(pools.write_lock()))))
        other.start()
        other.join()
        seen.append((result[0], result[1]))
        return unlink(self, *args, **kwargs)

    monkeypatch.setattr(tutorial_practice.Path, "unlink", unlink_with_probe)
    assert practice.cleanup(practice.cleanup_preview()["token"])["removed"] == 4
    assert seen == [(False, False)] * 4
    assert not any(path.exists() for path in paths)


def test_practice_cleanup_keeps_the_deletion_error_when_the_record_save_also_fails(
    tmp_path: Path, monkeypatch
) -> None:
    """The user sees why cleanup stopped; the bookkeeping failure is chained, not substituted."""
    from hwpxfiller.external import settings, tutorial_practice

    practice = tutorial_practice.PracticeFiles(tmp_path / "templates", tmp_path / "home",
                                               _jobs(), _pools())
    paths = [Path(entry["path"]) for entry in _legacy_copies(practice)["entries"]]
    unlink = Path.unlink
    calls = 0

    def locked_third(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise PermissionError("백신이 파일을 잡고 있습니다")
        return unlink(self, *args, **kwargs)

    save = settings.save_tutorial_practice
    monkeypatch.setattr(tutorial_practice.Path, "unlink", locked_third)
    monkeypatch.setattr(tutorial_practice.settings, "save_tutorial_practice",
                        lambda _value: (_ for _ in ()).throw(OSError("settings disk failed")))
    with pytest.raises(PermissionError, match="백신") as raised:
        practice.cleanup(practice.cleanup_preview()["token"])
    assert isinstance(raised.value.__cause__, OSError)
    assert "settings disk failed" in str(raised.value.__cause__)
    monkeypatch.setattr(tutorial_practice.Path, "unlink", unlink)
    monkeypatch.setattr(tutorial_practice.settings, "save_tutorial_practice", save)
    assert [path.exists() for path in paths] == [False, False, True, True]
    rows = practice.cleanup_preview()["rows"]
    assert [row["delete"] for row in rows] == [True] * 4
    assert [row["reason"] for row in rows] == ["연습 파일이 없거나 이동했습니다."] * 2 + [""] * 2


def test_practice_vanished_record_requires_an_app_copy_path_that_is_really_gone(
    tmp_path: Path, monkeypatch
) -> None:
    """Only a missing file at this app's own generated path is a droppable record."""
    from hwpxfiller.external import tutorial_practice

    practice = tutorial_practice.PracticeFiles(tmp_path / "templates", tmp_path / "home",
                                               _jobs(), _pools())
    entry = next(item for item in _legacy_copies(practice)["entries"] if item["name"].endswith(".txt"))
    present = dict(entry)
    assert not practice._vanished(present)  # 파일이 있으면 기록을 걷지 않는다.
    Path(entry["path"]).unlink()
    assert practice._vanished(entry)
    assert not practice._vanished({**entry, "name": "사용자 문서.txt"})
    assert not practice._vanished({**entry, "batch": ""})
    assert not practice._vanished({**entry, "batch": None})
    assert not practice._vanished({key: value for key, value in entry.items() if key != "batch"})
    assert not practice._vanished({**entry, "path": str(practice.data_root / Path(entry["path"]).name)})

    lstat = Path.lstat

    def denied(self, *args, **kwargs):
        if str(self) == entry["path"]:
            raise PermissionError("접근 거부")
        return lstat(self, *args, **kwargs)

    monkeypatch.setattr(tutorial_practice.Path, "lstat", denied)
    assert not practice._vanished(entry)  # 확인할 수 없는 상태는 없는 것으로 보지 않는다.


def test_practice_cleanup_reference_scan_covers_pool_databases_and_empty_runs(tmp_path: Path) -> None:
    """A pool entry's ``db`` path protects a copy too; a cleanup with nothing to do writes nothing."""
    from types import SimpleNamespace

    from hwpxfiller.external import settings, tutorial_practice

    empty = tutorial_practice.PracticeFiles(tmp_path / "t0", tmp_path / "h0", _jobs(), _pools())
    assert empty.cleanup(empty.cleanup_preview()["token"]) == {"removed": 0, "preserved": 0}
    assert settings.load_tutorial_practice() == {"version": 1, "entries": []}

    pools = _pools()
    practice = tutorial_practice.PracticeFiles(tmp_path / "templates", tmp_path / "home",
                                               _jobs(), pools)
    data = Path(_legacy_copies(practice)["entries"][-1]["path"])
    pools.list_references = lambda: ([("slot", SimpleNamespace(opts={"db": str(data), "path": ""}))], [])
    preview = practice.cleanup_preview()
    row = next(row for row in preview["rows"] if row["path"] == str(data))
    assert not row["delete"] and row["reason"] == "등록 데이터가 참조합니다."
    assert practice.cleanup(preview["token"]) == {"removed": 3, "preserved": 1}
    assert data.is_file()
