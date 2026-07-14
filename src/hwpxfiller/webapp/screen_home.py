"""홈(대시보드) 화면 컨트롤러 — 두 트랙 허브(webview 비의존).

목업 scr-home 의 웹 이관(에픽 #20, 마지막 페이로드 화면). 링1 VM 을 **그대로 임포트**해
구동한다: KPI·작업 목록 성형·컴파일 상태 배지·작업 브라우저(group-by 렌즈 + facet 칩)·
빈 상태·손상 작업 격리·txt 트랙은 모두
:class:`~hwpxfiller.gui.home_state.HomeViewModel`(Qt-free)이 소유한다. 표현 계층(카드 렌더·
칩바·KPI 타일)만 웹(js/screens/home.js)으로 이식한다 — VM 로직 재구현이 아니다.

**허브 내비게이션**: 홈은 워크플로 화면들의 진입점이다. 카드/버튼의 이동은 링2(웹)에서만
일어난다 — 홈 컨트롤러는 다른 화면 컨트롤러를 모른다. 웹이 대상 화면의 자체 dispatch
(예: run.select_job)로 미리 겨눈 뒤 셸 라우터(window.Nav)로 화면을 전환한다. run/matrix
화면이 이관 전까지 두던 자체 작업 선택기는 홈 착지 후에도 독립 진입점으로 남는다(중복 아님 —
레일 직접 진입 경로).

**이번 이관의 스코프 경계(조용히 빠뜨리지 않고 명시)** — 아래는 미구현이며, 홈에서는 없는
어포던스를 있는 척하지 않는다(confirm-or-alarm):
- **작업 편집(edit)**: 저장된 작업을 에디터로 되불러오는 편집 모드가 아직 웹에 없다
  (screen_editor 는 신규 작성 4단계 마법사만). → 카드 '편집' 버튼은 비활성 + 사유 툴팁.
- **데이터 풀 관리·매핑 프로파일(어휘) 워크벤치**: 대응 웹 화면이 없다 → 홈에 버튼을 두지 않는다
  (Qt 홈의 manage_pool/manage_vocab 시그널은 이관 보류). pool_count KPI 도 목업이 표면화하지
  않으므로 pool_registry 를 붙이지 않는다.
- **손상 작업 파일 조치(열기·삭제)**: 네이티브/파괴 동작이라 보류 — 손상 행은 삭제/숨김이
  아니라 **시끄러운 위험 카드**로 노출만 한다(RC-05).
- **태그 편집(D14 수동 태깅)**: 브라우저는 태그를 **읽어** group-by/facet 하지만 태그를
  붙이는 UI 는 보류(홈은 퇴화-코퍼스 불변식대로 태그 없으면 평면 목록).
"""
from __future__ import annotations

from ..core.job import JobRegistry
from ..core.text_registry import TextTemplateRegistry
from ..gui.compile_badge import badge_level
from ..gui.home_state import HomeViewModel, JobRow
from .screens import PushSink

# 이어서 실행(continue-runs) 목록 상한 — 최근 실행순 상위 N. 대시보드 요약이라 짧게 유지.
_CONTINUE_LIMIT = 5


def _job_row_dict(r: JobRow) -> dict:
    """카드 1건 성형 — 링1 JobRow 표면만 읽는다(VM 로직 재구현 없음).

    컴파일 배지의 심각도(pill 색 레벨)는 :func:`badge_level`(RC-29 단일 어휘)로 파생해
    템플릿 관리 화면·Qt 홈과 같은 상태에 같은 신호를 낸다.
    """
    return {
        "name": r.name,
        "meta_line": r.meta_line(),
        "compile_badge": r.compile_badge,
        "badge_level": badge_level(r.compile_state),  # muted/warn/ok/danger
        "last_run_display": r.last_run_display,
        "template_missing": r.template_missing,
        "runnable": r.is_runnable(),
    }


class HomeController:
    """홈(대시보드) — 링1 HomeViewModel 소유·위임. 순수 데이터 화면(네이티브 표면 없음)."""

    name = "home"

    def __init__(self, registry: JobRegistry, text_registry: TextTemplateRegistry,
                 push: PushSink) -> None:
        # pool_registry 는 붙이지 않는다(pool_count KPI 미표면 — docstring 스코프 경계).
        self.vm = HomeViewModel(registry, text_registry)
        self._push_sink = push

    # ------------------------------------------------------------- 관측 푸시
    def _push(self) -> None:
        self._push_sink(self.name, self.snapshot())

    # ------------------------------------------------------------- 스냅샷
    def _continue_runs(self) -> "list[dict]":
        """이어서 실행 — 실행 이력이 있는 작업을 최근순 상위 N(요약)."""
        runs = [r for r in self.vm.rows() if r.last_run_at]
        runs.sort(key=lambda r: r.last_run_at, reverse=True)
        return [
            {"name": r.name, "last_run_display": r.last_run_display, "runnable": r.is_runnable()}
            for r in runs[:_CONTINUE_LIMIT]
        ]

    def _grouped(self) -> "list[dict]":
        """작업 브라우저 섹션 — effective group-by 축으로 분할(퇴화 시 단일 버킷)."""
        return [
            {
                "value": sec.value,
                "count": sec.count,
                "is_untagged": sec.is_untagged,
                "rows": [_job_row_dict(r) for r in sec.rows],
            }
            for sec in self.vm.grouped_rows()
        ]

    def _facets(self) -> "list[dict]":
        return [
            {
                "axis": fa.axis,
                "values": [
                    {"value": v.value, "count": v.count, "active": v.active}
                    for v in fa.values
                ],
            }
            for fa in self.vm.facets()
        ]

    def snapshot(self) -> dict:
        kpi = self.vm.kpi()
        return {
            "kpi": {
                "job_count": kpi.job_count,
                "missing_template_count": kpi.missing_template_count,
                "txt_template_count": kpi.txt_template_count,
            },
            "is_empty": self.vm.is_empty(),
            "continue_runs": self._continue_runs(),
            # 작업 브라우저(group-by 렌즈 + facet) — 태그 없으면 axes/facets 빈 목록 → 평면 강등.
            "axes": self.vm.axes(),
            "group_by": self.vm.effective_group_by(),
            "facets": self._facets(),
            "grouped_rows": self._grouped(),
            # 손상 작업 — 숨기지 않고 시끄러운 위험 카드로(RC-05).
            "corrupt_rows": [
                {"file_name": c.file_name, "detail_line": c.detail_line()}
                for c in self.vm.corrupt_rows()
            ],
            # txt 트랙 — 즉시 기안 템플릿 목록(정해진 루트).
            "txt_rows": [{"name": t.name, "field_count": t.field_count} for t in self.vm.txt_rows()],
        }

    def initial(self) -> dict:
        return self.snapshot()

    # ------------------------------------------------------- 웹→Python 데이터 액션
    def dispatch(self, action: str, payload: dict):
        handler = getattr(self, f"_do_{action}", None)
        if handler is None:  # confirm-or-alarm: 미지 액션은 시끄럽게.
            raise ValueError(f"알 수 없는 home 액션: {action!r}")
        result = handler(payload)
        self._push()
        return result

    def _do_set_group_by(self, p: dict) -> None:
        """group-by 렌즈 교체(""=flat). 빈 축 값은 flat 로 자연 강등."""
        self.vm.set_group_by(p.get("axis") or "")

    def _do_toggle_facet(self, p: dict) -> None:
        self.vm.toggle_facet(p["axis"], p["value"])

    def _do_clear_facets(self, p: dict) -> None:
        self.vm.clear_facets()

    def _do_delete_job(self, p: dict) -> None:
        """작업 삭제(웹이 확인 후 호출). VM 이 레지스트리에서 지우고 목록을 갱신·통지한다."""
        self.vm.delete(p["name"])

    def _do_refresh(self, p: dict) -> None:
        """레지스트리 재조회(다른 화면에서 작업 저장/삭제 후 홈 복귀 시 최신화)."""
        self.vm.refresh()
