"""데이터-우선 후보 판정(링1) — 현재 데이터 필드에 대한 저장 작업의 최소 호환성.

v6 워크플로 계약 §18.4 의 이식(정본: ``lab/ui-reboot`` 태그 ``prototype-v6-freeze`` 의
``docs/core-workflow.md``; 봉합 지도: ``docs/DATA_FIRST_INTEGRATION_MAP.md``).

계약 국경 세 가지:

- **최소 Binding 호환성만 판정한다** — 매핑이 읽는 소스 키 전체(:meth:`Job.source_keys`,
  blank 선언 제외)가 현재 데이터 ``fields`` 에 존재하는가. blank 선언 필드와 데이터의
  새 열은 호환을 깨지 않는다. v6 의 "required" 는 master 어휘로 ``source_keys()`` 다 —
  blank 매핑 제외가 이미 그 안에 있고, 상수 입력의 공백은 소스 요구가 아니라
  :class:`~hwpxfiller.gui.run_state.RunViewModel` 빈값 게이트 소관이다.
- **``available`` 은 실행 완료를 보장하지 않는다** — 권위 판정은 작업 선택 뒤
  ``RunViewModel.refresh()`` (템플릿 구조 드리프트·빈 값·출력 폴더는 거기서 본다).
  전역 작업 건강(템플릿 파손 등)과도 섞지 않는다(§19.7) — 여기는 현재 데이터 호환성만.
- **매체 국경(§19.1)** — hwpx 만 실행 후보다. txt 는 「기안」 화면 소유, 미상 확장자는
  fail-closed 제외(모르는 것을 hwpx 로 추측하지 않는다).

데이터 미준비 시 호출하지 않는 것(§18.1)은 호출측(컨트롤러) 의무다 — 이 모듈은
마운트된 fields 를 받는 순수 판정만 한다.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .run_state import GateState

if TYPE_CHECKING:
    from ..core.job import Job

#: 현재 데이터로 바로 선택 가능(최소 호환) — 실행 보장은 아니다.
KIND_AVAILABLE = "available"
#: 필수 소스 키가 현재 데이터에 없음 — 선택 전 연결 확인이 필요하다.
KIND_NEEDS_ACTION = "needs_action"
#: 실행 후보 자체가 아님(매체 국경) — 목록에서 fail-closed 로 빠진다.
KIND_EXCLUDED = "excluded"


@dataclass(frozen=True)
class WorkCompatibility:
    """작업 1건의 현재-데이터 호환성 — 단일 판정(§18.4), 모든 소비자가 이것만 본다."""

    kind: str
    #: 현재 데이터에 없는 필수 소스 키(문서순) — needs_action 일 때만 비지 않는다.
    missing: "tuple[str, ...]" = ()
    #: excluded 사유: ``"media"`` (txt=기안 소유) | ``"unsupported"`` (미상 확장자).
    reason: str = ""


def compatibility_for(job: "Job", fields: "list[str]") -> WorkCompatibility:
    """작업 1건 × 현재 데이터 fields 의 최소 호환성 — 호환성 판정의 단일 출처.

    빈 매핑 작업은 요구 소스가 없어 자명하게 ``available`` 이다(퇴화 허용) —
    실제 생성 가능성은 어차피 권위 판정(RunViewModel)이 다시 본다.
    """
    media = job.media
    if media != "hwpx":
        return WorkCompatibility(
            KIND_EXCLUDED, reason="media" if media == "txt" else "unsupported"
        )
    present = set(fields)
    missing = tuple(k for k in job.source_keys() if k not in present)
    if missing:
        return WorkCompatibility(KIND_NEEDS_ACTION, missing=missing)
    return WorkCompatibility(KIND_AVAILABLE)


def candidate_rows(
    jobs: "list[Job]", fields: "list[str]"
) -> "list[tuple[Job, WorkCompatibility]]":
    """저장 작업 전체 → 후보 목록. excluded 는 반환에서 제외(fail-closed, §19.1).

    입력 순서를 보존한다 — 정렬(즐겨찾기·최근 사용, §19.3)은 후속 슬라이스의 소관이고
    여기서 미리 흉내 내지 않는다. 반환된 (작업, 판정) 쌍의 분류는 호출측이
    :data:`KIND_AVAILABLE` / :data:`KIND_NEEDS_ACTION` 으로 나눈다.
    """
    rows: "list[tuple[Job, WorkCompatibility]]" = []
    for job in jobs:
        compat = compatibility_for(job, fields)
        if compat.kind == KIND_EXCLUDED:
            continue
        rows.append((job, compat))
    return rows


def prework_gate(
    *, has_data: bool, selected_count: int, has_candidates: bool
) -> GateState:
    """작업 미선택 상태의 생성 게이트 — 단일 표시 결정(RC-23 동형, 링2 재조립 금지).

    데이터-우선 도입 순서(§18.2)대로 다음 할 일 하나만 말한다: 데이터 → 항목 선택 →
    문서 작업. "데이터 없음"과 "호환 작업 없음"은 구분해 재진술한다(§18.4 문안 3구분 —
    과경고도 과소경고도 없이, 막힌 실제 이유만). 작업이 선택되면 이 게이트는 퇴장하고
    권위 판정(``RunViewModel.refresh``)이 이어받는다.
    """
    if not has_data:
        return GateState(False, "warn", "데이터 파일을 먼저 선택하세요.")
    if selected_count == 0:
        return GateState(False, "warn", "처리할 항목을 선택하세요.")
    if not has_candidates:
        return GateState(
            False, "warn", "현재 데이터에 사용할 수 있는 문서 작업이 없습니다."
        )
    return GateState(False, "warn", "문서 작업을 선택하세요.")
