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
                    ("function moveJob", "const favorite")):
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


def test_primary_action_target_comes_from_python_not_the_surface() -> None:
    """리뷰 3R 근본 조치 — 주 행동의 **목적지를 표면이 조립하지 않는다**.

    표면이 매체를 보고 목적지를 가르면 표시용 정규화(`library_mode_of` 는 미연결을 hwpx 로
    센다)와 실행 판정(원시 `Job.media` 를 쓰는 `rank_available`)의 어휘가 갈린다. 그 틈에서
    TXT(2R)와 미연결(3R)이 똑같이 「후보에서 배제 → 확인 필요에서도 배제 → 빈 화면 착지」로
    끝났다. 목적지·라벨은 Python 이 한 번에 내고 표면은 라우팅만 한다.
    """
    body = LIB[LIB.index("async function runPrimary"):LIB.index("function editJob")]
    assert "work.primary && work.primary.target" in body, (
        "목적지를 Python 페이로드에서 읽지 않습니다(3R 근본 조치)."
    )
    for derived in ('media === "txt"', "template_linked", "mode_label"):
        assert derived not in body, f"표면이 목적지를 조립합니다: {derived}"
    # 세 목적지 전부 실제 착지처가 있다 — 빈 화면으로 보내지 않는다.
    assert 'Nav.go("draft")' in body and "DraftScreen.openWork" in body
    assert "editJob(name)" in body          # 미연결·미상 방식 → 고칠 수 있는 곳
    assert "prefer_work" in body            # hwpx 연결분만 「문서 만들기」로
    # 취소면 화면을 바꾸지 않는다(§9.3 전이 순서 면).
    assert "if (!(await window.DraftScreen.openWork(name))) return;" in body
    # 라벨도 목적지와 함께 온다 — 표면이 짝을 다시 맞추면 또 갈린다.
    detail = LIB[LIB.index("function renderDetail"):LIB.index("async function runPrimary")]
    assert "esc(primary.label)" in detail, "라벨을 Python 페이로드에서 읽지 않습니다."
    # 라벨을 매체로 고르면 목적지와 짝이 또 갈린다 — 방어 기본값 하나만 허용한다.
    assert 'd.media === "txt"' not in detail
    assert detail.count('"기안에서 열기"') == 0
    # 「기안」이 그 단일 경로를 내보내고 취소/실패를 boolean 으로 말한다.
    draft = (ROOT / "web" / "js" / "screens" / "draft.js").read_text(encoding="utf-8")
    assert "openWork: selectJob" in draft
    sel = draft[draft.index("async function selectJob"):draft.index("/* ---- ⋮ 메뉴")]
    assert "return false" in sel and "return true" in sel


def test_rename_carries_the_selection_only_when_it_succeeded() -> None:
    """리뷰 2R·3R — 개명 성공이면 선택을 승계하고, **거절이면 옮기지 않는다**.

    승계가 없으면 상세가 닫혀 사용자가 보던 문맥이 사라지고(2R), 무조건 승계하면 이미 있는
    이름으로의 개명이 거절됐는데도 선택이 그 **남의 작업**으로 옮겨가 오류 모달이 엉뚱한
    상세 위에 뜬다(3R). 성공 여부로 가른다.
    """
    body = LIB[LIB.index("async function jobDispatch"):LIB.index("function selectedWork")]
    assert "const ok = !(r && r.ok === false);" in body, "성공 여부를 가리지 않습니다(3R)."
    assert 'refresh", ok && selectIfOk ? { select: selectIfOk } : {}' in body
    rename = LIB[LIB.index("async function renameJob"):LIB.index("function moveJob")]
    assert '"rename_job", { name, new: v }, next' in rename, (
        "이름 변경이 새 이름을 refresh 로 넘기지 않습니다(2R)."
    )


def test_group_merge_confirm_runs_after_the_prompt_settles() -> None:
    """리뷰 3R — 병합 확인을 prompt 의 validate 안에서 열면 **영영 발화하지 않는다**.

    `modal.js` 는 진행 중인 promise 다이얼로그가 있으면 두 번째를 거절한다(pendingDialog
    직렬화). validate 안의 `Modal.confirm` 은 언제나 false 로 풀려 병합이 조용히 사라지고
    재진입 alert 만 뜬다. 「작업」 화면과 같은 순서 — 값을 먼저 받고 확정은 그다음이다.
    """
    body = LIB[LIB.index("async function renameGroup"):LIB.index("async function disbandGroup")]
    assert "validate:" not in body, "그룹 개명이 아직 validate 안에서 확정을 겁니다(3R)."
    prompt_at = body.index("Modal.prompt")
    settled_at = body.index("if (val === null) return;")
    confirm_at = body.index("Modal.confirm")
    assert prompt_at < settled_at < confirm_at, (
        "병합 확인이 prompt 가 풀리기 전에 열립니다 — pendingDialog 가 거절합니다(3R)."
    )
    # modal.js 의 그 직렬화가 실재한다는 전제 고정(바뀌면 이 가드의 근거가 사라진다).
    modal = (ROOT / "web" / "js" / "modal.js").read_text(encoding="utf-8")
    assert "pendingDialog" in modal and "if (pendingDialog)" in modal


def test_favorite_intent_is_serialized_through_the_shared_mechanism() -> None:
    """리뷰 3R 근본 조치 — 즐겨찾기 의도 직렬화는 「작업」 화면과 **한 몸통**이다.

    이 파일은 처음부터 그 기제를 쓴다고 적어 놓고 실제로는 DOM 의 `data-next` 를 그대로
    보냈다(계약 거짓말). 왕복 중 두 번째 클릭이 낡은 값을 읽으면 멱등 재지정이 "껐다"를
    삼켜 켜진 채로 남는다 — §8.4 4행(지연 왕복 중의 의도)이 이미 세운 결함류다.
    """
    assert "Intent.createFavorite(" in LIB, "공용 기제를 쓰지 않습니다(3R)."
    assert "data-next" not in LIB, "다음 값을 DOM 에서 읽습니다 — 미결 의도가 아닙니다(3R)."
    handler = LIB[LIB.index("function onListClick"):LIB.index("function onDetailClick")]
    assert 'favorite.toggle(fav.dataset.fav, fav.getAttribute("aria-pressed") === "true")' in handler


def test_library_axis_mutations_share_one_chain() -> None:
    """리뷰 4R — 축 변이(보기·방식·검색·facet·접힘·선택)는 **한 체인**으로 직렬화한다.

    pywebview 는 호출마다 별도 스레드라 동시 발신의 도착 순서가 보장되지 않는다: 디바운스된
    검색이 도는 중 다른 축을 만지면 늦게 도착한 옛 응답이 새 결과를 되돌려, 목록은 옛
    검색어로 걸러진 채 입력창만 새 글자를 유지한다(「작업」 화면 탐색이 이미 밟은 결함류).
    """
    assert "function axis(action, payload)" in LIB
    axis_fn = LIB[LIB.index("function axis(action, payload)"):LIB.index("function cancelPendingSearch")]
    assert "Intent.chained(SCREEN" in axis_fn, "축 변이가 체인을 타지 않습니다(4R)."
    for action in ("set_view", "set_mode", "set_query", "toggle_facet", "clear_facets",
                   "clear_filters", "toggle_group", "select_work"):
        assert f'axis("{action}"' in LIB, f"{action} 이 축 체인을 타지 않습니다(4R)."
        assert f'Bridge.call(SCREEN, "{action}"' not in LIB, (
            f"{action} 이 체인을 우회해 직접 발신합니다(4R)."
        )


def test_clearing_filters_cancels_the_pending_search() -> None:
    """리뷰 4R — 「필터 지우고 전체 보기」는 **대기 중인 검색까지** 걷겠다는 의사다.

    타이머를 안 취소하면 방금 지운 필터 위로 옛 검색어가 다시 얹힌다. 반대로 다른 축을
    누를 때는 취소하지 않는다 — 사용자가 친 글자는 그의 의사이고 체인이 순서를 지킨다.
    """
    assert "function cancelPendingSearch" in LIB
    handler = LIB[LIB.index("const cf = e.target.closest"):LIB.index("function onDetailClick")]
    assert "cancelPendingSearch();" in handler, "지우기가 대기 검색을 취소하지 않습니다(4R)."
    # 다른 축 경로에는 취소가 없어야 한다(친 글자를 말없이 버리지 않는다).
    assert LIB.count("cancelPendingSearch()") == 2  # 정의부 1 + 지우기 1


def test_pending_favorite_intent_is_shared_across_screens() -> None:
    """리뷰 4R — 미결 의도는 모듈 스코프여야 "공용 몸통"이 이름뿐이 아니게 된다.

    표면마다 사본을 두면, 라이브러리에서 별을 켠 직후 「작업」 화면의 아직 갱신 안 된 빈 별을
    눌렀을 때 두 인스턴스가 똑같이 `true` 를 계산해 같은 쓰기가 두 번 나가고 두 번째 토글이
    사라진다(멱등 재지정이 "껐다"를 삼키는 그 창).
    """
    intent = (ROOT / "web" / "js" / "intent.js").read_text(encoding="utf-8")
    factory = intent[intent.index("function createFavorite"):intent.index("window.Intent =")]
    assert "new Map()" not in factory, "팩토리가 호출마다 사본을 만듭니다(4R)."
    module = intent[:intent.index("function createFavorite")]
    assert "const FAV_PENDING = new Map();" in module and "const FAV_LAST = new Map();" in module
