"""Quickstart 101 사용자 여정 — **행동 순서와 결과 판정만**(N-11A · #423).

이 파일에는 창을 띄우는 코드도, 픽셀을 뜨는 코드도, 종료 정책도 없다. 그것들은
:mod:`.driver` 와 :mod:`.capture` 가 진다. 여기 남는 것은 "사용자가 무엇을 어떤 순서로
누르고, 그래서 무엇이 참이어야 하는가" 하나다.

셔터는 **이름으로만** 지목한다(``ctx.shoot("session-panel")``). 그 이름이 PNG 가 되는지
(``capture``) 아무것도 되지 않는지(``check``) 는 부른 쪽이 정한다 — 두 모드가 같은 대본을
쓰는 것이 이 파일의 요점이고, 그래야 "찍히는 화면"과 "검사되는 화면"이 갈라지지 않는다.

:data:`CAPTURE_POINTS` 는 그 이름들의 **정렬된 단일 출처**다. 종전에는 이름이 대본 안에
14번 흩어져 있어 커밋된 ``img/`` 와 README 참조와 대본이 서로를 못 봤다 — 셋 중 하나만
어긋나도 아무도 모르는 상태였다. 이제 셋이 같은 목록을 본다
(``tests/test_quickstart_101_live.py`` 의 3자 대조).
"""
from __future__ import annotations

import json
import posixpath
from collections.abc import Callable
from dataclasses import dataclass, field

from hwpxfiller.domain.job import MISSING_MARKER
from hwpxfiller.external.example_pack import (
    DATA_ASSETS,
    EXAMPLE_GROUP,
    HWPX_ASSETS,
    TXT_ASSETS,
)
from hwpxfiller.gui.tutorial_state import STEPS as TUTORIAL_STEPS
from hwpxfiller.webapp.app import _DISPATCH_REJECTION_KEY
from hwpxfiller.webapp.blocker_affordance import managed_primary_action_controls

from .surface import ScenarioFailure, StepTimeout, Surface

#: 캡처 지점 14개 — **순서가 계약이다**(파일 이름의 번호가 여기서 나온다).
#: README 참조·커밋된 ``img/*.png`` 와 3자 대조된다.
CAPTURE_POINTS: "tuple[str, ...]" = (
    "job-landing",
    "library-empty",
    "template-pick",
    "mapping-confirm",
    "save-job",
    "library-detail",
    "preview-drawer",
    "session-panel",
    "range-editor",
    "mirror-check",
    "generated",
    "workbench-review",
    "workbench-copied",
    "workbench-empty-value",
)

#: 101 이 만드는 작업 이름 — 트랙 A(HWPX) · 트랙 B(TXT) · 오류 연습.
JOB_NAMES: "tuple[str, ...]" = ("발주요청서", "발주요청 기안", "오류연습")

#: 트랙 A 가 만들어야 하는 문서 수(CSV 3행).
EXPECTED_HWPX = 3


def _rejection_message(value: object) -> str:
    if not isinstance(value, dict):
        return ""
    rejection = value.get(_DISPATCH_REJECTION_KEY)
    return str(rejection.get("message", "")) if isinstance(rejection, dict) else ""


@dataclass
class ScenarioContext:
    """대본이 바깥 세계와 닿는 **좁은 통로**."""

    surface: Surface
    shoot: "Callable[[str], None]"
    #: 데이터 CSV 의 절대 경로(홈이 임시냐 예제냐에 따라 다르다).
    csv_path: str
    #: 다음 native 파일 대화상자의 답을 큐에 넣는다. 큐가 비면 대화상자는 취소로 답한다.
    queue_file_answer: "Callable[[str], None]"
    queue_folder_answer: "Callable[[str], None]"
    stage_template: "Callable[[str], str]"
    stage_data: "Callable[[str], str]"
    stage_context: "Callable[[str], None]"
    output_dir: str
    prepare_output: "Callable[[], str]"
    create_collision: "Callable[[str], None]"
    output_manifest: "Callable[[], dict[str, str]]"
    #: 앱 홈 전체의 파일 census(상대경로 → sha256). 온보딩 여정의 「누르기 전에는 홈에
    #: 아무것도 쓰지 않는다」(#891 D1)를 재는 자리이고, 그 뒤로는 설치·생성·제거가 실제로
    #: 파일을 움직였는지의 실물 증거다 — 화면이 말하는 것과 디스크가 말하는 것을 가른다.
    home_census: "Callable[[], dict[str, str]]"
    audit_shoot: "Callable[[str], dict]"
    #: 대본이 관측한 사실 — 드라이버가 파일 시스템 사실과 합쳐 보고서를 만든다.
    observations: dict = field(default_factory=dict)


def run(ctx: ScenarioContext) -> dict:
    """트랙 A·B 와 오류 연습을 실 렌더로 완주하고 관측 사실을 돌려준다."""
    s = ctx.surface
    seen = ctx.observations

    # ---- S1 부팅 랜딩(문서 만들기 · 데이터도 작업도 없는 상태) --------------
    # 좌 목록이 죽은 뒤(F2 PR-B) 이 자리의 출구는 「문서 작업」으로 가는 버튼 하나다.
    s.wait(
        "document.querySelector('#jobPickInLibrary') !== null",
        "빈 상태 랜딩",
        requires=["#jobPickInLibrary"],
    )
    s.wait(
        "getComputedStyle(document.getElementById('jobNoDataExit')).display !== 'none'",
        "흡수처 출구 상주",
        requires=["#jobNoDataExit"],
    )
    ctx.shoot("job-landing")

    # ---- S2 「문서 작업」 → ＋ 새 작업 → 편집 모드 1단계(라이브러리 피커) ----
    s.click_sel("#jobPickInLibrary", what="문서 작업으로 가는 출구")
    s.wait(
        "document.querySelector('#scr-library.on') !== null",
        "문서 작업 화면",
        requires=["#scr-library"],
    )
    ctx.shoot("library-empty")
    s.click_sel("#libraryNewWork", what="새 작업")
    # 편집기는 몰입 표면이다(재작성 F7) — 상단 2탭을 덮는 자기 화면으로 착지한다.
    s.wait(
        "document.querySelector('#scr-editor.on') !== null"
        " && !!window.__cap.btn('#scr-editor','이 템플릿으로')",
        "편집기 화면·라이브러리 피커",
        requires=["#scr-editor"],
    )
    # 발주요청서 행의 "이 템플릿으로" — data-path 로 정확 겨눔.
    s.click_sel(
        '#scr-editor button[data-act="use-library"][data-path*="발주요청서"]',
        what="발주요청서 템플릿 채택",
    )
    s.wait(
        "document.querySelector('#scr-editor').textContent.includes('공고번호')",
        "템플릿 선택·필드 스키마",
        requires=["#scr-editor"],
    )
    # 텍스트가 **있다**는 것과 **보인다**는 것은 다르다: 스키마 표는 템플릿 목록 아래라
    # 기본 스크롤에서 폴드 밖이고, 위 조건은 그 상태에서도 참이다(문서가 "6개 필드를
    # 확인한다"고 적은 그림에 표가 없게 된다). 겨눠 스크롤해 그 말을 그림이 지게 한다.
    s.scroll_to("#scr-editor table.schema-fields")
    ctx.shoot("template-pick")

    # ---- S3 2단계: 데이터 연결 + 모두 확정 ---------------------------------
    s.click_text("#scr-editor", "다음 ▶")
    s.wait(
        "!!window.__cap.btn('#scr-editor','파일 선택…')",
        "「필드 연결·표시」 탭 데이터 관문",
        requires=["#scr-editor"],
    )
    ctx.queue_file_answer(ctx.csv_path)
    s.click_text("#scr-editor", "파일 선택…")
    s.wait(
        "!!window.__cap.btn('#scr-editor','모두 확정')"
        " && document.querySelector('#scr-editor').textContent.includes('해양수산부')",
        "데이터 로드·매핑표 미리보기",
        requires=["#scr-editor"],
    )
    s.click_text("#scr-editor", "모두 확정")
    s.wait(
        "document.querySelector('#scr-editor').textContent.includes('확정 6/6')",
        "전 행 확정",
        requires=["#scr-editor"],
    )
    # 확정 게이트 줄(확정 6/6·모두 확정)이 폴드 아래로 잘리지 않게 겨눠 스크롤.
    s.js("window.__cap.btn('#scr-editor','모두 해제')?.scrollIntoView({block:'center'}); true;")
    ctx.shoot("mapping-confirm")

    # ---- S4 「파일 이름」 탭: 이름·패턴 → 저장 ------------------------------
    # 파일 이름은 F7 에서 **전용 탭**으로 승격했고(대조표 20행), 작업 이름은 화면 머리의
    # 인라인 입력이다(「저장」 분류 사망의 승계 — §10.13.3).
    s.click_text("#scr-editor", "다음 ▶")
    s.wait(
        "!!document.querySelector('#scr-editor input[data-act=\"pattern\"]')",
        "파일 이름 탭",
        requires=['#scr-editor input[data-act="pattern"]'],
    )
    s.set_value("#editorName", "발주요청서")
    s.set_value('#scr-editor input[data-act="pattern"]', "발주요청서-{{공고번호}}")
    s.wait(
        "document.querySelector('#scr-editor').textContent.includes('발주요청서-2026-001')",
        "파일명 라이브 예시",
        requires=["#scr-editor"],
    )
    ctx.shoot("save-job")
    s.click_text("#scr-editor", "작업 저장")
    # 저장 착지를 먼저 확인한다 — 저장은 비동기라 곧바로 화면을 옮기면 라이브러리가 아직
    # 없는 작업을 기다린다(경합). 성공 재진술은 Python notice(ok) 채널이 낸다.
    s.wait(
        "document.querySelector('#scr-editor').textContent.includes('저장했습니다')",
        "작업 저장 착지",
        timeout=30.0,
        requires=["#scr-editor"],
    )
    # 저장 뒤 머리가 판본을 말한다(§10.13 판정 O) — 첫 저장이므로 r1 이다.
    s.wait(
        "document.getElementById('editorSaveState').textContent.includes('r1')",
        "저장 상태·판본 표기",
        requires=["#editorSaveState"],
    )
    seen["hwpx_job_saved"] = True
    # 편집기는 출구가 하나다 — back 이 원래 업무로 되돌린다(깨끗한 세션이라 가드 없음).
    s.click_sel("#editorBack", what="편집기 출구")
    s.wait("document.querySelector('#scr-job.on') !== null", "편집기 이탈", requires=["#scr-job"])

    # ---- S5 실행 세션(「문서 작업」에서 골라 문서 만들기로) ------------------
    # 좌 목록 사망 뒤 저장된 작업을 찾는 자리는 「문서 작업」 하나다(F2 PR-B).
    s.click_sel('.navbtn[data-scr="library"]', what="문서 작업 탭")
    s.wait(
        "!!document.querySelector('#libraryList [data-work=\"발주요청서\"]')",
        "저장·라이브러리 반영",
        requires=["#libraryList"],
    )
    s.click_sel('#libraryList [data-work="발주요청서"]', what="저장된 작업 행")
    s.wait(
        "!!document.querySelector('#libraryDetail [data-use]')",
        "상세 상시 행동",
        requires=["#libraryDetail"],
    )
    ctx.shoot("library-detail")
    s.click_sel('#libraryDetail [data-use="발주요청서"]', what="문서 만들기에서 사용")
    # 작업↔데이터 결속(`Job.default_dataset_ref`)과 자동 조준은 U2 §5.3 판정 D 로 폐기됐다
    # (#347) — 「문서 만들기에서 사용」은 **데이터 선택을 반드시 지난다**. 데이터가 없으면
    # 백엔드가 그 명시 사건을 보관만 한다(reason=no_data). 마운트 뒤에도 active Work 는 0이고,
    # 사용자가 현재 데이터에 맞는 후보를 다시 명시적으로 골라야 한다.
    s.wait("document.querySelector('#scr-job.on') !== null", "문서 만들기 착지", requires=["#scr-job"])
    ctx.queue_file_answer(ctx.csv_path)
    s.click_sel("#jobBtnPickData", what="데이터 선택")
    s.wait(
        "!document.getElementById('dataPickerModal').classList.contains('hidden')",
        "데이터 선택 면",
        requires=["#dataPickerModal"],
    )
    s.click_sel("#dataPickerBrowse", what="파일 찾아보기")
    # 찾아보기 성사는 **면을 닫지 않는다**(U2 §2.7, #343): 「현재 데이터」가 방금 고른
    # 파일로 재진술되고 그 자리에 「이 데이터 고정…」이 선다. 존재만 재면 hidden 버튼도
    # 통과하므로(프로브 click 이 hidden 을 지나는 것과 같은 함정) **가시성**으로 잰다.
    s.wait(
        "(function(){"
        "if(document.getElementById('dataPickerModal').classList.contains('hidden'))return false;"
        "if(!document.querySelector('#dataPickerCurrent .tplcard-name'))return false;"
        "const b=document.getElementById('dataPickerPin');"
        "return !!b && getComputedStyle(b).display !== 'none';})()",
        "찾아보기 성사·면 유지·고정 버튼 가시",
        timeout=25.0,
        requires=["#dataPickerModal", "#dataPickerCurrent", "#dataPickerPin"],
    )
    s.click_sel("#dataPickerClose", what="데이터 선택 면 닫기")
    s.wait(
        "document.getElementById('dataPickerModal').classList.contains('hidden')"
        " && document.getElementById('jobDataLabel').value.length > 0",
        "데이터 마운트 착지",
        timeout=25.0,
        requires=["#dataPickerModal", "#jobDataLabel"],
    )
    s.wait(
        "document.getElementById('jobActionName').textContent.trim() === ''",
        "데이터 마운트 뒤 active Work 0",
        requires=["#jobActionName"],
    )
    seen["active_work_absent_after_mount"] = True

    candidate = '#jobCandidates button[data-cand="발주요청서"]'
    s.wait(
        "(function(){"
        f"const b=document.querySelector({candidate!r});"
        "if(!b)return false;const style=getComputedStyle(b);"
        "return !b.disabled && b.getClientRects().length > 0"
        " && style.visibility !== 'hidden' && style.pointerEvents !== 'none'"
        " && b.getAttribute('aria-pressed') === 'false';})()",
        "현재 데이터의 발주요청서 후보 가시·선택 가능",
        requires=["#jobCandidates", candidate],
    )
    seen["work_candidate_actionable"] = "발주요청서"
    s.wait(
        "(function(){const n=document.getElementById('jobDataNotice');"
        "return !n.hidden && n.textContent.includes('발주요청서')"
        " && n.textContent.includes('직접 고르세요');})()",
        "preferred notice의 직접 선택 안내",
        requires=["#jobDataNotice"],
    )
    seen["preferred_notice_requires_selection"] = True

    # 후보 카드의 보이는 production action을 실제로 누른다. 「열렸다」의 정본은 액션바 이름과
    # 카드 aria-pressed다. 이 확인 전에 다음 단계로 가면 명시 선택 없는 진행을 놓친다.
    s.click_sel(candidate, what="발주요청서 후보 명시 선택")
    s.wait(
        "document.getElementById('jobActionName').textContent.trim() === '발주요청서'"
        f" && document.querySelector({candidate!r}).getAttribute('aria-pressed') === 'true'"
        " && !document.getElementById('jobSelAll').disabled",
        "데이터 마운트·명시 작업 선택",
        requires=["#jobActionName", candidate, "#jobSelAll"],
    )
    seen["explicit_work_selected"] = "발주요청서"
    # 데이터-우선 계약(§18.2): 새 데이터의 선택은 **0건**에서 시작한다 — 무엇을 만들지는
    # 사용자가 고른다. 그래서 마운트만으로는 게이트가 열리지 않고, 여기서 전체 선택을
    # 눌러야 「N개 생성」이 열린다. 101 도 이 순서를 그대로 가르친다.
    s.click_sel("#jobSelAll", what="전체 선택")

    # ---- S5a 첫 실행의 결과 확인(F5) ---------------------------------------
    # 방금 만든 작업은 아직 한 번도 문서를 만들지 않았다 — §13-3 대로 결과를 확인해야
    # 실행할 수 있다. 행을 골라도 게이트는 아직 닫혀 있고, 미리보기에서 확인해야 열린다.
    # 게이트가 「생성 값 미리보기」를 지목하는데 그 버튼이 잠겨 있으면 이행 불가능한
    # 지시다 — 지목과 가용성을 **같이** 재고 나서 누른다.
    s.wait(
        "document.getElementById('jobGenBtn').disabled"
        " && document.getElementById('jobGate').textContent.includes('생성 값 미리보기')"
        " && !document.getElementById('jobPreviewOpen').disabled",
        "첫 실행 검토 요구",
        requires=["#jobGenBtn", "#jobGate", "#jobPreviewOpen"],
    )
    seen["first_run_review_required"] = True
    s.click_sel("#jobPreviewOpen", what="생성 값 미리보기")
    s.wait(
        "!document.getElementById('previewSheet').classList.contains('hidden')"
        " && document.querySelectorAll('#previewRows .mir-row').length > 0"
        " && document.getElementById('previewFilename').textContent.length > 0",
        "확인 면(생성 값 미리보기)·값·파일 이름",
        requires=["#previewSheet", "#previewRows", "#previewFilename"],
    )
    ctx.shoot("preview-drawer")
    s.click_sel("#previewApprove", what="이 이름과 값으로 승인")
    # 승인은 명시 사건이다 — 버튼이 사라지는 것이 그 사건의 착지다(면은 열린 채 남아
    # 나머지 문서를 계속 넘겨볼 수 있다).
    s.wait(
        "getComputedStyle(document.getElementById('previewApprove')).display === 'none'",
        "결과 확인 착지",
        requires=["#previewApprove"],
    )
    seen["preview_approved"] = True
    s.click_sel("#previewClose", what="확인 면 닫기")
    s.wait(
        "document.getElementById('previewSheet').classList.contains('hidden')"
        " && !document.getElementById('jobGenBtn').disabled",
        "확인 뒤 게이트 열림",
        requires=["#previewSheet", "#jobGenBtn"],
    )
    ctx.shoot("session-panel")

    # ---- S5b 범위 편집기(⤢) — 초안 거래를 사람 순서로 한 바퀴(F3) ----------
    # 여는 것 자체가 Python 왕복(초안 생성)이고, 여기서의 편집은 **적용 전까지** 메인 범위를
    # 바꾸지 않는다. 캡처 뒤 **취소**로 나오므로 아래 단계들의 상태는 그대로다.
    s.click_sel("#jobDataExpand", what="펼쳐서 행 고르기")
    s.wait(
        "!document.getElementById('dataSheet').classList.contains('hidden')"
        " && document.getElementById('dataSheetSlot').contains("
        "document.getElementById('jobRangeFoot'))",
        "범위 편집기·footer",
        requires=["#dataSheet", "#dataSheetSlot", "#jobRangeFoot"],
    )
    # 표시순서를 뒤집어 표가 실제로 따라오는지 본다(보이는 것 = 만들어지는 것).
    s.set_value("#jobOrderSel", "sourceAsc")
    s.wait(
        "(document.querySelector('#jobTableBody tr')||{dataset:{}}).dataset.i === '0'",
        "표시순서 전환 반영",
        requires=["#jobTableBody"],
    )
    ctx.shoot("range-editor")
    # 재렌더가 축 선택기를 커밋 값으로 되돌리지 않는지 — 행 하나를 껐다 켜서 **실 왕복**을
    # 만든다. 판정 수치(footer 「선택 적용: N건」)가 바뀐 것을 먼저 확인해 **push 가 도착한
    # 뒤**를 재는 것이 요점이다 — 클릭 직후를 재면 아직 안 온 재렌더를 통과로 읽는다.
    s.click_sel('#jobTableBody tr[data-i="0"] input[type="checkbox"]', what="행 선택 토글")
    s.wait(
        "document.getElementById('jobRangeApply').textContent.includes('2건')"
        " && document.getElementById('jobOrderSel').value === 'sourceAsc'",
        "재렌더 뒤에도 초안 축 유지",
        requires=["#jobRangeApply", "#jobOrderSel"],
    )
    s.click_sel('#jobTableBody tr[data-i="0"] input[type="checkbox"]', what="행 선택 복원")
    s.wait(
        "document.getElementById('jobRangeApply').textContent.includes('3건')",
        "초안 선택 복원",
        requires=["#jobRangeApply"],
    )
    s.click_sel("#jobRangeCancel", what="범위 편집 취소")
    # 변경이 있으므로 이탈 가드가 끼어든다(적용하지 않은 편집을 조용히 버리지 않는다).
    s.wait("!!window.__cap.btn(null,'버리고 닫기')", "이탈 가드")
    s.click_text(None, "버리고 닫기")
    # 취소 = 초안만 버린다: 메인 범위(선택 3건)와 축(최신 행 먼저)이 그대로여야 한다.
    s.wait(
        "document.getElementById('dataSheet').classList.contains('hidden')"
        " && document.getElementById('jobOrderSel').value === 'sourceDesc'"
        " && !document.getElementById('jobGenBtn').disabled",
        "취소 뒤 메인 범위 보존",
        requires=["#dataSheet", "#jobOrderSel", "#jobGenBtn"],
    )

    # ---- S6 본문 확인(한 줄) ------------------------------------------------
    # 거울 표와 필드축 ack 는 U2 §2.13 으로 폐기됐다(#346) — 값을 말하는 표면은 확인 면
    # 하나이고, 이 존에 남은 것은 빈 값 표지·이름 건수·확인 면 출구 한 줄이다. 그 줄이
    # **서 있는 것을 확인한 뒤** 찍는다: 존만 겨눠 찍으면 한 줄이 hidden 인 화면(선택 0건·
    # 차단 배너)도 같은 컷으로 지나간다.
    s.wait(
        "!document.getElementById('jobMirrorLine').hidden"
        " && document.getElementById('jobMirrorSummary').textContent.trim().length > 0",
        "본문 확인 한 줄",
        requires=["#jobMirrorLine", "#jobMirrorSummary"],
    )
    s.scroll_to("#jobMirrorZone")
    ctx.shoot("mirror-check")

    # ---- S7 생성 → 완료 요약 ----------------------------------------------
    s.click_sel("#jobGenBtn", what="이 작업으로 문서 생성")
    # 결과는 3태 구획이 받는다(F4) — 제목이 태를, 요약이 수치를 말한다.
    s.wait(
        "(document.getElementById('jobResult')||{dataset:{}}).dataset.state === 'completed'",
        "생성 완료 태",
        timeout=60.0,
        requires=["#jobResult"],
    )
    seen["hwpx_result_state"] = s.js(
        "document.getElementById('jobResult').dataset.state"
    )
    s.scroll_to("#jobResult")
    ctx.shoot("generated")

    # ---- S8 트랙 B: TXT 작업 만들기(편집기 「템플릿」 탭 TXT 밴드) ----------
    # 휘발 「기안」 화면은 F6 PR-B 로 사라졌다 — TXT 도 같은 편집기에서 **저장 작업**으로
    # 만들고(지도 §10.15.15 점검표 1행), 채워 복사는 검토·복사 작업대가 잇는다.
    s.click_sel('.navbtn[data-scr="library"]', what="문서 작업 탭(트랙 B)")
    s.wait(
        "document.querySelector('#scr-library.on') !== null",
        "문서 작업 화면(트랙 B)",
        requires=["#scr-library"],
    )
    s.click_sel("#libraryNewWork", what="새 작업(트랙 B)")
    s.wait(
        "document.querySelector('#scr-editor.on') !== null && !!document.querySelector("
        "'#scr-editor button[data-act=\"use-library\"][data-path*=\"발주요청_기안\"]')",
        "편집기 TXT 밴드",
        requires=["#scr-editor"],
    )
    s.click_sel(
        '#scr-editor button[data-act="use-library"][data-path*="발주요청_기안"]',
        what="TXT 템플릿 채택",
    )
    # TXT 세션 = 탭 2개(템플릿·필드 연결) — 파일 이름 탭이 없다(§3.2, 파일을 만들지 않는 작업).
    s.wait(
        "document.querySelectorAll('#editor-steps .wstep-tab').length === 2"
        " && document.querySelector('#scr-editor').textContent.includes('공고번호')",
        "TXT 스키마·탭 2개",
        requires=["#editor-steps"],
    )
    s.click_text("#scr-editor", "다음 ▶")
    s.wait(
        "!!window.__cap.btn('#scr-editor','파일 선택…')",
        "TXT 필드 연결 데이터 관문",
        requires=["#scr-editor"],
    )
    ctx.queue_file_answer(ctx.csv_path)
    s.click_text("#scr-editor", "파일 선택…")
    s.wait(
        "!!window.__cap.btn('#scr-editor','모두 확정')"
        " && document.querySelector('#scr-editor').textContent.includes('해양수산부')",
        "TXT 매핑표 미리보기",
        requires=["#scr-editor"],
    )
    s.click_text("#scr-editor", "모두 확정")
    s.wait(
        "document.querySelector('#scr-editor').textContent.includes('확정 6/6')",
        "TXT 전 행 확정",
        requires=["#scr-editor"],
    )
    s.set_value("#editorName", "발주요청 기안")
    s.click_text("#scr-editor", "작업 저장")
    # (구 「등록 데이터 동명 확인 → [덮어쓰기]」 왕복은 #347 로 사라졌다 — 저장은 데이터를
    #  등록하지도 결속하지도 않는다. 풀 등록은 데이터 선택 면의 「이 데이터 고정」뿐이다.)
    s.wait(
        "document.querySelector('#scr-editor').textContent.includes('저장했습니다')",
        "TXT 작업 저장 착지",
        timeout=30.0,
        requires=["#scr-editor"],
    )
    s.click_sel("#editorBack", what="편집기 출구(트랙 B)")
    s.wait(
        "document.querySelector('#scr-job.on') !== null",
        "편집기 이탈(트랙 B)",
        requires=["#scr-job"],
    )

    # ---- S9 작업대 진입·검토 -----------------------------------------------
    # 실행 버튼이 매체 분기(판정 D)로 「검토·복사 시작 · 3건」으로 서고 작업대가 열린다.
    s.click_sel('.navbtn[data-scr="library"]', what="문서 작업 탭(작업대)")
    s.wait(
        "!!document.querySelector('#libraryList [data-work=\"발주요청 기안\"]')",
        "TXT 작업 라이브러리 반영",
        requires=["#libraryList"],
    )
    s.click_sel('#libraryList [data-work="발주요청 기안"]', what="TXT 작업 행")
    s.wait(
        "!!document.querySelector('#libraryDetail [data-use=\"발주요청 기안\"]')",
        "TXT 상세",
        requires=["#libraryDetail"],
    )
    s.click_sel('#libraryDetail [data-use="발주요청 기안"]', what="문서 만들기에서 사용(TXT)")
    # 이번엔 데이터 선택을 다시 지나지 않는다 — 앞 단계에서 마운트한 발주목록이 **세션
    # 소유**라 작업 전환에서 생존한다(데이터-우선 §18.2). 그래서 prefer_work 가 즉시
    # 승격시키고, 그 사실을 액션바 이름이 말한다.
    s.wait(
        "document.getElementById('jobActionName').textContent.trim() === '발주요청 기안'"
        " && !document.getElementById('jobSelAll').disabled",
        "TXT 작업 전환",
        timeout=25.0,
        requires=["#jobActionName", "#jobSelAll"],
    )
    seen["data_survived_job_switch"] = True
    s.click_sel("#jobSelAll", what="전체 선택(TXT)")
    s.wait(
        "document.getElementById('jobGenBtn').textContent.includes('검토·복사 시작')"
        " && !document.getElementById('jobGenBtn').disabled",
        "검토·복사 진입 버튼",
        requires=["#jobGenBtn"],
    )
    s.click_sel("#jobGenBtn", what="검토·복사 시작")
    # 카드 술어는 표시순서 무관하게 잡는다 — 고정 사본은 「최신 행 먼저」 기본 순서라 첫
    # 카드가 CSV 1행이 아니다. 템플릿 원문([발주 요청])과 채운 값(구매)이 함께 서야 채움이다.
    s.wait(
        "document.querySelector('#scr-workbench.on') !== null"
        " && (document.getElementById('wbCard')||{textContent:''}).textContent"
        ".includes('[발주 요청]')"
        " && (document.getElementById('wbCard')||{textContent:''}).textContent.includes('구매')",
        "작업대 카드 채움",
        requires=["#scr-workbench", "#wbCard"],
    )
    ctx.shoot("workbench-review")

    # ---- S10 복사(클립보드) ------------------------------------------------
    s.click_sel("#wbCopy", what="복사")
    s.wait(
        "(document.getElementById('wbCopied')||{textContent:''}).textContent"
        ".trim().indexOf('1 /') === 0",
        "복사 카운터",
        requires=["#wbCopied"],
    )
    seen["txt_copied"] = s.js(
        "document.getElementById('wbCopied').textContent.trim()"
    )
    ctx.shoot("workbench-copied")
    # 미복사 잔량이 있는 이탈은 가드가 확인을 요구한다(T3 승계) — 실 클릭으로 지난다.
    s.click_sel("#wbBack", what="작업대 출구")
    s.wait(
        "document.querySelector('#scr-job.on') !== null || !!window.__cap.btn(null,'나가기')",
        "작업대 이탈 가드",
    )
    s.js("window.__cap.clickBtn(null,'나가기'); true;")
    s.wait("document.querySelector('#scr-job.on') !== null", "작업대 이탈", requires=["#scr-job"])

    # ---- S11 오류 연습: 데이터에 없는 항목 = 비움 확정 → 〈빈 값〉 ----------
    # 구 「기안」의 빨간 {{토큰}} 은 휘발 세션(미결속 허용)의 표면이었다. 저장 작업은 전 행
    # 확정이 저장 조건이라, 없는 항목은 편집기가 **비움 확정**을 요구하고(조용히 지나가지
    # 않는다) 작업대 카드에 〈빈 값〉으로 남는다 — 같은 경보의 새 거처를 그대로 찍는다.
    s.click_sel('.navbtn[data-scr="library"]', what="문서 작업 탭(오류 연습)")
    s.wait(
        "document.querySelector('#scr-library.on') !== null",
        "문서 작업(오류 연습)",
        requires=["#scr-library"],
    )
    s.click_sel("#libraryNewWork", what="새 작업(오류 연습)")
    s.wait(
        "document.querySelector('#scr-editor.on') !== null && !!document.querySelector("
        "'#scr-editor button[data-act=\"use-library\"][data-path*=\"오류연습_미치환\"]')",
        "편집기 TXT 밴드(오류 연습)",
        requires=["#scr-editor"],
    )
    s.click_sel(
        '#scr-editor button[data-act="use-library"][data-path*="오류연습_미치환"]',
        what="오류 연습 템플릿 채택",
    )
    s.wait(
        "document.querySelector('#scr-editor').textContent.includes('담당연락처')",
        "오류 연습 스키마",
        requires=["#scr-editor"],
    )
    s.click_text("#scr-editor", "다음 ▶")
    s.wait(
        "!!window.__cap.btn('#scr-editor','파일 선택…')",
        "데이터 관문(오류 연습)",
        requires=["#scr-editor"],
    )
    ctx.queue_file_answer(ctx.csv_path)
    s.click_text("#scr-editor", "파일 선택…")
    s.wait("!!window.__cap.btn('#scr-editor','모두 확정')", "매핑표(오류 연습)", requires=["#scr-editor"])
    s.click_text("#scr-editor", "모두 확정")
    # 데이터에 없는 「담당연락처」 — 채우지 않고 비움으로 확정할지 **묻는다**(이름게이트).
    s.wait("!!window.__cap.btn(null,'비움으로 확정')", "비움 확정 이름게이트")
    seen["empty_value_gate_asked"] = True
    s.click_text(None, "비움으로 확정")
    s.wait(
        "document.querySelector('#scr-editor').textContent.includes('확정 3/3')",
        "오류 연습 전 행 확정",
        requires=["#scr-editor"],
    )
    s.set_value("#editorName", "오류연습")
    s.click_text("#scr-editor", "작업 저장")
    s.wait(
        "document.querySelector('#scr-editor').textContent.includes('저장했습니다')",
        "오류 연습 저장 착지",
        timeout=30.0,
        requires=["#scr-editor"],
    )
    s.click_sel("#editorBack", what="편집기 출구(오류 연습)")
    s.wait(
        "document.querySelector('#scr-job.on') !== null",
        "편집기 이탈(오류 연습)",
        requires=["#scr-job"],
    )
    s.click_sel('.navbtn[data-scr="library"]', what="문서 작업 탭(오류 연습 실행)")
    s.wait(
        "!!document.querySelector('#libraryList [data-work=\"오류연습\"]')",
        "오류 연습 작업 반영",
        requires=["#libraryList"],
    )
    s.click_sel('#libraryList [data-work="오류연습"]', what="오류 연습 작업 행")
    s.wait(
        "!!document.querySelector('#libraryDetail [data-use=\"오류연습\"]')",
        "오류 연습 상세",
        requires=["#libraryDetail"],
    )
    s.click_sel('#libraryDetail [data-use="오류연습"]', what="문서 만들기에서 사용(오류 연습)")
    # 여기도 데이터는 그대로다(세션 소유) — 작업만 바뀐다. 화면 전체 텍스트로 재면 후보
    # 카드에 이름이 **떠 있기만 해도** 참이 되므로 액션바 이름으로 겨눈다.
    s.wait(
        "document.getElementById('jobActionName').textContent.trim() === '오류연습'"
        " && !document.getElementById('jobSelAll').disabled",
        "오류 연습 작업 전환",
        timeout=25.0,
        requires=["#jobActionName", "#jobSelAll"],
    )
    s.click_sel("#jobSelAll", what="전체 선택(오류 연습)")
    s.wait(
        "!document.getElementById('jobGenBtn').disabled",
        "검토·복사 진입(오류 연습)",
        requires=["#jobGenBtn"],
    )
    s.click_sel("#jobGenBtn", what="검토·복사 시작(오류 연습)")
    s.wait(
        "document.querySelector('#scr-workbench.on') !== null"
        " && (document.getElementById('wbCard')||{textContent:''}).textContent.includes('빈 값')"
        " && (document.getElementById('wbMapPanel')||{textContent:''}).textContent"
        ".includes('담당연락처')",
        "작업대 〈빈 값〉 표면",
        requires=["#scr-workbench", "#wbCard", "#wbMapPanel"],
    )
    seen["empty_value_surfaced"] = True
    ctx.shoot("workbench-empty-value")

    return seen


def _expect(value: object, message: str) -> None:
    if not value:
        raise ScenarioFailure(message)


def _snapshot(surface: Surface) -> dict:
    value = surface.bridge("window.pywebview.api.initial('job')", "현재 job projection")
    if not isinstance(value, dict):
        raise ScenarioFailure(f"job projection이 객체가 아닙니다: {type(value)!r}")
    return value


def _current_view(snapshot: dict) -> dict:
    zone = snapshot.get("slot_configuration") or {}
    view = zone.get("current_view") if isinstance(zone, dict) else None
    if not isinstance(view, dict):
        raise ScenarioFailure(f"current Slot view가 없습니다: {zone!r}")
    return view


def _workbench(snapshot: dict) -> dict:
    value = snapshot.get("workbench_observation")
    if not isinstance(value, dict) or value.get("supported") is not True:
        raise ScenarioFailure(f"current workbench observation이 없습니다: {value!r}")
    return value


def _preview_observation(s: Surface, what: str) -> dict:
    """미리보기 서랍을 **열어** `semantic_preview` 가 실린 관측을 읽는다(닫지는 않는다).

    `semantic_preview` 는 서랍이 열려 있을 때만 스냅샷에 실린다(`screen_job.py:3390` —
    `self.preview_open and observation.semantic_preview is not None`). 그래서 토큰을 읽는
    걸음은 여는 행위와 **한 몸**이다. 닫힌 채로 물으면 `None` 이 오고, 대본은 그 자리에서
    `TypeError` 로 죽어 무엇이 없었는지 말하지 못한다 — 그 침묵을 여기서 문장으로 바꾼다.
    """
    s.click_sel("#jobManagedPreviewOpen", what=f"{what} semantic preview 열기")
    s.wait(
        "!document.getElementById('previewSheet').classList.contains('hidden')",
        f"{what} preview 서랍",
        timeout=30.0,
        requires=["#previewSheet"],
    )
    observation = _workbench(_snapshot(s))
    if not isinstance(observation.get("semantic_preview"), dict):
        raise ScenarioFailure(
            f"{what} preview 서랍이 열렸는데 semantic_preview 가 없습니다 — "
            f"requirement={observation.get('preview_requirement')!r}"
        )
    return observation


def _mount_data(ctx: ScenarioContext, path: str, *, failure: bool = False) -> None:
    s = ctx.surface
    ctx.queue_file_answer(path)
    s.click_sel("#jobBtnPickData", what="SX-05 데이터 선택")
    s.wait(
        "!document.getElementById('dataPickerModal').classList.contains('hidden')",
        "SX-05 데이터 선택 면",
        requires=["#dataPickerModal", "#dataPickerBrowse"],
    )
    s.click_sel("#dataPickerBrowse", what="SX-05 데이터 파일 찾아보기")
    # 착지는 **이번 찾아보기가 낸 말**로 잰다. 전환에서 이 면은 열리는 순간 이미 *이전* 데이터의
    # 카드를 세우므로(`open({current: currentData()})`), 「.tplcard-name 이 있다」·「문안이 비어
    # 있지 않다」는 새 적재를 증언하지 못한다 — 둘 다 여는 순간·진행 문안에서 이미 참이다.
    # 그 vacuous 대기가 적재 도중에 [닫기]를 누르게 하고, 그 닫기는 「불러오는 중」 계약대로
    # **거절**된다(제품이 옳다). 거절 문안은 곧 성공 문안에 덮여 증거가 「닫히지 않은 면」만
    # 남는다 — #728 이 이 자리를 overlay 결함으로 오진한 출처가 그것이다.
    # 반면 문안은 open 이 비워 두므로(`status: ""`), 아래 두 표식은 **이번** 적재에서만 참이고
    # 그때 `loading` 은 이미 false 다(성공 patch 와 `finally` 의 loading 해제가 한 tick).
    if failure:
        # 진행 문안(「파일 선택 창에서 파일을 고르세요…」)도 비어 있지 않다 — 길이가 아니라
        # 거절 표식으로 재야 실패한 전환을 진행 중과 가른다.
        try:
            s.wait(
                "document.getElementById('dataPickerNote').textContent.trim().startsWith('⚠')",
                "실패한 데이터 전환 문안",
                timeout=25.0,
                requires=["#dataPickerNote"],
            )
        except StepTimeout as exc:
            # 실패한 전환이 무엇을 말했는지 없이 시한만 남기면, 「거절 문안이 다르다」와
            # 「아무 말도 없었다」가 같은 빨강이 된다 — 그 둘은 전혀 다른 사건이다.
            state = s.js(
                "(function(){var n=document.getElementById('dataPickerNote');"
                "var c=document.querySelector('#dataPickerCurrent .tplcard-name');"
                "return {note:n?n.textContent.trim():null, note_shown:n?n.style.display!=='none':null,"
                " current:c?c.textContent.trim():null};})()"
            )
            raise ScenarioFailure(
                f"SX-05 실패한 데이터 전환이 사유를 말하지 않았습니다 — {state}"
            ) from exc
    else:
        # 존재만 재면 hidden 요소도 통과하므로 고정 버튼은 **가시성**으로 잰다(master 규율 승계).
        s.wait(
            "(function(){"
            "if(document.getElementById('dataPickerModal').classList.contains('hidden'))return false;"
            "if(!document.getElementById('dataPickerNote').textContent.includes('불러왔습니다'))return false;"
            "if(!document.querySelector('#dataPickerCurrent .tplcard-name'))return false;"
            "const b=document.getElementById('dataPickerPin');"
            "return !!b && getComputedStyle(b).display !== 'none';})()",
            "데이터 전환 착지",
            timeout=25.0,
            requires=["#dataPickerModal", "#dataPickerNote", "#dataPickerCurrent"],
        )
    s.click_sel("#dataPickerClose", what="데이터 선택 면 닫기")
    try:
        s.wait(
            "document.getElementById('dataPickerModal').classList.contains('hidden')",
            "데이터 선택 면 닫힘",
            requires=["#dataPickerModal"],
        )
    except StepTimeout as exc:
        # 이 면은 「불러오는 중」에는 닫히기를 거절한다(제품 계약). 그 거절인지 다른 것인지
        # 는 면이 스스로 말하고 있으므로, 시한만 남기지 말고 그 말을 함께 싣는다.
        state = s.js(
            "(function(){var m=document.getElementById('dataPickerModal');"
            "var n=document.getElementById('dataPickerNote');"
            "var all=[].slice.call(document.querySelectorAll('.modal')).map(function(x){"
            "return x.id+'['+x.className+'] depth='+(x.style.getPropertyValue('--modal-depth')||'-');});"
            "return {cls:m?m.className:null, depth:m?(m.style.getPropertyValue('--modal-depth')||'-'):null,"
            " note:n?n.textContent.trim():null, modals:all};"
            "})()"
        )
        raise ScenarioFailure(f"SX-05 데이터 선택 면이 닫히지 않았습니다 — {state}") from exc


def _select_work(surface: Surface, name: str) -> None:
    selector = f'#jobCandidates button[data-cand={json.dumps(name, ensure_ascii=False)}]'
    surface.wait(
        f"!!document.querySelector({json.dumps(selector)})"
        f" && !document.querySelector({json.dumps(selector)}).disabled",
        f"{name} 후보 선택 가능",
        requires=["#jobCandidates"],
    )
    surface.click_sel(selector, what=f"{name} 명시 선택")
    surface.wait(
        f"document.getElementById('jobActionName').textContent.trim() === {json.dumps(name, ensure_ascii=False)}",
        f"{name} active Work",
        requires=["#jobActionName"],
    )


def _apply_staged_template(ctx: ScenarioContext, kind: str) -> None:
    s = ctx.surface
    ctx.stage_template(kind)
    s.click_sel("#jobTplCheck", what=f"{kind} 템플릿 변경사항 확인")
    s.wait(
        "!!document.getElementById('jobTplApply')",
        f"{kind} 템플릿 적용 가능",
        timeout=30.0,
        requires=["#jobTplChange", "#jobTplStatus"],
    )
    s.click_sel("#jobTplApply", what=f"{kind} 템플릿 적용")
    s.wait(
        "(document.getElementById('jobTplNotice')||{textContent:''}).textContent.includes('적용')",
        f"{kind} 템플릿 적용 착지",
        timeout=30.0,
        requires=["#jobTplChange"],
    )


def run_sx(ctx: ScenarioContext) -> dict:
    """Append SX-05 V1–V4 to the existing journey without another normal boot."""
    s = ctx.surface
    seen = ctx.observations

    # Legacy journey ends in the error-work workbench. Return and explicitly select Work A.
    s.click_sel("#wbBack", what="SX-05 진입을 위한 작업대 출구")
    s.wait(
        "document.querySelector('#scr-job.on') !== null || !!window.__cap.btn(null,'나가기')",
        "SX-05 작업대 이탈",
    )
    s.js("window.__cap.clickBtn(null,'나가기'); true;")
    s.wait("document.querySelector('#scr-job.on') !== null", "SX-05 job 복귀", requires=["#scr-job"])
    _select_work(s, "발주요청서")
    s.install_dispatch_probe()

    # V1: actual canonical labels, opaque ids, no local optimism, fresh backend view.
    _apply_staged_template(ctx, "initial")
    s.wait(
        "document.querySelectorAll('#jobContentSelectionZone .cs-slot').length === 3",
        "canonical Slot 세 개",
        requires=["#jobContentSelectionZone"],
    )
    initial = _snapshot(s)
    initial_view = _current_view(initial)
    projection = initial_view["projection"]
    raw_ids = [slot["slot_id"] for slot in projection["slots"]]
    raw_ids += [
        option["option_id"]
        for slot in projection["slots"]
        for option in slot["options"]
    ]
    visible = str(s.js("document.getElementById('jobContentSelectionZone').innerText"))
    _expect(all(raw not in visible for raw in raw_ids), "H1: raw Slot/Option id가 화면에 노출됐습니다")
    labels = s.js(
        "[...document.querySelectorAll('#jobContentSelectionZone "
        ".cs-slot-legend,#jobContentSelectionZone .cs-option-text')].map(e=>e.textContent.trim())"
    )
    _expect(isinstance(labels, list) and len(labels) == 9, "H1: canonical label 전집이 보이지 않습니다")
    audit = ctx.audit_shoot("sx05-content-selection")
    _expect(audit.get("size", 0) > 0 and not audit.get("unstable"), "H1: actual pixel evidence가 불안정합니다")

    s.take_dispatch_trace()
    before_token = initial_view["new_configuration_token"]
    s.click_sel("#cs-opt-0-0", what="공고번호 표시 선택")
    s.wait("document.getElementById('cs-opt-0-0').checked", "첫 Option fresh 반영", requires=["#cs-opt-0-0"])
    after_first = _snapshot(s)
    after_first_view = _current_view(after_first)
    _expect(after_first_view["new_configuration_token"] != before_token, "H2: command 뒤 token이 갱신되지 않았습니다")
    first_option = after_first_view["projection"]["slots"][0]["options"][0]
    _expect(first_option["selected"] and first_option["effective"], "H2: declared/effective intent가 일치하지 않습니다")
    h2_trace = s.take_dispatch_trace()
    _expect(any(item.get("action") == "select_slot_option" for item in h2_trace), "H2: actual Product command trace가 없습니다")
    for selector in ("#cs-opt-1-0", "#cs-opt-2-0"):
        s.click_sel(selector, what="initial canonical Option 선택")
        s.wait(f"document.querySelector({json.dumps(selector)}).checked", "Option fresh 반영", requires=[selector])

    before_fields = tuple(_workbench(_snapshot(s)).get("active_field_requirement_ids") or ())
    s.click_sel("#cs-opt-0-1", what="S1 Option B 전환")
    s.wait("document.getElementById('cs-opt-0-1').checked", "Option B fresh recompute", requires=["#cs-opt-0-1"])
    after_fields = tuple(_workbench(_snapshot(s)).get("active_field_requirement_ids") or ())
    _expect(before_fields != after_fields, "H3: Option A↔B 뒤 Active Field가 변하지 않았습니다")
    s.click_sel("#cs-opt-0-0", what="preserved Option 복원")
    s.wait("document.getElementById('cs-opt-0-0').checked", "preserved Option 복원 반영", requires=["#cs-opt-0-0"])

    # S9-03(#829) 보관된 선택 왕복 — **기존 창·기존 선택 위**에서 밟는다(새 콜드 부팅 0).
    # 저장은 dispatch 로(이름 입력 모달은 프런트 소관이라 여기서는 command 자체를 겨눈다),
    # 적용은 **화면의 버튼**으로 민다: 「적용 n · 깨짐 m」 재진술은 렌더 층이 소유하므로 실제
    # 클릭만이 그 문장이 섰다는 증거다. 깨짐 m>0 갈래는 헤드리스 계약이 진다
    # (`tests/test_webapp_job_preset.py`) — 여기서 successor 를 끌어오면 아래 V2 의 old-token
    # 시나리오가 서 있는 전제(초기 Application)를 이 걸음이 먼저 무너뜨린다.
    preset_name = "sx-preset"
    save_expr = (
        "window.pywebview.api.dispatch('job','save_selection_preset',"
        + json.dumps(
            {
                "configuration_token": _current_view(_snapshot(s))["new_configuration_token"],
                "name": preset_name,
            },
            ensure_ascii=False,
        )
        + ")"
    )
    saved = s.bridge(save_expr, "현재 선택을 프리셋으로 저장")
    _expect(
        isinstance(saved, dict) and saved.get("status") == "SAVED" and saved.get("saved_key"),
        f"S9: 프리셋 저장이 성립하지 않았습니다 — {saved!r}",
    )
    preset_items = (_snapshot(s).get("content_presets") or {}).get("items") or []
    _expect(
        any(item.get("name") == preset_name for item in preset_items),
        f"S9: 저장한 프리셋이 스냅샷 목록에 없습니다 — {preset_items!r}",
    )
    # 목록에 **실제로 보이는지**를 잰다(hidden 요소는 존재해도 사용자에게는 없는 것이다).
    s.wait(
        "[...document.querySelectorAll('#jobContentSelectionZone .cs-preset-name')]"
        f".some(e=>e.offsetParent!==null&&e.textContent.trim()==={json.dumps(preset_name)})",
        "보관된 선택 목록의 실렌더 항목",
        requires=["#jobContentSelectionZone"],
    )
    # 지금을 저장 시점과 다르게 만든 뒤 적용해야 「되돌아왔다」가 vacuous 하지 않다.
    s.click_sel("#cs-opt-0-1", what="프리셋 적용 대조를 위한 다른 선택")
    s.wait("document.getElementById('cs-opt-0-1').checked", "대조 선택 반영", requires=["#cs-opt-0-1"])
    s.gate_dispatch("apply_selection_preset", mode="after")
    s.click_sel("#jobContentSelectionZone .cs-preset-apply", what="보관된 선택 적용")
    s.wait_dispatch_gate("프리셋 적용 응답 보류")
    s.release_dispatch()
    s.wait(
        "document.getElementById('cs-opt-0-0').checked"
        " && !document.getElementById('cs-opt-0-1').checked"
        " && !!document.querySelector('#jobContentSelectionZone .cs-preset-notice-applied')",
        "프리셋 적용 뒤 저장 시점 선택 복귀 + 결과 재진술",
        timeout=30.0,
        requires=["#jobContentSelectionZone"],
    )
    preset_notice = str(s.js(
        "document.querySelector('#jobContentSelectionZone .cs-preset-notice').textContent"
    )).strip()
    _expect("적용했습니다" in preset_notice, f"S9: 적용 결과 재진술이 없습니다 — {preset_notice!r}")
    preset_trace = [
        item for item in s.take_dispatch_trace()
        if item.get("action") == "apply_selection_preset"
    ]
    _expect(preset_trace, "S9: actual 프리셋 적용 command trace가 없습니다")

    # V2: hold the real old-token request, apply successor through the UI, then let it settle stale.
    ctx.stage_template("successor")
    s.gate_dispatch("select_slot_option", mode="before")
    s.click_sel("#cs-opt-1-1", what="old-token Option command")
    s.wait_dispatch_gate("old-token command 보류")
    s.wait("!!document.querySelector('.cs-status-pending')", "content command pending", requires=["#jobContentSelectionZone"])
    s.click_sel("#jobTplCheck", what="successor 템플릿 변경사항 확인")
    s.wait("!!document.getElementById('jobTplApply')", "successor 템플릿 적용 가능", timeout=30.0, requires=["#jobTplChange"])
    s.click_sel("#jobTplApply", what="successor 템플릿 적용")
    s.wait(
        "(document.getElementById('jobTplNotice')||{textContent:''}).textContent.includes('적용')",
        "successor 템플릿 적용 착지",
        timeout=30.0,
        requires=["#jobTplChange"],
    )
    s.release_dispatch()
    # 셋이 **화면에서** 서로 다른 것으로 서야 한다(#728 H4). 남은 둘은 각자의 Slot 자리에서
    # 서로 다른 fate 로 말하고, 사라진 항목은 별도 정보 블록으로 갈린다.
    #
    # `.cs-detached` 를 기다리지 않는다: 그 블록은 #903 에서 제거됐다. 근거는 그것이 소비하던
    # `detached_selections` 가 SG-01(#733) 이후 제품 경로에서 구조적으로 영영 비기 때문이다 —
    # declared 에 실리려면 AUTO_KEEP 이어야 하고, AUTO_KEEP 이려면 그 Option 이 target 에
    # **있어야** 하므로 「없다」와 동시에 성립할 수 없다. 이전 선택의 운명은 #777 이 세운
    # `retained_selections` 가 나른다.
    s.wait(
        "!!document.querySelector('.cs-status-stale')"
        " && document.querySelectorAll('#jobContentSelectionZone .cs-slot').length === 2"
        " && !!document.querySelector('#jobContentSelectionZone"
        " .cs-retained-note[data-fate=\"RESOLVED\"]')"
        " && !!document.querySelector('#jobContentSelectionZone"
        " .cs-retained-note[data-fate=\"SELECTED_OPTION_REMOVED\"]')"
        " && !!document.querySelector('#jobContentSelectionZone .cs-retained-gone')",
        "stale notice와 skipped successor hydrate + 세 갈래 이전 선택",
        timeout=30.0,
        requires=["#jobContentSelectionZone"],
    )
    successor = _snapshot(s)
    successor_view = _current_view(successor)
    successor_projection = successor_view["projection"]
    fates = {
        item["slot_id"]: item["fate"]
        for item in successor_projection.get("retained_selections", ())
    }
    _expect(fates, "H4: 이전 선택이 조용히 사라졌습니다")
    _expect("RESOLVED" in fates.values(), "H4: 그대로 다시 고를 수 있는 선택이 없습니다")
    _expect("SELECTED_OPTION_REMOVED" in fates.values(), "H4: broken selection이 없습니다")
    _expect("SLOT_REMOVED" in fates.values(), "H4: detached selection이 없습니다")
    _expect(len(set(fates.values())) == 3, f"H4: 세 상태가 같은 행동으로 뭉쳤습니다 — {fates}")
    # 사라진 항목은 자동 부활하지 않는다 — 현재 구성의 일부가 아니다.
    current_slot_ids = {slot["slot_id"] for slot in successor_projection["slots"]}
    detached_ids = {sid for sid, fate in fates.items() if fate == "SLOT_REMOVED"}
    _expect(
        not (detached_ids & current_slot_ids),
        "H4: 사라진 항목이 현재 구성으로 되살아났습니다",
    )
    # 내부 어휘는 여전히 화면에 없다(H1 은 이 새 문안에도 걸린다).
    successor_visible = str(s.js("document.getElementById('jobContentSelectionZone').innerText"))
    _expect(
        all(sid not in successor_visible for sid in fates),
        "H4: 이전 선택 문안이 내부 Slot id 를 노출했습니다",
    )
    stale_trace = s.take_dispatch_trace()
    stale_commands = [item for item in stale_trace if item.get("action") == "select_slot_option"]
    _expect(stale_commands, "H5: stale command trace가 없습니다")

    # Repair the broken option and its exact Binding target, then return through the real entry seam.
    #
    # 셋의 **행동이 다르다**는 것을 여기서 실제로 밟는다. broken 은 고른 것이 사라졌으니 **다른
    # 것**을 골라야 닫히고, 유지된 것은 **같은 것을 다시 고르면** 닫힌다(자동 승계가 아니므로
    # 확인은 사용자가 한다). 사라진 항목은 어느 쪽으로도 닫히지 않는다 — 정보로만 남는다.
    s.click_sel("#cs-opt-1-0", what="깨진 선택 복구")
    s.wait("document.getElementById('cs-opt-1-0').checked", "깨진 선택 복구 반영", requires=["#cs-opt-1-0"])
    s.click_sel("#cs-opt-0-0", what="유지된 이전 선택 재확인")
    s.wait("document.getElementById('cs-opt-0-0').checked", "재확인 반영", requires=["#cs-opt-0-0"])
    s.wait(
        "!document.querySelector('#jobContentSelectionZone"
        " .cs-retained-note[data-fate=\"RESOLVED\"]')"
        " && !document.querySelector('#jobContentSelectionZone"
        " .cs-retained-note[data-fate=\"SELECTED_OPTION_REMOVED\"]')"
        " && !!document.querySelector('#jobContentSelectionZone .cs-retained-gone')",
        "닫은 항목의 안내는 사라지고 사라진 항목은 남는다",
        requires=["#jobContentSelectionZone"],
    )
    closed = _current_view(_snapshot(s))["projection"]
    _expect(
        {item["fate"] for item in closed.get("retained_selections", ())} == {"SLOT_REMOVED"},
        "H4: 닫은 이전 선택이 계속 남거나 사라진 항목이 조용히 없어졌습니다",
    )
    exact_target = "binding/추가확인"
    exact_selector = f'#jobInputRequirements button[data-exact-target="{exact_target}"]'
    s.wait(f"!!document.querySelector({json.dumps(exact_selector)})", "신규 Active Field exact Binding", requires=["#jobInputRequirements"])
    s.js(
        "(function(){window.__focusLog=[];"
        "document.addEventListener('focusin',function(e){var t=e.target||{};"
        "window.__focusLog.push((t.tagName||'?')+'#'+(t.id||'')+'|'"
        "+((t.getAttribute&&t.getAttribute('data-act'))||''));},true);return true;})()"
    )
    s.click_sel(exact_selector, what="신규 Binding 수정")
    row = '#editor-body table.map tr[data-field="추가확인"]'
    source_select = row + ' select[data-act="row-source"]'
    s.wait(
        f"document.querySelector('#scr-editor.on') !== null && !!document.querySelector({json.dumps(source_select)})",
        "Binding editor exact row",
        requires=["#scr-editor", row],
    )
    # 초점은 진입 **뒤 렌더**가 세운다(`editor.aimAt` → `aimAtTarget`). 행의 존재를 본 그 순간에
    # 한 번 찍으면 아직 안 왔을 수 있다 — 그건 제품이 안 세운 것이 아니라 우리가 일찍 본 것이다.
    # 조건으로 기다리되 시한을 넘기면 시끄럽게 죽는다: 「안 세웠다」와 「아직 안 왔다」를 통과로
    # 뭉개지 않는다(대기는 단언을 약화시키는 것이 아니라 그 순간을 정확히 겨누는 것이다).
    focus_state = s.js(
        "(function(){"
        "const rowEl=document.querySelector(" + json.dumps(row) + ");"
        "const sel=rowEl?rowEl.querySelector('select[data-act=\"row-source\"]'):null;"
        "const a=document.activeElement;"
        "return {row:!!rowEl, select:!!sel, focused:!!sel&&a===sel,"
        " active:a?(a.tagName+'#'+(a.id||'')+'|'+(a.getAttribute('data-act')||'')):null,"
        " editorOn:!!document.querySelector('#scr-editor.on')};"
        "})()"
    )
    editor_snapshot = s.bridge("window.pywebview.api.initial('editor')", "현재 editor projection")
    editor_context = (editor_snapshot or {}).get("context") if isinstance(editor_snapshot, dict) else None
    _expect(
        isinstance(focus_state, dict) and focus_state.get("focused"),
        "H4: Binding deep-link가 exact source select에 focus하지 않았습니다 — "
        f"{focus_state} · editor context={editor_context} · focus log={s.js('window.__focusLog')}",
    )
    s.set_value(source_select, "공고명")
    s.js(
        "(function(){const c=document.querySelector(" + json.dumps(row + ' input[data-act="row-confirm"]') + ");"
        "if(c && !c.checked)c.click();return !!c;})()"
    )
    s.wait(
        "document.querySelector(" + json.dumps(row + ' input[data-act="row-confirm"]') + ").checked",
        "신규 Binding 확정",
        requires=[row],
    )
    # 수리 진입은 **저장된 작업의 편집 모드**다 — footer 가 마법사의 「작업 저장」이 아니라
    # 「변경 저장」을 낸다(저장·버리기를 상시 표시 + 상태 비활성으로 두는 U2 §2.4 형상).
    # 여기서 마법사 문안을 겨누면 없는 버튼을 기다리게 된다.
    s.click_text("#scr-editor", "변경 저장")
    s.wait("document.querySelector('#scr-editor').textContent.includes('저장했습니다')", "Binding 저장", timeout=30.0, requires=["#scr-editor"])
    s.click_text("#editorContext", "문서 만들기로 돌아가기")
    s.wait("document.querySelector('#scr-job.on') !== null", "Binding ReturnContext", timeout=30.0, requires=["#scr-job"])
    binding_after = _workbench(_snapshot(s))
    # U3-03(#876): 「입력이 필요한 항목」 존은 조치 필요만 싣는다 — 수리된 Active Field 는 활성
    # 누름틀로는 남고 이 목록에서만 사라진다. 그 둘을 함께 봐야 「갱신됐다」가 증명된다.
    repaired = {
        "field_id": "추가확인",
        "active_field": "추가확인" in tuple(binding_after.get("active_field_requirement_ids", ())),
        "pending_action": any(
            item.get("field_id") == "추가확인"
            for item in binding_after.get("input_requirements", ())
        ),
    }
    _expect(
        repaired["active_field"] and not repaired["pending_action"],
        "H4: Binding 저장 뒤 current recompute가 갱신되지 않았습니다",
    )

    # H5 context axis: deterministic lower-layer corruption only induces the real snapshot/recovery UI.
    ctx.stage_context("corrupt")
    s.click_sel('.navbtn[data-scr="library"]', what="context error snapshot 유발")
    s.wait("document.querySelector('#scr-library.on') !== null", "context error 전환")
    s.click_sel('.navbtn[data-scr="job"]', what="context error job 복귀")
    s.wait(
        "document.getElementById('jobContentSelectionZone').textContent.includes('포함할 내용을 불러오지 못했습니다')"
        " && !!window.__cap.btn('#jobContentSelectionZone','다시 불러오기')",
        "backend context copy/action",
        requires=["#jobContentSelectionZone"],
    )
    context_text = str(s.js("document.getElementById('jobContentSelectionZone').innerText"))
    _expect("INVALID_CONFIGURATION_TOKEN" not in context_text, "H5: context raw code가 화면에 노출됐습니다")
    ctx.stage_context("restore")
    s.click_text("#jobContentSelectionZone", "다시 불러오기")
    s.wait("document.querySelectorAll('#jobContentSelectionZone .cs-slot').length === 2", "context recovery", timeout=30.0, requires=["#jobContentSelectionZone"])

    # Record recovery: the blank value is induced by a real DataTarget transition; PASS comes from Product projection/DOM.
    blank_path = ctx.stage_data("blank")
    _mount_data(ctx, blank_path)
    s.click_sel("#jobSelAll", what="blank record 전체 선택")
    s.wait("!!document.querySelector('#jobRecordValidationIssues button')", "record validation issue", timeout=30.0, requires=["#jobRecordValidationIssues"])
    record_before = _workbench(_snapshot(s))
    issue = record_before["record_validation"]["issues"][0]
    old_recovery_target = issue["recovery_target"]
    s.click_sel("#jobRecordValidationIssues button", what="exact record recovery")
    s.wait("document.activeElement && document.activeElement.id.startsWith('job')", "record ReturnContext focus")
    record_focus = str(s.js("document.activeElement.id"))
    _expect(record_focus, "H5: record recovery가 exact focus를 내지 않았습니다")
    _mount_data(ctx, ctx.stage_data("clean"))
    recovery_expr = (
        "window.pywebview.api.dispatch('job','recover_record_issue',"
        + json.dumps({"target": old_recovery_target}, ensure_ascii=False)
        + ")"
    )
    old_recovery = s.bridge(recovery_expr, "old record recovery target 거절")
    # 전환은 `_reset_range_for_snapshot` 에서 record preparation 을 무효화한다
    # (`screen_job.py:743`). 그래서 옛 좌표는 「…복원할 수 없습니다」 가지가 아니라 그 **앞의**
    # 「현재 데이터 확인 결과가 없습니다」로 거절된다 — 둘 다 옳은 거절이고, 계약은 한 문장이
    # 아니라 「옛 좌표를 수락하지 않고 현재 데이터에서 다시 확인하라고 말한다」다. 한 가지의
    # 문장을 통째로 겨누면 옳은 거절을 실패로 읽는다(수락은 거절 문안 자체가 없어 걸린다).
    old_message = _rejection_message(old_recovery)
    _expect(
        "다시 확인해" in old_message,
        f"H7: old record recovery target이 수락됐습니다 — {old_recovery!r}",
    )

    # Exact delivery + OPTIONAL/REQUIRED semantic preview. The harness collision file predates the no-mutation bracket.
    # 새 스냅샷은 선택을 0건으로 되돌린다(`_reset_range_for_snapshot` — 마운트 직후 선택 0건).
    # 그래서 전환 뒤에 배달 계획을 물으려면 **다시 고르는** 걸음이 대본에 있어야 한다. 없으면
    # 제품은 계획 대신 배달 blocker 를 세우므로(`job_run.ts:869-878`) `#jobPlannedDocuments` 는
    # 아예 서지 않고, 그 부재는 「계획이 늦다」가 아니라 「고른 것이 0건이다」라는 뜻이다.
    s.click_sel("#jobSelAll", what="전환 뒤 record 재선택")
    output_dir = ctx.prepare_output()
    ctx.queue_folder_answer(output_dir)
    s.click_sel("#jobManagedPickFolder", what="managed output folder 선택")
    try:
        # `requires` 에 `#jobPlannedDocuments` 를 걸지 않는다 — 그것이 안 서는 것이 바로 제품의
        # 대답이라, requires 로 걸면 뜻 있는 시한이 「없는 요소를 겨눴다」로 둔갑한다.
        s.wait(
            "document.querySelectorAll('#jobPlannedDocuments li').length > 0",
            "exact delivery 계획",
            timeout=30.0,
        )
    except StepTimeout as exc:
        # 계획이 안 서면 제품은 그 이유를 blocker 로 말한다 — 시한만 남기지 말고 그 말을 싣는다.
        blockers = s.js(
            "(function(){var b=document.getElementById('jobDeliveryBlockers');"
            "return b?b.innerText.trim():null;})()"
        )
        raise ScenarioFailure(f"SX-05 배달 계획이 서지 않았습니다 — blockers={blockers!r}") from exc
    optional = _preview_observation(s, "OPTIONAL")
    _expect(optional["preview_requirement"]["kind"] == "OPTIONAL", "H5: OPTIONAL preview가 아닙니다")
    optional_token = optional["semantic_preview"]["preview_token"]
    relative_path = optional["delivery"]["planned_documents"][0]["relative_path"]
    # 읽었으면 닫는다 — 이어지는 충돌 처리·배달 재계산은 작업대 표면의 걸음이라, 서랍을 얹은
    # 채로 밟으면 무엇이 무엇을 가렸는지가 증거에서 흐려진다.
    s.click_sel("#previewClose", what="OPTIONAL preview 닫기")
    s.wait(
        "document.getElementById('previewSheet').classList.contains('hidden')",
        "OPTIONAL preview 닫힘",
        requires=["#previewSheet"],
    )
    ctx.create_collision(relative_path)
    baseline_manifest = ctx.output_manifest()
    s.set_value("#jobDeliveryCollision", "OVERWRITE_EXPLICIT")
    s.wait("!!window.__cap.btn(null,'덮어쓰기 사용')", "overwrite 명시 확인")
    s.click_text(None, "덮어쓰기 사용")
    s.click_sel("#jobRefreshDelivery", what="overwrite exact delivery 재계산")
    s.wait(
        "!!document.querySelector('#jobPlannedDocuments li[data-collision-disposition="
        "\"WRITE_OVERWRITE\"]')",
        "destructive overwrite delivery",
        timeout=30.0,
        requires=["#jobPlannedDocuments"],
    )
    required = _preview_observation(s, "REQUIRED")
    _expect(required["preview_requirement"]["kind"] == "REQUIRED", "H5: REQUIRED preview가 아닙니다")
    _expect(required["preview_requirement"].get("reason") == "DESTRUCTIVE_OVERWRITE", "H5: REQUIRED reason이 틀렸습니다")
    current_token = required["semantic_preview"]["preview_token"]
    old_preview_expr = (
        "window.pywebview.api.dispatch('job','preview_approve',"
        + json.dumps({"preview_token": optional_token})
        + ")"
    )
    old_preview = s.bridge(old_preview_expr, "old preview token 거절")
    _expect(
        "생성 내용이 바뀌었습니다" in _rejection_message(old_preview),
        "H7: old preview token이 수락됐습니다",
    )
    s.click_sel("#jobManagedPreviewOpen", what="REQUIRED semantic preview")
    s.wait(
        "!document.getElementById('previewSheet').classList.contains('hidden')"
        " && document.getElementById('previewSheet').textContent.includes('생성 내용')",
        "semantic/value preview",
        requires=["#previewSheet"],
    )
    preview_text = str(s.js("document.getElementById('previewSheet').innerText"))
    _expect("Artifact" not in preview_text and "아티팩트" not in preview_text, "H6: preview를 Artifact로 표현했습니다")
    s.click_sel("#previewApprove", what="current preview 승인")
    # 승인이 착지하면 이 서랍은 승인 버튼을 **지운다**(`job_preview.ts:121-127` — 요구가 남아
    # 있을 때만 서는 블록이라 satisfied 뒤에는 null 이다). 다른 변형(`:205-213`)은 display 로
    # 숨기지만 여기 오는 것은 앞의 것이다. 그래서 「display 가 none 인가」로 재면
    # `getElementById` 가 null 을 내고 `getComputedStyle` 이 던진다 — 착지가 예외로 둔갑한다.
    # 착지의 증거는 버튼의 **부재**와 문안의 전환을 함께 본다: 문안만 보면 승인 전 버튼 라벨이
    # 같은 말("확인 완료")을 해서 vacuous 하다.
    s.wait(
        "!document.getElementById('previewApprove')"
        " && document.getElementById('previewSheet').textContent.includes('확인 완료')",
        "current preview 승인 착지",
        requires=["#previewSheet"],
    )
    s.click_sel("#previewClose", what="managed preview 닫기")
    s.wait("document.getElementById('previewSheet').classList.contains('hidden')", "managed preview 닫힘", requires=["#previewSheet"])
    # S6-05(#812): 클릭 간극이 닫혔다 — 열린 create 를 실제로 눌러 managed materialization
    # 이 actual WebView2 에서 문서를 앉히는 것까지가 이 지점의 수직 증거다(H6 극성 전환:
    # 「filesystem 불변」→「계획된 문서가 실제로 생겼다」).
    s.wait(
        "!document.getElementById('jobManagedCreate').disabled",
        "S6-03 admitted enabled create",
        requires=["#jobManagedCreate"],
    )
    final_managed = _workbench(_snapshot(s))
    planned_names = [
        item["relative_path"]
        for item in final_managed["delivery"]["planned_documents"]
    ]
    s.click_sel("#jobManagedCreate", what="managed 문서 만들기")
    s.wait(
        "(document.getElementById('jobResult')||{dataset:{}}).dataset.state === 'completed'",
        "managed 생성 완료 착지",
        timeout=60.0,
        requires=["#jobResult"],
    )
    after_manifest = ctx.output_manifest()
    _expect(after_manifest != baseline_manifest, "H6: managed create가 filesystem을 바꾸지 못했습니다")
    for name in planned_names:
        _expect(name in after_manifest, f"H6: 계획된 문서 {name!r} 가 실제로 생기지 않았습니다")
    s.click_sel("#jobResultClose", what="managed 결과 닫기")

    # V4 data transition: cancel/failure are atomic, compatible keeps A, incompatible releases without auto-select.
    before_cancel = _snapshot(s)
    s.click_sel("#jobBtnPickData", what="DataTarget cancel 대조")
    s.wait("!document.getElementById('dataPickerModal').classList.contains('hidden')", "DataTarget cancel 면")
    s.click_sel("#dataPickerClose", what="DataTarget cancel")
    # 닫힘이 **정착할 때까지** 기다린 뒤 다음 걸음을 딛는다. 여기서 그냥 넘어가면 다음
    # `_mount_data` 의 여는 걸음이 아직 스택에 있는 같은 host 를 다시 열려다 멱등 무시로
    # 삼켜지고(`engine.open` — 같은 host 이중 open 은 무시), 대본은 **이미 settle 된 세션**의
    # 면을 보며 「열렸다」고 읽는다. 그러면 찾아보기가 session=null 로 조용히 되돌아와 문안이
    # 영영 안 선다. 로컬은 빨라서 지나가고 CI 러너에서만 터졌다(실측: note='' · current=None).
    s.wait(
        "document.getElementById('dataPickerModal').classList.contains('hidden')",
        "DataTarget cancel 면 닫힘",
        requires=["#dataPickerModal"],
    )
    after_cancel = _snapshot(s)
    _expect(after_cancel.get("job_name") == before_cancel.get("job_name"), "H7: cancel이 active Work를 바꿨습니다")
    _mount_data(ctx, ctx.stage_data("missing"), failure=True)
    after_failure = _snapshot(s)
    _expect(after_failure.get("job_name") == "발주요청서", "H7: failed transition이 committed Work를 바꿨습니다")
    _mount_data(ctx, ctx.stage_data("release"))
    s.wait("document.getElementById('jobActionName').textContent.trim() === ''", "incompatible DataTarget RELEASE", timeout=30.0, requires=["#jobActionName"])
    # 호환 재적재의 계약은 **KEEP** 이다. 그런데 RELEASE 직후엔 이름이 이미 비어 있어서
    # 「비어 있는가」로 물으면 무엇을 하든 참이다 — 그 대기는 아무것도 증언하지 못한다(제품이
    # 저절로 작업을 세우는 길은 명시 `prefer_work` 뿐이라 마운트로는 애초에 안 선다).
    # 그래서 호환 데이터로 되돌린 뒤 **명시로 고르고**, 한 번 더 호환 데이터를 얹어 그 작업이
    # 그대로 서 있는지를 잰다. 순서가 계약이다 — 비호환 데이터 위에서는 후보가 애초에 고를 수
    # 없고(방금 RELEASE 된 이유가 그것이다), 고르지 못하면 KEEP 을 물을 자리도 없다.
    _mount_data(ctx, ctx.stage_data("clean"))
    _select_work(s, "발주요청서")
    _mount_data(ctx, ctx.stage_data("clean"))
    s.wait(
        "document.getElementById('jobActionName').textContent.trim() === '발주요청서'",
        "compatible reload 뒤 active Work KEEP",
        timeout=30.0,
        requires=["#jobActionName"],
    )

    # Work A response cannot land on Work B: send A, hold only its response, switch B, then settle/re-hydrate latest.
    s.gate_dispatch("select_slot_option", mode="after")
    s.click_sel("#cs-opt-0-1", what="Work A pending Option")
    s.wait_dispatch_gate("Work A response 보류")
    _select_work(s, "발주요청 기안")
    s.release_dispatch()
    s.wait(
        "document.getElementById('jobActionName').textContent.trim() === '발주요청 기안'"
        " && document.getElementById('jobContentSelectionZone').textContent.trim() === ''",
        "Work B latest snapshot wins",
        timeout=30.0,
        requires=["#jobActionName"],
    )
    _select_work(s, "발주요청서")

    seen["sx05"] = {
        "H1": {"labels": labels, "raw_ids": raw_ids, "pixel": audit},
        "H2": {"before_token": before_token, "after_token": after_first_view["new_configuration_token"], "trace": h2_trace},
        "H3": {"option_a_fields": before_fields, "option_b_fields": after_fields},
        "H4": {"retained_fates": fates, "binding_target": exact_target, "binding_repaired": repaired},
        "H5": {"context_copy": context_text, "record_focus": record_focus, "optional": optional["preview_requirement"], "required": required["preview_requirement"], "runtime_reason": final_managed["create_action"].get("disabled_reason")},
        "H6": {"preview_token": current_token, "filesystem_before": baseline_manifest, "filesystem_after": ctx.output_manifest()},
        "H7": {"stale_trace": stale_commands, "old_record_rejected": True, "old_preview_rejected": True, "data_transition": "KEEP/RELEASE/FAILURE_ATOMIC", "work_race": "B_WON"},
    }
    return seen


def run_restart(ctx: ScenarioContext) -> dict:
    """Second actual process: durable intent recomputes; session-only values stay absent.

    U3-06(#879) 이후 「저장 폴더」는 그 사이에 선다 — 설정에 기억된 마지막 명시 지정이 **기본값**
    으로 되살지만, 그것은 session intent 의 부활이 아니다(충돌 처리 선언은 기본값으로 돌아온다).

    U3-07(#880) 이후 **데이터도 그 사이에 선다**: 마지막으로 성사된 마운트가 첫 화면에 이미
    서 있다(매 세션 파일을 다시 고르게 하던 자리). 그것도 session 상태의 부활이 아니다 —
    선택은 0건이고 active Work 는 여전히 비어 있다.
    """
    s = ctx.surface
    before_files = ctx.output_manifest()
    initial = _snapshot(s)
    # 자동 마운트는 「파일 다시 고르기」의 대역일 뿐이라 마운트만 승계한다: 데이터는 서고,
    # active Work·선택은 서지 않는다. 실패(파일 소실 등)면 조용한 빈 상태가 아니라
    # `data_notice` 가 사유를 실으므로 그 부재도 성사의 증거다.
    data_restored = {
        "has_data": initial.get("has_data"),
        "selected_count": initial.get("selected_count"),
        "notice": initial.get("data_notice"),
    }
    _expect(
        data_restored == {"has_data": True, "selected_count": 0, "notice": None},
        f"H7: restart가 마지막 사용 데이터를 계약대로 복원하지 않았습니다 — {data_restored!r}",
    )
    _expect(initial.get("has_job") is False, "H7: restart가 active Work를 복원했습니다")
    initial_wb = initial.get("workbench_observation") or {}
    # 작업을 고르기 전에는 저장 폴더를 도출할 재료(템플릿)조차 없다 — 기억이 있어도 여기서는
    # 아무것도 서지 않는다(U3-06 #879: 기억은 도출의 재료이지 그 자체로 세워지는 값이 아니다).
    _expect(initial_wb.get("run_delivery_intent") is None, "H7: 작업 선택 전에 delivery intent가 섰습니다")
    s.wait("document.getElementById('jobActionName').textContent.trim() === ''", "restart 자동 마운트 뒤 active Work 0", requires=["#jobActionName"])
    _select_work(s, "발주요청서")
    current = _snapshot(s)
    view = _current_view(current)
    selected = {
        slot["slot_id"]: [option["option_id"] for option in slot["options"] if option["effective"]]
        for slot in view["projection"]["slots"]
    }
    wb = _workbench(current)
    # U3-03(#876): 수리된 Binding 은 활성 누름틀로 남되 「입력이 필요한 항목」에는 안 실린다.
    binding = {
        "field_id": "추가확인",
        "active_field": "추가확인" in tuple(wb.get("active_field_requirement_ids", ())),
        "pending_action": any(
            item.get("field_id") == "추가확인" for item in wb.get("input_requirements", ())
        ),
    }
    _expect(
        binding["active_field"] and not binding["pending_action"],
        "H7: durable Binding이 restart 뒤 복원되지 않았습니다",
    )
    # U3-06(#879): 저장 폴더는 restart 뒤에도 선다 — 다만 **기억한 기본값**으로다. session 선언이
    # 부활하는 것이 아니라는 사실을 세 값이 함께 말한다: 경로는 지난번 명시 지정 그대로이고
    # 출처는 「기억한 폴더」인데, 지난 세션이 명시로 골랐던 파괴적 충돌 처리
    # (OVERWRITE_EXPLICIT)는 비파괴 기본값으로 돌아와 있다.
    intent = wb.get("run_delivery_intent") or {}
    delivery_default = {
        "directory": intent.get("output_directory"),
        "source": (wb.get("output_folder") or {}).get("source"),
        "collision_policy": intent.get("collision_policy"),
    }
    _expect(
        delivery_default == {
            "directory": ctx.output_dir,
            "source": "remembered",
            "collision_policy": "ADD_SUFFIX",
        },
        f"H7: 저장 폴더 기억이 계약대로 복원되지 않았습니다 — {delivery_default!r}",
    )
    _expect(wb.get("semantic_preview") is None, "H7: session preview가 거짓 복원됐습니다")
    after_files = ctx.output_manifest()
    _expect(after_files == before_files, "H7: restart observation이 filesystem을 변경했습니다")
    return {
        "sx05_restart": {
            "durable": {"job": current.get("job_name"), "selections": selected, "binding": binding},
            "delivery_default": delivery_default,
            "data_restored": data_restored,
            "session_absent": {"active_work_before_reselect": True, "delivery_collision": True, "preview": True},
            "filesystem_before": before_files,
            "filesystem_after": after_files,
        }
    }


# ══════════════════════════════════════════════════ 온보딩 여정(#895 · 슬라이스 F)
#
# 정본은 ``docs/ONBOARDING_TUTORIAL.md`` §3.3~3.6(T0~T17)·§4.5 다. 위의 101 대본과 **홈 전제가
# 반대**라는 것이 이 절의 요점이다: 101 은 커밋된 자산이 시딩된 홈에서 돌지만, 온보딩은 **빈
# 홈**에서 시작해 앱 안의 「예제로 시작하기」가 번들 원천을 스스로 풀어 앉히는 것부터 잰다.
# 그래서 자산을 미리 깔면 이 대본의 첫 검사 대상이 사라진다(:data:`~.driver.PHASES` 주석).

#: 빈 홈에 **부팅만으로** 생기는 것 — 여기 없는 파일이 설치 전에 있으면 시끄럽게 죽는다.
#:
#: 이 목록이 화이트리스트인 이유는 「0건」이 참이 아니기 때문이다: 앱은 부팅 자체로 설정과
#: WebView2 프로필을 쓴다. 그렇다고 "설치 전 census 는 안 본다"로 가면 D1 계약(누르기 전에는
#: 홈에 아무것도 쓰지 않는다, #891)을 재는 자리가 통째로 사라진다. 그래서 **부팅 잔재만**
#: 통과시키고 나머지는 전부 거절한다 — 새 부팅 산물이 생기면 이 목록을 고치라고 빨강이 난다.
BOOT_RESIDUE_PREFIXES: "tuple[str, ...]" = (
    "settings.json",        # 부팅 완주 스탬프(`boot_completed_runtime`)와 사용자 설정
    "ui_settings.ini",      # 창 기하 기억
    "webapp-alerts.log",    # 경보 채널의 곁사본
    # WebView2 프로필(``webview/``)은 여기 없다 — census 가 **애초에 싣지 않는다**
    # (:func:`~.driver.home_census` 가 그 이유를 진다: 실행 중 잠겨 읽히지도 않고, 앱이
    # 스스로 통청소하는 자기 작업 공간이라 D1 이 재는 「사용자 홈에 쓴 것」이 아니다).
    "template_authority/",  # S3 권위 스토어의 부팅 초기화(빈 하위 스토어 + 토큰 비밀)
    "presets/",             # Selection Preset 레지스트리 초기화
    "jobs/",                # 작업 레지스트리 폴더 초기화(설치 전에는 **기재 0건**이어야 한다)
    "datasets/",            # 데이터 참조 풀 초기화(같은 이유로 슬롯 0건)
)

#: 설치가 홈에 앉혀야 하는 것 — census 로 **디스크에서** 되짚는 자리(화면 말고).
INSTALLED_RELATIVE: "tuple[str, ...]" = (
    *(f"templates/{name}" for name in HWPX_ASSETS),
    *(f"text_templates/{name}" for name in TXT_ASSETS),
    *(f"example_data/{name}" for name in DATA_ASSETS),
)

#: 생성물이 떨어지는 자리(홈 상대 · :data:`~.driver.RESULTS_REL` 과 같은 곳).
RESULTS_PREFIX = "templates/Results/"

#: 온보딩 작업 이름 — 티어별로 하나씩. 이름이 곧 ``#jobCandidates`` 의 ``data-cand`` 다.
ONBOARDING_JOBS = {
    "basic": "계약체결안내",
    "applied_hwpx": "구매추진안내",
    "applied_txt": "계약안내 기안",
    "error": "오류연습 보증금",
    "advanced": "공고서 연습",
}

#: 기본 데이터의 행 수 = 기본 티어가 만들어야 하는 문서 수(``계약목록.csv`` 3행).
ONBOARDING_ROWS = 3


def _results(census: "dict[str, str]") -> "dict[str, str]":
    """홈 census 에서 생성 산출물만 — 상대경로 → sha256."""
    return {
        path: digest
        for path, digest in census.items()
        if path.startswith(RESULTS_PREFIX) and path.endswith(".hwpx")
    }


def _confirm(ctx: "ScenarioContext", label: str, what: str) -> str:
    """공용 확인 모달을 **라벨로 겨눠** 확정하고 재진술 본문을 돌려준다.

    라벨을 정확 대조하는 것이 요점이다. ``#confirmModalOk`` 는 어느 확인이든 같은 노드라,
    존재만 재면 **다른 확인**(가령 이탈 가드)이 떠 있어도 통과한다 — 그러면 대본이 사용자가
    보지 않은 것을 눌러 놓고 초록으로 지나간다. 판정·수치·문안은 Python 이 내고 확인 UI 는
    웹이 그린다는 계약이 여기서 검사된다: 본문을 돌려주는 이유도 그것이다.
    """
    s = ctx.surface
    s.wait(
        "(function(){"
        "if(document.getElementById('confirmModal').classList.contains('hidden'))return false;"
        "return document.getElementById('confirmModalOk').textContent.trim() === "
        f"{json.dumps(label, ensure_ascii=False)};}})()",
        f"{what} 확인 모달(「{label}」)",
        timeout=30.0,
        requires=["#confirmModal", "#confirmModalOk"],
    )
    body = str(s.js("document.getElementById('confirmModalBody').textContent")).strip()
    s.click_sel("#confirmModalOk", what=f"{what} 확정")
    s.wait(
        "document.getElementById('confirmModal').classList.contains('hidden')",
        f"{what} 확인 모달 닫힘",
        requires=["#confirmModal"],
    )
    return body


def _goto_library(ctx: "ScenarioContext", what: str) -> None:
    s = ctx.surface
    s.click_sel('.navbtn[data-scr="library"]', what=f"문서 작업 탭({what})")
    s.wait(
        "document.querySelector('#scr-library.on') !== null",
        f"문서 작업 화면({what})",
        requires=["#scr-library"],
    )


def _open_editor(ctx: "ScenarioContext", what: str) -> None:
    """「＋ 새 작업」으로 편집기(몰입 표면)에 들어가 라이브러리 피커 단계에 선다."""
    _goto_library(ctx, what)
    s = ctx.surface
    s.click_sel("#libraryNewWork", what=f"새 작업({what})")
    s.wait(
        "document.querySelector('#scr-editor.on') !== null"
        " && !!document.querySelector('#scr-editor [data-act=\"install-examples\"]')",
        f"편집기 라이브러리 피커({what})",
        requires=["#scr-editor"],
    )


def _leave_editor(ctx: "ScenarioContext", what: str) -> None:
    s = ctx.surface
    s.click_sel("#editorBack", what=f"편집기 출구({what})")
    s.wait(
        "document.querySelector('#scr-job.on') !== null",
        f"편집기 이탈({what})",
        requires=["#scr-job"],
    )


def _save_work(
    ctx: "ScenarioContext",
    *,
    template: str,
    name: str,
    confirmed: str,
    pattern: "str | None" = None,
    empty_confirm: bool = False,
) -> bool:
    """편집기 한 바퀴 — 템플릿 채택 → 데이터 연결 → 전 행 확정 → (파일 이름) → 저장.

    ``pattern`` 이 있으면 hwpx 3탭 세션(파일 이름 탭을 지난다), 없으면 TXT 2탭 세션이다 —
    파일을 만들지 않는 작업에는 그 탭이 아예 없다(§3.2). ``empty_confirm`` 은 데이터에 **열
    자체가 없는** 항목이 있어 저작측 결핍 게이트를 지나야 하는 갈래다(T14).

    **게이트가 실제로 떴다는 사실을 돌려준다.** T14 는 「단계가 체크됐다」로 재면 안 되는
    자리다: 퍼지 제안 임계가 다시 낮아지면(#908 이 0.6→0.7 로 올린 그 값) ``계약보증금`` 이
    ``계약금액`` 에 자동 결속돼 게이트가 **서지 않고**, 그래도 저장은 성립한다. 그때 조용히
    지나가는 것은 잘못된 열이 결속된 작업이므로, 게이트의 발화 자체가 보고서에 남아 판정을
    받아야 한다(대본의 대기는 실행 중에만 살아 있다).
    """
    s = ctx.surface
    _open_editor(ctx, name)
    s.click_sel(
        f'#scr-editor button[data-act="use-library"][data-path*="{template}"]',
        what=f"{template} 템플릿 채택",
    )
    s.wait(
        "document.querySelector('#scr-editor').textContent.includes('공고번호')",
        f"{name} 템플릿 스키마",
        requires=["#scr-editor"],
    )
    s.click_text("#scr-editor", "다음 ▶")
    s.wait(
        "!!window.__cap.btn('#scr-editor','파일 선택…')",
        f"{name} 데이터 관문",
        requires=["#scr-editor"],
    )
    # 편집기의 매핑 관문은 고정 데이터를 받지 못한다 — 여는 동사가 native 파일 선택 하나뿐이라
    # (`editor.ts` 의 `pickData`), 설치된 예제 CSV 의 실경로로 답한다.
    ctx.queue_file_answer(ctx.csv_path)
    s.click_text("#scr-editor", "파일 선택…")
    s.wait(
        "!!window.__cap.btn('#scr-editor','모두 확정')"
        " && document.querySelector('#scr-editor').textContent.includes('한빛과학기술연구원')",
        f"{name} 매핑표 미리보기",
        timeout=30.0,
        requires=["#scr-editor"],
    )
    s.click_text("#scr-editor", "모두 확정")
    gate_fired = False
    if empty_confirm:
        # 데이터에 열 자체가 없는 「계약보증금」 — 채우지 않고 비움으로 확정할지 **묻는다**.
        s.wait("!!window.__cap.btn(null,'비움으로 확정')", f"{name} 비움 확정 이름게이트")
        s.click_text(None, "비움으로 확정")
        gate_fired = True
    s.wait(
        f"document.querySelector('#scr-editor').textContent.includes({json.dumps(confirmed)})",
        f"{name} 전 행 확정({confirmed})",
        requires=["#scr-editor"],
    )
    if pattern is not None:
        s.click_text("#scr-editor", "다음 ▶")
        s.wait(
            "!!document.querySelector('#scr-editor input[data-act=\"pattern\"]')",
            f"{name} 파일 이름 탭",
            requires=['#scr-editor input[data-act="pattern"]'],
        )
        s.set_value('#scr-editor input[data-act="pattern"]', pattern)
    s.set_value("#editorName", name)
    s.click_text("#scr-editor", "작업 저장")
    s.wait(
        "document.querySelector('#scr-editor').textContent.includes('저장했습니다')",
        f"{name} 저장 착지",
        timeout=30.0,
        requires=["#scr-editor"],
    )
    _leave_editor(ctx, name)
    return gate_fired


def _mount_pinned(ctx: "ScenarioContext", name: str) -> None:
    """「고정한 데이터」에서 한 건을 마운트한다 — 파괴적 교체면 중간 확인을 실제로 지난다."""
    s = ctx.surface
    pinned = (
        "#dataPickerPinned button[data-act=\"use\"]"
        f"[data-name={json.dumps(name, ensure_ascii=False)}]"
    )
    s.click_sel("#jobBtnPickData", what=f"데이터 선택({name})")
    s.wait(
        "!document.getElementById('dataPickerModal').classList.contains('hidden')"
        f" && !!document.querySelector({json.dumps(pinned)})",
        f"데이터 선택 면·고정 항목({name})",
        timeout=30.0,
        requires=["#dataPickerModal", "#dataPickerPinned"],
    )
    s.click_sel(pinned, what=f"고정 데이터 사용({name})")
    # 실행 증거가 서 있으면 교체는 파괴 전이라 확인을 **먼저** 받는다(`confirmDestructiveIfArmed`).
    # 그 확인은 조건부라, 「떴으면 지난다」를 한 대기 안에서 갈라야 대본이 두 갈래에 다 산다.
    s.wait(
        "(function(){"
        "const m=document.getElementById('confirmModal');"
        "if(m && !m.classList.contains('hidden'))return true;"
        "return document.getElementById('dataPickerModal').classList.contains('hidden');})()",
        f"교체 확인 또는 마운트 착지({name})",
        timeout=30.0,
        requires=["#dataPickerModal"],
    )
    if not s.js("document.getElementById('confirmModal').classList.contains('hidden')"):
        _confirm(ctx, "데이터 바꾸고 버리기", f"데이터 교체({name})")
    s.wait(
        "document.getElementById('dataPickerModal').classList.contains('hidden')"
        " && document.getElementById('jobDataLabel').value.includes("
        f"{json.dumps(name, ensure_ascii=False)})",
        f"데이터 마운트 착지({name})",
        timeout=30.0,
        requires=["#dataPickerModal", "#jobDataLabel"],
    )


def _select_all(ctx: "ScenarioContext", job: str) -> None:
    """후보 카드를 **명시로** 고르고 전체 선택까지 — 마운트 직후 선택은 0건이다(§18.2)."""
    _select_work(ctx.surface, job)
    s = ctx.surface
    s.wait(
        "!document.getElementById('jobSelAll').disabled",
        f"{job} 전체 선택 가능",
        requires=["#jobSelAll"],
    )
    s.click_sel("#jobSelAll", what=f"전체 선택({job})")
    # 클릭이 아니라 **선택이 선 것**이 이 걸음의 착지다: 작업 저장 직후의 새 스냅샷은 범위를
    # 0건으로 되돌리므로(`_reset_range_for_snapshot`), 누른 사실만 믿고 넘어가면 다음 걸음이
    # 「0건 선택」 게이트를 제품 결함으로 읽는다.
    s.wait(
        "(function(){const g=document.getElementById('jobGate');"
        "return !!g && !g.textContent.includes('최소 1건');})()",
        f"{job} 선택 착지",
        timeout=30.0,
        requires=["#jobGate"],
    )


def _approve(
    ctx: "ScenarioContext", what: str, *, managed: bool, expect_text: "str | None" = None
) -> str:
    """생성 값 미리보기를 열어 승인하고 닫는다 — 승인은 **버튼의 부재**로 착지한다.

    ``expect_text`` 는 승인 **전에** 확인 면이 말하고 있어야 하는 문안이다. 빈 값 표식(T13)이
    그것인데, 그 표식의 계약은 「빈칸으로 새지 않는다」라서 **사용자가 확정하기 전에 보인다**는
    것까지가 계약이다 — 생성된 파일에서만 확인하면 「나중에 보였다」만 증명된다.
    """
    s = ctx.surface
    opener = "#jobManagedPreviewOpen" if managed else "#jobPreviewOpen"
    s.wait(
        f"!!document.querySelector('{opener}') && !document.querySelector('{opener}').disabled",
        f"{what} 미리보기 열기 가능",
        timeout=30.0,
        requires=[opener],
    )
    s.take_dispatch_trace()  # 이 걸음의 왕복만 남기고 앞의 것은 버린다(실패 진단용)
    s.click_sel(opener, what=f"{what} 생성 값 미리보기")
    # 열림을 **가시성**으로 잰다. ``hidden`` 클래스로 재면 실측으로 넘어진다: 재승인에서 다시
    # 열린 서랍은 화면에 서 있고 승인 버튼도 누를 수 있는데 그 클래스가 남아 있었다(관측:
    # `open:false` 인데 `innerText` 는 전문이 나오고 `approve:true`). 클래스는 표면의 사정이고
    # 대본이 물어야 하는 것은 「사용자가 지금 이 승인 버튼을 누를 수 있는가」다.
    try:
        s.wait(
            "(function(){const b=document.getElementById('previewApprove');"
            "if(!b || b.disabled)return false;const st=getComputedStyle(b);"
            "return b.getClientRects().length > 0 && st.display !== 'none'"
            " && st.visibility !== 'hidden';})()",
            f"{what} 확인 면·승인 버튼 가시",
            timeout=30.0,
            requires=["#previewSheet"],
        )
    except StepTimeout as exc:
        # 「열리지 않았다」와 「열렸는데 승인 버튼이 없다」는 전혀 다른 사건이다 — 시한만
        # 남기면 둘이 같은 빨강이 되고, 뒤쪽은 곧 「이미 승인돼 있다」일 수도 있다.
        # 그래서 표면과 **백엔드 투영**을 함께 뜬다: 화면이 안 그린 것과 백엔드가 안 준 것은
        # 고칠 자리가 다르다.
        state = s.js(
            "(function(){const sh=document.getElementById('previewSheet');"
            "const all=[...document.querySelectorAll('#previewApprove')].map(b=>{"
            "const st=getComputedStyle(b);return {label:b.textContent.trim(),"
            " disabled:b.disabled, rects:b.getClientRects().length, display:st.display};});"
            "return {sheet_hidden: !sh || sh.classList.contains('hidden'), approvals: all,"
            " opener_disabled: (document.getElementById('jobPreviewOpen')||{}).disabled,"
            # 셸 상태기계가 「지금 어느 화면인가」를 어떻게 답하는지 — `openPreview` 가 그
            # 답으로 열지 말지를 가르므로(`job_run.ts`), DOM 의 `.on` 과 갈리면 버튼이
            # 죽는다. 튜토리얼 패널 루트가 그 답을 `data-screen` 으로 이미 그리고 있다.
            " nav_screen: (document.getElementById('tutorialPanelRoot')||{dataset:{}})"
            ".dataset.screen,"
            " dom_screen: (document.querySelector('.scr.on')||{}).id,"
            " gate: (document.getElementById('jobGate')||{textContent:''}).textContent.trim()};})()"
        )
        projection = _snapshot(s)
        preview = projection.get("preview") if isinstance(projection, dict) else None
        trace = [
            {k: v for k, v in item.items() if k in ("action", "payload", "response", "error")}
            for item in s.take_dispatch_trace()
        ]
        wb = projection.get("workbench_observation") or {}
        state["out_dir"] = projection.get("out_dir")
        state["output_folder"] = wb.get("output_folder")
        state["preview_requirement"] = wb.get("preview_requirement")
        raise ScenarioFailure(
            f"{what} 확인 면이 승인할 상태로 서지 않았습니다 — DOM {state}"
            f" · preview zone {preview!r} · review {projection.get('review')!r}"
            f" · dispatch trace {trace!r}"
        ) from exc
    if expect_text is not None:
        s.wait(
            "document.getElementById('previewSheet').innerText.includes("
            f"{json.dumps(expect_text, ensure_ascii=False)})",
            f"{what} 확인 면의 {expect_text!r} 표면",
            timeout=30.0,
            requires=["#previewSheet"],
        )
    sheet_text = str(s.js("document.getElementById('previewSheet').innerText"))
    s.click_sel("#previewApprove", what=f"{what} 이 이름과 값으로 승인")
    # 승인의 착지는 버튼의 **부재 또는 숨김**이다. 서랍 변형이 둘이라(하나는 노드를 지우고
    # 하나는 display 로 숨긴다) 한쪽만 겨누면 착지가 예외로 둔갑한다(run_sx 가 만난 함정).
    s.wait(
        "(function(){const b=document.getElementById('previewApprove');"
        "return !b || getComputedStyle(b).display === 'none';})()",
        f"{what} 승인 착지",
        timeout=30.0,
        requires=["#previewSheet"],
    )
    s.click_sel("#previewClose", what=f"{what} 확인 면 닫기")
    s.wait(
        "(function(){const sh=document.getElementById('previewSheet');"
        "return !sh || sh.getClientRects().length === 0;})()",
        f"{what} 확인 면 닫힘",
    )
    return sheet_text


#: 이 대본이 **스스로 지나갈 의사가 있는** 관리 경로 단계(§3.5 T16 「검토 확인들」).
#:
#: 셀렉터는 여기 적지 않는다 — 그것은 제품 소유의 사실이고
#: :func:`~hwpxfiller.webapp.blocker_affordance.managed_primary_action_controls` 가 낸다(#912 D6).
#: 종전에는 이 자리가 코드→셀렉터 **사설 매핑표**였고 정본과 결속이 없어 거짓 항목을 실었다:
#: ``RESOLVE_RUNTIME_POLICY → #jobResolveExecution`` — runtime/policy 는 설계상 동사가 없는 축이라
#: 그 조합에서 버튼이 렌더되지 않는다. 파생으로 옮기면 그 항목은 만들어질 수 없다.
#:
#: 그래도 이 tuple 이 남는 이유는 **범위 선언**이기 때문이다: 파생표에는 데이터·작업 선택처럼
#: 사슬에 들어오기 **전에** 끝났어야 할 동사도 들어 있고, 그것이 여기서 서면 지나갈 일이 아니라
#: 앞 단계가 무너진 것이다. 자동으로 눌러 넘기면 그 사실이 조용히 지나간다.
#: 미리보기·결속은 서랍/편집기 왕복이라 아래 loop 가 따로 다루되, 겨눔은 같은 파생표에서 온다.
_MANAGED_REVIEW_STEPS: "tuple[str, ...]" = (
    "REVIEW_BINDING",
    "REVIEW_PREVIEW",
    "RESOLVE_EXECUTION",
    "REVIEW_DELIVERY",
)


def _managed_review_control(code: str) -> "str | None":
    """관리 검토 단계 코드 → 그것을 푸는 셀렉터(정본 파생). 범위 밖이면 ``None``."""
    if code not in _MANAGED_REVIEW_STEPS:
        return None
    return managed_primary_action_controls().get(code)


def _probe_affordance(s: "Surface", code: str, selector: str) -> dict:
    """그 단계의 컨트롤이 **실제로 어떤 꼴로 서 있는지**를 뜬다(#912 (c) 층).

    재는 것은 하나다: 「존재하고 비활성이 아니거나, 비활성이면 사유가 비어 있지 않다」. 이것이
    #912 결함류의 실창 얼굴이다 — 제품이 무엇을 하라고 지시했는데 그 자리에 누를 것이 없거나,
    비활성인데 왜인지 말하지 않으면 사용자는 거기서 막힌다. 판정은 여기서 내리지 않고
    ``report.py`` 가 보고서만 보고 내린다(관측과 판정의 분리 — 앱 없이 음성 대조를 세우려면
    판정이 대본 밖에 있어야 한다).
    """
    return s.js(
        f"(function(){{const el=document.querySelector({json.dumps(selector)});"
        "if(!el)return {present:false, disabled:null, reason:''};"
        "const row=el.closest('.run-row');"
        "const note=row ? row.querySelector('.capnote') : null;"
        "const create=document.getElementById('jobManagedCreateReason');"
        "return {present:true, disabled: !!el.disabled,"
        " label:(el.textContent||'').trim(),"
        " reason:((note&&note.textContent)||(create&&create.textContent)||'').trim()};})()"
    ) or {"present": False, "disabled": None, "reason": ""}


def _resolve_bindings(ctx: "ScenarioContext", what: str) -> dict:
    """결속 검토(``REVIEW_BINDING``) — 편집기로 건너가 **연결을 확정**하고 돌아온다.

    누름틀 변환이 만든 필드는 **판본에 규칙이 정말 없는 활성 Field**(``NEW_ACTIVE_FIELD``)라,
    편집기 매핑을 확정해 저장한 것과는 다른 층이다: 저 확정은 작업의 매핑 프로필이고, 여기서
    묻는 것은 durable Binding 판본이다. 그래서 「확정 5/5 로 저장했는데 왜 또 묻나」가 아니라
    **처음 묻는 것**이다(§3.5 가 말하는 결속 검토).

    ## 왜 무변경 확정인가 (#911)

    매핑이 이미 옳으면 더럽힐 것이 없어 변경 기반 무장(``armed = dirty || pendingEdits``)이
    영영 안 열린다 — #895 3차 실주행이 정확히 거기서 막혔다(푸터 두 동사 모두 비활성,
    ``REVIEW_BINDING`` 상주). #911 이 무변경 확정 동사 「연결 확정」을 무장했으므로 대본은
    **그 동사를 그대로 누른다**. 종전 우회(모두 해제 → 모두 확정으로 억지 dirty 만들기)는
    이제 쓰지 않는다: 그것은 사용자가 실제로 밟는 길이 아니었고, 그 우회가 초록이면 진짜
    사용자가 막히는 것을 이 게이트가 영영 못 본다.

    확정 동사가 **무변경 갈래로** 섰다는 사실(``data-confirm-binding``·라벨)을 관측에 실어
    돌려준다 — #911 이 실제로 발화했다는 증거이고, 임계가 되돌아가면 이 사실이 먼저 죽는다.
    """
    s = ctx.surface
    pending = [
        str(item.get("exact_target") or "")
        for item in (_workbench(_snapshot(s)).get("input_requirements") or ())
        if item.get("action_required") is True
    ]
    _expect(pending, f"{what}: 결속 검토를 요구하는데 조치 대상이 비었습니다")
    target = (
        "#jobInputRequirements button"
        f"[data-exact-target={json.dumps(pending[0], ensure_ascii=False)}]"
    )
    s.click_sel(target, what=f"{what} 결속 수정 진입")
    s.wait(
        "document.querySelector('#scr-editor.on') !== null"
        " && !!document.querySelector('#editor-body table.map')",
        f"{what} 결속 편집기",
        timeout=30.0,
        requires=["#scr-editor"],
    )
    # 확정 동사를 **바꾸지 않고** 기다린다(#911). 손대지 않았으므로 dirty 는 거짓이고, 무장의
    # 사유는 오직 `binding_confirm.pending` 이다 — 그 갈래가 정확히 이 걸음이 재는 것이다.
    # 서지 않으면 「내 선택자가 틀렸다」와 「사용자가 여기서 막힌다」가 같은 빨강이 되므로
    # 푸터 상태를 통째로 떠서 문장으로 가른다(#895 3차가 이 진단으로 막다른 길을 이름 지었다).
    save_sel = '#editor-foot button[data-act="save"]'
    try:
        s.wait(
            f"(function(){{const b=document.querySelector({json.dumps(save_sel)});"
            "return !!b && !b.disabled;})()",
            f"{what} 연결 확정 동사 무장",
            timeout=30.0,
            requires=["#editor-foot"],
        )
    except StepTimeout as exc:
        state = s.js(
            "(function(){const f=document.getElementById('editor-foot');"
            "return {footer: f ? [...f.querySelectorAll('button')].map(b=>"
            "({label:b.textContent.trim(), act:b.getAttribute('data-act'), disabled:b.disabled}))"
            " : null,"
            " hint: (document.querySelector('[data-role=\"binding-confirm-hint\"]')"
            "||{textContent:''}).textContent.trim(),"
            " confirmed: (document.querySelector('#scr-editor')||{textContent:''})"
            ".textContent.match(/확정 \\d+\\/\\d+/),"
            " save_state: (document.getElementById('editorSaveState')||{textContent:''})"
            ".textContent.trim()};})()"
        )
        raise ScenarioFailure(
            f"{what}: 결속 검토가 편집기를 지목했는데 확정 동사가 무장하지 않습니다 — {state}."
            " 바꿀 것이 없는 검토를 닫을 길이 없다는 뜻이라 사용자가 여기서 막힙니다"
            " (#911 회귀 후보)"
        ) from exc
    verb = s.js(
        f"(function(){{const b=document.querySelector({json.dumps(save_sel)});"
        "return {label: b.textContent.trim(),"
        " confirm_only: b.getAttribute('data-confirm-binding') === '1',"
        " hint: (document.querySelector('[data-role=\"binding-confirm-hint\"]')"
        "||{textContent:''}).textContent.trim()};})()"
    )
    # 무변경 갈래로 섰는지까지 잰다 — 라벨만 보면 「변경 저장」과 구별되지 않고, 우리가 아무것도
    # 건드리지 않았으므로 여기서 참이어야 하는 것은 `confirm_only` 다.
    _expect(
        isinstance(verb, dict) and verb.get("confirm_only") is True,
        f"{what}: 무변경 확정 갈래가 서지 않았습니다 — {verb!r}",
    )
    s.click_sel(save_sel, what=f"{what} 연결 확정")
    s.wait(
        "document.querySelector('#scr-editor').textContent.includes('저장했습니다')",
        f"{what} 연결 확정 착지",
        timeout=30.0,
        requires=["#scr-editor"],
    )
    s.click_text("#editorContext", "문서 만들기로 돌아가기")
    s.wait(
        "document.querySelector('#scr-job.on') !== null",
        f"{what} 결속 복귀",
        timeout=30.0,
        requires=["#scr-job"],
    )
    return {"pending": len(pending), "verb": verb}


def _managed_reviews(ctx: "ScenarioContext", what: str, *, limit: int = 8) -> "list[str]":
    """관리 경로의 **검토 확인들**을 지나 「만들기」를 연다 — 지나온 단계 코드를 돌려준다.

    구간 템플릿의 첫 작업은 기본 티어보다 확인 왕복이 몇 걸음 더 있다(§3.5, PR #909): 결속·
    전달·실행 검토를 사람이 확정해야 생성이 열린다. 그 사슬을 대본이 **미리 적지 않는** 이유는
    순서와 구성이 제품 소유이기 때문이다(``PRIMARY_ACTION_CODES`` 우선순위) — 고정 대본을 박으면
    제품이 한 걸음을 더하거나 뺄 때 옳은 동작이 빨강이 된다. 그래서 매 바퀴 **제품이 지금 무엇을
    최우선으로 요구하는지**(``primary_action``)를 읽고 그 자리의 버튼을 누른다.

    ``NOT_REQUIRED`` 미리보기에서는 승인할 것이 아예 없다(``#jobManagedPreviewOpen`` 이 서지
    않는다) — 그 갈래를 승인으로 재면 없는 버튼을 기다리게 된다. 모르는 코드는 조용히 넘기지
    않고 관측을 통째로 실어 시끄럽게 죽는다.

    ``REVIEW_RECORD_DATA`` 도 그 「모르는 코드」다(#915). 종전 자산은 ``납품기한`` 이라는
    **이름**이 날짜 유형을 선언해 자유서식 값 2행이 이 단계에 걸렸고, 대본은 제품이 지목한
    행을 범위에서 빼며 지나갔다 — 커리큘럼에 없는 게이트를 심화 티어 사용자 전원이 만난다는
    사실이 그 우회 뒤에 있었다. 자산의 칸 이름을 ``납품조건``(text)으로 고쳐 게이트를
    없앴으므로 우회도 함께 지웠다: 이 코드가 다시 서면 그것은 지나갈 길이 아니라 **자산↔서식
    드리프트의 재발**이고, 여기서 시끄럽게 죽는 것이 맞다.
    """
    s = ctx.surface
    passed: "list[str]" = []
    for _ in range(limit):
        observation = _workbench(_snapshot(s))
        create = observation.get("create_action") or {}
        if create.get("enabled") is True:
            return passed
        code = str(observation.get("primary_action") or "")
        if code == "CREATE_DOCUMENTS":
            # 최종 단계인데 아직 안 열렸다 — 한 tick 늦은 것일 수 있으니 화면으로 기다린다.
            s.wait(
                "!document.getElementById('jobManagedCreate').disabled",
                f"{what} 만들기 열림",
                timeout=30.0,
                requires=["#jobManagedCreate"],
            )
            return passed
        passed.append(code)
        selector = _managed_review_control(code)
        if selector is not None:
            # 누르기 **전에** 그 자리의 꼴을 뜬다(#912 (c)) — 누른 뒤에 재면 이미 지나간
            # 화면을 재게 되고, 「지시했는데 누를 것이 없었다」가 관측에서 사라진다.
            ctx.observations.setdefault("blocker_affordance", []).append(
                {"code": code, "selector": selector, **_probe_affordance(s, code, selector)}
            )
        if code == "REVIEW_PREVIEW":
            _approve(ctx, what, managed=True)
            continue
        if code == "REVIEW_BINDING":
            # 무변경 확정 갈래가 섰다는 사실(#911)은 관측에 남긴다 — 이 사슬을 닫은 것이 무엇이
            # 었는지를 보고서가 말할 수 있어야 한다(첫 확정만 기록: 뒤 바퀴는 같은 사실이다).
            resolved = _resolve_bindings(ctx, what)
            ctx.observations.setdefault("binding_confirm", resolved["verb"])
            continue
        if selector is None:
            raise ScenarioFailure(
                f"{what}: 대본이 지나갈 수 없는 관리 경로 단계 {code!r}"
                " — 어포던스 정본이 이 자리의 활성 동사를 선언하지 않았거나"
                f" 대본 범위 밖입니다. 지나온 단계 {passed!r} ·"
                f" blockers {observation.get('blockers')!r} ·"
                f" create {create!r} ·"
                f" preview {observation.get('preview_requirement')!r} ·"
                f" execution {observation.get('execution_action')!r} ·"
                f" input_requirements {observation.get('input_requirements')!r} ·"
                f" record_validation {observation.get('record_validation')!r} ·"
                f" delivery {observation.get('delivery')!r}"
            )
        before = str(s.js(
            "(document.getElementById('jobManagedCreateReason')||{textContent:''}).textContent"
        ))
        s.click_sel(selector, what=f"{what} {code}")
        # 착지는 「사유가 바뀌었다」거나 「열렸다」 — 클릭 직후를 재면 아직 안 온 재렌더를
        # 통과로 읽고 같은 단계를 limit 까지 헛돈다.
        s.wait(
            "(function(){const b=document.getElementById('jobManagedCreate');"
            "if(b && !b.disabled)return true;"
            "const r=document.getElementById('jobManagedCreateReason');"
            f"return !!r && r.textContent !== {json.dumps(before, ensure_ascii=False)};}})()",
            f"{what} {code} 착지",
            timeout=60.0,
            requires=["#jobManagedCreate"],
        )
    raise ScenarioFailure(
        f"{what}: 검토 확인 {limit}바퀴에도 만들기가 열리지 않았습니다 — 지나온 단계 {passed!r}"
    )


def _managed_route(ctx: "ScenarioContext") -> bool:
    """이 실행이 managed materialization 갈래인가 — **화면에 선 것으로** 가른다.

    구간을 가진 durable Work 는 legacy staging 을 타지 않고 managed 파이프라인으로 간다
    (``screen_job._is_managed_hwpx_work``). 어느 쪽인지 추측하지 않고 제품이 세운 버튼을 보고,
    그 사실을 관측에 실어 증거로 남긴다 — 갈래를 조용히 삼키면 「어느 경로가 검사됐는가」를
    보고서가 말하지 못한다.
    """
    return bool(ctx.surface.js("!!document.getElementById('jobManagedCreate')"))


def _generate(ctx: "ScenarioContext", what: str) -> dict:
    """문서를 실제로 만들고 **무슨 일이 있었는지**를 돌려준다 — 갈래는 화면이 정한다.

    덮어쓰기 확인을 기대값으로 받지 않고 **관측해서 싣는다**. 같은 이름이 이미 있는가는
    갈래가 정하지("legacy 는 확인을 묻고 managed 는 기본 충돌 처리로 접미를 붙인다") 대본이
    정하는 것이 아니라서, 기대값을 박으면 옳은 제품 동작이 빨강이 된다. 대신 「어느 바퀴에서
    확인이 실제로 떴는가」를 돌려주므로, 그것이 계약인 자리(T8)는 부른 쪽이 단언한다.
    """
    s = ctx.surface
    route = "managed" if _managed_route(ctx) else "legacy"
    button = "#jobManagedCreate" if route == "managed" else "#jobGenBtn"
    s.wait(
        f"!document.querySelector('{button}').disabled",
        f"{what} 생성 열림({route})",
        timeout=30.0,
        requires=[button],
    )
    s.click_sel(button, what=f"{what} 문서 만들기({route})")
    # 확인 모달과 완료 태 중 **먼저 서는 것**을 기다린다. 확인을 무조건 기다리면 안 뜨는
    # 갈래에서 매달리고, 완료만 기다리면 확인이 뜬 갈래에서 영영 오지 않는 태를 기다린다.
    s.wait(
        "(function(){"
        "const m=document.getElementById('confirmModal');"
        "if(m && !m.classList.contains('hidden'))return true;"
        "return (document.getElementById('jobResult')||{dataset:{}}).dataset.state === 'completed';"
        "})()",
        f"{what} 덮어쓰기 확인 또는 생성 완료",
        timeout=90.0,
        requires=["#jobResult"],
    )
    overwrite = not s.js("document.getElementById('confirmModal').classList.contains('hidden')")
    if overwrite:
        _confirm(ctx, "덮어쓰고 생성", f"{what} 덮어쓰기")
        s.wait(
            "(document.getElementById('jobResult')||{dataset:{}}).dataset.state === 'completed'",
            f"{what} 덮어쓴 뒤 생성 완료 태",
            timeout=90.0,
            requires=["#jobResult"],
        )
    state = str(s.js("document.getElementById('jobResult').dataset.state"))
    # 결과 구획을 닫아 다음 바퀴의 실행 면을 되돌린다(닫지 않으면 다음 걸음이 지난 결과를 본다).
    if s.js("!!document.getElementById('jobResultClose')"):
        s.click_sel("#jobResultClose", what=f"{what} 결과 닫기")
        s.wait(
            "(document.getElementById('jobResult')||{dataset:{}}).dataset.state !== 'completed'",
            f"{what} 결과 닫힘",
            requires=["#jobResult"],
        )
    return {"state": state, "route": route, "overwrite_confirmed": overwrite}


def _visible_moment(s: Surface, what: str) -> str:
    """지금 떠 있는 순간 카드의 단계 — **가시성으로** 잰다.

    존재만 재면 안 되는 자리다(저장소가 아는 함정: selftest 프로브의 `click` 은 hidden 도
    지난다). 다만 ``offsetParent`` 는 쓰지 않는다 — 카드는 요소를 겨누지 않는 고정 자리라
    ``position: fixed`` 이고, 그러면 보이는 카드도 ``offsetParent`` 가 ``null`` 이라 이 축이
    「안 보인다」를 참으로 만든다(가시성을 재려다 가시성을 부정하는 검사가 된다).
    """
    s.wait(
        "(function(){const c=document.getElementById('tutorialMoment');"
        "if(!c)return false;const st=getComputedStyle(c);"
        "return c.getClientRects().length > 0 && st.display !== 'none'"
        " && st.visibility !== 'hidden' && parseFloat(st.opacity || '1') > 0;})()",
        f"{what} 순간 카드 가시",
        timeout=30.0,
        requires=["#tutorialMoment"],
    )
    return str(s.js("document.getElementById('tutorialMoment').dataset.milestone"))


def _tier_complete(s: Surface, tier: str) -> bool:
    return bool(s.js(
        "!!document.querySelector('#tutorialPanel"
        f" section.tut-tier[data-tier=\"{tier}\"][data-complete=\"1\"]')"
    ))


def _require_step(s: Surface, milestone: str, what: str) -> None:
    """체크리스트의 한 단계가 **체크된 것으로 보이는지** — 링1 판정의 표면 착지."""
    s.wait(
        "!!document.querySelector('#tutorialPanel"
        f" li.tut-step[data-milestone=\"{milestone}\"][data-achieved=\"1\"]')",
        f"{what}({milestone}) 체크",
        timeout=30.0,
        requires=["#tutorialPanel"],
    )


def _tutorial_phase(s: Surface) -> str:
    """지금 패널이 선 국면 — 진행 · 완주 · 초점(``data-phase``). 없으면 빈 문자열."""
    return str(s.js(
        "(document.getElementById('tutorialPanel')||{dataset:{}}).dataset.phase || ''"
    ))


def _await_complete_phase(s: Surface, what: str) -> dict:
    """완주 국면이 **실제로 섰는지** — 체크리스트가 사라진 자리에 완주 문안이 선다(§1 D5).

    이 함수가 있는 이유는 실측 하나다(#927). 고급 티어는 T15·T16 둘이라 **T16 이 체크되는
    바로 그 순간** 표준 완주가 성립하고, 패널은 같은 렌더에서 complete 국면으로 접혀
    체크리스트를 통째로 걷는다. 그래서 T16 의 착지를 ``li.tut-step`` 으로 기다리면 그 대기는
    영영 참이 되지 않는다 — CI 에서 30.1초 시한으로 나온 빨강이 그것이고, 제품은 옳았다.

    그러므로 이 단계의 착지는 **국면 전환**이 증언한다. 체크 자체는 지나간 과정을 다시 겨눈
    뒤(:func:`_focus_tier`) 본다 — 「보이지 않는다」와 「체크되지 않았다」를 가르는 것이
    이 두 걸음의 요점이다.

    셋을 함께 잰다: 국면 표기 · 완주 문안의 실존 · 체크리스트 **부재**. 앞의 둘만 재면 완주
    문안이 체크리스트 위에 겹쳐 선 화면도 같은 초록으로 지나간다.
    """
    s.wait(
        "(function(){const p=document.getElementById('tutorialPanel');"
        "return !!p && p.dataset.phase === 'complete'"
        " && !!document.getElementById('tutorialComplete')"
        " && !document.querySelector('#tutorialPanel li.tut-step');})()",
        f"{what} 완주 국면",
        timeout=30.0,
        requires=["#tutorialPanel"],
    )
    return {
        "phase": _tutorial_phase(s),
        "title": str(s.js(
            "document.querySelector('#tutorialComplete .tut-done-title').textContent"
        )).strip(),
    }


def _focus_tier(s: Surface, tier: str, what: str) -> str:
    """「다시 볼 과정」에서 한 과정을 **명시로 겨눈다** — 심화 진입의 유일한 어포던스(§1 D5).

    심화는 선택 과정이라 표준 완주가 그리로 이어 주지 않는다. 사용자가 그 과정을 골라야
    안내가 그쪽을 보고, 그때 패널은 그 과정 하나만 세운다(focus 국면). 대본이 그 길을 그대로
    걷는 것은 우회가 아니라 새 어포던스의 live 커버리지다 — 이 버튼이 죽으면 심화는 제품에서
    닿을 수 없는 곳이 되고, 그 사실은 여기서만 드러난다.
    """
    selector = f'#tutorialTierPicker button[data-tier={json.dumps(tier)}]'
    s.wait(
        f"!!document.querySelector({json.dumps(selector)})",
        f"{what} 과정 버튼",
        timeout=30.0,
        requires=["#tutorialTierPicker"],
    )
    s.click_sel(selector, what=f"{what} 과정 겨눔")
    # 겨눈 과정이 **실제로 그 과정인지**까지 본다 — 국면만 재면 남의 과정이 선 화면도 통과한다.
    s.wait(
        "(function(){const p=document.getElementById('tutorialPanel');"
        "return !!p && p.dataset.phase === 'focus'"
        f" && !!p.querySelector('section.tut-tier[data-tier={json.dumps(tier)}]')"
        " && !!document.getElementById('tutorialFocusClear');})()",
        f"{what} 초점 국면",
        timeout=30.0,
        requires=["#tutorialPanel"],
    )
    return _tutorial_phase(s)


def _clear_focus(s: Surface, what: str) -> dict:
    """초점을 놓고 완주 자리로 돌아온다 — 「전체 보기」가 그 해제 동선이다(§1 D5)."""
    s.click_sel("#tutorialFocusClear", what=f"{what} 초점 해제")
    return _await_complete_phase(s, what)


def _tutorial_snapshot(s: Surface) -> dict:
    value = s.bridge("window.pywebview.api.initial('tutorial')", "튜토리얼 스냅샷")
    if not isinstance(value, dict):
        raise ScenarioFailure(f"튜토리얼 스냅샷이 객체가 아닙니다: {type(value)!r}")
    return value


def _achieved(snapshot: dict) -> "list[str]":
    return [
        step["milestone"]
        for tier in snapshot.get("tiers", ())
        for step in tier.get("steps", ())
        if step.get("achieved")
    ]


def _example_rows(s: Surface) -> int:
    """편집기 라이브러리 밴드에 서 있는 **예제 자산** 행 수 — 이름으로 센다."""
    names = json.dumps(
        [name for name in (*HWPX_ASSETS, *TXT_ASSETS)], ensure_ascii=False
    )
    return int(s.js(
        "(function(){const names=" + names + ";"
        "return [...document.querySelectorAll("
        "'#scr-editor button[data-act=\"use-library\"]')]"
        ".filter(b=>names.some(n=>(b.getAttribute('data-path')||'').includes(n))).length;})()"
    ))


#: 「고정한 데이터」 목록에서 예제 등록만 세는 표현식 — 이름·문안을 함께 낸다.
_PINNED_PROBE = (
    "(function(){const stems=%s;"
    "const all=[...document.querySelectorAll('#dataPickerPinned button[data-act=\"use\"]')];"
    "return {matched: all.filter(b=>stems.includes(b.getAttribute('data-name'))).length,"
    " names: all.map(b=>b.getAttribute('data-name')),"
    " text: document.getElementById('dataPickerPinned').innerText.slice(0, 400)};})()"
) % json.dumps([name.removesuffix(".csv") for name in DATA_ASSETS], ensure_ascii=False)


def _pinned_examples(ctx: "ScenarioContext", expected: int) -> dict:
    """「고정한 데이터」의 예제 등록이 ``expected`` 건이 될 때까지 기다려 세고 닫는다.

    **기다리는 것이 계약이다.** 이 면은 열리는 순간 지난 스냅샷의 목록을 먼저 그리고
    (`pool` 모델은 부팅 때 이미 한 번 채워진다), 그 뒤에야 여는 길이 띄운
    ``dispatch('pool','refresh')`` 가 도착한다. 그래서 「읽는 중이 아니다」로 재면 **설치
    이전의 빈 목록**을 보고 0건이라 읽는다 — 실측으로 이 자리에서 두 번 넘어졌고, 그 빨강은
    「설치가 데이터를 고정하지 못했다」는 제품 문장으로 나왔다(디스크에는 있었다).

    수치만 돌려주지 않는 이유도 같다: 「0건」의 뜻이 여럿이라(비었는가·이름이 다른가·아직
    안 왔는가) 실패에 본 이름과 목록 문안을 함께 실어야 무엇을 고치라는 말인지 남는다.
    """
    s = ctx.surface
    s.click_sel("#jobBtnPickData", what="고정 데이터 확인")
    s.wait(
        "!document.getElementById('dataPickerModal').classList.contains('hidden')",
        "데이터 선택 면(고정 확인)",
        timeout=30.0,
        requires=["#dataPickerModal", "#dataPickerPinned"],
    )
    try:
        s.wait(
            f"{_PINNED_PROBE}.matched === {expected}",
            f"고정한 예제 데이터 {expected}건 도착",
            timeout=30.0,
            requires=["#dataPickerPinned"],
        )
    except StepTimeout as exc:
        observed = s.js(_PINNED_PROBE)
        raise ScenarioFailure(
            f"고정한 예제 데이터가 {expected}건이 되지 않았습니다 — {observed!r}"
        ) from exc
    observed = s.js(_PINNED_PROBE)
    if not isinstance(observed, dict):
        raise ScenarioFailure(f"고정 목록 관측이 객체가 아닙니다: {observed!r}")
    s.click_sel("#dataPickerClose", what="데이터 선택 면 닫기(고정 확인)")
    s.wait(
        "document.getElementById('dataPickerModal').classList.contains('hidden')",
        "데이터 선택 면 닫힘(고정 확인)",
        requires=["#dataPickerModal"],
    )
    return observed


def run_onboarding(ctx: ScenarioContext) -> dict:
    """온보딩 여정(#895) — 빈 홈에서 설치 → 4티어 완주 → 제거까지 실창으로 완주한다.

    §0 의 독자 2(제작자)가 하는 UX 검증 루프를 CI 가 대신 도는 자리다. 체크리스트가 넘어가지
    않는 지점 = 사용자가 막히는 지점이라, 이 대본이 재는 것은 화면 문안이 아니라 **단계가
    실제로 체크되는가**다: 각 T 는 링1 판정의 표면 착지(``li.tut-step[data-achieved]``)로
    확인하고, 수치는 디스크 census 로 되짚는다.
    """
    s = ctx.surface
    seen = ctx.observations
    facts: dict = {}

    # ---- O1 설치 전 홈 불가침(§1 D1 · #891 완료 기준 승계) --------------------
    s.wait(
        "document.querySelector('#jobPickInLibrary') !== null",
        "빈 홈 부팅 랜딩",
        requires=["#jobPickInLibrary"],
    )
    # 제품 command 를 관찰만 한다(가로채지 않는다). 실패했을 때 「눌렀는데 아무 일도 없다」가
    # 「보내지 않았다」인지 「보냈는데 거절됐다」인지를 가르는 유일한 증거다.
    s.install_dispatch_probe()
    before = ctx.home_census()
    intruders = sorted(
        path for path in before if not path.startswith(BOOT_RESIDUE_PREFIXES)
    )
    _expect(
        not intruders,
        "D1: 「예제로 시작하기」를 누르기 전에 홈에 부팅 잔재가 아닌 파일이 있습니다"
        f" — {intruders}",
    )
    asset_names = {*HWPX_ASSETS, *TXT_ASSETS, *DATA_ASSETS}
    planted = sorted(path for path in before if posixpath.basename(path) in asset_names)
    _expect(not planted, f"D1: 설치 전에 예제 자산이 이미 홈에 있습니다 — {planted}")
    # 튜토리얼은 **명시 시작**이다(§1 D3): 설치 전에는 표면 자체가 서지 않는다.
    _expect(
        not s.js("!!document.getElementById('tutorialPanel')"),
        "D3: 예제를 설치하기 전에 튜토리얼 패널이 이미 서 있습니다",
    )
    facts["home_before_install"] = sorted(before)

    # ---- O2 설치(T0) --------------------------------------------------------
    _goto_library(ctx, "설치")
    s.wait(
        "(function(){const b=document.querySelector('#scr-library [data-install-examples]');"
        "if(!b)return false;const st=getComputedStyle(b);"
        "return b.getClientRects().length > 0 && st.visibility !== 'hidden' && !b.disabled;})()",
        "빈 라이브러리의 예제 설치 제안",
        requires=["#scr-library", "#scr-library [data-install-examples]"],
    )
    s.click_sel("#scr-library [data-install-examples]", what="예제로 시작하기")
    install_body = _confirm(ctx, "설치", "예제 설치")
    _require_step(s, "T0", "예제 설치")
    # 순간 카드는 설치 직후 자리에서 잰다 — 큐의 맨 앞이고 자동 소멸까지 시간이 있다.
    facts["moment_visible"] = _visible_moment(s, "설치")
    after_install = ctx.home_census()
    missing = [rel for rel in INSTALLED_RELATIVE if rel not in after_install]
    _expect(not missing, f"T0: 설치가 홈에 앉히지 못한 자산이 있습니다 — {missing}")
    _open_editor(ctx, "설치 확인")
    installed_rows = _example_rows(s)
    _expect(
        installed_rows == len(HWPX_ASSETS) + len(TXT_ASSETS),
        f"T0: 라이브러리의 예제 템플릿이 {installed_rows}건입니다"
        f" (기대 {len(HWPX_ASSETS) + len(TXT_ASSETS)}건)",
    )
    grouped = bool(s.js(
        "document.getElementById('scr-editor').innerText.includes("
        f"{json.dumps(EXAMPLE_GROUP, ensure_ascii=False)})"
    ))
    _expect(grouped, f"T0: 설치한 템플릿이 '{EXAMPLE_GROUP}' 그룹으로 묶이지 않았습니다")
    _leave_editor(ctx, "설치 확인")
    pinned = _pinned_examples(ctx, len(DATA_ASSETS))
    facts["install"] = {
        "templates": installed_rows,
        "pinned": pinned["matched"],
        "grouped": grouped,
        "confirm_body": install_body,
        "installed_files": [rel for rel in INSTALLED_RELATIVE if rel in after_install],
    }

    # ---- O3 기본 티어(T1~T8) — L1 + L4a + L9(덮어쓰기) -----------------------
    _save_work(
        ctx,
        template="계약체결안내",
        name=ONBOARDING_JOBS["basic"],
        confirmed="확정 7/7",
        pattern="계약체결안내-{{공고번호}}",
    )
    for milestone, what in (("T1", "템플릿 고르기"), ("T2", "데이터 열 연결"), ("T3", "작업 저장")):
        _require_step(s, milestone, what)
    _mount_pinned(ctx, "계약목록")
    _require_step(s, "T4", "데이터 연결")
    _select_all(ctx, ONBOARDING_JOBS["basic"])
    _require_step(s, "T5", "작업과 행 선택")
    # 첫 실행은 결과 확인을 요구한다(§13-3) — 그 요구가 서 있는 것을 보고 나서 승인한다.
    s.wait(
        "document.getElementById('jobGenBtn').disabled"
        " && document.getElementById('jobGate').textContent.includes('생성 값 미리보기')",
        "기본 티어 첫 실행 검토 요구",
        requires=["#jobGenBtn", "#jobGate"],
    )
    _approve(ctx, "기본 첫 바퀴", managed=False)
    _require_step(s, "T6", "이름과 값 승인")
    first_run = _generate(ctx, "기본 첫 바퀴")
    _require_step(s, "T7", "문서 생성")
    first_docs = _results(ctx.home_census())
    _expect(
        len(first_docs) == ONBOARDING_ROWS,
        f"T7: 생성 문서가 {len(first_docs)}건입니다 (기대 {ONBOARDING_ROWS}건)",
    )

    # 한 바퀴 더 — ① 규칙축 승인은 **작업당 1회**라 다시 서지 않고(L4a) ② 같은 이름 파일은
    # 조용히 덮이지 않는다(L9). ①은 누르기 **전**에 재야 한다: 누른 뒤에 재면 이미 지나갔다.
    rearmed = bool(s.js(
        "(function(){const g=document.getElementById('jobGate');"
        "return !!g && g.textContent.includes('생성 값 미리보기');})()"
    ))
    _expect(
        not rearmed,
        "T8: 두 번째 바퀴에 승인이 다시 섰습니다 — 규칙축 승인은 작업당 1회입니다",
    )
    second_run = _generate(ctx, "기본 두 바퀴")
    _expect(
        second_run["overwrite_confirmed"],
        "T8: 같은 이름의 파일을 덮어쓰는데 확인을 묻지 않았습니다",
    )
    _require_step(s, "T8", "한 바퀴 더")
    _expect(_tier_complete(s, "basic"), "기본 티어가 졸업 상태로 서지 않았습니다")
    facts["basic"] = {
        "documents": len(first_docs),
        "first_run": first_run,
        "second_run": second_run,
        "approval_rearmed": rearmed,
    }

    # ---- O4 응용 티어(T9~T14) — L2 + L6 + L3 + L4b + L9(결핍 2종) ------------
    _save_work(
        ctx,
        template="구매추진안내",
        name=ONBOARDING_JOBS["applied_hwpx"],
        confirmed="확정 5/5",
        pattern="구매추진안내-{{공고번호}}",
    )
    # 데이터를 **다시 고르지 않는다** — 마운트는 작업이 아니라 화면이 든다(§18.2 · L2).
    _select_all(ctx, ONBOARDING_JOBS["applied_hwpx"])
    _approve(ctx, "작업 전환", managed=False)
    switch_run = _generate(ctx, "작업 전환")
    _require_step(s, "T9", "작업 전환")

    _save_work(
        ctx,
        template="계약안내_기안",
        name=ONBOARDING_JOBS["applied_txt"],
        confirmed="확정 6/6",
    )
    _require_step(s, "T10", "TXT 작업 저장")
    _select_all(ctx, ONBOARDING_JOBS["applied_txt"])
    s.wait(
        "document.getElementById('jobGenBtn').textContent.includes('검토·복사 시작')"
        " && !document.getElementById('jobGenBtn').disabled",
        "검토·복사 진입 버튼",
        requires=["#jobGenBtn"],
    )
    s.click_sel("#jobGenBtn", what="검토·복사 시작")
    s.wait(
        "document.querySelector('#scr-workbench.on') !== null"
        " && (document.getElementById('wbCard')||{textContent:''}).textContent"
        ".includes('계약 안내')",
        "작업대 카드 채움",
        timeout=30.0,
        requires=["#scr-workbench", "#wbCard"],
    )
    s.click_sel("#wbCopy", what="복사")
    s.wait(
        "(document.getElementById('wbCopied')||{textContent:''}).textContent"
        ".trim().indexOf('1 /') === 0",
        "복사 카운터",
        requires=["#wbCopied"],
    )
    copied = str(s.js("document.getElementById('wbCopied').textContent")).strip()
    _require_step(s, "T11", "검토와 복사")
    # 미복사 잔량이 있는 이탈은 가드가 확인을 요구한다 — 실 클릭으로 지난다.
    s.click_sel("#wbBack", what="작업대 출구")
    s.wait(
        "document.querySelector('#scr-job.on') !== null || !!window.__cap.btn(null,'나가기')",
        "작업대 이탈 가드",
    )
    s.js("window.__cap.clickBtn(null,'나가기'); true;")
    s.wait("document.querySelector('#scr-job.on') !== null", "작업대 이탈", requires=["#scr-job"])

    # T12 데이터 교체 — 앞 데이터의 선택을 새 행에 물려주지 않는다.
    _mount_pinned(ctx, "계약목록_2")
    swapped = _snapshot(s)
    _expect(
        swapped.get("selected_count") == 0,
        f"T12: 데이터 교체 뒤 선택이 0건에서 재시작하지 않았습니다 — {swapped.get('selected_count')!r}",
    )
    _require_step(s, "T12", "데이터 교체")

    # T13 빈 값 재승인 — 이번 실행의 빈 값 집합이 갈려 승인이 **다시 선다**(L4b).
    marker = MISSING_MARKER.format(field="납품조건")
    _select_all(ctx, ONBOARDING_JOBS["basic"])
    s.wait(
        "document.getElementById('jobGenBtn').disabled"
        " && document.getElementById('jobGate').textContent.includes('생성 값 미리보기')",
        "빈 값축 재승인 요구",
        requires=["#jobGenBtn", "#jobGate"],
    )
    _approve(ctx, "빈 값 재승인", managed=False, expect_text=marker)
    blank_run = _generate(ctx, "빈 값 생성")
    _require_step(s, "T13", "빈 값 포함 승인")

    # T14 저작측 결핍 — 열 자체가 없는 항목은 **저장할 때** 한 번 비움을 확정한다.
    empty_gate = _save_work(
        ctx,
        template="오류연습_보증금",
        name=ONBOARDING_JOBS["error"],
        confirmed="확정 4/4",
        empty_confirm=True,
    )
    _expect(empty_gate, "T14: 비움 확정 게이트가 서지 않았습니다")
    _require_step(s, "T14", "비움 확정")
    _expect(_tier_complete(s, "applied"), "응용 티어가 졸업 상태로 서지 않았습니다")
    facts["applied"] = {
        "switch_run": switch_run,
        "copied": copied,
        "selected_after_swap": swapped.get("selected_count"),
        "blank_marker": marker,
        "blank_run": blank_run,
        "empty_confirm_gate": empty_gate,
    }

    # ---- O5 고급·심화 티어(T15~T17) — L8 → L1 재진입 → L8b -------------------
    # 갈래 대조는 빈 값 없는 3행 위에서 한다 — 결핍이 섞이면 「무엇이 문서를 바꿨는가」가 흐려진다.
    _mount_pinned(ctx, "계약목록")

    _open_editor(ctx, "누름틀 변환")
    s.click_sel(
        '#scr-editor button[data-act="lib-more"][data-media="hwpx"][data-key="공고서_연습.hwpx"]',
        what="공고서_연습 항목 관리",
    )
    s.wait(
        "!!document.querySelector('.ctx-menu button[data-context-menu-action=\"act:compile\"]')",
        "누름틀 변환 메뉴 항목",
        requires=[".ctx-menu"],
    )
    s.click_sel(
        '.ctx-menu button[data-context-menu-action="act:compile"]', what="누름틀·구간 변환"
    )
    compile_body = _confirm(ctx, "제자리 변환", "누름틀 변환")
    _require_step(s, "T15", "누름틀 변환")
    _leave_editor(ctx, "누름틀 변환")

    _save_work(
        ctx,
        template="공고서_연습",
        name=ONBOARDING_JOBS["advanced"],
        confirmed="확정 5/5",
        pattern="공고서-{{공고번호}}",
    )
    _select_all(ctx, ONBOARDING_JOBS["advanced"])
    # 구간은 EXACTLY_ONE 이다 — 항목마다 갈래 하나를 골라야 생성이 열린다(§3.6).
    # 갓 저장한 작업은 **아직 bootstrap 전**이라 「포함할 내용」이 서지 않는다(durable id 미발급 —
    # 스냅샷 존은 그 상태를 `supported:true, initialized:false` 로 정직하게 낸다). 「템플릿 변경사항
    # 확인」이 그 bootstrap 동사다: 누르면 권위 id 가 발급되고 구간과 managed 실행면이 함께 선다.
    s.click_sel("#jobTplCheck", what="템플릿 확인(구간 bootstrap)")
    s.wait(
        "document.querySelectorAll('#jobContentSelectionZone .cs-slot').length === 1"
        " && !!document.getElementById('cs-opt-0-0')"
        " && !!document.getElementById('cs-opt-0-1')",
        "구간 1개·갈래 2",
        timeout=60.0,
        requires=["#jobContentSelectionZone"],
    )
    s.click_sel("#cs-opt-0-0", what="현장설명회 실시 갈래")
    s.wait("document.getElementById('cs-opt-0-0').checked", "첫 갈래 반영", requires=["#cs-opt-0-0"])
    managed = _managed_route(ctx)
    # 관리 경로는 승인 한 번이 아니라 **검토 확인들**이다(§3.5) — 무엇을 몇 걸음 요구하는지는
    # 제품이 정하므로 대본은 그 사슬을 따라간다. legacy 갈래면 종전대로 승인 한 번이다.
    before_compiled = _results(ctx.home_census())
    advanced_reviews = (
        _managed_reviews(ctx, "변환본 생성")
        if managed
        else [_approve(ctx, "변환본 생성", managed=False) and "REVIEW_PREVIEW"]
    )
    compiled_run = _generate(ctx, "변환본 생성")
    # T16 이 곧 표준 완주다(고급 = T15·T16) — 체크되는 순간 패널이 complete 국면으로 접히고
    # 체크리스트가 사라진다. 그래서 여기서 기다리는 것은 체크가 아니라 **국면 전환**이다.
    standard = _await_complete_phase(s, "표준 완주")
    # 그 체크를 눈으로 보려면 지나간 과정을 다시 겨눠야 한다 — 「다시 볼 과정」이 그 길이다.
    advanced_focus = _focus_tier(s, "advanced", "고급 되짚기")
    _require_step(s, "T16", "변환본으로 생성")
    _expect(_tier_complete(s, "advanced"), "고급 티어가 졸업 상태로 서지 않았습니다")
    # 초점 국면은 겨눈 과정 **하나만** 세운다 — 「다시 볼 과정」은 그 자리에 없다. 그래서 다른
    # 과정으로 옮기는 길은 초점을 놓고 완주 자리로 돌아가는 것 하나다(제품이 그렇게 섰다).
    refocus = _clear_focus(s, "고급 되짚기 해제")
    # 심화는 **선택 과정**이라 표준 완주가 그리로 이어 주지 않는다(§1 D5) — 명시로 겨눈다.
    deep_focus = _focus_tier(s, "deep", "심화 진입")
    before_deep = _results(ctx.home_census())
    # 심화 티어는 **동봉 3행 전부**로 선다(#915). 종전 자산은 `납품기한` 이라는 이름이
    # 날짜 유형을 선언해 자유서식 값 2행이 「먼저 데이터 문제를 확인하세요」에 걸렸고,
    # 대본은 제품이 지목한 행을 빼며 지나갔다 — 커리큘럼에 없는 게이트를 사용자 전원이
    # 만난다는 사실이 그 우회 뒤에 있었다. 자산의 칸 이름을 `납품조건`(text)으로 고쳐
    # 게이트를 없앴으므로, 이제 **몇 건이 나왔는지**가 그 수리의 증거다.
    compiled_docs = len(before_deep) - len(before_compiled)
    _expect(
        compiled_docs == ONBOARDING_ROWS,
        f"T16: 변환본 생성이 {compiled_docs}건입니다 (기대 {ONBOARDING_ROWS}건)"
        " — 데이터 게이트가 행을 떨어뜨렸을 수 있습니다",
    )

    # T17 구성 바꿔 생성 — 「절을 뺀다」가 곧 「생략」 갈래를 고르는 것이다(v1 EXACTLY_ONE).
    s.click_sel("#cs-opt-0-1", what="현장설명회 생략 갈래")
    s.wait(
        "document.getElementById('cs-opt-0-1').checked"
        " && !document.getElementById('cs-opt-0-0').checked",
        "갈래 전환 반영",
        timeout=30.0,
        requires=["#cs-opt-0-1", "#cs-opt-0-0"],
    )
    # 구성 변경은 규칙 변경이라 확인이 **다시 선다**(L4a 의 두 번째 대면) — 관리 경로에서는
    # 그것이 실행 검토의 재확정으로 나타난다(구성이 갈리면 Plan 이 stale 이 된다).
    #
    # 재무장을 **기다린 뒤** 사슬을 걷는다. 클릭 직후를 재면 아직 도착하지 않은 재계산을
    # 「아무것도 안 섰다」로 읽어, 늦은 push 와 계약 위반이 같은 빨강이 된다.
    #
    # ## 실측이 뒤집은 기대 (#895 4차)
    #
    # 관리 갈래에서는 **아무 확인도 다시 서지 않는다**: 60초를 기다려 봐도 `primary_action` 은
    # `CREATE_DOCUMENTS`, `blockers` 는 빈 배열, 만들기는 열린 채였다(`preview_requirement` 가
    # 처음부터 `NOT_REQUIRED` 다 — 이 작업에는 애초에 승인이 요구된 적이 없다). 그런데 §3.6 의
    # T17 순간 카드는 "갈래를 바꾸자 … 승인이 다시 섰습니다" 라고 말한다.
    #
    # 그래서 여기서 **단언하지 않는다**. 「다시 섰다」를 단언하면 지금 제품이 빨강이고,
    # 「안 선다」를 단언하면 지금 동작을 정본으로 못박아 정반대 판정을 막는다 — 어느 쪽도 이
    # 대본이 내릴 판정이 아니다(문서와 제품 중 무엇을 고칠지는 §3.6 재판정 소관). 관측된
    # 사실만 실어 보고서가 말하게 하고, T17 의 **단단한 증거는 산출물 차이**가 진다(아래).
    #
    # 그래서 프로브는 **짧다**. 단언하지 않는 관측에 60초를 태우면 관리 갈래를 지나는 모든
    # 실행이 매번 그만큼을 버린다 — 게이트 예산은 매달림을 유한 시간에 빨강으로 만들라고
    # 있는 것이지 확정된 관측을 다시 확인하라고 있는 것이 아니다. 여기서 흡수해야 할 것은
    # **늦은 push** 하나뿐이고 그건 초 단위다(재무장이 실제로 서는 갈래로 제품이 바뀌면
    # 그때는 이 짧은 대기가 그대로 참을 낸다).
    reconfirmed = False
    if managed:
        try:
            s.wait(
                "(function(){const b=document.getElementById('jobManagedCreate');"
                "return !!b && b.disabled;})()",
                "T17 구성 변경 뒤 확인 재무장",
                timeout=8.0,
                requires=["#jobManagedCreate"],
            )
            reconfirmed = True
        except StepTimeout:
            reconfirmed = False
    deep_reviews = (
        _managed_reviews(ctx, "구성 바꿔 생성")
        if managed
        else [_approve(ctx, "구성 바꿔 생성", managed=False) and "REVIEW_PREVIEW"]
    )
    seen["composition_reconfirmed"] = {
        "rearmed": reconfirmed,
        "reviews": list(deep_reviews),
        "managed": managed,
    }
    composed_run = _generate(ctx, "구성 바꿔 생성")
    _require_step(s, "T17", "구성 바꿔 생성")
    after_deep = _results(ctx.home_census())
    fresh = sorted(set(after_deep.values()) - set(before_deep.values()))
    _expect(
        fresh,
        "T17: 갈래를 바꿔 다시 만들었는데 앞선 산출과 내용이 같은 문서만 있습니다"
        " — 절이 빠지지 않았습니다",
    )
    _expect(_tier_complete(s, "deep"), "심화 티어가 졸업 상태로 서지 않았습니다")
    # 초점을 놓으면 완주 자리로 돌아온다 — 이번엔 심화까지 걸었으므로 표준 완주와 **다른 말**을
    # 해야 한다. 그 갈림은 링1 이 이미 냈고 여기서는 그것이 화면에 섰는지만 관측한다.
    all_done = _clear_focus(s, "전체 완주")
    facts["lifecycle"] = {
        "standard_phase": standard["phase"],
        "standard_title": standard["title"],
        "advanced_focus_phase": advanced_focus,
        "refocus_phase": refocus["phase"],
        # 심화에 어떻게 들어갔는가 — 자동 이월이 아니라 「다시 볼 과정」 선택이다(§1 D5).
        "deep_entry": "focus_picker",
        "deep_focus_phase": deep_focus,
        "final_phase": all_done["phase"],
        "final_title": all_done["title"],
    }
    facts["advanced"] = {
        "compile_confirm_body": compile_body,
        "compiled_run": compiled_run,
        "compiled_documents": compiled_docs,
        "documents_before_change": len(before_deep),
        "reviews": advanced_reviews,
    }
    facts["deep"] = {
        "route": composed_run["route"],
        "composed_run": composed_run,
        "documents_after_change": len(after_deep),
        "fresh_digests": len(fresh),
        "reviews": deep_reviews,
    }

    # ---- O6 전 티어 완주 --------------------------------------------------
    tutorial = _tutorial_snapshot(s)
    achieved = _achieved(tutorial)
    facts["achieved"] = achieved
    facts["step_count"] = tutorial.get("step_count")
    facts["all_complete"] = tutorial.get("all_complete")
    facts["tiers"] = {
        str(tier.get("tier")): bool(tier.get("complete"))
        for tier in tutorial.get("tiers", ())
    }
    expected_steps = [str(step.milestone) for step in TUTORIAL_STEPS]
    _expect(
        achieved == expected_steps,
        f"전 단계 완주가 아닙니다 — 달성 {achieved} (기대 {expected_steps})",
    )
    _expect(tutorial.get("all_complete") is True, "튜토리얼 스냅샷이 전체 완주를 말하지 않습니다")

    # ---- O7 제거(§1 D4) — manifest 기재분만 걷고 잔재는 정직하게 드러난다 ----
    _open_editor(ctx, "예제 제거")
    s.wait(
        "!!document.querySelector('#scr-editor button[data-act=\"remove-examples\"]')",
        "예제 걷어내기 어포던스",
        requires=["#scr-editor"],
    )
    s.click_sel(
        '#scr-editor button[data-act="remove-examples"]', what="예제 걷어내기"
    )
    remove_body = _confirm(ctx, "걷어내기", "예제 제거")
    _expect(
        "되돌리기는 다시 설치하기입니다" in remove_body,
        f"제거 확인이 되돌리는 법을 말하지 않았습니다 — {remove_body!r}",
    )
    s.wait(
        "!document.querySelector('#scr-editor button[data-act=\"remove-examples\"]')",
        "제거 뒤 걷어내기 어포던스 소멸",
        timeout=30.0,
        requires=["#scr-editor"],
    )
    left_rows = _example_rows(s)
    _expect(left_rows == 0, f"제거 뒤에도 예제 템플릿이 {left_rows}건 남았습니다")
    entry_label = str(s.js(
        "document.querySelector('#scr-editor [data-act=\"install-examples\"]').textContent"
    )).strip()
    _expect(
        entry_label == "예제로 시작하기…",
        f"제거 뒤 설치 진입점 라벨이 되돌아오지 않았습니다 — {entry_label!r}",
    )
    _leave_editor(ctx, "예제 제거")
    left_pins = _pinned_examples(ctx, 0)
    removed_census = ctx.home_census()
    left_files = [rel for rel in INSTALLED_RELATIVE if rel in removed_census]
    _expect(not left_files, f"제거 뒤에도 예제 자산 파일이 남았습니다 — {left_files}")

    # 실습으로 만든 작업들은 남는다 — 그 템플릿이 사라진 사실을 라이브러리가 **시끄럽게** 말한다.
    _goto_library(ctx, "제거 뒤 정직성 경보")
    s.wait(
        "[...document.querySelectorAll('#scr-library .note.warnbox')]"
        ".some(n=>n.textContent.includes('템플릿이 연결되지 않은 작업'))",
        "끊긴 작업 경보",
        timeout=30.0,
        requires=["#scr-library"],
    )
    alarm = str(s.js(
        "([...document.querySelectorAll('#scr-library .note.warnbox')]"
        ".find(n=>n.textContent.includes('템플릿이 연결되지 않은 작업'))||{}).textContent || ''"
    )).strip()
    broken = int("".join(ch for ch in alarm.split("작업")[1] if ch.isdigit()) or 0)
    _expect(
        broken >= 1,
        f"제거 뒤 끊긴 작업 수를 경보가 말하지 않았습니다 — {alarm!r}",
    )
    facts["removal"] = {
        "confirm_body": remove_body,
        "templates_left": left_rows,
        "pinned_left": left_pins["matched"],
        "files_left": left_files,
        "entry_label": entry_label,
        "missing_template_jobs": broken,
        "alarm": alarm,
    }

    # 관리 검토 사슬을 지나며 뜬 어포던스 관측(#912 (c)). 대본은 뜨기만 하고 판정은
    # `report._judge_onboarding` 이 진다 — 관측만 하고 아무도 안 보면 계약이 아니다.
    facts["affordance"] = seen.pop("blocker_affordance", [])

    seen["onboarding"] = facts
    return seen
