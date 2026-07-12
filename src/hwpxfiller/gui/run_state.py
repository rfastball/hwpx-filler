"""실행(Run) 화면 ViewModel — Qt 비의존 실행 결정(데이터·대상·사전검증·게이트).

위젯(:class:`~hwpxfiller.gui.run_view.RunView`)에서 백엔드로 새던 부분을 여기로 옮겼다:
``DataSource`` 포트(팩토리 경유)·``HwpxEngine``·``RunRequest`` 는 이 뷰모델만 만지고,
위젯은 QThread·QMessageBox·QFileDialog 같은 Qt 오케스트레이션만 남긴다(링1: PySide6 금지).
**매핑 재확정 없음** — 매핑은 작업 정의 때 확정됐고 여기선 사전검증만 한다.

이 뷰모델 표면(dataclass 결과 + 메서드)이 목업 실행 화면이 겨누는 seam 계약이다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..core.engine import HwpxEngine
from ..core.fill_ledger import (
    TemplateStructureDrift,
    template_path_drift,
    template_structure_drift,
)
from ..core.job import Job, RunRequest
from ..core.mapping import MappingProfile
from ..data import source_for_path
from ..naming import existing_outputs, plan_output_names


@dataclass
class PreflightResult:
    """사전검증 표시용 — 데이터에 없는 항목(치명)·빈 출력값(경고)."""

    missing_columns: "list[str]" = field(default_factory=list)
    empty_valued: "list[str]" = field(default_factory=list)
    level: str = ""          # ""/"ok"/"warn"/"danger" (style.mark 레벨)
    text: str = ""

    def issues(self) -> "list[str]":
        """로그용 이슈 목록(데이터 항목 누락 + 빈값, 문서순 중복제거)."""
        return list(dict.fromkeys(list(self.missing_columns) + list(self.empty_valued)))


@dataclass
class PrevNote:
    """기존 문서 이어채우기 정합 고지(비차단)."""

    text: str
    level: str  # ""/"warn"/"danger"


@dataclass
class GateError:
    """생성 차단 사유 — 위젯이 message/level 로 대화상자를 띄운다."""

    message: str
    level: str  # "warn"(확인) / "danger"(오류)


@dataclass
class FieldState:
    """실행 화면 상시 인라인 배지 1개(ADR-E/B) — 필드의 채움 상태."""

    name: str
    state: str            # "filled" | "blank" | "missing" | "drift"(구조 불일치)
    acknowledged: bool = False  # missing 만 유효 — 사용자가 직접 확인했는가


@dataclass(frozen=True)
class GateState:
    """생성 게이트의 **단일 표시 결정**(RC-23) — 위젯은 이걸 그대로 렌더만 한다.

    unmet/drift 판정과 차단 문구가 위젯에 재조립되던 이중 진실을 소거한다 —
    버튼 활성 여부와 게이트 라벨(level/text)이 한 산출에서 나온다.
    """

    enabled: bool
    level: str  # ""/"warn"/"danger" (style.mark 레벨)
    text: str


@dataclass(frozen=True)
class RunStatus:
    """상태 리프레시 1회의 **단일 스냅샷**(RC-23) — 사전검증·필드 배지·게이트.

    한 번의 계산(레코드 매핑 1회 + 템플릿 구조 1회 재읽기)에서 세 표시면이 전부
    파생된다 — 표시면마다 재질의해 리프레시 1회당 템플릿 zip 을 5회 재파싱하고
    표시면 간 모순(상단 '통과' 녹색 + 하단 드리프트 차단)이 생기던 결함의 봉합.
    """

    preflight: PreflightResult
    field_states: "tuple[FieldState, ...]"
    gate: GateState


@dataclass(frozen=True)
class GenerationPlan:
    """생성 1회의 **불변 계획**(RC-07) — 게이트 통과 시점의 전체 스냅샷.

    워커·완료 핸들러·원장 export 가 이것만 소비한다. 실행 중 사용자의 위젯 조작
    (출력 폴더 편집·데이터 재로드)이 라이브 재독을 통해 원장에 생성물과 다른
    데이터·폴더를 '증거'로 기록하던 결함의 봉합 — 계획에 없는 값은 소비할 수 없다.
    """

    template: str
    records: "tuple[dict, ...]"          # 매핑+표식 적용 완료(생성 입력 그대로)
    out_dir: str
    pattern: str
    marker: str                          # 이번 생성에 실제 쓴 미입력 표식("" = 없음)
    indices: "tuple[int, ...]"
    source_pointer: str                  # 원장 소스 표기(포인터-온리)
    overwrite: bool = False              # 사용자 확정을 받은 덮어쓰기(RC-02)
    ledger: bool = False                 # 원장 사이드카 opt-in
    # ---- 원장 문맥(ledger=True 일 때 워커 꼬리가 소비) — 전부 계획 시점 캡처 ----
    job_name: str = ""
    mapping: "MappingProfile | None" = None
    template_fields: "tuple[str, ...]" = ()
    source_records: "tuple[dict, ...]" = ()   # 매핑 전 실제형(프로파일링 대상)
    source_keys: "tuple[str, ...]" = ()
    labels: "dict[str, str]" = field(default_factory=dict)


def export_plan_ledger(plan: GenerationPlan, batch) -> str:
    """계획 스냅샷 + 배치 결과만으로 원장 사이드카 저장(RC-07) — 라이브 상태 재독 0.

    조립·저장은 GUI/CLI 공유 단일 함수
    :func:`~hwpxfiller.core.fill_ledger.export_batch_ledger`(RC-03). 저장 경로 반환,
    실패는 raise(호출측 워커/뷰가 시끄럽게 표면화).
    """
    from ..core.fill_ledger import export_batch_ledger

    if plan.mapping is None:
        raise ValueError("원장 export 에는 계획의 매핑 스냅샷이 필요합니다.")
    sidecar = export_batch_ledger(
        plan.out_dir,
        template=plan.template,
        source=plan.source_pointer,
        mapping=plan.mapping,
        template_fields=list(plan.template_fields),
        results=batch.results,
        mapped_records=list(plan.records),
        source_records=list(plan.source_records),
        source_keys=list(plan.source_keys),
        labels=dict(plan.labels),
        job_name=plan.job_name,
        missing_marker=plan.marker,
    )
    return str(sidecar)


# ------------------------------------------ 데이터 겨눔 리졸버(단일 실행·매트릭스 공용)
def resolve_file_source(path: str) -> "tuple[object, list[dict]]":
    """파일 경로 → (DataSource, records). 팩토리가 종류 선택(엑셀/CSV). 로드 실패는 raise."""
    source = source_for_path(path)
    return source, source.records()


def resolve_pool_source(item, *, secret_store=None, fetcher=None) -> "tuple[object, list[dict]]":
    """데이터셋 풀 항목(참조) → (DataSource, records). 실행 시점 재읽기="싱크".

    나라장터는 N2 취득 경로(:class:`~hwpxfiller.gui.nara_state.NaraAcquireViewModel`)를 재사용
    — resultCode '00' 정합·기간 재검증·키 마스킹 관통, 만료·인증실패는 조용한 "0건"이 아니라
    **시끄러운** ``RuntimeError``. 성공은 **키 없는 스냅샷**이라 반복 조회가 재-fetch·키 재사용을
    하지 않는다. 엑셀 등 파일 소스는 라이브(파일 재읽기=싱크). 단일 실행·매트릭스가 공유한다.
    """
    if getattr(item, "kind", None) == "nara":
        from .nara_state import NaraAcquireViewModel

        opts = dict(item.opts)
        avm = NaraAcquireViewModel(secret_store, fetcher=fetcher)
        res = avm.acquire(
            str(opts.get("bgn_dt", "")), str(opts.get("end_dt", "")),
            num_rows=int(opts.get("num_rows", 100)),
            page_no=int(opts.get("page_no", 1)),
        )
        if not res.ok:
            raise RuntimeError(f"나라장터 데이터 취득 실패: {res.error}")
        return res.as_datasource(), res.records

    from ..data.factory import source_from_pool_item

    source = source_from_pool_item(item, secret_store=secret_store, fetcher=fetcher)
    return source, source.records()


class RunViewModel:
    """작업 1건 실행 상태·결정. 데이터·대상 문서는 DataSource 이음새 뒤에 둔다."""

    def __init__(self, job: Job):
        self.job = job
        self.datasource = None                 # DataSource 포트(팩토리가 생성)
        self.records: "list[dict]" = []
        # 이어채우기: 기존 문서가 **템플릿 자리**에 온다(데이터 소스 아님 — 이음새 무관).
        self.template_override: "str | None" = None
        self.target_mode = "new"               # "new" | "continue"
        self._acked: "set[str]" = set()        # 사용자가 직접 확인한 미입력 필드(ADR-E)

    # ------------------------------------------------------------ 대상 문서
    def effective_template(self) -> str:
        """생성이 겨눌 문서 — 누적 모드면 이전 출력, 아니면 작업 템플릿."""
        return self.template_override or self.job.template_path

    def set_target_mode(self, mode: str) -> None:
        """새 문서/기존 문서 이어채우기 전환. 새 문서 복귀 시 override 해제."""
        self.target_mode = mode
        if mode != "continue":
            self.template_override = None

    def set_prev_output(self, path: str) -> PrevNote:
        """기존 문서를 겨누고 정합 고지를 계산한다(값 겹침 덮어씀을 시끄럽게 — ADR G).

        누름틀은 채운 뒤에도 재발견되므로(engine.required_fields) 교집합으로 판정.
        값 수준 '이미 채워짐' 검사는 필드 값 읽기 API 부재로 파킹.
        """
        self.template_override = path
        try:
            doc_fields = set(HwpxEngine().required_fields(path))
        except Exception as exc:  # noqa: BLE001
            return PrevNote(f"기존 문서를 읽을 수 없습니다: {exc}", "danger")
        ours = set(self.job.template_fields())
        inter = doc_fields & ours
        if not inter:
            return PrevNote("이 작업의 필드가 이 문서에 하나도 없습니다 — 파일을 확인하세요.", "danger")
        return PrevNote(
            f"이 작업의 필드 {len(ours)}개 중 {len(inter)}개가 문서에 있습니다. "
            "이미 값이 있는 겹침 필드는 덮어씁니다 — 단계별 필드는 서로소로 설계하세요.",
            "warn" if len(inter) < len(ours) else "",
        )

    # ------------------------------------------------------------ 데이터
    def load_data(self, path: str) -> "list[dict]":
        """겨눈 경로에서 레코드를 읽는다(팩토리가 종류 선택). 로드 실패는 raise,
        레코드 0건이면 상태를 바꾸지 않고 빈 리스트 반환(위젯이 경고)."""
        source, records = resolve_file_source(path)
        if not records:
            return []
        self.datasource = source
        self.records = records
        self.reset_acks()  # 새 데이터 → 미입력 확인 재평가
        return records

    def load_pool_item(self, item, *, secret_store=None, fetcher=None) -> "list[dict]":
        """데이터셋 풀 항목(참조)을 복원해 겨눈다 — 실행 시점 재읽기가 곧 "싱크".

        - **나라장터**: N2 :class:`~hwpxfiller.gui.nara_state.NaraAcquireViewModel` 취득 경로를
          재사용한다 — 기간(1개월) 재검증·``resultCode`` 정합('00'만 성공)·키 마스킹을 그대로
          관통시켜, 만료·인증실패 키가 조용한 "0건"이 아니라 **시끄러운 API 오류**로 실패하게
          한다(acquire 경로와 동일 엄격도). 성공 결과는 **키 없는 스냅샷**(``as_datasource``)이라
          실행뷰의 반복 조회가 재-fetch·키 재사용을 하지 않는다("싱크 = 의도적 1회 재읽기").
        - **엑셀 등 파일 소스**: :func:`~hwpxfiller.data.factory.source_from_pool_item` 로 라이브
          소스를 복원(지연·캐시, 파일 재읽기가 곧 싱크).

        키는 복원 순간에만 저장소에서 읽혀 스냅샷·레코드 어디에도 남지 않는다. 취득 실패는
        **마스킹된 채** raise(위젯이 시끄럽게 표시), 레코드 0건이면 상태 불변(위젯이 경고).
        실제 복원·마스킹·스냅샷은 :func:`resolve_pool_source`(단일 실행·매트릭스 공용)가 한다."""
        source, records = resolve_pool_source(
            item, secret_store=secret_store, fetcher=fetcher
        )
        if not records:
            return []
        self.datasource = source
        self.records = records
        self.reset_acks()
        return records

    def set_acquired(self, datasource, records: "list[dict]") -> None:
        """이미 만들어진(키 없는) 소스·레코드를 직접 겨눈다 — 나라 애드혹 취득 등.

        매트릭스 VM 과 같은 seam(RC-22) — datasource/records 직접 대입 + ``reset_acks``
        수동 호출 관례에 의존하다 누락 시 stale ack 로 미입력 게이트가 무단 통과하던
        잠복 함정을 원자 진입점으로 봉합한다.
        """
        self.datasource = datasource
        self.records = list(records)
        self.reset_acks()

    # ------------------------------------------------------------ 사전검증
    def request(self, indices: "list[int]") -> RunRequest:
        return RunRequest(self.job, self.datasource, list(indices))

    def preflight(self, indices: "list[int]") -> PreflightResult:
        """데이터에 없는 항목(치명)·구조 드리프트(치명)·빈값(경고) 판정(재확정 아님).

        위젯은 level/text 를 **그대로** 렌더한다(RC-23) — 드리프트 차단 중에 상단만
        '통과' 녹색으로 남는 모순 신호를 여기서 차단한다.
        """
        return self.refresh(indices).preflight

    def blank_fields(self, indices: "list[int]") -> "list[str]":
        """미충족 빈칸 필드(ADR-E 상시 인라인 게이트의 seam). 데이터 없으면 빈 목록."""
        if self.datasource is None:
            return []
        return list(self.request(indices).output_report().empty_valued)

    # ------------------------------------------------------- 상시 인라인 필드 상태(ADR-E)
    def _template_fields(self) -> "list[str]":
        """현재 대상 문서의 누름틀 집합. 드리프트 감지를 위해 매 호출 재읽기한다."""
        template = self.effective_template()
        if not template or not Path(template).exists():
            return []
        return list(HwpxEngine().required_fields(template))

    def structure_drift(self) -> TemplateStructureDrift:
        """현재 템플릿과 확정 매핑 커버의 대칭차(스냅샷 없는 구조 계약)."""
        return template_path_drift(self.effective_template(), self.job.mapping)

    def field_states(self, indices: "list[int]") -> "list[FieldState]":
        """필드별 3상태(채움/의도적 빈칸/미입력) — 상시 인라인 배지의 원천.

        채움/미입력은 값 매핑 출력에서, 의도적 빈칸은 매핑의 ``blank`` 선언에서 온다.
        템플릿↔커버 대칭차는 ``drift`` 로 별도 표시해 의도적 공란으로 오라벨하지 않는다.
        데이터 미겨눔이면 빈 목록(패널 비움).
        """
        return list(self.refresh(indices).field_states)

    # ------------------------------------------------ 상태 스냅샷·게이트 단일 산출(RC-23)
    def refresh(self, indices: "list[int]") -> RunStatus:
        """상태 리프레시 1회의 단일 스냅샷 — 사전검증·필드 배지·게이트를 동시 파생.

        레코드 매핑·템플릿 구조를 **각 1회만** 계산해 세 표시면이 같은 사실에서
        나온다(RC-23: 표시면별 재질의가 만들던 모순 신호·zip 5회 재파싱 해소).
        데이터 미겨눔이면 전부 공백이고 게이트는 열림 — ``validate_generate`` 가
        '먼저 데이터를 선택하세요'로 막는 기존 동작 보존.
        """
        if self.datasource is None:
            return RunStatus(PreflightResult(), (), GateState(True, "", ""))
        idx = list(indices)
        req = self.request(idx)
        src = req.source_report()
        out = req.output_report()
        drift, current_fields = self._structure_snapshot()
        states = self._compose_field_states(set(out.empty_valued), drift, current_fields)
        return RunStatus(
            preflight=self._compose_preflight(src, out, drift),
            field_states=tuple(states),
            gate=self._compose_gate(states, drift),
        )

    def gate_state(self, indices: "list[int]") -> GateState:
        """생성 게이트 표시 결정(활성/level/text)의 단일 통합(RC-23)."""
        return self.refresh(indices).gate

    def _structure_snapshot(self) -> "tuple[TemplateStructureDrift, set[str]]":
        """템플릿 구조 1회 재읽기 → (드리프트, 현재 누름틀 집합).

        읽기 실패는 :func:`template_path_drift` 와 동일하게 ``read_error``
        (fail-closed)로 남긴다 — 드리프트 감지를 위해 refresh 마다 재읽기한다.
        """
        template = self.effective_template()
        if not template:
            return TemplateStructureDrift(read_error="템플릿 경로가 비어 있습니다."), set()
        try:
            fields = HwpxEngine().required_fields(template)
        except Exception as exc:  # noqa: BLE001 - 구조를 증명 못 하면 fail-closed
            return TemplateStructureDrift(read_error=str(exc)), set()
        return template_structure_drift(fields, self.job.mapping), set(fields)

    def _compose_field_states(
        self, empty: "set[str]", drift: TemplateStructureDrift, current_fields: "set[str]"
    ) -> "list[FieldState]":
        drift_fields = drift.symmetric_difference | set(drift.conflicting)
        blanks = {f for f in self.job.mapping.blank_fields() if f in current_fields}
        # 매핑 계약순 뒤에 템플릿 신규 유입순을 붙인다. 사라진 값 매핑도 drift 하나로
        # 표시해 filled/missing과 중복·모순되지 않게 한다.
        order = list(self.job.mapping.cover_fields()) + list(drift.template_only)
        states: "list[FieldState]" = []
        for name in dict.fromkeys(order):
            if name in drift_fields:
                states.append(FieldState(name, "drift"))
            elif name in blanks:
                states.append(FieldState(name, "blank"))
            else:
                states.append(FieldState(
                    name, "missing" if name in empty else "filled", name in self._acked
                ))
        return states

    def _compose_gate(
        self, states: "list[FieldState]", drift: TemplateStructureDrift
    ) -> GateState:
        """게이트 표시 결정 — 드리프트(danger·차단) > 미확인 미입력(warn·차단) > 열림."""
        if drift.has_drift:
            if drift.read_error:
                return GateState(False, "danger", "템플릿 구조를 읽을 수 없어 생성이 차단됩니다.")
            names = list(drift.template_only) + list(drift.mapping_only) + list(drift.conflicting)
            return GateState(
                False, "danger",
                "템플릿 구조 드리프트 — 매핑을 다시 확정해야 생성할 수 있습니다: "
                + ", ".join(names),
            )
        unmet = [s.name for s in states if s.state == "missing" and not s.acknowledged]
        if unmet:
            return GateState(
                False, "warn",
                f"미입력 {len(unmet)}필드를 확인해야 문서 생성이 가능합니다: {', '.join(unmet)}",
            )
        return GateState(True, "", "")

    def _compose_preflight(self, src, out, drift: TemplateStructureDrift) -> PreflightResult:
        parts: "list[str]" = []
        if src.missing_columns:
            parts.append(
                "[치명] 데이터에 없는 항목입니다(빈 값 생성됨): " + ", ".join(src.missing_columns)
            )
        if drift.has_drift:
            # 게이트가 상세 사유를 렌더한다 — 여기선 '통과' 녹색이 남지 않게만 알린다.
            parts.append("[치명] 템플릿 구조가 확정 매핑과 다릅니다 — 아래 차단 사유를 확인하세요.")
        if out.empty_valued:
            parts.append("[경고] 값이 비어 있는 필드: " + ", ".join(out.empty_valued))
        if src.missing_columns or drift.has_drift:
            level = "danger"
        elif out.empty_valued:
            level = "warn"
        else:
            level = "ok"
        return PreflightResult(
            list(src.missing_columns), list(out.empty_valued), level,
            "\n".join(parts) if parts
            else "사전검증 통과 — 치명 누락 없음. 아래 빈 값 표면화를 확인하세요.",
        )

    def acknowledge(self, field: str) -> None:
        """미입력 필드를 사용자가 직접 확인함(강제 상호작용)."""
        self._acked.add(field)

    def reset_acks(self) -> None:
        """확인 상태 초기화(새 데이터 겨눔 등)."""
        self._acked.clear()

    def unmet_blanks(self, indices: "list[int]") -> "list[str]":
        """미입력이면서 아직 확인 안 된 필드 — 이게 남아 있으면 생성 게이트가 닫힌다."""
        return [
            s.name for s in self.field_states(indices)
            if s.state == "missing" and not s.acknowledged
        ]

    # ------------------------------------------------------------ 생성 게이트
    def validate_generate(self, indices: "list[int]", out_dir: str) -> "list[GateError]":
        """생성 전 가드 — 첫 차단 사유만 반환(없으면 빈 목록)."""
        indices = list(indices)
        if self.datasource is None:
            return [GateError("먼저 데이터를 선택하세요.", "warn")]
        if self.target_mode == "continue" and not self.template_override:
            return [GateError("이어채울 기존 문서(.hwpx)를 선택하세요.", "warn")]
        template = self.effective_template()
        if template and not Path(template).exists():
            return [GateError(f"템플릿을 찾을 수 없습니다:\n{template}", "danger")]
        drift = self.structure_drift()
        if drift.has_drift:
            # 상세 문구는 describe() 단일화(RC-03) — CLI/생성 경계와 같은 문장.
            return [GateError(
                "템플릿 구조가 확정 매핑과 다릅니다. 매핑을 다시 확정해 전건 커버를 "
                "회복해야 생성할 수 있습니다.\n" + drift.describe(),
                "danger",
            )]
        if not out_dir:
            return [GateError("저장 폴더를 지정하세요.", "warn")]
        if not indices:
            return [GateError("생성할 레코드를 최소 1건 선택하세요.", "warn")]
        if self.template_override and len(indices) != 1:
            # 누적 v1 = 단건. 배치 누적(이전출력↔레코드 파일키 매칭)은 별개 설계 — 파킹.
            return [GateError(
                "기존 문서 이어채우기는 레코드 1건만 지원합니다 — 문서 1개에 여러 "
                "레코드를 겹쳐 쓸 수 없습니다. 레코드를 1건만 선택하세요.", "warn")]
        return []

    def mapped_records(self, indices: "list[int]", mark_missing: str = "") -> "list[dict]":
        """선택 레코드에 매핑 적용 → {템플릿필드: 값}. mark_missing 시 빈 키에 표식 주입."""
        return self.request(indices).mapped_records(mark_missing=mark_missing)

    def output_conflicts(
        self, indices: "list[int]", out_dir: str, *, mark_missing: str = ""
    ) -> "list[str]":
        """생성이 덮어쓸 **기존** 파일 경로 목록 — 실행 전 덮어쓰기 확인의 원천(RC-02).

        생성과 동일한 매핑·표식·파일명 규칙으로 대상 경로를 계산해 디스크 존재만
        조회한다(무변형). 위젯은 이 목록이 비지 않으면 "기존 N개 파일을 덮어씁니다"
        사용자 확정을 받은 뒤에만 ``overwrite=True`` 로 진행한다(확인-또는-경보).
        """
        names = plan_output_names(
            self.job.filename_pattern, self.mapped_records(indices, mark_missing)
        )
        return existing_outputs(out_dir, names)

    # ------------------------------------------------------------ 생성 계획(RC-07)
    def build_generation_plan(
        self,
        indices: "list[int]",
        out_dir: str,
        *,
        marker: str = "",
        ledger: bool = False,
        overwrite: bool = False,
    ) -> GenerationPlan:
        """게이트 통과 직후 호출 — 생성·완료 처리·원장이 소비할 전부를 원자 캡처한다.

        이후 위젯/VM 이 어떻게 바뀌어도 이 계획은 불변이다(RC-07). ``marker`` 는
        생성에 실제 쓸 표식과 동일해야 원장 dry-run 행이 주입값과 일치한다.
        """
        idx = list(indices)
        labels_fn = getattr(self.datasource, "field_labels", None)
        labels = labels_fn() if callable(labels_fn) else {}
        return GenerationPlan(
            template=self.effective_template(),
            records=tuple(self.mapped_records(idx, marker)),
            out_dir=out_dir,
            pattern=self.job.filename_pattern,
            marker=marker,
            indices=tuple(idx),
            source_pointer=self.source_pointer(),
            overwrite=overwrite,
            ledger=ledger,
            job_name=self.job.name,
            mapping=self.job.mapping,
            template_fields=tuple(self._template_fields()),
            source_records=tuple(self.request(idx).selected_records()),
            source_keys=tuple(self.job.source_keys()),
            labels=dict(labels),
        )

    # ------------------------------------------------------------ 생성 원장(L2)
    def source_pointer(self) -> str:
        """원장에 남길 소스 표기 — **포인터-온리**(경로·종류). 쿼리·키는 박제하지 않는다.

        소스가 자기 표기를 선언하면(``source_pointer()`` — :mod:`hwpxfiller.data.base`
        의 선택 프로토콜) 그것이 우선한다. 문자열 타입명 비교로 소스 종류를 식별하지
        않는다 — 클래스 개명이 원장 침묵 오기록이 되지 않게(RC-25). 미선언 소스는
        ``path`` 속성(``file:<경로>``) → 타입명 순으로 강등 표기.
        """
        src = self.datasource
        if src is None:
            return ""
        pointer_fn = getattr(src, "source_pointer", None)
        if callable(pointer_fn):
            return str(pointer_fn())
        path = getattr(src, "path", "")
        if path:
            return f"file:{path}"
        return type(src).__name__

    def export_run_ledger(
        self, out_dir: str, indices: "list[int]", batch, *, mark_missing: str = ""
    ) -> str:
        """생성 원장 JSON 사이드카 저장(**opt-in**) — 저장 경로 반환, 실패는 raise.

        지금 상태를 계획으로 캡처해 :func:`export_plan_ledger` 에 위임한다 — 정상
        경로(위젯)는 생성 시점 계획을 워커 꼬리에서 그대로 export 하므로(RC-07)
        이 메서드는 헤드리스/사후 export 용 보조 표면이다. ``mark_missing`` 은 생성에
        실제 쓴 표식과 동일해야 dry-run 행이 주입값과 일치한다. 되읽기 검증·마스킹은
        :func:`~hwpxfiller.core.fill_ledger.export_run_ledger` 계열이 관통시킨다.
        파일명은 실행별 타임스탬프(RC-02) — 재실행이 이전 증거를 덮지 않는다.
        """
        plan = self.build_generation_plan(
            list(indices), out_dir, marker=mark_missing, ledger=True
        )
        return export_plan_ledger(plan, batch)
