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

**#26 패리티 회수(이 라운드 포함)**:
- **작업 편집(edit)**: 카드 '편집' → 브리지 ``open_job_in_editor`` 로 에디터 편집 세션 복원
  (:meth:`~hwpxfiller.webapp.screen_editor.EditorController.load_job`). 미저장 세션 확인은
  웹이 선판단(#25 미러).
- **태그 편집(D14 수동 태깅)**: ``set_tags`` 액션 — 작업의 분류 태그(축→값)를 통째로
  교체·저장한다. 카드는 태그를 직접 렌더하지 않는 D8 불변을 지키고(섹션·칩만 소비),
  편집 어포던스(버튼)만 카드에 둔다.
- **손상 작업 파일 조치(열기·삭제)**: ``delete_corrupt``(확인 라운드트립) + 브리지
  ``reveal_corrupt_job``(탐색기 표시). 경로는 레지스트리 디렉터리 안의 ``.job.json`` 만
  허용한다(웹 페이로드로 임의 파일을 지우는 경로 봉쇄).

**남은 스코프 경계(조용히 빠뜨리지 않고 명시)**:
- **매핑 프로파일(어휘) 워크벤치**: 전용 관리 화면은 없다 — 에디터 3단계의 적용/저장/삭제가
  현재 표면이다. pool_count KPI 는 목업이 표면화하지 않으므로 pool_registry 를 붙이지 않는다
  (데이터 관리 자체는 pool 화면 소유).
"""
from __future__ import annotations

from pathlib import Path

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
        # 태그 편집(#26 D14) 프리필용 — 카드는 직접 렌더하지 않는다(D8 불변).
        "tags": dict(r.tags),
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
            # 손상 작업 — 숨기지 않고 시끄러운 위험 카드로(RC-05) + 조치 경로(#26 #8).
            "corrupt_rows": [
                {"file_name": c.file_name, "detail_line": c.detail_line(), "path": c.path}
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

    # ------------------------------------------------------- 태그 편집(#26 #2·D14)
    def _do_set_tags(self, p: dict) -> None:
        """작업의 분류 태그(축→값)를 통째로 교체·저장 — 빈 dict = 전체 해제.

        축·값은 모두 비어 있지 않은 문자열이어야 한다(loud — Job.from_dict 의 타입 계약
        미러). 같은 이름 재저장은 자기-갱신이라 slug 가드를 자연 통과한다. 저장 후
        refresh 로 axes/facets 가 즉시 재발견된다(퇴화-코퍼스 불변식 유지).
        """
        name = p["name"]
        raw = p.get("tags", {})
        if not isinstance(raw, dict):
            raise ValueError("태그는 {축: 값} 사전이어야 합니다")
        tags: "dict[str, str]" = {}
        for k, v in raw.items():
            if not isinstance(k, str) or not isinstance(v, str) or not k.strip() or not v.strip():
                raise ValueError("태그의 축·값은 비어 있지 않은 문자열이어야 합니다")
            tags[k.strip()] = v.strip()
        job = self.vm.registry.load(name)  # 부재·손상 → loud raise
        job.tags = tags
        self.vm.registry.save(job, allow_overwrite=True)  # 자기-갱신
        self.vm.refresh()

    # ------------------------------------------------- 손상 작업 조치(#26 #8·UD-44)
    def validate_corrupt_path(self, raw: str) -> Path:
        """손상 작업 조치 대상 경로 검증 — 레지스트리 밖·비 job 파일은 loud 거절.

        웹 페이로드의 경로를 그대로 신뢰하면 임의 파일 삭제/열기 통로가 된다. 현재
        손상 목록에 실재하는 경로만 허용한다(스냅샷이 곧 화이트리스트).
        """
        candidates = {str(c.path) for c in self.vm.corrupt_rows()}
        if raw not in candidates:
            raise ValueError("손상 작업 목록에 없는 경로입니다 — 새로고침 후 다시 시도하세요.")
        return Path(raw)

    def _do_delete_corrupt(self, p: dict) -> dict:
        """손상 작업 파일 삭제 — 파괴이므로 확인 라운드트립(1차=재진술, 2차=삭제)."""
        path = self.validate_corrupt_path(p["path"])
        if not p.get("confirm"):
            return {
                "ok": True, "needs_confirm": True, "path": str(path),
                "confirm_text": (
                    f"손상된 작업 파일을 삭제합니다(복구 불가):\n{path}\n"
                    "내용을 확인하려면 먼저 '폴더 열기'로 살펴보세요."
                ),
            }
        path.unlink()
        self.vm.refresh()
        return {"ok": True}
