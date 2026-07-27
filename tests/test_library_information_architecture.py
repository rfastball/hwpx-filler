"""H-05 부팅 랜딩 · 「문서 작업」 라이브러리 정보 위생 · 첫 실행 CTA 계약.

홈 화면은 재작성 F2 PR-A 에서 죽었고(지도 §10.8) 라이브러리가 그 자리를 이었다. 이 파일은
승계된 계약(부팅 랜딩·개수 타일 부재·조건부 경보 존치·빈 상태 CTA)을 새 표면에서 다시 못박고,
죽은 표면이 되살아나지 않는지를 함께 본다 — 삭제는 의무를 상속한다.
"""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
APP = (ROOT / "web" / "js" / "app.js").read_text(encoding="utf-8")
LIB = (ROOT / "web" / "js" / "screens" / "library.js").read_text(encoding="utf-8")
JOB = (ROOT / "web" / "js" / "screens" / "job.js").read_text(encoding="utf-8")
CSS = (ROOT / "web" / "css" / "app.css").read_text(encoding="utf-8")


def test_cold_boot_lands_on_jobs() -> None:
    assert 'data-scr="job" aria-current="true"' in INDEX
    assert '<section class="scr on" id="scr-job">' in INDEX
    assert 'data-scr="library" aria-current="true"' not in INDEX
    assert '<section class="scr on" id="scr-library">' not in INDEX
    assert 'const DEFAULT_SCREEN = "job"' in APP
    assert "go(DEFAULT_SCREEN)" in APP
    assert "if (!routingReady) return" in APP


def test_kpi_and_continue_surfaces_stay_removed_with_their_layout() -> None:
    for dead in ("homeKpis", "homeContinue", "renderKpis", "renderContinue"):
        assert dead not in INDEX + LIB
    for dead_rule in (".kpis{", ".kpi{", ".continue-runs{", ".continue-run{"):
        assert dead_rule not in CSS


def test_dead_home_surface_leaves_no_dom_or_css_behind() -> None:
    """홈 화면 사망(F2 PR-A) — 죽은 DOM·렌즈·CSS 가 남으면 다음 세션의 부활 경로가 된다."""
    for dead in ("scr-home", "homeBrowser", "homeJobs", "homeTxt", "homeRowMenu",
                 "homeGroupBy", "set_group_by"):
        assert dead not in INDEX + LIB + APP, f"죽은 홈 표면이 남아 있습니다: {dead}"
    for dead_rule in (".tracks{", ".jobbrowser{", ".tlist ", ".groupsec{"):
        assert dead_rule not in CSS, f"죽은 홈 CSS 가 남아 있습니다: {dead_rule}"
    assert not (ROOT / "web" / "js" / "screens" / "home.js").exists()


def test_library_keeps_conditional_alert_information() -> None:
    """경보 승계 — 개수 타일은 없어도 조치가 필요한 조건은 계속 시끄럽게 말한다."""
    assert 'id="libraryAlerts"' in INDEX
    assert "function renderAlerts" in LIB
    assert "missing_template_count" in LIB and "pool_corrupted" in LIB
    assert "renderCorrupt(s.corrupt_rows)" in LIB


def test_library_carries_the_four_axes_and_two_pane_skeleton() -> None:
    """§19.6 browser+detail — 축 4종과 2-pane 이 정적 DOM 에 서 있다."""
    for anchor in ('id="librarySearch"', 'id="libraryViewTabs"', 'id="libraryModeFilters"',
                   'id="libraryFacets"', 'id="libraryList"', 'id="libraryDetail"',
                   'id="libraryCount"', 'class="library-browser"'):
        assert anchor in INDEX, f"라이브러리 골격이 없습니다: {anchor}"
    # 보기 4종은 계약 표(§19.6) 그대로 — 하나라도 빠지면 그 투영에 도달할 길이 없다.
    for view in ("all", "recent", "favorites", "needsAction"):
        assert f'data-library-view="{view}"' in INDEX
    # 결과 수는 role=status 로 재진술한다 — 필터가 목록을 비운 사실이 조용히 지나가지 않게.
    assert 'id="libraryCount" tabindex="-1" role="status"' in INDEX
    # 2-pane 치수 계약(≥921px·≥760px)은 CSS 가 진다 — 그보다 좁으면 세로 퇴화.
    assert "@media(min-width:921px) and (min-height:760px)" in CSS


def test_library_row_keeps_favorite_outside_the_select_button() -> None:
    """§19.6 "행 선택 버튼 안에 즐겨찾기나 메뉴 버튼을 중첩하지 않는다".

    중첩하면 즐겨찾기 클릭이 행 선택을 함께 발화한다. 이 배치가 동시에 「표시 상한과 무관한
    도달성」(§8.4 2행)의 새 거처다 — 순위 밖 작업도 여기서 별을 켤 수 있다.
    """
    row = LIB.split("function rowHtml", 1)[1].split("function sectionHtml", 1)[0]
    main = row.split('class="lib-row-main"', 1)[1].split("</button>", 1)[0]
    assert "data-fav" not in main, "즐겨찾기 버튼이 행 선택 버튼 **안에** 있습니다(§19.6 위반)."
    assert 'class="lib-fav" data-fav=' in row


def test_empty_job_list_has_a_direct_new_job_cta_without_a_new_surface() -> None:
    empty = INDEX.split('id="jobListHwpxEmpty"', 1)[1].split("</aside>", 1)[0]
    assert 'id="jobEmptyNewBtn"' in empty
    assert 'class="muted job-empty"' in INDEX
    assert 'class="empty"' not in empty
    assert '$("jobEmptyNewBtn").addEventListener("click", startNewJob)' in JOB
    assert "EditorEntry.newDraft()" in JOB


def test_management_verbs_read_identity_from_the_unfiltered_detail() -> None:
    """리뷰 1R P1 — 관리 동사는 **상세 스냅샷**에서 정체를 읽는다.

    목록 구획(`sections`)은 보기·검색·facet 이 걸러 낸 투영이라 선택 행이 거기 없을 수 있다.
    거기서 읽으면 태그 프리필이 `{}` 로, 소속 그룹이 `""` 로 조작돼 사용자가 「확인」 한 번에
    실제 태그를 통째로 지우고 그룹을 벗겨 낸다 — 조용한 파괴다. 상세는 걸러지지 않은
    `rows()` 에서 성형되므로 선택이 살아 있는 한 언제나 있고, 없으면 꾸며내지 않고 멈춘다.
    """
    assert "function selectedWork" in LIB
    src = LIB[LIB.index("function selectedWork"):LIB.index("function allGroups")]
    assert "LAST.detail" in src, "선택 정체를 상세 스냅샷에서 읽지 않습니다(P1)."
    assert "window.alert" in src and "return null" in src, (
        "정체를 못 읽었을 때 조용히 진행합니다 — 빈 메타 조작으로 이어집니다(confirm-or-alarm)."
    )
    for fn, nxt in (("async function editTags", "function relinkTemplate"),
                    ("function moveJob", "async function toggleFavorite")):
        body = LIB[LIB.index(fn):LIB.index(nxt)]
        assert "selectedWork(name)" in body, f"{fn} 가 상세에서 정체를 읽지 않습니다(P1)."
        assert "if (!row) return" in body, f"{fn} 가 정체 부재를 통과시킵니다(P1)."
    # 걸러진 구획에서 정체를 긁던 옛 헬퍼가 되살아나면 같은 결함이 재발한다.
    assert "function findRow" not in LIB


def test_move_dialog_targets_come_from_the_registry_wide_group_list() -> None:
    """리뷰 1R P2 — 도착지 후보는 화면 구획이 아니라 레지스트리 전역 목록이다.

    평면 보기(최근·즐겨찾기·확인 필요)나 켜진 필터는 구획에서 그룹을 없앤다 — 거기서
    파생하면 실재하는 그룹으로 옮길 길이 사라진다(job·draft 화면은 완전한 목록을 받는다).
    """
    src = LIB[LIB.index("function allGroups"):LIB.index("async function renameJob")]
    assert "LAST.group_names" in src, "도착지 후보가 레지스트리 전역 목록이 아닙니다(P2)."
    assert "LAST.sections" not in src, "도착지 후보를 걸러진 구획에서 파생합니다(P2)."


def test_txt_works_route_to_the_draft_surface_not_the_hwpx_picker() -> None:
    """리뷰 2R — TXT 작업의 「열기」는 「기안」으로 간다(라이브러리 합류는 F6).

    「문서 만들기」로 보내면 후보 판정(`compatibility_for`)이 hwpx 아닌 작업을 전부 배제해
    `incompatible` 이 되고, 이어 여는 「확인 필요」 탭에서도 그 작업이 빠져 **빈 화면**에
    착지한다 — 사용자는 자기가 고른 작업을 어디서도 못 본다. 가드 문안·stale 재진술은
    「기안」이 소유한 단일 경로(`DraftScreen.openWork`)에 위임한다.
    """
    body = LIB[LIB.index("async function useInJob"):LIB.index("function editJob")]
    assert 'work.media === "txt"' in body, "TXT 작업을 가르지 않습니다(2R)."
    assert "DraftScreen.openWork" in body, "TXT 열기를 「기안」 단일 경로에 위임하지 않습니다."
    txt_branch = body[body.index('work.media === "txt"'):body.index('prefer_work')]
    assert "prefer_work" not in txt_branch
    assert 'Nav.go("draft")' in txt_branch
    # 취소면 화면을 바꾸지 않는다(§9.3 전이 순서 면).
    assert "if (!(await window.DraftScreen.openWork(name))) return;" in txt_branch
    # 라벨-행동 일치 — 목적지가 다르면 라벨도 다르다.
    detail = LIB[LIB.index("function renderDetail"):LIB.index("async function useInJob")]
    assert '"기안에서 열기"' in detail and '"문서 만들기에서 사용"' in detail
    # 「기안」이 실제로 그 단일 경로를 내보내고, 취소/실패를 boolean 으로 말한다.
    draft = (ROOT / "web" / "js" / "screens" / "draft.js").read_text(encoding="utf-8")
    assert "openWork: selectJob" in draft
    sel = draft[draft.index("async function selectJob"):draft.index("/* ---- ⋮ 메뉴")]
    assert "return false" in sel and "return true" in sel


def test_rename_carries_the_selection_to_the_new_name() -> None:
    """리뷰 2R — 이름 변경 뒤 선택이 옛 이름에 남으면 상세가 닫힌다.

    이름만 바뀌었을 뿐 그 작업은 그대로 있는데 사용자가 보던 문맥과 모달 복귀 지점이
    함께 사라진다. 새 이름을 refresh 에 실어 **한 왕복**으로 승계한다(중간 프레임 깜빡임도 없음).
    """
    body = LIB[LIB.index("async function jobDispatch"):LIB.index("function findRow")
               if "function findRow" in LIB else LIB.index("function selectedWork")]
    assert 'refresh", select ? { select } : {}' in body, "refresh 가 새 이름을 싣지 않습니다(2R)."
    rename = LIB[LIB.index("async function renameJob"):LIB.index("function moveJob")]
    assert '"rename_job", { name, new: v }, next' in rename, (
        "이름 변경이 새 이름을 refresh 로 넘기지 않습니다(2R)."
    )
