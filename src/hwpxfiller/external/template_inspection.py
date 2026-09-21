"""HWPX 템플릿 판독·컴파일 파일 효과의 외부 어댑터.

파서 의미론 층(schema·authoring·template_status·lint·fields)은 **열린 package 전용**이다
(P2-19R, #576). 경로를 받아 package adapter로 한 번 열고 Domain 순수
함수를 부르는 path 진입 함수들이 여기 산다 — ring 2/Host 는 직접 부르고, Application VM
(gui)은 External 을 import 할 수 없어 ring 2 가 이 함수들을 포트로 결속해 주입한다
(P2-12 ``inspect_hwpx_template`` 동형).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from hwpxcore.package import HwpxPackage

from ..application.execution_structure import (
    LABELED_EXECUTION_QUALIFICATION_PROFILE_ID,
    LABELED_EXECUTION_STRUCTURE_PROJECTION_SCHEMA,
)
from ..application.qualification_evidence import (
    QualificationProfileManifest,
    build_manifest,
)
from ..application.template_qualification import QualificationProfile
from ..domain.authoring import (
    CompileReport,
    StructureScan,
    TokenSite,
    compile_document,
    scan_structure,
    scan_tokens,
)
from ..domain.fields import fill_precheck, read_fields
from ..domain.lint import LintReport, SchemaDrift, diff_schema, lint_template
from ..domain.schema import extract_schema
from ..domain.slot import Slot
from ..domain.template_status import TemplateStatus, compile_status
from ..gui.template_manager_state import (
    TemplateFileOps,
    TemplateInspection,
)
from .hwpx_package_io import read_hwpx_package, write_hwpx_package
from .hwpx_product_inspection import (
    ProductBookmarkInspection as ProductBookmarkInspection,
    ProductClassification as ProductClassification,
    ProductInspectionContractError as ProductInspectionContractError,
    ProductScopeObservation as ProductScopeObservation,
    ProductScopeRole as ProductScopeRole,
    inspect_product_bookmarks as inspect_product_bookmarks,
    inspect_slots as inspect_slots,
    serialize_slot_metatag as serialize_slot_metatag,
    serialize_slot_option_metatag as serialize_slot_option_metatag,
)
from .hwpx_qualification import inspect_hwpx_qualification as inspect_hwpx_qualification
from .hwpx_structure_ops import (
    DUPLICATE_SLOT_ID as DUPLICATE_SLOT_ID,
    StructureCompileRefusal as StructureCompileRefusal,
    StructureCompileRefusalKind as StructureCompileRefusalKind,
    StructureCompileReport as StructureCompileReport,
    compile_structure as compile_structure,
    decompile_slot as decompile_slot,
    decompile_structure as decompile_structure,
    remove_slot as remove_slot,
    remove_slot_option as remove_slot_option,
    rename_slot_label as rename_slot_label,
    structure_region_name as structure_region_name,
)


# Bump this identity whenever the HWPX qualification rule set or projection changes.
# v4(#773): 같은 read-only inspection 이 canonical label 과 composition-ready execution fact 를
# 함께 낸다. v3 는 label 만, v2 는 composition fact 만 실을 수 있어 둘 중 어느 것도 shipping
# Qualification 이 S4·S5 를 동시에 먹일 수 없었다.
HWPX_QUALIFICATION_PROFILE = QualificationProfile(
    LABELED_EXECUTION_QUALIFICATION_PROFILE_ID,
    inspect_hwpx_qualification,
)


def hwpx_qualification_manifest(created_at: str) -> "QualificationProfileManifest":
    """제품 HWPX profile 의 durable semantic manifest — profile identity 와 같은 곳에서 소유.

    S3-09 코디네이터가 최초 사용 시 qualification store 에 create-once 로 시딩한다. 버전
    문자열들은 profile id 처럼 **규칙이 바뀌면 함께 올린다** — manifest 는 immutable 이라
    같은 id 로 다른 의미를 다시 쓰는 경로가 없다.
    """
    return build_manifest(
        qualification_profile_id=HWPX_QUALIFICATION_PROFILE.id,
        media="hwpx",
        adapter_contract_version="hwpx-inspection-v4",
        product_rule_version="hwpx-qualification-rules-v4",
        # label·composition fact 는 operation 종류·피연산자·순서를 바꾸지 않는다.
        operation_alphabet_version="hwpx-operations-v1",
        projection_schema_version=LABELED_EXECUTION_STRUCTURE_PROJECTION_SCHEMA,
        manifest_payload={},
        created_at=created_at,
    )

def compile_structure_file(path: str) -> StructureCompileReport:
    """경로의 구간 표기를 컴파일해 **같은 경로에 저장**(변이가 있을 때만).

    거절·no-op 이면 파일을 한 바이트도 쓰지 않는다(:func:`compile_template_file` 선례).
    """
    package = read_hwpx_package(path)
    report = compile_structure(package)
    if report.modified:
        write_hwpx_package(path, package)
    return report


def _mutate_slot_file(
    path: str, mutate: "Callable[[object], None]"
) -> "tuple[Slot, ...]":
    """경로를 열어 Slot 동사 하나를 돌리고 **성공했을 때만** 같은 경로에 저장.

    동사가 거절하면(``ValueError``) 파일은 한 바이트도 바뀌지 않는다 —
    :func:`compile_structure_file` 과 같은 규율이다. 반환은 변이 뒤 제품 Slot 목록이라
    상위 링이 결과를 재진술하려고 파일을 다시 열지 않는다.
    """
    package = read_hwpx_package(path)
    mutate(package)
    write_hwpx_package(path, package)
    slots, _diagnostics = inspect_slots(package)
    return slots


def rename_slot_label_file(path: str, slot_id: str, label: "str | None" = None):
    """경로의 Slot label 을 바꾸고 제자리 저장(성공 시에만)."""
    return _mutate_slot_file(path, lambda pkg: rename_slot_label(pkg, slot_id, label))


def decompile_slot_file(path: str, slot_id: str):
    """경로의 Slot 하나를 구간 표기로 되돌리고 제자리 저장(성공 시에만)."""
    return _mutate_slot_file(path, lambda pkg: decompile_slot(pkg, slot_id))


def decompile_structure_file(path: str) -> "tuple[Slot, ...]":
    """경로의 **전 Slot** 을 구간 표기로 되돌리고 **같은 경로에 저장**(변이가 있을 때만).

    ``_mutate_slot_file`` 을 빌리지 않는 이유는 하나다 — 그쪽은 성공하면 늘 쓰지만 전체판은
    슬롯 0 no-op 이 실재해서 무변형 저장이 나온다. 거절·no-op 이면 파일을 한 바이트도 쓰지
    않는 규율은 :func:`compile_structure_file` 과 같다. 반환은 되돌린 선언 목록이다.
    """
    package = read_hwpx_package(path)
    decompiled = decompile_structure(package)
    if decompiled:
        write_hwpx_package(path, package)
    return decompiled


def remove_slot_file(path: str, slot_id: str):
    """경로의 Slot 하나를 **내용째** 지우고 제자리 저장(성공 시에만)."""
    return _mutate_slot_file(path, lambda pkg: remove_slot(pkg, slot_id))


def scan_template_structure(path: str) -> StructureScan:
    """경로 → 구간 표기 스캔(읽기 전용, 파일 무변형)."""
    return scan_structure(read_hwpx_package(path))


def inspect_hwpx_template(path: str) -> TemplateInspection:
    """경로를 한 번 열고 같은 패키지 스냅샷에서 상태와 사전고지를 계산한다."""
    package = read_hwpx_package(path)
    slots, diagnostics = inspect_slots(package)
    return TemplateInspection(
        status=compile_status(package),
        precheck_notes=tuple(fill_precheck(package)),
        fields=tuple(extract_schema(package).field_names()),
        slots=slots,
        diagnostics=diagnostics,
    )


def inspect_and_lint_hwpx_template(
    path: str, vocabulary: "list[str] | set[str] | None" = None
) -> "tuple[TemplateInspection, LintReport]":
    """경로를 **한 번** 열고 판독과 위생 점검을 같은 패키지 스냅샷에서 낸다(U6-E 리뷰 7).

    「자세히…」 한 번이 :func:`inspect_hwpx_template` 와 :func:`lint_template_file` 을 각각
    부르면 같은 파일을 두 번 연다 — 비용도 두 배지만, 무엇보다 **두 스냅샷**이 한 시트에
    얹혀 그 사이의 변경이 갈린 사실로 선다. 판정은 둘 다 기존 순수 함수 그대로다.
    """
    package = read_hwpx_package(path)
    slots, diagnostics = inspect_slots(package)
    inspection = TemplateInspection(
        status=compile_status(package),
        precheck_notes=tuple(fill_precheck(package)),
        fields=tuple(extract_schema(package).field_names()),
        slots=slots,
        diagnostics=diagnostics,
    )
    return inspection, lint_template(package, vocabulary=vocabulary)


def template_compile_status(path: str) -> TemplateStatus:
    """경로 → 컴파일 수명주기 상태(C2). 홈/라이브러리 배지 파생 포트의 concrete."""
    return compile_status(read_hwpx_package(path))


def hwpx_structure_marker_count(canonical_bytes: bytes) -> int:
    """bytes → 잔존 구간 표기 수. :func:`template_compile_status` 의 **bytes 얼굴**이다.

    managed 실행 admission(S8-F1 · #852)이 검문할 것은 staging 파일이 아니라 Candidate
    blob 의 exact bytes 라 경로 진입점이 맞지 않는다. 그래서 같은
    :func:`~hwpxfiller.domain.template_status.compile_status` 를 bytes 로 한 번 더 열 뿐,
    마커를 여기서 다시 세지 않는다 — 세는 주체는 스캐너 단일 출처
    (:attr:`~hwpxfiller.domain.authoring.StructureSummary.markers`)뿐이다(판정 이중화 금지).
    """
    return compile_status(HwpxPackage.from_bytes(canonical_bytes)).structure_marker_n


def scan_template_tokens(path: str) -> "list[TokenSite]":
    """경로 → 토큰 스캔 미리보기(읽기 전용, 파일 무변형)."""
    return scan_tokens(read_hwpx_package(path))


def compile_template_file(path: str) -> CompileReport:
    """경로의 토큰을 누름틀로 컴파일해 **같은 경로에 저장**(변경이 있을 때만).

    바뀐 게 없으면(``modified=False``) 아무것도 쓰지 않는다 — 종전
    ``TemplateManagerViewModel.apply_fieldize`` 의 저장 판정 그대로.
    """
    pkg, report = compile_document(read_hwpx_package(path))
    if report.modified:
        write_hwpx_package(path, pkg)
    return report


def compile_to_sibling(path: str, *, overwrite: bool = False) -> "tuple[str | None, CompileReport]":
    """토큰을 컴파일해 **원본 옆** ``<이름>.compiled.hwpx`` 로 저장(원본 무변형).

    출력 경로 파생·저장·충돌 정책을 뷰가 하드코딩하지 않는다(RC-28). 정책:

    - 바꿀 토큰이 없으면(``modified=False``) 아무것도 쓰지 않고 ``(None, report)``.
    - 컴파일본이 이미 있으면 ``overwrite=True`` 없이는 :class:`FileExistsError`
      (메시지 = 충돌 경로)로 시끄럽게 차단 — 조용한 덮어쓰기 금지(RC-02). 호출측이
      사용자 확정을 받은 뒤 ``overwrite=True`` 로 재호출한다.
    - 컴파일·저장 실패는 그대로 raise(호출측이 시끄럽게 표시).

    (P2-19R 에서 ``domain.authoring`` 과 분리 — 경로 열기·충돌 검사·저장이 파일 IO 개시라
    Domain 에 둘 수 없다. 의미 불변.)
    """
    pkg, report = compile_document(read_hwpx_package(path))
    if not report.modified:
        return None, report
    compiled_path = str(Path(path).with_suffix(".compiled.hwpx"))
    if Path(compiled_path).exists() and not overwrite:
        raise FileExistsError(compiled_path)
    write_hwpx_package(compiled_path, pkg)
    return compiled_path, report


def lint_template_file(
    path: str, vocabulary: "list[str] | set[str] | None" = None
) -> LintReport:
    """경로 → 단일 템플릿 위생 점검(읽기 전용)."""
    return lint_template(read_hwpx_package(path), vocabulary=vocabulary)


def diff_template_schemas(old_path: str, new_path: str) -> SchemaDrift:
    """두 경로의 판본 간 필드셋 드리프트(추가/삭제/개명 추정). 읽기 전용."""
    return diff_schema(read_hwpx_package(old_path), read_hwpx_package(new_path))


def read_template_fields(path: str) -> "dict[str, str]":
    """경로 → 모든 누름틀 현재 값(C1 read_fields)."""
    return read_fields(read_hwpx_package(path))


#: :class:`~hwpxfiller.gui.template_manager_state.TemplateFileOps` 의 concrete 결속 —
#: ring 2 가 ``TemplateManagerViewModel(file_ops=HWPX_TEMPLATE_OPS)`` 로 주입한다.
HWPX_TEMPLATE_OPS = TemplateFileOps(
    scan_tokens=scan_template_tokens,
    compile_file=compile_template_file,
    lint=lint_template_file,
    inspect_and_lint=inspect_and_lint_hwpx_template,
    diff=diff_template_schemas,
    read_fields=read_template_fields,
    scan_structure=scan_template_structure,
    compile_structure_file=compile_structure_file,
    rename_slot_label=rename_slot_label_file,
    decompile_slot=decompile_slot_file,
    decompile_structure=decompile_structure_file,
    remove_slot=remove_slot_file,
)
