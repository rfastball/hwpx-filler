"""기안 세션(txt) 공용 본체 — 「기안」 화면의 세션 기계. #148 슬라이스 3a.

R-info 3부 결정 1·5·7 의 합병은 **하나의 세션 기계**라는 뜻이다. 이 모듈은 구 「기안문 채우기」
(``screen_txt.TxtController``, #148 슬라이스 6 삭제)가 혼자 갖고 있던 세션 본체(템플릿 원문 ·
데이터 존 · 큐 · 작업점 카드 · 대상 글꼴 · 정렬 린트 · T3 가드 · 클립보드 렌더)를 **무변화로**
끌어올린 것이다 — 「기안」 화면이 400줄 사본을 새로 짓지 않게(#94 가 남긴 교훈: 한시적
중복은 한시적이지 않다). 슬라이스 3a~5 에선 신·구 두 표면이 잠시 공존하며 같은 이 믹스인을
봐 드리프트가 생길 자리가 없었고, 슬라이스 6 에서 구 화면이 흡수·삭제돼 소비자는 하나가 됐다.

소비자:

- :class:`~hwpxfiller.webapp.screen_draft.DraftController` — 「기안」 화면. 좌 목록(master)에
  세션(detail)을 얹는다. 스냅샷은 목록 키 + :meth:`DraftSessionMixin._session_snapshot`
  병합이고 디스패치는 두 계열의 ``_do_*`` 가 한 라우터를 공유한다(MRO).

**스코프 경계**: 여기 있는 것은 **휘발 세션**뿐이다. 맞추기 표 그릇(유형·확정 열·확정-비움
의미론)은 슬라이스 4 가 얹었다(늘 켜짐). 저장된 기안 작업의 복원·지속성 스위치 5종(유래로
그릇을 켜고 끔)·「기안으로 저장」 승격은 슬라이스 5 몫이다 — 없는 걸 있는 척하지 않는다.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..core.format_engine import presets as format_presets
from ..core.mapping import TYPES
from ..core.text_render import (
    RenderReport,
    align_segments,
    render_segments,
    segments_have_space_run,
    template_fields,
)
from ..core.text_registry import TextTemplateRegistry
from ..gui.filter_state import sniff_column_kinds
from ..gui.mapping_state import MappingModel
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


# 표시형 프리셋(유형별) — 에디터·빠른 기안과 **같은 표**(format_engine)에서 뽑는다. 승격 시
# 매핑 행 fmt 로 그대로 이관되려면 세 표면이 같은 어휘를 써야 한다(결정 31 프리셋 키 = 매핑 1:1).
_FMT_OPTIONS = {
    t: [{"code": code, "label": label} for label, code in format_presets(t)] for t in TYPES
}

# 유형 열 선택지(#148 슬라이스 4, 결정 12) — **값-운반 유형**(text/date/amount)만. ``const``
# 는 유형이 아니라 「직접 입력」의 결과(수기 값)라 목록에 두지 않는다(값이 빈 상수 = 확정-비움,
# 결정 14). 라벨은 에디터 위저드(TYPE_LABEL)와 같은 어휘 — 두 표면이 유형을 달리 부르지 않게.
_TYPE_LABEL = {"text": "텍스트", "date": "날짜", "amount": "금액"}
_TYPE_OPTIONS = [{"code": t, "label": _TYPE_LABEL[t]} for t in ("text", "date", "amount")]


def _row_own(row) -> str:
    """맞추기 행의 소유권 색(#148 슬라이스 3b) — 값이 어디서 오는지.

    ``man``: 상수(직접 입력한 값 — 전 행 공통) · ``auto``: 결속 열(행마다 데이터 값) ·
    ``""``: 무결속·무값(토큰이 {{}} 로 남는 자리). hand(결속인데 고쳐 씀)는 큐에서 존치하지
    않는다 — 값을 고치면 상수로 강등되므로 색은 곧 man 이다(사용자 결정)."""
    if row.type == "const":
        return "man"
    if row.source:
        return "auto"
    return ""


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
    ``{{토큰}}`` · 〈빈 값〉)은 링2 대체라 웹(js/screens/draft.js)에서 만든다 — VM
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
        # 이 세션에서 복사가 한 번이라도 있었나(내구, 리뷰 5b 3R P2 / 682) — 무데이터 가상 1건
        # 복사는 큐(copied_count)에 안 잡혀(note_copied 가 큐를 안 늘림) _last_copy 만 남기는데,
        # 그건 다음 동작이 지운다. 「사본으로 편집」의 "이미 복사한 N건은 이전 문안" 경고가 가상
        # 복사도 인정하고 **정확한 건수**를 말하도록, 복사 조작마다 +1 되는 **내구 단조 카운터**를
        # 둔다(리뷰 5b 4R P2 / 685): copied_count(큐)는 선택 해제·데이터 교체 시 reconcile 로
        # 줄어들어 이미 붙여넣은 문서 수를 못 센다. 세션 baseline(새 세션·복원)에서만 0으로 리셋.
        self._copied_total: int = 0
        # 빈칸 지도 캐시(리뷰 F6) — (records 정체, 템플릿) 키. 데이터/템플릿 불변이면 재계산 안 함.
        self._gap_cache: "dict[int, bool]" = {}
        self._gap_cache_key: "tuple | None" = None
        # 세션 유래(#148 슬라이스 5a) — 저장 기안 결속 여부. ``_bound_job`` 비면 휘발 모드(그릇
        # 열 숨김·원문 편집 가능), 차면 저장 모드(유형·확정 열·원문 읽기 전용). **단일 실체**:
        # 스냅샷 mode·source_readonly 도, 컨트롤러 목록 선택(has_job)도 이 한 필드에서 유도한다
        # (같은 사실을 두 번 선언하면 갈라진다 — 이 저장소 지배 결함류). 유래는 목록을 가진
        # DraftController 만 세운다(_do_select_job → _restore_from_job); 구 화면은 늘 휘발.
        self._bound_job = ""
        self._source_readonly = False
        # 원문 수정 표지(#148 슬라이스 5b) — 원문이 라이브러리 정의에서 갈라졌는가(사본으로
        # 편집·원문 라이브 편집). 깨끗한 라이브러리 픽·복원·붙여넣기는 False. modBadge(수정됨)
        # 의 단일 출처 — 표면이 "원문≠라이브러리"를 정직하게 말한다(문안≠상태 차단).
        self._source_dirty = False
        # 현 원문의 라이브러리/Job 파일 경로(#148 슬라이스 5c) — 「기안으로 저장」이 Job.template_path
        # 로 쓴다. 라이브러리 픽·복원은 실경로, 붙여넣기는 "". 매 스냅샷 재해석(I/O)을 피해 필드로
        # 든다(TargetFontSetting 과 같은 규율 — 타건마다 파일 스캔 금지). 수정된 원문(_source_dirty)
        # 은 파일과 어긋나므로 저장 자격이 없다(먼저 「템플릿으로 저장」, 결정 = 라이브러리 배접만).
        self._template_path = ""
        # 휘발 세션 스태시(두 세션 병존) — 저장 기안을 고르면 붙여넣던 세션을 여기 얼려 두고,
        # 「이번 세션」으로 돌아오면 되살린다(소실 0). 저장-세션은 Job 에서 결정적으로 재구성
        # 되므로(Job 은 데이터/행 미저장) 스태시가 필요한 건 휘발 하나뿐이다.
        self._volatile_stash: "dict | None" = None
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
        # 새 기안 = 휘발(유래 소거) — 저장 결속·읽기 전용을 함께 푼다. 스태시는 건드리지
        # 않는다(저장 기안에서 「이번 세션」으로 돌아올 슬롯이라 새 기안과 수명이 다르다).
        self._bound_job = ""
        self._source_readonly = False
        self._source_dirty = False  # 갓 선택한 첫 템플릿 = 깨끗한 라이브러리 정의
        # 미저장 레시피 편집 표지(리뷰 5a 3R P1 / 147) — 사람이 소스·상수·확정·유형을 손대면
        # True. 세션-교체(전환·귀환·삭제·포크) 앞 가드가 이걸 무장으로 친다(:meth:`_leave_guard`).
        # 갓 세운 세션·복원 직후는 사람 편집 전이라 깨끗하다(리셋). 자동 골격(_rebuild_mapping)은
        # 시스템 소유라 이 표지를 올리지 않는다(그 경로는 _do_* 핸들러를 안 탄다).
        self._map_dirty = False
        self._copied_total = 0  # 새 세션 = 복사 이력 없음(682·685)
        self._editing_fingerprint = ""  # 휘발 = 결속 작업 없음 → 드리프트 판정 대상 아님(212)
        names = self.vm.template_names()
        if names:
            self.vm.select_template(names[0])
            self._template_path = self._resolve_template_path(names[0])
        else:
            self._template_path = ""  # 라이브러리 비었음 = 저장할 배접 없음
        self._rebuild_mapping()  # 첫 템플릿의 맞추기 골격(정확 자동 결속·이름 유형)

    def _resolve_template_path(self, name: str) -> str:
        """라이브러리 템플릿 이름 → 실경로 문자열(없으면 "") — 저장 자격의 template_path 원천."""
        t = self._registry.load(name)
        return str(t.path) if t.path.exists() else ""

    # ------------------------------------------------ 세션 유래 전이(#148 슬라이스 5a)
    # 휘발 세션과 함께 스태시/복원되는 세션-스코프 속성. 컨트롤러 수명(_advance_after·_font·
    # _last_filter·pool_registry·_registry)은 두 세션을 관통하므로 여기 없다(스태시 대상 아님).
    _SESSION_ATTRS = (
        "vm", "data_label", "data_source", "_data_key", "selection", "queue",
        "filter", "mapping", "_fullwidth", "_last_copy", "_gap_cache", "_gap_cache_key",
        "_source_dirty",   # 사본/편집 여부는 그 원문에 붙는다 — 스태시·복원과 함께 이동(슬라이스 5b)
        "_template_path",  # 원문의 파일 경로도 그 세션에 붙는다(슬라이스 5c 저장 자격)
        "_map_dirty",      # 미저장 레시피 편집 표지도 그 세션에 붙는다 — 스태시·복원과 함께 이동(147)
        "_copied_total",   # 복사 이력 카운터도 그 세션에 붙는다 — 스태시·복원과 함께 이동(682·685)
        "_editing_fingerprint",  # 로드 시점 내용 지문도 그 세션에 붙는다(212 드리프트 판정)
    )

    def _stash_volatile(self) -> None:
        """붙여넣던 휘발 세션을 얼려 둔다 — 저장 기안 선택 직전(두 세션 병존, 소실 0).

        세션-스코프 객체 **참조**를 담는다: 이어지는 :meth:`_restore_from_job` 이 ``self.vm`` ·
        ``self.mapping`` 등을 새 객체로 **교체**하므로 얼려 둔 참조는 변이되지 않는다(휘발
        세션이 그대로 산다). 매 「휘발→저장」 진입마다 최신 휘발 상태로 덮어써, 떠나던 순간이
        정확히 보존된다."""
        self._volatile_stash = {a: getattr(self, a) for a in self._SESSION_ATTRS}

    def _stash_guard(self) -> "dict | None":
        """얼려 둔 휘발 세션의 무장 상태 — 포크가 그것을 밀어내기 전에 소실을 판정한다(리뷰 5b 2R P1).

        단일 슬롯 모델: 포크(:meth:`_do_fork_to_volatile`)는 현 저장 세션을 유일 휘발로 만들어
        스태시해 둔 붙여넣기 세션을 대체한다. 그 세션에 복구 불가 진행(T3: 선택·큐 부분 복사)이
        있으면 조용히 버리지 않고 재진술한다. 스태시 객체를 잠시 결속해 공용 :meth:`_leave_guard`
        로 **같은 술어**를 재평가한다(선택·큐 ∨ 미저장 레시피 편집 — 세션 교체와 같은 문턱, 147;
        컨트롤러 상태를 복붙 판정하지 않아 드리프트 0). 스태시가 없거나(포크 대상 저장 세션 전
        휘발 미스태시) 무장 아니면(재현 가능 — 붙여넣기 텍스트만은 복구 가능) ``None``."""
        if self._volatile_stash is None:
            return None
        live = {a: getattr(self, a) for a in self._SESSION_ATTRS}
        try:
            for attr, val in self._volatile_stash.items():
                setattr(self, attr, val)
            g = self._leave_guard()  # 선택·큐 ∨ 미저장 레시피 편집(147) — 세션 교체 문턱
        finally:  # 판정은 순수 읽기 — 무슨 일이 있어도 현 세션 객체를 되돌린다.
            for attr, val in live.items():
                setattr(self, attr, val)
        return g if g["armed"] else None

    def _restore_volatile(self) -> None:
        """「이번 세션」 귀환 — 얼려 둔 휘발 세션 복원 + 유래 소거. 스태시가 없으면(승격 직후
        등) 새 휘발 세션으로 낙착한다(빈 슬롯 = 갓 시작하는 휘발이 참이다)."""
        if self._volatile_stash is None:
            self._fresh_session()  # bound/readonly 도 여기서 소거
            return
        for attr, val in self._volatile_stash.items():
            setattr(self, attr, val)
        self._bound_job = ""
        self._source_readonly = False

    def _restore_from_job(self, job) -> None:
        """저장 기안(:class:`~hwpxfiller.core.job.Job`)을 세션으로 되살린다 — 저장 모드 진입.

        Job 은 데이터/행을 저장하지 않으므로(per-run, one-shot) 템플릿 원문 + 매핑 프로파일만
        복원한다: 데이터는 「바꾸기…」로 이 저장-세션 안에서 물린다(무데이터면 가상 1건 큐).
        매핑은 :meth:`~hwpxfiller.gui.mapping_state.MappingModel.apply_profile` 로 ``confirm=True``
        복원 — 프로파일은 과거 사람 확정 산출물이라 확정본으로 도착하고 라이브 재제안이 덮지
        못한다(결정 12). 원문은 읽기 전용(정의가 조용히 갈라지지 않게 — 손보려면 「사본으로
        편집」, 슬라이스 5b).

        **실패 원자성**: 실패 가능한 파일 읽기(template_path)를 **먼저** 지역 변수로 끝낸 뒤에야
        세션을 교체한다 — 템플릿 파일이 사라졌으면 상태를 건드리지 않고 :class:`OSError` 를
        올려, 스태시해 둔 휘발 세션이 반쪽 상태로 오염되지 않는다(호출측이 잡아 재진술)."""
        vm = TxtDraftViewModel(self._registry)
        vm.load_saved_template(job.template_path)  # OSError 가능 — 교체 전에 끝낸다
        mapping = MappingModel.from_field_names(template_fields(vm.template_text), [], col_kinds={})
        mapping.apply_profile(job.mapping, confirm=True)  # 결정 12 — 사람 소유 확정 복원
        # 커밋(이 아래로는 실패 없음) — 저장-세션으로 원자 교체.
        self.vm = vm
        self.mapping = mapping
        self.data_label = ""
        self.data_source = ""
        self._data_key = ""
        self.selection = SelectionModel(0)   # 데이터 미로드 — 무데이터 가상 1건 큐(결정 14)
        self.queue = TxtQueueModel(self.selection)
        self.filter = None
        self._fullwidth = False
        self._last_copy = None
        self._gap_cache = {}
        self._gap_cache_key = None
        self._bound_job = job.name
        self._source_readonly = True
        self._source_dirty = False  # 저장 정의 = 깨끗한 원문(읽기 전용 — 손보려면 「사본으로 편집」)
        self._template_path = job.template_path  # 재저장(save-as) 시 이 경로를 재사용
        self._map_dirty = False  # 복원한 레시피 = 저장분과 일치하는 깨끗한 baseline(147)
        self._copied_total = 0  # 복원 = 아직 이 세션에서 복사 안 함(682·685)
        # 로드 시점 지문(리뷰 5c 2R P1 / 212) — 자기 재저장 전에 디스크가 이 지문과 달라졌으면
        # (다른 표면이 이 작업의 템플릿·매핑을 바꿈) 무확인 덮어쓰기가 파괴다.
        self._editing_fingerprint = self._baseline_fingerprint(job)

    @staticmethod
    def _baseline_fingerprint(job) -> str:
        """draft 저장이 실제로 **덮는** 필드만의 지문 — 자기 재저장 드리프트 판정 baseline(212·270).

        draft 저장은 {name(요청값)·template_path·mapping} 만 갈아 끼우고 group·tags·last_run_at·
        filename_pattern·default_dataset_ref·version 은 ``replace`` 로 **보존**한다(재저장이 이
        화면이 편집하지 않는 필드를 승계). 따라서 드리프트 판정은 실제로 덮는 세 필드만 본다 —
        전 필드 지문(:func:`~hwpxfiller.core.job.content_fingerprint`, 에디터용)을 쓰면 무관한
        메타 변경(그룹 이동·외부 참조·파일명 패턴)마다 거짓 드리프트가 뜬다(리뷰 5c 5R P2 / 270).
        보존되는 필드의 외부 변경은 이 저장에 파괴가 아니므로(그대로 승계) 비교에서 뺀다."""
        return json.dumps(
            {"name": job.name, "template_path": job.template_path, "mapping": job.mapping.to_dict()},
            ensure_ascii=False, sort_keys=True,
        )

    def _do_fork_to_volatile(self, p: dict) -> "dict | None":
        """「사본으로 편집」(#148 슬라이스 5b) — 저장 원문을 휘발 사본으로 가른다(결정 7 스위치 ④).

        저장된 기안의 원문은 읽기 전용이라(정의가 조용히 갈라지지 않게) 손보려면 사본이 필요하다.
        포크는 **원문만 갈라지고 값·데이터·선택·큐 진행은 승계**한다 — 현 세션을 그대로 두고 Job
        결속만 끊어 편집 가능하게 한다(``_bound_job`` 소거 → 휘발 모드). 저장된 기안 자체는 건드리지
        않는다. 이미 휘발이면(포크할 저장 정의 없음) 무동작 — 버튼은 저장 모드에서만 뜬다.

        **밀려나는 이전 휘발 재진술(리뷰 5b 2R P1)**: 저장 기안 결속 전에 붙여넣던 휘발 세션은
        스태시에 얼어 있다(두 세션 병존). 포크한 사본이 곧 유일 휘발("이번 세션")이 되어 그 스태시를
        대체하므로 — 단일 슬롯 — 얼려 둔 세션은 도달 불가가 된다. 거기 복구 불가 진행이 있으면
        조용히 버리지 않고 확인 왕복한다(:meth:`_stash_guard`, RC-02). 확인(또는 무장 아님)이면
        스태시를 비운다: 포크가 유일 휘발이라 뒤이은 저장 선택이 이 사본을 밀려난 세션 위로 덮어
        조용히 지우지 않게 한다(사본은 그때 새로 스태시된다)."""
        if not self._bound_job:
            return None
        if not p.get("confirm"):
            g = self._stash_guard()
            if g is not None:
                return {"needs_confirm": True, "kind": "fork_displaces_stash", **g}
        self._bound_job = ""
        self._source_readonly = False
        self._source_dirty = True  # 사본 = 저장 정의에서 갈라진 원문(수정됨 표지)
        self._volatile_stash = None  # 포크 = 유일 휘발 — 밀려난 스태시를 조용히 덮지 않게 비운다
        return None

    def _records(self) -> list:
        return self.vm.records

    def _is_virtual(self) -> bool:
        """데이터 없음 = 가상 길이-1 큐(결정 14) — 「빠른 기안」의 최단 경로.

        데이터를 물리지 않았어도 붙여넣은 원문에 토큰마다 **직접 입력(상수)** 값을 채워 복사할
        수 있어야 한다(무데이터 = 빠른 기안의 정체성). 병합 세션의 큐는 선택된 데이터 행에서
        나오므로 무데이터면 비지만, 그 경우 큐를 **가상 1건**으로 퇴화시켜 카드·복사를 살린다:
        작업점(``queue.current``)은 여전히 ``None`` 이되 :meth:`can_copy` 와 카드 스냅샷이
        가상 카드를 인정한다. **템플릿이 있을 때만** 성립한다 — 원문도 데이터도 없으면 클립보드로
        나갈 것이 없어(빈 문자열) 복사를 열면 조용한 쓰레기가 된다(confirm-or-alarm).
        """
        return self.vm.datasource is None and bool(self.vm.template_text.strip())

    # ----------------------------------------------------- 맞추기 매핑(#148 슬라이스 3b)
    def _map_source_fields(self) -> "list[str]":
        """겨눈 데이터의 열 목록(레코드 0의 키 순서 — 데이터 소스 열 순서 보존)."""
        records = self._records()
        return list(records[0].keys()) if records else []

    def _rebuild_mapping(self) -> None:
        """템플릿·데이터 변화를 맞추기 표에 반영 — 사람 소유는 승계, 새 자리만 재제안.

        :meth:`~hwpxfiller.gui.mapping_state.MappingModel.from_field_names` 로 새 골격을
        세우고(정확 일치 자동 결속·이름 유형 추론), 옛 매핑에서 같은 토큰의 **사람 소유**
        상태(결속·수기 값·유형·서식·**확정**)를 이어 붙인다. 단 결속 열이 새 데이터에 **없으면**
        승계하지 않는다(죽은 결속 방지) — 새 골격의 자동/제안이 그 자리를 다시 채운다.
        시스템 소유(미접촉·미확정 제안)는 승계하지 않는다: 새 데이터 기준으로 다시 제안돼야 한다.

        **확정 승계(#148 슬라이스 4, Codex F1)**: 사람 소유는 ``touched`` 만이 아니라
        ``confirmed`` 도 포함한다(:meth:`RowState.is_system_owned`). 확정-비움(확정+무내용)은
        ``touched=False`` 라 종전 ``touched`` 게이트가 통째로 떨어뜨려, 템플릿 편집·데이터
        새로고침 같은 무관한 재구성에 **선언이 조용히 증발**하고 토큰이 missing 으로 게이트에
        재진입했다(confirm-or-alarm 위반). 확정 상태를 함께 승계해 이를 막는다. 확정-비움은
        새 골격의 자동 결속(정확 일치)까지 **덮어** 무결속으로 유지한다 — 사람의 「비운다」가
        시스템 재제안을 이긴다(결정 12).

        큐·선택은 세션 휘발이라 여기서 건드리지 않는다(호출측이 데이터 교체 시 새로 세운다).
        """
        fields = template_fields(self.vm.template_text)
        records = self._records()
        source_fields = self._map_source_fields()
        col_kinds = sniff_column_kinds(records) if records else {}
        old = getattr(self, "mapping", None)
        self.mapping = MappingModel.from_field_names(
            fields, source_fields, col_kinds=col_kinds
        )
        if old is None:
            return
        cols = set(source_fields)
        for row in self.mapping.rows:
            prev = next(
                (r for r in old.rows if r.template_field == row.template_field), None
            )
            if prev is None or prev.is_system_owned():
                continue  # 새 토큰이거나 시스템 소유(미접촉·미확정 제안) — 새 데이터 기준 자동
            if prev.type == "const":  # 수기 값(man)은 데이터 무관 — 상수째 승계
                row.type = "const"
                row.const = prev.const
                row.fmt = prev.fmt
                row.touched = prev.touched
                # 기억한 결속 소스는 **새 데이터에 살아 있을 때만** 승계한다(Codex F3). 사라진
                # 열을 남기면 「자동으로 되돌리기」가 없는 열로 결속을 되살려, live_profile 이 전
                # 레코드에 빈 값을 내면서 소유권은 auto 라 보고하는 계약 거짓말이 된다(can_revert
                # = type==const ∧ source 라, source 를 비우면 되돌리기 자체가 사라져 정합).
                row.source = prev.source if prev.source in cols else ""
                row.confirmed = prev.confirmed
            elif prev.source and prev.source in cols:  # 사람이 고른 결속이 새 데이터에도 있으면
                row.source = prev.source
                row.type = prev.type
                row.fmt = prev.fmt
                row.touched = prev.touched
                row.confirmed = prev.confirmed
            elif not prev.source:  # 확정-비움(비운다 선언) — 결속 없이 확정. 선언 보존.
                # from_field_names 가 정확 일치로 자동 결속했어도 무결속으로 되돌린다 — 사람의
                # 「비운다」가 시스템 재제안을 이긴다(결정 12). 확정을 승계해 게이트 제외를 유지.
                row.source = ""
                row.touched = prev.touched
                row.confirmed = prev.confirmed
            # else: 사람이 고른 결속이 죽었다(prev.source ∉ cols·非const) — 값 복구 불가라
            #        확정을 승계하지 않고 시스템 소유(missing)로 떨어뜨려 사람 재검토를 강제한다
            #        (조용한 blank 승격 금지 — 확정-비움과 죽은 결속은 다른 사실이다).

    def _map_kind_of(self, source: str) -> str:
        """결속 대상 열의 스니핑 유형(결정 5 우선) — 없으면 빈 문자열(이름 추론 낙착)."""
        if not source:
            return ""
        return sniff_column_kinds(self._records()).get(source, "")

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
        # 이음매(#148 슬라이스 3b) — 레코드를 **맞추기 매핑**에 통과시켜 값 사전을 낸다(결속 열·
        # 표시형·상수). 프로파일은 push 당 1회 빌드해 카드·빈칸 지도·값 셀이 한 출처를 본다.
        profile = self.mapping.live_profile()
        card_values = profile.apply(card_rec)
        segments, card_report = render_segments(vm.template_text, card_values)
        # 정렬 린트 술어는 **치환 전 원문** 기준(결정 17) — 치환하면 런이 사라지므로 원문
        # 기준으로 보아야 "적용됨 · 되돌리기" 상태에서도 무엇을 고쳤는지 정직하게 말한다.
        space_run = segments_have_space_run(segments)
        proportional = is_proportional_font(self._font.value)
        segments = self._aligned(segments)

        # 빈칸 지도(has_gap)는 레코드 값+템플릿+**매핑**에 의존 — 결속·표시형·상수가 바뀌면 어느
        # 카드가 빈칸인지도 바뀐다. 네비게이션·필터 타건마다 O(행×필드) 재계산하지 않게
        # (records 정체, 템플릿, 매핑 지문) 키로 캐시한다(리뷰 F6). 데이터·템플릿·매핑 변경 시 무효화.
        # 지문에 confirmed 포함(#148 슬라이스 4) — 확정-비움 토글이 어느 카드가 빈칸인지 바꾸므로
        # (declared 가 _has_gap 을 가른다) 확정 상태가 캐시 키에 없으면 stale 로 굳는다.
        map_sig = tuple((r.source, r.type, r.const, r.fmt, r.confirmed) for r in self.mapping.rows)
        gap_key = (id(records), vm.template_text, map_sig)
        if self._gap_cache_key != gap_key:
            self._gap_cache = {}
            self._gap_cache_key = gap_key
        gap_cache = self._gap_cache

        # 확정-비움(#148 슬라이스 4, 결정 12) — 렌더는 blank 지만 빈칸 게이트·완료 노트·빈칸
        # 지도에서 빠진다(사람이 「비운다」고 선언한 것은 다시 묻지 않는다). 데이터가 비어 생긴
        # blank 는 여기 없어 게이트에 남는다. 판정은 매핑 모델 단일 출처(declared_blank_fields).
        declared = set(self.mapping.declared_blank_fields())

        def _has_gap(i: int) -> bool:  # 미충족(항목 없음·빈 값) 카드 판정 — 매핑 적용 후, 1회 상각
            if i not in gap_cache:
                values = profile.apply(records[i])
                gap_cache[i] = any(
                    name not in declared
                    and (name not in values or str(values[name]).strip() == "")
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
        # 맞추기 표 행(#148 슬라이스 3b) — 토큰별 결속·소유권·표시형·제안·「지금 행의 값」.
        # 상태는 **card_report 단일 출처**(카드 렌더와 한 출처, 리뷰 F4): missing=무결속·무값
        # ({{토큰}} 빨강) · blank=결속인데 값 빔(〈빈 값〉) · fill=값 있음. 값 셀은 결속(auto)이면
        # 현재 행의 값 읽기전용 미리보기, 상수(man)면 편집 가능한 입력(전 행 공통)이다.
        missing_set, empty_set = set(card_report.missing_fields), set(card_report.empty_fields)
        suggestions = self.mapping.suggestions()
        tokens = [
            {
                "name": r.template_field,
                "state": ("missing" if r.template_field in missing_set
                          else ("blank" if r.template_field in empty_set else "fill")),
                # 결속 열("" = 무결속) · 소유권 색(auto 데이터 / man 상수 / "" 무결속·무값).
                "source": r.source,
                "own": _row_own(r),
                # 값 셀 편집 가능 = 상수(man). 결속(auto)은 행마다 데이터 값이라 읽기전용 미리보기.
                "manual": r.type == "const",
                # 「지금 행의 값」 — man 이면 상수, auto 면 현재 행 값, 무결속이면 빈칸(missing).
                "value": card_values.get(r.template_field, ""),
                "fmt_kind": r.type,      # 표시형 프리셋 선택(결속 값에만 뜻 — man/const 는 프리셋 없음)
                "fmt_code": r.fmt,
                "suggest": suggestions.get(r.template_field, ""),  # 근사 제안(무결속·≥0.6, 원클릭)
                # man 인데 결속 소스를 기억하고 있으면 「자동으로 되돌리기」를 띄운다(막다른 강등 금지).
                "can_revert": r.type == "const" and bool(r.source),
                # 확정 열(#148 슬라이스 4, 결정 12) — 행별 확정. 확정+무내용 = 확정-비움(위 blank
                # 렌더 + 게이트 제외). 저장 세션 유래로 켜고 끄는 스위치(결정 7)는 슬라이스 5.
                "confirmed": r.confirmed,
                # 확정-비움 표지 — 판정은 Python(is_empty_confirmed) 단일 출처. 표면이 빈
                # 값 셀을 「아직 안 씀」이 아니라 「비워둠(선언)」으로 정직하게 말하게(문안≠집합 차단).
                "blank_declared": r.is_empty_confirmed(),
            }
            for r in self.mapping.rows
        ]
        # 가상 카드·큐 퇴화(결정 8·14) — 판정은 여기(Python)서 지금, JS 는 표현만. 유효 큐
        # ≤ 1건이면 **큐 장치 3종**(진행 색인·다음 카드·자동 전진)이 숨는다: 단건이면 순회할
        # 곳이 없고 무데이터(가상 1건)면 큐 자체가 퇴화한다(정보가 없어서지 장식이라서가 아니다).
        # 가상 카드는 작업점(``current``)이 None 이되 복사 가능한 카드 하나로 선다(직접 입력값).
        virtual = self._is_virtual()
        effective_count = 1 if virtual else self.selection.selected_count()
        card = {
            "index": current,
            # 가상 카드(무데이터 직접 입력)도 실재하는 카드다 — 복사·렌더 제목이 이를 인정한다.
            "has_current": current is not None or virtual,
            "queue_degenerate": effective_count <= 1,
            "is_copied": current in copied_set if current is not None else False,
            "position": self.queue.position_of(current) if current is not None else None,
            "uncopied_count": len(self.queue.uncopied()),
            "copied_count": self.queue.copied_count(),
            "selected_count": self.selection.selected_count(),
            "is_complete": self.queue.is_complete(),
            "advance_after": self._advance_after,
            "segments": [{"text": s.text, "kind": s.kind, "name": s.name} for s in segments],
            "missing_fields": card_report.missing_fields,
            # 게이트·상태 배지·완료 노트가 소비하는 결손 집합 — **확정-비움은 뺀다**(결정 12).
            # 토큰 상태 배지·카드 세그먼트는 여전히 card_report 로 blank(〈빈 값〉)를 그린다
            # (보이는 건 같고, 「확인해야 하는가」만 다르다) — 두 소비를 여기서 가른다.
            "empty_fields": [f for f in card_report.empty_fields if f not in declared],
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
            # 복사 이력 건수(내구 단조, 682·685) — 「사본으로 편집」 경고가 무데이터 가상 복사도
            # 세고 정확한 건수를 말하도록. copied_count(큐)는 선택 해제·데이터 교체로 줄지만 이건
            # 붙여넣은 문서 수를 유지한다(0 = 이력 없음).
            "copied_total": self._copied_total,
        }
        return {
            "template_name": vm.template_name or "(붙여넣은 텍스트)",
            "template_text": vm.template_text,
            "tokens": tokens,
            # 맞추기 표가 소비하는 결속 후보·표시형 프리셋(#148 슬라이스 3b). columns = 겨눈
            # 데이터 열(무데이터면 빈 목록 → 드롭다운은 「직접 입력」만). fmt_options 는 유형별
            # 프리셋(format_engine 단일 출처 — 에디터·빠른 기안과 같은 어휘).
            "columns": self._map_source_fields(),
            "fmt_options": _FMT_OPTIONS,
            # 유형 열 선택지(#148 슬라이스 4, 결정 12) — 값-운반 유형(text/date/amount). 결속(auto)
            # 행에서 값 스니핑 오판을 사람이 정정한다("사람이 고른 유형은 언제나 이긴다").
            "type_options": _TYPE_OPTIONS,
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
            # 세션 유래(#148 슬라이스 5a) — 표면이 그릇 열(유형·확정)을 켜고 끄고, 원문 읽기
            # 전용을 가른다(결정 7). 판정은 여기 단일 실체(_bound_job)에서 유도 — JS 는 표현만.
            # 구 화면은 저장 결속이 없어 늘 volatile 이다(무해).
            "mode": "saved" if self._bound_job else "volatile",
            "source_readonly": self._source_readonly,
            "bound_job": self._bound_job,
            # 원문 수정 표지(#148 슬라이스 5b) — modBadge(수정됨)의 단일 출처. 원문이 라이브러리
            # 정의에서 갈라졌는가(사본으로 편집·원문 라이브 편집). 판정은 Python, JS 는 표시만.
            "source_dirty": self._source_dirty,
            # 「기안으로 저장」 자격(#148 슬라이스 5c) — 라이브러리 배접(파일 경로 있음)이고 수정되지
            # 않은 원문만 저장할 수 있다(결정 = 라이브러리 배접만). 붙여넣기·수정 원문은 먼저
            # 「템플릿으로 저장」이 필요하다(비활성 + 사유, dead button 금지). 판정은 Python 단일.
            "can_save_job": (not self._source_dirty) and bool(self._template_path),
            # 「템플릿으로 저장」 노출(#148 슬라이스 6, #135) — 세션 원문을 TXT 라이브러리로 승격하는
            # 두 번째 승격 동사(구 「빠른 기안」에서 흡수). **휘발 세션 전용**(사용자 결정): 저장 기안
            # 결속(saved) 모드는 원문이 이미 라이브러리에 있어 재저장이 무의미하다. 빈손은 저장할
            # 원문이 없어 숨는다(dead button 금지 — 표면은 hidden 으로 가른다). 판정은 Python 단일.
            "can_save_template": (not self._bound_job) and bool(vm.template_text.strip()),
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
        # 타이핑 액션(값 입력·원문 라이브 편집)은 **푸시 대신 반환 스냅샷**으로 JS 가 겨냥
        # 패치한다(_NO_PUSH, 빠른 기안 선례) — 서버 푸시가 포커스된 입력을 재구성하면 왕복 중
        # 친 글자가 지워지고 IME 조합이 끊긴다. 반환은 handler 가 낸 스냅샷(창 상태 반영).
        if getattr(handler, "is_no_push", False):
            return result
        # 확인 왕복(``needs_confirm``/``confirm``)은 변이가 없었으므로 push 를 생략한다 — 목록
        # 액션(삭제·병합)의 needs_confirm, 결속 덮어쓰기의 confirm 이 같은 규약을 쓴다(RC-02).
        if isinstance(result, dict) and (result.get("needs_confirm") or result.get("confirm")):
            return result
        # 변이 동작(네비게이션·템플릿·선택)은 직전 복사 확정을 무효화한다 — 카드가 바뀌므로
        # 완료 노트가 다른 카드와 모순되지 않게(리뷰 F1). 무변이 질의는 재렌더가 없어 불건드림.
        self._last_copy = None
        self._push()
        return result

    def _do_select_template(self, p: dict) -> "dict | None":
        """라이브러리 템플릿 선택 — 콤보(휘발 모드)·홈/템플릿 관리 라우팅 공용 진입(#148 슬라이스 6).

        **저장 결속에서의 진입 = 세션 교체 가드**(리뷰 F3): 홈 「기안 열기」·템플릿 관리 「열기」가
        저장 기안 결속 상태에서 이 액션을 직접 부르면, 종전엔 ``_bound_job``·``_source_readonly`` 를
        그대로 둔 채 원문·매핑만 갈아, 저장 정의가 **다른 템플릿을 가리키는 저장 모드**로 남았다
        (읽기전용 잠금 우회 + 이후 재저장이 그 작업에 엉뚱한 템플릿/매핑을 결속 — 계약 위반).
        무장(진행)이면 파괴를 먼저 재진술하고(``needs_confirm``, :meth:`~...DraftController._do_
        select_job` 동형), 확인(또는 미결속)이면 **휘발로 전이**(``_restore_volatile`` — 저장 결속·
        읽기전용 해제, 스태시된 붙여넣기 세션 복원)한 뒤 템플릿을 선택한다. 콤보는 휘발 모드
        (``_bound_job==""``)라 이 가드를 안 타고 종전 그대로 동작한다(읽기전용 저장 모드에선 콤보
        자체가 잠겨 이 경로로 못 온다).
        """
        if self._bound_job and not p.get("confirm"):
            g = self._leave_guard()
            if g["armed"]:
                return {"needs_confirm": True, "kind": "leave_for_template",
                        "target": p.get("name", ""), **g}
        if self._bound_job:
            self._restore_volatile()  # 저장 결속 해제 → 휘발(스태시 복원 or 새 휘발)
        self.vm.select_template(p["name"])
        self._fullwidth = False  # 치환은 그 원문에 대한 판단 — 원문이 바뀌면 함께 죽는다(리뷰 F2)
        self._source_dirty = False  # 깨끗한 라이브러리 픽 — 수정됨 표지 해제(슬라이스 5b)
        self._template_path = self._resolve_template_path(p["name"])  # 저장 배접(슬라이스 5c)
        self._rebuild_mapping()  # 새 토큰 집합 → 맞추기 골격 재구성(같은 이름 결속은 승계)
        return None

    def _do_new_draft(self, p: dict) -> None:
        """홈 「＋ 새 기안」 — 세션 원자 초기화(F11, F10 「새 작업」과 대칭 문법).

        종전 bare nav 는 직전 기안의 템플릿 선택·붙여넣은 텍스트·데이터·레코드 위치를
        그대로 남겨 라벨 '새'와 어긋났다.

        **면제 철회(#126)**: 원장 F11 의 무확인 근거는 "txt 출력은 일회성이라 버릴 durable
        상태가 없다"였는데, 블록 3 전-선언 큐가 신설되면서 거짓이 됐다. 큐의 복사 진행은
        durable 은 아니어도 **복구 불가**다 — 어디까지 붙여넣었는지는 앱 밖 기억이다. 이제
        이 전이도 가드를 지나며, 확인은 제스처를 소유한 표면(``DraftScreen.confirmNewDraftIfArmed``,
        홈 「＋ 새 기안」도 이를 소비 — #148 슬라이스 6)이 진행을 재진술해 받는다. **세션 교체이므로
        :meth:`_do_leave_guard`(미저장 매핑·원문 편집 포함) 술어를 쓴다**(리뷰 F4 — 데이터 스왑
        전용 ``_guard_state`` 는 map_dirty 를 놓쳐 저장 기안의 미저장 편집을 조용히 버렸다). 결정
        32 가 같은 F11 전제를 이미 부분 개정했다(수기 폼 신설로 버릴 상태가 생김).
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
            # 확정-비움은 게이트에서 뺀다(결정 12) — 사람이 「비운다」고 선언한 것은 다시 묻지 않는다.
            "empty_fields": self._gate_empty(report),
        }

    _do_copy_precheck.is_query = True  # 무변이 질의 — dispatch 가 push 를 생략한다

    def _do_set_template_text(self, p: dict) -> None:
        self.vm.set_template_text(p["text"])
        self._fullwidth = False  # 붙여넣은 새 원문에 옛 치환 결정이 승계되지 않는다(리뷰 F2)
        self._source_dirty = False  # 새로 붙여넣은 원문 = 깨끗한 시작(수정됨 아님, 슬라이스 5b)
        self._template_path = ""  # 붙여넣기 = 파일 배접 없음 → 저장 불가(먼저 「템플릿으로 저장」)
        self._rebuild_mapping()  # 붙여넣은 원문의 토큰 → 맞추기 골격

    def _do_edit_source(self, p: dict) -> dict:
        """원문 뷰 라이브 편집(뷰 전환 ③, 결정 34) — 타이핑이 맞추기 표를 실시간 재구성.

        _NO_PUSH: 포커스된 원문 textarea 를 서버 푸시가 재구성하면 왕복 중 친 글자가 지워지고
        한글 IME 조합이 끊긴다(슬라이스 4 stale 경합·빠른 기안 선례). 반환 스냅샷으로 JS 가
        맞추기 표·미리보기만 겨냥 패치하고 원문 textarea 는 손대지 않는다. 전각 치환은
        **타건마다 리셋하지 않는다**(빠른 기안 `_do_edit_source` 리뷰 F3와 같은 근거: 켠 뒤 한
        글자만 쳐도 조용히 꺼지는 것을 막는다 — 보이는 이월은 조용한 이월이 아니다).

        저장 원문은 읽기 전용이라 여기서 편집을 받지 않는다(#148 슬라이스 5a·5b) — 표면이 이미
        textarea readonly 로 막지만 백엔드도 방어한다(무변이 스냅샷 반환 — 조용한 정의 분기 금지).
        손보려면 「사본으로 편집」이 먼저 휘발로 가른다(:meth:`_do_fork_to_volatile`)."""
        if self._source_readonly:
            return self.snapshot()  # 저장 정의는 여기서 안 바뀐다(포크가 먼저)
        self.vm.set_template_text(p["text"])
        self._source_dirty = True  # 원문 라이브 편집 = 라이브러리에서 갈라짐(수정됨 표지)
        self._rebuild_mapping()
        return self.snapshot()

    _do_edit_source.is_no_push = True  # 포커스 원문 입력 보호 — 반환 스냅샷 겨냥 패치

    # ---------------------------------------------------- 맞추기 결속·표시형(#148 슬라이스 3b)
    def _do_set_source(self, p: dict) -> "dict | None":
        """토큰 결속·해제(드롭다운·제안 원클릭 공유) — 결정 5·30.

        ``col`` = 데이터 열이면 자동 결속(auto, 유형은 값 스니핑), 빈 값이면 해제(무결속 →
        근사 제안·재결속 대기). **수기 값 덮어쓰기 확인**: 직접 입력한 값이 있는 자리에 열을
        붙이면 그 값은 되돌릴 수 없이 사라지므로 첫 호출은 확인 요구(``{"confirm": 문안}``)를
        돌려주고, 웹이 확인받아 ``confirm=True`` 로 다시 부른다(빠른 기안·relink 게이트 문법)."""
        name, col = p["name"], (p.get("col") or "")
        idx = self.mapping.index_of(name)
        if col:
            if col not in self._map_source_fields():
                raise ValueError(f"데이터에 없는 열입니다: {col}")  # confirm-or-alarm
            row = self.mapping.rows[idx]
            if row.type == "const" and row.const.strip() and not p.get("confirm"):
                return {
                    "confirm": (
                        f"{{{{{name}}}}} 에 직접 입력한 값 「{row.const}」은 「{col}」 열의 값으로 "
                        "바뀌고 되돌릴 수 없습니다. 계속하시겠습니까?"
                    )
                }
            self.mapping.bind_column(idx, col, self._map_kind_of(col))
        else:
            self.mapping.unbind(idx)  # 무결속 — 값 동결 없음(큐는 행마다 값이 달라 단건 문법 부적용)
        self._map_dirty = True  # 사람이 결속/해제 — 미저장 레시피 편집(147)
        return None

    def _do_set_map_value(self, p: dict) -> dict:
        """토큰 값 직접 입력(man) — 상수 강등. 결속 소스는 기억(되돌리기로 복귀, 사용자 결정).

        _NO_PUSH: 포커스된 값 입력을 서버 푸시가 재구성하지 않게 반환 스냅샷으로 미리보기·
        소유권만 겨냥 패치한다(빠른 기안 `set_token` 선례). 값은 **전 행 공통 상수**다 —
        큐에서 '어느 행의 값'인지 모호한 hand 대신 상수로 낙착한다."""
        self.mapping.set_manual(self.mapping.index_of(p["name"]), p.get("text", ""))
        self._map_dirty = True  # 직접 입력 = 미저장 레시피 편집(147)
        return self.snapshot()

    _do_set_map_value.is_no_push = True

    def _do_set_map_fmt(self, p: dict) -> None:
        """표시형(유형 내 프리셋) 정정 — 결속 열에서 오는 값에만 뜻이 있다(결정 34 2층)."""
        self.mapping.set_fmt_for(p["name"], p.get("code", ""))
        self._map_dirty = True  # 표시형 정정 = 미저장 레시피 편집(147)

    def _do_set_map_type(self, p: dict) -> None:
        """값 유형 정정(#148 슬라이스 4, 결정 12) — 값 스니핑 오판을 사람이 이긴다.

        결속(auto) 값의 운반 유형(text/date/amount)을 사람이 고른다: 이름에 「금액」이 없어도
        값이 숫자면 금액 스니핑이 맞지만, 틀렸을 때 사람 선택이 언제나 이긴다(:meth:`MappingModel.
        set_type` 이 ``touched=True`` — 시스템 재제안 차단). 유형이 바뀌면 이전 표시형 프리셋은
        무효라 기본으로 떨어진다(모델 계약). 미지 유형은 조용히 무시하지 않고 시끄럽게 거부한다
        (set_type 이 열거형 검증 — confirm-or-alarm). 표면은 결속 행에만 이 컨트롤을 띄운다
        (const/무결속엔 운반 유형이 뜻이 없어 dead control 금지)."""
        self.mapping.set_type(self.mapping.index_of(p["name"]), p["type"])
        self._map_dirty = True  # 유형 정정 = 미저장 레시피 편집(147)

    def _do_set_confirmed(self, p: dict) -> None:
        """행별 확정 토글(#148 슬라이스 4, 결정 12) — 확정+무내용 = 확정-비움(「비운다」 선언).

        확정-비움은 렌더가 데이터-빈값 ``blank`` 와 같되(〈빈 값〉) 복사 전 빈칸 게이트에서
        빠진다(:meth:`MappingModel.declared_blank_fields` 가 가른다). 저장 승격의 확정 게이트
        (전 행 확정 = 「기안으로 저장」 자격)는 슬라이스 5 — 여기선 그릇만 세운다."""
        self.mapping.set_confirmed(self.mapping.index_of(p["name"]), bool(p.get("value")))
        self._map_dirty = True  # 확정 토글 = 미저장 레시피 편집(147)

    def _do_revert_map(self, p: dict) -> None:
        """man→auto 되돌리기 — 기억한 결속 소스 복귀(막다른 강등 금지, 결정 31).

        직접 입력으로 상수 강등된 자리를 원 결속 열로 되살린다. 소스 기억이 없으면 무동작
        (표면은 되돌리기를 소스 기억이 있을 때만 띄운다)."""
        idx = self.mapping.index_of(p["name"])
        if self.mapping.revert_binding(idx, self._map_kind_of(self.mapping.rows[idx].source)):
            self._map_dirty = True  # 실제 되돌림 발생 = 미저장 레시피 편집(무동작이면 불변, 147)

    def _do_step(self, p: dict) -> None:
        """작업점을 큐 표시 순서로 이동(↓/↑, 경계 멈춤) — 자유 레코드 커서가 아니라 큐 판(결정 16)."""
        self.queue.step(int(p["delta"]))

    def _do_set_current(self, p: dict) -> None:
        """상태 색인 점 클릭 = 작업점 직접 지정(큐 밖 인덱스는 큐 모델이 정규화로 되돌린다).

        ◀▶ :meth:`_do_step` 와 함께 **자유 이동**이 미루기(결정 10 사망)를 대체한다 —
        막힌 카드에서 다음 점을 눌러 벗어난다(작업점 고정 전제가 깨져 미루기가 불필요해졌다).
        """
        idx = p.get("index")
        self.queue.set_current(int(idx) if idx is not None else None)

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
        g["map_dirty"] = self._map_dirty
        g["source_dirty"] = self._source_dirty  # 원문 편집 성분(342) — 문안이 정직하게 짚도록
        g["armed"] = g["armed"] or queue_partial
        return g

    def _leave_guard(self) -> dict:
        """세션 **교체** 앞 가드 — 선택·큐(:meth:`_guard_state`)에 **미저장 레시피 편집**을 더한다.

        데이터 교체(T3, :meth:`_guard_state`)와 갈린다: 데이터 스왑은 매핑·상수·원문을 **유지**
        하므로 편집은 잃을 게 없다(거기 실으면 over-warn — confirm-or-alarm 역방향 위반). 반면
        다른 기안 전환·「이번 세션」 귀환·삭제·포크는 세션 전체(매핑·원문 포함)를 재구성/폐기하므로
        미저장 상수·확정·유형 편집(``_map_dirty``, 147)과 **미저장 원문 편집**(``_source_dirty``,
        리뷰 5b 4R P1 / 342)도 사라진다. 원문 편집은 붙여넣기와 달리 재타이핑이 재현을 담보하지
        못하는 손댄 작업이라(재현성 기준) 무장으로 친다. 데이터 미로드·선택·큐 0이어도 이 두
        성분이 무장을 세운다. 소비처: :meth:`~...DraftController._do_select_job`(전환·귀환)·
        ``_do_delete_job``(결속 삭제)·:meth:`_stash_guard`(포크 대체)."""
        g = self._guard_state()
        g["armed"] = g["armed"] or self._map_dirty or self._source_dirty
        return g

    def _do_guard_state(self, p: dict) -> dict:
        """무장 상태 실시간 질의 — 표면의 **데이터 재겨눔** 사전 확인이 소비(작업 화면과 동형).

        스냅샷 캐시가 아니라 지금 Python 이 판정한다(왕복 지연·무푸시 경로의 stale 오판 차단).
        **데이터 스왑 전용**이라 :meth:`_guard_state`(T3, map_dirty 제외 — 스왑은 매핑 유지)를 쓴다.
        세션 **교체**(「새 기안」 등)는 매핑도 폐기하므로 :meth:`_do_leave_guard` 를 써야 한다.
        """
        return self._guard_state()

    _do_guard_state.is_query = True  # 무변이 질의 — dispatch 가 push 를 생략한다

    def _do_leave_guard(self, p: dict) -> dict:
        """세션 **교체** 앞 무장 질의 — 「새 기안」(F11)이 소비(리뷰 F4).

        「새 기안」은 세션 전체(매핑·상수·확정·유형·원문 편집 포함)를 폐기하는 교체라, 데이터
        스왑 전용 :meth:`_guard_state`(map_dirty 를 armed 에 넣지 않는다 — 스왑은 매핑 유지)가
        아니라 :meth:`_leave_guard`(미저장 매핑·원문 편집을 armed 로 친다) 술어를 써야 한다.
        종전엔 ``confirmNewDraftIfArmed`` 가 ``guard_state`` 를 질의해, 저장 기안의 미저장 매핑
        편집을 데이터 없이 한 세션에서 「새 기안」이 **조용히 버렸다**(armed=False → 확인 생략).
        전환·귀환·삭제·포크가 이미 :meth:`_leave_guard` 를 쓰는 것과 정합.
        """
        return self._leave_guard()

    _do_leave_guard.is_query = True  # 무변이 질의 — dispatch 가 push 를 생략한다

    # 등록 데이터(풀) 겨눔(#26/#6)은 PoolTargetingMixin 공용 래퍼(K4) — 화면별 후처리는
    # _after_pool_load(데이터 존 리셋)가 진다.
    def _after_pool_load(self, records: list) -> None:
        """풀 겨눔도 파일과 동일 리셋 — 전체 선택·새 큐·필터 재생성(작업 화면과 동형)."""
        self._stash_filter()  # 죽는 세션의 정의 → 슬롯(옛 소스 키 기준 — 키 갱신 전에)
        self._data_key = self._pool_key()  # 라벨은 공용 래퍼가 이미 세팅
        self.selection = SelectionModel(len(records))  # 데이터 변경 → 전체 선택 초기화
        self.queue = TxtQueueModel(self.selection)     # 큐 = 세션 휘발 — 새 데이터 = 새 큐
        self._install_filter(records, {})  # txt 는 매핑 힌트 없음 — 값 스니핑만(결정 24)
        self._rebuild_mapping()  # 새 데이터의 열 → 자동 결속·근사 제안 재계산(사람 소유 승계)

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
        self._rebuild_mapping()  # 새 데이터의 열 → 자동 결속·근사 제안 재계산(사람 소유 승계)
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
        # 이음매(#148 슬라이스 3b) = **레코드 → 맞추기 매핑 → 값 사전 → render_segments**. 종전
        # 항등 매핑(레코드를 그대로 값 사전으로)에 결속·표시형·상수(수기 값)를 얹는다 — 토큰명이
        # 열명과 정확히 같아야만 채워지던 제약이 풀린다. 클립보드 텍스트 = **카드와 같은 변환의
        # 결과**(결정 17 치환의 계약): 세그먼트를 이어붙여 만든다(치환이 카드에만 걸려 "보이는 것
        # ≠ 복사되는 것"으로 갈라지지 않게 세그먼트 경로 하나로 묶는다).
        segments, report = render_segments(self.vm.template_text, self.mapping.live_profile().apply(rec))
        return "".join(s.text for s in self._aligned(segments)), report

    def _aligned(self, segments: list) -> list:
        """전각 치환 적용(세션 옵션이 켜졌을 때만) — 카드 렌더·클립보드 공용 통로."""
        return align_segments(segments) if self._fullwidth else segments

    def _gate_empty(self, report: "RenderReport") -> "list[str]":
        """리포트의 빈 값 집합에서 **확정-비움을 뺀** 게이트/노트용 집합(#148 슬라이스 4, 결정 12).

        복사 전 빈칸 게이트·완료 노트는 이걸 소비한다 — 렌더(〈빈 값〉 표지)는 확정-비움을
        그대로 그리되, 「확인해야 하는가」에서는 사람이 선언한 비움을 뺀다. 데이터가 비어 생긴
        빈 값은 선언이 아니라 그 행의 사실이라 남는다(:meth:`MappingModel.declared_blank_fields`
        단일 출처 — 카드 스냅샷의 게이트 집합과 같은 판정)."""
        declared = set(self.mapping.declared_blank_fields())
        return [f for f in report.empty_fields if f not in declared]

    def can_copy(self) -> bool:
        """복사 가능 = 작업점 실재(리뷰 F3) **또는 가상 카드**(무데이터 직접 입력, 결정 14).

        브리지가 이걸로 게이트해 작업점 없을 때 빈 템플릿(생 ``{{토큰}}``)이 클립보드로 조용히
        나가는 것을 막는다(버튼 비활성과의 레이스·직접 호출). 데이터를 안 물린 세션은 작업점이
        없어도(:meth:`_is_virtual`) 상수 값으로 채운 카드를 복사할 수 있다 — :meth:`render` 는
        작업점이 ``None`` 이면 빈 레코드(``{}``)를 매핑에 통과시키므로 상수만으로 채워진다."""
        return self.queue.current is not None or self._is_virtual()

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
            # 가상 카드(무데이터 직접 입력, 결정 14) — 큐가 없어 후미 이동·전진은 없지만 완료
            # 노트는 남긴다(행 번호 없이 — 가상 1건이라 "N행"이 무의미하다). 그 외(작업점도
            # 가상도 아님)는 게이트가 막았어야 할 무동작.
            if self._is_virtual():
                self._last_copy = {
                    "row": None,
                    "missing_fields": list(report.missing_fields),
                    "empty_fields": self._gate_empty(report),  # 확정-비움 제외(결정 12)
                }
                self._copied_total += 1  # 가상 복사 = 큐 미기록이라 내구 카운터로 센다(682·685)
                self._push()
            return
        # 복사한 카드(전진 전 작업점)를 못박아 완료 노트에 실린다 — 전진해도 어느 행인지 명시.
        self._last_copy = {
            "row": cur,
            "missing_fields": list(report.missing_fields),
            "empty_fields": self._gate_empty(report),  # 확정-비움 제외(결정 12)
        }
        self._copied_total += 1  # 복사 이력(682·685) — 선택 해제로 줄지 않는 내구 건수
        self.queue.copy(cur)
        if self._advance_after:
            self.queue.advance_to_next_uncopied()
        self.queue.reconcile()  # copied ⊆ selected 불변식 유지(멱등)
        self._push()
