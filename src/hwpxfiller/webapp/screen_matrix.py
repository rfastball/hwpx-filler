"""여러 작업 실행(Matrix) 화면 컨트롤러 — M 작업 × 공통 데이터 일괄 생성(webview 비의존).

목업 scr-matrix 의 웹 이관(에픽 #20, 화면 #14). 링1 VM 을 **그대로 임포트**해 구동한다:
작업 다중선택·데이터 겨눔·작업별 3상태 배지·강제 확인 게이트·사전검증은
:class:`~hwpxfiller.gui.matrix_state.MatrixRunViewModel`(Qt-free)이 소유하고, 공유 데이터의
행 선택은 :class:`~hwpxfiller.gui.selection_state.SelectionModel`(Qt-free)이 소유한다.
표현 계층(작업별 배지 렌더·게이트 재진술·진행/로그)만 웹(js/screens/matrix.js)으로 이식한다
— VM 로직 재구현이 아니다. 생성은 :func:`~hwpxfiller.batch.generate_matrix`(작업별 하위폴더).

Qt 는 홈의 '같은 데이터로 여러 작업 실행'(matrix_run_requested)로 진입하는 독립 셸 페이지지만,
웹 셸의 레일 '여러 작업 실행' 진입은 독립적이라 화면 안에 작업 다중선택기를 둔다(홈 이관 전까지의
진입점 — run 화면과 동형).

**이번 이관의 스코프 경계(조용히 빠뜨리지 않고 명시)** — 아래는 이 커밋에서 미구현이며 후속
이관 대상이다(confirm-or-alarm: 없는 기능을 있는 척하지 않는다):
- 데이터 소스 = **파일(.xlsx/.csv)만**. 등록 데이터 풀·나라장터 애드혹 취득은 후속(run 과 동일 경계).
- 협조적 취소(RC-06)는 미구현 — 웹 생성은 동기(진행 델타 푸시)라 단일 실행 화면과 같은 경계.
작업별 미입력 강제 확인 게이트·덮어쓰기 확인·구조 드리프트 차단은 모두 포함한다(게이트 소멸 없음).
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from ..batch import generate_matrix
from ..core.job import JobRegistry
from ..gui.matrix_state import MatrixRunViewModel
from ..gui.result_errors import describe_result_error
from ..gui.selection_state import SelectionModel
from ..naming import make_output_filename
from .screens import PushSink

# 공유 데이터 행은 작업마다 파일명 패턴이 달라 단일 패턴이 없다 — Qt(RecordSelector "행-{{seq}}")
# 와 동형의 중립 라벨로 렌더한다.
_ROW_PATTERN = "행-{{seq}}"


class MatrixController:
    """여러 작업 실행 화면 — 작업 다중선택 + 공유 데이터 겨눔 + 작업별 게이트."""

    name = "matrix"

    def __init__(self, registry: JobRegistry, push: PushSink) -> None:
        self.registry = registry
        self._push_sink = push
        # pool_registry 를 스텁 없이 기본 주입하면 나라/풀 경로가 열리지만, 이 화면의 웹
        # 스코프는 파일만이라 풀은 겨누지 않는다(후속). VM 자체는 3소스를 다 아는 링1 그대로.
        self.vm = MatrixRunViewModel(registry)
        self.selection = SelectionModel(0)
        self.data_label = ""
        self.out_dir = ""

    # ------------------------------------------------------------- 관측 푸시
    def _push(self) -> None:
        self._push_sink(self.name, self.snapshot())

    # ------------------------------------------------------------- 스냅샷
    def _indices(self) -> "list[int]":
        return self.selection.selected_indices()

    def _job_rows(self) -> "list[dict]":
        return [
            {"name": n, "selected": self.vm.is_selected(n)}
            for n in self.vm.all_job_names()
        ]

    def _record_rows(self) -> "list[dict]":
        """공유 데이터 각 행 = 중립 라벨(행-N) + 선택 여부."""
        rows: "list[dict]" = []
        for i, rec in enumerate(self.vm.records):
            rows.append({
                "index": i,
                "label": f"{i + 1}. {make_output_filename(_ROW_PATTERN, rec, seq=i + 1)}",
                "selected": self.selection.is_selected(i),
            })
        return rows

    def _field_summaries(self, indices: "list[int]") -> "tuple[list, list[dict]]":
        """(원시 요약, 웹 직렬화) — 요약을 게이트가 재사용하도록 원시도 함께 돌려준다(RC-23)."""
        summaries = self.vm.field_summaries(indices)
        serial = [
            {
                "job_name": js.job_name,
                "states": [
                    {"name": s.name, "state": s.state, "acknowledged": s.acknowledged}
                    for s in js.field_states
                ],
            }
            for js in summaries
        ]
        return summaries, serial

    def _gate(self, indices: "list[int]", summaries: "list") -> dict:
        """생성 버튼 게이트 = 기본 사전검증(작업·데이터·행·폴더·드리프트) + 미입력 확인 게이트.

        미입력 확인 축은 :meth:`~hwpxfiller.gui.matrix_state.MatrixRunViewModel.missing_gate`
        가 소유하고, 그 외 전제는 ``validate`` 가 소유한다(중복 판정 금지) — 둘 중 하나라도
        막으면 버튼을 닫고 그 사유를 재진술한다(조용한 활성 금지).
        """
        errors = self.vm.validate(indices, self.out_dir)
        if errors:
            return {"enabled": False, "level": "warn", "text": errors[0]}
        gate = self.vm.missing_gate(indices, summaries=summaries)
        return {"enabled": gate.enabled, "level": gate.level, "text": gate.text}

    def snapshot(self) -> dict:
        indices = self._indices()
        summaries, serial = self._field_summaries(indices)
        return {
            "jobs": self._job_rows(),
            "selection_count": self.vm.selection_count(),
            "data_label": self.data_label,
            "has_data": self.vm.datasource is not None,
            "out_dir": self.out_dir,
            "record_count": len(self.vm.records),
            "selected_count": self.selection.selected_count(),
            "records": self._record_rows(),
            "field_summaries": serial,
            "gate": self._gate(indices, summaries),
        }

    def initial(self) -> dict:
        return self.snapshot()

    # ------------------------------------------- 네이티브 보조(브리지가 다이얼로그 담당)
    def load_data_path(self, path: str, *, sheet: "str | None" = None) -> None:
        """선택된 데이터 파일을 링1 VM 으로 겨눔(공통 데이터). 레코드 0건이면 시끄럽게 실패.

        ``sheet`` = 웹에서 확정한 시트명(다중 시트 확정 게이트 #33, None=CSV·단일 시트)."""
        records = self.vm.load_file(path, sheet=sheet)  # 파일 소스 리졸버(Qt-free). 실패는 raise.
        if not records:
            raise ValueError("레코드 0건 — 데이터를 바꾸지 않았습니다.")
        self.data_label = Path(path).name
        self.selection = SelectionModel(len(records))  # 데이터 변경 → 전체 선택 초기화
        self._push()

    def set_output_folder(self, path: str) -> None:
        """네이티브 폴더 피커가 고른 저장 폴더를 반영(작업별 하위폴더 루트)."""
        self.out_dir = path
        self._push()

    # ------------------------------------------------------- 웹→Python 데이터 액션
    def dispatch(self, action: str, payload: dict):
        handler = getattr(self, f"_do_{action}", None)
        if handler is None:  # confirm-or-alarm: 미지 액션은 시끄럽게.
            raise ValueError(f"알 수 없는 matrix 액션: {action!r}")
        result = handler(payload)
        self._push()
        return result

    def _do_toggle_job(self, p: dict) -> None:
        self.vm.set_job_selected(p["name"], bool(p["value"]))

    def _do_set_all_jobs(self, p: dict) -> None:
        for n in self.vm.all_job_names():
            self.vm.set_job_selected(n, True)

    def _do_set_none_jobs(self, p: dict) -> None:
        for n in self.vm.all_job_names():
            self.vm.set_job_selected(n, False)

    def _do_toggle_record(self, p: dict) -> None:
        self.selection.toggle(int(p["index"]), bool(p["value"]))

    def _do_set_all(self, p: dict) -> None:
        self.selection.set_all()

    def _do_set_none(self, p: dict) -> None:
        self.selection.set_none()

    def _do_ack_field(self, p: dict) -> None:
        """미입력 배지 클릭 = 직접 확인(강제 상호작용, ADR-E). (작업, 필드) 단위."""
        self.vm.acknowledge(p["job"], p["field"])

    def _do_unack_field(self, p: dict) -> None:
        """ack 칩 재클릭 = 확인 철회(UD-19 토글) — 게이트가 다시 닫힌다."""
        self.vm.unacknowledge(p["job"], p["field"])

    # ------------------------------------------------------------------ 생성
    def _push_progress(self, done: int, total: int) -> None:
        """생성 진행 델타 — 전체 스냅샷 재계산 없이 진행바만 갱신."""
        self._push_sink(self.name, {"progress": {"done": done, "total": total}})

    def generate(self, *, confirm_overwrite: bool = False) -> dict:
        """게이트 통과 시 동기 매트릭스 생성 → 결과 dict. 덮어쓰기는 재진술 후 재호출(RC-02).

        pywebview js_api 는 UI 스레드 밖에서 돌아 블로킹 생성이 창을 얼리지 않는다 —
        (작업×행) 진행 델타를 푸시한다. 실패/차단은 조용히 삼키지 않고 dict 로 재진술.
        """
        indices = self._indices()
        out_dir = self.out_dir

        # 1) 기본 가드(작업·데이터·행·폴더·구조 드리프트) — 링1 단일 판정.
        errors = self.vm.validate(indices, out_dir)
        if errors:
            return {"ok": False, "error": errors[0], "level": "warn"}

        # 2) 작업별 미입력 강제 확인 게이트(ADR-E) — 버튼이 이미 비활성이어도 방어적 재확인.
        #    필드 요약은 한 번만 계산해 게이트 재확인·표식 목록이 공유한다(RC-23).
        summaries = self.vm.field_summaries(indices)
        unmet = self.vm.unmet_missing(indices, summaries=summaries)
        if unmet:
            names = "; ".join(f"{jn}·{f}" for jn, f in unmet)
            return {
                "ok": False, "level": "warn",
                "error": "미입력 필드를 먼저 확인하세요: " + names,
            }

        # 3) 미입력 표식(확인된 빈칸) — 완료 요약이 병기한다(낙관 서사 해소).
        marked = [
            (js.job_name, s.name)
            for js in summaries
            for s in js.field_states if s.state == "missing"
        ]

        # 4) 덮어쓰기 확인(RC-02) — 같은 날짜 토큰 시각을 고정해 확인·생성이 일치하게.
        now = datetime.now()
        conflicts = self.vm.output_conflicts(indices, out_dir, now=now)
        if conflicts and not confirm_overwrite:
            names = [Path(p).name for p in conflicts]
            shown = "\n".join(names[:10]) + (
                f"\n… 외 {len(names) - 10}개" if len(names) > 10 else ""
            )
            return {
                "ok": False, "needs_overwrite": True,
                "overwrite_text": (
                    f"저장 폴더에 같은 이름의 파일이 이미 있습니다.\n"
                    f"계속하면 기존 파일 {len(conflicts)}개를 덮어씁니다:\n\n{shown}"
                ),
            }
        overwrite = bool(conflicts)

        # 5) 동기 매트릭스 생성(진행 델타 푸시). 확인·생성이 같은 now 를 공유(RC-02).
        jobs = self.vm.selected_jobs()
        self._push_progress(0, len(jobs) * len(indices))
        result = generate_matrix(
            jobs, self.vm.datasource, indices, out_dir,
            overwrite=overwrite, now=now, progress=self._push_progress,
        )

        summary = (
            f"완료 — 작업 {result.job_count}개, 문서 {result.succeeded}/{result.total} 성공 · "
            f"실패 {result.failed}"
        )
        if marked:
            summary += f" · 미입력 표시 필드 {len(marked)}개"
        failures = [
            f"[{jr.job_name}] {Path(r.output_path).name}: {describe_result_error(r.error)}"
            for jr in result.per_job
            for r in jr.batch.results if not r.ok
        ]
        return {
            "ok": True,
            "summary": summary,
            "level": "ok" if result.failed == 0 else "danger",
            "out_dir": out_dir,
            "succeeded": result.succeeded,
            "failed": result.failed,
            "total": result.total,
            "failures": failures,
            "per_job": [
                {"job_name": jr.job_name, "succeeded": jr.batch.succeeded,
                 "total": jr.batch.total, "out_dir": Path(jr.out_dir).name}
                for jr in result.per_job
            ],
        }
