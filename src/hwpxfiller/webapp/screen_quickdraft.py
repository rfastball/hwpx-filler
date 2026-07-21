"""빠른 기안 화면 컨트롤러 — 작업의 휘발 쌍둥이(R-flow 블록 5, 결정 29). webview 비의존.

R-flow 구현 라운드(에픽 #90) 슬라이스 7. 링1 :class:`~hwpxfiller.gui.quickdraft_state.
QuickDraftViewModel` 을 소유·위임하는 얇은 어댑터다 — 다른 실행 표면과 같은 컨트롤러 계약
(``name``·``initial``·``snapshot``·``dispatch``)을 구현하고 등록 한 줄로 배선된다.

**빠른 기안 = 아무것도 저장하지 않는 작업**(결정 29): 템플릿(라이브러리 사본/붙여넣기)과
선택적 데이터를 세션 안에서만 결합해 복사한다. 세션 전체가 휘발이라(결정 32의 휘발도 사다리)
레일 이탈·복귀는 생존하지만 앱 종료·「새 기안」은 소멸한다. 남기려면 복사하거나 승격 동사로
동결한다 — 「템플릿으로 저장」은 착지했고(#135), 「작업으로 저장」은 목적지가 아직 없다(아래).

**슬라이스 착지 순서**(confirm-or-alarm — 없는 기능을 있는 척하지 않는다):
- **PR-1(이 커밋)**: 컨트롤러 골격 + 레일/화면 신설 + 빈 세션 스냅샷. 눈에 보이는 결과는
  도달 가능한 빈손 화면이다(템플릿 소스·토큰 폼·데이터는 아직 없다).
- PR-2: 템플릿 소스(라이브러리·붙여넣기·원문 라이브 편집) + 파이프라인 토큰 폼 + 미리보기
  채움 표지(결정 22·34).
- PR-3: 데이터 소스 이원(등록 데이터·임의 파일) + 제스처 결속(정확=자동·근사=제안 원클릭)
  + 행 재겨눔 3분류 고지 + 표현형 3층(결정 30·31·32·34).
- **PR-4(이 커밋)**: 휘발도 가드(「새 기안」·템플릿 전환 — session_loss 판정 + 세션 노동 재진술) +
  복사(공유 copy_clipboard 관통 → 사후 경보 승계) + 표지 토글·소유권 색(auto/hand/man) +
  상태 배지 3상 + 승격 2동사 표면(결정 32·33).

**부록 B-7 처분 기록(#134)** — 미구현·미채택은 문안째 박제한다(표기가 없으면 "PR 본문에 적힌
스코프만 진실"이 되고 다음 라운드가 구멍을 못 본다 = confirm-or-alarm 위반의 문서판):

- **(c) 붙여넣기 진입 모달 유지 — 채택된 결론**. 원문의 라이브 인라인 편집은 착지했지만
  **진입은 모달로 남긴다**. 근거 둘: ①빈손 상태에는 붙여넣을 대상 textarea 가 화면에 없다
  (본문이 진입 카드 2장뿐) — 인라인 진입을 만들려면 빈손 전용 편집 표면을 하나 더 지어야
  하는데, 그것은 원문 탭과 같은 일을 하는 두 번째 표면이다. ②모달 열기가 **세션 교체 제스처의
  확인 지점**(``sessionGuardOk("switch")``)과 결속돼 있다 — 인라인이면 "어디부터가 교체인가"의
  경계가 흐려져 저장 안 된 노동을 언제 물을지 정할 수 없다.
- **(e) 데이터 행 클립보드 붙여넣기 — 미구현(유보)**. 표에서 복사한 행을 붙여 데이터로 삼는
  경로는 저장소 전체에 없다(클립보드 **읽기** 자체가 없다 — 쓰기만 있다). 데이터 겨눔은
  등록 데이터·임의 파일 둘뿐이다. 착수하려면 네이티브 클립보드 읽기 + 구분자 추론 +
  머리행 판정이 필요하고, 그 추론들은 전부 confirm-or-alarm 판단을 새로 요구한다(조용한
  오추론 금지) — 별도 라운드 몫이라 여기서 있는 척하지 않는다.
- (g) 대상 글꼴 선언·정렬 린트 합류: **착지**(이 파일 ``target_font``·``lint``·``_aligned``).

**승격 2동사의 비대칭**(#135, 마일스톤 C — 슬라이스 7의 "표면만" 스코프 경계 해소):

- **「템플릿으로 저장」 = 착지**(``_do_save_template``). 세션 원문을 라이브러리로 승격하고
  그룹까지 지정한다. 동명은 확인 게이트(결정 34) — 관리 화면의 접미 회피·loud 거부와 다른
  계약인 이유는 그 메서드 독스트링에 있다. 저장 뒤 세션은 죽지 않고 정체만 승격한다.
- **「작업으로 저장」 = 미구현(목적지 부재)**. 표면은 비활성 + 인라인 사유로 남는다(죽은 버튼
  금지). 빠른 기안의 템플릿은 txt 인데 :class:`~hwpxfiller.core.job.Job` 은 hwpx 전용이고
  (``template_path``→hwpx·매핑=TemplateSchema 필드·생성=hwpx 엔진), 작업 목록의 TXT 구획은
  ``screen_job.py`` 의 말대로 "draft-as-job 착지 전까지 빈 채로" 있다. 지금 승격시키면 목록에
  뜨지도 열리지도 실행되지도 않는 Job 이 생긴다 — 죽은 산출물은 조용한 소실과 같은 부류다.
  결정 31의 국경(매핑 초안을 전 행 미확정으로 착지시키고 에디터 확정 워크플로가 엄격성을
  재부과)은 그 draft-as-job 라운드의 계약이다.
"""
from __future__ import annotations

from hwpxcore.atomic import write_text_atomic

from ..core.format_engine import presets as format_presets
from ..core.mapping import TYPES
from ..core.text_registry import TextTemplateRegistry
from ..core.text_render import (
    RenderReport,
    align_segments,
    render_segments,
    segments_have_space_run,
)
from ..gui.quickdraft_state import QuickDraftViewModel, QuickToken
from .screens import (
    NO_ROWS_TEXT,
    DatasetPoolRegistry,
    PushSink,
    default_pool_registry,
    load_pool_into,
    pool_sources_payload,
    source_label,
)
from .settings import is_proportional_font, load_draft_target_font
from .template_groups import TemplateGroupModel, validate_template_name

# 표시형 프리셋 목록(유형별) — 에디터 스냅샷과 **같은 표(format_engine)**에서 뽑는다.
# 빠른 기안의 fmt 코드가 승격 시 매핑 행의 fmt 로 그대로 이관되려면 두 표면이 같은 어휘를
# 써야 한다(결정 31의 "프리셋 키 = 매핑과 1:1").
_FMT_OPTIONS = {
    t: [{"code": code, "label": label} for label, code in format_presets(t)] for t in TYPES
}


def _token_state(t: QuickToken) -> str:
    """토큰 폼 칩 상태(결정 30·31 표현형 3층) — 카드 표지와 한 출처가 되게 이름을 고정한다.

    - ``auto``: 결속·무수정(자동 서식). ``hand``: 결속·직접 수정(사람 소유 강등).
    - ``man``: 무결속 수기 값. ``blank``: 비어 있음.

    결속 토큰은 값이 비어도(데이터 빈칸) ``auto`` 다 — 「비어 있음」은 아직 임자가 없는
    자리를 뜻하는 말이라, 임자가 있는데 값이 빈 자리와 섞으면 표지가 거짓말을 한다.
    """
    if t.col and not t.edited:
        return "auto"
    if t.col and t.edited:
        return "hand"
    if t.text.strip() != "":
        return "man"
    return "blank"


#: 고지 문안에 이름을 그대로 적는 상한 — 넘으면 「외 N개」로 접는다.
_NAMES_SHOWN = 3


def _names(names: "list[str]") -> str:
    """토큰 이름 열거 — 소량은 전부, 대량은 앞 몇 개 + 「외 N개」(결정 5 표본 문안 동형).

    빠른 기안의 토큰 수는 한 화면 분량이라 층화가 필요 없다 — 순서 그대로가 사용자가 폼에서
    보는 순서다.
    """
    if len(names) <= _NAMES_SHOWN:
        return ", ".join(names)
    return f"{', '.join(names[:_NAMES_SHOWN])} 외 {len(names) - _NAMES_SHOWN}개"


def _frozen_notice(vm: QuickDraftViewModel) -> str:
    """데이터 교체로 열이 사라져 평문 동결된 자리의 경보 문안(없으면 빈 문자열).

    사후 사실이라 확인을 받을 수 없다 — 대신 시끄럽게 알린다(confirm-or-alarm 의 알람 갈래).
    다시 결속된 자리는 목록에서 빠져 경보가 스스로 낫는다(낡은 경보는 그 자체로 거짓).
    """
    live = [n for n in vm.frozen_cols if (t := vm.token(n)) is not None and not t.col]
    if not live:
        return ""
    return (
        f"바뀐 데이터에 없는 열이라 {len(live)}개 자리({_names(live)})의 값이 "
        "이전 값 그대로 굳었습니다. 데이터에서 오는 값이 아니니 확인하세요."
    )


class QuickDraftController:
    """빠른 기안 화면 — :class:`QuickDraftViewModel` 소유·위임(링1 로직 재구현 금지)."""

    name = "quickdraft"

    def __init__(
        self,
        registry: TextTemplateRegistry,
        push: PushSink,
        *,
        pool_registry: "DatasetPoolRegistry | None" = None,
        txt_groups: "TemplateGroupModel | None" = None,
    ) -> None:
        self._registry = registry
        self._push_sink = push
        # txt 그룹 모델(#108 결정 2·3) — 「템플릿으로 저장」이 그룹까지 지정하므로 필요하다.
        # 관리 화면과 **같은 인스턴스**여야 한다(app.py 가 주입): 별도 인스턴스면 지정·접힘
        # 인메모리 캐시가 갈라져 여기서 넣은 그룹이 관리 화면 목록에 안 보인다(에디터 1단계
        # 피커에 hwpx 모델을 공유한 것과 같은 이유).
        self._groups = txt_groups if txt_groups is not None else TemplateGroupModel("txt")
        # 등록 데이터(풀) 겨눔(결정 34의 데이터 판) — 기본은 홈 레지스트리, 테스트는 주입.
        # 다른 실행 표면과 **같은 인스턴스**를 공유해야 데이터 관리 화면의 변경이 즉시 보인다.
        self.pool_registry = (
            pool_registry if pool_registry is not None else default_pool_registry()
        )
        # 템플릿 라이브러리는 txt·템플릿 관리와 공유 레지스트리(변경이 양쪽에 반영).
        self.vm = QuickDraftViewModel(registry)
        # 전각 정렬 치환(결정 17 린트 처방, #134 (g) 합류) — **세션 렌더 옵션**이라 템플릿
        # 원본은 건드리지 않는다. 대상 글꼴 선언은 반대로 전역 영속이라 여기 사본을 두지
        # 않고 매번 설정에서 읽는다(txt 큐에서 바꾼 선언이 이 화면에도 즉시 보여야 한다 —
        # 사본을 들면 두 화면이 서로 다른 글꼴로 "이대로 복사됩니다"라고 말한다).
        self._fullwidth = False

    # ------------------------------------------------------------- 관측 푸시
    def _push(self) -> None:
        self._push_sink(self.name, self.snapshot())

    def snapshot(self) -> dict:
        """휘발 세션의 웹 관측 스냅샷 — 템플릿 정체·토큰 폼·미리보기 세그먼트.

        미리보기는 링1 :func:`~hwpxfiller.core.text_render.render_segments`(채움 표지 삼분,
        결정 22·33)를 소비한다: 웹은 토큰 정규식을 재구현하지 않는다(파생경계 번역오류 상류
        차단). 토큰 상태 배지도 같은 값 레코드에서 파생해 카드와 한 출처가 되게 한다.
        데이터 절반(겨눔 라벨·행 스테퍼·열 목록·표시형 표)은 경량 슬롯이 소비한다 —
        필터·다중 선택 존은 N 행 표면의 문법이라 여기 없다. 복사는 공유 copy_clipboard 관통
        (render/can_copy), 소유권 색은 토큰 state 를 웹이 그대로 소비(파생 판정 금지).
        """
        vm = self.vm
        record = vm.values_record()
        segments, report = render_segments(vm.template_text, record)
        missing, empty = report.missing_fields, report.empty_fields
        # 정렬 린트 술어는 **치환 전 원문** 기준(결정 17) — 치환하면 런이 사라지므로, 원문
        # 기준으로 보아야 "적용됨 · 되돌리기" 상태에서도 무엇을 고쳤는지 정직하게 말한다.
        space_run = segments_have_space_run(segments)
        target_font = load_draft_target_font()
        proportional = is_proportional_font(target_font)
        segments = self._aligned(segments)
        tokens = [
            {
                "name": t.name,
                "state": _token_state(t),
                "value": vm.token_value(t),
                # 파이프라인 폼 2열(결정 34): 소스(결속 열, ''=무결속) → 표시형(유형+코드).
                "col": t.col or "",
                "fmt_kind": t.fmt_kind,
                "fmt_code": t.fmt_code,
                # 근사 제안(결정 30) — 자동으로 붙지 않고 버튼 하나로만 붙는다.
                "suggest": vm.suggest_for(t) or "",
            }
            for t in vm.tokens
        ]
        return {
            # 템플릿 정체 — 유래(lib/paste)와 (수정됨) 강등 여부는 슬롯 라벨이 소비(결정 34).
            "origin": vm.origin,
            "template_name": vm.template_name,
            "template_text": vm.template_text,
            "modified": vm.modified,
            # 파이프라인 토큰 폼(결정 34) — 이름·상태(칩)·현재 값·소스(결속 열)·표시형·제안.
            "tokens": tokens,
            # 미리보기 세그먼트(채움 표지 삼분) — literal/fill/blank/missing. 무결속 빈 토큰은
            # missing 으로 {{토큰}} 원문이 빨강으로 남는다(방향 A 미채움 = 아직 안 채운 자리).
            "segments": [{"text": s.text, "kind": s.kind, "name": s.name} for s in segments],
            "missing_fields": missing,
            "empty_fields": empty,
            # 미채움 = 렌더에서 빠진(missing) + 데이터 빈칸(blank). 알약·상태 배지가 소비.
            "unfilled_count": len(missing) + len(empty),
            # 겨눔 존재의 단일 진실 = datasource(파생 bool, 별도 저장 없음). data_kind 는
            # 유래(등록/파일)일 뿐 존재 사본이 아니다 — 불변식은 VM 의 원자 세엄이 성립시킨다.
            "has_data": vm.has_data(),
            "data_label": vm.data_label,
            "data_kind": vm.data_kind,
            # 병기 라벨은 저장하지 않고 매번 합성한다(K8 단일 출처 — 세 표면 공통 문구).
            "data_source_label": source_label(vm.data_kind, vm.data_label),
            # 경량 데이터 슬롯(단건 표면) — 열 목록·행 스테퍼. 필터·다중 선택 문법은 N 행
            # 표면(txt 큐·작업 존)의 것이라 여기 들이지 않는다(결정 34 형상).
            "columns": vm.columns,
            "record_count": vm.record_count(),
            "row_idx": vm.row_idx,
            "row_label": vm.row_label(),
            "fmt_options": _FMT_OPTIONS,
            # 대상 글꼴 선언(결정 17) — **전역 영속**이라 이 화면이 사본을 들지 않고 읽어 쓴다.
            # 미리보기가 선언을 추종하지 않으면(#134) 사용자가 굴림체로 선언해도 이 화면만
            # 다른 글꼴로 그려서, 바로 아래 "이대로 복사됩니다"의 정직성을 갉는다.
            "target_font": target_font,
            # 선언-조건부 정렬 린트(결정 17) — 표면은 판정하지 않는다(글꼴 이름으로 비례폭을
            # 재판별하거나 정규식을 다시 걷지 않는다). txt 큐와 같은 술어·같은 처방.
            "lint": {
                "proportional": proportional,
                "space_run": space_run,
                "applied": self._fullwidth,
                "active": self._fullwidth or (proportional and space_run),
            },
            # 교체로 열이 없어져 평문 동결된 자리의 경보(확인이 불가능한 사후 사실이라 알람
            # 쪽). 이미 다시 결속했거나 사람이 손댄 자리는 빼서 낡은 경보가 남지 않게 한다.
            "frozen_notice": _frozen_notice(vm),
        }

    def initial(self) -> dict:
        """부팅 시 웹이 1회 당겨 가는 초기 상태 — 슬롯 드롭다운용 템플릿 목록 포함."""
        return {"templates": self.vm.template_names(), **self.snapshot()}

    # 타이핑 구동 액션(값 입력·원문 편집)은 **푸시하지 않고 스냅샷을 반환**한다. 서버 푸시가
    # 포커스된 textarea 의 innerHTML 을 재구성하면 왕복 중 입력한 글자가 지워지고 한글 IME
    # 조합이 끊긴다(슬라이스 4 stale 경합 클래스, 리뷰 확정). JS 가 반환 스냅샷으로 미리보기·
    # 폼만 겨냥 패치하고 포커스 입력은 손대지 않는다(전면 재렌더는 구조 액션에서만).
    _NO_PUSH = {"set_token", "edit_source"}

    def dispatch(self, action: str, payload: dict):
        """순수 데이터 액션(창 불필요) 라우팅. 미지 액션은 시끄럽게 거부(P5 규약 정렬).

        구조 액션(템플릿 선택·붙여넣기)은 관측 푸시로 전면 재렌더한다. 타이핑 액션은
        :attr:`_NO_PUSH` 라 푸시 대신 스냅샷을 반환해 JS 가 겨냥 패치하게 한다(위 설명).
        휘발도 가드(session_guard)·새 기안(fresh)은 PR-4 가 얹었다. 복사는 dispatch 가 아니라
        공유 copy_clipboard 브리지 관통이다(render/can_copy — txt 카드와 같은 진입점).
        """
        handler = getattr(self, f"_do_{action}", None)
        if handler is None:  # confirm-or-alarm: 조용한 무시 금지.
            raise ValueError(f"알 수 없는 빠른 기안 액션: {action!r}")
        result = handler(payload)
        if action in self._NO_PUSH:
            return result  # 포커스 입력 보호 — 푸시 대신 반환 스냅샷으로 JS 가 겨냥 패치
        if getattr(handler, "is_query", False):
            return result  # 무변이 질의(고지 판정) — 재렌더 유발 금지(txt·작업 동형)
        self._push()
        return result

    # ---------------------------------------------------- 템플릿 소스(PR-2)
    def _do_select_template(self, p: dict) -> None:
        """슬롯 드롭다운·빈손 카드에서 라이브러리 템플릿 선택 — 세션 사본 적용(결정 34)."""
        self.vm.apply_library(p["name"])
        self._fullwidth = False  # 치환은 그 원문에 대한 판단 — 원문이 바뀌면 함께 죽는다(txt 동형)

    def _do_paste_template(self, p: dict) -> None:
        """붙여넣기 모달 확정 — 이름 없는 세션 사본(라이브러리 비저장, 결정 34).

        빈 붙여넣기(공백뿐)는 **템플릿만 비우고 데이터 겨눔은 남긴다**(clear_template) — origin=
        'paste' 로 두면 슬롯은 「붙여넣은 텍스트」를 가리키는데 본문·알약은 빈손을 말해 세 표면이
        어긋난다(confirm-or-alarm 위반). fresh 로 겨눔까지 버리면 전환 가드가 "데이터는
        이어집니다"라 한 약속을 어긴다(리뷰 F2) — 그래서 데이터는 남기고 템플릿만 비운다.
        """
        text = p["text"]
        if text.strip() == "":
            self.vm.clear_template()
        else:
            self.vm.apply_paste(text)
        self._fullwidth = False  # 새 원문에 옛 치환 결정이 승계되지 않는다

    def _do_edit_source(self, p: dict) -> dict:
        """원문 편집 탭 라이브 편집 — 타이핑이 토큰 폼을 즉시 재구성((수정됨) 강등, 결정 34).

        _NO_PUSH: 반환 스냅샷으로 JS 가 폼 패인만 재구성하고 포커스된 원문 textarea 는 안 만진다.

        **전각 치환(``_fullwidth``)을 여기서 리셋하지 않는다** — 템플릿 선택·붙여넣기와 다른
        판단이다(리뷰 F3 의 지적에 대한 결론). 저 둘은 원문을 통째로 갈아치우는 한 번의 사건이라
        옛 판단을 승계하면 조용한 이월이 되지만, 이 경로는 **타건마다** 불린다: 리셋하면 사용자가
        치환을 켠 뒤 원문에 한 글자만 쳐도 치환이 소리 없이 꺼져, "적용됨" 상태가 손가락 밑에서
        사라진다. 이월이 조용하지도 않다 — ``lint.active`` 는 ``applied`` 가 참인 동안 계속 참이라
        「전각 공백으로 치환했습니다 · 되돌리기」 줄이 편집 내내 서 있고, 미리보기와 클립보드가
        :meth:`_aligned` 한 통로를 지나므로 화면이 곧 결과다(보이는 이월은 조용한 이월이 아니다).
        """
        self.vm.edit_source(p["text"])
        return self.snapshot()

    def _do_set_token(self, p: dict) -> dict:
        """토큰 값 직접 입력 — 결속 토큰이면 사람 소유로 강등한다(표현형 3층 최하층).

        _NO_PUSH: 반환 스냅샷으로 JS 가 미리보기만 패치하고 포커스된 값 textarea 는 안 만진다.
        """
        self.vm.set_token_text(p["name"], p.get("text", ""))
        return self.snapshot()

    # ------------------------------------------------- 데이터 겨눔·결속(PR-3)
    #
    # 등록 데이터 겨눔에 :class:`~hwpxfiller.webapp.screens.PoolTargetingMixin` 을 섞지
    # 않는다: 그 래퍼는 **컨트롤러가 라벨·유래를 따로 저장**하는 표면(txt·작업)을 위한
    # 것이라 `data_label = …` → `data_source = …` → `_after_pool_load(…)` 세 대입 사이에
    # 부분 상태 창이 열리는데, 빠른 기안은 겨눔 상태 전부가 휘발 세션 VM 소유이고 불변식
    # (`datasource ⟺ data_kind`)을 **원자 세엄 하나**로만 성립시키기로 했다(PR-1 리뷰).
    # 게이트·문구의 공용 실행부(load_pool_into·pool_sources_payload·source_label·
    # NO_ROWS_TEXT)는 그대로 소비하므로 나라 동결·모호 시트·죽은 참조·0건 재진술은 세
    # 표면 단일 출처다(부록 A-31) — 손복사되는 것은 없다.
    def _do_pool_sources(self, p: dict) -> dict:
        """활성 등록 데이터 목록 — 공용 피커(pool_picker.js)가 그대로 소비한다."""
        return pool_sources_payload(self.pool_registry)

    _do_pool_sources.is_query = True  # 목록 조회는 무변이 — 피커를 여는 것만으로 재렌더 금지

    def _do_load_pool(self, p: dict) -> dict:
        """등록 데이터 겨눔 — 공유 관문에 위임(실패는 raise 대신 오류 dict 재진술)."""
        res = load_pool_into(self.pool_registry, p["name"], self.vm.load_pool_item)
        if not res["ok"]:
            return res
        return {"ok": True, "label": source_label("pool", self.vm.data_label)}

    def _do_clear_data(self, p: dict) -> None:
        """데이터 해제 — 결속 값은 평문 동결(결정 30). 가드 고지는 웹이 먼저 받는다."""
        self.vm.clear_data()

    def _do_step_row(self, p: dict) -> None:
        """행 스테퍼 한 칸 — **다음 번호는 여기서 계산**한다(슬라이스 4 교훈).

        웹이 캐시한 번호에 더해 보내면 연타 시 두 번째 클릭이 아직 도착 안 한 첫 클릭의
        결과를 못 보고 같은 행을 다시 보낸다(클릭이 조용히 삼켜진다). 양끝을 넘는 걸음은
        제자리다 — 버튼이 이미 비활성인 자리라 거절이 아니라 무동작이 정직하다.
        """
        self.vm.step_row(int(p["delta"]))

    def _do_set_source(self, p: dict) -> "dict | None":
        """토큰 결속·해제(제안 원클릭·드롭다운 공유 액션) — 해제도 값은 평문 동결.

        **수기 값 덮어쓰기 확인**: 직접 입력한 값이 있는 자리에 열을 붙이면 그 값은 되돌릴
        수 없이 사라진다(되돌리기는 자동 값으로만 돌아간다). 그래서 첫 호출은 확인 요구를
        돌려주고(``{"confirm": 문안}``), 웹이 사람에게 확인받아 ``confirm=True`` 로 다시
        부른다 — 재진술 확인 후 허용(relink 게이트와 같은 문법).
        """
        name, col = p["name"], (p.get("col") or None)
        if col and not p.get("confirm"):
            old = self.vm.bind_overwrites(name)
            if old:
                return {
                    "confirm": (
                        f"{{{{{name}}}}} 에 직접 입력한 값 「{old}」은 「{col}」 열의 값으로 "
                        "바뀌고 되돌릴 수 없습니다. 계속하시겠습니까?"
                    )
                }
        self.vm.bind(name, col)
        return None

    def _do_set_fmt(self, p: dict) -> None:
        """표현형 정정(2층) — 프리셋 코드만 바꾼다(유형은 열이 정한다)."""
        self.vm.set_fmt(p["name"], p.get("code", ""))

    def _do_revert_token(self, p: dict) -> None:
        """직접 수정 → 자동 복귀 — 강등을 되돌리는 출구(막다른 강등 금지, 결정 31)."""
        self.vm.revert_token(p["name"])

    #: 제스처별 "값이 남는 곳"의 사람 어휘 — 확인 문안이 실제 동작과 어긋나지 않게 한다
    #: (한 문장을 세 동사에 돌려쓰면 해제 확인이 있지도 않은 「새 데이터」를 말한다).
    _CARRY_WHERE = {
        "swap": "새 데이터에서도 그대로 남아 데이터에서 오는 값과 섞입니다",
        "row": "새 행에서도 그대로 남아 그 행의 값과 섞입니다",
        "clear": "그대로 남습니다. 나머지 자리는 지금 보이는 값으로 굳습니다",
    }

    def _do_carry_notice(self, p: dict) -> dict:
        """데이터 교체·해제·행 이동 전 고지 — 지금 Python 이 판정한다(스냅샷 캐시 아님).

        결정 32의 3분류를 그대로 옮긴다: 결속·무수정 = 조용 재생성(말하지 않는다) ·
        **직접 수정 = 가드**(``armed`` — 확인) · **무결속 수기 = 유지 + 고지**(``notice`` —
        막지 않는다). 수기 값 하나 때문에 행을 넘길 때마다 모달이 서면 그건 완화 조항이
        경계하는 "반복"이라, 고지는 화면 노트로 흐르고 확인은 혼합이 생길 때만 선다.

        ``gesture`` 는 swap|row|clear — 문안이 실제 동사를 말한다.
        """
        carry = self.vm.carry_over()
        edited, manual = carry["edited"], carry["manual"]
        where = self._CARRY_WHERE.get(p.get("gesture", "swap"), self._CARRY_WHERE["swap"])
        message = ""
        if edited:
            message = (
                f"직접 고친 값 {len(edited)}개({_names(edited)})는 {where}. "
                "확인하고 계속하세요."
            )
        parts = []
        if manual:
            parts.append(
                f"직접 입력한 값 {len(manual)}개({_names(manual)})는 데이터와 무관하게 그대로 남습니다."
            )
        # 해제만의 고지(#134): clear_data 가 결속 자리를 평문으로 동결해 소유권이 「자동」에서
        # 「직접 입력」으로 통째 넘어간다. 값이 눈에 남으니 조용한 소실은 아니지만, 전이가
        # 무언이면 사용자는 화면의 값이 여전히 데이터에서 온다고 믿는다 — 교체·행 이동에선
        # 같은 자리가 조용히 재생성되므로 이 문장을 세우지 않는다(제스처별 정확한 술어).
        if p.get("gesture") == "clear" and carry["bound"]:
            bound = carry["bound"]
            parts.append(
                f"데이터에서 오던 값 {len(bound)}개({_names(bound)})는 지금 보이는 값으로 굳고 "
                "표지가 「직접 입력」으로 바뀝니다."
            )
        notice = " ".join(parts)
        return {
            "armed": bool(edited),
            "message": message,
            "notice": notice,
            "edited": edited,
            "manual": manual,
            "bound": carry["bound"],
        }

    _do_carry_notice.is_query = True  # 무변이 질의 — dispatch 가 push 를 생략한다

    # ------------------------------------------------ 휘발도 가드·복사(PR-4, 결정 32·33)
    #
    # 제스처별 술어·문안(지배 결함류 = 확인 문안 ≠ 실제 집합, 슬라이스 4·5 교훈 + 이 PR 리뷰):
    # - **fresh**(새 기안 = 통째 폐기): 세션의 모든 노동이 사라지므로 종류별로 **열거**한다
    #   (데이터 겨눔·원문·사람 값 전부 정확히 인용 — 결정 27 수치 재진술).
    # - **switch**(다른 템플릿으로 전환): _set_template 이 **동명 토큰의 값을 승계**하고 데이터
    #   겨눔도 **유지**한다(_retokenize·datasource 불변). 그래서 사람 값을 "사라진다"고 열거하면
    #   실제 살아남는 것을 거짓으로 말한다(리뷰 F4) — 대신 **규칙만** 말한다: 확정 손실은 원문
    #   (붙여넣은 원문·라이브러리 원문 수정)뿐이고 값은 "같은 이름이면 이어지고 없으면 사라진다".
    #   정확 손실 집합은 새 템플릿에 달려 있어 가드 시점에 알 수 없으므로 토큰을 열거하지 않는다.
    def _do_session_guard(self, p: dict) -> dict:
        """「새 기안」·템플릿 전환 전 세션 폐기 확인 — **지금** 판정한다(스냅샷 캐시 아님).

        휘발도 사다리(결정 32): 레일 이탈은 무가드로 살지만 세션을 비우는/바꾸는 제스처는
        재현 불가한 노동을 버린다. 무장 아니면 조용히 통과(빈손·미노동엔 죽은 확인 금지). 판정
        재료는 링1 :meth:`~hwpxfiller.gui.quickdraft_state.QuickDraftViewModel.session_loss`
        (토큰 1회 순회), 무장 연역·문안 합성만 컨트롤러다(carry_notice 와 같은 규율).
        """
        loss = self.vm.session_loss()
        if p.get("gesture", "fresh") == "switch":
            return self._switch_guard(loss)
        return self._fresh_guard(loss)

    _do_session_guard.is_query = True  # 무변이 질의 — 재렌더 유발 금지

    @staticmethod
    def _fresh_guard(loss: dict) -> dict:
        """새 기안(통째 폐기) 가드 — 사라지는 노동을 종류별로 정확히 열거한다.

        빈손이면 버릴 게 없다(origin None). 붙여넣은 원문은 재선택 복원 경로가 없어 그 자체가
        노동이고(리뷰 F1), 라이브러리 무수정 원문은 재선택으로 되살아나므로 열거하지 않는다.
        """
        parts: "list[str]" = []
        if loss["paste_body"]:
            parts.append("붙여넣은 템플릿 원문")
        elif loss["modified"]:
            parts.append(f"「{loss['template_name']}」 원문 수정" if loss["template_name"] else "원문 수정")
        if loss["data_label"]:
            parts.append(f"선택한 데이터 {loss['data_label']}")
        if loss["manual"]:
            parts.append(f"직접 입력 {len(loss['manual'])}곳({_names(loss['manual'])})")
        if loss["edited"]:
            parts.append(f"직접 고친 값 {len(loss['edited'])}곳({_names(loss['edited'])})")
        if not parts:  # origin None 이거나 순수 라이브러리 무수정 — 버릴 노동 없음
            return {"armed": False, "message": ""}
        return {
            "armed": True,
            "message": (
                "이 세션을 비우면 지금까지 만든 내용이 모두 사라집니다. "
                f"사라지는 항목: {' · '.join(parts)}. "
                "빠른 기안은 저장하지 않으니, 남기려면 먼저 복사하세요."
            ),
        }

    @staticmethod
    def _switch_guard(loss: dict) -> dict:
        """템플릿 전환 가드 — 규칙만 말한다(토큰 열거 금지, 리뷰 F4).

        확정 손실은 원문(붙여넣은 원문·라이브러리 원문 수정)뿐이다. 사람 값은 새 템플릿에
        같은 이름이 있으면 이어지고 없으면 사라지는데, 어느 쪽인지는 전환 대상에 달려 있어
        여기서 알 수 없다 — 그래서 "사라진다"고 단정하지 않고 규칙을 재진술한다.
        """
        human = loss["manual"] + loss["edited"]
        lost_body = ""
        if loss["paste_body"]:
            lost_body = "붙여넣은 템플릿 원문"
        elif loss["modified"]:
            lost_body = f"「{loss['template_name']}」 원문 수정" if loss["template_name"] else "원문 수정"
        if not (lost_body or human):  # 원문 손실도 사람 값도 없으면 전환은 아무것도 안 버린다
            return {"armed": False, "message": ""}
        head = f"다른 템플릿으로 바꾸면 {lost_body}이 사라집니다. " if lost_body else "다른 템플릿으로 바꾸면 "
        return {
            "armed": True,
            "message": (
                head
                + "같은 이름의 자리와 선택한 데이터는 새 템플릿에서도 이어집니다. "
                "다만 새 템플릿에 없는 자리에 직접 넣은 값은 남지 않습니다. 남기려면 먼저 복사하세요."
            ),
        }

    def _do_fresh(self, p: dict) -> None:
        """「새 기안」 — 세션을 빈손으로 되돌린다(결정 32). 가드는 웹이 먼저 묻는다(위)."""
        self.vm.fresh()
        self._fullwidth = False  # 세션 렌더 옵션은 세션과 함께 죽는다

    # ------------------------------------------------ 승격(결정 33·34, #135)
    #
    # 승격 2동사 중 **「템플릿으로 저장」만** 여기 산다. 「작업으로 저장」은 목적지(기안 작업 =
    # txt 작업)가 아직 실체가 아니라 — 작업 목록의 TXT 구획이 "준비 중"으로 비어 있다 —
    # 승격시켜도 열 수도 실행할 수도 없는 Job 이 생긴다. 그래서 표면은 비활성으로 두고 사유를
    # 정직하게 말한다(죽은 버튼 금지). draft-as-job 라운드가 잇는다.
    def _do_promote_info(self, p: dict) -> dict:
        """저장 모달이 열릴 때의 프리필 — 이름 후보·그룹 후보·현재 그룹(무변이 질의).

        이름 후보는 라이브러리 유래일 때만 그 이름이다(붙여넣기는 이름이 없으니 빈칸에서
        사람이 짓는다). 그룹 후보는 **살아있는 지정만** 센다(고아 그룹 부활 금지 — 결정 8).
        """
        vm = self.vm
        name = vm.template_name if vm.origin == "lib" and vm.template_name else ""
        keys = self._library_keys()
        return {
            "name": name,
            "groups": self._groups.existing_groups(keys),
            "group": self._groups.group_of(f"{name}.txt") if name else "",
        }

    _do_promote_info.is_query = True  # 무변이 질의 — 재렌더 유발 금지

    def _library_keys(self) -> "list[str]":
        """살아있는 txt 템플릿의 그룹 식별키 — 관리 화면과 같은 규칙(루트 상대경로+확장자)."""
        return [f"{n}{TextTemplateRegistry.SUFFIX}" for n in self.vm.template_names()]

    def _do_save_template(self, p: dict) -> dict:
        """「템플릿으로 저장」(결정 33·34) — 세션 원문을 라이브러리로 승격. 값은 저장 대상이 아니다.

        동명은 **확인 게이트**를 거친다(결정 34 "역반영 자동 없음 = 명시 승격만, 동명 덮어쓰기
        확인 게이트"). 관리 화면의 두 기존 경로와 다른 계약인 것은 의도다: 「가져오기」는
        ``이름 (2).txt`` 접미로 회피하고 「새 TXT」는 loud 거부하는데, 여기선 **되돌려 쓰기가
        본래 목적**(라이브러리 사본을 고쳐 왔으니 같은 이름으로 되돌아가는 게 정상 경로)이라
        회피도 거부도 사용자가 원한 일을 막는다. 대신 파괴를 확인받는다.

        저장 뒤 세션은 죽지 않고 **정체만 승격**한다(:meth:`~hwpxfiller.gui.quickdraft_state.
        QuickDraftViewModel.mark_saved_as`) — 채우던 값·데이터 겨눔은 그대로라 하던 일을 잇는다.
        """
        if not self.vm.template_text.strip():  # 빈손 승격 = 빈 템플릿 양산(복사 게이트 동형)
            return {"ok": False, "error": "저장할 템플릿 원문이 없습니다."}
        try:
            name = validate_template_name(p.get("name", ""))
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}  # 모달 인라인 재진술(창 밖 예외 금지)
        root = self._registry.directory
        dest = root / f"{name}{TextTemplateRegistry.SUFFIX}"
        if dest.exists() and not p.get("confirm"):
            return {
                "ok": False,
                "needs_confirm": True,
                "name": name,
                "confirm_text": (
                    f"라이브러리에 이미 「{name}」 템플릿이 있습니다. "
                    "지금 원문으로 덮어쓰면 기존 내용은 되돌릴 수 없습니다. "
                    "채운 값은 저장되지 않고 원문만 저장됩니다."
                ),
            }
        overwritten = dest.exists()
        root.mkdir(parents=True, exist_ok=True)
        write_text_atomic(str(dest), self.vm.template_text)
        # 그룹 지정은 **저장이 성공한 뒤에만** — 파일 없는 키에 지정을 남기면 고아가 된다.
        # 덮어쓰기에서 사용자가 그룹을 안 건드렸으면 프리필로 돌아온 현재 그룹이 그대로 실린다.
        self._groups.set_group(dest.name, p.get("group", ""))
        self.vm.mark_saved_as(name)
        return {
            "ok": True,
            "name": name,
            "overwritten": overwritten,
            # 슬롯 드롭다운은 initial() 에서 한 번 받아 캐시하므로, 새 이름이 목록에 서려면
            # 여기서 갱신본을 함께 돌려줘야 한다(방금 만든 템플릿이 목록에 없는 어긋남 방지).
            "templates": self.vm.template_names(),
        }

    def _do_set_fullwidth(self, p: dict) -> None:
        """전각 정렬 치환 적용/해제(결정 17 린트 처방, #134 (g)) — 세션 렌더 옵션.

        템플릿 원본은 건드리지 않는다(이름 있는 라이브러리 사본이 조용히 강등되지 않게).
        미리보기와 클립보드가 :meth:`_aligned` 한 통로를 지나므로 되읽기가 곧 검증이다.
        """
        self._fullwidth = bool(p["value"])

    def render(self) -> "tuple[str, RenderReport]":
        """빠른 기안 렌더 — 미리보기와 **같은 세그먼트 통로**로 클립보드 평문을 만든다.

        표지는 화면 전용이라 클립보드엔 음영이 없다(결정 33). 종전엔 ``render_record`` 를
        따로 불렀는데, 정렬 치환이 합류하면서(#134 부록 B-7 (g)) 그러면 치환이 미리보기에만
        걸려 "보이는 것과 복사되는 것"이 갈라진다 — txt 카드와 같은 처방으로 세그먼트 경로
        하나에 묶어 그 어긋남을 구조적으로 없앤다. 공유
        :meth:`~hwpxfiller.webapp.app.Api.copy_clipboard` 이 ``(text, report)`` 계약을 소비한다.
        """
        segments, report = render_segments(self.vm.template_text, self.vm.values_record())
        return "".join(s.text for s in self._aligned(segments)), report

    def _aligned(self, segments: list) -> list:
        """전각 치환 적용(세션 옵션이 켜졌을 때만) — 미리보기·클립보드 공용 통로(txt 동형)."""
        return align_segments(segments) if self._fullwidth else segments

    def can_copy(self) -> bool:
        """복사 가능 = 템플릿이 깔려 있음 — 빈손 클립보드 쓰기 차단(리뷰 F3 동형).

        미채움이 있어도 복사는 막지 않는다(완화 조항 — 미리보기에서 빨강으로 보이고, 경보는
        복사 **후**에 온다: 결정 33 사후 경보). 여기 게이트는 "쓸 게 아예 없음"만 막는다.
        """
        return bool(self.vm.template_text.strip())

    # ------------------------------------------- 네이티브 보조(브리지가 다이얼로그 담당)
    def load_data_path(self, path: str, *, sheet: "str | None" = None) -> None:
        """선택된 임의 파일을 겨눔(결정 34) — 0건이면 시끄럽게 실패하고 상태는 불변.

        브리지(``pick_data_file``/``load_data_sheet``)가 부르는 공개 표면이라 dispatch 를
        경유하지 않는다 — 그래서 푸시도 여기서 직접 한다.
        """
        records = self.vm.load_data(path, sheet=sheet)
        if not records:
            raise ValueError(NO_ROWS_TEXT)  # 문구는 세 표면 단일 출처(R-copy)
        self._push()
