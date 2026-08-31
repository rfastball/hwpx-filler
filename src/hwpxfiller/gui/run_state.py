"""실행(Run) 화면 ViewModel — Qt 비의존 실행 결정(데이터·대상·사전검증·게이트).

웹 작업 컨트롤러(:class:`~hwpxfiller.webapp.screen_job.JobController`)는 이 뷰모델에 실행 결정을
위임한다. ``DataSource`` 포트(팩토리 경유)·``HwpxEngine``·``RunRequest`` 는 이 뷰모델만
만지고, 컨트롤러는 렌더·확인·파일 선택 같은 UI 오케스트레이션을 맡는다(링1: PySide6 금지).
**매핑 재확정 없음** — 매핑은 작업 정의 때 확정됐고 여기선 사전검증만 한다.

이 뷰모델 표면(dataclass 결과 + 메서드)이 목업 실행 화면이 겨누는 seam 계약이다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Protocol

from ..domain.engine import HwpxEngine

if TYPE_CHECKING:
    from datetime import datetime
from ..domain.fill_ledger import (
    TemplateStructureDrift,
    template_path_drift,
    template_structure_drift,
)
from ..domain.job import Job, RunRequest, has_data_binding, require_hwpx
from ..domain.mapping import MappingProfile
from ..naming import (
    OutputNameAudit,
    audit_output_names,
    pattern_field_tokens,
    plan_output_names,
)
from .review_state import ReviewRequirement, review_gate_text


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
    """생성 차단 사유 — 표현 계층이 ``message``/``level``로 고지한다."""

    message: str
    level: str  # "warn"(확인) / "danger"(오류)


@dataclass
class FieldState:
    """필드의 채움 상태 1개(ADR-E/B). 필드축 ack 는 폐기됐다(U2 §2.13) — 빈 값은
    클릭 확인 대상이 아니라 승인 지문의 성분(``blank_set``)이고, 표식 삽입 동의는
    승인 1번이 겸한다."""

    name: str
    state: str            # "filled" | "blank" | "missing" | "drift"(구조 불일치)


#: 이 작업이 어떤 데이터에도 연결돼 있지 않다(U4 §2.4 · #932 U4-C). 축 이름이 따로 필요한
#: 이유는 표면의 지목이 달라서다 — `no_data` 는 「지금 무엇이 마운트됐나」의 세션 사실이고
#: 이쪽은 「이 작업이 무엇을 기억하나」의 작업 사실이라, 고칠 자리도 피커가 아니라 편집기다.
GATE_REASON_DATA_UNBOUND = "data_unbound"


@dataclass(frozen=True)
class GateState:
    """생성 게이트의 **단일 표시 결정**(RC-23) — 표현 계층은 이걸 그대로 렌더만 한다.

    unmet/drift 판정과 차단 문구가 표현 계층에 재조립되던 이중 진실을 소거한다 —
    버튼 활성 여부와 게이트 라벨(level/text)이 한 산출에서 나온다.
    """

    enabled: bool
    level: str  # ""/"warn"/"danger" (style.mark 레벨)
    text: str
    #: 차단 사유의 기계 판독 이름 — **표시면이 게이트 서열을 재유도하지 않게** 한다(리뷰 F2).
    #: 거울 배너는 자기 사실(드리프트 목록·미해소 토큰)을 따로 보고 그리면 게이트가 실제로
    #: 막고 있는 이유와 다른 것을 크게 말할 수 있다(예: 템플릿을 못 읽는데 "파일명을 고치라").
    #: ""=이 사유 축과 무관(warn·열림).
    #: 값: drift | template_unreadable | name_tokens | review_required
    reason: str = ""


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
    #: 이 실행이 발급할 이름과 그 집합 성질(C-01, 재작성 F5). 게이트가 소비하고 미리보기
    #: 증거가 **같은 산출**을 재사용한다 — 표면이 따로 계획하면 미리보기가 실행과 다른
    #: 이름을 말할 수 있다(RC-23 이 표시면 간 모순에 대해 세운 규율의 파일명 판).
    audit: OutputNameAudit = field(default_factory=OutputNameAudit)


@dataclass(frozen=True)
class GenerationPlan:
    """생성 1회의 **불변 계획**(RC-07) — 게이트 통과 시점의 전체 스냅샷.

    실행기·완료 처리·원장 export 가 이것만 소비한다. 실행 중 사용자의 화면 조작
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
    # 날짜 토큰({{date}}) 기준 시각을 계획 시점에 **고정**한다(RC-02) — 덮어쓰기 확인이
    # 조회한 대상 파일과 실제 생성이 쓰는 파일이 하위-일 토큰에서 갈라지지 않도록.
    # None 이면 생성 시 datetime.now() 로 폴백(직접 구성 테스트 호환).
    now: "datetime | None" = None
    ledger: bool = False                 # 원장 사이드카 opt-in
    # ---- 원장 문맥(ledger=True 일 때 워커 꼬리가 소비) — 전부 계획 시점 캡처 ----
    job_name: str = ""
    mapping: "MappingProfile | None" = None
    template_fields: "tuple[str, ...]" = ()
    source_records: "tuple[dict, ...]" = ()   # 매핑 전 실제형(프로파일링 대상)
    source_keys: "tuple[str, ...]" = ()
    labels: "dict[str, str]" = field(default_factory=dict)


# (계획 스냅샷의 원장 사이드카 저장은 P2-18(#566)에서 External 로 승계 —
#  :func:`hwpxfiller.external.ledger_export.export_plan_ledger`. Application 은 계획
#  (:class:`GenerationPlan`)을 소유하고, durable 기록 효과는 adapter 가 소유한다.)


# ------------------------------------------------------------ 데이터 겨눔 리졸버
class FileSourceFactoryPort(Protocol):
    """파일 경로 → DataSource 포트 — 구체 종류 선택(엑셀/CSV)은 Host(``webapp.app``)가
    주입하는 factory 의 몫이다. 링1 은 포트만 안다(P2-16, `gui → data.factory` 역간선 제거)."""

    def __call__(
        self, path: str, *, sheet: "str | None" = None, header_row: int = 0,
    ) -> object: ...


class PoolSourceFactoryPort(Protocol):
    """풀 항목(참조) → DataSource 포트 — 복원·키 주입·pipeline 재귀는 Host 가 주입하는
    factory 의 몫이다. 나라장터 항목은 이 포트에 **오지 않는다**(아래 nara 분기가 선점)."""

    def __call__(self, item, *, secret_store=None, fetcher=None) -> object: ...


def resolve_file_source(
    path: str, *, sheet: "str | None" = None, header_row: int = 0,
    source_factory: FileSourceFactoryPort,
) -> "tuple[object, list[dict]]":
    """파일 경로 → (DataSource, records). 종류 선택은 주입된 factory. 로드 실패는 raise.

    ``sheet`` 는 사용자가 **확정한** 시트명(T2) — None 이면 기본(첫/유일 시트).
    확정은 표현 계층의 시트 선택 UI가 하고 여기는 옵션 관통만 한다(링1: PySide6 금지).
    ``source_factory`` 는 **필수 주입**(기본값·service locator 금지) — 조립은 Host 한 곳.

    ``header_row`` 는 참조가 들고 있던 읽기 옵션의 승계 자리다(0 = 어댑터 기본 1행).
    작업이 데이터를 durable 로 결속한 뒤(#932 U4-C) 이 값이 여기까지 와야 한다: 결속을
    경로+시트로만 되읽으면 헤더 행이 다른 파일을 **같은 데이터라고 부르며** 다른 표를
    세운다 — 화면 어디에도 표시가 없는 어긋남이다(#349 리뷰 P1 과 같은 자리).
    """
    opts: "dict[str, object]" = {"sheet": sheet}
    if header_row:
        opts["header_row"] = header_row
    source = source_factory(path, **opts)  # type: ignore[arg-type]
    return source, source.records()


def resolve_pool_source(
    item, *, secret_store=None, fetcher=None, nara_factory=None,
    source_factory: PoolSourceFactoryPort,
) -> "tuple[object, list[dict]]":
    """데이터셋 풀 항목(참조) → (DataSource, records). 실행 시점 재읽기="싱크".

    나라장터는 주입된 N2 취득 factory를 재사용
    — resultCode '00' 정합·기간 재검증·키 마스킹 관통, 만료·인증실패는 조용한 "0건"이 아니라
    **시끄러운** ``RuntimeError``. 성공은 **키 없는 스냅샷**이라 반복 조회가 재-fetch·키 재사용을
    하지 않는다. 엑셀 등 파일 소스는 라이브(파일 재읽기=싱크).
    """
    if getattr(item, "kind", None) == "nara":
        if nara_factory is None:
            raise RuntimeError("나라장터 취득 어댑터가 주입되지 않았습니다.")

        opts = dict(item.opts)
        avm = nara_factory(store=secret_store, fetcher=fetcher)
        res = avm.acquire(
            str(opts.get("bgn_dt", "")), str(opts.get("end_dt", "")),
            num_rows=int(opts.get("num_rows", 100)),
            page_no=int(opts.get("page_no", 1)),
        )
        if not res.ok:
            raise RuntimeError(f"나라장터 데이터 취득 실패: {res.error}")
        return res.as_datasource(), res.records

    source = source_factory(item, secret_store=secret_store, fetcher=fetcher)
    return source, source.records()


def template_missing(template_path: str) -> bool:
    """템플릿 「연결 상태」의 단일 술어 — 빈 경로와 파일 부재를 **한 축**으로 센다.

    #342 리뷰 3라운드가 세운 규율의 링1 승격(P2-24): 같은 질문을 표면마다 각자 답하면
    술어가 갈린다(빈 경로를 정상으로 보고한 스냅샷 vm-None 가지 전례). 둘 다 "이 작업으로는
    문서를 만들 수 없다"이고 복구 동선도 같은 재연결이다. 문안(「템플릿 없음」)은 표면 몫.
    """
    return not template_path or not Path(template_path).exists()


def unresolved_name_tokens_in(
    mapping: "MappingProfile", filename_pattern: str
) -> "list[str]":
    """파일명 패턴이 요구하는데 이 매핑이 채우지 못하는 데이터 토큰(F34, RC-20 GUI 짝).

    생성 파일명은 **매핑 적용 후** 레코드({템플릿필드: 값})에서 해소되므로 해소 가능 집합 =
    비움 아닌 매핑 커버 필드다(blank 선언 필드는 출력 dict 에서 빠져 토큰이 리터럴로 남는다).
    매핑 적용 키는 전 레코드 균일이라 CLI 의 '일부 레코드 누락' 경고 분기는 GUI 에 원리적으로
    없다.

    **데이터 없이도 판정 가능한 작업 정의 수준의 계약 검사**라 ``Job`` 이 아직 없는 자리
    (저장 게이트 :func:`~hwpxfiller.gui.job_editor_state.validate_save`, U4 계열4-4)에서도
    같은 몸통을 부를 수 있게 프로파일 수준으로 둔다 — 저장 게이트가 이 술어를 다시 지으면
    같은 상태를 두 곳이 판정한다.
    """
    resolved = set(mapping.cover_fields()) - set(mapping.blank_fields())
    return [t for t in pattern_field_tokens(filename_pattern) if t not in resolved]


def unresolved_name_tokens_for(job: "Job") -> "list[str]":
    """:func:`unresolved_name_tokens_in` 의 ``Job`` 결속 형태.

    실행 게이트(:meth:`RunViewModel._name_token_gate`)와 전역 건강 보기(§19.7 번역)가 이
    한 몸통을 공유한다 — 두 표면이 같은 상태를 다르게 부르지 않게(리뷰 P2). 저장 게이트가
    선 뒤에도 **방어층으로 남는다**: 이 앱 밖에서 편집되거나 저장 게이트 이전에 만들어진
    작업은 여전히 미해소 토큰을 들 수 있다(조용한 리터럴 파일명 금지).
    """
    return unresolved_name_tokens_in(job.mapping, job.filename_pattern)


class RunViewModel:
    """작업 1건 실행 상태·결정. 데이터·대상 문서는 DataSource 이음새 뒤에 둔다."""

    def __init__(self, job: Job, *, engine: HwpxEngine):
        # 진입 가드(3부 결정 13 · 2층): 실행뷰는 hwpx 생성 경로다 — HwpxEngine.required_fields·
        # template_path_drift 가 이 job 의 템플릿을 hwpx 로 파싱한다. txt 기안 작업은 「기안」
        # 화면이 자기 경로로 소비하므로 여기 오면 조회 경계가 샌 것 → loud 거부(조용한 오파싱 금지).
        require_hwpx(job)
        self.job = job
        # zip IO 가 결속된 엔진은 Host/ring 2 가 주입한다(P3-03 — 링1 은 concrete package
        # read/write adapter를 모른다. P2-16 source factory 주입과 같은 seam).
        self._engine = engine
        self.datasource = None                 # DataSource 포트(팩토리가 생성)
        self.records: "list[dict]" = []
        # 이어채우기: 기존 문서가 **템플릿 자리**에 온다(데이터 소스 아님 — 이음새 무관).
        self.template_override: "str | None" = None
        # managed Product Work 생성이 고정한 exact applied bytes staged 경로(#681 G11) —
        # mutable job.template_path 대신 이걸 소비한다. 이어채우기(override)가 우선한다.
        self._managed_template: "str | None" = None
        self.target_mode = "new"               # "new" | "continue"

    # ------------------------------------------------------------ 대상 문서
    def effective_template(self) -> str:
        """생성이 겨눌 문서 — 이어채우기면 이전 출력, managed 생성이면 staged exact bytes,
        아니면 작업 템플릿."""
        return self.template_override or self._managed_template or self.job.template_path

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
            doc_fields = set(self._engine.required_fields(path))
        except Exception as exc:  # noqa: BLE001
            return PrevNote(f"기존 문서를 읽을 수 없습니다: {exc}", "danger")
        ours = set(self.job.template_fields())
        inter = doc_fields & ours
        if not inter:
            return PrevNote("이 작업의 필드가 이 문서에 하나도 없습니다. 파일을 확인하세요.", "danger")
        return PrevNote(
            f"이 작업의 필드 {len(ours)}개 중 {len(inter)}개가 문서에 있습니다. "
            "이미 값이 있는 겹침 필드는 덮어씁니다.",
            "warn" if len(inter) < len(ours) else "",
        )

    # ------------------------------------------------------------ 데이터
    def load_data(
        self, path: str, *, sheet: "str | None" = None,
        source_factory: FileSourceFactoryPort,
    ) -> "list[dict]":
        """겨눈 경로에서 레코드를 읽는다(주입된 factory 가 종류 선택). 로드 실패는 raise,
        레코드 0건이면 상태를 바꾸지 않고 빈 리스트 반환(표현 계층이 경고).
        ``sheet`` 는 사용자가 확정한 시트명(T2) — None 이면 기본(첫/유일 시트)."""
        source, records = resolve_file_source(path, sheet=sheet, source_factory=source_factory)
        if not records:
            return []
        self.datasource = source
        self.records = records
        return records

    def load_pool_item(
        self, item, *, secret_store=None, fetcher=None, nara_factory=None,
        source_factory: PoolSourceFactoryPort,
    ) -> "list[dict]":
        """데이터셋 풀 항목(참조)을 복원해 겨눈다 — 실행 시점 재읽기가 곧 "싱크".

        - **나라장터**: 주입된 N2 취득 factory 경로를
          재사용한다 — 기간(1개월) 재검증·``resultCode`` 정합('00'만 성공)·키 마스킹을 그대로
          관통시켜, 만료·인증실패 키가 조용한 "0건"이 아니라 **시끄러운 API 오류**로 실패하게
          한다(acquire 경로와 동일 엄격도). 성공 결과는 **키 없는 스냅샷**(``as_datasource``)이라
          실행뷰의 반복 조회가 재-fetch·키 재사용을 하지 않는다("싱크 = 의도적 1회 재읽기").
        - **엑셀 등 파일 소스**: 주입된 ``source_factory``(Host 가 조립한 풀 복원 factory)로
          라이브 소스를 복원(지연·캐시, 파일 재읽기가 곧 싱크).

        키는 복원 순간에만 저장소에서 읽혀 스냅샷·레코드 어디에도 남지 않는다. 취득 실패는
        **마스킹된 채** raise(표현 계층이 시끄럽게 표시), 레코드 0건이면 상태 불변(표현 계층이 경고).
        실제 복원·마스킹·스냅샷은 :func:`resolve_pool_source` 가 한다."""
        source, records = resolve_pool_source(
            item,
            secret_store=secret_store,
            fetcher=fetcher,
            nara_factory=nara_factory,
            source_factory=source_factory,
        )
        if not records:
            return []
        self.datasource = source
        self.records = records
        return records

    def set_acquired(self, datasource, records: "list[dict]") -> None:
        """이미 만들어진(키 없는) 소스·레코드를 직접 겨눈다 — 나라 애드혹 취득 등.

        데이터 귀속 상태의 원자 진입점(RC-22)으로 남는다. 종전에 여기서 재평가하던
        빈 값 확인(ack)은 폐기됐다(U2 §2.13) — 빈 값 집합은 이제 승인 지문의 성분이라
        데이터가 갈리면 승인이 키 결속으로 자동 무효가 된다(별도 리셋 코드 불요).
        """
        self.datasource = datasource
        self.records = list(records)

    # ------------------------------------------------------------ 사전검증
    def request(self, indices: "list[int]") -> RunRequest:
        return RunRequest(self.job, self.datasource, list(indices))

    def preflight(self, indices: "list[int]") -> PreflightResult:
        """데이터에 없는 항목(치명)·구조 드리프트(치명)·빈값(경고) 판정(재확정 아님).

        표현 계층은 level/text 를 **그대로** 렌더한다(RC-23) — 드리프트 차단 중에 상단만
        '통과' 녹색으로 남는 모순 신호를 여기서 차단한다.
        """
        return self.refresh(indices).preflight

    def blank_fields(self, indices: "list[int]") -> "list[str]":
        """선택분에서 값이 빈 필드 — 표식(`MISSING_MARKER`)·빈 값 표지·승인 지문
        성분(`blank_set`, U2 §2.13)의 단일 원천. 데이터 없으면 빈 목록."""
        if self.datasource is None:
            return []
        return list(self.request(indices).output_report().empty_valued)

    # ------------------------------------------------------- 상시 인라인 필드 상태(ADR-E)
    def _template_fields(self) -> "list[str]":
        """현재 대상 문서의 누름틀 집합. 드리프트 감지를 위해 매 호출 재읽기한다."""
        template = self.effective_template()
        if template_missing(template):
            return []
        return list(self._engine.required_fields(template))

    def structure_drift(self) -> TemplateStructureDrift:
        """현재 템플릿과 확정 매핑 커버의 대칭차(스냅샷 없는 구조 계약)."""
        return template_path_drift(
            self.effective_template(), self.job.mapping, engine=self._engine
        )

    def field_states(self, indices: "list[int]") -> "list[FieldState]":
        """필드별 3상태(채움/의도적 빈칸/미입력) — 상시 인라인 배지의 원천.

        채움/미입력은 값 매핑 출력에서, 의도적 빈칸은 매핑의 ``blank`` 선언에서 온다.
        템플릿↔커버 대칭차는 ``drift`` 로 별도 표시해 의도적 공란으로 오라벨하지 않는다.
        데이터 미겨눔이면 빈 목록(패널 비움).
        """
        return list(self.refresh(indices).field_states)

    # ------------------------------------------------ 상태 스냅샷·게이트 단일 산출(RC-23)
    def unresolved_name_tokens(self) -> "list[str]":
        """이 작업의 미해소 파일명 토큰 — 판정 몸통은 :func:`unresolved_name_tokens_for`."""
        return unresolved_name_tokens_for(self.job)

    def _name_token_gate(self) -> "GateState | None":
        """미해소 파일명 토큰의 게이트 발화(danger·차단) — 없으면 None."""
        unresolved = self.unresolved_name_tokens()
        if not unresolved:
            return None
        toks = ", ".join("{{" + t + "}}" for t in unresolved)
        # 문안이 사망한 화면을 지시하지 않게(#128): 「작업 에디터」 화면·레일 항목은 결정 39·40
        # 으로 사망했고 같은 자리 드리프트 배너는 이미 "편집에서…"로 개정돼 있었다. 두 danger 가
        # 같은 목적지를 다르게 부르면, 둘 중 하나는 반드시 존재하지 않는 곳을 가리킨다.
        return GateState(
            False, "danger",
            f"파일명 패턴의 토큰이 채워지지 않아 파일명에 그대로 남습니다: "
            f"{toks}. 편집에서 파일명 패턴을 고쳐야 생성할 수 있습니다.",
            reason="name_tokens",
        )

    def refresh(
        self, indices: "list[int]", out_dir: str = "", *,
        review_unmet: "ReviewRequirement | None" = None,
        mapped: "list[dict] | None" = None,
        now: "datetime | None" = None,
    ) -> RunStatus:
        """상태 리프레시 1회의 단일 스냅샷 — 사전검증·필드 배지·게이트를 동시 파생.

        레코드 매핑·템플릿 구조를 **각 1회만** 계산해 세 표시면이 같은 사실에서
        나온다(RC-23: 표시면별 재질의가 만들던 모순 신호·zip 5회 재파싱 해소).
        데이터 미겨눔이면 표시면은 공백이되 게이트는 **닫힌 인라인 사유**로 발화한다
        (UD-06: '활성 primary + 클릭 후 모달' 이원화를 '버튼 비활성 + 인라인 사유'로 통일
        — 초기 상태 침묵 해소). 저장 폴더·레코드 선택 같은 warn 급 전제조건도 여기서
        게이트로 흡수해 모달은 danger 예외에만 남긴다. 파일명 토큰 계약(F34)은 데이터
        없이도 판정되므로 미겨눔 상태에서도 danger 로 먼저 발화한다 — 고칠 수 없는
        작업에 데이터부터 고르게 하지 않는다.

        ``review_unmet`` 은 **아직 승인되지 않은** 검토 요구(재작성 F5, 지도 §10.12 판정 F).
        요구 판정과 승인 대조는 세션이 하고(기준선은 durable·승인은 세션), 여기서는 그
        결과를 게이트 서열에 끼운다 — 서열의 권위가 둘로 갈리지 않게 표시 결정은 계속
        :meth:`_compose_gate` 단일 산출이다.
        """
        name_gate = self._name_token_gate()
        if self.datasource is None:
            return RunStatus(
                PreflightResult(), (),
                name_gate or GateState(False, "warn", "먼저 데이터를 선택하세요."),
            )
        idx = list(indices)
        req = self.request(idx)
        src = req.source_report()
        out = req.output_report()
        drift, current_fields = self._structure_snapshot()
        states = self._compose_field_states(set(out.empty_valued), drift, current_fields)
        # 이름 계획은 **대상이 있으면** 낸다(미리보기가 폴더 없이도 이름을 보여준다).
        # 경로 길이만 폴더에 의존하고, 폴더가 없으면 잴 경로가 없어 조용하다.
        # ``mapped`` 는 호출측이 이미 만든 매핑 결과 — 넘겨받아 같은 계산을 두 번 하지 않는다.
        audit = (
            audit_output_names(
                self.job.filename_pattern,
                self.mapped_records(idx, now=now) if mapped is None else mapped,
                out_dir,
                now=now,
            ) if idx else OutputNameAudit()
        )
        return RunStatus(
            preflight=self._compose_preflight(
                src, out, drift, name_gate is not None, len(audit.too_long),
            ),
            field_states=tuple(states),
            gate=self._compose_gate(
                states, drift, idx, out_dir, name_gate, review_unmet, audit,
            ),
            audit=audit,
        )

    def gate_state(self, indices: "list[int]", out_dir: str = "") -> GateState:
        """생성 게이트 표시 결정(활성/level/text)의 단일 통합(RC-23)."""
        return self.refresh(indices, out_dir).gate

    def _structure_snapshot(self) -> "tuple[TemplateStructureDrift, set[str]]":
        """템플릿 구조 1회 재읽기 → (드리프트, 현재 누름틀 집합).

        읽기 실패는 :func:`template_path_drift` 와 동일하게 ``read_error``
        (fail-closed)로 남긴다 — 드리프트 감지를 위해 refresh 마다 재읽기한다.
        """
        template = self.effective_template()
        if not template:
            return TemplateStructureDrift(read_error="템플릿 경로가 비어 있습니다."), set()
        try:
            fields = self._engine.required_fields(template)
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
                states.append(FieldState(name, "missing" if name in empty else "filled"))
        return states

    def _compose_gate(
        self, states: "list[FieldState]", drift: TemplateStructureDrift,
        indices: "list[int]", out_dir: str, name_gate: "GateState | None" = None,
        review_unmet: "ReviewRequirement | None" = None,
        audit: "OutputNameAudit | None" = None,
    ) -> GateState:
        """게이트 표시 결정 — 드리프트(danger·차단) > 파일명 토큰(danger) >
        **데이터 결속(warn)** > 세션 전제조건(warn) > **검토 요구(warn)** > 열림.

        결속 단이 세션 전제조건보다 앞선 이유는 **고칠 자리가 다르기** 때문이다(U4 §2.4):
        저장 폴더·행 선택은 이 화면에서 지우지만 결속은 편집기를 지난다. 세션을 다 갖춰도
        남는 결핍을 뒤에 두면 사용자가 준비를 마친 뒤에야 진짜 막힌 이유를 듣는다.

        구 「미확인 미입력」 단은 필드축 ack 폐기(U2 §2.13)와 함께 죽었다 — 빈 값은
        승인 지문의 성분(``blank_set`` 위험종)이 되어 검토 요구 단이 진다.

        UD-06: 이어채우기 문서·저장 폴더·레코드 선택 같은 warn 급 전제조건을 이 단일
        산출로 흡수해 '버튼 비활성 + 인라인 사유' 문법으로 통일한다(클릭 후 차단 모달
        재유입 소거 — 모달은 danger 예외에만 남긴다). 템플릿 부재(danger)는
        ``validate_generate`` 의 모달 백스톱에 남긴다.

        검토 요구가 **전제조건보다 뒤**인 이유(F5 판정 F): 선택 0건에서는 미리보기에
        진입하지 않는 것이 불변식(§18.11-6·§13-26 "첫 레코드를 실행 미리보기로 대신하지
        않는다")이라, 선택이 0인데 "검토하세요"라고 말하면 이행 불가능한 지시가 된다.
        """
        if self.target_mode == "continue" and not self.template_override:
            return GateState(False, "warn", "이어채울 기존 문서(.hwpx)를 선택하세요.")
        if drift.has_drift:
            if drift.read_error:
                return GateState(
                    False, "danger", "템플릿 구조를 읽을 수 없어 생성이 차단됩니다.",
                    reason="template_unreadable",
                )
            names = list(drift.template_only) + list(drift.mapping_only) + list(drift.conflicting)
            return GateState(
                False, "danger",
                "템플릿 구조가 확정 매핑과 달라졌습니다. 매핑을 다시 확정해야 생성할 "
                "수 있습니다: " + ", ".join(names),
                reason="drift",
            )
        if name_gate is not None:
            return name_gate
        # 데이터 결속은 **작업 정의 수준의 결핍**이다(U4 §2.4 · #932 U4-C): 저장 게이트가
        # 요구하는 것을 실행 게이트가 통과시키면 「필수」는 한 자리에서만 참인 말이 되고,
        # 그 작업은 매 세션 데이터를 다시 물으면서도 무엇이 잘못됐는지 말하지 않는다.
        #
        # **자리는 danger 뒤·세션 전제조건 앞**이다. 구조가 깨진 것(드리프트·미해소 토큰)은
        # 차단 등급이 더 높아 먼저 말해야 하고, 반대로 저장 폴더·행 선택 같은 세션 준비보다는
        # 앞선다 — 세션을 다 갖춰도 이 결핍은 남고 고칠 자리도 다르다(피커가 아니라 편집기).
        if not has_data_binding(self.job):
            return GateState(
                False, "warn",
                "이 작업에 연결된 데이터가 없습니다. 데이터를 연결해야 문서를 만들 수 "
                "있습니다.",
                reason=GATE_REASON_DATA_UNBOUND,
            )
        if not out_dir:
            return GateState(False, "warn", "저장 폴더를 지정하세요.")
        if not indices:
            return GateState(False, "warn", "생성할 문서를 최소 1건 선택하세요.")
        if self.template_override and len(indices) != 1:
            return GateState(
                False, "warn",
                "기존 문서 이어채우기는 1건만 지원합니다. 생성 대상을 1건만 선택하세요.",
            )
        if review_unmet is not None and review_unmet.required:
            return GateState(
                False, "warn", review_gate_text(review_unmet), reason="review_required",
            )
        return GateState(True, "", "")

    def _compose_preflight(
        self, src, out, drift: TemplateStructureDrift, name_unresolved: bool = False,
        long_paths: int = 0,
    ) -> PreflightResult:
        parts: "list[str]" = []
        if src.missing_columns:
            parts.append(
                "[치명] 데이터에 없는 항목입니다(빈 값 생성됨): " + ", ".join(src.missing_columns)
            )
        if drift.has_drift:
            # 게이트가 상세 사유를 렌더한다 — 여기선 '통과' 녹색이 남지 않게만 알린다.
            parts.append("[치명] 템플릿 구조가 확정 매핑과 다릅니다. 아래 차단 사유를 확인하세요.")
        if name_unresolved:
            # 상세(토큰 목록·복구 동선)는 게이트가 렌더한다(F34) — 여기선 '통과' 녹색이
            # 미해소 파일명과 공존하는 모순 신호만 차단한다(RC-23 동형).
            parts.append("[치명] 파일명 패턴에 해소되지 않는 토큰이 있습니다. 아래 차단 사유를 확인하세요.")
        if out.empty_valued:
            # 상태 어휘 경계(UD-20): 사전검증 경고도 배지·게이트와 같은 '미입력'으로 통일
            # (같은 상태 2이름 해소) — '미입력'=출력값 빔(ack 대상).
            parts.append("[경고] 빈 값 필드: " + ", ".join(out.empty_valued))
        if long_paths:
            # **차단하지 않는다**(2R P2 · 재작성 F5 판정 K): 확장 경로·longPathsEnabled 에서는
            # 실제로 성공하므로 게이트를 닫으면 잘 되는 환경의 사용자가 UI 로는 아예 못
            # 만든다. 그렇다고 침묵하면 생성 중 OSError 로만 드러난다 — 그래서 사전 경고다.
            # 문안도 단정하지 않는다("실패한다"가 아니라 "실패할 수 있다").
            parts.append(
                f"[경고] 저장 경로가 너무 길어 저장에 실패할 수 있는 문서 {long_paths}건. "
                "저장 폴더를 더 짧은 곳으로 바꾸거나 파일 이름 규칙을 줄이면 확실합니다."
            )
        if src.missing_columns or drift.has_drift or name_unresolved:
            level = "danger"
        elif out.empty_valued or long_paths:
            level = "warn"
        else:
            level = "ok"
        return PreflightResult(
            list(src.missing_columns), list(out.empty_valued), level,
            "\n".join(parts) if parts
            else "사전검증 통과(치명 누락 없음). 아래 빈 값 목록을 확인하세요.",
        )

    # (acknowledge·unacknowledge·reset_acks·acked_count·unmet_blanks 는 필드축 ack
    #  폐기와 함께 사망 — U2 §2.13. 빈 값 판정은 :meth:`blank_fields` 하나로 남고,
    #  표식 삽입 동의는 승인(빈 값 집합이 지문 성분)이 겸한다.)

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
                "템플릿 구조가 확정 매핑과 다릅니다. 매핑을 다시 확정해야 생성할 수 "
                "있습니다.\n" + drift.describe(),
                "danger",
            )]
        name_gate = self._name_token_gate()
        if name_gate is not None:
            # 파일명 토큰 계약(F34) — 게이트 버튼이 이미 비활성이어도 워커/API 우회를
            # 방어적으로 재차단한다(CLI RC-20 게이트의 GUI 짝, 문구 동일 출처).
            return [GateError(name_gate.text, "danger")]
        if not out_dir:
            return [GateError("저장 폴더를 지정하세요.", "warn")]
        if not indices:
            return [GateError("생성할 문서를 최소 1건 선택하세요.", "warn")]
        if self.template_override and len(indices) != 1:
            # 누적 v1 = 단건. 배치 누적(이전출력↔레코드 파일키 매칭)은 별개 설계 — 파킹.
            return [GateError(
                "기존 문서 이어채우기는 1건만 지원합니다. 생성 대상을 1건만 선택하세요.",
                "warn")]
        return []

    def mapped_records(
        self, indices: "list[int]", mark_missing: str = "",
        *, now: "datetime | None" = None,
    ) -> "list[dict]":
        """선택 레코드에 매핑 적용 → {템플릿필드: 값}. mark_missing 시 빈 키에 표식 주입.

        ``now`` 는 ``today``(오늘 날짜) 유형의 기준 시각 — 파일명 날짜 토큰에 넘긴 값과
        같아야 본문과 이름이 갈라지지 않는다(RC-02). 미지정이면 적용 시점으로 폴백한다.
        """
        return self.request(indices).mapped_records(mark_missing=mark_missing, now=now)

    def blank_record_positions(
        self, indices: "list[int]", mapped: "list[dict] | None" = None
    ) -> "list[int]":
        """빈 값이 있는 건의 **표시순 자리** 목록 — 「빈 값 있는 건만 보기」의 판정 원천.

        :meth:`blank_fields`(필드축)와 같은 층이 소유하는 **레코드축** 판정이다(P2-24 —
        두 축이 다른 층에 살면 「빈 값」의 술어가 갈린다). 판정은 표식 **없는** 매핑
        출력에서 한다(표식을 채우면 언제나 0건). 의도적 빈칸(blank 선언)은 매핑이 키
        자체를 제외하므로 자동으로 세지 않는다. ``mapped`` 는 호출측이 이미 계산한 같은
        출력의 관통(이중 적용 방지)이다.
        """
        recs = self.mapped_records(indices) if mapped is None else mapped
        return [
            i for i, rec in enumerate(recs)
            if any(not str(v).strip() for v in rec.values())
        ]

    def output_conflicts(
        self, indices: "list[int]", out_dir: str, *, mark_missing: str = "",
        now: "datetime | None" = None,
        existing_outputs: "Callable[[str, list[str]], list[str]]",
    ) -> "list[str]":
        """생성이 덮어쓸 **기존** 파일 경로 목록 — 실행 전 덮어쓰기 확인의 원천(RC-02).

        생성과 동일한 매핑·표식·파일명 규칙으로 대상 경로를 계산해 디스크 존재만
        조회한다(무변형). 표현 계층은 이 목록이 비지 않으면 "기존 N개 파일을 덮어씁니다"
        사용자 확정을 받은 뒤에만 ``overwrite=True`` 로 진행한다(확인-또는-경보).
        ``now`` 는 날짜 토큰 기준 시각 — 이후 생성 계획과 **같은 값**을 넘겨야 하위-일
        토큰에서 확인 대상과 실제 생성 대상이 갈라지지 않는다(RC-02).
        """
        names = plan_output_names(
            self.job.filename_pattern,
            self.mapped_records(indices, mark_missing, now=now),
            now=now,
        )
        return existing_outputs(out_dir, names)

    def output_name_audit(
        self, indices: "list[int]", out_dir: str = "", *,
        mark_missing: str = "", now: "datetime | None" = None,
    ) -> OutputNameAudit:
        """이 실행이 발급할 이름의 집합 감사(C-01, 지도 §10.12 판정 K).

        ``output_conflicts`` 와 같은 입력·같은 규칙이되 디스크를 보지 않는다 — 이쪽은
        **배치 안에서 자기들끼리** 생기는 성질(수렴·경로 길이)만 센다.
        """
        return audit_output_names(
            self.job.filename_pattern,
            self.mapped_records(indices, mark_missing, now=now),
            out_dir, now=now,
        )

    # ------------------------------------------------------------ 생성 계획(RC-07)
    def build_generation_plan(
        self,
        indices: "list[int]",
        out_dir: str,
        *,
        marker: str = "",
        ledger: bool = False,
        overwrite: bool = False,
        now: "datetime | None" = None,
    ) -> GenerationPlan:
        """게이트 통과 직후 호출 — 생성·완료 처리·원장이 소비할 전부를 원자 캡처한다.

        이후 표현 계층/VM 이 어떻게 바뀌어도 이 계획은 불변이다(RC-07). ``marker`` 는
        생성에 실제 쓸 표식과 동일해야 원장 dry-run 행이 주입값과 일치한다. ``now`` 는
        덮어쓰기 확인(:meth:`output_conflicts`)에 넘긴 시각과 **같은 값**이어야 확인
        대상과 실제 생성 대상이 하위-일 날짜 토큰에서 갈라지지 않는다(RC-02). 그 값은
        파일명뿐 아니라 **본문**의 ``today``(오늘 날짜) 유형에도 그대로 간다 — 한 실행에서
        이름과 본문이 다른 시각을 말하지 않는다(U4-E1 #939).
        """
        idx = list(indices)
        labels_fn = getattr(self.datasource, "field_labels", None)
        labels = labels_fn() if callable(labels_fn) else {}
        return GenerationPlan(
            template=self.effective_template(),
            records=tuple(self.mapped_records(idx, marker, now=now)),
            out_dir=out_dir,
            pattern=self.job.filename_pattern,
            marker=marker,
            indices=tuple(idx),
            source_pointer=self.source_pointer(),
            overwrite=overwrite,
            now=now,
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

        소스가 자기 표기를 선언하면(``source_pointer()`` — :mod:`hwpxfiller.domain.data_source`
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

    # (사후 export 보조 표면 export_run_ledger 는 P2-18(#566)에서 제거 — production
    #  소비자 0 이었고, 같은 일은 :meth:`build_generation_plan` + External
    #  :func:`~hwpxfiller.external.ledger_export.export_plan_ledger` 조합이 한다.)
