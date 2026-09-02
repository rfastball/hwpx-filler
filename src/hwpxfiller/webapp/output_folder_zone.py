"""저장 폴더 존 — 「어디에 저장되는가」를 **한 함수가** 답한다(U6-D #978).

저장 폴더는 전역 설정이고 판정은 링0 순수 함수
(:func:`~hwpxfiller.domain.output_folder_default.resolve_output_folder`) 하나다. 그런데 그
판정에 먹일 **관찰**(설정한 폴더가 지금도 있는가)과 그 결과의 **스냅샷 모양**은 호출자
쪽에 산다 — 두 화면이 각자 관찰하고 각자 사전을 조립하면, 링0 이 하나여도 두 화면이 다른
값을 그리는 자리가 다시 생긴다(하향 사유를 한쪽만 싣는 것으로 충분하다).

그래서 이 모듈이 그 두 가지를 진다. 「문서 만들기」의 저장 폴더 표시와 편집기 3단계의
읽기 전용 재진술이 같은 함수를 부르고, 갈리는 것은 **어느 템플릿 옆을 기본값으로 보는가**
하나다(작업 화면은 앉은 작업의 템플릿, 편집기는 이 세션의 템플릿).

값을 바꾸는 동사는 여기 없다 — 고르는 자리는 설정 모달 하나다(`docs/UI_CONTRACT.md`
「저장 폴더 — 전역 단일 값」).
"""

from __future__ import annotations

from pathlib import Path

from ..domain.output_folder_default import (
    OutputFolderResolution,
    resolve_output_folder,
)


def output_folder_resolution(
    *, template_path: str, remembered_directory: str
) -> OutputFolderResolution:
    """지금 쓸 저장 폴더 도출 — 관찰(존재 확인)을 여기서 하고 판정은 링0 에 맡긴다."""
    return resolve_output_folder(
        remembered_directory=remembered_directory,
        remembered_exists=bool(remembered_directory)
        and Path(remembered_directory).is_dir(),
        template_path=template_path,
    )


def output_folder_zone(
    *, template_path: str, remembered_directory: str
) -> "dict[str, str]":
    """스냅샷의 ``output_folder`` 존 — 표면은 읽기만 하고 재판정·재조립하지 않는다.

    ``notice`` 는 설정한 폴더가 사라져 기본값으로 내려간 사유다(조용한 하향 금지). 빈
    문자열이면 말할 것이 없다는 뜻이고, 표면이 그 자리를 다른 문장으로 채우지 않는다.
    """
    resolution = output_folder_resolution(
        template_path=template_path, remembered_directory=remembered_directory
    )
    return {
        "directory": resolution.directory,
        "source": resolution.source,
        "source_label": resolution.source_label,
        "notice": resolution.notice,
    }
