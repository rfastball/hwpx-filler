"""좌 목록 그룹 구획 빌더 — 「작업」(HWPX)·「기안」(TXT) 두 master-detail 화면 공용(순수).

R-info 3부 결정 1·13: 저장 기계는 하나(JobRegistry)·화면은 둘이고, 각 화면이 자기 매체만
조회한다(조회 경계). 좌 목록의 **그룹 구획 파생**(이름순 안정·「그룹 없음」 마지막·퇴화 평면·
접힘 사영)은 매체와 무관한 순수 로직이라 여기 단일 출처로 둔다 — :class:`~hwpxfiller.webapp.
screen_job.JobController` 와 :class:`~hwpxfiller.webapp.screen_draft.DraftController` 가 같은
빌더를 쓴다(백엔드 사본 2벌 방지, JS 그룹 목록 팩토리[grouplist.js]의 백엔드 짝).

세션·매체 필터·접힘 영속 같은 표면별 상태는 각 컨트롤러가 소유하고, 이 함수들엔 이미
필터·정렬된 ``jobs`` 와 관측값(선택 이름·접힘 집합)만 넘긴다 — I/O·부작용 없음.
"""
from __future__ import annotations


def build_flat_rows(jobs, selected_name: str) -> "list[dict]":
    """그룹과 무관한 평면 뷰 — 이름 + 선택 표지. "전체 집합" 소비자(테스트·세션 판정)용.

    :func:`build_group_sections` 과 같은 ``jobs`` 를 받아 두 뷰가 어긋나지 않게 한다(호출측이
    ``list_jobs`` 를 1회 읽어 둘에 같은 목록을 넘긴다).
    """
    return [{"name": j.name, "selected": j.name == selected_name} for j in jobs]


def build_group_sections(
    jobs, selected_name: str, collapsed: "set[str]"
) -> "tuple[list[dict], bool]":
    """그룹 구획 뷰(결정 43·R-info 결정 4·6) — ``(sections, flat)`` 반환.

    - 그룹 배열 = 이름순 안정, 「그룹 없음」(``group==""``)은 마지막.
    - ``flat=True`` = 그룹 0개 **퇴화 불변식**: 헤더·들여쓰기 없는 평면. 이때도 sections 는
      무그룹 1구획으로 돌아가 표면이 분기 없이 그린다.
    - ``collapsed`` 는 영속 접힘 집합(결정 6-①)의 사영 — 행은 접혀도 집합에서 빠지지 않는다
      (선택·세션 판정은 전체 집합 위 — 결정 6-⑤ 접어도 선택 유지).
    """
    grouped: "dict[str, list[dict]]" = {}
    for j in jobs:
        grouped.setdefault(j.group, []).append(
            {"name": j.name, "selected": j.name == selected_name}
        )
    named = sorted(g for g in grouped if g)
    flat = not named
    order = named + ([""] if "" in grouped else [])
    sections = [
        {
            "group": g,
            "collapsed": (not flat) and g in collapsed,
            "count": len(grouped[g]),
            "rows": grouped[g],
        }
        for g in order
    ]
    return sections, flat


def drift_note(seen, count: int) -> str:
    """확인 시점 건수와 실제 이동 건수가 갈라졌으면 그 사실을 말할 문구, 아니면 ``""``(#149).

    그룹 일괄 갱신(개명 병합·해산)의 확인 문안은 **잠금 밖 사전 카운트**로 만들어진다 —
    사용자가 모달을 읽는 사이 다른 표면이 작업을 옮기면 "N건" 이 실제와 어긋난다. 이동 자체는
    파괴가 아니고(소속만 바뀐다·삭제 없음) 잠금 안 일괄 갱신이 실제 건수를 돌려주므로,
    재확인까지 올리지 않고 **결과 재진술**로 갈음하되 어긋났으면 조용히 넘기지 않는다.
    """
    if not isinstance(seen, int) or seen == count:
        return ""
    return f" · 확인 시점 {seen}건과 다릅니다"
