"""실행(Run) 화면 컨트롤러 — 저장된 작업을 골라 데이터·행을 겨눠 생성(webview 비의존).

목업 scr-run 의 웹 이관(에픽 #20, 화면 #18). 링1 VM 을 **그대로 임포트**해 구동한다:
실행 결정(데이터 로드·사전검증·3상태 배지·강제 확인 게이트·생성 계획)은
:class:`~hwpxfiller.gui.run_state.RunViewModel`(Qt-free), 레코드 선택은
:class:`~hwpxfiller.gui.selection_state.SelectionModel`(Qt-free)이 소유한다. 표현 계층
(배지 렌더·게이트 재진술·진행/로그)만 웹(js/screens/run.js)으로 이식한다 — VM 로직 재구현이
아니다. 실패 문구는 :func:`~hwpxfiller.gui.result_errors.describe_result_error`(RC-30, Qt-free)로
Qt 위젯과 **같은** 보강을 얻는다.

**진입 어포던스(작업 선택)**: Qt 는 홈에서 특정 작업으로 실행 화면에 진입하지만, 웹 셸의
레일 '실행' 진입은 독립적이라 화면 상단에 **작업 선택기**를 둔다(홈 이관 전까지의 진입점).
목업도 이를 반영한다(작업 헤더 → 선택기).

**데이터 소스(#26/#6)**: **파일(.xlsx/.csv) + 등록 데이터(데이터셋 풀 참조)** 2소스.
풀 겨눔은 링1 :meth:`~hwpxfiller.gui.run_state.RunViewModel.load_pool_item`(실행 시점
재읽기="싱크") 재사용. **나라장터 소스는 동결**(내부망 API 미확인 — #10/#24 정합)이라 웹에
노출하지 않는다 — 풀의 nara 항목은 목록에 보이되 겨눔은 시끄럽게 거절(:mod:`.screens`
``load_pool_item_checked`` 단일 관문).

**이번 이관의 스코프 경계(조용히 빠뜨리지 않고 명시)** — 아래는 미구현이며
후속 이관 대상이다(confirm-or-alarm: 없는 기능을 있는 척하지 않는다):
- 나라장터 소스 겨눔(동결 해제 시 재배선)·나라 애드혹 취득.
- 기존 문서 이어채우기(#18 결정으로 실행 화면에선 강등/숨김 — seam 은 링1 에 존치).
- 협조적 취소(RC-06)·생성 원장 opt-in.
덮어쓰기 확인·미입력 강제 확인 게이트·구조 드리프트 차단·미입력 표식·다중 시트 확정
게이트(#33)는 모두 포함한다.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from ..batch import generate_batch
from ..core.job import MISSING_MARKER, JobRegistry
from ..data import source_for_path
from ..core.dataset_pool import DatasetPoolRegistry
from ..gui.result_errors import describe_result_error
from ..gui.run_state import RunViewModel
from ..gui.selection_state import SelectionModel
from .screens import (
    PoolTargetingMixin,
    PushSink,
    default_pool_registry,
    load_pool_into,
    relink_job_template,
    source_label,
)

# 사전검증 성공 문구는 링2 사용자 어휘로 순화한다(#18/D0D92672-A) — 위젯 run_view 와 동일.
_PREFLIGHT_OK_TEXT = "검증 완료 — 문서를 생성할 준비가 됐습니다."

# 레코드 식별 요약(F33)에 넣을 원본 데이터 앞쪽 열 수 — 파일명만으로 레코드가 안
# 갈리는 패턴(예약 토큰만·상수 패턴)에서도 '어느 데이터의 문서인지'가 보이게 한다.
_SUMMARY_FIELDS = 3


def _record_summary(rec: dict) -> str:
    """원본 레코드 앞쪽 값들로 만드는 한 줄 식별 요약 — 빈 값은 건너뛴다."""
    parts = [
        f"{k}: {v}" for k, v in list(rec.items())[:_SUMMARY_FIELDS]
        if str(v).strip()
    ]
    if not parts:
        return ""
    tail = " …" if len(rec) > _SUMMARY_FIELDS else ""
    return " · ".join(parts) + tail


class RunController(PoolTargetingMixin):
    """실행 화면 — 작업 선택 상태 소유 + 링1 RunViewModel/SelectionModel 위임."""

    name = "run"

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
        self.data_label = ""
        self.data_source = ""  # 소스 종류 플래그('file'|'pool') — 병기 라벨은 스냅샷이 합성(K8)
        self.out_dir = ""
        self._marked_fields: "list[str]" = []
        # 기본 데이터셋 자동 조준(#53-A) 결과 재진술 — 성공(ok)/실패(warn)를 스냅샷에 노출.
        # 실패는 조용한 폴백 금지: 데이터 미겨눔으로 남기고 원인·복구 동선을 시끄럽게 알린다.
        self.data_notice_text = ""
        self.data_notice_level = ""
        # 등록 데이터(풀) 겨눔(#26/#6) — 기본은 홈 레지스트리, 테스트는 주입.
        self.pool_registry = (
            pool_registry if pool_registry is not None else default_pool_registry()
        )

    # ------------------------------------------------------------- 관측 푸시
    def _push(self) -> None:
        self._push_sink(self.name, self.snapshot())

    # ------------------------------------------------------------- 스냅샷
    def _job_names(self) -> "list[str]":
        return self.registry.names()

    def _indices(self) -> "list[int]":
        return self.selection.selected_indices()

    def _record_rows(self) -> "list[dict]":
        """각 레코드 = 원본 데이터 식별 요약 + 그 행이 만들 **실**파일명 미리보기(F33).

        파일명은 생성과 동일 규칙으로 계산한다 — 매핑 적용 레코드 + 배치 내 충돌
        접미사(:func:`~hwpxfiller.naming.plan_output_names`). 종전엔 매핑 **전** 원본
        레코드로 치환해 소스 열 이름과 템플릿 필드 이름이 다르면 미리보기와 실파일명이
        갈라졌다. ``{{seq}}``·충돌 접미사는 최종 선택 집합에 따라 달라지므로 **선택된**
        레코드에만 이름을 계산한다 — 미선택 행에 확정되지 않은 이름을 지어내지
        않는다(확인-또는-경보). 식별 요약은 매핑 전 원본 값이다 — 사용자가 데이터에서
        본 그 어휘로 '어느 데이터의 문서인지'를 드러낸다.
        """
        if self.vm is None:
            return []
        from ..naming import plan_output_names

        indices = self._indices()
        names: "dict[int, str]" = {}
        if indices:
            names = dict(zip(indices, plan_output_names(
                self.vm.job.filename_pattern, self.vm.mapped_records(indices)
            )))
        return [
            {
                "index": i,
                "selected": self.selection.is_selected(i),
                "name": names.get(i, ""),
                "summary": _record_summary(rec),
            }
            for i, rec in enumerate(self.vm.records)
        ]

    def snapshot(self) -> dict:
        base = {
            "jobs": self._job_names(),
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
                "job_name": "", "template_name": "", "filename_pattern": "",
                "record_count": 0, "selected_count": 0, "records": [],
                "preflight": {"level": "", "text": ""},
                "field_states": [], "has_data": False,
                "gate": {"enabled": False, "level": "warn", "text": "실행할 작업을 선택하세요."},
            })
            return base
        job = self.vm.job
        indices = self._indices()
        status = self.vm.refresh(indices, self.out_dir)  # 사전검증+배지+게이트 단일 산출(RC-23)
        preflight_text = (
            _PREFLIGHT_OK_TEXT if status.preflight.level == "ok" else status.preflight.text
        )
        base.update({
            "job_name": job.name,
            "template_name": Path(job.template_path).name if job.template_path else "",
            "template_path": job.template_path,  # 추적성 로케이트(#53-B) — 전체 경로
            "filename_pattern": job.filename_pattern,
            "has_data": self.vm.datasource is not None,
            "record_count": len(self.vm.records),
            "selected_count": self.selection.selected_count(),
            "records": self._record_rows(),
            "preflight": {"level": status.preflight.level, "text": preflight_text},
            "field_states": [
                {"name": s.name, "state": s.state, "acknowledged": s.acknowledged}
                for s in status.field_states
            ],
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

        ``sheet`` 는 사용자가 웹에서 **확정한** 시트명(다중 시트 확정 게이트, #33) — None 이면
        CSV·단일 시트라 물을 것이 없는 경우다(브리지가 모호할 때만 확정을 요구하므로).
        """
        if self.vm is None:
            raise ValueError("실행할 작업을 먼저 선택하세요.")
        records = self.vm.load_data(path, sheet=sheet)  # 파일 소스 리졸버(Qt-free). 실패는 raise.
        if not records:
            raise ValueError("레코드 0건 — 데이터를 바꾸지 않았습니다.")
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
            raise ValueError(f"알 수 없는 run 액션: {action!r}")
        result = handler(payload)
        self._push()
        return result

    def _do_refresh(self, p: dict) -> None:
        """레지스트리 재스캔 반영(C6 — 전환 자동 + 필요 시 수동) — 스냅샷 고착 방지.

        작업 목록은 스냅샷이 매번 ``registry.names()`` 를 재읽으므로 상태 갱신이 필요
        없다 — dispatch 말미의 ``_push()`` 가 새 스냅샷을 밀어내는 것이 이 액션의 전부다
        (home/pool/tpl 은 VM 이 행을 캐시해 ``vm.refresh()`` 를 태우는 것과 대비).
        없으면 에디터에서 막 저장한 작업이 실행 화면 드롭다운에 안 보인다(C6 잔여).
        """

    def _do_select_job(self, p: dict) -> None:
        """작업 선택 → RunViewModel 재구성. 저장 폴더 기본값 = 템플릿 폴더/Results(Qt 동형).

        작업에 기본 데이터셋 참조(#53-A)가 있으면 실행 시점에 다시 읽어 자동 조준한다 —
        없으면 현행처럼 사용자가 파일/등록 데이터를 수동 선택한다.
        """
        name = p["name"]
        self._clear_data_notice()
        if not name:  # 선택 해제 = 빈 상태로
            self.vm = None
            self.selection = SelectionModel(0)
            self.data_label = ""
            self.data_source = ""
            self.out_dir = ""
            return
        job = self.registry.load(name)
        self.vm = RunViewModel(job)
        self.selection = SelectionModel(0)
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
        """저장된 기본 데이터셋을 실행 시점에 다시 읽어 자동 조준한다(#53-A).

        실패(참조 부재·죽은 파일·모호 시트·나라 동결·레코드 0건)는 **조용한 폴백 금지** —
        데이터를 미겨눔으로 남기고 원인과 복구 동선(수동 선택·재연결)을 시끄럽게 재진술한다
        (confirm-or-alarm). 성공/실패 모두 겨눔 관문(``load_pool_into``)을 파일·수동 겨눔과
        공유해 문구 체계가 갈리지 않는다.
        """
        res = load_pool_into(self.pool_registry, ref, self.vm.load_pool_item)
        if res["ok"]:
            self.data_label = ref
            self.data_source = "pool"
            # 풀 겨눔 공유 후처리(선택 초기화·재진술 소거)를 재사용 — 수동 겨눔 경로와
            # 갈리지 않게(K4 복붙 방지). notice 는 소거 뒤에 세팅(순서 중요).
            self._after_pool_load(res["records"])
            self.data_notice_text = (
                f"기본 데이터 '{ref}' 를 자동 연결했습니다 — 실행 시점에 다시 읽었습니다."
            )
            self.data_notice_level = "ok"
        else:
            self.data_notice_text = (
                f"기본 데이터 '{ref}' 를 자동으로 열 수 없습니다: {res['error']}\n"
                "다른 데이터를 직접 선택하거나 데이터 관리에서 참조를 다시 연결하세요."
            )
            self.data_notice_level = "warn"

    def _do_relink_template(self, p: dict) -> dict:
        """작업 템플릿 다시 연결(#67) — 공유 확정 게이트에 위임 + 기선택 작업 재적재.

        커밋된 작업이 지금 화면에 선택돼 있으면 옛 경로의 VM 이 stale 이므로
        ``_do_select_job`` 으로 재구성한다 — 이는 데이터 겨눔·저장 폴더를 초기화하므로
        (자동 조준은 재실행) 조용히 두지 않고 결과 문구로 재진술한다(confirm-or-alarm).
        """
        res = relink_job_template(
            self.registry, p["name"], p.get("path", ""), confirm=bool(p.get("confirm")),
        )
        if res.get("relinked") and self.vm is not None and self.vm.job.name == p["name"]:
            self._do_select_job({"name": p["name"]})
            res["restated"] = (
                "템플릿을 다시 연결했습니다 — 작업을 다시 불러왔습니다. "
                "데이터·저장 폴더 선택을 확인하세요."
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
        return "실행할 작업을 먼저 선택하세요." if self.vm is None else None

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

        pywebview js_api 는 UI 스레드 밖에서 돌아 블로킹 생성이 창을 얼리지 않는다 —
        레코드마다 진행 델타를 푸시한다. 실패/차단은 조용히 삼키지 않고 dict 로 재진술.
        """
        if self.vm is None:
            return {"ok": False, "error": "실행할 작업을 먼저 선택하세요.", "level": "warn"}
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

        # 4) 덮어쓰기 확인(RC-02) — 같은 날짜 토큰 시각을 고정해 확인·생성이 일치하게.
        now = datetime.now()
        conflicts = self.vm.output_conflicts(indices, out_dir, mark_missing=marker, now=now)
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

        summary = f"완료 — 성공 {batch.succeeded}/{batch.total} · 실패 {batch.failed}"
        if blanks:
            summary += f" · 미입력 표시 필드 {len(blanks)}개({', '.join(blanks)})"
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
