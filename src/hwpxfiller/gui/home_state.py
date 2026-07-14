"""홈 화면 ViewModel — Qt 비의존 프레젠테이션 상태(작업 목록·메타 성형·선택).

위젯(:class:`~hwpxfiller.gui.home.JobListHome`)은 이 뷰모델을 들고 ``rows()``·``is_empty()``·
``count_label()`` 로 **렌더만** 한다. 레지스트리 접근, 카드 메타 문자열, 최근실행 포맷, 선택
상태가 여기 산다 — 변경 통지는 Qt 시그널이 아니라 순수 옵저버 콜백(``subscribe``)이라
QApplication 없이 헤드리스로 테스트된다(링1 규율: PySide6 임포트 금지).

이 뷰모델의 공개 표면(``JobRow`` 필드 + 메서드)이 목업(``docs/UI_PROTOTYPE_APPB.html`` 홈)이
겨누는 seam 계약이다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from ..core.job import Job, JobRegistry
from ..core.template_status import CompileState, compile_status
from .compile_badge import ERROR_BADGE_LEVEL, badge_level

# 카드 컴파일 상태 배지 어휘(C2 파생) — 기존 '템플릿 없음' pill 을 대체가 아니라 확장한다.
# 이모지 접두로 한눈에 "실행 준비 vs 손봐야 함" 을 가른다.
BADGE_MISSING = "❌ 템플릿 없음"        # 경로 있으나 파일 부재(compile_status 호출 안 함)
BADGE_RAW = "✏ 원문·누름틀 변환 필요"   # CompileState.RAW(진짜 필드 없음, 평문 토큰)
BADGE_READY = "✅ 실행 준비"           # COMPILED/FILLED(잔존 토큰 0)
BADGE_ERROR = "⚠ 템플릿 오류"          # 손상 템플릿 — 조용한 ✅ 금지, 시끄럽게 알림
BADGE_CORRUPT = "⚠ 손상됨"             # .job.json 파싱 실패 — 목록을 죽이지 않되 시끄럽게(RC-05)


def _partial_badge(n: int) -> str:
    """PARTIAL 배지 — N = 미확인(잔존) 토큰 수."""
    return f"⚠ 미확인 토큰 {n}개"


def _derive_compile(tpath: str, template_missing: bool) -> "tuple[CompileState | None, str]":
    """(compile_state, compile_badge) 를 C2 ``compile_status`` 에서 파생한다.

    비용 주의: 템플릿이 존재하면 매 refresh 마다 .hwpx 를 파싱해 상태를 **재계산**한다
    (한글 재편집으로 COMPILED→PARTIAL 드리프트가 나므로 저장·캐시하지 않는다 — C2 의
    compute-not-store 원칙). 손상 템플릿이 홈 목록을 죽이지 않도록 예외를 가드하되,
    조용히 ✅ 로 통과시키지 않고 시끄럽게 오류 배지로 강등한다.
    """
    if not tpath:
        return None, ""                       # 템플릿 경로 없음 → 배지 없음(부재 아님)
    if template_missing:
        return None, BADGE_MISSING            # 부재 경로엔 compile_status 를 부르지 않는다
    try:
        st = compile_status(tpath)
    except Exception:
        return None, BADGE_ERROR              # 손상/파싱 실패 → 시끄럽게 강등(never silent ✅)
    if st.state == CompileState.RAW:
        return st.state, BADGE_RAW
    if st.state == CompileState.PARTIAL:
        # N = 미확인(잔존) 토큰 총합: skip 채널 + 본문 stray + 미컴파일(compilable).
        n = st.skipped_n + st.stray_n + st.compilable_n
        return st.state, _partial_badge(n)
    return st.state, BADGE_READY              # COMPILED 또는 FILLED(잔존 토큰 0)


def _fmt_iso(ts: str) -> str:
    """ISO-8601 → 'YYYY-MM-DD HH:MM' (파싱 실패 시 원문)."""
    try:
        return datetime.fromisoformat(ts).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return ts


@dataclass
class JobRow:
    """카드 1건이 렌더할 성형된 데이터 — 위젯은 이 필드만 읽는다(Job 을 직접 안 만진다)."""

    name: str
    template_name: str
    template_missing: bool
    field_count: int
    filename_pattern: str
    last_run_display: str
    last_run_at: str = ""  # 원시 ISO(KPI '최근 실행' 계산용, ""=미실행)
    # C2 파생 컴파일 상태(seam) — refresh 마다 재계산(저장·캐시 없음). None = 배지 없음/부재/오류.
    compile_state: "CompileState | None" = None
    compile_badge: str = ""
    # 브라우징용 분류 태그 {축→값}(JOB_BROWSER_DESIGN D1·D2) — group-by/facet 의 소스.
    # 위젯은 카드에 직접 렌더하지 않는다(D8 카드 스펙 불변); 섹션·칩만 이 값을 소비한다.
    tags: "dict[str, str]" = field(default_factory=dict)

    @classmethod
    def from_job(cls, job: Job) -> "JobRow":
        tpath = job.template_path
        # 실행 화면의 템플릿 가드를 홈에서 선고지(비차단).
        template_missing = bool(tpath) and not Path(tpath).exists()
        compile_state, compile_badge = _derive_compile(tpath, template_missing)
        return cls(
            name=job.name,
            template_name=(Path(tpath).name or "—") if tpath else "—",
            template_missing=template_missing,
            field_count=len(job.mapping.mappings),
            filename_pattern=job.filename_pattern,
            last_run_display=(
                f"최근 실행 {_fmt_iso(job.last_run_at)}" if job.last_run_at else "아직 실행 안 함"
            ),
            last_run_at=job.last_run_at,
            compile_state=compile_state,
            compile_badge=compile_badge,
            tags=dict(job.tags),
        )

    def meta_line(self) -> str:
        return (
            f"템플릿 {self.template_name} · 필드 {self.field_count}개 · "
            f"파일명 {self.filename_pattern}"
        )

    def is_runnable(self) -> bool:
        """실행 진입 가능 여부 — 카드 상태 모델과 실행 판정을 잇는 단일 술어(UD-03).

        판정을 badge_level(RC-29 단일 어휘)에 연결한다: ``danger``(템플릿 부재·손상·컴파일
        오류·미설정 = compile_state None)면 실행 불가, 그 외(RAW·PARTIAL·COMPILED·FILLED)는
        진입 가능하다. RAW/PARTIAL 은 아직 실행 준비 전이지만 진입 자체는 허용하고
        위젯이 CTA 강조를 강등해 고지한다. 카드 [실행] 버튼 활성화와 더블클릭 게이트가
        이 한 술어를 공유해 같은 액션의 두 경로가 다른 판정을 내지 않는다(자기 모순 해소).
        """
        return badge_level(self.compile_state) != ERROR_BADGE_LEVEL


@dataclass
class CorruptJobRow:
    """파싱 실패한 ``.job.json`` 1건 — 조용히 감추지 않고 '손상됨' 행으로 노출한다(RC-05).

    이름을 알 수 없으므로(JSON 파싱 불가) 파일명이 식별자다. 사용자가 원인 파일을
    직접 복구/삭제할 수 있게 경로·오류를 그대로 나른다.
    """

    file_name: str
    path: str
    error: str

    def detail_line(self) -> str:
        return f"작업 파일을 읽을 수 없습니다 — {self.error}"


@dataclass
class TxtRow:
    """txt 기안 템플릿 1건(대시보드 txt 트랙 목록)."""

    name: str
    field_count: int


@dataclass
class DashboardKpi:
    """대시보드 요약 — 전부 실재 데이터(레지스트리·실행 이력·템플릿 상태·txt 루트)."""

    job_count: int
    recent_run: str            # "MM-DD · 작업명" 또는 "—"
    missing_template_count: int
    txt_template_count: int
    pool_count: int = 0        # 데이터 풀 활성 항목 수(durable 참조)


# ── 작업 브라우저(패싯 탐색) — group-by 렌즈 + facet (JOB_BROWSER_DESIGN §4) ──────
# 씨앗 기본 group-by 축(D5·O2) — INI 지속 렌즈가 없을 때의 초기값으로만 쓴다. 축 레지스트리가
# 아니다(D3 축은 태그에서 발견); 이 축에 태그가 없으면 flat 로 자연 강등된다. "틀려도 싼 값".
SEED_GROUP_BY_AXIS = "금액구간"
# 미태깅 작업이 서는 그룹의 표시 라벨(D12 — 선택적 태그의 1급 섹션). group-by 축의 값이
# 없는 작업도 저장·브라우징에서 사라지지 않고 이 섹션에 모인다.
NO_VALUE_LABEL = "(값 없음)"


@dataclass
class GroupSection:
    """group-by 축의 한 구간 — 값 라벨·건수·그 구간에 속한 카드 행들.

    ``value`` = 태그 값(명명 그룹), :data:`NO_VALUE_LABEL`(미태깅 그룹), 또는 ""(flat 단일
    버킷 — group-by 미적용). 위젯은 섹션이 ≤1개이고 활성 facet 이 없으면 헤더를 억제하고
    오늘과 동일한 평면 리스트를 그린다(퇴화-코퍼스 불변식).
    """

    value: str
    count: int
    rows: "list[JobRow]"


@dataclass
class FacetValue:
    """한 facet 축의 값 하나 — 값·건수(현재 다른 facet 제약 하)·활성 여부."""

    value: str
    count: int
    active: bool


@dataclass
class FacetAxis:
    """group-by 로 쓰이지 않는 한 축 = facet — 값 목록(칩 묶음)."""

    axis: str
    values: "list[FacetValue]"


class HomeViewModel:
    """작업 목록 상태 + 레지스트리 어댑터. 위젯은 구독해서 렌더한다."""

    def __init__(self, registry: JobRegistry, text_registry=None, pool_registry=None):
        self.registry = registry
        self.text_registry = text_registry  # TextTemplateRegistry | None (txt 트랙)
        self.pool_registry = pool_registry  # DatasetPoolRegistry | None (데이터 풀 KPI)
        self._rows: "list[JobRow]" = []
        self._corrupt_rows: "list[CorruptJobRow]" = []
        self._selected: "str | None" = None
        self._subs: "list" = []
        # 사용자 소유 group-by 렌즈(D4) — 축 키 하나(""=flat). 씨앗으로 초기화하되(D5)
        # 위젯이 INI 지속 렌즈로 덮어쓸 수 있다(링1 VM 은 값만 보유, 지속 IO 는 위젯 몫).
        self.active_group_by: str = SEED_GROUP_BY_AXIS
        # facet 선택(D10 — facet 내 OR / facet 간 AND). {축 → 선택된 값 집합}, 빈 축은 제거.
        self.active_facets: "dict[str, set[str]]" = {}
        self.refresh()

    # ---------------------------------------------------------- 변경 통지
    def subscribe(self, cb) -> None:
        """상태 변경 시 호출될 콜백 등록(위젯의 렌더 메서드)."""
        self._subs.append(cb)

    def _notify(self) -> None:
        for cb in self._subs:
            cb()

    # ---------------------------------------------------------- 데이터
    def refresh(self) -> None:
        """레지스트리에서 다시 읽어 행을 성형하고 통지(선택은 살아있으면 보존).

        손상 ``.job.json`` 은 격리 수집(RC-05)해 :meth:`corrupt_rows` 로 노출한다 —
        정상 작업은 계속 표시하되 손상 파일을 조용히 감추지 않는다.
        """
        corrupted: "list" = []
        self._rows = [
            JobRow.from_job(j) for j in self.registry.list_jobs(corrupted=corrupted)
        ]
        self._corrupt_rows = [
            CorruptJobRow(file_name=p.name, path=str(p), error=err)
            for p, err in corrupted
        ]
        if self._selected not in {r.name for r in self._rows}:
            self._selected = None
        self._notify()

    def rows(self) -> "list[JobRow]":
        return list(self._rows)

    def corrupt_rows(self) -> "list[CorruptJobRow]":
        """파싱 실패한 작업 파일 행 — 홈이 '손상됨' 배지 카드로 렌더한다(RC-05)."""
        return list(self._corrupt_rows)

    def is_empty(self) -> bool:
        # 손상 행만 있어도 빈 상태로 위장하지 않는다 — 손상 행이 보여야 한다.
        return not self._rows and not self._corrupt_rows

    def count_label(self) -> str:
        return f"{len(self._rows)}건" if self._rows else ""

    # ---------------------------------------------------------- 대시보드
    def kpi(self) -> DashboardKpi:
        """대시보드 KPI — 실재 데이터만(가짜 지표 없음)."""
        runs = [r for r in self._rows if r.last_run_at]
        if runs:
            latest = max(runs, key=lambda r: r.last_run_at)
            recent = f"{_fmt_iso(latest.last_run_at)[5:10]} · {latest.name}"
        else:
            recent = "—"
        return DashboardKpi(
            job_count=len(self._rows),
            recent_run=recent,
            missing_template_count=sum(1 for r in self._rows if r.template_missing),
            txt_template_count=self.text_registry.count() if self.text_registry else 0,
            pool_count=self._pool_count(),
        )

    def _pool_count(self) -> int:
        """데이터 풀 활성(active) 항목 수. 레지스트리 없거나 읽기 실패면 0(조용히 감춤 아님 —
        관리 표면이 손상 파일을 시끄럽게 노출; KPI 는 요약이라 0 으로 안전 강등)."""
        if self.pool_registry is None:
            return 0
        try:
            from ..core.dataset_pool import STATUS_ACTIVE

            return len(self.pool_registry.list_items(status=STATUS_ACTIVE))
        except Exception:  # noqa: BLE001
            return 0

    def txt_rows(self) -> "list[TxtRow]":
        """txt 기안 템플릿 목록(정해진 루트). 레지스트리 없으면 빈 목록."""
        if self.text_registry is None:
            return []
        return [
            TxtRow(t.name, len(t.fields())) for t in self.text_registry.list_templates()
        ]

    # ---------------------------------------------------------- 선택
    @property
    def selected_name(self) -> "str | None":
        return self._selected

    def select(self, name: "str | None") -> None:
        """선택 갱신 — 값싸므로 재렌더 통지는 하지 않는다(위젯이 버튼만 동기화)."""
        self._selected = name if name in {r.name for r in self._rows} else None

    def has_selection(self) -> bool:
        return self._selected is not None

    def delete(self, name: str) -> None:
        """작업 삭제 후 목록 갱신(확인 UI 는 위젯/컨트롤러 몫)."""
        self.registry.delete(name)
        if self._selected == name:
            self._selected = None
        self.refresh()

    # ------------------------------------------------- 작업 브라우저(group/facet)
    def axes(self) -> "list[str]":
        """사용 가능한 분류 축 목록 — 작업들에 실제 붙은 태그 키의 합집합(D3 발견).

        authored 레지스트리가 없다: 축 추가는 태그를 붙이는 데이터 행위일 뿐. 결정적 표시를
        위해 정렬한다(값 순서 편집 D11 은 보류 — v1 알파벳).
        """
        keys: "set[str]" = set()
        for r in self._rows:
            keys.update(r.tags.keys())
        return sorted(keys)

    def effective_group_by(self) -> str:
        """실제 적용되는 group-by 축 — 렌즈 값이 발견된 축일 때만 유효, 아니면 ""(flat).

        씨앗 축(D5)이 이 코퍼스에 없으면(태그 0 등) 자동으로 flat 로 강등된다 — 첫 실행이
        오늘과 동일해지는 퇴화-코퍼스 불변식의 링1 절반.
        """
        return self.active_group_by if self.active_group_by in self.axes() else ""

    def _passes_facets(self, row: "JobRow", exclude_axis: str) -> bool:
        """facet 간 AND / facet 내 OR — ``exclude_axis`` 축은 제약에서 뺀다.

        group-by 축(섹션 분할 축)이나 자기 자신의 카운트를 셀 때 해당 축을 뺀다(표준 패싯
        의미론: 한 facet 의 선택은 그 facet 자신의 카운트를 좁히지 않는다).
        """
        for axis, sel in self.active_facets.items():
            if axis == exclude_axis or not sel:
                continue
            if row.tags.get(axis) not in sel:  # facet 내 OR(집합 소속) / facet 간 AND(전 축 통과)
                return False
        return True

    def grouped_rows(self) -> "list[GroupSection]":
        """활성 facet 으로 좁힌 뒤 effective group-by 축으로 분할한 섹션들.

        미태깅(그 축 값 없음) 작업은 :data:`NO_VALUE_LABEL` 섹션에 1급으로 선다(D12).
        flat(축 미유효)이면 단일 버킷 하나만 돌려주고, 위젯이 헤더를 억제한다.
        """
        eff = self.effective_group_by()
        rows = [r for r in self._rows if self._passes_facets(r, exclude_axis=eff)]
        if not eff:
            return [GroupSection(value="", count=len(rows), rows=list(rows))]
        named: "dict[str, list[JobRow]]" = {}
        untagged: "list[JobRow]" = []
        for r in rows:
            v = r.tags.get(eff)
            if not v:  # None 또는 "" → 미태깅
                untagged.append(r)
            else:
                named.setdefault(v, []).append(r)
        sections = [
            GroupSection(value=v, count=len(named[v]), rows=named[v])
            for v in sorted(named)
        ]
        if untagged:  # 미태깅 그룹은 명명 그룹 뒤 1급 섹션(D12)
            sections.append(
                GroupSection(value=NO_VALUE_LABEL, count=len(untagged), rows=untagged)
            )
        return sections

    def facets(self) -> "list[FacetAxis]":
        """group-by 로 쓰이지 않는 축들 = facet. 각 값에 건수·활성 여부(D10).

        건수는 **자기 축을 제외한** 다른 facet 제약 하의 행 수 — 표준 패싯 의미론. 0건 값도
        돌려주고(위젯이 회색/억제), 값 순서는 알파벳(D11 보류).
        """
        eff = self.effective_group_by()
        result: "list[FacetAxis]" = []
        for axis in self.axes():
            if axis == eff:
                continue  # group-by 축은 섹션이지 facet 이 아니다
            values = sorted({r.tags[axis] for r in self._rows if r.tags.get(axis)})
            sel = self.active_facets.get(axis, set())
            fvals = [
                FacetValue(
                    value=v,
                    count=sum(
                        1
                        for r in self._rows
                        if r.tags.get(axis) == v
                        and self._passes_facets(r, exclude_axis=axis)
                    ),
                    active=v in sel,
                )
                for v in values
            ]
            result.append(FacetAxis(axis=axis, values=fvals))
        return result

    def set_group_by(self, axis: "str | None") -> None:
        """group-by 렌즈 교체(""=flat). 변경 시 통지(select 와 달리 표시가 바뀌므로 재렌더).

        새 group-by 축에 걸려 있던 facet 선택은 제거한다 — 그 축은 이제 섹션 분할 축이라
        facet 이 아니다(의미론 일관).
        """
        axis = axis or ""
        if axis == self.active_group_by:
            return
        self.active_group_by = axis
        self.active_facets.pop(axis, None)
        self._notify()

    def toggle_facet(self, axis: str, value: str) -> None:
        """한 facet 값 on/off. 마지막 값을 끄면 축 키를 제거해 상태를 깨끗이 유지."""
        sel = self.active_facets.setdefault(axis, set())
        if value in sel:
            sel.discard(value)
        else:
            sel.add(value)
        if not sel:
            self.active_facets.pop(axis, None)
        self._notify()

    def clear_facets(self) -> None:
        """활성 facet 전부 해제(D10 '활성 제약 일괄 해제')."""
        if self.active_facets:
            self.active_facets = {}
            self._notify()

    def set_facets(self, facets: "dict[str, set[str]]") -> None:
        """facet 선택 일괄 지정(INI 복원용) — 통지는 1회. 빈 값 집합은 버린다."""
        self.active_facets = {a: set(v) for a, v in facets.items() if v}
        self._notify()


def discover_tag_axes(jobs: "list[Job]") -> "dict[str, list[str]]":
    """작업 목록에서 분류 축과 각 축의 알려진 값들을 발견한다(에디터 태그 편집의 후보 공급).

    링1 순수 함수(Qt·레지스트리 비의존) — 호출자가 ``registry.list_jobs()`` 를 넘긴다.
    반환 = {축 → 정렬된 값 리스트}. 축 authored 레지스트리 없음(D3)과 정합.
    """
    axes: "dict[str, set[str]]" = {}
    for j in jobs:
        for k, v in j.tags.items():
            if v:
                axes.setdefault(k, set()).add(v)
    return {k: sorted(axes[k]) for k in sorted(axes)}
