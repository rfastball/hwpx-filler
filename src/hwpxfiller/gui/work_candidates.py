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

    입력 순서를 보존한다 — 메인 순위(즐겨찾기·최근 사용, §19.3)는 :func:`rank_available`
    이 available 만 대상으로 따로 매긴다(판정과 정렬의 분리). 반환된 (작업, 판정) 쌍의 분류는 호출측이
    :data:`KIND_AVAILABLE` / :data:`KIND_NEEDS_ACTION` 으로 나눈다.
    """
    rows: "list[tuple[Job, WorkCompatibility]]" = []
    for job in jobs:
        compat = compatibility_for(job, fields)
        if compat.kind == KIND_EXCLUDED:
            continue
        rows.append((job, compat))
    return rows


#: 메인 후보 구획이 한 번에 보여 주는 최대 개수(§18.5 — 전체 합계 5, 구획별 5가 아니다).
MAIN_TOP_N = 5

#: 순위 계층(§19.3) — 즐겨찾기 → 최근 사용 → 미사용. 카드 표지의 근거이기도 하다.
TIER_FAVORITE = "favorite"
TIER_RECENT = "recent"
TIER_UNUSED = "unused"

_TIER_ORDER = {TIER_FAVORITE: 0, TIER_RECENT: 1, TIER_UNUSED: 2}


@dataclass(frozen=True)
class RankedWork:
    """순위가 매겨진 available 후보 1건 — 표면은 이 순서·계층을 그대로 그린다."""

    name: str
    tier: str
    #: 계층의 정렬 근거 시각(즐겨찾기=favorited_at, 최근 사용=last_run_at, 미사용="").
    at: str = ""


def rank_available(jobs: "list[Job]", fields: "list[str]") -> "list[RankedWork]":
    """현재 데이터에서 **선택 가능한** 작업의 메인 순위(§18.5·§19.3).

    정렬 = 즐겨찾기(``favorited_at`` 최신순) → 즐겨찾기가 아닌 최근 사용(``last_run_at``
    최신순) → 미사용(이름순)이며, 계층 안 동률은 모두 이름순이다. 자르지 않은 전체 순위를
    돌려준다 — 상위 :data:`MAIN_TOP_N` 만 쓸지는 표면 결정이고, 잘린 나머지의 존재는
    호출측이 정직하게 고지해야 하므로(조용한 절단 금지) 여기서 미리 버리지 않는다.

    ``needs_action`` 은 순위에 넣지 않는다(§18.5: 메인은 available 만). 확인 필요 목록은
    별도 표면(§19.5 문서 탐색, 후속 슬라이스)이 소유하고 그 전까지는 호출측이 같은
    :func:`candidate_rows` 결과에서 따로 추려 정직하게 병기한다.

    **최근 사용의 의미**(지도 §8.2 ②): master 의 ``last_run_at`` 은 **완주(전건 성공)**
    스탬프다. v6 §19.4 는 부분 성공도 최근 사용으로 치지만, 같은 절이 시안 mock 값이
    백엔드 의미를 덮지 않는다고 못 박았고 완주 술어는 세션 가드 무장 해제와 단일 출처라
    (#129) 여기서 갈라 놓지 않는다 — 표면 문안도 "마지막 성공 실행"으로 맞춘다.
    """
    ranked = [
        RankedWork(
            job.name,
            TIER_FAVORITE if job.favorited_at
            else (TIER_RECENT if job.last_run_at else TIER_UNUSED),
            job.favorited_at or job.last_run_at,
        )
        for job, compat in candidate_rows(jobs, fields)
        if compat.kind == KIND_AVAILABLE
    ]
    # 3단 안정 정렬: 이름순(최종 동률) → 시각 최신순(안정이라 동률은 이름순 유지) → 계층.
    # reverse=True 도 안정성을 지키므로 같은 시각끼리의 이름 순서가 뒤집히지 않는다.
    ranked.sort(key=lambda r: r.name)
    ranked.sort(key=lambda r: r.at, reverse=True)
    ranked.sort(key=lambda r: _TIER_ORDER[r.tier])
    return ranked


def suggested_work(ranked: "list[RankedWork]", *, active: str) -> str:
    """추천 작업 이름(§18.3 **개정판** — 자동 선택 삭제, F-02). 없으면 ``""``.

    추천은 **표지일 뿐 전이가 아니다**: 활성 작업(``active``)은 사용자 클릭 사건으로만
    바뀐다. 유일 후보라도 앱이 대신 고르면, 사용자가 고른 적 없는 작업의 게이트·파일명
    규칙이 화면의 진실이 된다(v6 상태전이 리뷰 F-02).

    발화 조건은 v6 가 자동 선택하려던 딱 그 자리로 한정한다 — 활성 작업이 없고 선택
    가능한 후보가 **정확히 1개**일 때. 2개 이상에서 1위를 추천하지 않는 것은 의도다:
    순위는 사용 이력의 관측이지 이 데이터에 맞는 문서라는 권위가 아니다.

    ``preferredWorkId``(명시 사건 유래 자동 선정)는 이 슬라이스에 **구현하지 않는다** —
    그 사건의 원천(문서 탐색·기본 데이터 확인 흐름)이 후속 슬라이스 소관이라 seam 을
    비워 둔다(없는 기능을 있는 척하지 않는다).
    """
    if active:
        return ""
    return ranked[0].name if len(ranked) == 1 else ""


#: 문서 탐색 탭(§18.6) — primary classification 은 현재 데이터 실행 가능성이다.
TAB_AVAILABLE = "available"
TAB_NEEDS_ACTION = "needs_action"


@dataclass(frozen=True)
class BrowseResult:
    """문서 탐색 한 판정 — 탭 건수는 **검색 전** 전체이고, 행은 검색 적용 결과다.

    건수를 검색 전으로 두는 건 탭 라벨(「사용 가능 N」·「확인 필요 M」)이 *데이터에 대한
    사실*이지 검색어에 대한 사실이 아니기 때문이다 — 검색 중에 탭 숫자가 흔들리면
    사용자가 "이 데이터에 몇 건이 있나"를 잃는다. 검색으로 0행이 되면 그 사실은 행 목록의
    빈 상태가 말한다(§18.6 탭 전환 뒤 검색어 유지와 같은 결).
    """

    tab: str
    rows: "tuple[dict, ...]"
    available_count: int
    needs_count: int
    #: 검색어가 걸러낸 건수(그 탭 전체 − 표시 행) — 0이 아니면 표면이 정직하게 고지한다.
    filtered_out: int = 0


def browse_candidates(
    jobs: "list[Job]", fields: "list[str]", *, tab: str, query: str = ""
) -> BrowseResult:
    """현재 데이터 문서 탐색(§18.6·§19.5) — 탭 분류 + 이름 검색의 단일 판정.

    - 분류는 :func:`candidate_rows` 그대로 소비한다(호환성 판정 단일 출처 §18.4).
    - 검색 대상은 **작업 표시 이름만**이다(§18.6 — 그룹·태그·매체·필드·소스 이름과 데이터
      경로는 대상이 아니다). 일치 규칙은 앱 전역과 같은 자모 부분일치
      (:mod:`~hwpxfiller.core.jamo`) — 검색 어휘를 이 표면만 다르게 발명하지 않는다.
    - 행은 이름순(결정적 순서). 메인 순위(§19.3)는 여기 쓰지 않는다: 탐색은 "찾기"이고
      순위는 "고르기"의 문법이라, 같은 목록에 두 정렬 근거를 겹치면 어느 쪽도 못 읽는다.
    """
    from ..core.jamo import jamo_contains

    rows = candidate_rows(jobs, fields)
    avail = sorted(
        ({"name": j.name, "missing": []} for j, c in rows if c.kind == KIND_AVAILABLE),
        key=lambda d: d["name"],
    )
    needs = sorted(
        (
            {"name": j.name, "missing": list(c.missing)}
            for j, c in rows
            if c.kind == KIND_NEEDS_ACTION
        ),
        key=lambda d: d["name"],
    )
    pool = needs if tab == TAB_NEEDS_ACTION else avail
    q = query.strip()
    shown = [r for r in pool if jamo_contains(r["name"], q)] if q else list(pool)
    return BrowseResult(
        tab=TAB_NEEDS_ACTION if tab == TAB_NEEDS_ACTION else TAB_AVAILABLE,
        rows=tuple(shown),
        available_count=len(avail),
        needs_count=len(needs),
        filtered_out=len(pool) - len(shown),
    )


def prework_gate(
    *, has_data: bool, selected_count: int, has_candidates: bool
) -> GateState:
    """작업 미선택 상태의 생성 게이트 — 단일 표시 결정(RC-23 동형, 링2 재조립 금지).

    데이터-우선 도입 순서(§18.2)대로 다음 할 일 하나만 말한다: 데이터 → 항목 선택 →
    문서 작업. "데이터 없음"과 "호환 작업 없음"은 구분해 재진술한다(§18.4 문안 3구분 —
    과경고도 과소경고도 없이, 막힌 실제 이유만). 작업이 선택되면 이 게이트는 퇴장하고
    권위 판정(``RunViewModel.refresh``)이 이어받는다.

    ``has_candidates`` 는 **선택 가능한(available) 후보의 존재**다 — needs_action 뿐인
    목록으로 True 를 주면 "선택하세요"가 이행 불가능한 지시가 된다(#302 리뷰 P2).
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
