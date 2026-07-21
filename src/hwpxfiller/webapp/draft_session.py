"""기안 세션(txt) 공용 본체 — 「기안문 채우기」와 「기안」 화면의 단일 출처. #148 슬라이스 3a.

R-info 3부 결정 1·5·7 의 합병은 **두 표면이 같은 세션 기계를 쓴다**는 뜻이다. 이 모듈은
:class:`~hwpxfiller.webapp.screens.TxtController` 가 혼자 갖고 있던 세션 본체(템플릿 원문 ·
데이터 존 · 큐 · 작업점 카드 · 대상 글꼴 · 정렬 린트 · T3 가드 · 클립보드 렌더)를 **무변화로**
끌어올린 것이다 — 「기안」 화면이 400줄 사본을 새로 짓지 않게(#94 가 남긴 교훈: 한시적
중복은 한시적이지 않다).

소비자는 둘:

- :class:`~hwpxfiller.webapp.screens.TxtController` — 구 화면. 세션이 화면의 전부라
  스냅샷·디스패치를 그대로 물려받는다(슬라이스 6에서 사망).
- :class:`~hwpxfiller.webapp.screen_draft.DraftController` — 신 화면. 좌 목록(master)에
  세션(detail)을 얹는다. 스냅샷은 목록 키 + :meth:`DraftSessionMixin._session_snapshot`
  병합이고 디스패치는 두 계열의 ``_do_*`` 가 한 라우터를 공유한다(MRO).

**스코프 경계**: 여기 있는 것은 **휘발 세션**뿐이다. 저장된 기안 작업의 복원·지속성 스위치
5종·「기안으로 저장」 승격은 슬라이스 4·5 가 얹는다 — 없는 걸 있는 척하지 않는다.
"""
from __future__ import annotations

from pathlib import Path

from ..core.text_render import (
    RenderReport,
    align_segments,
    render_segments,
    segments_have_space_run,
    template_fields,
)
from ..core.text_registry import TextTemplateRegistry
from ..gui.selection_state import SelectionModel
from ..gui.txt_queue import TxtQueueModel
from ..gui.txt_state import TxtDraftViewModel
from .data_zone import DataZoneMixin
from .screens import (
    NO_ROWS_TEXT,
    DatasetPoolRegistry,
    PoolTargetingMixin,
    PushSink,
    default_pool_registry,
    source_label,
)
from .settings import (
    is_proportional_font,
    load_draft_target_font,
    save_draft_target_font,
)


class TargetFontSetting:
    """대상 글꼴 선언(결정 17)의 **단일 실체** — 두 기안 표면이 한 인스턴스를 공유한다.

    값의 스코프가 **앱 전역 영속**이라 컨트롤러마다 사본을 캐시하면 한쪽에서 바꾼 선언이
    다른 쪽에 도달하지 않는다(코덱스 리뷰 P2): 저장은 됐는데 그 화면의 콤보·미리보기 글꼴·
    비례폭 정렬 린트는 앱을 다시 켤 때까지 옛 값으로 판정한다 — 선언과 실제가 갈라지는
    이 저장소 지배 결함류. 공유 실체 하나로 그 자리를 없앤다(#108 의 `TemplateGroupModel`
    공유와 같은 처방). 스냅샷마다 설정 파일을 다시 읽는 대안은 매 타건 I/O 라 기각.
    """

    def __init__(self) -> None:
        self._value = load_draft_target_font()

    @property
    def value(self) -> str:
        return self._value

    def set(self, font: str) -> None:
        """선언 변경 — **저장이 먼저**(영속 실패 시 상태 불변 + 브리지 경보)."""
        save_draft_target_font(font)  # 검증도 여기 단일 출처(열거형·문안 사본 금지)
        self._value = font


class DraftSessionMixin(DataZoneMixin, PoolTargetingMixin):
    """기안(txt) 휘발 세션 — :class:`TxtDraftViewModel` 소유·위임.

    스파이크가 끝까지 검증한 첫 실화면(SPIKE_FINDINGS.md). 표현 재진술(빨강 미입력
    ``{{토큰}}`` · 〈빈 값〉)은 링2 대체라 웹(js/screens/txt.js · draft.js)에서 만든다 — VM
    로직 재구현이 아니다.

    **데이터 존(블록 3·4, 슬라이스 6 PR-2b)**: 행 선택 = 복사용 렌더링 큐의 **전-선언**
    (결정 16 — hwpx 와 문법 대칭, 차이는 선언 입도뿐). 필터·선택 디스패치와 스냅샷 합성은
    :class:`~hwpxfiller.webapp.data_zone.DataZoneMixin` 공유(작업 화면과 단일 출처), 큐
    상태는 링1 :class:`~hwpxfiller.gui.txt_queue.TxtQueueModel` 이 소유한다(재구현 금지) —
    선택 변경마다 :meth:`TxtQueueModel.reconcile` 로 재봉합(``copied ⊆ selected`` 자가복구).

    **작업점 카드(블록 3, 슬라이스 6 PR-3)**: 큐가 지나가는 한 장(결정 16).
    :meth:`_session_snapshot` 의 ``card`` 섹션이 작업점 레코드를 링1
    :func:`~hwpxfiller.core.text_render.render_segments` (채움 표지 삼분, 결정 22)로 사영하고
    상태 색인(위치·처리·빈칸 지도)을 싣는다. :meth:`render` 는 자유 레코드 커서가 아니라 큐
    작업점을 렌더하며(복사=완료의 대상), :meth:`note_copied` 가 복사 후 큐를 전진시킨다
    (전진 opt-in=``_advance_after``, 기본 꺼짐). 건별 파일 저장은 사망(결정 18) — 새 큐
    표면에 재구현하지 않는다.

    **대상 글꼴 선언·정렬 린트·T3 가드(블록 3, 슬라이스 6 PR-4)**: 클립보드 평문은 글꼴을
    운반하지 않으므로(글꼴 = 목적지 소유) 붙여넣을 곳의 표준 글꼴을 선언받고 카드 렌더가 그
    선언을 따른다(결정 17 — 넘기려는 모습으로 미리 봄). 선언이 비례폭일 때만 연속 공백 정렬을
    경보하고 전각 치환을 제안하며, 치환은 **세션 렌더 옵션**(``_fullwidth``)이라 템플릿 원본은
    불변이고 카드와 클립보드가 같은 함수를 통과한다(보이는 것이 복사되는 것). T3 가드는
    데이터 교체가 큐의 부분 진행을 조용히 버리지 못하게 막는다(결정 26·27).
    """

    # 미지 액션 거부 문구의 화면 이름(confirm-or-alarm) — 소비자가 자기 이름으로 덮는다.
    _action_label = "기안 세션"

    name: str
    _push_sink: PushSink

    def _init_session(
        self,
        registry: TextTemplateRegistry,
        *,
        pool_registry: "DatasetPoolRegistry | None" = None,
        target_font: "TargetFontSetting | None" = None,
    ) -> None:
        """세션 상태 초기화 — 소비자 ``__init__`` 이 부른다(생성자 상속 대신 명시 호출).

        컨트롤러마다 생성자 시그니처가 다르므로(「기안」은 JobRegistry 도 받는다) 세션 몫만
        여기서 세운다. 수명 주석은 원본 그대로 — 무엇이 세션과 함께 죽고 무엇이 살아남는지가
        이 클래스의 계약이다.
        """
        self._registry = registry
        # 등록 데이터(풀) 겨눔(#26/#6) — 기본은 홈 레지스트리, 테스트는 주입.
        self.pool_registry = (
            pool_registry if pool_registry is not None else default_pool_registry()
        )
        # 직전 필터 슬롯·소스 키(결정 28)는 **컨트롤러 수명** — 세션(「새 기안」)이 죽어도
        # 직전 "정의"의 연속성은 남는다. filter 는 _fresh_session 의 스태시 판정이 첫
        # 호출에서도 안전하게 미리 눕힌다.
        self._last_filter = None
        self._data_key = ""
        self.filter = None
        # 복사 후 전진 옵션(결정 16, 기본 꺼짐) — 컨트롤러 수명(세션 「새 기안」을 넘어 유지,
        # 워드프로세서 토글 멘탈 모델). 넘어가기 = 사용자의 사실상 붙여넣기 서명이라 opt-in.
        self._advance_after = False
        # 대상 글꼴 선언(결정 17) — **전역 영속**(설정 파일)이라 컨트롤러보다 오래 살고,
        # 두 기안 표면이 **같은 실체**를 본다(앱이 주입; 미주입=독립 인스턴스라 테스트·
        # 단독 구동은 종전 그대로). 배치는 큐 상단 드롭다운이지만 스코프는 앱 전역.
        self._font = target_font if target_font is not None else TargetFontSetting()
        # 전각 정렬 치환(결정 17 린트 처방) — **세션 렌더 옵션**. 템플릿 원본은 건드리지 않고
        # (이름 있는 템플릿이 조용히 「이름 없는 세션 템플릿」으로 강등되지 않게) 렌더 단계에서만
        # 적용한다. 카드와 클립보드가 같은 변환을 통과하므로 되읽기가 곧 검증이다.
        self._fullwidth = False
        # 직전 복사 확정(스냅샷 구동 완료 노트) — 복사가 세팅, 어떤 동작이든 무효화(결정 16).
        self._last_copy: "dict | None" = None
        # 빈칸 지도 캐시(리뷰 F6) — (records 정체, 템플릿) 키. 데이터/템플릿 불변이면 재계산 안 함.
        self._gap_cache: "dict[int, bool]" = {}
        self._gap_cache_key: "tuple | None" = None
        self._fresh_session()

    def _fresh_session(self) -> None:
        """기안 세션 초기 상태 — VM 재구성 + 첫 템플릿 자동 선택 + 데이터 라벨 소거.

        생성자와 「새 기안」(F11)이 같은 경로를 탄다 — 두 초기 상태가 갈라지지 않게.
        죽는 세션의 활성 필터 정의는 직전 슬롯으로 넘긴다(결정 28 — 슬롯은 세션보다
        오래 산다). 선택·큐·필터 자체는 세션 휘발(결정 8·24)이라 세션과 함께 죽는다.
        """
        self._stash_filter()  # 옛 소스 키 기준 — 키 소거 전에
        self.vm = TxtDraftViewModel(self._registry)
        self.data_label = ""  # 겨눈 데이터 파일 표시명(서버 소유 — run 과 정렬, P4)
        self.data_source = ""  # 소스 종류 플래그('file'|'pool') — 병기 라벨은 스냅샷이 합성(K8)
        self._data_key = ""
        # 데이터 존(슬라이스 6) — 레코드 정체 = 세션 내 인덱스(SelectionModel 키를 큐가 재사용).
        self.selection = SelectionModel(0)
        self.queue = TxtQueueModel(self.selection)
        self.filter = None
        # 전각 치환은 그 원문에 대한 판단이라 세션과 함께 죽는다(대상 글꼴 선언은 전역 영속이라
        # 살아남는 것과 대비 — 선언은 사용자의 환경 사실, 치환은 이번 원문의 조치).
        self._fullwidth = False
        names = self.vm.template_names()
        if names:
            self.vm.select_template(names[0])

    def _records(self) -> list:
        return self.vm.records

    # ------------------------------------------------------------- 관측 푸시
    def _push(self) -> None:
        self._push_sink(self.name, self.snapshot())

    def _session_snapshot(self) -> dict:
        """세션 4존이 소비하는 스냅샷 조각 — 소비자가 자기 키와 병합한다.

        구 화면은 이것이 스냅샷의 전부이고, 「기안」 화면은 좌 목록 키를 앞에 얹는다.
        """
        vm = self.vm
        n = vm.record_count()
        records = self._records()
        fields = template_fields(vm.template_text)
        # 데이터 존(블록 3·4) — 선두 「큐」 열 소재 = 큐 표지(대기·복사됨·작업점).
        # 큐 조회는 **1회 O(n) 선계산** 후 O(1) 로 본다(PR-2b 리뷰: position_of·is_copied 는
        # 각각 리스트 스캔이라 행마다 부르면 매 push 가 O(n²) — 대형 코퍼스에서 타건마다 지연).
        indices = self.selection.selected_indices()
        qpos_of = {idx: k + 1 for k, idx in enumerate(self.queue.uncopied())}
        copied_set = set(self.queue.copied_tail())
        current = self.queue.current

        def lead_for(i: int) -> dict:
            return {
                "index": i,
                "selected": self.selection.is_selected(i),
                # 미처리 큐 순번 — 표면은 이 수를 **행 표에 렌더하지 않는다**(큐-꼬리 순서라
                # 레코드 순서 표에서 비단조로 읽힌다, PR-2b 리뷰). 큐 순서로 그리는 상태
                # 색인·작업점 카드(PR-3)가 소비할 링1 진실이라 스냅샷엔 싣는다.
                "qpos": qpos_of.get(i),
                "copied": i in copied_set,
                "current": current == i,
            }

        filter_snap, table_snap, _view, _visible = self._zone_sections(indices, lead_for)

        # 작업점 카드(결정 16) — 큐가 지나가는 한 장. 렌더는 링1 render_segments(채움 표지
        # 삼분, 결정 22)를 소비한다: 웹은 토큰 정규식을 재구현하지 않는다(파생경계 번역오류
        # 상류 차단, PR-1 예고).
        # 프리뷰 레코드(리뷰 F1): 작업점이 있으면 그 행, 없어도 **데이터가 있으면 행 0 을
        # 미리 보여준다**(자유 커서 시절 거동 복원). 선택 0(전체 해제)에서 빈 레코드로 그리면
        # `_field_state` 가 실재하는 열까지 전부 '항목 없음'(missing)으로 칠해 **거짓 경보**를
        # 낸다(confirm-or-alarm 정면 위반). 복사 게이트는 프리뷰가 아니라 `has_current` 가 진다.
        preview_idx = current if (current is not None and 0 <= current < n) else (0 if n else None)
        card_rec = records[preview_idx] if preview_idx is not None else {}
        segments, card_report = render_segments(vm.template_text, card_rec)
        # 정렬 린트 술어는 **치환 전 원문** 기준(결정 17) — 치환하면 런이 사라지므로 원문
        # 기준으로 보아야 "적용됨 · 되돌리기" 상태에서도 무엇을 고쳤는지 정직하게 말한다.
        space_run = segments_have_space_run(segments)
        proportional = is_proportional_font(self._font.value)
        segments = self._aligned(segments)

        # 빈칸 지도(has_gap)는 레코드 값+템플릿에만 의존(선택·작업점 무관) — 네비게이션·필터
        # 타건마다 O(행×필드)로 재계산하지 않게 (records 정체, 템플릿) 키로 캐시한다(리뷰 F6:
        # 매 push 재구축이 PR-2b 가 세운 O(1) 을 무너뜨림). 데이터 교체·템플릿 변경 시 무효화.
        gap_key = (id(records), vm.template_text)
        if self._gap_cache_key != gap_key:
            self._gap_cache = {}
            self._gap_cache_key = gap_key
        gap_cache = self._gap_cache

        def _has_gap(i: int) -> bool:  # 미충족(항목 없음·빈 값) 카드 판정, 인덱스별 1회 상각
            if i not in gap_cache:
                rec = records[i]
                gap_cache[i] = any(
                    name not in rec or ("" if rec[name] is None else str(rec[name])).strip() == ""
                    for name in fields
                )
            return gap_cache[i]

        index_map = [
            {
                "index": i,
                "state": "current" if i == current else ("copied" if i in copied_set else "uncopied"),
                "has_gap": _has_gap(i) if 0 <= i < n else False,
            }
            for i in self.queue.display_order()
        ]
        # 토큰 상태 = **링1 render_segments 리포트에서 파생**(리뷰 F4) — 같은 카드를 두 번 걷지
        # 않는다(_field_state 재유도 폐기). 카드 렌더(음영/〈빈 값〉/빨강)와 토큰 배지가 한 출처.
        missing_set, empty_set = set(card_report.missing_fields), set(card_report.empty_fields)
        tokens = [
            {
                "name": name,
                "state": "missing" if name in missing_set else ("blank" if name in empty_set else "fill"),
            }
            for name in fields
        ]
        card = {
            "index": current,
            "has_current": current is not None,
            "is_copied": current in copied_set if current is not None else False,
            "position": self.queue.position_of(current) if current is not None else None,
            "uncopied_count": len(self.queue.uncopied()),
            "copied_count": self.queue.copied_count(),
            "selected_count": self.selection.selected_count(),
            "is_complete": self.queue.is_complete(),
            "advance_after": self._advance_after,
            "segments": [{"text": s.text, "kind": s.kind, "name": s.name} for s in segments],
            "missing_fields": card_report.missing_fields,
            "empty_fields": card_report.empty_fields,
            "index_map": index_map,
            # 선언-조건부 정렬 린트(결정 17) — 표면은 **판정하지 않는다**(글꼴 이름으로
            # 비례폭을 재판별하거나 정규식을 다시 걷지 않는다, 파생경계 번역오류 차단).
            # active = 경보/확인 줄을 세울지. **치환이 걸려 있으면 선언 글꼴과 무관하게 선다**
            # (리뷰 F1): 고정폭으로 되돌린 뒤 줄이 사라지면 전각이 계속 클립보드로 나가는데
            # 사용자는 통보도 되돌릴 손잡이도 잃는다 — 조용한 변환 금지. 경보(치환 전)만
            # 선언-조건부다(고정폭에서 연속 공백은 정당한 저작이라 경보하면 소음).
            "lint": {
                "proportional": proportional,
                "space_run": space_run,
                "applied": self._fullwidth,
                "active": self._fullwidth or (proportional and space_run),
            },
            # 직전 복사 확정(결정 16 복사=완료) — **스냅샷 구동**이라 announce 순서 경합이 없다:
            # 노트가 카드와 같은 push 로 오고(어긋남 불가), 복사한 행을 명시(전진 시 카드는 다음
            # 행이라 행 번호로 어느 카드가 복사됐는지 못박는다). 어떤 동작이든(dispatch·데이터
            # 교체) 무효화 → 걷힌다(리뷰: 매 push 무조건 sticky 면 완료 노트가 다른 카드와 모순).
            "last_copy": self._last_copy,
        }
        return {
            "template_name": vm.template_name or "(붙여넣은 텍스트)",
            "template_text": vm.template_text,
            "tokens": tokens,
            "record_count": n,
            # 미충족 리포트는 **card 단일 출처**(리뷰 F9: 최상위 트윈은 조용한 desync 위험) —
            # 상태 배지(setStatus)·카드 판독·완료 노트 모두 card.missing_fields/empty_fields 소비.
            # render_text 이중 방출도 폐기(리뷰 F8): 카드 평문은 card.segments 로 재구성한다.
            "data_label": self.data_label,  # 서버 소유(P4) — 붙여넣기/템플릿 전환에도 실상태 반영
            # 소스 종류 병기 라벨(#26) — 저장 상태가 아니라 플래그에서 매번 합성(K8).
            "data_source_label": source_label(self.data_source, self.data_label),
            # 데이터 존 계약(datazone.js 소비 키) — 작업 화면과 같은 모양.
            # ``data_key`` = 소스 **정체**(경로 정규화·시트/참조 병기) — 표시 라벨은
            # basename 이라 `folder1/명단.xlsx`↔`folder2/명단.xlsx` 가 같은 문자열이 된다.
            # 표면의 세션 리셋(Shift 앵커·디바운스·고지)은 이 키에 겨눠야 동명 전환에서
            # stale 앵커로 엉뚱한 범위가 조용히 선택되지 않는다(PR-2b 리뷰).
            "data_key": self._data_key,
            "has_data": vm.datasource is not None,
            "selected_count": self.selection.selected_count(),
            # 대상 글꼴 선언(결정 17) — 카드가 아니라 최상위: 값의 스코프가 전역 영속이라
            # 카드/세션과 수명이 다르다(카드에 실으면 세션 값처럼 읽힌다).
            "target_font": self._font.value,
            "filter": filter_snap,
            "table": table_snap,
            "card": card,
        }

    # ------------------------------------------------------- 웹→Python 데이터 액션
    def dispatch(self, action: str, payload: dict):
        """순수 데이터 액션(창 불필요) 라우팅 후 푸시. 미지 액션은 시끄럽게 거부(P5).

        액션 후 큐 재봉합(:meth:`TxtQueueModel.reconcile`) — 선택·필터 변이가 큐 지형을
        바꾼다(``copied ⊆ selected`` 자가복구, 블록 3). reconcile 은 멱등이라 액션별 분기
        없이 공통 후처리로 둔다. 무변이 질의(``is_query`` — filter_panel)는 push 를
        생략한다(작업 화면 규약 승계 — 패널 여는 중 동일 스냅샷 재렌더 낭비 제거).
        **확인 왕복**(``needs_confirm``)도 변이가 없었으므로 push 를 생략한다 — 「기안」
        화면의 목록 액션(삭제·그룹 병합)이 이 규약을 쓴다(RC-02 동형).
        """
        handler = getattr(self, f"_do_{action}", None)
        if handler is None:  # confirm-or-alarm: 조용한 무시 금지.
            raise ValueError(f"알 수 없는 {self._action_label} 액션: {action!r}")
        result = handler(payload)
        self.queue.reconcile()
        if getattr(handler, "is_query", False):
            return result
        if isinstance(result, dict) and result.get("needs_confirm"):
            return result
        # 변이 동작(네비게이션·템플릿·선택)은 직전 복사 확정을 무효화한다 — 카드가 바뀌므로
        # 완료 노트가 다른 카드와 모순되지 않게(리뷰 F1). 무변이 질의는 재렌더가 없어 불건드림.
        self._last_copy = None
        self._push()
        return result

    def _do_select_template(self, p: dict) -> None:
        self.vm.select_template(p["name"])
        self._fullwidth = False  # 치환은 그 원문에 대한 판단 — 원문이 바뀌면 함께 죽는다(리뷰 F2)

    def _do_new_draft(self, p: dict) -> None:
        """홈 「＋ 새 기안」 — 세션 원자 초기화(F11, F10 「새 작업」과 대칭 문법).

        종전 bare nav 는 직전 기안의 템플릿 선택·붙여넣은 텍스트·데이터·레코드 위치를
        그대로 남겨 라벨 '새'와 어긋났다.

        **면제 철회(#126)**: 원장 F11 의 무확인 근거는 "txt 출력은 일회성이라 버릴 durable
        상태가 없다"였는데, 블록 3 전-선언 큐가 신설되면서 거짓이 됐다. 큐의 복사 진행은
        durable 은 아니어도 **복구 불가**다 — 어디까지 붙여넣었는지는 앱 밖 기억이다. 이제
        이 전이도 T3 술어(:meth:`_guard_state`)를 지나며, 확인은 제스처를 소유한 표면
        (``TxtScreen.confirmNewDraftIfArmed``)이 큐 진행을 재진술해 받는다. 결정 32 가 빠른
        기안에서 같은 F11 전제를 이미 부분 개정했다(수기 폼 신설로 버릴 상태가 생김).
        """
        self._fresh_session()

    def _do_copy_precheck(self, p: dict) -> dict:
        """복사 전 빈칸 게이트 질의(결정 16 · 부록 A-3-28) — 클립보드로 나갈 카드의 결손 보고.

        게이트를 **복사 앞**에 세우기 위한 질의다: 종전에는 :meth:`can_copy`(작업점 실재)만
        보고 곧바로 클립보드에 쓴 뒤 결손을 사후 노트로 알렸다. 그러면 미해소 ``{{토큰}}`` 이
        확인 없이 나가고, 사용자는 온나라 기안작성기에 붙여넣은 **다음에야** 안다.

        판정은 여기서 지금 한다(JS 는 문안만) — 복사와 같은 :meth:`render` 통로를 타므로
        게이트가 본 집합과 실제 나가는 텍스트가 갈라지지 않는다. 완화 조항(결정 31)은
        "틀리면 보이는 추측(표현형)"에만 적용되고 미해소 토큰은 **그럴싸한 오류** 쪽이라
        엄격 유지가 같은 결정의 명문이다.
        """
        if not self.can_copy():
            return {"can_copy": False, "row": None, "missing_fields": [], "empty_fields": []}
        _text, report = self.render()
        return {
            "can_copy": True,
            "row": self.queue.current,
            "missing_fields": list(report.missing_fields),
            "empty_fields": list(report.empty_fields),
        }

    _do_copy_precheck.is_query = True  # 무변이 질의 — dispatch 가 push 를 생략한다

    def _do_set_template_text(self, p: dict) -> None:
        self.vm.set_template_text(p["text"])
        self._fullwidth = False  # 붙여넣은 새 원문에 옛 치환 결정이 승계되지 않는다(리뷰 F2)

    def _do_step(self, p: dict) -> None:
        """작업점을 큐 표시 순서로 이동(↓/↑, 경계 멈춤) — 자유 레코드 커서가 아니라 큐 판(결정 16)."""
        self.queue.step(int(p["delta"]))

    def _do_set_current(self, p: dict) -> None:
        """상태 색인 점 클릭 = 작업점 직접 지정(큐 밖 인덱스는 큐 모델이 정규화로 되돌린다)."""
        idx = p.get("index")
        self.queue.set_current(int(idx) if idx is not None else None)

    def _do_defer(self, p: dict) -> None:
        """미루기(결정 19) — 막힌 미처리 카드를 큐 뒤로. index 없으면 작업점(막힌 카드 탈출구)."""
        idx = p.get("index")
        self.queue.defer(int(idx) if idx is not None else None)

    def _do_toggle_advance(self, p: dict) -> None:
        """복사 후 전진 옵션(결정 16, 기본 꺼짐) — 컨트롤러 수명(세션 넘어 유지)."""
        self._advance_after = bool(p["value"])

    def _do_set_target_font(self, p: dict) -> None:
        """대상 글꼴 선언(결정 17) — 열거형 밖 값은 조용히 무시하지 않고 시끄럽게 거부한다.

        검증·저장 순서 계약은 :class:`TargetFontSetting` 단일 실체가 진다 — 값이 앱 전역이라
        여기서 컨트롤러 사본을 갱신하면 **다른 기안 표면이 옛 선언으로 판정한다**(리뷰 P2).
        """
        self._font.set(p["font"])

    def _do_set_fullwidth(self, p: dict) -> None:
        """전각 정렬 치환 적용/해제(결정 17 린트 처방) — 세션 렌더 옵션, 템플릿 원본 불변."""
        self._fullwidth = bool(p["value"])

    # ------------------------------------------------- 세션 가드(T3, 블록 4 결정 26·27)
    def _guard_state(self) -> dict:
        """무장 판정 = 선택 성분(공유 술어) ∨ **큐 부분 진행**(T3) — 데이터 교체가 소비한다.

        T3 성분: ``0 < 복사 < 선택``. 큐를 절반 걷다 데이터를 갈아치우면 처리 표지가 통째로
        증발하는데(새 데이터 = 새 큐), 어디까지 붙여넣었는지는 앱 밖 기억이라 복구 불가다.
        완주(``복사 == 선택``)는 완료 이벤트라 무장 해제 — 선택 성분에도 완주 집합을
        ``settled`` 로 넘겨 "다 복사한 선택"이 수작업으로 재고발되지 않게 한다.

        소비처는 **둘**이다: 데이터 재겨눔(원 T3)과 「＋ 새 기안」(#126 — 면제 철회, 근거
        상세는 :meth:`_do_new_draft`). 템플릿 교체는 여전히 가드 대상이 아니다 — 큐를 죽이지
        않으므로 잃을 진행이 없다.
        """
        copied, selected = self.queue.copied_count(), self.selection.selected_count()
        complete = self.queue.is_complete() and selected > 0
        settled = set(self.selection.selected_indices()) if complete else set()
        g = self._selection_guard(settled=settled)
        queue_partial = 0 < copied < selected
        g["copied_count"] = copied
        g["queue_partial"] = queue_partial
        g["armed"] = g["armed"] or queue_partial
        return g

    def _do_guard_state(self, p: dict) -> dict:
        """무장 상태 실시간 질의 — 표면의 데이터 재겨눔 사전 확인이 소비(작업 화면과 동형).

        스냅샷 캐시가 아니라 지금 Python 이 판정한다(왕복 지연·무푸시 경로의 stale 오판 차단).
        """
        return self._guard_state()

    _do_guard_state.is_query = True  # 무변이 질의 — dispatch 가 push 를 생략한다

    # 등록 데이터(풀) 겨눔(#26/#6)은 PoolTargetingMixin 공용 래퍼(K4) — 화면별 후처리는
    # _after_pool_load(데이터 존 리셋)가 진다.
    def _after_pool_load(self, records: list) -> None:
        """풀 겨눔도 파일과 동일 리셋 — 전체 선택·새 큐·필터 재생성(작업 화면과 동형)."""
        self._stash_filter()  # 죽는 세션의 정의 → 슬롯(옛 소스 키 기준 — 키 갱신 전에)
        self._data_key = self._pool_key()  # 라벨은 공용 래퍼가 이미 세팅
        self.selection = SelectionModel(len(records))  # 데이터 변경 → 전체 선택 초기화
        self.queue = TxtQueueModel(self.selection)     # 큐 = 세션 휘발 — 새 데이터 = 새 큐
        self._install_filter(records, {})  # txt 는 매핑 힌트 없음 — 값 스니핑만(결정 24)

    # ------------------------------------------------ 네이티브 보조(브리지가 다이얼로그 담당)
    def load_data_path(self, path: str, *, sheet: "str | None" = None) -> None:
        """선택된 파일 경로를 링1 VM 으로 로드(레코드 0건이면 시끄럽게 실패·상태 불변).

        ``sheet`` = 웹에서 확정한 시트명(다중 시트 확정 게이트 #33, None=CSV·단일 시트)."""
        records = self.vm.load_data(path, sheet=sheet)
        if not records:
            raise ValueError(NO_ROWS_TEXT)  # 표류 변형('상태를…')도 단일 출처로 수렴(R-copy)
        self._stash_filter()  # 죽는 세션의 정의 → 직전 필터 슬롯(결정 28, 옛 소스 키 기준)
        self.data_label = Path(path).name  # 서버 소유(P4)
        self.data_source = "file"  # 병기 라벨은 스냅샷이 합성(#26·K8)
        self._data_key = self._file_key(path, sheet)  # 소스 일치 게이트(결정 28)
        self.selection = SelectionModel(len(records))  # 데이터 변경 → 전체 선택 초기화
        self.queue = TxtQueueModel(self.selection)     # 큐 = 세션 휘발 — 새 데이터 = 새 큐
        self._last_copy = None  # 새 데이터 = 직전 복사 확정 무효(네이티브 경로라 dispatch 미경유)
        self._install_filter(records, {})  # txt 는 매핑 힌트 없음 — 값 스니핑만(결정 24)
        self._push()

    def render(self) -> "tuple[str, RenderReport]":
        """작업점 카드(``queue.current``)의 렌더 텍스트+리포트 — 복사 완료가 소비한다(결정 16).

        자유 레코드 커서가 아니라 큐 작업점을 렌더한다(``vm.record_index`` 비의존 — 카드가
        진실). 작업점이 없으면 빈 레코드(전 토큰 미충족)라 표면이 복사를 게이트하지만,
        방어적으로 시끄러운 리포트를 낸다(confirm-or-alarm: 크래시 아닌 경보).
        """
        cur = self.queue.current
        records = self._records()
        rec = records[cur] if (cur is not None and 0 <= cur < len(records)) else {}
        # 클립보드 텍스트 = **카드와 같은 변환의 결과**(결정 17 치환의 계약): 세그먼트를
        # 이어붙여 만든다. render_record 를 그냥 부르면 치환이 카드에만 걸려 "보이는 것과
        # 복사되는 것"이 갈라진다 — 세그먼트 경로 하나로 묶어 그 어긋남을 구조적으로 없앤다.
        segments, report = render_segments(self.vm.template_text, rec)
        return "".join(s.text for s in self._aligned(segments)), report

    def _aligned(self, segments: list) -> list:
        """전각 치환 적용(세션 옵션이 켜졌을 때만) — 카드 렌더·클립보드 공용 통로."""
        return align_segments(segments) if self._fullwidth else segments

    def can_copy(self) -> bool:
        """복사 가능 = 작업점 실재(리뷰 F3) — 브리지가 이걸로 게이트해 작업점 없을 때 빈 템플릿
        (생 ``{{토큰}}``)이 클립보드로 조용히 나가는 것을 막는다(버튼 비활성과의 레이스·직접 호출)."""
        return self.queue.current is not None

    def note_copied(self, report: "RenderReport") -> None:
        """복사 완료 후 큐 갱신 — 작업점을 처리 후미로(멱등), 전진 opt-in, 재봉합·푸시(결정 16).

        복사=완료(결정 28)의 큐 판: 클립보드 쓰기(app.py 브리지)에 이어 상태를 전진시킨다.
        작업점을 복사해도 작업점은 그 카드에 머문다(조용한 이동 금지) — 전진은 ``_advance_after``
        가 켜졌을 때만 다음 미처리로. 작업점이 없으면(게이트가 막았어야) 무동작.

        ``report`` = 브리지가 클립보드용으로 이미 렌더한 그 카드의 리포트(재렌더 없이 재사용) —
        복사한 **행 번호**와 함께 ``_last_copy`` 에 담아 스냅샷 구동 완료 노트로 낸다(announce
        순서 경합·전진 시 카드 desync 차단, 리뷰 F1·F2)."""
        cur = self.queue.current
        if cur is None:
            return
        # 복사한 카드(전진 전 작업점)를 못박아 완료 노트에 실린다 — 전진해도 어느 행인지 명시.
        self._last_copy = {
            "row": cur,
            "missing_fields": list(report.missing_fields),
            "empty_fields": list(report.empty_fields),
        }
        self.queue.copy(cur)
        if self._advance_after:
            self.queue.advance_to_next_uncopied()
        self.queue.reconcile()  # copied ⊆ selected 불변식 유지(멱등)
        self._push()
