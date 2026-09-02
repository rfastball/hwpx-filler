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

from hwpxfiller.application.document_creation_vocabulary import (
    DEFAULT_COLLISION_POLICY,
)
from hwpxfiller.webapp.app import _DISPATCH_REJECTION_KEY

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
    "session-panel",
    "range-editor",
    "preflight-check",
    "generated",
    "workbench-review",
    "workbench-copied",
    "workbench-empty-value",
)

#: 101 이 만드는 작업 이름 — 트랙 A(HWPX) · 트랙 B(TXT) · 오류 연습.
JOB_NAMES: "tuple[str, ...]" = ("발주요청서", "발주요청 기안", "오류연습")

#: 트랙 A 가 만들어야 하는 문서 수(CSV 3행).
EXPECTED_HWPX = 3


def _set_folder_in_settings(
    s: Surface,
    ctx: "ScenarioContext",
    directory: str,
    *,
    what: str,
    kind: str,
    pick: str,
    field: str,
    extra: "list[tuple[str, str, str]] | None" = None,
) -> None:
    """설정 모달에서 폴더 하나를 지정하고 **되읽는다** — 저장 폴더·서식 폴더 공용 몸통.

    두 행은 형상이 같다(⚙ → 모달 → 「찾아보기…」 → 경로 칸 되읽기 → 닫기). 사본으로 두면
    한쪽에만 붙는 걸음이 생기고, 그 어긋남은 실패했을 때만 드러난다. 다른 것은 좌표와
    문안뿐이라 인자로 받는다.

    모달은 **닫고 나온다**: 열린 채 두면 뒤 걸음의 클릭을 가린다. 되읽기까지가 이 걸음이다 —
    피커 응답이 Python 에 닿아 도출이 다시 서고 그 값이 경로 칸으로 돌아오는 것을 보고
    나서야 다음으로 간다(무착지 클릭 금지).

    ``extra`` 는 그 행에만 있는 추가 되읽기다: ``(표현식, 걸음 이름, 필요 좌표)``.
    """
    s.click_sel("#settingsOpen", what=f"설정 열기({what})")
    s.wait(
        "!document.getElementById('settingsModal').classList.contains('hidden')",
        f"설정 모달 열림({what})",
        requires=["#settingsModal"],
    )
    ctx.queue_folder_answer(directory)
    s.click_sel(pick, what=what)
    s.wait(
        f"(document.getElementById('{field.lstrip('#')}')||{{}}).value === "
        + json.dumps(directory, ensure_ascii=False),
        f"설정 모달이 지정한 {kind}를 되읽음({what})",
        requires=[field],
    )
    for expression, step, coordinate in extra or []:
        s.wait(expression, f"{step}({what})", requires=[coordinate])
    s.click_sel("#settingsClose", what=f"설정 닫기({what})")
    s.wait(
        "document.getElementById('settingsModal').classList.contains('hidden')",
        f"설정 모달 닫힘({what})",
        requires=["#settingsModal"],
    )


def _set_output_folder(
    s: Surface, ctx: "ScenarioContext", directory: str, *, what: str
) -> None:
    """저장 폴더를 지정한다 — 전역화 뒤 그 동사의 자리는 **설정 모달 하나**다.

    종전 대본은 작업 화면의 `#jobManagedPickFolder` 를 눌렀다. 저장 폴더가 작업 속성이 아니라
    앱 설정이 되면서 그 단추가 사라졌고, 지금 길은 토바 ⚙ → 설정 모달 → 「찾아보기…」다.
    """
    _set_folder_in_settings(
        s, ctx, directory, what=what, kind="저장 폴더",
        pick="#settingsPickFolder", field="#settingsOutDir",
    )


def _set_templates_root(
    s: Surface, ctx: "ScenarioContext", directory: str, *, what: str
) -> None:
    """서식 폴더를 지정한다(U6-A #975) — 저장 폴더 왕복과 **같은 몸통**의 한 걸음.

    겨누는 값은 **지금 쓰이는 그 폴더**다: 이 걸음이 재는 것은 「피커 응답이 Python 에 닿아
    설정에 앉고 그 도출이 설정 면의 경로 칸으로 돌아오는가」이고, 다른 폴더로 옮기면 뒤
    걸음의 템플릿 풀이 통째로 비어 그 뒤 대본이 전부 무의미해진다.

    출처 승격까지 함께 본다 — 같은 폴더를 겨눴어도 「기본 폴더」에서 「설정한 폴더」로
    바뀌는 것이 이 왕복이 실제로 영속에 닿았다는 증거다(경로만 보면 무변화와 구분되지 않는다).
    """
    _set_folder_in_settings(
        s, ctx, directory, what=what, kind="서식 폴더",
        pick="#settingsPickTplFolder", field="#settingsTplDir",
        extra=[(
            "(document.getElementById('settingsTplDirSource')||{}).textContent"
            " === '설정한 폴더'",
            "서식 폴더 출처가 「설정한 폴더」로 승격",
            "#settingsTplDirSource",
        )],
    )


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
    #: 서식 폴더(U6-A #975) — 이 홈의 ``templates``. 재지정 왕복이 겨누는 **그 폴더**다.
    templates_root: str
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
    # 1단계는 「고르기」다(U6-B #976): 좌 템플릿 풀 · 중앙 연결 카드 · 우 데이터 풀.
    s.wait(
        "document.querySelector('#scr-editor.on') !== null"
        " && document.querySelectorAll('#editorTplList .pitem').length > 0",
        "편집기 화면·고르기 존",
        requires=["#scr-editor", "#editorPairZone"],
    )
    # 발주요청서 항목 — data-path 로 정확 겨눔(클릭이 1차 경로, 끌어 놓기는 가속기).
    s.click_sel(
        '#editorTplList .pitem[data-path*="발주요청서"]',
        what="발주요청서 템플릿 채택",
    )
    s.wait(
        "document.querySelector('#scr-editor').textContent.includes('공고번호')",
        "템플릿 선택·필드 스키마",
        requires=["#scr-editor"],
    )

    # ---- S3 같은 단계의 오른쪽: 데이터 연결 → 「연결 확인」으로 --------------
    # 데이터 고르기가 2단계 머리에서 1단계 우 열로 옮겨 왔다(U6 §2.2) — 「다음 ▶」 앞이다.
    ctx.queue_file_answer(ctx.csv_path)
    s.click_sel("#editorPoolBrowse", what="파일 찾아보기")
    s.wait(
        "document.querySelector('#editorLinkCard').textContent.includes('⟷')"
        " && document.querySelector('#editorLinkCta').disabled === false",
        "연결 카드·전진 게이트 개방",
        requires=["#editorLinkCard", "#editorLinkCta"],
    )
    # 텍스트가 **있다**는 것과 **보인다**는 것은 다르다: 연결 카드는 두 열 사이라 기본
    # 스크롤에서 폴드 밖일 수 있고, 위 조건은 그 상태에서도 참이다. 겨눠 스크롤한다.
    s.scroll_to("#editorPairZone")
    ctx.shoot("template-pick")

    s.click_text("#scr-editor", "다음 ▶")
    # 라벨에 수치가 들어 있어 문안으로 겨누지 않는다 — 좌표(`data-act`)가 계약이다.
    s.wait(
        "!!document.querySelector('#scr-editor [data-act=\"confirm-suggested\"]')"
        " && document.querySelector('#scr-editor').textContent.includes('해양수산부')",
        "「연결 확인」 단계·매핑표 미리보기",
        requires=["#scr-editor"],
    )
    s.click_sel('#scr-editor [data-act="confirm-suggested"]', what="제안 일괄 확인")
    # 「확정 6/6」 게이트 줄은 머리 pill 로 접혔다 — 남은 행이 0 이면 전 행 확인이다.
    # 배지 전건을 함께 되읽어 pill 만 초록인 자리를 막는다(수치와 행이 갈리지 않는다).
    s.wait(
        "document.querySelector('#scr-editor').textContent.includes('확인 필요 0')"
        " && [...document.querySelectorAll('#scr-editor [data-act=\"row-confirm\"]')]"
        ".every((b) => b.textContent.trim() === '확인')",
        "전 행 확인",
        requires=["#scr-editor"],
    )
    # 머리 pill 줄이 폴드 아래로 잘리지 않게 겨눠 스크롤.
    s.scroll_to("#scr-editor .bindbar")
    ctx.shoot("mapping-confirm")

    # ---- S4 「이름·저장」 단계: 이름·파일 이름·저장 폴더 → 저장 --------------
    # 3단계가 묻는 것은 셋이다(U6-D #978): 작업 이름(이제 이 폼에 산다 — 머리의 인라인
    # 입력이 여기로 왔다) · 문서 파일 이름 · 저장 폴더(읽기 전용 재진술).
    s.click_text("#scr-editor", "다음 ▶")
    s.wait(
        "!!document.getElementById('editorName')"
        " && !!document.querySelector('#scr-editor input[data-act=\"pattern\"]')",
        "이름·저장 단계",
        requires=["#editorName", '#scr-editor input[data-act="pattern"]'],
    )
    # 이름은 이미 도출돼 있다 — 여기서 덮어쓰는 것이 곧 「고쳐도 된다」의 실주행이다.
    s.wait(
        "document.getElementById('editorName').value.length > 0"
        " && !!document.getElementById('editorNameHint')",
        "이름 기본값·힌트",
        requires=["#editorName"],
    )
    s.set_value("#editorName", "발주요청서")
    # 연번 예시는 **패턴에 seq 토큰이 있을 때만** 선다(U6-D #978). 그래서 한 값만 재면
    # 규칙이 검사되지 않는다 — 있는 자리에서 서는 것과 없는 자리에서 **안 서는** 것을
    # 두 값으로 각각 세운다(모션 층의 `prefers-reduced-motion` 대조와 같은 규율).
    #
    # ① 양성 — seq 토큰이 있으면 첫 이름 + 달라지는 부분이 잇는다.
    s.set_value(
        '#scr-editor input[data-act="pattern"]', "발주요청서-{{공고번호}}-{{seq:001}}"
    )
    s.wait(
        "document.getElementById('editorPatternPreview').textContent"
        ".includes('발주요청서-2026-001-001.hwpx · 002 · 003')",
        "파일명 라이브 예시 — 연번 양성",
        requires=["#editorPatternPreview"],
    )
    seen["seq_example_positive"] = s.js(
        "document.getElementById('editorPatternPreview').textContent.trim()"
    )
    # ② 음성 — seq 토큰을 걷으면 첫 이름 하나만 남는다. 없는 연번을 그리면 실제로는 이름
    #    셋이 충돌하는 자리를 정상으로 보인다. 이 패턴이 이 작업이 실제로 저장할 값이다.
    s.set_value('#scr-editor input[data-act="pattern"]', "발주요청서-{{공고번호}}")
    s.wait(
        "document.getElementById('editorPatternPreview').textContent"
        ".includes('발주요청서-2026-001')"
        " && !document.getElementById('editorPatternPreview').textContent"
        ".includes('· 002')",
        "파일명 라이브 예시 — 연번 음성",
        requires=["#editorPatternPreview"],
    )
    seen["seq_example_negative"] = s.js(
        "document.getElementById('editorPatternPreview').textContent.trim()"
    )
    # 저장 폴더는 읽기 전용 재진술이고 바꾸러 갈 문이 하나 있다(#968 전역 값).
    s.wait(
        "document.getElementById('editorOutDir').value.length > 0"
        " && !!document.getElementById('editorOpenFolderSettings')",
        "저장 폴더 재진술",
        requires=["#editorOutDir"],
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
    # 저장 뒤 머리가 상태를 말한다(#945 F5 — 판본 표기는 내부 어휘라 걷혔다).
    s.wait(
        "document.getElementById('editorSaveState').textContent.includes('저장됨')",
        "저장 상태 표기",
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
    # **작업이 자기 데이터를 끌고 온다**(U4 §2.4 · #932 U4-C — U2 §5.3 판정 D 의 명시 철회).
    # 종전 계약은 「문서 만들기에서 사용」이 **데이터 선택을 반드시 지난다**였고(결속 폐기의
    # 귀결) 마운트 뒤에도 작업은 0이었다. 결속이 durable 이 된 지금은 착지 자체가 승격이다 —
    # 이 걸음이 재는 것이 그 뒤집기다. 데이터 선택 면의 찾아보기·고정 계약(U2 §2.7 · #343)은
    # 아래 SX-05 H7 의 `_mount_data` 가 계속 지난다(같은 증거를 두 번 밟지 않는다).
    s.wait("document.querySelector('#scr-job.on') !== null", "문서 만들기 착지", requires=["#scr-job"])
    s.wait(
        "(function(){"
        "const d=document.getElementById('jobDataLabel');"
        "const n=document.getElementById('jobActionName');"
        # 화면이 다시 마운트되는 동안 두 요소는 잠시 사라진다(스냅샷 null 렌더) —
        # 부재를 실패가 아니라 「아직」으로 접어야 착지를 기다릴 수 있다.
        "if(!d||!n)return false;"
        "return d.value.length > 0 && n.textContent.trim() === '발주요청서';})()",
        "결속 데이터·작업 동시 착지",
        timeout=25.0,
        requires=["#jobDataLabel", "#jobActionName"],
    )
    seen["bound_work_arrives_with_its_data"] = str(
        s.js("document.getElementById('jobDataLabel').value")
    ).strip()

    candidate = '#jobCandidates button[data-cand="발주요청서"]'
    # 후보 줄은 이제 **결속 역인덱스**다 — 그 데이터로 만드는 작업만 선다. 방금 승격된
    # 작업이 그 자리에 `aria-pressed="true"` 로 서 있는 것이 「열렸다」의 정본이다.
    # 가시성·클릭 가능성은 여기서 재지 않는다: 그 단언은 **명시 선택을 앞둔 카드**의
    # 것이었고(누를 수 있는가), 지금 이 카드는 이미 눌린 결과다. 클릭 가능한 후보의
    # 기하는 온보딩 대본의 `_select_all` 이 매 티어에서 계속 지난다.
    s.wait(
        "(function(){"
        f"const b=document.querySelector({candidate!r});"
        "if(!b)return false;"
        "return b.getAttribute('aria-pressed') === 'true';})()",
        "결속 후보가 열린 작업으로 선다",
        timeout=25.0,
        requires=["#jobCandidates", candidate],
    )
    seen["work_candidate_actionable"] = "발주요청서"
    # 명시 사건은 사라지지 않고 **자리가 옮겨졌다**: 사용자가 누른 것은 라이브러리의
    # 「문서 만들기에서 사용」이고, 그 한 번이 데이터와 작업을 함께 세운다.
    seen["explicit_work_selected"] = "발주요청서"
    # 데이터-우선 계약(§18.2): 새 데이터의 선택은 **0건**에서 시작한다 — 무엇을 만들지는
    # 사용자가 고른다. 그래서 마운트만으로는 게이트가 열리지 않고, 여기서 전체 선택을
    # 눌러야 「N개 생성」이 열린다. 101 도 이 순서를 그대로 가르친다.
    _ensure_all_selected(s, "전체 선택")

    # ---- S5a 첫 실행은 막지도 알리지도 않는다 -------------------------------
    # 방금 만든 작업은 아직 한 번도 문서를 만들지 않았다. 종전에는 그 사실이 게이트를 닫고
    # 승인을 요구했고(#957 이 고지로 낮췄다), 간소화 라운드가 그 고지마저 걷었다 — 결과
    # 문서를 열어 확인하는 것은 첫 실행이든 아니든 상수라 알림이 바꾸는 행동이 없다.
    # 그래서 여기서 재는 것은 **생성이 열려 있고 사전검증이 첫 실행을 들먹이지 않는 것**,
    # 그리고 철거된 확인 면의 출구가 화면에 없다는 사실이다.
    s.wait(
        "!document.getElementById('jobGenBtn').disabled"
        " && !document.getElementById('jobPreflight').textContent.includes('첫 실행')",
        "첫 실행 무고지 + 생성 게이트 개방",
        requires=["#jobGenBtn", "#jobPreflight"],
    )
    seen["first_run_not_announced"] = True
    _expect(
        not s.js("!!document.getElementById('jobMirrorPreviewOpen')"),
        "S5a: 철거된 「생성 값 미리보기」 출구가 아직 서 있습니다",
    )
    _expect(
        not s.js("!!document.getElementById('jobReviewFlag')"),
        "S5a: 철거된 「승인 필요」 표지가 아직 서 있습니다",
    )
    seen["preview_surface_retired"] = True
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
    # 축은 이제 `<select>` 가 아니라 표 머리의 스위치다(U4 7번) — 값 설정형이 사라졌으므로
    # 대본도 **사용자가 하는 그대로** 누른다.
    s.click_sel("#jobOrderToggle", what="표시순서 뒤집기")
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
        " && document.getElementById('jobOrderToggle').getAttribute('aria-pressed') === 'true'",
        "재렌더 뒤에도 초안 축 유지",
        requires=["#jobRangeApply", "#jobOrderToggle"],
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
        " && document.getElementById('jobOrderToggle').getAttribute('aria-pressed') === 'false'"
        " && !document.getElementById('jobGenBtn').disabled",
        "취소 뒤 메인 범위 보존",
        requires=["#dataSheet", "#jobOrderToggle", "#jobGenBtn"],
    )

    # ---- S6 사전검증 + 위험 배너 --------------------------------------------
    # 존 재편: 구 「본문 확인」 존의 요약 한 줄(`#jobMirrorLine`/`#jobMirrorSummary`)과
    # 재진술 블록(`#jobRestate`)은 사전검증·표 머리가 이미 말하던 사실의 2·3중 발화라
    # 걷혔다. 남은 것은 **행동을 든** 위험 배너 host 뿐이고, 그 자리는 사전검증 바로 아래다.
    # 실주행에서 재는 것은 ①죽은 세 좌표의 부재 ②배너 host 가 사전검증 뒤에 있음이다 —
    # 부재를 대본이 안 재면 「걷었다」는 선언이 실앱에서 증명되지 않는다.
    s.wait(
        "!document.getElementById('jobMirrorLine')"
        " && !document.getElementById('jobMirrorSummary')"
        " && !document.getElementById('jobRestate')"
        " && document.getElementById('jobPreflight').nextElementSibling"
        " === document.getElementById('jobMirror')",
        "본문 요약·재진술 부재 + 위험 배너 자리",
        requires=["#jobPreflight", "#jobMirror"],
    )
    s.scroll_to("#jobPreflight")
    ctx.shoot("preflight-check")

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
        "'#editorTplList .pitem[data-path*=\"발주요청_기안\"]')",
        "편집기 고르기 존(TXT 항목)",
        requires=["#scr-editor", "#editorPairZone"],
    )
    s.click_sel(
        '#editorTplList .pitem[data-path*="발주요청_기안"]',
        what="TXT 템플릿 채택",
    )
    # TXT 세션도 **탭 3개**다(U6-D #978) — 셋째가 「이름·저장」이 되면서 매체가 정하는 것은
    # 단계가 아니라 그 안의 문서 파일 이름 행 하나로 좁아졌다(그 부재는 아래 3단계에서 잰다).
    s.wait(
        "document.querySelectorAll('#editor-steps .wstep-tab').length === 3"
        " && document.querySelector('#scr-editor').textContent.includes('공고번호')",
        "TXT 스키마·탭 3개",
        requires=["#editor-steps"],
    )
    ctx.queue_file_answer(ctx.csv_path)
    s.click_sel("#editorPoolBrowse", what="파일 찾아보기(TXT)")
    s.wait(
        "document.querySelector('#editorLinkCta').disabled === false",
        "TXT 연결 카드·전진 게이트 개방",
        requires=["#editorLinkCta"],
    )
    s.click_text("#scr-editor", "다음 ▶")
    s.wait(
        "!!document.querySelector('#scr-editor [data-act=\"confirm-suggested\"]')"
        " && document.querySelector('#scr-editor').textContent.includes('해양수산부')",
        "TXT 매핑표 미리보기",
        requires=["#scr-editor"],
    )
    s.click_sel('#scr-editor [data-act="confirm-suggested"]', what="제안 일괄 확인(TXT)")
    # 「확인 필요 0」 pill 은 **사람이 손댄 미확인 행**만 센다 — 자동 제안만 있는 표에서는
    # 승격 **전에도** 0 이라 이 문안만 기다리면 왕복이 도착하기 전에 지나간다(공허한 대기).
    # 배지 전건을 되읽어 전 행 확인을 실제로 잰다(S4 와 같은 형).
    s.wait(
        "document.querySelector('#scr-editor').textContent.includes('확인 필요 0')"
        " && [...document.querySelectorAll('#scr-editor [data-act=\"row-confirm\"]')]"
        ".every((b) => b.textContent.trim() === '확인')",
        "TXT 전 행 확인",
        requires=["#scr-editor"],
    )
    # TXT 도 3단계를 갖는다(U6-D #978) — 다른 것은 그 단계에 **문서 파일 이름 행이 없다**는
    # 것 하나다(파일을 만들지 않는 작업).
    s.click_text("#scr-editor", "다음 ▶")
    s.wait(
        "!!document.getElementById('editorName')"
        " && document.querySelector('#scr-editor input[data-act=\"pattern\"]') === null",
        "이름·저장 단계(TXT — 파일 이름 행 없음)",
        requires=["#editorName"],
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
    _ensure_all_selected(s, "전체 선택(TXT)")
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
        "'#editorTplList .pitem[data-path*=\"오류연습_미치환\"]')",
        "편집기 고르기 존(오류 연습)",
        requires=["#scr-editor", "#editorPairZone"],
    )
    s.click_sel(
        '#editorTplList .pitem[data-path*="오류연습_미치환"]',
        what="오류 연습 템플릿 채택",
    )
    s.wait(
        "document.querySelector('#scr-editor').textContent.includes('담당연락처')",
        "오류 연습 스키마",
        requires=["#scr-editor"],
    )
    ctx.queue_file_answer(ctx.csv_path)
    s.click_sel("#editorPoolBrowse", what="파일 찾아보기(오류 연습)")
    s.wait(
        "document.querySelector('#editorLinkCta').disabled === false",
        "연결 카드·전진 게이트 개방(오류 연습)",
        requires=["#editorLinkCta"],
    )
    s.click_text("#scr-editor", "다음 ▶")
    s.wait(
        '!!document.querySelector(\'#scr-editor [data-act="confirm-suggested"]\')',
        "매핑표(오류 연습)", requires=["#scr-editor"],
    )
    s.click_sel('#scr-editor [data-act="confirm-suggested"]', what="제안 일괄 확인(오류 연습)")
    # **승격이 실제로 도착했는지 먼저 잰다.** 이 다음 걸음은 표의 select 를 만지는데, 승격
    # 왕복이 아직 오지 않았으면 그 사이의 재렌더가 방금 넣은 값을 서버 값으로 되돌린다 —
    # `set_value` 는 값 넣기와 커밋을 **두 번의 왕복**으로 하므로 그 사이가 곧 창이다(실측:
    # 비움 선언이 통째로 증발해 「확인 필요 1」로 남았다). 아래 「배지 disabled」 조건은 승격
    # 전에도 참이라(내용 없는 행은 처음부터 못 누른다) 그 자리를 지켜 주지 못한다.
    s.wait(
        "document.querySelector('#scr-editor').textContent.includes('자동 제안 0')"
        " && document.querySelector('#scr-editor').textContent"
        ".includes('제안을 모두 확인했습니다')",
        "일괄 승격 착지(오류 연습)",
        requires=["#scr-editor"],
    )
    # 데이터에 없는 「담당연락처」는 일괄 승격이 **건드리지 않는다**(U6-C #977) — 사람이 그
    # 행에서 「비워 둠」을 골라야 넘어간다. 확인의 자리가 모달에서 그 행으로 옮겨 왔고,
    # 요구 자체(사람이 명시로 비운다)는 그대로다.
    empty_row = '#scr-editor table.map tr[data-field="담당연락처"]'
    s.wait(
        f'!!document.querySelector({json.dumps(empty_row)})'
        f' && document.querySelector({json.dumps(empty_row)}).querySelector'
        '(\'[data-act="row-confirm"]\').disabled === true',
        "비움 선언을 기다리는 행", requires=["#scr-editor"],
    )
    seen["empty_value_gate_asked"] = True
    s.set_value(empty_row + ' select[data-act="row-source"]', "sp:blank")
    # 같은 이유로 배지 전건을 함께 잰다 — pill 만 보면 비움 선언이 도착하기 전에 지나간다.
    s.wait(
        "document.querySelector('#scr-editor').textContent.includes('확인 필요 0')"
        " && [...document.querySelectorAll('#scr-editor [data-act=\"row-confirm\"]')]"
        ".every((b) => b.textContent.trim() === '확인')",
        "오류 연습 전 행 확인",
        requires=["#scr-editor"],
    )
    s.click_text("#scr-editor", "다음 ▶")
    s.wait("!!document.getElementById('editorName')", "이름·저장 단계(오류 연습)",
           requires=["#editorName"])
    s.set_value("#editorName", "오류연습")
    # **두 저장 동사 중 나머지 한쪽**을 여기서 실주행한다(U6-D #978). 「작업 저장」은
    # 제자리 착지라 S4·트랙 B 가 이미 찍었고, 이 동사가 약속하는 절반은 그 다음이다:
    # 저장 성공 뒤 `prefer_work` 로 「문서 만들기」에 그 작업이 **선 상태로** 착석한다.
    s.click_text("#scr-editor", "저장하고 문서 만들기로")
    s.wait(
        "document.querySelector('#scr-job.on') !== null"
        " && document.getElementById('jobActionName').textContent.trim() === '오류연습'",
        "저장 뒤 문서 만들기 착석",
        timeout=30.0,
        requires=["#scr-job", "#jobActionName"],
    )
    seen["save_and_open_seated"] = True
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
    _ensure_all_selected(s, "전체 선택(오류 연습)")
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
    # staging 은 **앱 밖 편집**이다(한글에서 템플릿을 고치는 것과 같은 사건) — push 를 내지
    # 않으므로 조치가 있을 때만 서는 구획이 아직 침묵한다. 그 사용자 이야기의 나머지 절반,
    # 「앱으로 돌아온다」를 여기서 실제로 낸다: 셸이 포커스 복귀에 현재 화면을 다시 묻고
    # (#932 B5), 그때 드리프트가 존을 세운다. 대본이 지어내는 상태가 아니라 사용자가 반드시
    # 지나는 사건이라 여기 선다.
    s.js("window.dispatchEvent(new Event('focus')); true;")
    s.wait(
        "!!document.getElementById('jobTplCheck')",
        f"{kind} 앱 복귀 뒤 템플릿 조치 필요 존",
        timeout=30.0,
        requires=["#scr-job"],
    )
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
    _pick_option(s, "#cs-opt-0-0", what="공고번호 표시 선택")
    s.wait("document.getElementById('cs-opt-0-0').checked", "첫 Option fresh 반영", requires=["#cs-opt-0-0"])
    # U4 14~17 — **고른 직후 그 슬롯은 접히지 않는다**(U4-A 26번 회귀 금지). backend 는 이제
    # 이 슬롯을 `settled` 로 싣지만, 방금 만진 자리가 눈앞에서 접히면 그것이 26번이 고친 바로
    # 그 깜빡임이다. 상태가 걸린 사실이라 정적 렌더 테스트가 못 보고 여기가 진다.
    _expect(
        s.js(
            "(function(){const d=document.getElementById('cs-opt-0-0').closest('details');"
            "return !!d && d.open;})()"
        ),
        "H1: 고른 직후 그 슬롯이 접혔습니다(U4-A 26번 회귀)",
    )
    after_first = _snapshot(s)
    after_first_view = _current_view(after_first)
    _expect(after_first_view["new_configuration_token"] != before_token, "H2: command 뒤 token이 갱신되지 않았습니다")
    first_option = after_first_view["projection"]["slots"][0]["options"][0]
    _expect(first_option["selected"] and first_option["effective"], "H2: declared/effective intent가 일치하지 않습니다")
    h2_trace = s.take_dispatch_trace()
    _expect(any(item.get("action") == "select_slot_option" for item in h2_trace), "H2: actual Product command trace가 없습니다")
    for selector in ("#cs-opt-1-0", "#cs-opt-2-0"):
        _pick_option(s, selector, what="initial canonical Option 선택")
        s.wait(f"document.querySelector({json.dumps(selector)}).checked", "Option fresh 반영", requires=[selector])

    before_fields = tuple(_workbench(_snapshot(s)).get("active_field_requirement_ids") or ())
    _pick_option(s, "#cs-opt-0-1", what="S1 Option B 전환")
    s.wait("document.getElementById('cs-opt-0-1').checked", "Option B fresh recompute", requires=["#cs-opt-0-1"])
    after_fields = tuple(_workbench(_snapshot(s)).get("active_field_requirement_ids") or ())
    _expect(before_fields != after_fields, "H3: Option A↔B 뒤 Active Field가 변하지 않았습니다")
    _pick_option(s, "#cs-opt-0-0", what="preserved Option 복원")
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
    # U4 14~17 — 보관된 선택 **목록이 슬롯보다 앞에** 선다(한 번에 끝내는 길이 먼저다).
    _expect(
        s.js(
            "(function(){const z=document.getElementById('jobContentSelectionZone');"
            "const list=z&&z.querySelector('.cs-presets');"
            "const slot=z&&z.querySelector('.cs-slot');"
            "if(!list||!slot)return false;"
            "return !!(list.compareDocumentPosition(slot)"
            " & Node.DOCUMENT_POSITION_FOLLOWING);})()"
        ),
        "S9: 보관된 선택 목록이 슬롯 뒤에 섰습니다(U4 14~17 — 프리셋 우선)",
    )
    # 목록에 **실제로 보이는지**를 잰다(hidden 요소는 존재해도 사용자에게는 없는 것이다).
    s.wait(
        "[...document.querySelectorAll('#jobContentSelectionZone .cs-preset-name')]"
        f".some(e=>e.offsetParent!==null&&e.textContent.trim()==={json.dumps(preset_name)})",
        "보관된 선택 목록의 실렌더 항목",
        requires=["#jobContentSelectionZone"],
    )
    # 지금을 저장 시점과 다르게 만든 뒤 적용해야 「되돌아왔다」가 vacuous 하지 않다.
    _pick_option(s, "#cs-opt-0-1", what="프리셋 적용 대조를 위한 다른 선택")
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
    _pick_option(s, "#cs-opt-1-1", what="old-token Option command")
    s.wait_dispatch_gate("old-token command 보류")
    # 왕복 중 표지는 임시 **줄**이 아니라 구획의 `aria-busy` 다(U4 계열1-26) — 줄이 섰다
    # 사라지면 구획 높이가 두 번 튀어 「접혔다 깜빡인다」로 보인다.
    s.wait(
        "(document.querySelector('.content-selection')||{getAttribute:()=>null})"
        ".getAttribute('aria-busy') === 'true'",
        "content command pending",
        requires=["#jobContentSelectionZone"],
    )
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
    _pick_option(s, "#cs-opt-1-0", what="깨진 선택 복구")
    s.wait("document.getElementById('cs-opt-1-0').checked", "깨진 선택 복구 반영", requires=["#cs-opt-1-0"])
    _pick_option(s, "#cs-opt-0-0", what="유지된 이전 선택 재확인")
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
    # 열 값은 **항목 값**이다(U6-C #977) — 실 열은 `col:` 접두이고 특수 항목은 `sp:` 라
    # 두 이름 공간이 구조적으로 갈린다(동명 열 충돌 봉쇄).
    s.set_value(source_select, "col:공고명")
    badge = row + ' button[data-act="row-confirm"]'
    # 배지는 **채울 것이 생긴 뒤에야** 눌린다(`confirmable`). `set_value` 의 발신은 host
    # 왕복이라 바로 위 줄이 끝난 시점에 서버가 아직 그 열을 모를 수 있고, 그때 누르면
    # 비활성 버튼을 클릭해 조용히 아무 일도 안 일어난다 — 열린 것을 보고 누른다.
    s.wait(
        "!!document.querySelector(" + json.dumps(badge + ":not([disabled])") + ")",
        "확인 배지 무장(결속 반영)",
        requires=[row],
    )
    s.js(
        "(function(){const b=document.querySelector(" + json.dumps(badge) + ");"
        "if(b && b.getAttribute('aria-pressed') !== 'true')b.click();return !!b;})()"
    )
    s.wait(
        "document.querySelector(" + json.dumps(badge) + ").getAttribute('aria-pressed') === 'true'",
        "신규 Binding 확인",
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

    # Record advisory(#957): 행 안의 빈 값은 **차단이 아니라 표식 고지**다. 유도는 그대로
    # 실 DataTarget 전환이고, PASS 는 Product projection/DOM 이 낸 비차단 한 줄에서 온다.
    # 종전 이 자리는 blocker 목록(`#jobRecordValidationIssues`)과 그 복구 버튼을 겨눴다 —
    # 그 목록은 이제 **열 누락**류에만 서므로 빈 값으로는 유도되지 않는다.
    blank_path = ctx.stage_data("blank")
    _mount_data(ctx, blank_path)
    _ensure_all_selected(s, "blank record 전체 선택")
    s.wait(
        "!!document.getElementById('jobRecordValidationAdvisory')"
        " && !document.getElementById('jobRecordValidationIssues')",
        "record validation advisory(비차단)",
        timeout=30.0,
        requires=["#jobRecordValidationAdvisory"],
    )
    record_before = _workbench(_snapshot(s))
    record_advisory = str(
        s.js("document.getElementById('jobRecordValidationAdvisory').textContent")
    )
    _expect(
        not record_before["record_validation"]["issues"]
        and int(record_before["record_validation"].get("advisory_count") or 0) >= 1,
        f"H5: 빈 값이 차단 issue 로 섰습니다 — #957 이후 그 자리는 비차단 고지입니다: {record_advisory!r}",
    )
    # 옛 좌표 거절(H7)은 그대로 잰다. 실 issue 가 없어졌으므로 좌표를 **지어내** 던진다 —
    # 계약은 「옛 좌표를 수락하지 않는다」이지 「issue 가 있다」가 아니다.
    old_recovery_target = {
        "target_kind": "cell",
        "snapshot_generation": -1,
        "record_identity": "current-record/-1/0",
        "model_index": 0,
        "field_id": "공고명",
    }
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

    # Exact delivery + destructive overwrite confirm roundtrip (#957). The harness collision
    # file predates the no-mutation bracket.
    # 새 스냅샷은 선택을 0건으로 되돌린다(`_reset_range_for_snapshot` — 마운트 직후 선택 0건).
    # 그래서 전환 뒤에 배달 계획을 물으려면 **다시 고르는** 걸음이 대본에 있어야 한다. 없으면
    # 제품은 계획 대신 배달 blocker 를 세우므로(`job_run.ts:869-878`) `#jobPlannedDocuments` 는
    # 아예 서지 않고, 그 부재는 「계획이 늦다」가 아니라 「고른 것이 0건이다」라는 뜻이다.
    _ensure_all_selected(s, "전환 뒤 record 재선택")
    # 서식 폴더 왕복(U6-A #975) — 저장 폴더와 같은 면·같은 형상. 새 창을 만들지 않는다.
    _set_templates_root(s, ctx, ctx.templates_root, what="서식 폴더 지정")
    seen["templates_root_roundtrip"] = ctx.templates_root
    output_dir = ctx.prepare_output()
    _set_output_folder(s, ctx, output_dir, what="managed output folder 선택")
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
    # 파괴 **전**: 계획된 문서는 전부 새 파일이다(`WRITE_NEW`) — 이 음성 대조가 없으면
    # 아래 파괴 대조가 「원래 그랬다」와 구별되지 않는다.
    before_collision = _workbench(_snapshot(s))
    dispositions_before = [
        item["collision_disposition"]
        for item in before_collision["delivery"]["planned_documents"]
    ]
    _expect(
        dispositions_before and "WRITE_OVERWRITE" not in dispositions_before,
        f"H5: 충돌 전인데 이미 파괴 처분입니다 — {dispositions_before!r}",
    )
    relative_path = before_collision["delivery"]["planned_documents"][0]["relative_path"]
    ctx.create_collision(relative_path)
    baseline_manifest = ctx.output_manifest()
    # 충돌 처리 선택기는 없다(U4 계열2-27) — 기본이 덮어쓰기라 같은 이름은 막히지 않고
    # `WRITE_OVERWRITE` 처분으로 선다. 「목록 새로 확인」도 없으므로(2-28) 재관찰은
    # delivery 를 무효화하는 전이가 낸다: 같은 폴더를 다시 지정하는 것이 그 전이이고,
    # REVIEW_DELIVERY 의 등록된 복구 동사(`#settingsPickFolder`)와 같은 자리다 — 저장 폴더
    # 전역화로 그 동사가 작업 화면에서 설정 모달로 이사했다(화면 쪽에 남은 것은 그리로 가는
    # 문 `#jobOpenFolderSettings` 뿐이라 복구 좌표가 아니다).
    _set_output_folder(s, ctx, output_dir, what="충돌 발생 뒤 delivery 재관찰")
    s.wait(
        "!!document.querySelector('#jobPlannedDocuments li[data-collision-disposition="
        "\"WRITE_OVERWRITE\"]')",
        "destructive overwrite delivery",
        timeout=30.0,
        requires=["#jobPlannedDocuments"],
    )
    # 파괴 **후**: 처분이 `WRITE_OVERWRITE` 로 서고, 그래도 관찰 축은 막지 않는다
    # (U4 계열2-27). 확인은 **실행 축**에 산다 — 생성을 눌렀을 때 되돌아오는
    # `needs_overwrite` 왕복이 그것이고, 그 자리는 legacy·managed 공용 하나다(#957).
    required = _workbench(_snapshot(s))
    _expect(
        "WRITE_OVERWRITE" in [
            item["collision_disposition"]
            for item in required["delivery"]["planned_documents"]
        ],
        "H5: 충돌 뒤에도 파괴 처분이 서지 않았습니다",
    )
    _expect(
        not s.js("!!document.getElementById('jobManagedPreviewOpen')"),
        "H5: 철거된 「생성 내용 확인」 동사가 아직 서 있습니다",
    )
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
    # 파괴 확인 왕복 — 조용히 덮지 않는다. 본문이 수치와 이름을 재진술하고, 확인해야 앉는다.
    s.wait(
        "!document.getElementById('confirmModal').classList.contains('hidden')"
        " && document.getElementById('confirmModalTitle').textContent.includes('덮어쓰기')",
        "managed 덮어쓰기 확인 왕복",
        timeout=30.0,
        requires=["#confirmModal", "#confirmModalTitle"],
    )
    overwrite_confirm_body = str(
        s.js("document.getElementById('confirmModalBody').textContent")
    )
    _expect(
        "덮어씁니다" in overwrite_confirm_body,
        f"H5: 확인 본문이 파괴를 말하지 않습니다 — {overwrite_confirm_body!r}",
    )
    _expect(
        relative_path in overwrite_confirm_body,
        "H5: 확인 본문이 덮어쓸 이름을 재진술하지 않습니다",
    )
    s.click_sel("#confirmModalOk", what="덮어쓰고 생성")
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
    _pick_option(s, "#cs-opt-0-1", what="Work A pending Option")
    s.wait_dispatch_gate("Work A response 보류")
    _select_work(s, "발주요청 기안")
    s.release_dispatch()
    # 재는 것은 **A 의 응답이 B 에 착지하지 않는다**이고, 표지는 「B 의 구획이 비었다」였다.
    # 그 표지는 B 가 **미준비**라 구획이 통째로 안 서던 시절의 것이고, 준비를 착석이 지게 된
    # 뒤로(#932 B5) 한동안 구획이 서서 「선택할 내용이 없습니다」를 말했다. U4 13번 뒤로는
    # 다시 서지 않는다 — 다만 사유가 다르다: 미준비라서가 아니라 **고를 항목이 없어서**다.
    # 그래서 두 사실을 함께 잰다: B 에 A 의 갈래가 없고(A 가 보류시킨 것이 `cs-opt-0-1` 이다),
    # 조치 0건인 B 의 구획은 자리째 서지 않는다.
    s.wait(
        "document.getElementById('jobActionName').textContent.trim() === '발주요청 기안'"
        " && !document.getElementById('cs-opt-0-1')"
        " && document.querySelectorAll('#jobContentSelectionZone .cs-slot').length === 0"
        " && document.getElementById('jobContentSelectionZone').children.length === 0"
        " && !document.querySelector('#jobContentSelectionZone .cs-presets')",
        "Work B latest snapshot wins",
        timeout=30.0,
        requires=["#jobActionName", "#jobContentSelectionZone"],
    )
    # 숨김이 자리만 남기지 않는가 — 빈 `.zone` 은 안쪽 여백과 구분선을 그대로 들어 사용자에게는
    # 「사라진 구획」이 아니라 「비어 있는 구획」으로 보인다(CSS `:empty` 접기의 실주행 증거).
    _expect(
        s.js(
            "getComputedStyle(document.getElementById('jobContentSelectionZone')).display"
        ) == "none",
        "H7: 조치 0건 구획이 빈 상자로 남았습니다",
    )
    _select_work(s, "발주요청서")

    seen["sx05"] = {
        "H1": {"labels": labels, "raw_ids": raw_ids, "pixel": audit},
        "H2": {"before_token": before_token, "after_token": after_first_view["new_configuration_token"], "trace": h2_trace},
        "H3": {"option_a_fields": before_fields, "option_b_fields": after_fields},
        "H4": {"retained_fates": fates, "binding_target": exact_target, "binding_repaired": repaired},
        "H5": {"context_copy": context_text, "record_advisory": record_advisory, "dispositions_before": dispositions_before, "overwrite_confirm_body": overwrite_confirm_body, "runtime_reason": final_managed["create_action"].get("disabled_reason")},
        "H6": {"filesystem_before": baseline_manifest, "filesystem_after": ctx.output_manifest()},
        "H7": {"stale_trace": stale_commands, "old_record_rejected": True, "data_transition": "KEEP/RELEASE/FAILURE_ATOMIC", "work_race": "B_WON"},
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
    # 작업이 없으면 작업대 관찰이 없고, 그래서 delivery intent 도 서지 않는다(관찰은 작업의
    # 것이다). 저장 폴더는 **다르다**: 전역 설정이라 작업이 앉기 전에도 값이 서 있고, 그것이
    # 전역화가 바꾼 계약의 실증거다 — 종전에는 도출 재료(템플릿)가 없어 여기가 비어 있었다.
    _expect(initial_wb.get("run_delivery_intent") is None, "H7: 작업 선택 전에 delivery intent가 섰습니다")
    initial_folder = initial.get("output_folder") or {}
    _expect(
        (initial_folder.get("directory"), initial_folder.get("source"))
        == (ctx.output_dir, "remembered"),
        f"H7: 작업 선택 전 전역 저장 폴더가 서지 않았습니다 — {initial_folder!r}",
    )
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
    # U3-06(#879 → 전역화): 저장 폴더는 restart 뒤에도 선다 — **설정한 전역 폴더**로다.
    # 경로는 지난번 지정 그대로이고 출처는 `remembered`(라벨은 「설정한 저장 폴더」)다.
    # 도출 존은 작업대 관찰이 아니라 **스냅샷 최상위**에서 읽는다: 작업 유무·관찰 성패와
    # 무관한 사실이라 자리가 옮겨졌다. 충돌 처리는 세션이 고르는 값이 아니게 됐으므로
    # (U4 §2-27) 언제나 `DEFAULT_COLLISION_POLICY` 여야 한다 — 이 자리가 재는 것은
    # 「세션 축이 restart 를 넘어 새어 오지 않는다」이고, 그 축이 저장 폴더 전역화로 하나 더
    # 줄었을 뿐 판정은 그대로다(정책 이름을 여기 적지 않고 정본 상수를 읽는다).
    intent = wb.get("run_delivery_intent") or {}
    delivery_default = {
        "directory": intent.get("output_directory"),
        "source": (current.get("output_folder") or {}).get("source"),
        "collision_policy": intent.get("collision_policy"),
    }
    _expect(
        delivery_default == {
            "directory": ctx.output_dir,
            "source": "remembered",
            "collision_policy": DEFAULT_COLLISION_POLICY,
        },
        f"H7: 저장 폴더 기억이 계약대로 복원되지 않았습니다 — {delivery_default!r}",
    )
    after_files = ctx.output_manifest()
    _expect(after_files == before_files, "H7: restart observation이 filesystem을 변경했습니다")
    return {
        "sx05_restart": {
            "durable": {"job": current.get("job_name"), "selections": selected, "binding": binding},
            "delivery_default": delivery_default,
            "data_restored": data_restored,
            # 세션 축은 둘이다 — 충돌 처리는 U4 §2-27 에서 세션이 고르는 값이 아니게 돼
            # 「부활하지 않았다」고 말할 것 자체가 없다(위 delivery_default 가 기본값을 잰다).
            "session_absent": {"active_work_before_reselect": True},
            "filesystem_before": before_files,
            "filesystem_after": after_files,
        }
    }


def _pick_option(s: "Surface", selector: str, *, what: str) -> None:
    """갈래 라디오를 **사람이 하는 그대로** 누른다 — 접혀 있으면 먼저 편다.

    U4 14~17 로 끝난 슬롯은 접힌 채 선다(`<details>`). 닫힌 `<details>` 안의 요소는 화면에
    없지만 `el.click()` 은 **그래도 통과한다** — 그래서 대본이 「눈으로 본 것과 다른 결론」을
    내는 자리가 생긴다(CLAUDE.md 가 selftest 클릭에 대해 경고하는 바로 그 결함류). 펼치는
    걸음을 명시로 두어, 사람이 밟는 경로와 대본이 밟는 경로를 같게 만든다.
    """
    s.js(
        "(function(){const el=document.querySelector(" + json.dumps(selector) + ");"
        "if(!el)return false;const d=el.closest('details');"
        "if(d && !d.open)d.open=true;return true;})()"
    )
    s.click_sel(selector, what=what)


def _ensure_all_selected(s: "Surface", what: str) -> None:
    """전건 선택 **상태로 만든다** — 「그 단추를 한 번 누른다」가 아니다.

    U4 11번에서 「전체 선택/해제」 두 버튼이 머리 체크박스 하나로 접히면서 이 자리의 동사가
    멱등에서 **토글**로 바뀌었다. 선택은 작업 전환에서 생존하므로(§18.2 세션 소유) 전환 뒤에는
    이미 전건인 채로 들어오는 걸음이 있고, 거기서 한 번 누르면 그것이 곧 **해제**다. 그래서
    대본은 상태를 보고 필요할 때만 누른다 — 표현하려는 것은 클릭이 아니라 「전건이 됐다」다.

    착지도 **수치**로 잰다. 종전 술어는 게이트 문안에 「최소 1건」이 없는 것을 봤는데, 그것은
    다른 blocker(검토 요구 등)가 서 있으면 선택이 0건이어도 조용히 통과한다 — 실제로 이
    라운드에서 그 구멍이 온보딩 T9 를 엉뚱한 자리에서 넘어뜨렸다.
    """
    s.js(
        "(function(){const b=document.getElementById('jobSelAll');"
        "if(b && !b.checked && !b.disabled)b.click(); return true;})()"
    )
    s.wait(
        "(function(){const c=document.getElementById('jobSelCount');"
        r"if(!c)return false;const m=/선택\s+(\d+)/.exec(c.textContent||'');"
        "return !!m && Number(m[1]) > 0;})()",
        f"{what} — 선택 착지",
        timeout=30.0,
        requires=["#jobSelCount"],
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
    # 클릭이 아니라 **선택이 선 것**이 이 걸음의 착지다: 작업 저장 직후의 새 스냅샷은 범위를
    # 0건으로 되돌리므로(`_reset_range_for_snapshot`), 누른 사실만 믿고 넘어가면 다음 걸음이
    # 「0건 선택」 게이트를 제품 결함으로 읽는다.
    _ensure_all_selected(s, f"전체 선택({job})")
