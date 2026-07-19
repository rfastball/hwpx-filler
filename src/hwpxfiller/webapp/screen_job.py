"""「작업」 화면 컨트롤러 — 좌 작업 목록 + 우 세션 패널 4존(webview 비의존).

R-flow 구현 라운드 슬라이스 1(에픽 #90). R-info 1부가 확정한 「작업」 화면(변형 B
master-detail: 좌 목록 + 우 4존 세션 패널)의 착지. 이 컨트롤러는 **새 링2 표면**이다 —
소멸 예정인 실행 화면(:mod:`~hwpxfiller.webapp.screen_run`)을 재사용하지 않고, 링1 VM 을
**직접 임포트**해 구동한다(부록 A: "계약 대부분은 링1이 소유하고, 죽는 것은 링2 표면뿐").
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
- 필터·세션 가드·건 연속성(블록 4)·txt 큐(블록 3)·빠른 기안(블록 5).
(슬라이스 2 착지분 — 게이트 재진술 블록·거울 채움 테이블·덮어쓰기 modal.js 수치 합성·식별
요약 링1 :func:`~hwpxfiller.core.identity_summary.identity_summary`(#88, A-1-15) — 은 본문에
배선돼 있다.)

**스코프 경계 — 미구현 명시(#89, A-4-33; ``screen_run.py`` 경계 절 문안째 승계)**: 아래는
링1 seam 은 존치하나 이 패널이 노출하지 않는다. "없는 기능을 있는 척하지 않는다"의 명문이며,
표면(실행 화면)이 죽어도 이 경계 선언은 죽지 않는다(F40 전례 방지):
- 나라장터 소스 겨눔(동결 해제 시 재배선)·나라 애드혹 취득.
- 협조적 취소(RC-06)·생성 원장 opt-in.
- 기존 문서 이어채우기(#18 결정으로 강등/숨김 — seam 은 링1 ``target_mode``/``set_prev_output``
  게이트 술어에 잔존, A-4-32).
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
from ..gui.result_errors import describe_result_error
from ..gui.run_state import RunViewModel
from ..gui.selection_state import SelectionModel
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
_PREFLIGHT_OK_TEXT = "검증 완료 — 문서를 생성할 준비가 됐습니다."


class JobController(PoolTargetingMixin):
    """「작업」 화면 — 좌 작업 목록 선택 + 우 세션 패널(링1 RunViewModel/SelectionModel 위임).

    **한시적 링2 중복(리뷰 #4·#5, 의도적 미추출)**: 이 컨트롤러의 링2 배선(``load_data_path``·
    ``dispatch``·``_do_*``·``_auto_aim_default``·``snapshot`` 골자)은 :class:`~hwpxfiller.webapp.
    screen_run.RunController` 와 크게 겹친다. 결정(2026-07-19): 공유 베이스를 **지금 추출하지
    않는다** — ① 실행 화면은 슬라이스 3(게이트 패리티 도달)에서 사망하므로 그 뒤 JobController 가
    유일 세션 표면이 되어 중복이 자연 소멸, ② 패널은 실행 화면과 이미 갈라진다(덮어쓰기 모달
    재진입 안전=리뷰 #1, 완료 존 세션 보존=결정 7·리뷰 #3, master-detail 좌 목록) — 공유 베이스는
    override 훅투성이 leaky 베이스가 되고 죽어가는 ``screen_run.py`` 를 건드린다. **주의(가드
    사각)**: ``test_job_panel_imports_ring1_and_does_not_reimplement`` 는 **링1 VM 메서드 재정의만**
    막는다 — 이 링2 중복은 통과한다. 슬라이스 3 착지(실행 화면 제거) 시 이 중복이 해소 대상이며,
    추적 이슈 #94 로 명시한다(조용한 드롭 아님)."""

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
        self.job_name = ""  # 좌 목록에서 겨눈 작업(패널 세션의 주체)
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
    def _job_rows(self) -> "list[dict]":
        """좌 master 목록 — 저장된 작업(HWPX 구획). 슬라이스 1은 이름 + 선택 표지만.

        2구획 틴트·group-by·컴파일 배지 등 풍부화는 후속 슬라이스(홈 브라우저 VM 채택).
        기안 작업(TXT) 구획은 draft-as-job(블록 3/5) 착지 전까지 빈 채로 둔다(없는 걸 있는
        척하지 않는다) — job.js 가 라벨만 렌더.
        """
        return [
            {"name": n, "selected": n == self.job_name}
            for n in self.registry.names()
        ]

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
                "summary": isum.display_for(rec),  # 표시=빈 세그먼트 생략(매달린 구분자 방지)
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

    def snapshot(self) -> dict:
        """4존 패널 스냅샷 — 필드는 실행 화면과 평행(링1 배선 감사 가능), 좌 목록 동봉.

        존 배치는 job.js 소관(헤더=작업 정체, 데이터=겨눔·행, 본문=배지·게이트, 완료=결과).
        """
        base = {
            "job_rows": self._job_rows(),   # 좌 master 목록
            "job_name": self.job_name,
            "has_job": self.vm is not None,
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
                "mirror": [], "drift": [],
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
            "records": self._record_rows(indices, mapped),
            "preflight": {"level": status.preflight.level, "text": preflight_text},
            # 본문 존 거울(필드 채움 테이블) + drift 필드(차단 배너로 분리, 결정 36).
            "mirror": mirror_rows,
            "drift": drift_fields,
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
        self.data_label = Path(path).name
        self.data_source = "file"  # 병기 라벨은 스냅샷이 합성(#26·K8)
        self.selection = SelectionModel(len(records))  # 데이터 변경 → 전체 선택 초기화
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
            self._do_select_job({"name": ""})  # 세션 무효화(vm·job_name·데이터·폴더 clear)

    def _do_select_job(self, p: dict) -> None:
        """좌 목록 클릭 → RunViewModel 재구성(패널 세션 진입). 저장 폴더 기본 = 템플릿/Results.

        작업에 기본 데이터셋 참조(#53-A)가 있으면 실행 시점에 다시 읽어 자동 조준한다.
        """
        name = p["name"]
        self._clear_data_notice()
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
            str(Path(job.template_path).parent / "Results") if job.template_path else ""
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

    def _do_toggle_record(self, p: dict) -> None:
        self.selection.toggle(int(p["index"]), bool(p["value"]))

    def _do_set_all(self, p: dict) -> None:
        self.selection.set_all()

    def _do_set_none(self, p: dict) -> None:
        self.selection.set_none()

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
        """풀 겨눔도 파일과 동일하게 새 데이터 = 전체 선택·ack 초기화를 탄다."""
        self.selection = SelectionModel(len(records))  # 데이터 변경 → 전체 선택 초기화
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
