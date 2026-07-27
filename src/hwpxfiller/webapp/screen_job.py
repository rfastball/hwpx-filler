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
  입력 성분(블록 5, 슬라이스 7). **T3**(기안 큐 부분 진행)은 기안 세션 공용 본체
  (:class:`~hwpxfiller.webapp.draft_session.DraftSessionMixin`)가 진다 — 술어 몸통은 이 화면과
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
- 생성 원장 opt-in. 협조적 취소(RC-06)는 #220에서 건 경계 중단으로 배선됐다.
덮어쓰기 확인·미입력 강제 확인 게이트·구조 드리프트 차단·미입력 표식·다중 시트 확정
게이트(#33)는 모두 포함한다.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import threading

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
from ..gui.result_errors import classify_result_error, describe_fill_note
from ..gui.run_state import RunViewModel, resolve_file_source, resolve_pool_source
from ..gui.selection_state import SelectionModel
from ..gui.work_candidates import (
    KIND_NEEDS_ACTION,
    MAIN_TOP_N,
    TAB_AVAILABLE,
    TAB_NEEDS_ACTION,
    browse_candidates,
    candidate_rows,
    prework_gate,
    preferred_promotion,
    rank_available,
    suggested_work,
)
from .job_list import drift_note
from .settings import load_job_collapsed_groups, save_job_collapsed_groups
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

# 사전검증 성공 문구는 링2 사용자 어휘로 순화한다(실행 화면 _PREFLIGHT_OK_TEXT 동형).
_PREFLIGHT_OK_TEXT = "검증 완료. 생성할 수 있습니다."

# 데이터 미겨눔 상태의 재진술 빈 골격 — 필터/테이블 골격은 데이터 존 공유 믹스인
# (data_zone.EMPTY_*)이 소유한다(PR-2b).
_EMPTY_RESTATE = {
    "origin": None, "filter_active": False, "in_def": 0, "extra": 0, "sample": [],
}

# 재진술 이름 목록 표본 크기 — 소량(≤N)=전부, 대량=층화 표본 N + 「외 …건 펼치기」(결정 5·36).
_RESTATE_SAMPLE = 3


def _run_status(succeeded: int, total: int, cancelled: bool = False) -> str:
    """결과 3태(계약 §10 · 지도 §10.10 판정 A) — 성공/전체 + 중단 여부의 함수다.

    불변식 §13-10("일부 성공을 전체 성공으로 표시하지 않는다")이 경계를 정한다: 전건
    성공만 ``completed``, 1건이라도 성공했고 남은 게 있으면 ``partiallyCompleted``,
    성공 0건은 ``failed``. **취소는 네 번째 태가 아니라** ``partiallyCompleted`` 의
    변종이다(``cancelled`` 플래그 + 미착수 재진술 + warn 채널) — 태를 늘리면 "중단"이
    성공·실패와 같은 층위인 것처럼 읽힌다. 표면은 이 판정을 재계산하지 않는다.

    그래서 **중단은 성공 수와 무관하게** 부분이다(1R P2): 첫 레코드 전에 멈춘 런은
    성공 0·실패 0인데 성공 수만 보면 ``failed`` 가 되어, "중단했습니다 · 0개 완료"라고
    말하는 제목 옆에서 태가 "실패"라고 다른 얘기를 한다. 실패한 시도가 없는데 실패
    태를 다는 것은 없던 실패를 지어내는 쪽이다 — 중단은 완주하지 않은 **중간 상태**이고
    그것이 부분 태의 뜻이다(실패분이 있으면 실패 행이 그 사실을 따로 나른다).
    """
    if cancelled:
        return "partiallyCompleted"
    if total > 0 and succeeded >= total:
        return "completed"
    if succeeded > 0:
        return "partiallyCompleted"
    return "failed"


def _run_title(status: str, cancelled: bool, succeeded: int, failed: int) -> str:
    """3태 제목 — 취소는 태를 바꾸지 않고 제목이 그 사실을 **먼저** 말한다.

    문안이 Python 에 있는 이유는 요약(``summary``)과 같다: 같은 수치를 두 층이 따로
    조립하면 제목과 요약이 갈라진다(공유 합성기 규율).
    """
    if cancelled:
        return f"생성을 중단했습니다 · {succeeded}개 완료"
    if status == "completed":
        return f"문서 생성 완료 · {succeeded}개"
    if status == "partiallyCompleted":
        return f"{succeeded}개 성공 · {failed}개 실패"
    return "문서 생성 실패"


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
        # 세션 소유 데이터(data-first 봉합, §18.2 보존 계약) — 마운트된 datasource·records 는
        # 컨트롤러(세션)가 보유해 **작업 전환에서 생존**한다. vm 은 재생성 시
        # ``set_acquired`` 로 이 상태를 주입받는 소비자다(RC-22 원자 진입점 재사용).
        self.datasource = None
        self.records: "list[dict]" = []
        self.selection = SelectionModel(0)
        # 필터 선언 상태(블록 4, 결정 23~25) — 스코프 = 세션(작업×데이터, 결정 24).
        # 데이터 겨눔 시 생성, 작업 전환·데이터 교체 시 재생성(전환 인계는 PR-4 결정 28).
        self.filter: "FilterModel | None" = None
        # 마지막 생성 완주 집합(결정 27) — 완료 이벤트 = 무장 해제(내역은 완료 존이 담보).
        self._last_generated: "set[int] | None" = None
        # 직전 런의 실패 레코드 원본 index(지도 §10.10 판정 F) — 「실패한 N건만 선택」의
        # 소재. **Python 이 소유**한다: 웹이 들고 있다 되돌려주면 그 사이의 데이터 교체·
        # 표시순서 변경이 남의 행을 고른다. 수명 = 이 데이터·이 작업(둘 중 하나가 바뀌면 비운다).
        self._last_failed: "list[int]" = []
        # 직전 필터 슬롯(결정 28) — 정의 가진 세션이 죽을 때 덮어쓰는 1칸 세션 메모리
        # (앱 수명·미저장 — 필터 영속 뒷문 금지). 소스 일치 게이트용 키와 쌍.
        self._last_filter: "dict | None" = None  # {"source_key": str, "state": dict}
        self._data_key = ""  # 현 데이터 소스 정체(file:경로 | pool:참조) — 소스 일치 판정
        self.job_name = ""  # 후보·탐색에서 겨눈 작업(패널 세션의 주체)
        # 문서 탐색 상태(§18.6) — 탭·검색어는 **세션 소유**다: 탭을 옮겨도 검색어가 살아야
        # 하고(계약 명문), 시트를 닫고 다시 열어도 방금 찾던 자리로 돌아온다. 스크롤·포커스는
        # 기존 보존 기제(preserve.js) 소관이라 여기 두지 않는다.
        self.browse_tab = TAB_AVAILABLE
        self.browse_query = ""
        # preferredWorkId(§18.3 개정 1행) — 라이브러리 「문서 만들기에서 사용」이 낸 **명시
        # 사건**을 데이터가 준비되는 시점까지 들고 있는 자리. 슬2가 규칙만 박제하고 비워
        # 뒀던 seam 이며, 그 사건의 유일한 원천이 F2 에서 섰다. 승격·소비 규칙은
        # :meth:`_apply_preferred_work`.
        self.preferred_work = ""
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
        self._cancel_generation = threading.Event()
        self._generation_lock = threading.Lock()
        # 등록 데이터(풀) 겨눔(#26/#6) — 기본은 홈 레지스트리, 테스트는 주입.
        self.pool_registry = (
            pool_registry if pool_registry is not None else default_pool_registry()
        )

    # ------------------------------------------------------------- 관측 푸시
    def _push(self) -> None:
        self._push_sink(self.name, self.snapshot())

    # ------------------------------------------------------------- 스냅샷
    def _display_indices(self, indices: "list[int]") -> "list[int]":
        """표시 순서 = sourceDesc(§18.10, 충돌 B 확정 2026-07-26) — 최신 행(마지막 원본
        행)이 먼저다. 표 렌더·실행 입력이 이 한 훅을 공유한다(보이는 것=실행되는 것)."""
        return sorted(indices, reverse=True)

    def _indices(self) -> "list[int]":
        """실행 입력 = OrderedSelection(§2): 선택 집합을 **전체 표시순서에 투영**한다.

        생성·미리보기·거울이 전부 이 순서를 소비한다 — 순번 토큰(``{{seq}}``)과 동명
        꼬리표(``naming._dedupe``)가 화면에 보이는 위→아래 순서를 그대로 따른다(WYSIWYG).
        같은 선택이라도 표시 순서가 다르면 파일명이 달라질 수 있다 — 인지하고 수용한
        확정(봉합 지도 §2)이며, 완화는 파일명 미리보기가 같은 투영을 보여주는 것이다.
        """
        return self._display_indices(self.selection.selected_indices())

    def _candidate_payload(self, jobs) -> dict:
        """현재 데이터에 대한 문서 작업 후보(§18.4)+메인 순위(§18.5·§19.3) — 판정·정렬 모두
        링1 단일 출처 소비.

        데이터 미준비면 빈 구획(§18.1 — 계산 자체를 하지 않는다). ``jobs`` 는 문서 탐색과
        같은 스캔 1회 결과를 받아 목록·후보가 갈라지지 않는다. fields 는 필터 열 파생과
        같은 원천(``records[0].keys``) — 표시와 판정이 같은 열 집합을 본다.

        반환 5구획:

        - ``top`` = 상위 :data:`~hwpxfiller.gui.work_candidates.MAIN_TOP_N` available,
          순위순. 카드가 그릴 근거(계층·즐겨찾기·마지막 실행·추천 표지)를 함께 싣는다.
        - ``more`` = 순위 밖 available 수. 0이 아니면 표면이 **정직하게 고지**한다 —
          전체 목록 표면(문서 탐색)은 슬라이스 3 소관이라 지금은 수치만 말한다.
        - ``needs``·``needs_more`` = 확인 필요(needs_action) 이름순 상위 N + 잘린 수.
          메인 순위엔 못 들어가지만(§18.5) 전용 표면(확인 필요 탭)이 생기기 전까지 막힌
          이유를 여기서 계속 말한다(삭제는 의무를 상속한다). available 과 같은 상한을
          두는 건 데이터 존이 비활성 칩으로 넘치지 않게 하기 위함이고, 잘린 만큼은
          available 과 똑같이 수치로 고지한다.
        - ``suggested`` = 추천 작업 이름(§18.3 개정, 없으면 ``""``).
        """
        empty = {"top": [], "more": 0, "needs_count": 0, "suggested": ""}
        if self.datasource is None or not self.records:
            return empty
        fields = list(self.records[0].keys())
        by_name = {j.name: j for j in jobs}
        ranked = rank_available(jobs, fields)
        suggested = suggested_work(ranked, active=self.job_name)
        top = []
        for r in ranked[:MAIN_TOP_N]:
            job = by_name[r.name]
            top.append({
                "name": r.name,
                "tier": r.tier,
                "favorited": bool(job.favorited_at),
                # 원시 ISO — 표시 문안(자릿수·구분자)은 표면이 만든다(판정만 Python).
                # 의미는 **완주(전건 성공) 실행**이다(지도 §8.2 ②).
                "last_run_at": job.last_run_at,
                "suggested": r.name == suggested,
            })
        needs = sorted(
            (
                {"name": j.name, "missing": list(c.missing)}
                for j, c in candidate_rows(jobs, fields)
                if c.kind == KIND_NEEDS_ACTION
            ),
            key=lambda d: d["name"],
        )
        return {
            "top": top,
            "more": max(0, len(ranked) - MAIN_TOP_N),
            # 확인 필요 전체는 문서 탐색(§18.6)이 소유한다 — 후보 줄엔 **수치만** 남긴다
            # (슬라이스 3: 칩 구획 이사, 삭제는 의무를 상속한다).
            "needs_count": len(needs),
            "suggested": suggested,
        }

    def _browse_payload(self, jobs) -> dict:
        """문서 탐색 구획(§18.6·§19.5) — 탭·검색 판정은 링1 단일 출처 소비.

        데이터 미준비면 빈 골격이다(§18.1 — 후보를 계산하지 않으므로 탐색도 없다). 시트가
        열려 있는지는 표면 상태라 여기서 모른다: 판정은 언제나 최신이고, 열지 않았으면
        아무도 안 본다(스냅샷 분기보다 단순한 쪽).
        """
        empty = {
            "tab": self.browse_tab, "query": self.browse_query, "rows": [],
            "available_count": 0, "needs_count": 0, "filtered_out": 0,
        }
        if self.datasource is None or not self.records:
            return empty
        res = browse_candidates(
            jobs, list(self.records[0].keys()),
            tab=self.browse_tab, query=self.browse_query,
        )
        return {
            "tab": res.tab,
            "query": self.browse_query,
            "rows": [dict(r) for r in res.rows],
            "available_count": res.available_count,
            "needs_count": res.needs_count,
            "filtered_out": res.filtered_out,
        }

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

        if self.vm is None:
            return []  # 작업 미선택 = 파일명 네임스페이스 부재 — 토큰 모드 입력 없음
        tokens = set(pattern_field_tokens(self.vm.job.filename_pattern))
        present = set(self.records[0].keys()) if self.records else set()
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
        if not self.records:
            return []
        from ..naming import plan_output_names

        names: "dict[int, str]" = {}
        if indices and self.vm is not None:  # 파일명은 작업 속성 — 미선택이면 미리보기 없음
            self._names_now = datetime.now()
            planned = plan_output_names(
                self.vm.job.filename_pattern, mapped, now=self._names_now,
            )
            names = dict(zip(indices, planned, strict=True))
        isum = identity_summary(
            self.records, filename_tokens=self._filename_source_columns()
        )
        # 목록 순서 = 표시순(sourceDesc) — 각 행은 원본 index 를 지녀 선택·토글이 안전하다.
        return [
            {
                "index": i,
                "selected": self.selection.is_selected(i),
                "name": names.get(i, ""),
                "summary": isum.display_for(self.records[i]),  # 표시=빈 세그먼트를 마커(빈칸)로 채워 위치 보존(생략 아님 — 서로 다른 행이 동일 문자열로 붕괴하는 것 차단)
            }
            for i in self._display_indices(list(range(len(self.records))))
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
            return "(비움 확정)"
        n = len(mapped)
        vals = [str(r.get(name, "")) for r in mapped]
        if state == "missing":
            blank_n = sum(1 for v in vals if not v.strip())
            return f"(빈 값) 선택 {n}행 중 {blank_n}행에서 값이 비어 있습니다."
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
        if self.filter is None:  # 데이터 미겨눔 — 작업 미선택은 무관(데이터 존은 세션 소유)
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

        **``ack_count`` 는 열거 성분이지 무장 성분이 아니다**(재작성 F1, 지도 §10.7.3):
        데이터 전환은 ``set_acquired`` 로 빈 값 확인을 전량 재평가하므로 세워 둔 확인이
        있으면 가드 문안이 그 사실을 말해야 한다. 그렇다고 확인만으로 무장시키지는 않는다 —
        확인이 사라지면 게이트가 **다시 닫히는**(더 엄격해지는) 안전 방향이라, 결정 27 의
        "재현 불가능한 수작업" 기준에 확인은 들지 않는다. 과경고는 경보를 싸구려로 만든다.
        """
        guard = self._selection_guard(
            settled=set(self._last_generated or ()), vis_set=vis_set
        )
        guard["ack_count"] = self.vm.acked_count() if self.vm is not None else 0
        return guard

    def _do_guard_state(self, p: dict) -> dict:
        """무장 상태 실시간 질의 — 표면의 파괴 전이 사전 확인(데이터 재겨눔·재연결)이 소비.

        스냅샷 캐시(LAST.guard)는 왕복 지연·무푸시 경로(``generate`` 는 dispatch 밖이라
        push 가 없다)에서 stale 이 된다 — 판정은 항상 Python 이 지금 내린다(고효율 리뷰
        #4: 완주 직후 데이터 재겨눔에 거짓 확인 모달·#3: 무장 직후 창에 무확인 통과).
        """
        return self._guard_state()

    _do_guard_state.is_query = True  # 무변이 질의 — dispatch 가 push 를 생략한다

    def snapshot(self) -> dict:
        """세션 패널 스냅샷 — 필드는 실행 화면과 평행(링1 배선 감사 가능).

        존 배치는 job.js 소관(현재 데이터·거울·결과 / side-card 후보·정체·생성 준비).
        좌 목록 4키(``job_rows``·``job_sections``·``job_flat``·``job_group_names``)는 표면과
        함께 사망했다(F2 PR-B, 지도 §10.9 판정 F): 아무도 그리지 않는 페이로드가 남으면 다음
        세션이 그걸 근거로 목록을 되살린다. 저장된 작업의 전역 목록은 「문서 작업」 소관이다.
        """
        # 조회 경계(3부 결정 13 · 1층): 이 화면은 hwpx 워크플로 작업을 조회한다 — **txt 기안
        # 작업만 뺀다**(「기안」 화면 소관). 빈/미상 매체(템플릿 미링크 = 저작 중)는 남긴다:
        # 그것도 hwpx 작업이고, 여기서 빼면 막 만든 무템플릿 작업이 후보에서 사라진다.
        jobs = [j for j in self.registry.list_jobs() if j.media != "txt"]
        base = {
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
            # 마운트 대상 재진술(F1) — 데이터 선택 다이얼로그의 「현재 데이터」·고정 프리필.
            "data_target": self._data_target(),
            # 기본 데이터셋 자동 조준 재진술(#53-A) — 없으면 None.
            "data_notice": (
                {"level": self.data_notice_level, "text": self.data_notice_text}
                if self.data_notice_text else None
            ),
        }
        # 후보(§18.4) — 데이터 준비 시에만 계산(§18.1: 미준비면 계산 자체를 하지 않는다).
        # 판정 fields 는 필터 열 파생과 같은 원천(records[0].keys — 표시=판정 정합).
        base["candidates"] = self._candidate_payload(jobs)
        # 문서 탐색(§18.6) — 후보 줄의 「외 N건」·「확인 필요」가 여기로 이어진다.
        base["browse"] = self._browse_payload(jobs)
        if self.vm is None:
            # 작업 미선택 상태 — 데이터 존은 세션 소유라 그대로 산다(데이터-우선, §18.2).
            indices = self._indices()
            record_rows = self._record_rows(indices, [])
            filter_snap, table_snap, restate_snap, guard_snap = self._filter_sections(
                indices, record_rows
            )
            g = prework_gate(
                has_data=self.datasource is not None,
                selected_count=self.selection.selected_count(),
                # available 만 센다(#302 리뷰 P2) — needs_action 뿐이면 모든 후보 버튼이
                # 비활성이라 "선택하세요"는 이행 불가능한 지시(문안 정직성 위반)가 된다.
                # 순위 밖(more)도 선택 가능한 후보라 top 이 비어야만 "없음"이다.
                has_candidates=bool(base["candidates"]["top"]),
            )
            base.update({
                "template_name": "", "template_path": "", "filename_pattern": "",
                "template_missing": False,
                "has_data": self.datasource is not None,
                "record_count": len(self.records),
                "selected_count": self.selection.selected_count(),
                "records": record_rows,
                "preflight": {"level": "", "text": ""},
                "mirror": [], "drift": [], "name_tokens": [],
                "filter": filter_snap, "table": table_snap, "restate": restate_snap,
                "guard": guard_snap,
                # 게이트는 링1 단일 산출(prework_gate) 소비 — 링2 문안 재조립 금지(RC-23 동형).
                "gate": {"enabled": g.enabled, "level": g.level, "text": g.text},
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
            "has_data": self.datasource is not None,
            "record_count": len(self.records),
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
        """선택된 데이터 파일을 세션에 마운트. 레코드 0건이면 시끄럽게 실패.

        **데이터-우선(§18.2)**: 작업 미선택에도 마운트할 수 있다 — 데이터는 세션 소유고
        vm 은 있으면 ``set_acquired`` 로 주입받는다. 마운트 직후 선택은 **0건**이다
        (§18.2 commit 뒤 초기화 — 구 전체선택 계약의 개정, 봉합 지도 충돌 A).

        ``sheet`` 는 웹에서 확정한 시트명(다중 시트 확정 게이트 #33, None=CSV·단일 시트).
        시그니처 동형 — 브리지 ``pick_data_file``/``load_data_sheet`` 재사용.
        """
        if self._generation_lock.locked():  # 생성 중 데이터 교체 금지(#302 P1 동류)
            raise ValueError("문서 생성이 진행 중입니다. 중단하거나 완료된 뒤 데이터를 바꾸세요.")
        source, records = resolve_file_source(path, sheet=sheet)  # 실패는 raise(§18.2 원자)
        if not records:
            raise ValueError(NO_ROWS_TEXT)  # 성공 전 현재 runtime 미파기 — 아래 대입 전 반환
        self._stash_filter()  # 죽는 세션의 정의 → 직전 필터 슬롯(결정 28, 옛 소스 키 기준)
        self._last_failed = []  # 실패 index 는 이 레코드 집합에서만 뜻이 있다(§10.10 판정 F)
        self.datasource = source
        self.records = records
        if self.vm is not None:
            self.vm.set_acquired(source, records)  # ack 재평가 포함(RC-22)
        self.data_label = Path(path).name
        self.data_source = "file"  # 병기 라벨은 스냅샷이 합성(#26·K8)
        self.data_path, self.data_sheet = path, sheet or ""  # 「이 데이터 고정」 프리필(F1)
        self._data_key = self._file_key(path, sheet)  # 소스 일치 게이트(결정 28)
        self.selection = SelectionModel(len(records), all_selected=False)  # 선택 0건(§18.2)
        self._init_filter()  # 데이터 교체 = 필터 재생성(결정 24 — 열 지형이 바뀐다)
        self._clear_data_notice()  # 사용자가 직접 데이터를 겨눔 → 자동 조준 재진술 소거
        self._apply_preferred_work()  # 보관된 명시 사건(§18.3 1행)을 이 데이터에서 판정
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

    def _do_refresh(self, p: dict) -> "dict | None":
        """레지스트리 재스캔 반영(C6) + stale 세션 무효화(master-detail 불변식).

        레지스트리(``registry.names()``)와 세션 패널(``self.vm``)이 갈라지지 않게 조정한다: 선택된
        작업이 다른 화면에서 삭제·개명돼 레지스트리에서 사라졌으면 세션을 무효화한다 — 안 그러면
        존재하지 않는 작업의 라이브 세션이 활성 생성 버튼과 함께 남아 유령 작업에서 생성된다
        (리뷰 #2). 조용히 두지 않고 빈 패널로 재진술(후보·라이브러리에서도 사라져 상실이 보인다).
        재스캔 자체는 스냅샷이 매번 ``names()`` 를 재읽어 반영(에디터 저장분 즉시 노출).
        작업 화면은 REFRESH_ON_NAV 에 있어 이 액션이 레일 복귀마다 발화하므로, 타 화면에서의
        삭제(그 화면으로 가려면 반드시 작업 화면을 이탈)가 복귀 시점에 잡힌다.
        """
        if self.job_name and self.job_name not in self.registry.names():
            lost = self.job_name
            # 세션 무효화(vm·job_name·데이터·폴더 clear). confirm=True — 작업이 이미
            # 레지스트리에서 사라져 가드로 잡아둘 대상이 없다(잡으면 유령 세션 좌초).
            self._do_select_job({"name": "", "confirm": True})
            return {
                "notice": f"'{lost}' 작업이 다른 화면에서 삭제되어 열어 둔 실행 세션을 닫았습니다."
            }
        return None

    def _do_select_job(self, p: dict) -> "dict | None":
        """후보·탐색에서 작업 선택 → RunViewModel 재구성. 저장 폴더 기본 = 템플릿/Results.

        **데이터-우선 보존 계약(§18.2)**: 데이터·선택·필터는 세션 소유라 작업 전환에서
        **생존**한다 — 전환은 vm 만 재생성하고 세션 데이터를 ``set_acquired`` 로 주입한다.
        전환이 잃는 것은 실행 증거(ack·완주 담보)뿐이고(§19.10) 게이트가 재검증을 강제하므로
        조용한 소실이 없다. 구 T1 스위치 가드(전환=세션 파기 재확인)는 파기 자체가 사라져
        함께 죽었다 — 가드 문안은 실제로 사라지는 집합과 일치해야 한다(과경고=거짓말).
        ``confirm`` 페이로드 키는 왕복 동형 유지를 위해 수용하되 더는 판정에 쓰지 않는다.

        작업에 기본 데이터셋 참조(#53-A)가 있으면 **세션에 데이터가 없을 때만** 자동
        조준한다 — 사용자가 이미 마운트한 데이터를 참조가 조용히 덮으면 §18.2 위반이다.
        """
        name = p["name"]
        # 생성 진행 중 전환 금지(#302 P1) — vm 교체가 진행 중 배치의 검증·계획과 경합한다.
        # 조용한 무시가 아니라 시끄러운 거부(raise → 셸 rejection 백스톱이 표면화).
        if self._generation_lock.locked():
            raise ValueError("문서 생성이 진행 중입니다. 중단하거나 완료된 뒤 작업을 전환하세요.")
        self._clear_data_notice()
        # 사용자가 직접 골랐다 = 보관된 명시 사건보다 최신 의사. 들고 있으면 다음 마운트에서
        # 옛 의도가 되살아나 방금 고른 작업을 밀어낸다(지연된 조용한 추측).
        self.preferred_work = ""
        self._last_generated = None  # 실행 증거는 세션 스코프 — 전환 시 소멸(§19.10)
        self._last_failed = []  # 실패 목록도 같은 증거 — 다른 작업의 실패를 고르지 않는다
        if not name:  # 선택 해제 = 작업만 내려놓는다(데이터 존은 그대로)
            self.vm = None
            self.job_name = ""
            self.out_dir = ""
            return
        job = self.registry.load(name)
        self.vm = RunViewModel(job)
        self.job_name = name
        if self.records:
            self.vm.set_acquired(self.datasource, self.records)  # ack 재평가 포함(RC-22)
            # 필터 열 유형 재조정(#302 리뷰 P2): 무작업 마운트의 필터는 값 스니핑만 탔다 —
            # 작업이 정해진 지금 매핑 확정 유형 힌트를 반영한다. 단 **정의 없는 필터만**
            # 재생성한다: 사용자가 이미 만든 정의는 유형 재판정이 술어를 조용히 떨어뜨릴
            # 수 있어 그대로 둔다(사용자 확정 > 유형 힌트 — 조작 순서 의존을 정의 유무의
            # 명시 규칙으로 환원).
            if self.filter is not None and not self.filter.is_active():
                self._init_filter()
        self.out_dir = (
            str(Path(job.template_path).parent / OUTPUT_SUBDIR_NAME)
            if job.template_path else ""
        )
        if job.default_dataset_ref and self.datasource is None:
            self._auto_aim_default(job.default_dataset_ref)

    # --------------------------------------- 「문서 만들기에서 사용」(§19.8 3분기)
    def _ranked_now(self) -> list:
        """현재 데이터 기준 available 순위 — 후보 구획과 **같은 링1 판정**을 재사용한다."""
        if self.datasource is None or not self.records:
            return []
        fields = list(self.records[0].keys())
        return rank_available(list(self.registry.list_jobs()), fields)

    def _do_prefer_work(self, p: dict) -> dict:
        """라이브러리 「문서 만들기에서 사용」의 착지 — §19.8 3분기를 **Python 이 가른다**.

        분기 판정(데이터 준비·호환)은 링1 술어가 이미 소유하므로 표면이 다시 계산하면 같은
        상태를 두 곳이 판정하게 된다(판정 단일 출처). 웹은 반환된 ``reason`` 으로 라우팅만
        한다.

        ```text
        데이터 ready + 호환   → 명시 선택(select_job) — RecordRangeState 는 세션 소유라 생존
        데이터 ready + 비호환 → 활성 불변 + 보관. 표면이 「확인 필요」 탭에서 사유를 보인다
        데이터 없음           → 보관만. 마운트 시 _apply_preferred_work 가 판정한다
        ```

        **비호환에서 활성으로 세우지 않는 이유**: 게이트가 닫힌 채 화면이 "이걸 만들 참"이라고
        말하게 된다. 계약도 그 경우 선택이 아니라 **사유 표면**으로 보내라고 적는다(§19.8).
        """
        name = str(p.get("name", "")).strip()
        if not name:
            raise ValueError("겨눌 작업 이름이 비어 있습니다.")
        if not self.registry.exists(name):
            raise ValueError(f"'{name}' 작업을 찾을 수 없습니다.")
        self.preferred_work = name
        if self.datasource is None or not self.records:
            # 데이터가 없고 그 작업이 **기본 데이터 참조**(#53-A)를 가졌으면 보관에서 그치지
            # 않고 연다(F2 PR-B 판정 I). 좌 목록이 죽기 전에는 목록 클릭이 이 경로의 진입이라
            # `_do_select_job` 의 자동 조준이 발화했는데, 목록이 죽으면 무데이터 상태에서
            # 작업을 겨눌 표면이 여기뿐이라 **보관만 하면 #53-A 가 도달 불가능해진다**
            # (기능 소실). §19.8 의 "확인 없이 데이터를 자동 교체하지 않는다"는 여전히 참이다
            # — 교체가 아니라 **빈 자리에 첫 마운트**이고, 결과는 `data_notice` 가 재진술한다.
            if self.registry.load(name).default_dataset_ref:
                self.preferred_work = ""       # 소비 — 지금 이뤄졌다
                self._do_select_job({"name": name})
                return {"promoted": True, "name": name, "reason": "default_data"}
            return {"stored": True, "reason": "no_data", "name": name}
        if any(r.name == name for r in self._ranked_now()):
            self.preferred_work = ""  # 소비 — 지금 이뤄졌다
            self._do_select_job({"name": name})
            return {"promoted": True, "name": name}
        return {"stored": True, "reason": "incompatible", "name": name}

    def _apply_preferred_work(self) -> None:
        """마운트 직후 보관된 명시 사건을 판정한다(§18.3 개정 1행). **1회 소비**.

        판정은 링1(:func:`preferred_promotion`)이 내고 여기서는 그 결과를 세션에 반영만
        한다. 올리지 못하는 경우에도 보관분을 **비운다** — 다음 마운트까지 들고 있으면
        사용자가 잊은 의도가 나중에 조용히 발화한다(지연된 조용한 추측 금지).

        올리지 못한 사유는 삼키지 않는다: 사용자가 방금 「이 작업을 쓰겠다」고 눌렀는데
        아무 일도 안 일어나면 그게 조용한 소실이다. 기존 활성 작업이 있어 계약이 유지를
        지시한 경우(§18.3 2행)와 이 데이터로 실행할 수 없는 경우를 갈라 재진술한다.
        """
        name, self.preferred_work = self.preferred_work, ""
        if not name:
            return
        if not self.registry.exists(name):  # 그사이 삭제·개명 — 유령을 겨누지 않는다
            self.data_notice_text = (
                f"「문서 작업」에서 고른 '{name}' 작업이 더는 없습니다."
            )
            self.data_notice_level = "warn"
            return
        ranked = self._ranked_now()
        promoted = preferred_promotion(
            ranked, active=self.job_name, preferred=name,
        )
        if promoted:
            self._do_select_job({"name": promoted})
            self.data_notice_text = f"「문서 작업」에서 고른 '{promoted}' 을(를) 열었습니다."
            self.data_notice_level = "ok"
            return
        if self.job_name:
            self.data_notice_text = (
                f"'{self.job_name}' 작업이 이미 열려 있어 '{name}' 으로 바꾸지 않았습니다. "
                "바꾸려면 아래 후보에서 직접 고르세요."
            )
        else:
            self.data_notice_text = (
                f"「문서 작업」에서 고른 '{name}' 은(는) 이 데이터로 실행할 수 없습니다. "
                "「확인 필요」에서 사유를 확인하세요."
            )
        self.data_notice_level = "warn"

    def _do_toggle_favorite(self, p: dict) -> dict:
        """즐겨찾기 지정/해제(§18.5) — 정렬 메타만 바꾸고 세션은 건드리지 않는다.

        활성 작업·매핑·파일명·검증·선택 어느 것도 폐기하지 않는다(§18.5 명문). 값은
        표면이 보내는 **의도한 상태**(``value``)다 — 현재 값을 여기서 뒤집으면 빠른 연속
        클릭이 서로의 결과를 되돌린다(토글 경합, #215 동류).

        지정 시각은 서버 시각으로 찍는다(정렬 근거를 표면이 정하지 않는다). 작업이 다른
        화면에서 사라졌으면 조용히 넘기지 않고 재진술한다 — 목록이 곧 다음 스냅샷에서
        갱신되므로 파괴는 없다.

        **시각은 레지스트리가 쓰기 잠금 안에서 찍는다**(리뷰 1R·6R P2): ①초 절단이면 1초 안의
        두 지정이 동률이 돼 "최신순"(§18.5)이 거짓이 되고, ②여기서 미리 찍으면 서로 다른 작업
        둘을 연속으로 별 찍을 때 스레드 스케줄링이 나중 클릭에 이른 시각을 줄 수 있다. 잠금 안
        스탬프는 쓰기 순서 = 시각 순서를 담보한다. (생성 스탬프 ``last_run_at`` 은 런 자체가
        초 단위보다 길어 같은 함정이 성립하지 않아 그대로 둔다.)
        """
        name = p["name"]
        try:
            self.registry.set_favorite(name, bool(p["value"]))
        except (FileNotFoundError, ValueError) as exc:
            return {"ok": False,
                    "error": f"'{name}' 작업의 즐겨찾기를 바꾸지 못했습니다: {exc}"}
        return {"ok": True}

    def _do_browse_tab(self, p: dict) -> None:
        """문서 탐색 탭 전환(§18.6) — **검색어는 유지한다**(계약 명문).

        미지 값은 링1이 사용 가능으로 퇴화시키므로(표면 오타가 빈 화면을 만들지 않는다)
        여기서는 받은 값을 그대로 세션에 둔다.
        """
        self.browse_tab = (
            TAB_NEEDS_ACTION if p.get("tab") == TAB_NEEDS_ACTION else TAB_AVAILABLE
        )

    def _do_browse_query(self, p: dict) -> None:
        """문서 탐색 검색어 갱신 — 대상은 작업 표시 이름만(§18.6, 판정은 링1)."""
        self.browse_query = str(p.get("text", ""))

    def _clear_data_notice(self) -> None:
        self.data_notice_text = ""
        self.data_notice_level = ""

    def _auto_aim_default(self, ref: str) -> None:
        """저장된 기본 데이터셋을 실행 시점에 다시 읽어 자동 조준(#53-A).

        실패(참조 부재·죽은 파일·모호 시트·나라 동결·레코드 0건)는 **조용한 폴백 금지** —
        데이터 미겨눔으로 남기고 원인·복구 동선을 시끄럽게 재진술한다(confirm-or-alarm).
        A-1-11 승계: 동기 I/O 지연·표시 부재 우려는 이슈 #65 가 소비 시점에 재평가.
        """
        res = load_pool_into(self.pool_registry, ref, self._load_pool_records)
        if res["ok"]:
            self.data_label = ref
            self.data_source = "pool"
            self._after_pool_load(res["records"])
            self.data_notice_text = f"기본 데이터 '{ref}' 를 자동으로 연결했습니다."
            self.data_notice_level = "ok"
        else:
            self.data_notice_text = (
                f"기본 데이터 '{ref}' 를 자동으로 열 수 없습니다: {res['error']}\n"
                "「데이터 선택」에서 다른 데이터를 고르거나 그 참조를 다시 연결하세요."
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

    # ----------------------------------- 관리 동사(표면은 라이브러리, 소유는 이 컨트롤러)
    # 좌 목록이 죽어도(F2 PR-B) 아래 넷은 남는다: 열린 세션의 정체(``job_name``·VM)와 결속돼
    # 있어 여기가 계속 소유하고, 「문서 작업」 상세·그룹 헤더가 **교차 화면 dispatch** 로
    # 부른다(지도 §10.8 판정 F). 라이브러리에서 재구현하면 거기서 이름을 바꾼 순간 열린
    # 세션이 없는 이름을 가리킨다. 반면 세션과 무관한 복제·삭제·복원과 그룹 접힘은 표면과
    # 함께 걷혔다 — 라이브러리가 자기 채널에서 소유한다(판정 F 정정분).
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

    def session_guard_for(self, name: str) -> "dict | None":
        """타 화면(홈) 삭제 가드 조회(#268 리뷰) — 이 화면이 ``name`` 에 무장 세션을 열어
        두었으면 가드 수치(+``screen``)를 돌려준다. 판정·수치는 :meth:`_guard_state` 단일
        출처를 재사용한다(문안이 실제 소실 집합과 어긋나지 않게)."""
        if name and name == self.job_name:
            g = self._guard_state()
            if g["armed"]:
                return {"screen": self.name, **g}
        return None

    def _do_cancel_generation(self, p: dict) -> dict:
        """진행 중인 문서를 완결한 뒤 다음 레코드부터 중단하도록 요청한다."""
        self._cancel_generation.set()
        return {"ok": True}

    def _do_select_failed(self, p: dict) -> dict:
        """「실패한 N건만 선택」 — 선택을 직전 런의 실패 레코드로 **교체**한다(§10.10 판정 F).

        **생성은 하지 않는다**: 의사표시 2클릭 분리(결정 28 「직전 필터 재적용」이 정의만
        복원하고 선택은 건드리지 않는 것과 같은 격 구분). 성공분 보존은 신설 기제가 아니라
        덮어쓰기 확인 왕복(RC-02)이 담보한다 — 재생성이 성공분을 겨누면 그 수치가 모달에
        선다. 재시도(건별 재실행·filename override)는 이 슬라이스 밖이다(F7 선행).

        목록이 비었으면(수명 경계를 지났거나 실패 없던 런) ``0`` 을 돌려 표면이 무동작을
        정직하게 말한다 — 아무 반응 없는 버튼은 결함으로 읽힌다(``_do_set_all`` 선례).
        """
        idx = [i for i in self._last_failed if 0 <= i < len(self.records)]
        if not idx:
            return {"selected": 0}
        self.selection.set_none()
        for i in idx:
            self.selection.toggle(i, True)
        return {"selected": len(idx)}

    def _do_set_group(self, p: dict) -> None:
        """그룹 지정/해제(이동 다이얼로그 확정) — ``group=""`` 는 「그룹 없음」으로 이동.

        새 그룹 = 다이얼로그의 새 이름 입력이 이 액션으로 그대로 들어온다(소속=생성,
        빈 그룹 불가 불변식은 모델 구조가 담보).
        """
        self.registry.set_group(p["name"], p.get("group", ""))

    def _drift_note(self, seen, count: int) -> str:
        """확인 시점 건수와 실제 이동 건수 어긋남 고지(#149) — 공용 job_list.drift_note 위임."""
        return drift_note(seen, count)

    def _recollapse(self, old: str, new: str) -> None:
        """사라진 그룹 이름의 접힘 영속을 정리한다(``new`` 가 있으면 그 이름으로 승계).

        접힘의 **표면**은 라이브러리로 넘어갔지만(지도 §10.8 판정 F) 그룹을 개명·해산하는
        동사는 여기가 소유하므로, 남는 유령 이름을 치우는 것도 여기다. 메모리 사본을 들지
        않고 영속 키를 그때그때 읽고 쓴다 — 표면 없는 두 번째 인메모리 소유자가 남으면
        라이브러리의 접힘과 갈라지고, 그게 제2 정본이다(키는 계속 공유).
        """
        collapsed = set(load_job_collapsed_groups())
        if old not in collapsed:
            return
        collapsed.discard(old)
        if new:
            collapsed.add(new)
        save_job_collapsed_groups(sorted(collapsed))

    def _do_rename_group(self, p: dict) -> dict:
        """그룹 이름 변경 — 새 이름이 **기존 그룹**이면 병합이므로 확인 승격(무확인 반환).

        순수 개명이면 접힘 상태를 새 이름으로 승계한다(이름만 바뀐 같은 그룹). 병합이면
        대상 그룹의 접힘 상태를 존중하고 옛 이름만 접힘 집합에서 걷는다.

        확인 문안의 건수는 **약속이 아니라 그 시점의 관측**이다(#149) — 실제 이동 건수는 잠금
        안 일괄 갱신이 세어 ``count`` 로 돌려주고, 확인 때 본 수(``seen``)와 다르면
        ``drift_note`` 로 함께 말한다.
        """
        old, new = p["name"], p.get("new", "").strip()
        if not new:
            return {"ok": False, "error": "그룹 이름이 비어 있습니다."}
        if new == old:
            return {"ok": True, "count": 0, "drift_note": ""}
        target_members = sum(1 for j in self.registry.list_jobs() if j.group == new)
        if target_members and not p.get("confirm"):
            count = sum(1 for j in self.registry.list_jobs() if j.group == old)
            return {"needs_confirm": True, "kind": "merge_group", "name": old,
                    "new": new, "count": count, "target_count": target_members}
        count = self.registry.rename_group(old, new)
        self._recollapse(old, new if not target_members else "")
        return {"ok": True, "count": count, "drift_note": self._drift_note(p.get("seen"), count)}

    def _do_disband_group(self, p: dict) -> dict:
        """그룹 해산(결정 43) — 무확인 호출은 소속 수 재진술로 멈춘다. 소속은 「그룹 없음」으로.

        재진술한 수는 그 시점의 관측이다 — 실제 이동 건수·어긋남 고지는 ``_drift_note``(#149).
        """
        name = p["name"]
        if not p.get("confirm"):
            count = sum(1 for j in self.registry.list_jobs() if j.group == name)
            return {"needs_confirm": True, "name": name, "count": count}
        count = self.registry.disband_group(name)
        self._recollapse(name, "")
        return {"ok": True, "count": count, "drift_note": self._drift_note(p.get("seen"), count)}

    # (행 선택 4액션·필터 12액션·직전 필터 슬롯·소스 키는 DataZoneMixin 으로 이동 —
    #  슬라이스 6 PR-2b: txt 큐가 같은 존을 재사용한다. data_zone.py 가 정본.)

    def _records(self) -> list:
        return self.records  # 세션 소유(데이터-우선) — vm 은 주입 소비자일 뿐

    def _init_filter(self) -> None:
        """데이터 겨눔 시 필터 신설(결정 24) — 설치는 믹스인, 힌트(매핑 확정 유형)는 화면 몫.

        작업 미선택 마운트(데이터-우선)에선 힌트 없이 값 스니핑만 쓴다 — 작업을 나중에
        선택해도 필터는 데이터 스코프라 재생성하지 않는다(§18.10: 필터는 가시성만).
        """
        hints = {
            m.source: m.type
            for m in (self.vm.job.mapping.mappings if self.vm is not None else [])
            if m.source and m.type in (KIND_TEXT, KIND_DATE, KIND_AMOUNT)
        }
        self._install_filter(self.records, hints)
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
    def _pool_loader(self):
        """세션 소유 풀 로더(데이터-우선) — 작업 미선택에도 겨눌 수 있다."""
        return self._load_pool_records

    def _load_pool_records(self, item) -> list:
        """풀 항목 → 세션 마운트. 0건이면 상태 불변(공용 관문이 문구 재진술).

        링1 리졸버(:func:`~hwpxfiller.gui.run_state.resolve_pool_source`)를 직접 소비한다 —
        vm 경유(``load_pool_item``)는 작업 선택을 전제해 데이터-우선과 어긋난다. vm 이
        있으면 같은 데이터를 ``set_acquired`` 로 주입(ack 재평가 포함, RC-22).
        """
        if self._generation_lock.locked():  # 생성 중 데이터 교체 금지(#302 P1 동류)
            raise ValueError("문서 생성이 진행 중입니다. 중단하거나 완료된 뒤 데이터를 바꾸세요.")
        source, records = resolve_pool_source(item)
        if not records:
            return []
        self.datasource = source
        self.records = records
        if self.vm is not None:
            self.vm.set_acquired(source, records)
        return records

    def _after_pool_load(self, records: list) -> None:
        """풀 겨눔도 파일과 동일하게 새 데이터 = 선택 0건(§18.2)·ack·필터 초기화를 탄다."""
        self._stash_filter()  # 죽는 세션의 정의 → 슬롯(옛 소스 키 기준 — 키 갱신 전에)
        self._last_failed = []  # 파일 마운트와 같은 수명(§10.10 판정 F)
        self._data_key = self._pool_key()  # 라벨은 믹스인/자동 조준이 이미 세팅
        self.selection = SelectionModel(len(records), all_selected=False)  # 선택 0건(§18.2)
        self._init_filter()  # 데이터 교체 = 필터 재생성(결정 24)
        self._clear_data_notice()  # 사용자가 직접 겨눔 → 자동 조준 재진술 소거
        self._apply_preferred_work()  # 보관된 명시 사건(§18.3 1행)을 이 데이터에서 판정

    # ------------------------------------------------------------------ 생성
    def _push_progress(self, done: int, total: int) -> None:
        """생성 진행 델타 — 전체 스냅샷 재계산(템플릿 재파싱) 없이 진행바만 갱신."""
        self._push_sink(self.name, {"progress": {"done": done, "total": total}})

    def _stamp_last_run(self, job_name: str, vm) -> str:
        """완주 런의 시각을 **그 런이 시작될 때 겨눴던 작업**에 영속 — 성공 시 ``""``, 실패 시 사유.

        디스크 재읽기 후 단일 필드 뮤테이션이다 — ``vm.job`` 은 작업 선택 시점의 인메모리
        사본이라 그것만 고쳐서는 아무 데도 남지 않고, 통째 저장은 세션이 들고 있던 옛 매핑으로
        디스크의 최신 편집을 되돌린다. 읽기-수정-쓰기는 레지스트리의 잠금된 경로
        (:meth:`~hwpxfiller.core.job.JobRegistry.stamp_last_run`)가 진다(리뷰 2R P1) —
        브리지 호출이 스레드별이라 에디터 저장과 **진짜로 겹치고**, 잠금 없이는 늦게 착지한
        저장이 상대의 변경을 통째로 되돌린다(스탬프가 매핑 편집을 지우거나 그 반대).

        **정체를 인자로 받는 이유**(Codex 리뷰 P1): 생성 중에도 후보 카드는 눌린다
        (busy 잠금은 ``[data-busy-lock]`` 선언 요소만 잠그는데 ``.job-item`` 엔 없다). 기본
        전체 선택 세션은 무장 상태가 아니라 전환이 확인도 거치지 않는다 — 브리지 호출이
        별도 스레드라 배치가 도는 사이 ``self.job_name``/``self.vm`` 이 B 로 바뀔 수 있고,
        그때 현재 상태를 읽어 스탬프하면 **A 의 완주가 B 의 역사로 기록되고 A 는 이력을
        잃는다**(없던 실행을 지어내는 쪽이라 조용한 누락보다 나쁘다).

        스탬프 실패를 삼키지 않는 이유(confirm-or-alarm): 문서는 이미 만들어졌으므로 예외로
        완료 서사(요약·실패 목록)를 날리는 건 더 큰 손실이고, 조용히 넘기면 홈 이력이
        아무 말 없이 이번 실행을 잃는다 — 그래서 **사유를 완료 요약에 병기**한다.
        """
        try:
            job = self.registry.stamp_last_run(
                job_name, datetime.now().isoformat(timespec="seconds")
            )
        except (OSError, ValueError) as exc:
            return str(exc) or exc.__class__.__name__
        # 인메모리 사본은 **그 런의 VM 이 아직 현 세션일 때만** 동기화한다(디스크와 갈라지지
        # 않게). 세션이 이미 다른 작업으로 옮겨갔으면 남의 VM 을 만지지 않는다.
        if vm is not None and vm is self.vm:
            vm.job.last_run_at = job.last_run_at
        return ""

    def generate(self, *, confirm_overwrite: bool = False) -> dict:
        """게이트 통과 시 동기 생성 → 결과 dict. 덮어쓰기는 웹 재진술 후 재호출(RC-02).

        슬라이스 1은 실행 화면과 동일한 링1 계약을 배선한다 — 게이트 판정·덮어쓰기 재진술의
        표현(재진술 블록·modal.js)은 슬라이스 2(블록 6)가 광택한다.
        """
        if self.vm is None:
            return {"ok": False, "error": "먼저 작업을 선택하세요.", "level": "warn"}
        if not self._generation_lock.acquire(blocking=False):
            return {"ok": False, "error": "이미 문서를 생성하고 있습니다.", "level": "warn"}
        self._cancel_generation.clear()
        try:
            return self._generate_locked(confirm_overwrite=confirm_overwrite)
        finally:
            self._generation_lock.release()

    def _generate_locked(self, *, confirm_overwrite: bool = False) -> dict:
        """단일 생성 실행의 본체. ``generate``가 재진입 잠금과 취소 토큰을 소유한다."""
        # 이 런의 주체를 **시작 시점에 붙들고 이후 self.vm 을 다시 읽지 않는다**(#302 P1):
        # 생성 중 작업 전환이 self.vm 을 갈아끼우면 검증·계획이 남의 작업으로 새고,
        # 완주 뒤 현재 상태를 읽으면 남의 작업에 역사를 적는다(_stamp_last_run 동류).
        run_job_name, run_vm = self.job_name, self.vm
        indices = self._indices()
        out_dir = self.out_dir

        # 1) 기본 가드(데이터·폴더·레코드·구조 드리프트) — 링1 단일 판정.
        errors = run_vm.validate_generate(indices, out_dir)
        if errors:
            return {"ok": False, "error": errors[0].message, "level": errors[0].level}

        # 2) 미입력 강제 확인 게이트(ADR-E) — 버튼이 이미 비활성이어도 방어적 재확인.
        unmet = run_vm.unmet_blanks(indices)
        if unmet:
            return {
                "ok": False, "level": "warn",
                "error": "빈 값 필드를 먼저 확인하세요: " + ", ".join(unmet),
            }

        # 3) 미입력 표식(확인된 빈칸) — 완료 요약이 병기한다(낙관 서사 해소).
        blanks = run_vm.blank_fields(indices)
        self._marked_fields = list(blanks)
        marker = MISSING_MARKER if blanks else ""

        # 4) 덮어쓰기 확인(RC-02) — 미리보기가 캡처한 날짜 토큰 시각을 재사용(표시=확인=생성 일치).
        #    수치 합성(결정 36): 총량·파괴분(덮어씀)·신규분을 종류별로 재진술한다(블록 4 가드
        #    형식 "종류별 수치 재진술" 승계). 모달은 파괴 지점=덮어쓰기에만 선다. 표면(job.js)이
        #    이 수치로 modal.js 본문을 합성한다 — 별도 재진술 모달을 만들지 않는다.
        now = self._names_now or datetime.now()
        conflicts = run_vm.output_conflicts(indices, out_dir, mark_missing=marker, now=now)
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
        plan = run_vm.build_generation_plan(
            indices, out_dir, marker=marker, overwrite=overwrite, now=now
        )
        self._push_progress(0, len(plan.records))
        try:
            batch = generate_batch(
                plan.template, list(plan.records), plan.out_dir, plan.pattern,
                now=plan.now, overwrite=plan.overwrite, mapping=plan.mapping,
                progress=self._push_progress,
                cancelled=self._cancel_generation.is_set,
            )
        except (ValueError, OSError) as exc:
            # 배치가 **시작조차 못 한** 실패(구조 드리프트·산출물 충돌·폴더 오류) —
            # 지도 §10.10 판정 C. 여기서 잡지 않으면 브리지 rejection 이 되고 결과 자리는
            # 빈 채로 남아 사용자는 "아무 일도 안 일어났다"로 읽는다. 전역 백스톱은
            # 최후 방어로 그대로 두고, 알려진 실패류만 앞에서 결과 구획으로 회수한다.
            self._last_failed = list(indices)
            return self._failed_result(
                indices, plan.out_dir, str(exc) or exc.__class__.__name__,
            )
        cancelled = bool(getattr(batch, "cancelled", False))
        attempted = int(getattr(batch, "attempted", len(batch.results)))

        # 완료 이벤트 = 가드 무장 해제(결정 27) — 단 **완주**(전건 성공)만이다(고효율 리뷰
        # #1): 부분 실패 런에서 해제하면 실패분 재시도에 필요한 수작업 선택이 무확인
        # 파괴 가능해지고, 전환이 세션 지문을 바꿔 실패 목록(완료 존)까지 지워져 "내역은
        # 완료 존이 담보"의 전제가 깨진다.
        if not cancelled and batch.failed == 0:
            self._last_generated = set(indices)

        # 완주 = 역사(결정 7·부록 A-2-23) — 완주 런만 `last_run_at` 을 찍는다. 완주 술어를
        # 위 무장 해제와 공유하는 건 의도다: "완료 이벤트"가 둘로 갈라지면 홈 이력과 가드가
        # 서로 다른 실행을 완료로 부르게 된다(#129).
        stamp_error = (
            self._stamp_last_run(run_job_name, run_vm)
            if not cancelled and batch.failed == 0 else ""
        )

        if cancelled:
            unstarted = batch.total - attempted
            summary = (
                f"중단했습니다. 완료 {attempted}/{batch.total}건"
                f"(성공 {batch.succeeded}, 실패 {attempted - batch.succeeded}), "
                f"미착수 {unstarted}건. 완료된 문서는 그대로 유지됩니다."
            )
        else:
            summary = f"완료. 성공 {batch.succeeded}/{batch.total}, 실패 {batch.failed}."
        if blanks:
            summary += f" 빈 값 표시 필드 {len(blanks)}개({', '.join(blanks)})."
        if stamp_error:
            summary += (
                f" 문서는 모두 만들어졌지만 실행 기록 저장에 실패했습니다({stamp_error})."
            )
        # 실패 항목은 **구조화**해 넘긴다(§10.10 판정 E) — 파일명만으로 부르면 "어느
        # 행인가"를 사용자가 표에서 되찾아야 한다. 원본 index 는 「실패한 N건만 선택」의
        # 입력이기도 하다(판정 F). ``batch.results`` 는 ``plan.records`` 와 같은 순서이고
        # 그 순서는 ``indices`` 다(build_generation_plan 이 같은 리스트로 짓는다).
        failures = self._failure_rows(indices, batch.results)
        self._last_failed = [f["index"] for f in failures]
        # 채움 완화 사실(#154)은 완료 표면에 시끄럽게 — 파괴적 의미론(인라인 요소
        # 제거·값 런 합성)이 무경고면 조용한 데이터 손실이다(confirm-or-alarm).
        # 템플릿 구조 속성이라 레코드 수와 무관하게 한 번씩(순서 보존 dedupe).
        fill_notes = [
            describe_fill_note(n)
            for n in dict.fromkeys(
                n for r in batch.results if r.ok for n in r.notes
            )
        ]
        if fill_notes:
            summary += f" 채움 주의 {len(fill_notes)}건(아래 기록 확인)."
        failed_n = attempted - batch.succeeded if cancelled else batch.failed
        status = _run_status(batch.succeeded, batch.total, cancelled)
        return {
            "ok": True,
            "status": status,
            "title": _run_title(status, cancelled, batch.succeeded, failed_n),
            # 실패 단계·받은 메시지는 배치 진입 전 실패(_failed_result)의 자리다 —
            # 레코드 단위 실패는 각 행이 자기 사유를 진다. 모양은 한 벌로 유지한다.
            "stage": "",
            "message": "",
            "known": True,
            "summary": summary,
            "level": (
                "warn" if cancelled
                else ("ok" if batch.failed == 0 and not stamp_error else "danger")
            ),
            "out_dir": plan.out_dir,
            "succeeded": batch.succeeded,
            "failed": failed_n,
            # 「실패한 N건만 선택」의 노출·라벨은 **이 수치**가 정한다(1R P2): 실패 행
            # 목록에서 파생하면, 행 없이 전량이 실패하는 런(배치 진입 전 실패)에서 복구
            # 행동이 통째로 숨는다 — 뒤에 선택을 바꾸면 대상 집합을 되찾을 길이 없다.
            # index 를 Python 이 소유하기로 한 이상(판정 F) 그 개수도 Python 이 낸다.
            "failed_selectable": len(self._last_failed),
            "total": batch.total,
            "failures": failures,
            "fill_notes": fill_notes,
            "cancelled": cancelled,
            "attempted": attempted,
            "unstarted": batch.total - attempted,
        }

    def _failure_rows(self, indices: "list[int]", results: list) -> "list[dict]":
        """실패 레코드 = 원본 index + 식별 요약 + 실파일명 + 사유(+원인 확정 여부).

        식별 요약은 링1 단일 함수(:func:`~hwpxfiller.core.identity_summary.identity_summary`,
        결정 37)를 재사용한다 — 표 「문서」 열과 **같은 판정**이라 사용자가 결과에서 본
        이름으로 표에서 그 행을 찾는다(§10.10 판정 E: 어느 열로 부를지 재구현 금지).
        ``results`` 는 취소 런에서 ``indices`` 보다 짧다 — zip 이 짧은 쪽에서 멈추는 것이
        곧 "시도한 것만 결과가 있다"는 뜻이다(미착수는 실패가 아니다).
        """
        # strict=False 는 의도다(위 문단) — 취소 런의 짧은 results 가 정상 입력이다.
        pairs = [(i, r) for i, r in zip(indices, results, strict=False) if not r.ok]
        if not pairs:
            return []
        isum = identity_summary(
            self.records, filename_tokens=self._filename_source_columns()
        )
        rows = []
        for i, res in pairs:
            reason, known = classify_result_error(res.error)
            rows.append({
                "index": i,
                "identity": (
                    isum.display_for(self.records[i])
                    if 0 <= i < len(self.records) else ""
                ),
                "filename": Path(res.output_path).name,
                "reason": reason,
                "known": known,
            })
        return rows

    def _failed_result(self, indices: "list[int]", out_dir: str, message: str) -> dict:
        """배치 진입 전 실패 → ``failed`` 태 결과(§10.10 판정 C).

        계약 §10.3 이 요구하는 것을 그대로 싣는다: **실패 단계·영향 레코드·받은 메시지**
        와 원인 확정 여부. 원인을 꾸며내지 않으므로 아는 패턴이 없으면 ``known=False`` 로
        표면이 「원인 진단 미연결」을 세운다. ``ok=True`` 인 이유: 이것은 게이트 거절
        (실행하지 않음)이 아니라 **실행하다 실패**라서 결과 구획의 소관이다.

        ``failures`` 는 비어 있다 — 레코드별 시도가 없었으므로 행별 사유를 지어내지
        않는다. 영향 레코드는 수치(``failed``·``failed_selectable``)와 복구 행동으로
        나른다: 행이 없다고 「실패한 N건만 선택」까지 숨으면 전량 실패에서 대상 집합을
        되찾을 길이 사라진다(1R P2).
        """
        reason, known = classify_result_error(message)
        n = len(indices)
        return {
            "ok": True,
            "status": "failed",
            "title": _run_title("failed", False, 0, n),
            "summary": f"문서를 만들지 못했습니다. 대상 {n}건이 모두 생성되지 않았습니다.",
            "level": "danger",
            "stage": "생성 시작 전",
            "message": reason,
            "known": known,
            "out_dir": out_dir,
            "succeeded": 0,
            "failed": n,
            "failed_selectable": len(self._last_failed),
            "total": n,
            "failures": [],
            "fill_notes": [],
            "cancelled": False,
            "attempted": 0,
            "unstarted": n,
        }
