"""템플릿 관리 워크숍 ViewModel(C5) 계약 테스트 — Qt/QApplication 불필요(링1, Qt-free).

핵심 증명:
1. 상태별(RAW/PARTIAL/COMPILED/FILLED) 게이트 액션이 정확히 합의된 집합이다.
2. fieldize dry-run(scan_preview)은 파일을 만지지 않고 미리보기만; 적용(apply_fieldize)만
   컴파일·저장하고 그 파일의 compile_status 가 진행한다(RAW/PARTIAL → COMPILED).
3. lint/drift 결과가 VM 을 통해 렌더된다.

파일 하단에 offscreen GUI 스모크(PySide6 있을 때만)를 얹는다 — 위젯이 VM 을 카드로
렌더하고 상태별 버튼을 배선하는 최소 배선 확인.
"""

from __future__ import annotations

from pathlib import Path

from hwpxfiller.core.authoring import compile_document
from hwpxfiller.core.fields import FieldDocument
from hwpxfiller.core.template_status import CompileState, compile_status
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
    _pkg(section_inner).save(str(path))
    return path


def _write_compiled(path: Path, section_inner: str) -> Path:
    """평문 토큰을 컴파일한 템플릿을 파일로 저장(COMPILED)."""
    pkg, _ = compile_document(_pkg(section_inner))
    pkg.save(str(path))
    return path


def _write_filled(path: Path, section_inner: str, field: str, value: str) -> Path:
    """컴파일 후 값 1개 주입한 템플릿을 파일로 저장(FILLED)."""
    pkg, _ = compile_document(_pkg(section_inner))
    doc = FieldDocument(pkg.entries[SECTION])
    assert doc.set_field(field, value) is True
    pkg.entries[SECTION] = doc.to_bytes()
    pkg.save(str(path))
    return path


# =============================================== 수용기준 1 — 상태별 게이트 액션
def test_available_actions_per_state_exact_sets():
    """각 상태가 정확히 합의된 액션 키 집합을 제공한다(순수 리졸버)."""
    assert [a.key for a in available_actions(CompileState.RAW)] == ["compile"]
    assert [a.key for a in available_actions(CompileState.PARTIAL)] == ["compile", "review"]
    assert [a.key for a in available_actions(CompileState.COMPILED)] == ["preview", "make_job"]
    assert [a.key for a in available_actions(CompileState.FILLED)] == ["preview"]


def test_action_labels_are_state_contextual():
    """같은 key='compile' 라도 RAW='누름틀 변환' / PARTIAL='마저 변환' 으로 문맥화된다."""
    assert available_actions(CompileState.RAW)[0].label == "누름틀 변환"
    assert available_actions(CompileState.PARTIAL)[0].label == "마저 변환"


def test_error_or_none_state_offers_no_actions():
    assert available_actions(None) == []


def test_vm_actions_for_delegates_to_resolver(tmp_path):
    vm = TemplateManagerViewModel(paths=[])
    assert [a.key for a in vm.actions_for(CompileState.COMPILED)] == ["preview", "make_job"]


def test_library_scan_is_recursive(tmp_path):
    """R-info 2부 결정 5 — 하위폴더의 .hwpx 도 재귀로 찾는다(비재귀 glob 이던 시절 조용한 누락)."""
    _write_raw(tmp_path / "루트.hwpx", "<hp:p><hp:run><hp:t>계약명: {{계약명}}</hp:t></hp:run></hp:p>")
    sub = tmp_path / "탐색기묶음"
    sub.mkdir()
    _write_raw(sub / "하위.hwpx", "<hp:p><hp:run><hp:t>계약명: {{계약명}}</hp:t></hp:run></hp:p>")
    vm = TemplateManagerViewModel(library_dir=tmp_path)
    names = {r.name for r in vm.rows()}
    assert names == {"루트.hwpx", "하위.hwpx"}  # 하위폴더 파일도 평평하게 올라온다


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
    vm = TemplateManagerViewModel(library_dir=tmp_path)
    assert {r.name for r in vm.rows()} == {"서식.hwpx"}  # 산출물은 목록에 없다


def test_rows_expose_gated_actions_matching_state(tmp_path):
    """VM 행이 실제 파일 상태에서 계산한 액션 집합을 노출한다(라이브러리 전 상태)."""
    raw = _write_raw(tmp_path / "raw.hwpx", "<hp:p><hp:run><hp:t>계약명: {{계약명}}</hp:t></hp:run></hp:p>")
    comp = _write_compiled(tmp_path / "comp.hwpx", "<hp:p><hp:run><hp:t>계약명: {{계약명}}</hp:t></hp:run></hp:p>")
    filled = _write_filled(
        tmp_path / "fill.hwpx",
        "<hp:p><hp:run><hp:t>계약명: {{계약명}}</hp:t></hp:run></hp:p>",
        "계약명", "정보시스템 구축",
    )
    vm = TemplateManagerViewModel(library_dir=tmp_path)
    by_name = {r.name: r for r in vm.rows()}

    assert by_name["raw.hwpx"].state == CompileState.RAW
    assert [a.key for a in by_name["raw.hwpx"].actions()] == ["compile"]
    assert by_name["comp.hwpx"].state == CompileState.COMPILED
    assert [a.key for a in by_name["comp.hwpx"].actions()] == ["preview", "make_job"]
    assert by_name["fill.hwpx"].state == CompileState.FILLED
    assert [a.key for a in by_name["fill.hwpx"].actions()] == ["preview"]
    # 배지·상세가 성형돼 위젯이 읽을 수 있다.
    assert by_name["raw.hwpx"].badge_label == "원문"
    assert "필드" in by_name["comp.hwpx"].detail_line()


# ================================ 수용기준 2 — dry-run 무변형 → 적용 시 상태 진행
def test_scan_preview_is_readonly_and_previews_sites(tmp_path):
    """scan_preview 는 컴파일 가능/건너뜀을 미리 보여주되 파일을 만지지 않는다."""
    path = _write_raw(tmp_path / "t.hwpx", "<hp:p><hp:run><hp:t>계약명: {{계약명}}</hp:t></hp:run></hp:p>")
    before = path.read_bytes()

    vm = TemplateManagerViewModel(paths=[path])
    preview = vm.scan_preview(str(path))

    assert preview.has_compilable
    assert [s.name for s in preview.compilable] == ["계약명"]
    assert path.read_bytes() == before  # 무변형(dry-run)
    assert compile_status(str(path)).state == CompileState.RAW  # 여전히 RAW


def test_apply_fieldize_compiles_and_advances_status(tmp_path):
    """적용은 컴파일·저장하고 그 파일 상태가 RAW → COMPILED 로 진행한다."""
    path = _write_raw(tmp_path / "t.hwpx", "<hp:p><hp:run><hp:t>계약명: {{계약명}}</hp:t></hp:run></hp:p>")
    assert compile_status(str(path)).state == CompileState.RAW

    vm = TemplateManagerViewModel(paths=[path])
    report = vm.apply_fieldize(str(path))

    assert report.compiled == ["계약명"]
    assert report.modified
    assert compile_status(str(path)).state == CompileState.COMPILED  # 진행
    # VM 행도 재산출돼 COMPILED 로 갱신(그리고 액션 집합도 전이).
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
    _pkg(inner).save(str(path))
    assert compile_status(str(path)).state == CompileState.PARTIAL

    vm = TemplateManagerViewModel(paths=[path])
    vm.apply_fieldize(str(path))
    assert compile_status(str(path)).state == CompileState.COMPILED


# =================================================== 수용기준 3 — lint / drift
def test_lint_reports_near_duplicate_fields(tmp_path):
    """공백만 다른 유사 필드명(계약명 vs 계약 명)을 VM lint 가 near_duplicate 로 신고."""
    path = _write_compiled(
        tmp_path / "dup.hwpx",
        "<hp:p><hp:run><hp:t>계약명: {{계약명}} / 상대: {{계약 명}}</hp:t></hp:run></hp:p>",
    )
    vm = TemplateManagerViewModel(paths=[path])
    report = vm.lint(str(path))
    kinds = {f.kind for f in report.findings}
    assert "near_duplicate" in kinds
    assert report.has_issues


def test_lint_reports_stray_compilable_token(tmp_path):
    """미컴파일 평문 토큰이 남으면 lint 가 stray_token(fieldize 권장)으로 신고."""
    path = _write_raw(tmp_path / "raw.hwpx", "<hp:p><hp:run><hp:t>계약명: {{계약명}}</hp:t></hp:run></hp:p>")
    vm = TemplateManagerViewModel(paths=[path])
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
    vm = TemplateManagerViewModel(paths=[])
    drift = vm.drift(str(old), str(new))
    assert drift.has_changes
    assert "사업예산" in drift.added
    assert "금액" in drift.removed


# ==================================================== 라이브러리/오류 노출
def test_empty_library_is_empty(tmp_path):
    vm = TemplateManagerViewModel(library_dir=tmp_path)
    assert vm.is_empty()
    assert vm.count_label() == ""


def test_unreadable_file_surfaced_as_error_row_not_hidden(tmp_path):
    """읽기 실패 파일은 조용히 감추지 않고 error 행으로 시끄럽게 노출한다."""
    bad = tmp_path / "broken.hwpx"
    bad.write_bytes(b"not a zip at all")
    vm = TemplateManagerViewModel(library_dir=tmp_path)
    rows = vm.rows()
    assert len(rows) == 1
    assert rows[0].is_error
    assert rows[0].state is None
    assert rows[0].actions() == []


def test_filled_values_preview_reads_c1_fields(tmp_path):
    """FILLED 미리보기 값은 C1 read_fields 로 읽는다."""
    path = _write_filled(
        tmp_path / "fill.hwpx",
        "<hp:p><hp:run><hp:t>계약명: {{계약명}}</hp:t></hp:run></hp:p>",
        "계약명", "정보시스템 구축",
    )
    vm = TemplateManagerViewModel(paths=[path])
    assert vm.filled_values(str(path)) == {"계약명": "정보시스템 구축"}


# ============================================ RC-14 — 기본 라이브러리·빈상태·성형
def test_default_templates_dir_honors_env_override(monkeypatch, tmp_path):
    """링0 기본 템플릿 라이브러리 루트 — HWPXFILLER_HOME 재지정(기존 루트 4종 미러)."""
    from hwpxfiller.core.template_status import default_templates_dir

    monkeypatch.setenv("HWPXFILLER_HOME", str(tmp_path))
    assert default_templates_dir() == tmp_path / "templates"


def test_vm_lint_accepts_vocabulary(tmp_path):
    """VM.lint(path, vocabulary=None) 가 코어 lint_template 시그니처와 정렬(RC-14).

    통제 어휘를 주면 어휘 밖 필드명이 off_vocabulary 로 신고된다 — CLI --vocab 과
    GUI 위생 점검 범위 동등.
    """
    path = _write_compiled(
        tmp_path / "v.hwpx",
        "<hp:p><hp:run><hp:t>계약명: {{계약명}}</hp:t></hp:run></hp:p>",
    )
    vm = TemplateManagerViewModel(paths=[path])
    assert "off_vocabulary" not in {f.kind for f in vm.lint(str(path)).findings}  # 기본: 어휘 검사 없음
    report = vm.lint(str(path), vocabulary=["표준필드명"])
    assert "off_vocabulary" in {f.kind for f in report.findings}


def test_vm_set_library_dir_and_empty_hint_distinguish_missing_vs_empty(tmp_path):
    """'폴더 없음'과 '빈 폴더'를 구분 안내하고, 폴더 재지정이 재스캔한다(RC-14 W6)."""
    missing = tmp_path / "없는폴더"
    vm = TemplateManagerViewModel(library_dir=missing)
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
    vm = TemplateManagerViewModel(paths=[raw])

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
    vm = TemplateManagerViewModel(paths=[raw])
    line = vm.format_scan_empty_result(str(raw), ScanPreview(compilable=[], skipped=[]))
    assert "onlymanual.hwpx" in line and "변환 가능한 토큰이 없습니다" in line
    assert line.level == "warn"
