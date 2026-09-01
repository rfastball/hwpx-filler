"""저장 폴더 도출(U3-06 · #879 → 전역화) — 설정한 저장 폴더 → 템플릿 옆 ``Results``.

같은 질문에 두 답이 있었다: 구식 축은 작업을 고르는 순간 템플릿 옆 ``Results`` 를 잡았고,
관리(hwpx) 축은 저장 폴더 미지정을 **생성 차단**으로 다뤘다. 이 모듈이 그 답 하나를 소유한다.

**세션 축은 없다.** 종전에는 그 위에 「이번 세션의 명시 지정」(``SOURCE_EXPLICIT``)이 한 층 더
있었다 — 같은 사용자가 같은 폴더를 작업마다 다시 고르게 만들고, 작업을 갈아타면 조용히
증발하는 값이었다. 저장 폴더는 **작업의 속성이 아니라 앱의 설정**이라는 재판정으로 그 층이
걷혔고, 남은 축은 둘뿐이다: 설정한 저장 폴더(존재 확인 통과분) → 템플릿 옆 ``Results``.

**조용한 추측이 아니라 표시된 기본값이다.** 도출은 경로만 내지 않고 그 경로가 어디서 왔는지
(:data:`SOURCE_LABELS`)를 함께 낸다. 표면은 실제로 쓰일 경로와 출처를 같이 그리고, 설정한
폴더가 사라져 기본값으로 내려간 경우는 :attr:`OutputFolderResolution.notice` 로 사유를 병기한다
(조용한 하향 금지).

**순수 함수다** — 파일 시스템을 만지지 않는다. 설정한 폴더가 실제로 있는지는 호출자가 관찰해
``remembered_exists`` 로 건넨다(관찰은 호출자, 판정은 여기).

설정값의 소유자도 여기가 아니다: 전역 저장 폴더는 설정 층
(:func:`hwpxfiller.external.settings.load_last_output_directory`)이 들고, 이 함수는 그 값을
**도출 재료로만** 받는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from hwpxfiller.domain.template_status import OUTPUT_SUBDIR_NAME

#: 설정에 남은 전역 저장 폴더(존재 확인 통과분). 값 이름은 영속 키와 함께 유지하되 의미는
#: 「지난 세션의 기억」이 아니라 **지금 설정된 값**으로 승격됐다.
SOURCE_REMEMBERED = "remembered"
#: 템플릿 옆 ``Results`` — 아무것도 설정되지 않았을 때의 기본값.
SOURCE_TEMPLATE_DEFAULT = "template_default"
#: 도출 불가(템플릿 경로 부재 등) — 저장 폴더를 정할 재료가 없다.
SOURCE_NONE = ""

#: 출처의 사용자 문안. 표면은 이 라벨을 그대로 그린다(재조립 금지).
SOURCE_LABELS: "dict[str, str]" = {
    SOURCE_REMEMBERED: "설정한 저장 폴더",
    SOURCE_TEMPLATE_DEFAULT: "기본값",
}

_REMEMBERED_MISSING_WITH_FALLBACK = (
    "설정한 저장 폴더를 찾을 수 없습니다. 기본 폴더로 되돌렸습니다."
)
_REMEMBERED_MISSING_WITHOUT_FALLBACK = (
    "설정한 저장 폴더를 찾을 수 없습니다. 설정에서 저장 폴더를 선택하세요."
)


def _is_full_path(directory: str) -> bool:
    """전체 경로인가 — 순수 판정이다(파일 시스템을 묻지 않는다)."""
    return bool(directory) and Path(directory).is_absolute()


def default_output_directory(template_path: str) -> str:
    """템플릿 옆 ``Results`` 경로. 템플릿 경로가 없으면 ``""``(도출 불가).

    구식 축이 작업 선택에서 잡는 값과 **같은 함수**다 — 두 축이 같은 기본값을 봐야 어긋나지
    않는다(하위폴더 이름의 정본은 :data:`~hwpxfiller.domain.template_status.OUTPUT_SUBDIR_NAME`).
    """
    if not template_path:
        return ""
    return str(Path(template_path).parent / OUTPUT_SUBDIR_NAME)


@dataclass(frozen=True)
class OutputFolderResolution:
    """도출된 저장 폴더 + 출처 + 사유 문안(표면은 읽기만 한다)."""

    directory: str
    source: str
    notice: str = ""

    @property
    def resolved(self) -> bool:
        """실제로 쓸 폴더가 정해졌는가 — False 면 저장 폴더 지정이 여전히 전제조건이다."""
        return bool(self.directory)

    @property
    def source_label(self) -> str:
        """출처의 사용자 문안 — 미도출이면 ``""``."""
        return SOURCE_LABELS.get(self.source, "")


def resolve_output_folder(
    *,
    remembered_directory: str = "",
    remembered_exists: bool = False,
    template_path: str = "",
) -> OutputFolderResolution:
    """저장 폴더 도출 — ① 설정한 전역 저장 폴더 ② 템플릿 옆 ``Results``.

    ①은 **존재 확인을 통과할 때만** 산다. 사라진 폴더를 조용히 쓰면 생성이 뒤늦게 실패하거나
    사용자가 모르는 자리에 문서가 떨어진다 — 기본값으로 내리고 ``notice`` 로 사유를 남긴다.
    둘 다 재료가 없으면(템플릿 경로 부재·전체 경로 아님) ``directory=""`` 로 **도출 불가**를
    진술한다 — 그때만 저장 폴더 지정이 생성의 전제조건으로 남는다.
    """
    fallback = default_output_directory(template_path)
    if not _is_full_path(fallback):
        # 전체 경로가 아니면 어디를 가리키는지 실행 시점에 결정된다 — 기본값으로 세우지 않고
        # 지정을 요구한다(작업 디렉터리를 따라 움직이는 자리에 문서를 떨구지 않는다).
        fallback = ""
    fallback_source = SOURCE_TEMPLATE_DEFAULT if fallback else SOURCE_NONE
    if remembered_directory and remembered_exists and _is_full_path(remembered_directory):
        return OutputFolderResolution(remembered_directory, SOURCE_REMEMBERED)
    if remembered_directory:
        return OutputFolderResolution(
            fallback,
            fallback_source,
            _REMEMBERED_MISSING_WITH_FALLBACK
            if fallback
            else _REMEMBERED_MISSING_WITHOUT_FALLBACK,
        )
    return OutputFolderResolution(fallback, fallback_source)
