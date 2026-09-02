"""템플릿 관리 워크숍 ViewModel(C5) 계약 테스트 — 창 없이 실행하는 링1 테스트.

핵심 증명:
1. 상태별(RAW/PARTIAL/COMPILED/FILLED) 게이트 액션이 정확히 합의된 집합이다.
2. fieldize dry-run(scan_preview)은 파일을 만지지 않고 미리보기만; 적용(apply_fieldize)만
   컴파일·저장하고 그 파일의 compile_status 가 진행한다(RAW/PARTIAL → COMPILED).
3. lint/drift 결과가 VM 을 통해 렌더된다.

웹 표현 계층과의 배선은 ``test_webapp_template``·``test_webapp_editor``가 별도로 검증한다.
"""

from __future__ import annotations

from pathlib import Path
from zipfile import BadZipFile

import pytest

from hwpxfiller.domain.authoring import compile_document
from hwpxfiller.domain.fields import FieldDocument
from hwpxfiller.domain.template_status import CompileState
from hwpxfiller.external import template_inspection
from hwpxfiller.external.hwpx_package_io import write_hwpx_package
from hwpxfiller.external.template_inspection import (
    HWPX_TEMPLATE_OPS,
    inspect_hwpx_template,
    template_compile_status,
)
from hwpxfiller.gui.template_manager_state import (
    TemplateManagerViewModel,
    available_actions,
)
from hwpxcore.package import MIMETYPE_NAME, MIMETYPE_VALUE, HwpxPackage

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HS = "http://www.hancom.co.kr/hwpml/2011/section"
SECTION = "Contents/section0.xml"


# --------------------------------------------------------------- 픽스처 빌더
def _pkg(section_inner: str) -> HwpxPackage:
    sec = (
        f'<hs:sec xmlns:hs="{HS}" xmlns:hp="{HP}">{section_inner}</hs:sec>'
    ).encode("utf-8")
    pkg = HwpxPackage()
    pkg.entries[MIMETYPE_NAME] = MIMETYPE_VALUE
    pkg.stored.add(MIMETYPE_NAME)
    pkg.entries[SECTION] = sec
    return pkg


def _write_raw(path: Path, section_inner: str) -> Path:
    """평문 토큰만 든 템플릿을 파일로 저장(RAW/미컴파일 원문)."""
    write_hwpx_package(path, _pkg(section_inner))
    return path


def _write_compiled(path: Path, section_inner: str) -> Path:
    """평문 토큰을 컴파일한 템플릿을 파일로 저장(COMPILED)."""
    pkg, _ = compile_document(_pkg(section_inner))
    write_hwpx_package(path, pkg)
    return path


def _write_filled(path: Path, section_inner: str, field: str, value: str) -> Path:
    """컴파일 후 값 1개 주입한 템플릿을 파일로 저장(FILLED)."""
    pkg, _ = compile_document(_pkg(section_inner))
    doc = FieldDocument(pkg.entries[SECTION])
    assert doc.set_field(field, value) is True
    pkg.entries[SECTION] = doc.to_bytes()
    write_hwpx_package(path, pkg)
    return path


# =============================================== 수용기준 1 — 상태별 게이트 액션
def test_action_matrix_and_vm_delegation():
    """상태 판정은 순수 리졸버 하나가 소유하고 VM은 그 결과를 그대로 낸다."""
    expected = {
        CompileState.RAW: ["compile"],
        CompileState.PARTIAL: ["compile", "review"],
        CompileState.COMPILED: ["preview", "make_job"],
        CompileState.FILLED: ["preview"],
        None: [],
    }
    for state, keys in expected.items():
        assert [a.key for a in available_actions(state)] == keys
    # RAW 라벨은 S8-03 에서 구간 축을 포함하게 바뀌었다(같은 한 동사가 둘을 변환한다).
    assert [available_actions(state)[0].label for state in (CompileState.RAW, CompileState.PARTIAL)] == [
        "누름틀·구간 변환", "마저 변환",
    ]
    vm = TemplateManagerViewModel(
        paths=[], inspect_template=inspect_hwpx_template, file_ops=HWPX_TEMPLATE_OPS
    )
    assert [a.key for a in vm.actions_for(CompileState.COMPILED)] == ["preview", "make_job"]


def test_library_scan_is_recursive(tmp_path):
    """R-info 2부 결정 5 — 하위폴더의 .hwpx 도 재귀로 찾는다(비재귀 glob 이던 시절 조용한 누락)."""
    _write_raw(tmp_path / "루트.hwpx", "<hp:p><hp:run><hp:t>계약명: {{계약명}}</hp:t></hp:run></hp:p>")
    sub = tmp_path / "탐색기묶음"
    sub.mkdir()
    _write_raw(sub / "하위.hwpx", "<hp:p><hp:run><hp:t>계약명: {{계약명}}</hp:t></hp:run></hp:p>")
    vm = TemplateManagerViewModel(
        library_dir=tmp_path,
        inspect_template=inspect_hwpx_template,
        file_ops=HWPX_TEMPLATE_OPS,
    )
    names = {r.name for r in vm.rows()}
    # 표시명은 **루트 상대경로·확장자 제외**다(U6-A #975 — txt 와 같은 규칙): 재귀 루트에서
    # basename 은 유일하지 않으므로 하위폴더가 이름에 남아야 두 파일이 구분된다.
    assert names == {"루트", "탐색기묶음/하위"}


def test_library_scan_excludes_results_output_subtree(tmp_path):
    """#136 리뷰 F2 — 작업 산출물 폴더(템플릿/Results)는 템플릿으로 재수집하지 않는다.

    실행 기본 저장 폴더가 라이브러리 루트 밑 ``Results`` 라, 재귀 스캔이 완성 문서를 다시
    템플릿(FILLED 행)으로 올리면 실행할수록 라이브러리가 오염된다."""
    _write_raw(tmp_path / "서식.hwpx", "<hp:p><hp:run><hp:t>계약명: {{계약명}}</hp:t></hp:run></hp:p>")
    results = tmp_path / "Results"
    results.mkdir()
    _write_compiled(results / "생성물.hwpx", "<hp:p><hp:run><hp:t>계약명: {{계약명}}</hp:t></hp:run></hp:p>")
    # 하위폴더의 Results 도 제외(templates/입찰/Results/*.hwpx 형태).
    nested = tmp_path / "입찰" / "Results"
    nested.mkdir(parents=True)
    _write_compiled(nested / "생성물2.hwpx", "<hp:p><hp:run><hp:t>계약명: {{계약명}}</hp:t></hp:run></hp:p>")
    vm = TemplateManagerViewModel(
        library_dir=tmp_path,
        inspect_template=inspect_hwpx_template,
        file_ops=HWPX_TEMPLATE_OPS,
    )
    assert {r.name for r in vm.rows()} == {"서식"}  # 산출물은 목록에 없다


def test_rows_expose_gated_actions_matching_state(tmp_path, monkeypatch):
    """VM 행이 실제 파일 상태에서 계산한 액션 집합을 노출한다(라이브러리 전 상태)."""
    raw = _write_raw(tmp_path / "raw.hwpx", "<hp:p><hp:run><hp:t>계약명: {{계약명}}</hp:t></hp:run></hp:p>")
    comp = _write_compiled(tmp_path / "comp.hwpx", "<hp:p><hp:run><hp:t>계약명: {{계약명}}</hp:t></hp:run></hp:p>")
    filled = _write_filled(
        tmp_path / "fill.hwpx",
        "<hp:p><hp:run><hp:t>계약명: {{계약명}}</hp:t></hp:run></hp:p>",
        "계약명", "정보시스템 구축",
    )
    inspected: "list[str]" = []
    opened: "list[str]" = []
    original_read = template_inspection.read_hwpx_package

    def recording_inspect(path: str):
        inspected.append(path)
        return inspect_hwpx_template(path)

    def counting_read(path: str) -> HwpxPackage:
        opened.append(path)
        return original_read(path)

    monkeypatch.setattr(template_inspection, "read_hwpx_package", counting_read)
    vm = TemplateManagerViewModel(
        library_dir=tmp_path,
        inspect_template=recording_inspect,
        file_ops=HWPX_TEMPLATE_OPS,
    )
    by_name = {r.name: r for r in vm.rows()}

    expected_paths = sorted(str(path) for path in (raw, comp, filled))
    assert sorted(inspected) == expected_paths
    assert sorted(opened) == expected_paths

    assert by_name["raw"].state == CompileState.RAW
    assert [a.key for a in by_name["raw"].actions()] == ["compile"]
    assert by_name["comp"].state == CompileState.COMPILED
    assert [a.key for a in by_name["comp"].actions()] == ["preview", "make_job"]
    assert by_name["fill"].state == CompileState.FILLED
    assert [a.key for a in by_name["fill"].actions()] == ["preview"]
    # 배지·상세가 성형돼 표현 계층이 읽을 수 있다.
    assert by_name["raw"].badge_label == "원문"
    assert "필드" in by_name["comp"].detail_line()


# ================================ 수용기준 2 — dry-run 무변형 → 적용 시 상태 진행
def test_scan_then_apply_is_readonly_until_the_state_transition(tmp_path):
    """scan은 무변형이고 apply만 RAW → COMPILED 상태 전이를 소유한다."""
    path = _write_raw(tmp_path / "t.hwpx", "<hp:p><hp:run><hp:t>계약명: {{계약명}}</hp:t></hp:run></hp:p>")
    before = path.read_bytes()

    vm = TemplateManagerViewModel(
        paths=[path],
        inspect_template=inspect_hwpx_template,
        file_ops=HWPX_TEMPLATE_OPS,
    )
    preview = vm.scan_preview(str(path))
    assert preview.has_compilable
    assert [s.name for s in preview.compilable] == ["계약명"]
    assert path.read_bytes() == before
    assert template_compile_status(str(path)).state == CompileState.RAW
    report = vm.apply_fieldize(str(path))
    assert report.compiled == ["계약명"]
    assert report.modified
    assert template_compile_status(str(path)).state == CompileState.COMPILED
    row = vm.row_for(str(path))
    assert row.state == CompileState.COMPILED
    assert [a.key for a in row.actions()] == ["preview", "make_job"]


def test_apply_fieldize_advances_partial_to_compiled(tmp_path):
    """PARTIAL(필드 有 + 미컴파일 평문 중복)에 적용하면 잔존 토큰이 컴파일돼 COMPILED."""
    # 필드 1개(컴파일됨) + 같은 이름 평문 중복(미컴파일) = PARTIAL.
    inner = (
        "<hp:p><hp:run><hp:ctrl>"
        f'<hp:fieldBegin id="1" type="CLICK_HERE" name="계약명" fieldid="2"/>'
        "</hp:ctrl></hp:run>"
        "<hp:run><hp:t>{{계약명}}</hp:t></hp:run>"
        "<hp:run><hp:ctrl><hp:fieldEnd beginIDRef=\"1\" fieldid=\"2\"/></hp:ctrl></hp:run></hp:p>"
        "<hp:p><hp:run><hp:t>다시: {{계약명}}</hp:t></hp:run></hp:p>"
    )
    path = tmp_path / "partial.hwpx"
    write_hwpx_package(path, _pkg(inner))
    assert template_compile_status(str(path)).state == CompileState.PARTIAL

    vm = TemplateManagerViewModel(
        paths=[path],
        inspect_template=inspect_hwpx_template,
        file_ops=HWPX_TEMPLATE_OPS,
    )
    vm.apply_fieldize(str(path))
    assert template_compile_status(str(path)).state == CompileState.COMPILED


def test_apply_fieldize_noop_writes_nothing(tmp_path):
    """바꿀 토큰이 없으면 저장하지 않는다 — 파일 바이트 무변형(조용한 재저장 금지)."""
    path = _write_compiled(
        tmp_path / "done.hwpx", "<hp:p><hp:run><hp:t>계약명: {{계약명}}</hp:t></hp:run></hp:p>"
    )
    before = path.read_bytes()
    vm = TemplateManagerViewModel(
        paths=[path],
        inspect_template=inspect_hwpx_template,
        file_ops=HWPX_TEMPLATE_OPS,
    )
    report = vm.apply_fieldize(str(path))
    assert not report.modified
    assert path.read_bytes() == before  # 저장 자체가 없다


# =================================================== 수용기준 3 — lint / drift
def test_lint_reports_near_duplicate_fields(tmp_path):
    """공백만 다른 유사 필드명(계약명 vs 계약 명)을 VM lint 가 near_duplicate 로 신고."""
    path = _write_compiled(
        tmp_path / "dup.hwpx",
        "<hp:p><hp:run><hp:t>계약명: {{계약명}} / 상대: {{계약 명}}</hp:t></hp:run></hp:p>",
    )
    vm = TemplateManagerViewModel(
        paths=[path],
        inspect_template=inspect_hwpx_template,
        file_ops=HWPX_TEMPLATE_OPS,
    )
    report = vm.lint(str(path))
    kinds = {f.kind for f in report.findings}
    assert "near_duplicate" in kinds
    assert report.has_issues


def test_lint_reports_stray_compilable_token(tmp_path):
    """미컴파일 평문 토큰이 남으면 lint 가 stray_token(fieldize 권장)으로 신고."""
    path = _write_raw(tmp_path / "raw.hwpx", "<hp:p><hp:run><hp:t>계약명: {{계약명}}</hp:t></hp:run></hp:p>")
    vm = TemplateManagerViewModel(
        paths=[path],
        inspect_template=inspect_hwpx_template,
        file_ops=HWPX_TEMPLATE_OPS,
    )
    report = vm.lint(str(path))
    kinds = {f.kind for f in report.findings}
    assert "stray_token" in kinds  # authoring.scan_tokens 가 단일 진실원


def test_drift_reports_added_and_removed_fields(tmp_path):
    """두 판본의 필드셋 변화를 VM drift 가 추가/삭제로 낸다."""
    old = _write_compiled(
        tmp_path / "v1.hwpx",
        "<hp:p><hp:run><hp:t>계약명: {{계약명}} 금액 {{금액}}</hp:t></hp:run></hp:p>",
    )
    new = _write_compiled(
        tmp_path / "v2.hwpx",
        "<hp:p><hp:run><hp:t>계약명: {{계약명}} 예산 {{사업예산}}</hp:t></hp:run></hp:p>",
    )
    vm = TemplateManagerViewModel(paths=[], inspect_template=inspect_hwpx_template, file_ops=HWPX_TEMPLATE_OPS)
    drift = vm.drift(str(old), str(new))
    assert drift.has_changes
    assert "사업예산" in drift.added
    assert "금액" in drift.removed


# ==================================================== 라이브러리/오류 노출
def test_empty_library_is_empty(tmp_path):
    vm = TemplateManagerViewModel(
        library_dir=tmp_path,
        inspect_template=inspect_hwpx_template,
        file_ops=HWPX_TEMPLATE_OPS,
    )
    assert vm.is_empty()
    assert vm.count_label() == ""


def test_unreadable_file_surfaced_as_error_row_not_hidden(tmp_path):
    """읽기 실패 파일은 조용히 감추지 않고 error 행으로 시끄럽게 노출한다."""
    bad = tmp_path / "broken.hwpx"
    bad.write_bytes(b"not a zip at all")
    with pytest.raises(BadZipFile) as raised:
        inspect_hwpx_template(str(bad))
    vm = TemplateManagerViewModel(
        library_dir=tmp_path,
        inspect_template=inspect_hwpx_template,
        file_ops=HWPX_TEMPLATE_OPS,
    )
    rows = vm.rows()
    assert len(rows) == 1
    assert rows[0].is_error
    assert rows[0].state is None
    assert rows[0].actions() == []
    assert rows[0].error == str(raised.value)


def test_filled_values_preview_reads_c1_fields(tmp_path):
    """FILLED 미리보기 값은 C1 read_fields 로 읽는다."""
    path = _write_filled(
        tmp_path / "fill.hwpx",
        "<hp:p><hp:run><hp:t>계약명: {{계약명}}</hp:t></hp:run></hp:p>",
        "계약명", "정보시스템 구축",
    )
    vm = TemplateManagerViewModel(
        paths=[path],
        inspect_template=inspect_hwpx_template,
        file_ops=HWPX_TEMPLATE_OPS,
    )
    assert vm.filled_values(str(path)) == {"계약명": "정보시스템 구축"}


# ============================================ RC-14 — 기본 라이브러리·빈상태·성형
def test_default_templates_dir_honors_env_override(monkeypatch, tmp_path):
    """링0 기본 템플릿 라이브러리 루트 — HWPXFILLER_HOME 재지정(기존 루트 4종 미러)."""
    from hwpxfiller.host.locations import default_templates_dir

    monkeypatch.setenv("HWPXFILLER_HOME", str(tmp_path))
    assert default_templates_dir() == tmp_path / "templates"


def test_vm_lint_accepts_vocabulary(tmp_path):
    """VM.lint(path, vocabulary=None) 가 코어 lint_template 시그니처와 정렬(RC-14).

    통제 어휘를 주면 어휘 밖 필드명이 off_vocabulary 로 신고된다 — CLI --vocab 과
    웹·CLI 위생 점검 범위와 동등하다.
    """
    path = _write_compiled(
        tmp_path / "v.hwpx",
        "<hp:p><hp:run><hp:t>계약명: {{계약명}}</hp:t></hp:run></hp:p>",
    )
    vm = TemplateManagerViewModel(
        paths=[path],
        inspect_template=inspect_hwpx_template,
        file_ops=HWPX_TEMPLATE_OPS,
    )
    assert "off_vocabulary" not in {f.kind for f in vm.lint(str(path)).findings}  # 기본: 어휘 검사 없음
    report = vm.lint(str(path), vocabulary=["표준필드명"])
    assert "off_vocabulary" in {f.kind for f in report.findings}


def test_vm_set_library_dir_and_empty_hint_distinguish_missing_vs_empty(tmp_path):
    """'폴더 없음'과 '빈 폴더'를 구분 안내하고, 폴더 재지정이 재스캔한다(RC-14 W6)."""
    missing = tmp_path / "없는폴더"
    vm = TemplateManagerViewModel(
        library_dir=missing,
        inspect_template=inspect_hwpx_template,
        file_ops=HWPX_TEMPLATE_OPS,
    )
    assert vm.is_empty()
    assert "폴더가 없습니다" in vm.empty_hint()
    assert str(missing) in vm.empty_hint()  # 어느 폴더인지 지목

    empty = tmp_path / "빈폴더"
    empty.mkdir()
    vm.set_library_dir(empty)
    assert vm.is_empty()
    assert "템플릿이 없습니다" in vm.empty_hint()  # 폴더는 있으나 .hwpx 없음

    lib = tmp_path / "lib"
    lib.mkdir()
    _write_raw(lib / "t.hwpx", "<hp:p><hp:run><hp:t>계약명: {{계약명}}</hp:t></hp:run></hp:p>")
    vm.set_library_dir(lib)
    assert not vm.is_empty()  # 재지정 → 재스캔


def test_vm_result_formatting_lives_in_ring1_and_names_target(tmp_path):
    """결과 문구 성형 4종은 링1 소유 — 대상 템플릿명 포함, severity 한국어(RC-14)."""
    raw = _write_raw(
        tmp_path / "raw.hwpx",
        "<hp:p><hp:run><hp:t>계약명: {{계약명}}</hp:t></hp:run></hp:p>",
    )
    vm = TemplateManagerViewModel(
        paths=[raw],
        inspect_template=inspect_hwpx_template,
        file_ops=HWPX_TEMPLATE_OPS,
    )

    lint_text = vm.format_lint_result(str(raw), vm.lint(str(raw)))
    assert "raw.hwpx" in lint_text
    assert "[경고]" in lint_text          # severity 영문 원시 노출 금지
    assert "[warning]" not in lint_text
    assert lint_text.level == "warn"      # UD-07: 경고 잔존 → warn 심각도 채널
    # 이슈 없는 검토는 ok(muted 고정 아님).
    assert vm.format_lint_result(str(raw), _EmptyLint()).level == "ok"

    preview_text = vm.format_preview_result(str(raw), {"계약명": "값"})
    assert "raw.hwpx" in preview_text and "계약명 = 값" in preview_text
    assert preview_text.level == "muted"  # 미리보기는 정보성 → muted
    assert "raw.hwpx" in vm.format_preview_result(str(raw), {})  # 빈 값도 대상 명시

    report = vm.apply_fieldize(str(raw))
    compile_text = vm.format_compile_result(str(raw), report)
    assert "raw.hwpx" in compile_text and "필드 1개 추가" in compile_text
    assert compile_text.level == "ok"     # 성공 → ok

    drift_text = vm.format_drift_result(str(raw), str(raw), vm.drift(str(raw), str(raw)))
    assert "raw.hwpx" in drift_text and "변화 없음" in drift_text
    assert drift_text.level == "ok"       # 변화 없음 → ok


class _EmptyLint:
    """findings 없는 LintReport 대역(형 계약: .findings 순회)."""

    findings: "list" = []


def test_format_scan_empty_result_is_inline_warn(tmp_path):
    """UD-24: '변환 가능 토큰 없음'을 인라인 결과(warn)로 성형 — 차단 모달 강등."""
    from hwpxfiller.gui.template_manager_state import ScanPreview

    raw = _write_raw(
        tmp_path / "onlymanual.hwpx",
        "<hp:p><hp:run><hp:t>계약: {{계약명}}</hp:t></hp:run></hp:p>",
    )
    vm = TemplateManagerViewModel(
        paths=[raw],
        inspect_template=inspect_hwpx_template,
        file_ops=HWPX_TEMPLATE_OPS,
    )
    line = vm.format_scan_empty_result(str(raw), ScanPreview(compilable=[], skipped=[]))
    assert "onlymanual.hwpx" in line and "변환 가능한 토큰이 없습니다" in line
    assert line.level == "warn"


# ================================= S8-03 — 누름틀·구간 변환 미리보기·적용·Slot 목록
def _structure_body(*lines: str) -> str:
    return "".join(
        f"<hp:p><hp:run charPrIDRef=\"0\"><hp:t>{line}</hp:t></hp:run></hp:p>"
        for line in lines
    )


_NOTATION_LINES = (
    "{{#항목 특약 특약 사항}}",
    "{{#선택 지체상금 지체상금 조항}}",
    "지체상금은 {{지체상금률}} 로 한다.",
    "{{/선택}}",
    "{{/항목}}",
    "발주자: {{수요기관}}",
)


def _structure_vm(tmp_path, *lines: str):
    path = _write_raw(tmp_path / "구간.hwpx", _structure_body(*lines))
    vm = TemplateManagerViewModel(
        paths=[path], inspect_template=inspect_hwpx_template, file_ops=HWPX_TEMPLATE_OPS
    )
    return vm, path


def test_convert_preview_counts_both_axes(tmp_path):
    """미리보기 하나가 필드 토큰과 구간 선언을 함께 센다(「항목 n · 선택 m · 누름틀 k」)."""
    vm, path = _structure_vm(tmp_path, *_NOTATION_LINES)
    preview = vm.convert_preview(str(path))

    assert (preview.slots, preview.options) == (1, 1)
    assert len(preview.tokens.compilable) == 2
    assert preview.summary() == "항목 1개 · 선택 1개 · 누름틀 2개"
    assert (preview.blocked, preview.has_convertible) == (False, True)
    assert path.read_bytes()  # dry-run — 파일 무변형(아래 apply 가 대조군)


def test_convert_preview_blocks_on_a_notation_diagnostic(tmp_path):
    """표기 진단이 있으면 미리보기가 스스로 '변환 불가'를 말한다."""
    vm, path = _structure_vm(tmp_path, "{{#항목 특약}}", "본문 {{값}}")
    preview = vm.convert_preview(str(path))

    assert preview.blocked is True
    assert any("닫는 마커" in item for item in preview.diagnostics)
    line = vm.format_convert_blocked_result(str(path), preview)
    assert "변환할 수 없습니다" in line and "구간.hwpx" in line
    assert line.level == "warn"


def test_convert_preview_with_nothing_to_do(tmp_path):
    vm, path = _structure_vm(tmp_path, "본문에 토큰도 마커도 없습니다.")
    preview = vm.convert_preview(str(path))

    assert (preview.blocked, preview.has_convertible) == (False, False)
    line = vm.format_convert_empty_result(str(path), preview)
    assert "변환할 토큰과 구간이 없습니다" in line and line.level == "warn"


def test_apply_convert_compiles_fields_before_structure(tmp_path):
    """순서 계약(S8-02 실측) — 구간 **안**의 토큰도 누름틀이 된다.

    구조를 먼저 컴파일하면 그 region 안 토큰은 depth>0 이라 필드 컴파일에서 제외된다.
    「지체상금률」이 필드로 잡혔다는 사실이 곧 순서의 증거다.
    """
    vm, path = _structure_vm(tmp_path, *_NOTATION_LINES)
    result = vm.apply_convert(str(path))

    assert (result.fields, result.slots, result.options) == (2, 1, 1)
    assert result.refused is False
    inspection = inspect_hwpx_template(str(path))
    assert set(inspection.fields) == {"지체상금률", "수요기관"}
    assert [slot.id for slot in inspection.slots] == ["특약"]
    line = vm.format_convert_result(str(path), result)
    assert "구간.hwpx" in line and "항목 1개" in line and line.level == "ok"


def test_apply_convert_restates_a_structure_refusal(tmp_path):
    """구간 컴파일 거절은 조용히 사라지지 않는다 — 결과 문구가 사유를 싣는다."""
    from hwpxfiller.gui.template_manager_state import ConvertResult

    vm, path = _structure_vm(tmp_path, "값: {{값}}")
    line = vm.format_convert_result(
        str(path), ConvertResult(fields=1, refusals=("이름 충돌",))
    )
    assert "누름틀 1개" in line and "구간 변환은 하지 못했습니다" in line
    assert "이름 충돌" in line and line.level == "warn"


def test_apply_convert_carries_a_structure_exception_with_the_mutation_fact(tmp_path):
    """구간 단계의 **예외**는 삼켜지지 않고 「이미 바뀌었다」와 함께 결과로 내려온다.

    필드 단계가 파일을 저장한 뒤 구간 단계가 raise 하면, 종전에는 예외가 호출자를 지나쳐
    재정산 통지가 통째로 빠졌다(#853 F-3). 예외를 result 로 바꾸는 것이지 숨기는 것이
    아니라서 사유가 문구에 그대로 남고 레벨은 danger 다.
    """
    from dataclasses import replace

    def boom(_path: str):
        raise ValueError("커널이 멈췄습니다")

    vm, path = _structure_vm(tmp_path, "값: {{값}}", *_NOTATION_LINES)
    vm._file_ops = replace(vm._file_ops, compile_structure_file=boom)

    result = vm.apply_convert(str(path))

    assert (result.fields, result.slots, result.mutated) == (3, 0, True)
    assert result.failed is True and result.refused is False
    line = vm.format_convert_result(str(path), result)
    assert line.level == "danger"
    assert "구간 변환이 중단됐습니다" in line and "커널이 멈췄습니다" in line
    assert "누름틀 3개는 저장됐습니다" in line  # 변이 사실이 문구에 선다


def test_apply_convert_reports_no_mutation_when_nothing_changed(tmp_path):
    """무변이 거절은 ``mutated=False`` 다 — 통지 축이 이 한 필드로 판정된다(#853 F-4)."""
    vm, path = _structure_vm(tmp_path, "바꿀 것이 없는 본문입니다.")
    before = path.read_bytes()

    result = vm.apply_convert(str(path))

    assert (result.fields, result.mutated, result.refused) == (0, False, False)
    assert path.read_bytes() == before


def test_slot_view_projects_compiled_slots(tmp_path):
    """Slot 목록은 **투영**이다 — 판정 없이 id·label·선택 수를 편다."""
    vm, path = _structure_vm(tmp_path, *_NOTATION_LINES)
    vm.apply_convert(str(path))

    view = vm.slot_view(str(path))
    assert view.name == "구간.hwpx" and view.diagnostics == ()
    assert [(row.id, row.label, row.option_count) for row in view.rows] == [
        ("특약", "특약 사항", 1)
    ]
    assert view.rows[0].options == ("지체상금 조항",)
    assert view.summary() == "항목 1개 · 선택 1개"


def test_slot_verbs_go_through_the_ports_and_reproject(tmp_path):
    """개명·풀기·삭제가 파일을 바꾸고 목록을 다시 투영한다."""
    vm, path = _structure_vm(tmp_path, *_NOTATION_LINES)
    vm.apply_convert(str(path))

    renamed = vm.rename_slot(str(path), "특약", "새 이름")
    assert renamed.rows[0].label == "새 이름"

    decompiled = vm.decompile_slot(str(path), "특약")
    assert decompiled.rows == ()
    assert vm.convert_preview(str(path)).slots == 1  # 표기로 돌아왔다

    vm.apply_convert(str(path))
    removed = vm.remove_slot(str(path), "특약")
    assert removed.rows == ()
    assert vm.convert_preview(str(path)).slots == 0  # 내용째 사라졌다


def test_slot_confirm_texts_restate_the_transition_and_the_loss(tmp_path):
    """확인 문안: 풀기는 **전이 결과**를, 삭제는 **손실 집합**을 재진술한다."""
    vm, path = _structure_vm(tmp_path, *_NOTATION_LINES)
    vm.apply_convert(str(path))

    decompile_text = vm.confirm_decompile_text(str(path), "특약")
    assert "구간 표기로 되돌립니다" in decompile_text
    assert "문서를 만들 수 없습니다" in decompile_text
    assert "구간.hwpx" in decompile_text

    remove_text = vm.confirm_remove_slot_text(str(path), "특약")
    assert "사라지는 것:" in remove_text and "선택 1개" in remove_text
    assert "구간.hwpx" in remove_text

    # 문안 규율: em dash 금지·낫표 금지(COPY_STYLE_GUIDE §3).
    for text in (decompile_text, remove_text):
        assert "—" not in text and "「" not in text


def test_rows_carry_fill_precheck_warns(tmp_path):
    """행에 채움 완화 사전 고지(#154)가 실린다 — 정상 템플릿은 무고지."""
    marker = tmp_path / "marker.hwpx"
    _write_raw(
        marker,
        '<hp:p><hp:run><hp:ctrl><hp:fieldBegin name="공고명"/></hp:ctrl></hp:run>'
        "<hp:run><hp:t>V<hp:markpenBegin/><hp:markpenEnd/></hp:t></hp:run>"
        '<hp:run><hp:ctrl><hp:fieldEnd/></hp:ctrl></hp:run></hp:p>',
    )
    clean = tmp_path / "clean.hwpx"
    _write_raw(
        clean,
        '<hp:p><hp:run><hp:ctrl><hp:fieldBegin name="공고명"/></hp:ctrl></hp:run>'
        "<hp:run><hp:t>값</hp:t></hp:run>"
        '<hp:run><hp:ctrl><hp:fieldEnd/></hp:ctrl></hp:run></hp:p>',
    )
    vm = TemplateManagerViewModel(
        paths=[marker, clean],
        inspect_template=inspect_hwpx_template,
        file_ops=HWPX_TEMPLATE_OPS,
    )
    vm.refresh()
    by_name = {r.name: r for r in vm.rows()}
    assert len(by_name["marker"].fill_warns) == 1
    assert "markpenBegin" in by_name["marker"].fill_warns[0]
    assert "제거됩니다" in by_name["marker"].fill_warns[0]  # 사전형 문안
    assert by_name["clean"].fill_warns == ()  # 과경고 금지


# ============================ 구간 표기 잔존의 행 전파(S8-04 #835 — 표면 전파)
def test_row_surfaces_residual_structure_notation_with_repair_verb(tmp_path):
    """컴파일된 필드 + 잔존 표기 파일의 행: PARTIAL 배지 · 수치 병기 · 수선 동사 노출.

    링1 이 판정을 그대로 실어 나르는지만 본다 — 행이 상태를 다시 조립하면 배지와 상세가
    갈린다(같은 상태의 두 번째 판정 금지).
    """
    inner = (
        "<hp:p><hp:run><hp:t>{{#항목 특약 특약 사항}}</hp:t></hp:run></hp:p>"
        "<hp:p><hp:run><hp:t>계약명: {{계약명}}</hp:t></hp:run></hp:p>"
        "<hp:p><hp:run><hp:t>{{/항목}}</hp:t></hp:run></hp:p>"
    )
    path = _write_compiled(tmp_path / "notation.hwpx", inner)
    status = template_compile_status(str(path))
    assert (status.state, status.structure_marker_n) == (CompileState.PARTIAL, 2)

    vm = TemplateManagerViewModel(
        paths=[path],
        inspect_template=inspect_hwpx_template,
        file_ops=HWPX_TEMPLATE_OPS,
    )
    row = vm.row_for(str(path))

    assert row.state == CompileState.PARTIAL
    assert row.badge_label == "부분 변환" and row.badge_level == "warn"
    assert row.structure_marker_n == 2
    assert "구간 표기 2개" in row.detail_line()
    assert [a.label for a in row.actions()] == ["마저 변환", "검토"]


def test_row_without_notation_says_nothing_about_it(tmp_path):
    """양성 대조 — 표기가 없으면 상세 줄에 그 축이 등장하지 않는다(빈 수치 노출 금지)."""
    path = _write_compiled(
        tmp_path / "clean.hwpx", "<hp:p><hp:run><hp:t>계약명: {{계약명}}</hp:t></hp:run></hp:p>"
    )
    vm = TemplateManagerViewModel(
        paths=[path],
        inspect_template=inspect_hwpx_template,
        file_ops=HWPX_TEMPLATE_OPS,
    )
    row = vm.row_for(str(path))
    assert row.state == CompileState.COMPILED
    assert "구간 표기" not in row.detail_line()
