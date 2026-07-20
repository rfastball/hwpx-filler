"""「작업」 화면 컨트롤러 — 좌 작업 목록 + 우 세션 패널 4존(webview 비의존).

R-flow 구현 라운드(에픽 #90). R-info 1부가 확정한 「작업」 화면(변형 B master-detail: 좌
목록 + 우 4존 세션 패널)의 착지. 이 컨트롤러는 **링2 표면**이다 — 실행 화면(``screen_run.py``,
슬라이스 3에서 사망)을 재사용하지 않고 링1 VM 을 **직접 임포트**해 구동한다(부록 A: "계약
대부분은 링1이 소유하고, 죽는 것은 링2 표면뿐" — 그 링2 표면이 죽어 이제 여기가 유일 소비처).
실행 결정(데이터 로드·사전검증·3상태 배지·강제 확인 게이트·생성 계획)은
:class:`~hwpxfiller.gui.run_state.RunViewModel`(Qt-free), 레코드 선택은
:class:`~hwpxfiller.gui.selection_state.SelectionModel`(Qt-free)이 소유한다 — 재구현 금지(#87).

**4존 스냅샷**: 헤더(작업 정체)·데이터(겨눔·행 선택)·본문(필드 배지 거울·게이트)·완료(생성
결과 세션 스코프). 존은 표현 구조라 job.js 가 필드를 배치한다 — 스냅샷 필드는 실행 화면과
평행해 링1 배선이 감사 가능하다(같은 refresh/게이트/생성 계약 소비).

**네이티브 표면 동형**: ``load_data_path``·``set_output_folder``·``generate``·``render`` 시그니처를
실행 화면과 같게 유지해 브리지(:mod:`~hwpxfiller.webapp.app`)의 화면-파라미터 네이티브 헬퍼
(``pick_data_file``·``load_data_sheet``·``pick_output_folder``·``generate``)를 등록 한 줄로 재사용한다.

**후속 슬라이스**(confirm-or-alarm: 없는 기능을 있는 척하지 않는다) — 아직 이 패널에 없는 것:
- 좌 목록의 2구획 틴트·group-by 렌즈·컴파일 배지 등 풍부화(홈 브라우저 VM 채택).
- 건 연속성 직전 필터 재적용(블록 4 결정 28, PR-4)·txt 큐(블록 3)·빠른 기안(블록 5).
- 세션 가드의 유보 성분: **T2**(마법사 인계 비파괴화 — 에디터 접합, 슬라이스 5)·수동 필드
  입력 성분(블록 5, 슬라이스 7). **T3**(txt 큐 부분 진행)은 슬라이스 6 PR-4 에서
  :class:`~hwpxfiller.webapp.screens.TxtController` 가 착지했다 — 술어 몸통은 이 화면과
  공유(:meth:`~hwpxfiller.webapp.data_zone.DataZoneMixin._selection_guard`).
(슬라이스 2 착지분 — 게이트 재진술 블록·거울 채움 테이블·덮어쓰기 modal.js 수치 합성·식별
요약 링1 :func:`~hwpxfiller.core.identity_summary.identity_summary`(#88, A-1-15) — 과
슬라이스 4 착지분 — 필터 선언 표면(결정 23~25)·세션 가드 T1+데이터 재겨눔(결정 26·27,
T4=가드 불요·T5=수용 손실) — 은 본문에 배선돼 있다.)

**스코프 경계 — 미구현 명시(#89, A-4-33)**: ``screen_run.py`` 경계 절을 승계한다 — 나라·
RC-06·생성 원장 항은 **원문 그대로**, 이어채우기 항만 실행 화면 사망으로 맥락을 반영해
**재기술**했다(원문의 "실행 화면에선 강등/숨김"이 이제 거짓이라 verbatim 불가). 아래는 링1
seam 은 존치하나 이 패널이 노출하지 않는다. "없는 기능을 있는 척하지 않는다"의 명문이며,
표면(실행 화면)이 죽어도 이 경계 선언은 죽지 않는다(F40 전례 방지):
- 나라장터 소스 겨눔(동결 해제 시 재배선)·나라 애드혹 취득.
- 기존 문서 이어채우기(#18 결정으로 강등/숨김 — seam 은 링1 ``target_mode``/``set_prev_output``
  게이트 술어에 잔존, A-4-32).
- 협조적 취소(RC-06)·생성 원장 opt-in.
덮어쓰기 확인·미입력 강제 확인 게이트·구조 드리프트 차단·미입력 표식·다중 시트 확정
게이트(#33)는 모두 포함한다.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from ..batch import generate_batch
from ..core.dataset_pool import DatasetPoolRegistry
from ..core.identity_summary import identity_summary
from ..core.job import MISSING_MARKER, JobRegistry
from ..core.mapping import SOURCE_CARRIER_TYPES
from ..core.template_status import OUTPUT_SUBDIR_NAME
from ..gui.filter_state import (
    KIND_AMOUNT,
    KIND_DATE,
    KIND_TEXT,
    FilterModel,
)
from ..gui.result_errors import describe_result_error
from ..gui.run_state import RunViewModel
from ..gui.selection_state import SelectionModel
from .data_zone import (
    EMPTY_FILTER as _EMPTY_FILTER,
    EMPTY_TABLE as _EMPTY_TABLE,
    DataZoneMixin,
)
from .screens import (
    NO_ROWS_TEXT,
    PoolTargetingMixin,
    PushSink,
    default_pool_registry,
    load_pool_into,
    relink_job_template,
    source_label,
)
from .settings import load_job_collapsed_groups, save_job_collapsed_groups

# 사전검증 성공 문구는 링2 사용자 어휘로 순화한다(실행 화면 _PREFLIGHT_OK_TEXT 동형).
_PREFLIGHT_OK_TEXT = "검증 완료 — 문서를 생성할 준비가 됐습니다."

# 데이터 미겨눔 상태의 재진술 빈 골격 — 필터/테이블 골격은 데이터 존 공유 믹스인
# (data_zone.EMPTY_*)이 소유한다(PR-2b).
_EMPTY_RESTATE = {
    "origin": None, "filter_active": False, "in_def": 0, "extra": 0, "sample": [],
}

# 재진술 이름 목록 표본 크기 — 소량(≤N)=전부, 대량=층화 표본 N + 「외 …건 펼치기」(결정 5·36).
_RESTATE_SAMPLE = 3


class JobController(DataZoneMixin, PoolTargetingMixin):
    """「작업」 화면 — 좌 작업 목록 선택 + 우 세션 패널(링1 RunViewModel/SelectionModel 위임).

    실행 화면(``screen_run.py``) 사망(슬라이스 3) 이후 **링1 실행 결정을 소비하는 유일 세션
    표면**이다. 슬라이스 1 시절 존재하던 RunController 와의 링2 배선 중복(``load_data_path``·
    ``dispatch``·``_do_*``·``_auto_aim_default``·``snapshot`` 골자)은 실행 화면 제거로 **자연 소멸**했다
    (#94 종결 — 공유 베이스 추출 대신 중복 유발 표면을 제거하는 결정의 귀결). 남은 소비 표면이
    하나뿐이라 링2 재구현을 막을 별도 가드는 불요 — 링1 결정(사전검증·게이트 단일 산출·생성 계획·
    ack 상태기계)은 여전히 :class:`~hwpxfiller.gui.run_state.RunViewModel`/:class:`~hwpxfiller.gui.
    selection_state.SelectionModel` 이 소유하고, ``test_job_panel_imports_ring1_and_does_not_
    reimplement``(#87)가 이 컨트롤러의 링1 메서드 재구현을 계속 막는다."""

    name = "job"

    def __init__(
        self,
        registry: JobRegistry,
        push: PushSink,
        *,
        pool_registry: "DatasetPoolRegistry | None" = None,
    ) -> None:
        self.registry = registry
        self._push_sink = push
        self.vm: "RunViewModel | None" = None
        self.selection = SelectionModel(0)
        # 필터 선언 상태(블록 4, 결정 23~25) — 스코프 = 세션(작업×데이터, 결정 24).
        # 데이터 겨눔 시 생성, 작업 전환·데이터 교체 시 재생성(전환 인계는 PR-4 결정 28).
        self.filter: "FilterModel | None" = None
        # 마지막 생성 완주 집합(결정 27) — 완료 이벤트 = 무장 해제(내역은 완료 존이 담보).
        self._last_generated: "set[int] | None" = None
        # 직전 필터 슬롯(결정 28) — 정의 가진 세션이 죽을 때 덮어쓰는 1칸 세션 메모리
        # (앱 수명·미저장 — 필터 영속 뒷문 금지). 소스 일치 게이트용 키와 쌍.
        self._last_filter: "dict | None" = None  # {"source_key": str, "state": dict}
        self._data_key = ""  # 현 데이터 소스 정체(file:경로 | pool:참조) — 소스 일치 판정
        self.job_name = ""  # 좌 목록에서 겨눈 작업(패널 세션의 주체)
        # 좌 목록 접힌 그룹(결정 43·R-info 결정 6) — 마지막 상태를 Python 설정에서 복원.
        # 앱은 홈당 단일 인스턴스(뮤텍스 가드)라 메모리 캐시가 디스크와 갈라질 경로가 없다.
        self._collapsed: "set[str]" = set(load_job_collapsed_groups())
        self.data_label = ""
        self.data_source = ""  # 소스 종류 플래그('file'|'pool') — 병기 라벨은 스냅샷이 합성(K8)
        self.out_dir = ""
        self._marked_fields: "list[str]" = []
        # 레코드 미리보기의 날짜 토큰 기준 시각(F33) — 스냅샷마다 갱신되고 generate 가 재사용
        # (미리보기=실파일명, RC-02 확장). None=미리보기 전(헤드리스 직행).
        self._names_now: "datetime | None" = None
        # 기본 데이터셋 자동 조준(#53-A) 결과 재진술 — 성공(ok)/실패(warn)를 스냅샷에 노출.
        self.data_notice_text = ""
        self.data_notice_level = ""
        # 등록 데이터(풀) 겨눔(#26/#6) — 기본은 홈 레지스트리, 테스트는 주입.
        self.pool_registry = (
            pool_registry if pool_registry is not None else default_pool_registry()
        )

    # ------------------------------------------------------------- 관측 푸시
    def _push(self) -> None:
        self._push_sink(self.name, self.snapshot())

    # ------------------------------------------------------------- 좌 목록
    def _job_rows(self, jobs) -> "list[dict]":
        """좌 master 목록의 평면 뷰 — 이름 + 선택 표지(슬라이스 1 형태 유지).

        그룹 렌더는 :meth:`_job_sections` 가 담당한다 — 이 평면 뷰는 "그룹과 무관한 전체
        집합" 소비자(테스트·세션 판정)를 위해 남는다. 두 뷰가 어긋나지 않게 :meth:`snapshot`
        이 ``list_jobs`` 를 1회 읽어 같은 ``jobs`` 를 둘에 넘긴다.
        기안 작업(TXT) 구획은 draft-as-job(블록 3/5) 착지 전까지 빈 채로 둔다(없는 걸 있는
        척하지 않는다) — job.js 가 라벨만 렌더.
        """
        return [{"name": j.name, "selected": j.name == self.job_name} for j in jobs]

    def _job_sections(self, jobs) -> "tuple[list[dict], bool]":
        """그룹 구획 뷰(결정 43·A안: 매체 구획 안 사용자 그룹) — ``(sections, flat)`` 반환.

        - 그룹 배열 = 이름순 안정(R-info 결정 4), 「그룹 없음」(``group==""``)은 마지막.
        - ``flat=True`` = 그룹 0개 **퇴화 불변식**: 헤더·들여쓰기 없는 평면(현행 모습 그대로).
          이때도 sections 는 무그룹 1구획으로 돌아가 표면이 분기 없이 그린다.
        - ``collapsed`` 는 영속 접힘 집합(결정 6-①)의 사영 — 행은 접혀도 **집합에서 빠지지
          않는다**(선택·세션 판정은 전체 집합 위 — 결정 6-⑤ 접어도 선택 유지).
        """
        grouped: "dict[str, list[dict]]" = {}
        for j in jobs:
            grouped.setdefault(j.group, []).append(
                {"name": j.name, "selected": j.name == self.job_name}
            )
        named = sorted(g for g in grouped if g)
        flat = not named
        order = named + ([""] if "" in grouped else [])
        sections = [
            {
                "group": g,
                "collapsed": (not flat) and g in self._collapsed,
                "count": len(grouped[g]),
                "rows": grouped[g],
            }
            for g in order
        ]
        return sections, flat

    # ------------------------------------------------------------- 스냅샷
    def _indices(self) -> "list[int]":
        return self.selection.selected_indices()

    def _filename_source_columns(self) -> "list[str]":
        """파일명 패턴이 이미 나르는 **원본 데이터 열** — 식별 요약 토큰 모드 입력(결정 37).

        파일명 토큰은 **매핑 후 템플릿 필드** 네임스페이스인데(파일명은 매핑 적용 후 레코드에서
        해소, :meth:`~hwpxfiller.gui.run_state.RunViewModel.unresolved_name_tokens`), 식별
        요약은 **원본 레코드**(사용자가 데이터에서 본 열)를 소비한다. 그래서 파일명이 요구하는
        템플릿 필드를 매핑의 ``source`` 로 역해소해 원본 열로 돌려준다 — 그렇지 않으면 토큰
        모드가 엉뚱한 네임스페이스로 오발한다(confirm-or-alarm).

        **원본 열을 실제로 나르는 유형만** 대상이다(:data:`~hwpxfiller.core.mapping.
        SOURCE_CARRIER_TYPES`). ``const`` 은 리터럴을 방출해 ``source`` 값과 무관하고(옛 매핑에서
        ``source`` 가 남아 있어도 파일명은 그 열을 나르지 않는다), ``blank`` 은 빈 값이다 — 둘을
        나르는 열로 오인하면 구별 열이 토큰 모드로 침묵 배제된다(리뷰 반영). 원본 레코드에
        실재하는 열만 반환한다(부재 열 헛발 방지).
        """
        from ..naming import pattern_field_tokens

        tokens = set(pattern_field_tokens(self.vm.job.filename_pattern))
        present = set(self.vm.records[0].keys()) if self.vm.records else set()
        cols: "list[str]" = []
        for m in self.vm.job.mapping.mappings:
            # source 유래 유형만 파일명이 그 열을 나른다(단일 출처 SOURCE_CARRIER_TYPES).
            if (m.template_field in tokens and m.type in SOURCE_CARRIER_TYPES
                    and m.source in present and m.source not in cols):
                cols.append(m.source)
        return cols

    def _record_rows(self, indices: "list[int]", mapped: "list[dict]") -> "list[dict]":
        """각 레코드 = 원본 식별 요약 + 그 행이 만들 **실**파일명 미리보기(F33).

        ``indices``·``mapped`` 는 :meth:`snapshot` 가 1회 계산해 넘긴다(``_mirror`` 와 공유 —
        매핑 이중 적용 방지, 리뷰 반영).

        식별 요약은 링1 단일 함수(:func:`~hwpxfiller.core.identity_summary.identity_summary`,
        결정 37·A-1-15)가 **전체 레코드 집합 위에서 1회** 판정한다 — 어느 열로 요약할지는
        집합 의존(중복 해소·토큰 모드)이라 선택과 무관하게 안정적이어야 한다. 표면은 표현만
        입히고 '어느 열'은 재구현하지 않는다(부록 A-1-15).

        파일명은 생성과 동일 규칙으로 계산한다(:func:`~hwpxfiller.naming.plan_output_names`).
        ``{{seq}}``·충돌 접미사는 최종 선택 집합에 따라 달라지므로 **선택된** 레코드에만 이름을
        계산한다(미선택 행에 확정되지 않은 이름을 지어내지 않는다 — confirm-or-alarm). 날짜 토큰
        기준 시각은 여기서 캡처해 ``_names_now`` 로 남긴다(:meth:`generate` 가 같은 값 소비 —
        RC-02 '확인 대상=생성 대상'의 미리보기 확장).
        """
        if self.vm is None:
            return []
        from ..naming import plan_output_names

        names: "dict[int, str]" = {}
        if indices:
            self._names_now = datetime.now()
            planned = plan_output_names(
                self.vm.job.filename_pattern, mapped, now=self._names_now,
            )
            names = dict(zip(indices, planned, strict=True))
        isum = identity_summary(
            self.vm.records, filename_tokens=self._filename_source_columns()
        )
        return [
            {
                "index": i,
                "selected": self.selection.is_selected(i),
                "name": names.get(i, ""),
                "summary": isum.display_for(rec),  # 표시=빈 세그먼트를 마커(빈칸)로 채워 위치 보존(생략 아님 — 서로 다른 행이 동일 문자열로 붕괴하는 것 차단)
            }
            for i, rec in enumerate(self.vm.records)
        ]

    # ---- 본문 존 거울(D2 ⓑ, 결정 36) — 필드 채움 테이블 값 집계 --------------
    def _formatted_fields(self) -> "set[str]":
        """표시형(값 변환)이 붙는 필드 — 거울이 '채움 · 표시형'으로 병기한다.

        date·amount 는 언제나 값을 변환하고, text 도 표시형 코드(``fmt``)가 있으면 변환한다.
        const 는 리터럴이라 데이터 변환이 아니다(그냥 '채움').
        """
        return {
            m.template_field for m in self.vm.job.mapping.mappings
            if not m.is_blank and (m.type in ("date", "amount") or m.fmt)
        }

    def _field_value_display(self, state: str, name: str, mapped: "list[dict]") -> str:
        """거울 행의 값 표시 — 상태별. 값은 매핑 출력(``mapped_records``)에서 온다(재구현 금지).

        - ``blank``(의도적 빈칸) = 값 없음 표지.
        - ``missing`` = 선택분 중 몇 행이 비었는지 재진술(낙관 서사 해소).
        - ``filled`` = 실값. 선택 N>1 이고 값이 **실제로 다르면** 표본 명시 병기(S10) — 다 같으면
          그냥 값(허위 '행마다 다름' 금지 — confirm-or-alarm 정직).
        """
        if state == "blank":
            return "(의도적 빈칸)"
        n = len(mapped)
        vals = [str(r.get(name, "")) for r in mapped]
        if state == "missing":
            blank_n = sum(1 for v in vals if not v.strip())
            return f"(미입력) 선택 {n}행 중 {blank_n}행에서 값이 비어 있습니다."
        distinct = list(dict.fromkeys(vals))
        if len(distinct) <= 1:
            return distinct[0] if distinct else ""
        # 표본 병기(S10) — '외 K개 값'은 **서로 다른 값 수**(len(distinct)-1)로 센다. 행 수로 세면
        # 5행 중 4행이 같고 1행만 달라도 '외 4행'이 되어 변화를 과장한다(리뷰 반영, 정직).
        return f"{vals[0]} (표본 · 외 {len(distinct) - 1}개 값)"

    def _mirror(
        self, indices: "list[int]", status, mapped: "list[dict]"
    ) -> "tuple[list[dict], list[str]]":
        """거울 행(비-drift 필드 값 테이블) + drift 필드 목록(차단 배너로 분리, 결정 36).

        거울 = "생성될 문서의 채움 상태"(hwpx 본문은 앱에서 안 렌더). ADR-E 배지는 별도 UI 가
        아니라 거울의 행이다. **drift(구조 불일치)는 미입력(ack 로 풀림)과 같은 표에 섞지 않는다**
        — 거울 자리 차단 배너로 분리한다(danger, 에디터 가야 풀림). RC-23 심각도 서열의 공간 번역.

        ``mapped`` 는 :meth:`snapshot` 가 1회 계산해 넘긴다(``_record_rows`` 와 공유 — 이중 적용 방지).
        """
        fmt = self._formatted_fields()
        rows: "list[dict]" = []
        drift: "list[str]" = []
        for st in status.field_states:
            if st.state == "drift":
                drift.append(st.name)  # 구조 불일치는 선택과 무관 — 0 선택에서도 배너로 발화.
            elif indices:
                # 선택 0 = 생성될 문서 없음 → 거울 행 없음(빈 값을 '채움'으로 오도하지 않는다).
                rows.append({
                    "name": st.name,
                    "state": st.state,
                    "acknowledged": st.acknowledged,
                    "value": self._field_value_display(st.state, st.name, mapped),
                    "formatted": st.name in fmt,
                })
        return rows, drift

    def _filter_sections(
        self, indices: "list[int]", record_rows: "list[dict]"
    ) -> "tuple[dict, dict, dict, dict]":
        """필터·테이블·재진술 유래 스냅샷(블록 4) — 합성은 공유 믹스인(:class:`~hwpxfiller.
        webapp.data_zone.DataZoneMixin`), 여기는 화면 몫(선두 「문서」 열 소재·재진술 유래·
        가드)만 얹는다.

        - **table/filter**: :meth:`_zone_sections` 가 FilterView 1회 평가(캐시 계약)로 합성.
          선두 「문서」 열 소재(이름·요약)는 ``record_rows`` 재사용(F33 승계 — 조용한 드롭 아님).
        - **restate.origin**: 선택 유래는 **집합 비교로 매 스냅샷 판정**(무상태 — 캡처
          시점 정의 텍스트가 스테일해지는 창이 없다): 선택==현 매치 전체 = 정의-유래,
          그 외 = 직접(필터 활성이면 매치/밖 수치 병기 — S4 델타).
        - **restate.sample**: 층화 표본(결정 5) — 광의 OR 에서 소수 가지가 반드시 등장.
        """
        if self.filter is None or self.vm is None:
            return _EMPTY_FILTER, _EMPTY_TABLE, _EMPTY_RESTATE, self._guard_state()
        # 선두 열 소재는 ``record_rows`` 재사용 — 이 화면은 그 목록을 스냅샷 ``records`` 로도
        # 싣기 때문에 이미 전량 지어져 있다(믹스인은 실리는 행에만 이 조회를 부른다).
        rows_by_index = {r["index"]: r for r in record_rows}
        filter_snap, table_snap, view, visible = self._zone_sections(
            indices, rows_by_index.__getitem__
        )
        assert view is not None  # filter 존재를 위에서 확인 — 믹스인 빈 골격 분기 아님
        vis_set = set(visible)
        sel_set = set(indices)
        f_active = self.filter.is_active()
        origin = None
        if indices:
            origin = "definition" if (f_active and sel_set == vis_set) else "manual"
        restate_snap = {
            "origin": origin,
            "filter_active": f_active,
            "in_def": len(sel_set & vis_set) if f_active else 0,
            "extra": len(sel_set - vis_set) if f_active else 0,
            "sample": (
                view.stratified_sample(indices, _RESTATE_SAMPLE)
                if f_active else indices[:_RESTATE_SAMPLE]
            ),
        }
        # 가드 무장도 같은 뷰의 가시 집합으로 판정 — 스냅샷 경로 필터 이중 평가 금지(리뷰 #7).
        return filter_snap, table_snap, restate_snap, self._guard_state(vis_set=vis_set)

    # ------------------------------------------------- 세션 가드(블록 4, 결정 26·27)
    def _guard_state(self, vis_set: "set[int] | None" = None) -> dict:
        """무장 판정 = 집합 비교(결정 27) — "재현 불가능한 수작업"이 있는가.

        술어 몸통은 :meth:`~hwpxfiller.webapp.data_zone.DataZoneMixin._selection_guard` 공유
        (txt T3 가드와 단일 출처, 슬라이스 6 PR-4) — 여기선 이 화면의 **완료 이벤트가 설명하는
        집합**만 댄다: 마지막 생성분(생성 = 무장 해제). 수동 필드 입력 성분은 빠른 기안
        표면(블록 5)이 슬라이스 7 에서 합류한다.

        ``vis_set`` 은 렌더 경로(:meth:`_filter_sections`)가 이미 산출한 가시 집합 —
        스냅샷에서 필터를 이중 평가하지 않기 위한 전달이다(FilterView 캐시 계약,
        고효율 리뷰 #7). 디스패치 단발 판정(select_job·guard_state)은 생략하고 직접 평가.
        """
        return self._selection_guard(
            settled=set(self._last_generated or ()), vis_set=vis_set
        )

    def _do_guard_state(self, p: dict) -> dict:
        """무장 상태 실시간 질의 — 표면의 파괴 전이 사전 확인(데이터 재겨눔·재연결)이 소비.

        스냅샷 캐시(LAST.guard)는 왕복 지연·무푸시 경로(``generate`` 는 dispatch 밖이라
        push 가 없다)에서 stale 이 된다 — 판정은 항상 Python 이 지금 내린다(고효율 리뷰
        #4: 완주 직후 데이터 재겨눔에 거짓 확인 모달·#3: 무장 직후 창에 무확인 통과).
        """
        return self._guard_state()

    _do_guard_state.is_query = True  # 무변이 질의 — dispatch 가 push 를 생략한다

    def snapshot(self) -> dict:
        """4존 패널 스냅샷 — 필드는 실행 화면과 평행(링1 배선 감사 가능), 좌 목록 동봉.

        존 배치는 job.js 소관(헤더=작업 정체, 데이터=겨눔·행, 본문=배지·게이트, 완료=결과).
        """
        # 좌 목록은 레지스트리 1회 판독에서 평면·구획 두 뷰를 함께 파생한다(드리프트 봉쇄).
        jobs = self.registry.list_jobs()
        sections, flat = self._job_sections(jobs)
        base = {
            "job_rows": self._job_rows(jobs),   # 좌 master 목록(평면 뷰)
            "job_sections": sections,           # 그룹 구획 뷰(결정 43) — 표면 렌더 원천
            "job_flat": flat,                   # 퇴화 불변식: 그룹 0개 = 헤더 없는 평면
            "job_group_names": [s["group"] for s in sections if s["group"]],
            "job_name": self.job_name,
            "has_job": self.vm is not None,
            # 세션 가드 무장 상태(결정 26·27) — 표면 참고용(진실은 guard_state 실시간 질의;
            # 렌더 판은 _filter_sections 가 같은 뷰로 산출해 아래 update 가 덮는다).
            "guard": {
                "armed": False, "sel_count": 0, "in_def": 0, "extra": 0,
                "filter_active": False, "filter_parts": 0,
            },
            "out_dir": self.out_dir,
            "data_label": self.data_label,
            # 소스 종류 병기 라벨(#26) — 저장 상태가 아니라 플래그에서 매번 합성(K8).
            "data_source_label": source_label(self.data_source, self.data_label),
            # 기본 데이터셋 자동 조준 재진술(#53-A) — 없으면 None.
            "data_notice": (
                {"level": self.data_notice_level, "text": self.data_notice_text}
                if self.data_notice_text else None
            ),
        }
        if self.vm is None:
            base.update({
                "template_name": "", "template_path": "", "filename_pattern": "",
                "template_missing": False, "has_data": False,
                "record_count": 0, "selected_count": 0, "records": [],
                "preflight": {"level": "", "text": ""},
                "mirror": [], "drift": [], "name_tokens": [],
                "filter": _EMPTY_FILTER, "table": _EMPTY_TABLE, "restate": _EMPTY_RESTATE,
                "gate": {"enabled": False, "level": "warn", "text": "왼쪽에서 작업을 선택하세요."},
            })
            return base
        job = self.vm.job
        indices = self._indices()
        # 선택분 매핑 적용은 1회 — 파일명 미리보기(_record_rows)와 거울 값(_mirror)이 공유한다.
        mapped = self.vm.mapped_records(indices) if indices else []
        status = self.vm.refresh(indices, self.out_dir)  # 사전검증+배지+게이트 단일 산출(RC-23)
        preflight_text = (
            _PREFLIGHT_OK_TEXT if status.preflight.level == "ok" else status.preflight.text
        )
        mirror_rows, drift_fields = self._mirror(indices, status, mapped)
        record_rows = self._record_rows(indices, mapped)
        filter_snap, table_snap, restate_snap, guard_snap = self._filter_sections(
            indices, record_rows
        )
        base.update({
            "template_name": Path(job.template_path).name if job.template_path else "",
            "template_path": job.template_path,  # 추적성 로케이트(#53-B) — 전체 경로
            # 템플릿 부재 시에만 복구 동선(다시 연결)을 노출한다(F30) — 홈 카드와 대칭.
            "template_missing": (
                not job.template_path or not Path(job.template_path).exists()
            ),
            "filename_pattern": job.filename_pattern,
            "has_data": self.vm.datasource is not None,
            "record_count": len(self.vm.records),
            "selected_count": self.selection.selected_count(),
            "records": record_rows,
            # 필터 상태·데이터 테이블·재진술 유래·가드(블록 4) — 표면은 받은 것을 그리기만.
            "filter": filter_snap,
            "table": table_snap,
            "restate": restate_snap,
            "guard": guard_snap,
            "preflight": {"level": status.preflight.level, "text": preflight_text},
            # 본문 존 거울(필드 채움 테이블) + drift 필드(차단 배너로 분리, 결정 36).
            "mirror": mirror_rows,
            "drift": drift_fields,
            # 미해소 파일명 토큰(#128) — 드리프트와 **같은 danger 자격**이라 같은 자리(거울)에서
            # 차단 배너 + 행동 링크로 발화한다. 종전엔 게이트 캡션 한 줄뿐이라 거울은 전 행
            # 「채움」으로 건강해 보이고 재진술은 말없이 사라지는, 신호 없는 차단이었다.
            #
            # **게이트가 실제로 이 사유로 막을 때만** 싣는다(리뷰 F2): 토큰 미해소는 템플릿을
            # 못 읽는 상태에서도 참이라, 사실만 보고 그리면 게이트는 "구조를 읽을 수 없다"고
            # 막는데 거울은 크게 "파일명을 고치라"고 말한다 — 사용자를 엉뚱한 수리로 보내고,
            # #128 이 없앤 바로 그 어긋남(문안 ≠ 실제 집합)을 반대 방향으로 되살린다.
            # 서열 판정은 run_state 단일 출처(gate.reason)를 소비하고 여기서 재유도하지 않는다.
            "name_tokens": (
                self.vm.unresolved_name_tokens()
                if status.gate.reason == "name_tokens" else []
            ),
            "gate": {
                "enabled": status.gate.enabled,
                "level": status.gate.level,
                "text": status.gate.text,
            },
        })
        return base

    def initial(self) -> dict:
        return self.snapshot()

    # ------------------------------------------- 네이티브 보조(브리지가 다이얼로그 담당)
    def load_data_path(self, path: str, *, sheet: "str | None" = None) -> None:
        """선택된 데이터 파일을 링1 VM 으로 로드. 레코드 0건이면 시끄럽게 실패.

        ``sheet`` 는 웹에서 확정한 시트명(다중 시트 확정 게이트 #33, None=CSV·단일 시트).
        시그니처는 실행 화면과 동형 — 브리지 ``pick_data_file``/``load_data_sheet`` 재사용.
        """
        if self.vm is None:
            raise ValueError("먼저 작업을 선택하세요.")
        records = self.vm.load_data(path, sheet=sheet)  # 파일 소스 리졸버(Qt-free). 실패는 raise.
        if not records:
            raise ValueError(NO_ROWS_TEXT)
        self._stash_filter()  # 죽는 세션의 정의 → 직전 필터 슬롯(결정 28, 옛 소스 키 기준)
        self.data_label = Path(path).name
        self.data_source = "file"  # 병기 라벨은 스냅샷이 합성(#26·K8)
        self._data_key = self._file_key(path, sheet)  # 소스 일치 게이트(결정 28)
        self.selection = SelectionModel(len(records))  # 데이터 변경 → 전체 선택 초기화
        self._init_filter()  # 데이터 교체 = 필터 재생성(결정 24 — 열 지형이 바뀐다)
        self._clear_data_notice()  # 사용자가 직접 데이터를 겨눔 → 자동 조준 재진술 소거
        self._push()

    def set_output_folder(self, path: str) -> None:
        """네이티브 폴더 피커가 고른 저장 폴더를 반영(게이트 전제조건, UD-06)."""
        self.out_dir = path
        self._push()

    # ------------------------------------------------------- 웹→Python 데이터 액션
    def dispatch(self, action: str, payload: dict):
        handler = getattr(self, f"_do_{action}", None)
        if handler is None:  # confirm-or-alarm: 미지 액션은 시끄럽게.
            raise ValueError(f"알 수 없는 작업 화면 액션: {action!r}")
        result = handler(payload)
        # 무변이 경로는 push 를 생략한다(고효율 리뷰 #8) — ① is_query 표식 핸들러(순수
        # 질의: filter_panel·guard_state) ② needs_confirm 반환(가드가 전이를 막아 상태
        # 그대로). 동일 스냅샷 전량 재계산+재렌더가 모달 여는 중에 겹치는 낭비 제거.
        is_query = getattr(handler, "is_query", False)
        blocked = isinstance(result, dict) and result.get("needs_confirm")
        if not is_query and not blocked:
            self._push()
        return result

    def _do_refresh(self, p: dict) -> None:
        """레지스트리 재스캔 반영(C6) + stale 세션 무효화(master-detail 불변식).

        좌 목록(``registry.names()``)과 우 패널(``self.vm``)이 갈라지지 않게 조정한다: 선택된
        작업이 다른 화면에서 삭제·개명돼 레지스트리에서 사라졌으면 세션을 무효화한다 — 안 그러면
        존재하지 않는 작업의 라이브 세션이 활성 생성 버튼과 함께 남아 유령 작업에서 생성된다
        (리뷰 #2). 조용히 두지 않고 빈 패널로 재진술(작업이 좌 목록에서도 사라져 상실이 보인다).
        재스캔 자체는 스냅샷이 매번 ``names()`` 를 재읽어 반영(에디터 저장분 즉시 노출).
        작업 화면은 REFRESH_ON_NAV 에 있어 이 액션이 레일 복귀마다 발화하므로, 타 화면에서의
        삭제(그 화면으로 가려면 반드시 작업 화면을 이탈)가 복귀 시점에 잡힌다.
        """
        if self.job_name and self.job_name not in self.registry.names():
            # 세션 무효화(vm·job_name·데이터·폴더 clear). confirm=True — 작업이 이미
            # 레지스트리에서 사라져 가드로 잡아둘 대상이 없다(잡으면 유령 세션 좌초).
            self._do_select_job({"name": "", "confirm": True})

    def _do_select_job(self, p: dict) -> "dict | None":
        """좌 목록 클릭 → RunViewModel 재구성(패널 세션 진입). 저장 폴더 기본 = 템플릿/Results.

        **T1 세션 가드(결정 26·27)**: 무장 상태(재현 불가능한 수작업 선택)에서 다른 작업으로
        전환하면 파괴를 먼저 재진술한다 — ``needs_confirm`` 반환(무변이), 표면이 modal.js
        이진 확인(기본 포커스=머무르기) 후 ``confirm=True`` 로 재호출(RC-02 왕복 동형).
        내부 경로(레지스트리 소실 무효화·재연결 재적재)는 confirm 승계로 통과한다.

        작업에 기본 데이터셋 참조(#53-A)가 있으면 실행 시점에 다시 읽어 자동 조준한다.
        """
        name = p["name"]
        if name != self.job_name and not p.get("confirm"):
            g = self._guard_state()
            if g["armed"]:
                return {"needs_confirm": True, "kind": "switch_job", "target": name, **g}
        self._clear_data_notice()
        self._stash_filter()  # 죽는 세션의 정의 → 직전 필터 슬롯(결정 28 — 저장 아닌 전달)
        self._last_generated = None  # 완주 담보는 세션 스코프 — 전환 시 소멸
        self.filter = None  # 필터 정의 = 세션 휘발(결정 8·24) — 작업 전환 시 소멸
        self._data_key = ""  # 데이터도 함께 죽는다 — 소스 키 무효
        if not name:  # 선택 해제 = 빈 패널
            self.vm = None
            self.selection = SelectionModel(0)
            self.job_name = ""
            self.data_label = ""
            self.data_source = ""
            self.out_dir = ""
            return
        job = self.registry.load(name)
        self.vm = RunViewModel(job)
        self.selection = SelectionModel(0)
        self.job_name = name
        self.data_label = ""
        self.data_source = ""
        self.out_dir = (
            str(Path(job.template_path).parent / OUTPUT_SUBDIR_NAME)
            if job.template_path else ""
        )
        if job.default_dataset_ref:
            self._auto_aim_default(job.default_dataset_ref)

    def _clear_data_notice(self) -> None:
        self.data_notice_text = ""
        self.data_notice_level = ""

    def _auto_aim_default(self, ref: str) -> None:
        """저장된 기본 데이터셋을 실행 시점에 다시 읽어 자동 조준(#53-A).

        실패(참조 부재·죽은 파일·모호 시트·나라 동결·레코드 0건)는 **조용한 폴백 금지** —
        데이터 미겨눔으로 남기고 원인·복구 동선을 시끄럽게 재진술한다(confirm-or-alarm).
        A-1-11 승계: 동기 I/O 지연·표시 부재 우려는 이슈 #65 가 소비 시점에 재평가.
        """
        res = load_pool_into(self.pool_registry, ref, self.vm.load_pool_item)
        if res["ok"]:
            self.data_label = ref
            self.data_source = "pool"
            self._after_pool_load(res["records"])
            self.data_notice_text = (
                f"기본 데이터 '{ref}' 를 자동으로 연결했습니다. 실행 시점에 다시 읽었습니다."
            )
            self.data_notice_level = "ok"
        else:
            self.data_notice_text = (
                f"기본 데이터 '{ref}' 를 자동으로 열 수 없습니다: {res['error']}\n"
                "다른 데이터를 직접 선택하거나 데이터 관리에서 참조를 다시 연결하세요."
            )
            self.data_notice_level = "warn"

    def _do_relink_template(self, p: dict) -> dict:
        """작업 템플릿 다시 연결(#67) — 공유 확정 게이트 위임 + 기선택 작업 재적재.

        커밋된 작업이 지금 패널에 선택돼 있으면 옛 경로의 VM 이 stale 이므로 ``_do_select_job``
        으로 재구성한다 — 데이터 겨눔·저장 폴더를 초기화하므로 결과 문구로 재진술(confirm-or-alarm).
        """
        res = relink_job_template(
            self.registry, p["name"], p.get("path", ""), confirm=bool(p.get("confirm")),
        )
        if res.get("relinked") and self.vm is not None and self.vm.job.name == p["name"]:
            self._do_select_job({"name": p["name"]})
            res["restated"] = (
                "템플릿을 다시 연결했습니다. 작업을 다시 불러왔으니 데이터와 저장 폴더 "
                "선택을 확인하세요."
            )
        elif res.get("relinked"):
            res["restated"] = "템플릿을 다시 연결했습니다."
        return res

    # --------------------------------------------- 좌 목록 관리(결정 43·R-info 결정 5·7)
    def _do_toggle_group(self, p: dict) -> None:
        """그룹 접힘/펼침 토글 — 마지막 상태를 Python 설정에 영속(결정 6-①, #74 전례).

        접힘은 **보기**만 바꾼다: 행은 집합에서 빠지지 않아 선택·세션 판정에 무영향
        (결정 6-⑤ 접어도 선택 유지). ``""`` 는 「그룹 없음」 구획.
        """
        g = p["group"]
        if g in self._collapsed:
            self._collapsed.discard(g)
        else:
            self._collapsed.add(g)
        save_job_collapsed_groups(sorted(self._collapsed))

    def _do_rename_job(self, p: dict) -> dict:
        """작업 이름 변경(인라인 편집 커밋) — 검증 실패는 ``{"ok": False, error}`` 재진술.

        열린 세션의 작업이면 세션 정체(``job_name``·VM)가 새 이름을 **추종**한다 — 이름
        변경은 비파괴(같은 작업)라 가드 없이 조용히 따라가되, 헤더가 즉시 새 이름을
        재진술하므로 변경이 보인다(전면 가시성).
        """
        name, new = p["name"], p.get("new", "")
        try:
            self.registry.rename(name, new)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        if self.job_name == name:
            new_clean = new.strip()
            self.job_name = new_clean
            if self.vm is not None:
                self.vm.job.name = new_clean
        return {"ok": True}

    def _do_clone_job(self, p: dict) -> dict:
        """작업 복제 — 레지스트리 clone(유일 이름 합성·이력 미계승) 위임. 그룹 계승 = 인접."""
        return {"ok": True, "name": self.registry.clone(p["name"])}

    def _do_delete_job(self, p: dict) -> "dict | None":
        """작업 삭제 — 무확인 호출은 재진술 자료를 돌려주고 멈춘다(RC-02 왕복 동형).

        열린 세션의 작업이면 세션도 함께 닫힌다 — 재진술에 ``open_session`` 과 무장 수치
        (:meth:`_guard_state`)를 동봉해 표면이 파괴 전모(durable 삭제 + 세션 선택 소실)를
        한 모달로 말하게 한다(confirm-or-alarm).
        """
        name = p["name"]
        if not p.get("confirm"):
            out = {"needs_confirm": True, "name": name,
                   "open_session": name == self.job_name}
            if name == self.job_name:
                out.update(self._guard_state())
            return out
        self.registry.delete(name)
        if name == self.job_name:
            # 세션 주체가 사라졌다 — 빈 패널로 재진술(레지스트리 소실 무효화와 동일 경로).
            self._do_select_job({"name": "", "confirm": True})

    def _do_set_group(self, p: dict) -> None:
        """그룹 지정/해제(이동 다이얼로그 확정) — ``group=""`` 는 「그룹 없음」으로 이동.

        새 그룹 = 다이얼로그의 새 이름 입력이 이 액션으로 그대로 들어온다(소속=생성,
        빈 그룹 불가 불변식은 모델 구조가 담보).
        """
        self.registry.set_group(p["name"], p.get("group", ""))

    def _do_rename_group(self, p: dict) -> dict:
        """그룹 이름 변경 — 새 이름이 **기존 그룹**이면 병합이므로 확인 승격(무확인 반환).

        순수 개명이면 접힘 상태를 새 이름으로 승계한다(이름만 바뀐 같은 그룹). 병합이면
        대상 그룹의 접힘 상태를 존중하고 옛 이름만 접힘 집합에서 걷는다.
        """
        old, new = p["name"], p.get("new", "").strip()
        if not new:
            return {"ok": False, "error": "그룹 이름이 비어 있습니다."}
        if new == old:
            return {"ok": True, "count": 0}
        target_members = sum(1 for j in self.registry.list_jobs() if j.group == new)
        if target_members and not p.get("confirm"):
            count = sum(1 for j in self.registry.list_jobs() if j.group == old)
            return {"needs_confirm": True, "kind": "merge_group", "name": old,
                    "new": new, "count": count, "target_count": target_members}
        count = self.registry.rename_group(old, new)
        if old in self._collapsed:
            self._collapsed.discard(old)
            if not target_members:
                self._collapsed.add(new)
            save_job_collapsed_groups(sorted(self._collapsed))
        return {"ok": True, "count": count}

    def _do_disband_group(self, p: dict) -> dict:
        """그룹 해산(결정 43) — 무확인 호출은 소속 수 재진술로 멈춘다. 소속은 「그룹 없음」으로."""
        name = p["name"]
        if not p.get("confirm"):
            count = sum(1 for j in self.registry.list_jobs() if j.group == name)
            return {"needs_confirm": True, "name": name, "count": count}
        count = self.registry.disband_group(name)
        if name in self._collapsed:
            self._collapsed.discard(name)
            save_job_collapsed_groups(sorted(self._collapsed))
        return {"ok": True, "count": count}

    # (행 선택 4액션·필터 12액션·직전 필터 슬롯·소스 키는 DataZoneMixin 으로 이동 —
    #  슬라이스 6 PR-2b: txt 큐가 같은 존을 재사용한다. data_zone.py 가 정본.)

    def _records(self) -> list:
        return self.vm.records if self.vm is not None else []

    def _init_filter(self) -> None:
        """데이터 겨눔 시 필터 신설(결정 24) — 설치는 믹스인, 힌트(매핑 확정 유형)는 화면 몫."""
        records = self.vm.records if self.vm is not None else []
        hints = {
            m.source: m.type
            for m in (self.vm.job.mapping.mappings if self.vm is not None else [])
            if m.source and m.type in (KIND_TEXT, KIND_DATE, KIND_AMOUNT)
        }
        self._install_filter(records, hints)
        self._last_generated = None  # 완주 집합의 인덱스는 이전 데이터 좌표 — 교체 시 무효

    def _do_ack_field(self, p: dict) -> None:
        """미입력 배지 클릭 = 직접 확인(강제 상호작용, ADR-E). 다 확인되면 생성이 열린다."""
        if self.vm is None:
            raise ValueError("작업이 선택되지 않았습니다.")
        self.vm.acknowledge(p["field"])

    def _do_unack_field(self, p: dict) -> None:
        """ack 칩 재클릭 = 확인 철회(UD-19 토글) — 게이트가 다시 닫힌다."""
        if self.vm is None:
            raise ValueError("작업이 선택되지 않았습니다.")
        self.vm.unacknowledge(p["field"])

    # -------------------------- 등록 데이터(풀) 겨눔(#26/#6) — 공용 래퍼(K4)의 화면별 훅
    def _pool_guard(self) -> "str | None":
        """겨눔 전제 = 작업 선택 — 미선택이면 공용 래퍼가 오류 dict 로 재진술한다."""
        return "먼저 작업을 선택하세요." if self.vm is None else None

    def _after_pool_load(self, records: list) -> None:
        """풀 겨눔도 파일과 동일하게 새 데이터 = 전체 선택·ack·필터 초기화를 탄다."""
        self._stash_filter()  # 죽는 세션의 정의 → 슬롯(옛 소스 키 기준 — 키 갱신 전에)
        self._data_key = self._pool_key()  # 라벨은 믹스인/자동 조준이 이미 세팅
        self.selection = SelectionModel(len(records))  # 데이터 변경 → 전체 선택 초기화
        self._init_filter()  # 데이터 교체 = 필터 재생성(결정 24)
        self._clear_data_notice()  # 사용자가 직접 겨눔 → 자동 조준 재진술 소거

    # ------------------------------------------------------------------ 생성
    def _push_progress(self, done: int, total: int) -> None:
        """생성 진행 델타 — 전체 스냅샷 재계산(템플릿 재파싱) 없이 진행바만 갱신."""
        self._push_sink(self.name, {"progress": {"done": done, "total": total}})

    def generate(self, *, confirm_overwrite: bool = False) -> dict:
        """게이트 통과 시 동기 생성 → 결과 dict. 덮어쓰기는 웹 재진술 후 재호출(RC-02).

        슬라이스 1은 실행 화면과 동일한 링1 계약을 배선한다 — 게이트 판정·덮어쓰기 재진술의
        표현(재진술 블록·modal.js)은 슬라이스 2(블록 6)가 광택한다.
        """
        if self.vm is None:
            return {"ok": False, "error": "먼저 작업을 선택하세요.", "level": "warn"}
        indices = self._indices()
        out_dir = self.out_dir

        # 1) 기본 가드(데이터·폴더·레코드·구조 드리프트) — 링1 단일 판정.
        errors = self.vm.validate_generate(indices, out_dir)
        if errors:
            return {"ok": False, "error": errors[0].message, "level": errors[0].level}

        # 2) 미입력 강제 확인 게이트(ADR-E) — 버튼이 이미 비활성이어도 방어적 재확인.
        unmet = self.vm.unmet_blanks(indices)
        if unmet:
            return {
                "ok": False, "level": "warn",
                "error": "미입력 필드를 먼저 확인하세요: " + ", ".join(unmet),
            }

        # 3) 미입력 표식(확인된 빈칸) — 완료 요약이 병기한다(낙관 서사 해소).
        blanks = self.vm.blank_fields(indices)
        self._marked_fields = list(blanks)
        marker = MISSING_MARKER if blanks else ""

        # 4) 덮어쓰기 확인(RC-02) — 미리보기가 캡처한 날짜 토큰 시각을 재사용(표시=확인=생성 일치).
        #    수치 합성(결정 36): 총량·파괴분(덮어씀)·신규분을 종류별로 재진술한다(블록 4 가드
        #    형식 "종류별 수치 재진술" 승계). 모달은 파괴 지점=덮어쓰기에만 선다. 표면(job.js)이
        #    이 수치로 modal.js 본문을 합성한다 — 별도 재진술 모달을 만들지 않는다.
        now = self._names_now or datetime.now()
        conflicts = self.vm.output_conflicts(indices, out_dir, mark_missing=marker, now=now)
        if conflicts and not confirm_overwrite:
            names = [Path(p).name for p in conflicts]
            return {
                "ok": False, "needs_overwrite": True,
                "total": len(indices),                      # 총량
                "overwrite_count": len(conflicts),          # 파괴분(기존 덮어씀)
                "new_count": len(indices) - len(conflicts),  # 신규분(새 파일)
                "conflict_names": names[:10],               # 파괴분 표본
                "conflict_more": max(0, len(names) - 10),
            }
        overwrite = bool(conflicts)

        # 5) 불변 생성 계획(RC-07) → 동기 생성(진행 델타 푸시).
        plan = self.vm.build_generation_plan(
            indices, out_dir, marker=marker, overwrite=overwrite, now=now
        )
        self._push_progress(0, len(plan.records))
        batch = generate_batch(
            plan.template, list(plan.records), plan.out_dir, plan.pattern,
            now=plan.now, overwrite=plan.overwrite, mapping=plan.mapping,
            progress=self._push_progress,
        )

        # 완료 이벤트 = 가드 무장 해제(결정 27) — 단 **완주**(전건 성공)만이다(고효율 리뷰
        # #1): 부분 실패 런에서 해제하면 실패분 재시도에 필요한 수작업 선택이 무확인
        # 파괴 가능해지고, 전환이 세션 지문을 바꿔 실패 목록(완료 존)까지 지워져 "내역은
        # 완료 존이 담보"의 전제가 깨진다.
        if batch.failed == 0:
            self._last_generated = set(indices)

        summary = f"완료. 성공 {batch.succeeded}/{batch.total}, 실패 {batch.failed}."
        if blanks:
            summary += f" 미입력 표시 필드 {len(blanks)}개({', '.join(blanks)})."
        failures = [
            f"{Path(r.output_path).name}: {describe_result_error(r.error)}"
            for r in batch.results if not r.ok
        ]
        return {
            "ok": True,
            "summary": summary,
            "level": "ok" if batch.failed == 0 else "danger",
            "out_dir": plan.out_dir,
            "succeeded": batch.succeeded,
            "failed": batch.failed,
            "total": batch.total,
            "failures": failures,
        }
