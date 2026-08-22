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
from collections.abc import Callable
from dataclasses import dataclass, field

from hwpxfiller.webapp.app import _DISPATCH_REJECTION_KEY

from .surface import ScenarioFailure, Surface

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
    if failure:
        s.wait(
            "document.getElementById('dataPickerNote').textContent.trim().length > 0",
            "실패한 데이터 전환 문안",
            requires=["#dataPickerNote"],
        )
    else:
        s.wait(
            "!!document.querySelector('#dataPickerCurrent .tplcard-name')",
            "데이터 전환 착지",
            timeout=25.0,
            requires=["#dataPickerCurrent"],
        )
    s.click_sel("#dataPickerClose", what="데이터 선택 면 닫기")
    s.wait(
        "document.getElementById('dataPickerModal').classList.contains('hidden')",
        "데이터 선택 면 닫힘",
        requires=["#dataPickerModal"],
    )


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
    s.wait(
        "!!document.querySelector('.cs-status-stale')"
        " && document.querySelectorAll('#jobContentSelectionZone .cs-slot').length === 2"
        " && !!document.querySelector('#jobContentSelectionZone .cs-detached')",
        "stale notice와 skipped successor hydrate",
        timeout=30.0,
        requires=["#jobContentSelectionZone"],
    )
    successor = _snapshot(s)
    successor_view = _current_view(successor)
    successor_projection = successor_view["projection"]
    changes = successor_projection.get("reconciliation_changes") or {}
    _expect(changes.get("preserved_selection_refs"), "H4: preserved selection이 없습니다")
    _expect(successor_projection.get("detached_selections"), "H4: detached selection이 없습니다")
    _expect(
        any(item.get("kind") == "SELECTED_OPTION_REMOVED" for item in successor_projection.get("blocking_items", ())),
        "H4: broken selection이 없습니다",
    )
    stale_trace = s.take_dispatch_trace()
    stale_commands = [item for item in stale_trace if item.get("action") == "select_slot_option"]
    _expect(stale_commands, "H5: stale command trace가 없습니다")

    # Repair the broken option and its exact Binding target, then return through the real entry seam.
    s.click_sel("#cs-opt-1-0", what="깨진 선택 복구")
    s.wait("document.getElementById('cs-opt-1-0').checked", "깨진 선택 복구 반영", requires=["#cs-opt-1-0"])
    exact_target = "binding/추가확인"
    exact_selector = f'#jobInputRequirements button[data-exact-target="{exact_target}"]'
    s.wait(f"!!document.querySelector({json.dumps(exact_selector)})", "신규 Active Field exact Binding", requires=["#jobInputRequirements"])
    s.click_sel(exact_selector, what="신규 Binding 수정")
    row = '#editor-body table.map tr[data-field="추가확인"]'
    source_select = row + ' select[data-act="row-source"]'
    s.wait(
        f"document.querySelector('#scr-editor.on') !== null && !!document.querySelector({json.dumps(source_select)})",
        "Binding editor exact row",
        requires=["#scr-editor", row],
    )
    focus_on_entry = s.js("document.activeElement === document.querySelector(" + json.dumps(source_select) + ")")
    _expect(focus_on_entry, "H4: Binding deep-link가 exact source select에 focus하지 않았습니다")
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
    s.click_text("#scr-editor", "작업 저장")
    s.wait("document.querySelector('#scr-editor').textContent.includes('저장했습니다')", "Binding 저장", timeout=30.0, requires=["#scr-editor"])
    s.click_text("#editorContext", "문서 만들기로 돌아가기")
    s.wait("document.querySelector('#scr-job.on') !== null", "Binding ReturnContext", timeout=30.0, requires=["#scr-job"])
    binding_after = _workbench(_snapshot(s))
    repaired = next(item for item in binding_after.get("input_requirements", ()) if item.get("field_id") == "추가확인")
    _expect(repaired.get("action_required") is False, "H4: Binding 저장 뒤 current recompute가 갱신되지 않았습니다")

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
    _expect(
        "복원할 수 없습니다" in _rejection_message(old_recovery),
        "H7: old record recovery target이 수락됐습니다",
    )

    # Exact delivery + OPTIONAL/REQUIRED semantic preview. The harness collision file predates the no-mutation bracket.
    output_dir = ctx.prepare_output()
    ctx.queue_folder_answer(output_dir)
    s.click_sel("#jobManagedPickFolder", what="managed output folder 선택")
    s.wait("document.querySelectorAll('#jobPlannedDocuments li').length > 0", "exact delivery 계획", timeout=30.0, requires=["#jobPlannedDocuments"])
    optional = _workbench(_snapshot(s))
    _expect(optional["preview_requirement"]["kind"] == "OPTIONAL", "H5: OPTIONAL preview가 아닙니다")
    optional_token = optional["semantic_preview"]["preview_token"]
    relative_path = optional["delivery"]["planned_documents"][0]["relative_path"]
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
    required = _workbench(_snapshot(s))
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
    s.wait("getComputedStyle(document.getElementById('previewApprove')).display === 'none'", "current preview 승인 착지", requires=["#previewApprove"])
    s.click_sel("#previewClose", what="managed preview 닫기")
    s.wait("document.getElementById('previewSheet').classList.contains('hidden')", "managed preview 닫힘", requires=["#previewSheet"])
    s.wait(
        "document.getElementById('jobManagedCreate').disabled"
        " && document.getElementById('jobManagedCreateReason').textContent.includes('현재 환경에서는 문서를 만들 수 없습니다')",
        "S6 unavailable disabled create",
        requires=["#jobManagedCreate", "#jobManagedCreateReason"],
    )
    final_managed = _workbench(_snapshot(s))
    _expect(ctx.output_manifest() == baseline_manifest, "H6: managed path가 filesystem을 변경했습니다")

    # V4 data transition: cancel/failure are atomic, compatible keeps A, incompatible releases without auto-select.
    before_cancel = _snapshot(s)
    s.click_sel("#jobBtnPickData", what="DataTarget cancel 대조")
    s.wait("!document.getElementById('dataPickerModal').classList.contains('hidden')", "DataTarget cancel 면")
    s.click_sel("#dataPickerClose", what="DataTarget cancel")
    after_cancel = _snapshot(s)
    _expect(after_cancel.get("job_name") == before_cancel.get("job_name"), "H7: cancel이 active Work를 바꿨습니다")
    _mount_data(ctx, ctx.stage_data("missing"), failure=True)
    after_failure = _snapshot(s)
    _expect(after_failure.get("job_name") == "발주요청서", "H7: failed transition이 committed Work를 바꿨습니다")
    _mount_data(ctx, ctx.stage_data("release"))
    s.wait("document.getElementById('jobActionName').textContent.trim() === ''", "incompatible DataTarget RELEASE", timeout=30.0, requires=["#jobActionName"])
    _mount_data(ctx, ctx.stage_data("clean"))
    s.wait("document.getElementById('jobActionName').textContent.trim() === ''", "compatible reload 뒤 auto Work 0", requires=["#jobActionName"])
    _select_work(s, "발주요청서")

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
        "H4": {"reconciliation": changes, "binding_target": exact_target, "binding_state": repaired.get("binding_state")},
        "H5": {"context_copy": context_text, "record_focus": record_focus, "optional": optional["preview_requirement"], "required": required["preview_requirement"], "runtime_reason": final_managed["create_action"].get("disabled_reason")},
        "H6": {"preview_token": current_token, "filesystem_before": baseline_manifest, "filesystem_after": ctx.output_manifest()},
        "H7": {"stale_trace": stale_commands, "old_record_rejected": True, "old_preview_rejected": True, "data_transition": "KEEP/RELEASE/FAILURE_ATOMIC", "work_race": "B_WON"},
    }
    return seen


def run_restart(ctx: ScenarioContext) -> dict:
    """Second actual process: durable intent recomputes; session-only values stay absent."""
    s = ctx.surface
    before_files = ctx.output_manifest()
    initial = _snapshot(s)
    _expect(initial.get("has_data") is False and initial.get("has_job") is False, "H7: restart가 DataTarget/active Work를 복원했습니다")
    initial_wb = initial.get("workbench_observation") or {}
    _expect(initial_wb.get("run_delivery_intent") is None, "H7: restart가 delivery intent를 복원했습니다")
    _mount_data(ctx, ctx.stage_data("clean"))
    s.wait("document.getElementById('jobActionName').textContent.trim() === ''", "restart data reload 뒤 active Work 0", requires=["#jobActionName"])
    _select_work(s, "발주요청서")
    current = _snapshot(s)
    view = _current_view(current)
    selected = {
        slot["slot_id"]: [option["option_id"] for option in slot["options"] if option["effective"]]
        for slot in view["projection"]["slots"]
    }
    wb = _workbench(current)
    binding = next(item for item in wb.get("input_requirements", ()) if item.get("field_id") == "추가확인")
    _expect(binding.get("action_required") is False, "H7: durable Binding이 restart 뒤 복원되지 않았습니다")
    _expect(wb.get("run_delivery_intent") is None and wb.get("semantic_preview") is None, "H7: session delivery/preview가 거짓 복원됐습니다")
    after_files = ctx.output_manifest()
    _expect(after_files == before_files, "H7: restart observation이 filesystem을 변경했습니다")
    return {
        "sx05_restart": {
            "durable": {"job": current.get("job_name"), "selections": selected, "binding": binding},
            "session_absent": {"data_before_reload": True, "active_work_before_reselect": True, "delivery": True, "preview": True},
            "filesystem_before": before_files,
            "filesystem_after": after_files,
        }
    }
