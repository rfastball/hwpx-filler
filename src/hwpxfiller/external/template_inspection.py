"""HWPX 템플릿 판독·컴파일 파일 효과의 외부 어댑터.

파서 의미론 층(schema·authoring·template_status·lint·fields)은 **열린 package 전용**이다
(P2-19R, #576). 경로를 받아 package adapter로 한 번 열고 Domain 순수
함수를 부르는 path 진입 함수들이 여기 산다 — ring 2/Host 는 직접 부르고, Application VM
(gui)은 External 을 import 할 수 없어 ring 2 가 이 함수들을 포트로 결속해 주입한다
(P2-12 ``inspect_hwpx_template`` 동형).
"""

from __future__ import annotations

from pathlib import Path

from ..core.authoring import CompileReport, TokenSite, compile_document, scan_tokens
from ..core.fields import fill_precheck, read_fields
from ..core.lint import LintReport, SchemaDrift, diff_schema, lint_template
from ..core.template_status import TemplateStatus, compile_status
from ..gui.template_manager_state import TemplateFileOps, TemplateInspection
from .hwpx_package_io import read_hwpx_package, write_hwpx_package


def inspect_hwpx_template(path: str) -> TemplateInspection:
    """경로를 한 번 열고 같은 패키지 스냅샷에서 상태와 사전고지를 계산한다."""
    package = read_hwpx_package(path)
    return TemplateInspection(
        status=compile_status(package),
        precheck_notes=tuple(fill_precheck(package)),
    )


def template_compile_status(path: str) -> TemplateStatus:
    """경로 → 컴파일 수명주기 상태(C2). 홈/라이브러리 배지 파생 포트의 concrete."""
    return compile_status(read_hwpx_package(path))


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

    (P2-19R 에서 ``core.authoring`` 이월 — 경로 열기·충돌 검사·저장이 파일 IO 개시라
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
    diff=diff_template_schemas,
    read_fields=read_template_fields,
)
