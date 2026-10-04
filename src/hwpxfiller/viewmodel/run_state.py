"""실행(Run) 화면 ViewModel — Qt 비의존 진단(사전검증·필드 상태·이름 감사).

웹 작업 컨트롤러(:class:`~hwpxfiller.webapp.screen_job.JobController`)는 이 뷰모델에 실행 진단을
위임한다. 컨트롤러가 소유한 현재 데이터는 :class:`RunDataInput` 으로 매 호출 명시하고,
이 뷰모델은 ``HwpxEngine``·``RunRequest`` 로 판정만 한다(링1: PySide6 금지).
**매핑 재확정 없음** — 매핑은 작업 정의 때 확정됐고 여기선 사전검증만 한다.

이 뷰모델 표면(dataclass 결과 + 메서드)이 목업 실행 화면이 겨누는 seam 계약이다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from ..domain.data_source import DataSource
from ..domain.engine import HwpxEngine

if TYPE_CHECKING:
    from datetime import datetime
from ..domain.fill_ledger import (
    TemplateStructureDrift,
    template_path_drift,
    template_structure_drift,
)
from ..domain.job import Job, RunRequest, require_hwpx
from ..domain.mapping import MappingProfile
from ..naming import (
    OutputNameAudit,
    audit_output_names,
    pattern_field_tokens,
)
from .review_state import ReviewRequirement, review_notice_text

#: 이름을 만들 수 없는 패턴·값(이름 kernel 의 OUTPUT_NAME_PATTERN_INVALID·
#: OUTPUT_PATH_ESCAPE_DETECTED)을 말하는 **한 문장** — 배달 blocker 표(webapp)도 이 상수를 쓴다.
OUTPUT_NAME_INVALID_TEXT = "파일 이름 규칙이 올바르지 않습니다."


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


@dataclass(frozen=True)
class GateState:
    """TXT·작업 미선택 화면의 진입 게이트 표시값."""

    enabled: bool
    level: str  # ""/"warn"/"danger" (style.mark 레벨)
    text: str
    #: 차단 사유의 기계 판독 이름(TXT 진입·작업 미선택 구획 지목).
    reason: str = ""


@dataclass(frozen=True)
class RunStatus:
    """상태 리프레시 1회의 진단 스냅샷 — 사전검증·필드 상태·이름 감사.

    레코드 매핑과 템플릿 구조를 한 번씩 계산해 진단 표시면이 같은 사실을 공유한다.
    """

    preflight: PreflightResult
    field_states: "tuple[FieldState, ...]"
    #: 이름과 그 집합 성질(C-01). 표 「문서」 열과 같은 시각·매핑을 재사용한다.
    audit: OutputNameAudit = field(default_factory=OutputNameAudit)


@dataclass(frozen=True)
class RunDataInput:
    """실행 판정에 명시적으로 건네는 현재 데이터 스냅샷."""

    datasource: object | None
    records: "tuple[dict, ...]"


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

    저장 게이트와 전역 건강 보기(§19.7 번역)가 이 한 몸통을 공유한다. 저장 게이트가
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
        template = self.job.template_path
        if template_missing(template):
            return []
        return list(self._engine.required_fields(template))

    def structure_drift(self) -> TemplateStructureDrift:
        """현재 템플릿과 확정 매핑 커버의 대칭차(스냅샷 없는 구조 계약)."""
        return template_path_drift(
            self.job.template_path, self.job.mapping, engine=self._engine
        )

    def field_states(self, data: RunDataInput, indices: "list[int]") -> "list[FieldState]":
        """필드별 3상태(채움/의도적 빈칸/미입력) — 상시 인라인 배지의 원천.

        채움/미입력은 값 매핑 출력에서, 의도적 빈칸은 매핑의 ``blank`` 선언에서 온다.
        템플릿↔커버 대칭차는 ``drift`` 로 별도 표시해 의도적 공란으로 오라벨하지 않는다.
        데이터 미겨눔이면 빈 목록(패널 비움).
        """
        return list(self.refresh(data, indices).field_states)

    # ------------------------------------------------ 진단 스냅샷(RC-23)
    def unresolved_name_tokens(self) -> "list[str]":
        """이 작업의 미해소 파일명 토큰 — 판정 몸통은 :func:`unresolved_name_tokens_for`."""
        return unresolved_name_tokens_for(self.job)

    def refresh(
        self, data: RunDataInput, indices: "list[int]", out_dir: str = "", *,
        review_notice: "ReviewRequirement | None" = None,
        mapped: "list[dict] | None" = None,
        now: "datetime | None" = None,
    ) -> RunStatus:
        """사전검증·필드 상태·이름 감사를 같은 매핑·템플릿 구조에서 만든다.

        데이터 미겨눔이면 진단은 공백이다. 생성 가능 여부는 작업대 관찰의 동사가 판정한다.

        ``review_notice`` 는 현재 **검토 요구**(:func:`~hwpxfiller.viewmodel.review_state.review_requirement`)
        다. 종전의 ``review_unmet``(승인 대조를 통과 못 한 요구)과 달리 실행을 막지
        않는다 — #957 정책 선회로 검토는 사전검증의 비차단 고지이고,
        승인이라는 해소 사건 자체가 없어져 「미승인분」이라는 축도 함께 사라졌다.
        """
        if data.datasource is None:
            return RunStatus(PreflightResult(), ())
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
                src, out, drift, bool(self.unresolved_name_tokens()), len(audit.too_long),
                review_notice,
            ),
            field_states=tuple(states),
            audit=audit,
        )

    def _structure_snapshot(self) -> "tuple[TemplateStructureDrift, set[str]]":
        """템플릿 구조 1회 재읽기 → (드리프트, 현재 누름틀 집합).

        읽기 실패는 :func:`template_path_drift` 와 동일하게 ``read_error``
        (fail-closed)로 남긴다 — 드리프트 감지를 위해 refresh 마다 재읽기한다.
        """
        template = self.job.template_path
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

    def _compose_preflight(
        self, src, out, drift: TemplateStructureDrift, name_unresolved: bool = False,
        long_paths: int = 0, review_notice: "ReviewRequirement | None" = None,
    ) -> PreflightResult:
        parts: "list[str]" = []
        if src.missing_columns:
            parts.append(
                "[치명] 데이터에 없는 항목입니다(빈 값 생성됨): " + ", ".join(src.missing_columns)
            )
        if drift.has_drift:
            parts.append("[치명] 템플릿 구조가 확정 매핑과 다릅니다.")
        if name_unresolved:
            parts.append("[치명] 파일명 패턴에 해소되지 않는 토큰이 있습니다.")
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
        elif out.empty_valued or long_paths:
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

    # (legacy 생성의 모달 백스톱 ``validate_generate``·덮어쓰기 대조 ``output_conflicts``·
    #  이름 감사 ``output_name_audit``·불변 계획 ``build_generation_plan``(+``GenerationPlan``·
    #  원장 ``source_pointer``)은 legacy 생성기와 함께 #1081 PR3 에서 퇴역했다. 생성 게이트
    #  판정은 managed 작업대 관찰이, 덮어쓰기·이름 판정은 배달 계획이 진다.)

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
