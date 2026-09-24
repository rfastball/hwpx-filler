"""실행(Run) 화면 ViewModel — Qt 비의존 실행 결정(사전검증·게이트·계획).

웹 작업 컨트롤러(:class:`~hwpxfiller.webapp.screen_job.JobController`)는 이 뷰모델에 실행 결정을
위임한다. 컨트롤러가 소유한 현재 데이터는 :class:`RunDataInput` 으로 매 호출 명시하고,
이 뷰모델은 ``HwpxEngine``·``RunRequest`` 로 판정만 한다(링1: PySide6 금지).
**매핑 재확정 없음** — 매핑은 작업 정의 때 확정됐고 여기선 사전검증만 한다.

이 뷰모델 표면(dataclass 결과 + 메서드)이 목업 실행 화면이 겨누는 seam 계약이다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Protocol, cast

from ..domain.data_source import DataSource
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
from .review_state import ReviewRequirement, review_notice_text


@dataclass
class PreflightResult:
    """사전검증 표시용 — 데이터에 없는 항목(치명)·빈 출력값(경고)·비차단 고지(알림).

    ``notices`` 는 등급을 올리지 않는 고지 줄(#957 검토 고지)이다. ``text`` 에도 이미
    실려 있지만 따로 드는 이유는 「치명·경고가 하나도 없는 실행」의 표면 때문이다:
    그 자리에서 표면은 ``text`` 대신 통과 문구를 쓰므로(링2 ``_PREFLIGHT_OK_TEXT``),
    고지를 별도 축으로 들지 않으면 조용히 사라진다.
    """

    missing_columns: "list[str]" = field(default_factory=list)
    empty_valued: "list[str]" = field(default_factory=list)
    level: str = ""          # ""/"ok"/"warn"/"danger" (style.mark 레벨)
    text: str = ""
    notices: "tuple[str, ...]" = ()

    def issues(self) -> "list[str]":
        """로그용 이슈 목록(데이터 항목 누락 + 빈값, 문서순 중복제거)."""
        return list(dict.fromkeys(list(self.missing_columns) + list(self.empty_valued)))


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
    state: str            # "filled" | "missing" | "drift"(구조 불일치)


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
    #: 값: drift | template_unreadable | name_tokens
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
    #: 이 실행이 발급할 이름과 그 집합 성질(C-01, 재작성 F5). 게이트와 표 「문서」 열이
    #: **같은 산출**을 재사용한다 — 표면이 따로 계획하면 화면이 실행과 다른 이름을 말할 수
    #: 있다(RC-23 이 표시면 간 모순에 대해 세운 규율의 파일명 판).
    audit: OutputNameAudit = field(default_factory=OutputNameAudit)


@dataclass(frozen=True)
class RunDataInput:
    """실행 판정에 명시적으로 건네는 현재 데이터 스냅샷."""

    datasource: object | None
    records: "tuple[dict, ...]"


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
    ) -> DataSource: ...


class PoolSourceFactoryPort(Protocol):
    """풀 항목(참조) → DataSource 포트 — 복원·키 주입·pipeline 재귀는 Host 가 주입하는
    factory 의 몫이다. 나라장터 항목은 이 포트에 **오지 않는다**(아래 nara 분기가 선점)."""

    def __call__(self, item, *, secret_store=None, fetcher=None) -> DataSource: ...


def resolve_file_source(
    path: str, *, sheet: "str | None" = None, header_row: int = 0,
    source_factory: FileSourceFactoryPort,
) -> "tuple[DataSource, list[dict]]":
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
) -> "tuple[DataSource, list[dict]]":
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
    빈 고정값이 아닌 매핑 커버 필드다(명시적 빈 고정값은 값이 빈 문자열이라 토큰을 해소하지
    못한다 — 이름이 조용히 뭉개지는 대신 미해소로 시끄럽게 선다).
    매핑 적용 키는 전 레코드 균일이라 CLI 의 '일부 레코드 누락' 경고 분기는 GUI 에 원리적으로
    없다.

    **데이터 없이도 판정 가능한 작업 정의 수준의 계약 검사**라 ``Job`` 이 아직 없는 자리
    (저장 게이트 :func:`~hwpxfiller.viewmodel.job_editor_state.validate_save`, U4 계열4-4)에서도
    같은 몸통을 부를 수 있게 프로파일 수준으로 둔다 — 저장 게이트가 이 술어를 다시 지으면
    같은 상태를 두 곳이 판정한다.
    """
    resolved = set(mapping.cover_fields()) - set(mapping.declared_empty_fields())
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
    """작업 1건의 실행 판정. 현재 데이터는 호출자가 명시적으로 건넨다."""

    def __init__(self, job: Job, *, engine: HwpxEngine):
        # 진입 가드(3부 결정 13 · 2층): 실행뷰는 hwpx 생성 경로다 — HwpxEngine.required_fields·
        # template_path_drift 가 이 job 의 템플릿을 hwpx 로 파싱한다. txt 기안 작업은 「기안」
        # 화면이 자기 경로로 소비하므로 여기 오면 조회 경계가 샌 것 → loud 거부(조용한 오파싱 금지).
        require_hwpx(job)
        self.job = job
        # zip IO 가 결속된 엔진은 Host/ring 2 가 주입한다(P3-03 — 링1 은 concrete package
        # read/write adapter를 모른다. P2-16 source factory 주입과 같은 seam).
        self._engine = engine
        # managed Product Work 생성이 고정한 exact applied bytes staged 경로(#681 G11) —
        # mutable job.template_path 대신 이걸 소비한다.
        self._managed_template: "str | None" = None

    # ------------------------------------------------------------ 대상 문서
    def effective_template(self) -> str:
        """생성이 겨눌 문서 — managed staged bytes가 있으면 우선한다."""
        return self._managed_template or self.job.template_path

    # ------------------------------------------------------------ 사전검증
    def request(self, data: RunDataInput, indices: "list[int]") -> RunRequest:
        return RunRequest(self.job, data.records, list(indices))

    def preflight(self, data: RunDataInput, indices: "list[int]") -> PreflightResult:
        """데이터에 없는 항목(치명)·구조 드리프트(치명)·빈값(경고) 판정(재확정 아님).

        표현 계층은 level/text 를 **그대로** 렌더한다(RC-23) — 드리프트 차단 중에 상단만
        '통과' 녹색으로 남는 모순 신호를 여기서 차단한다.
        """
        return self.refresh(data, indices).preflight

    def blank_fields(self, data: RunDataInput, indices: "list[int]") -> "list[str]":
        """선택분에서 값이 빈 필드 — 표식(`MISSING_MARKER`)·빈 값 표지·승인 지문
        성분(`blank_set`, U2 §2.13)의 단일 원천. 데이터 없으면 빈 목록."""
        if data.datasource is None:
            return []
        return list(self.request(data, indices).output_report().empty_valued)

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

    def field_states(self, data: RunDataInput, indices: "list[int]") -> "list[FieldState]":
        """필드별 3상태(채움/의도적 빈칸/미입력) — 상시 인라인 배지의 원천.

        채움/미입력은 값 매핑 출력에서, 의도적 빈칸은 매핑의 ``blank`` 선언에서 온다.
        템플릿↔커버 대칭차는 ``drift`` 로 별도 표시해 의도적 공란으로 오라벨하지 않는다.
        데이터 미겨눔이면 빈 목록(패널 비움).
        """
        return list(self.refresh(data, indices).field_states)

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
        self, data: RunDataInput, indices: "list[int]", out_dir: str = "", *,
        review_notice: "ReviewRequirement | None" = None,
        mapped: "list[dict] | None" = None,
        now: "datetime | None" = None,
        configuration_gate: "GateState | None" = None,
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

        ``review_notice`` 는 현재 **검토 요구**(:func:`~hwpxfiller.viewmodel.review_state.review_requirement`)
        다. 종전의 ``review_unmet``(승인 대조를 통과 못 한 요구)과 달리 게이트 서열에
        끼지 않는다 — #957 정책 선회로 검토는 차단이 아니라 사전검증의 비차단 고지이고,
        승인이라는 해소 사건 자체가 없어져 「미승인분」이라는 축도 함께 사라졌다.

        ``configuration_gate`` 는 실제 생성 admission과 같은 출처 판정이다. 템플릿 적용
        뒤 실행 구성이 아직 확정되지 않았으면 사전검증과 버튼이 함께 그 사유를 표시한다.
        """
        name_gate = self._name_token_gate()
        if data.datasource is None:
            return RunStatus(
                PreflightResult(
                    level=configuration_gate.level, text=configuration_gate.text,
                ) if configuration_gate else PreflightResult(), (),
                name_gate or configuration_gate
                or GateState(False, "warn", "먼저 데이터를 선택하세요."),
            )
        idx = list(indices)
        req = self.request(data, idx)
        src = req.source_report()
        out = req.output_report()
        drift, _current_fields = self._structure_snapshot()
        states = self._compose_field_states(set(out.empty_valued), drift)
        # 이름 계획은 **대상이 있으면** 낸다(폴더가 없어도 이름은 보여 준다).
        # 경로 길이만 폴더에 의존하고, 폴더가 없으면 잴 경로가 없어 조용하다.
        # ``mapped`` 는 호출측이 이미 만든 매핑 결과 — 넘겨받아 같은 계산을 두 번 하지 않는다.
        audit = (
            audit_output_names(
                self.job.filename_pattern,
                self.mapped_records(data, idx, now=now) if mapped is None else mapped,
                out_dir,
                now=now,
            ) if idx else OutputNameAudit()
        )
        return RunStatus(
            preflight=self._compose_preflight(
                src, out, drift, name_gate is not None, len(audit.too_long),
                review_notice, configuration_gate,
            ),
            field_states=tuple(states),
            gate=self._compose_gate(
                states, drift, idx, out_dir, name_gate, audit, configuration_gate,
            ),
            audit=audit,
        )

    def gate_state(
        self, data: RunDataInput, indices: "list[int]", out_dir: str = ""
    ) -> GateState:
        """생성 게이트 표시 결정(활성/level/text)의 단일 통합(RC-23)."""
        return self.refresh(data, indices, out_dir).gate

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
        self, empty: "set[str]", drift: TemplateStructureDrift
    ) -> "list[FieldState]":
        drift_fields = drift.symmetric_difference | set(drift.conflicting)
        # 매핑 계약순 뒤에 템플릿 신규 유입순을 붙인다. 사라진 값 매핑도 drift 하나로
        # 표시해 filled/missing과 중복·모순되지 않게 한다.
        order = list(self.job.mapping.cover_fields()) + list(drift.template_only)
        states: "list[FieldState]" = []
        for name in dict.fromkeys(order):
            if name in drift_fields:
                states.append(FieldState(name, "drift"))
            else:
                states.append(FieldState(name, "missing" if name in empty else "filled"))
        return states

    def _compose_gate(
        self, states: "list[FieldState]", drift: TemplateStructureDrift,
        indices: "list[int]", out_dir: str, name_gate: "GateState | None" = None,
        audit: "OutputNameAudit | None" = None,
        configuration_gate: "GateState | None" = None,
    ) -> GateState:
        """게이트 표시 결정 — 드리프트(danger·차단) > 파일명 토큰(danger) >
        실행 구성(warn) > **데이터 결속(warn)** > 세션 전제조건(warn) > 열림.

        결속 단이 세션 전제조건보다 앞선 이유는 **고칠 자리가 다르기** 때문이다(U4 §2.4):
        저장 폴더·행 선택은 이 화면에서 지우지만 결속은 편집기를 지난다. 세션을 다 갖춰도
        남는 결핍을 뒤에 두면 사용자가 준비를 마친 뒤에야 진짜 막힌 이유를 듣는다.

        구 「미확인 미입력」 단은 필드축 ack 폐기(U2 §2.13)와 함께 죽었고, 그 자리를
        이어받았던 **검토 요구 단도 #957 에서 사망**했다: 신뢰 정책이 「이상이 있으면
        알려주되 생성을 막지 않는다」로 선회해 검토는 차단이 아니라 :meth:`_compose_preflight`
        의 비차단 고지가 됐다. 빈 값도 게이트가 아니다 — 표식이 문서에 박히므로 조용한
        통과가 아니고, 확인은 결과 문서에서 한다.

        UD-06: 저장 폴더·레코드 선택 같은 warn 급 전제조건을 이 단일
        산출로 흡수해 '버튼 비활성 + 인라인 사유' 문법으로 통일한다(클릭 후 차단 모달
        재유입 소거 — 모달은 danger 예외에만 남긴다). 템플릿 부재(danger)는
        ``validate_generate`` 의 모달 백스톱에 남긴다.
        """
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
        if configuration_gate is not None:
            return configuration_gate
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
        return GateState(True, "", "")

    def _compose_preflight(
        self, src, out, drift: TemplateStructureDrift, name_unresolved: bool = False,
        long_paths: int = 0, review_notice: "ReviewRequirement | None" = None,
        configuration_gate: "GateState | None" = None,
    ) -> PreflightResult:
        parts: "list[str]" = []
        if configuration_gate is not None:
            parts.append(configuration_gate.text)
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
        # 검토 고지(#957) — **차단하지 않는다**. 종전에는 같은 사실이 게이트를 닫고
        # 확인 면의 승인을 요구했지만, 신뢰 정책 선회로 확인의 자리는 결과 문서다.
        # ``long_paths`` 와 같은 비차단 선례를 따른다: 침묵도 차단도 아닌 사전 고지.
        # 문안은 링1 단일 출처(:func:`~hwpxfiller.viewmodel.review_state.review_notice_text`)이고
        # 빈 값은 여기 없다 — 그 자리는 위의 "[경고] 빈 값 필드" 가 이미 진다.
        notice = review_notice_text(review_notice) if review_notice is not None else ""
        notices: "tuple[str, ...]" = ()
        if notice:
            notices = (f"[알림] {notice}",)
            parts.extend(notices)
        if src.missing_columns or drift.has_drift or name_unresolved:
            level = "danger"
        elif out.empty_valued or long_paths or configuration_gate is not None:
            level = "warn"
        else:
            # 고지만 있는 실행은 **등급을 올리지 않는다** — 「알려주되 막지 않는다」는
            # 색까지 포함한 말이라, 고지마다 경고색을 켜면 경고가 싸구려가 된다.
            level = "ok"
        return PreflightResult(
            list(src.missing_columns), list(out.empty_valued), level,
            "\n".join(parts) if parts
            else "사전검증 통과(치명 누락 없음). 아래 빈 값 목록을 확인하세요.",
            notices,
        )

    # (acknowledge·unacknowledge·reset_acks·acked_count·unmet_blanks 는 필드축 ack
    #  폐기와 함께 사망 — U2 §2.13. 빈 값 판정은 :meth:`blank_fields` 하나로 남고,
    #  표식 삽입 동의는 승인(빈 값 집합이 지문 성분)이 겸한다.)

    # ------------------------------------------------------------ 생성 게이트
    def validate_generate(
        self, data: RunDataInput, indices: "list[int]", out_dir: str
    ) -> "list[GateError]":
        """생성 전 가드 — 첫 차단 사유만 반환(없으면 빈 목록)."""
        indices = list(indices)
        if data.datasource is None:
            return [GateError("먼저 데이터를 선택하세요.", "warn")]
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
        return []

    def mapped_records(
        self, data: RunDataInput, indices: "list[int]", mark_missing: str = "",
        *, now: "datetime | None" = None,
    ) -> "list[dict]":
        """선택 레코드에 매핑 적용 → {템플릿필드: 값}. mark_missing 시 빈 키에 표식 주입.

        ``now`` 는 ``today``(오늘 날짜) 유형의 기준 시각 — 파일명 날짜 토큰에 넘긴 값과
        같아야 본문과 이름이 갈라지지 않는다(RC-02). 미지정이면 적용 시점으로 폴백한다.
        """
        return self.request(data, indices).mapped_records(mark_missing=mark_missing, now=now)

    def blank_record_positions(
        self, data: RunDataInput, indices: "list[int]", mapped: "list[dict] | None" = None
    ) -> "list[int]":
        """빈 값이 있는 건의 **표시순 자리** 목록 — 「빈 값 있는 건만 보기」의 판정 원천.

        :meth:`blank_fields`(필드축)와 같은 층이 소유하는 **레코드축** 판정이다(P2-24 —
        두 축이 다른 층에 살면 「빈 값」의 술어가 갈린다). 판정은 표식 **없는** 매핑
        출력에서 한다(표식을 채우면 언제나 0건). 의도적 빈칸(blank 선언)은 매핑이 키
        자체를 제외하므로 자동으로 세지 않는다. ``mapped`` 는 호출측이 이미 계산한 같은
        출력의 관통(이중 적용 방지)이다.
        """
        recs = self.mapped_records(data, indices) if mapped is None else mapped
        return [
            i for i, rec in enumerate(recs)
            if any(not str(v).strip() for v in rec.values())
        ]

    def output_conflicts(
        self, data: RunDataInput, indices: "list[int]", out_dir: str, *, mark_missing: str = "",
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
            self.mapped_records(data, indices, mark_missing, now=now),
            now=now,
        )
        return existing_outputs(out_dir, names)

    def output_name_audit(
        self, data: RunDataInput, indices: "list[int]", out_dir: str = "", *,
        mark_missing: str = "", now: "datetime | None" = None,
    ) -> OutputNameAudit:
        """이 실행이 발급할 이름의 집합 감사(C-01, 지도 §10.12 판정 K).

        ``output_conflicts`` 와 같은 입력·같은 규칙이되 디스크를 보지 않는다 — 이쪽은
        **배치 안에서 자기들끼리** 생기는 성질(수렴·경로 길이)만 센다.
        """
        return audit_output_names(
            self.job.filename_pattern,
            self.mapped_records(data, indices, mark_missing, now=now),
            out_dir, now=now,
        )

    # ------------------------------------------------------------ 생성 계획(RC-07)
    def build_generation_plan(
        self,
        data: RunDataInput,
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
        labels_fn = getattr(data.datasource, "field_labels", None)
        # Optional adapters may not expose labels; callable-only preserves that fallback while
        # narrowing the dynamic host seam to the declared label result.
        labels = (
            cast("Callable[[], dict[str, str]]", labels_fn)()
            if callable(labels_fn)
            else {}
        )
        return GenerationPlan(
            template=self.effective_template(),
            records=tuple(self.mapped_records(data, idx, marker, now=now)),
            out_dir=out_dir,
            pattern=self.job.filename_pattern,
            marker=marker,
            indices=tuple(idx),
            source_pointer=self.source_pointer(data),
            overwrite=overwrite,
            now=now,
            ledger=ledger,
            job_name=self.job.name,
            mapping=self.job.mapping,
            template_fields=tuple(self._template_fields()),
            source_records=tuple(
                dict(record) for record in self.request(data, idx).selected_records()
            ),
            source_keys=tuple(self.job.source_keys()),
            labels=dict(labels),
        )

    # ------------------------------------------------------------ 생성 원장(L2)
    def source_pointer(self, data: RunDataInput) -> str:
        """원장에 남길 소스 표기 — **포인터-온리**(경로·종류). 쿼리·키는 박제하지 않는다.

        소스가 자기 표기를 선언하면(``source_pointer()`` — :mod:`hwpxfiller.domain.data_source`
        의 선택 프로토콜) 그것이 우선한다. 문자열 타입명 비교로 소스 종류를 식별하지
        않는다 — 클래스 개명이 원장 침묵 오기록이 되지 않게(RC-25). 미선언 소스는
        ``path`` 속성(``file:<경로>``) → 타입명 순으로 강등 표기.
        """
        src = data.datasource
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
