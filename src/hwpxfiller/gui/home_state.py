"""전역 문서 작업 라이브러리 ViewModel — Qt 비의존 프레젠테이션 상태(목록·투영·건강).

**이 모듈이 소유하는 것은 「문서 작업」 라이브러리(§19.6·§19.7)이지 홈 화면이 아니다.**
홈은 재작성 F2 에서 죽었고(지도 §10.8) 그 자리를 라이브러리가 이었다. 파일명·클래스명
(``home_state``·``HomeViewModel``)은 그대로 둔다 — 지도 §10.3 이 이 모듈을 "재작성 무영향"
자산으로 배정했고 개명은 링1 전역 diff 를 부르는 데 비해 얻는 것이 어휘뿐이다. 링2 는
정산했다(``screen_library``·푸시 채널 ``library``); 남은 어휘 빚을 숨기지 않고 여기 적는다.

웹 컨트롤러(:class:`~hwpxfiller.webapp.screen_library.LibraryController`)는 이 뷰모델의
``library_sections()``·``library_counts()``·``facets()``·``rows()`` 결과를 렌더한다.
레지스트리 접근, 행 메타 문자열, 최근실행 포맷, 선택 상태가 여기 산다 — 변경 통지는 순수
옵저버 콜백(``subscribe``)이라 창 없이 테스트된다(링1 규율: PySide6 임포트 금지).
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from ..application.jobs import delete_job, remove_corrupt_entry, update_tags
from ..domain.engine import HwpxEngine
from ..domain.fill_ledger import template_path_drift
from ..domain.job import Job, require_hwpx_template
from ..domain.template_status import CompileState, TemplateStatus
from ..domain.dataset_reference import STATUS_ACTIVE
from .compile_badge import ERROR_BADGE_LEVEL, badge_level
from .run_state import unresolved_name_tokens_for
from .work_mode import last_use_label

# (손상 조치 거절 문구 CORRUPT_PATH_REJECT 는 P2-21 #569 에서 Application 포트 계약
#  (:mod:`~hwpxfiller.application.jobs`)으로 이사 — 잠금 안 재판정이 External semantic op
#  로 내려가면서 그 문구의 발화 주체가 이 모듈이 아니게 됐다.)

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


#: 경로 → 컴파일 상태 판정 포트(P2-19R, #576). Domain 판정(compile_status)은 열린
#: package 전용이 되어, 경로 열기는 ring 2 가 결속한 이 포트가 진다(concrete =
#: external/template_inspection.template_compile_status).
TemplateStatusPort = Callable[[str], TemplateStatus]


def _derive_compile(
    tpath: str, template_missing: bool, inspect_status: TemplateStatusPort
) -> "tuple[CompileState | None, str]":
    """(compile_state, compile_badge) 를 C2 ``compile_status`` 파생 포트에서 파생한다.

    비용 주의: 템플릿이 존재하면 매 refresh 마다 .hwpx 를 파싱해 상태를 **재계산**한다
    (한글 재편집으로 COMPILED→PARTIAL 드리프트가 나므로 저장·캐시하지 않는다 — C2 의
    compute-not-store 원칙). 손상 템플릿이 홈 목록을 죽이지 않도록 예외를 가드하되,
    조용히 ✅ 로 통과시키지 않고 시끄럽게 오류 배지로 강등한다.
    """
    if not tpath:
        return None, ""                       # 템플릿 경로 없음 → 배지 없음(부재 아님)
    # backstop(3부 결정 13 · 2층): 여기 닿는 경로는 hwpx 여야 한다 — from_job 이 매체로 선분기하므로
    # 정상 경로에선 통과가 보장된다. txt 경로가 새어 들면 compile_status 가 zip 파싱으로 엉뚱한
    # 오류 배지를 조용히 내는 대신 시끄럽게 터진다(홈은 두 매체를 다 보는 유일 표면).
    require_hwpx_template(tpath)
    if template_missing:
        return None, BADGE_MISSING            # 부재 경로엔 compile_status 를 부르지 않는다
    try:
        st = inspect_status(tpath)
    except Exception:
        return None, BADGE_ERROR              # 손상/파싱 실패 → 시끄럽게 강등(never silent ✅)
    if st.state == CompileState.RAW:
        return st.state, BADGE_RAW
    if st.state == CompileState.PARTIAL:
        # N = 미확인(잔존) 토큰 총합: skip 채널 + 본문 stray + 미컴파일(compilable) +
        # 미변환 구간 표기(S8-04). 마커를 빼면 마커만 남은 PARTIAL 이 「미확인 토큰 0개」라는
        # 속 빈 배지가 된다 — 상태는 시끄러운데 수치가 조용한 어긋남.
        n = st.skipped_n + st.stray_n + st.compilable_n + st.structure_marker_n
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
    """카드 1건이 렌더할 성형된 데이터 — 표현 계층은 이 필드만 읽는다."""

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
    # 카드에 직접 렌더하지 않는다(D8 카드 스펙 불변); 섹션·칩만 이 값을 소비한다.
    tags: "dict[str, str]" = field(default_factory=dict)
    # 라이브러리 보기(§19.6)의 축 — 사용자 group(구획)·즐겨찾기(우선순위)·매체(작업 방식).
    # 전부 이미 durable 에 있는 값의 성형이다(무확장 — 새 판정을 만들지 않는다).
    group: str = ""
    favorited_at: str = ""
    media: str = ""
    # 템플릿을 아직 연결하지 않은 상태(경로 빈 값) — **미상 매체와 다르다**: 저작 중인
    # 정상 hwpx 작업이고 복구 동선도 「템플릿 다시 연결」로 명확하다(리뷰 P2).
    template_linked: bool = True
    # 템플릿 구조 ↔ 확정 매핑의 대칭차(리뷰 P2). COMPILED 여도 필드가 늘거나 빠지면 실행은
    # `validate_generate` 가 **차단**하는데 건강 보기가 건강으로 분류하면, 사용자는 실행을
    # 눌러 보고서야 안다. compile_status 와 같은 compute-not-store 원칙(재편집 드리프트가
    # 나므로 저장하지 않는다) — 그 대가로 hwpx 행마다 템플릿을 한 번 더 읽는다.
    structure_drift: bool = False
    # txt 템플릿을 지금 읽을 수 있는가(리뷰 P2). 파일이 "있다"는 것과 "열린다"는 것은 다르다 —
    # 깨진 인코딩·`.txt` 로 끝나는 디렉터리는 존재하지만 여는 순간 실패한다.
    txt_readable: bool = True
    # 파일명 패턴이 요구하는데 매핑이 채우지 못하는 토큰(데이터 무관·작업 정의 수준 계약).
    # 실행은 danger 로 차단하는데 건강 보기가 침묵하면 사용자는 열어 보고서야 안다.
    unresolved_name_tokens: bool = False
    # 확정 매핑이 아직 없음 — 드리프트와 **원인이 다르지만 둘 다 실행을 막는다**(리뷰 P2).
    mapping_empty: bool = False

    @classmethod
    def from_job(
        cls, job: Job, *, engine: HwpxEngine, inspect_status: TemplateStatusPort
    ) -> "JobRow":
        tpath = job.template_path
        # 실행 화면의 템플릿 가드를 홈에서 선고지(비차단).
        template_missing = bool(tpath) and not Path(tpath).exists()
        # 매체 선분기(3부 결정 13 · 1층 조회 경계): hwpx 작업만 컴파일 수명주기를 갖는다.
        # txt 기안·미상 매체는 hwpx 배지 개념이 없어 배지 없음(txt 를 hwpx 로 파싱하지 않는다).
        if job.media == "hwpx":
            compile_state, compile_badge = _derive_compile(
                tpath, template_missing, inspect_status
            )
        else:
            compile_state, compile_badge = None, ""
        txt_readable = True
        if job.media == "txt" and tpath and not template_missing:
            # 여는 계약과 **같은 방식**으로 읽어 본다(UTF-8) — 다른 방식으로 재보면 이 화면과
            # 실제 열기가 서로 다른 답을 낸다. 소량 텍스트라 비용은 hwpx zip 파싱보다 싸다.
            try:
                Path(tpath).read_text(encoding="utf-8")
            except Exception:  # noqa: BLE001 — 못 읽으면 이유 불문 "지금 열 수 없다"
                txt_readable = False
        # 실행 게이트와 **같은 몸통**을 쓴다(두 표면이 같은 상태를 다르게 부르지 않게).
        name_tokens = bool(unresolved_name_tokens_for(job)) if job.media == "hwpx" else False
        drift = False
        if job.media == "hwpx" and compile_state is not None:
            # 읽을 수 있는 템플릿에서만 본다(못 읽는 건 이미 danger 로 말한다). 매핑이 비어
            # 있어도 **계산은 한다**: 실행 게이트는 그 상태를 template_only 드리프트로 막으므로
            # 건강 보기가 침묵하면 숨은 차단이 된다. 다만 **부르는 이름은 다르다** — 아직 안
            # 맞춘 것은 "달라졌다"가 아니다(사유는 library_health 가 가른다).
            drift = template_path_drift(tpath, job.mapping, engine=engine).has_drift
        return cls(
            name=job.name,
            template_name=(Path(tpath).name or "—") if tpath else "—",
            template_missing=template_missing,
            field_count=len(job.mapping.mappings),
            filename_pattern=job.filename_pattern,
            # 최근 사용 문구는 **방식이 정한다**(§19.4 표 · `last_use_label` 단일 출처).
            # 저장 필드는 `last_run_at` 하나지만 그 뜻은 매체마다 다르다: hwpx 는 생성
            # 완주에서, txt 는 작업대 **복사 완료** 1건에서 찍힌다. 한 문구로 뭉치면 문서를
            # 한 번도 만든 적 없는 TXT 작업이 목록·상세에서 「최근 실행」으로 보인다.
            last_run_display=last_use_label(job.work_mode, job.last_run_at),
            last_run_at=job.last_run_at,
            compile_state=compile_state,
            compile_badge=compile_badge,
            tags=dict(job.tags),
            group=job.group,
            favorited_at=job.favorited_at,
            media=job.media,
            template_linked=bool(tpath),
            structure_drift=drift,
            txt_readable=txt_readable,
            unresolved_name_tokens=name_tokens,
            mapping_empty=not job.mapping.mappings,
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
        표현 계층이 CTA 강조를 강등해 고지한다. 카드 [실행] 액션과 진입 게이트가
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
        return f"작업 파일을 읽을 수 없습니다: {self.error}"


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
    pool_corrupted: int = 0    # 데이터 풀 손상 파일 수 — 0 위장 금지, 병기 표시(C5)


# ── 작업 브라우저(패싯 탐색) — tag facet (JOB_BROWSER_DESIGN §4) ─────────────────
# group-by 렌즈는 은퇴했다(지도 §10.8 판정 B · §9.4 A안): 「모든 작업」 보기의 primary
# grouping 은 **사용자 group** 하나뿐이고(§19.2 "화면당 primary grouping 하나"), 태그는
# 좁히는 축(facet)으로만 남는다. 씨앗 축 상수·`active_group_by`·`grouped_rows` 도 함께
# 죽었다 — 아무도 보지 않는 구획 축을 남기면 제2 정본이 되어 다음 세션이 되살린다.
# 승계 의무(§9.4): ①facet 칩 존치 ②영속값은 애초에 없었다(씨앗 상수뿐 → 삭제가 이행분)
# ③퇴화-코퍼스 불변식은 library_sections 가 계속 진다.
#: 사용자 group 이 없는 작업이 서는 구획의 표시 라벨(§19.6 "`그룹 없음` 마지막").
#: 표면이 문안을 다시 만들지 않도록 링1 이 소유한다.
NO_GROUP_LABEL = "그룹 없음"


@dataclass
class GroupSection:
    """목록의 한 구획 — 값 라벨·건수·그 구간에 속한 행들.

    ``value`` = 사용자 group 이름, 또는 ""(구획 없음). ""는 **두 가지**를 뜻할 수 있어
    ``is_untagged`` 로 가른다: 나눌 group 이 없어 헤더 없이 퇴화한 평면 단일 버킷
    (``is_untagged=False``)과, group 없는 작업들이 명명 구간 뒤에 서는 1급 구획
    (``is_untagged=True``)이다. 표현 계층이 ``value`` 문자열로만 키잉하면 둘이 같은 키가 돼
    퇴화 평면에 헤더가 붙거나 「그룹 없음」이 헤더를 잃는다 — 정체성을 표시 값과 분리한다.
    """

    value: str
    count: int
    rows: "list[JobRow]"
    is_untagged: bool = False  # 구획 값 없음(「그룹 없음」) — 표시 라벨과 별개인 정체성 표식


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


#: 전역 라이브러리 보기(§19.6) — 투영만 바꾸는 사용자 렌즈.
VIEW_ALL = "all"
VIEW_RECENT = "recent"
VIEW_FAVORITES = "favorites"
VIEW_NEEDS = "needsAction"
_VIEWS = (VIEW_ALL, VIEW_RECENT, VIEW_FAVORITES, VIEW_NEEDS)

#: 작업 방식 필터 — 매체에서 파생(저장 필드 아님). 모든 보기와 AND 로 결합한다.
MODE_ALL = "all"
MODE_HWPX = "hwpx"
MODE_TXT = "txt"
_MODES = (MODE_ALL, MODE_HWPX, MODE_TXT)


def library_mode_of(row: "JobRow") -> str:
    """작업 방식 필터가 보는 매체 — **미연결은 hwpx 로 센다**(리뷰 P2).

    경로가 비면 ``Job.media`` 는 ``""`` 지만 그건 저작 중인 hwpx 작업이다(「작업」 화면의
    조회 경계와 같은 판정). 미상으로 두면 사용자가 고치러 오는 바로 그 필터(HWPX)에서
    사라지고 「확인 필요」 건수에서도 빠진다 — 진단은 내면서 손 닿는 곳에는 안 두는 꼴.
    실제 미상 확장자(경로는 있는데 hwpx/txt 가 아님)는 그대로 미상으로 남는다.
    """
    return MODE_HWPX if not row.template_linked else row.media


def library_health_causes(row: "JobRow") -> "list[tuple[int, str]]":
    """전역 작업 건강(§19.7)의 **전 원인** — 상세 패널이 읽는 정본(지도 §10.8 판정 E).

    계약 §19.7: "목록에는 가장 높은 심각도 하나를 표시하고 상세에서 모든 실제 원인을
    보여준다." 그래서 원인 열거가 정본이고 :func:`library_health` 의 1건은 **이 목록의
    파생**이다 — 같은 상태를 두 술어가 따로 판정하면 목록과 상세가 서로 다른 말을 한다
    (판정 단일 출처, `unresolved_name_tokens_for` 선례).

    현재 데이터 호환성(`compatibility_for`)과 섞지 않는다(§19.7 명문): 여기 들어오는 건
    데이터와 무관한 작업 자체의 상태뿐이다. master 가 이미 내는 신호만 옮긴다(새 판정
    금지). 손상 JSON 은 애초에 :class:`CorruptJobRow` 로 분리돼 이 목록에 오지 않는다.

    정렬 = 심각도 내림차순, 동률은 **발견 순서 유지**(안정 정렬). 발견 순서가 곧 진단의
    구체성 순서라 목록에 서는 대표 1건이 가장 실행 가능한 처방을 가리킨다.
    """
    causes: "list[tuple[int, str]]" = []
    # ── 템플릿 계보: 앞의 사유가 참이면 뒤는 **판정할 근거가 없다**(연쇄 elif 유지).
    # 연결 안 된 작업에 "지원하지 않는 작업 방식"을 함께 실으면 오진이 하나 늘 뿐이다.
    if not row.template_linked:
        # 경로가 비어 있는 건 "미상 매체"가 아니라 **아직 연결하지 않은 저작 중 작업**이다.
        # 진단이 틀리면 처방도 틀린다 — 여기서 갈라야 사용자가 「템플릿 다시 연결」로 간다.
        causes.append((3, "템플릿을 아직 연결하지 않았습니다."))
    elif row.template_missing:
        causes.append((3, "템플릿 파일을 찾을 수 없습니다."))
    elif row.media not in ("hwpx", "txt"):
        causes.append((3, "지원하지 않는 작업 방식입니다."))
    elif row.media == "hwpx" and row.compile_state is None:
        causes.append((3, "템플릿을 읽을 수 없습니다."))
    elif not row.txt_readable:
        # 파일이 있다고 열리는 건 아니다(깨진 인코딩·`.txt` 디렉터리) — 열면 바로 실패하는데
        # 건강 보기가 건강으로 분류하면 「확인 필요」가 정작 못 여는 작업을 빼놓는다.
        causes.append((3, "템플릿을 읽을 수 없습니다."))
    # ── 작업 정의 계보: 템플릿 상태와 **독립**이라 위 사유와 함께 실린다. 목록은 최고
    # 심각도 1건만 보여주므로 여기 추가해도 대표 문구는 안 바뀌고, 상세만 두 원인을 본다.
    if row.unresolved_name_tokens:
        # 실행 게이트가 danger 로 차단하는 상태(§19.7 차단 등급) — 데이터가 없어도 참이라
        # 라이브러리에서 먼저 말할 수 있다.
        causes.append((3, "파일명 패턴의 토큰을 채우지 못합니다."))
    if row.structure_drift and row.mapping_empty:
        # 같은 신호(대칭차)지만 원인이 다르다: 아직 아무것도 맞추지 않은 작업이다. 드리프트로
        # 부르면 오진이고(무엇이 "달라졌다"는 말인가), 숨기면 실행에서 막히는 걸 뒤늦게 안다.
        causes.append((3, "매핑을 아직 확정하지 않았습니다."))
    elif row.structure_drift:
        # §19.7 "확인된 Template/Binding drift = 2, 차단하지 않음"의 자리. 실행 게이트는
        # 실제로 차단하지만(fail-closed), 여기서 말하는 건 **작업 자체의 건강**이라 등급은
        # 계약 표를 따르고 강도는 실행 게이트가 낸다(두 표면이 서로 다른 판정을 만들지 않게).
        causes.append((2, "템플릿 구조가 확정 매핑과 달라졌습니다."))
    elif badge_level(row.compile_state) == "warn":
        # 미확인 토큰이 남은 템플릿(PARTIAL)은 **실행을 막지는 않지만** 손볼 것이 있다 —
        # 기존 신호가 이미 warn 배지로 말하는데 「확인 필요」에서 빼면 그 경고가 이 화면에서만
        # 증발한다. 판정은 새로 만들지 않고 배지 레벨(RC-29 단일 어휘)을 번역할 뿐이다.
        causes.append((2, row.compile_badge or "템플릿에 확인할 항목이 남아 있습니다."))
    causes.sort(key=lambda c: -c[0])  # 안정 정렬 — 동률은 위 발견 순서 그대로
    return causes


def library_health(row: "JobRow") -> "tuple[int, str]":
    """목록 행이 쓰는 건강 대표 1건 — :func:`library_health_causes` 의 최고 심각도.

    파생이지 독립 판정이 아니다(§19.7 "목록에는 가장 높은 심각도 하나"). 건강한 작업은
    ``(0, "")``.
    """
    causes = library_health_causes(row)
    return causes[0] if causes else (0, "")


#: 매핑 유형의 표시 어휘 — 라이브러리 상세 「필드 연결」 표가 소비한다. 편집기(웹)가 같은
#: 어휘를 자기 파일에 따로 두고 있다(`frontend/js/screens/editor.js` ``TYPE_LABEL``); 그 중복은
#: 편집기를 재작성하는 F7 에서 이 상수로 걷는다 — 빚을 숨기지 않고 적어 둔다.
MAPPING_TYPE_LABELS = {"text": "텍스트", "date": "날짜", "amount": "금액", "const": "고정값"}
#: 소스를 아직 고르지 않은 항목 — 「없음」이 아니라 **미지정**이다(조용한 빈칸 금지).
NO_SOURCE_LABEL = "미지정"


@dataclass
class FieldBindingRow:
    """라이브러리 상세 「필드 연결」 표의 한 줄 — 문서 필드 · 데이터 항목 · 표시형(§19.6)."""

    template_field: str
    source_label: str
    format_label: str
    blank: bool = False  # 명시적 공란 선언 — "아직 안 정함"과 시각적으로 갈라야 한다


def field_binding_rows(job: Job) -> "list[FieldBindingRow]":
    """저장된 Binding 을 **그대로** 읽어 상세 표로 성형한다(§19.6 · 지도 §10.8 판정 C·D).

    두 가지를 하지 않는다.

    - **현재 데이터의 원본 열 표시 이름을 쓰지 않는다.** 계약 §19.6 은 데이터가 준비돼
      있으면 열 표시 이름을 쓰라 하지만 그 전제는 v6 의 전역 단일 ``dataState`` 다. master
      에서 현재 데이터는 「문서 만들기」 **세션 소유**라 라이브러리가 읽으면 화면 간 결합을
      새로 만든다. 그래서 항상 저장된 항목 키를 보이고 표면 문안이 그 사실을 말한다.
      되깎기 조건 = 전역 ``dataState`` 가 실제로 서는 시점.
    - **값을 계산하지 않는다.** 미리보기는 데이터를 요구하고(F5 소관) 여기는 정의만 본다.
    """
    from ..domain.format_engine import presets

    rows: "list[FieldBindingRow]" = []
    for m in job.mapping.mappings:
        if m.is_blank:
            rows.append(FieldBindingRow(m.template_field, "비움(명시)", "—", blank=True))
            continue
        type_label = MAPPING_TYPE_LABELS.get(m.type, m.type)
        if m.type == "const":
            # 상수는 데이터 항목이 아니라 값 자체가 정의다 — 표시형 칸에 쓸 것이 없다.
            rows.append(FieldBindingRow(m.template_field, f"고정값 「{m.const}」", "—"))
            continue
        codes = {code: label for label, code in presets(m.type)}
        # 미지 코드(프리셋 밖 직접 입력)는 코드 원문을 그대로 — 모르는 것을 아는 척하지 않는다.
        # 빈 코드("")는 그 유형의 기본 프리셋 라벨이고, 프리셋 자체가 없는 유형이면 ""로 접힌다.
        fmt_label = codes.get(m.fmt, m.fmt)
        rows.append(FieldBindingRow(
            m.template_field,
            m.source or NO_SOURCE_LABEL,
            f"{type_label} · {fmt_label}" if fmt_label else type_label,
        ))
    return rows


class HomeViewModel:
    """작업 목록 상태 + 레지스트리 어댑터. 표현 계층은 구독해서 렌더한다."""

    def __init__(
        # registry 는 JobRegistry 형상(external/job_store) — APPLICATION 층은 External 을
        # import 할 수 없어 타입 주석 없이 덕타이핑으로 받는다(P2-21, #569).
        self, registry, text_registry=None, pool_registry=None,
        *, engine: HwpxEngine, inspect_status: TemplateStatusPort,
    ):
        self.registry = registry
        # zip IO 가 결속된 엔진은 ring 2 가 주입한다(P2-19) — 건강 보기의 드리프트
        # 재계산(:meth:`JobRow.from_job`)이 concrete package IO adapter를 직접 만들지 않는다.
        self._engine = engine
        # 경로 → 컴파일 상태 판정도 같은 이유로 ring 2 가 결속한다(P2-19R, #576).
        self._inspect_status = inspect_status
        self.text_registry = text_registry  # TextTemplateRegistry | None (txt 트랙)
        # 데이터 풀 KPI 원천 — external DatasetPoolRegistry 형상 | None. APPLICATION 층은
        # External 을 import 할 수 없어 타입 주석 없이 덕타이핑으로 받는다(P2-22, #570).
        self.pool_registry = pool_registry
        self._rows: "list[JobRow]" = []
        self._corrupt_rows: "list[CorruptJobRow]" = []
        self._selected: "str | None" = None
        self._subs: "list" = []
        # facet 선택(D10 — facet 내 OR / facet 간 AND). {축 → 선택된 값 집합}, 빈 축은 제거.
        self.active_facets: "dict[str, set[str]]" = {}
        # 전역 라이브러리 보기(§19.6) — 보기 4종 × 작업 방식 필터 × 이름/그룹/태그 검색.
        # 셋 다 **투영**일 뿐 저장 상태가 아니다(무확장: 새 durable 없음).
        self.library_view: str = VIEW_ALL
        self.library_mode: str = MODE_ALL
        self.library_query: str = ""
        self.refresh()

    # ---------------------------------------------------------- 변경 통지
    def subscribe(self, cb) -> None:
        """상태 변경 시 호출될 표현 계층 콜백을 등록한다."""
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
        jobs, corrupt = self.registry.list_jobs_with_corruption()
        self._rows = [
            JobRow.from_job(j, engine=self._engine, inspect_status=self._inspect_status)
            for j in jobs
        ]
        # 손상은 레지스트리가 값 객체(file_name·token·error)로 준다(P2-21 #569) — 이 VM 은
        # 더는 파일 좌표(Path)를 만지지 않고, 표시 문자열(token = 종전 str(path))은 불변이다.
        self._corrupt_rows = [
            CorruptJobRow(file_name=e.file_name, path=e.token, error=e.error)
            for e in corrupt
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
        pool_count, pool_corrupted = self._pool_counts()
        return DashboardKpi(
            job_count=len(self._rows),
            recent_run=recent,
            missing_template_count=sum(1 for r in self._rows if r.template_missing),
            txt_template_count=self.text_registry.count() if self.text_registry else 0,
            pool_count=pool_count,
            pool_corrupted=pool_corrupted,
        )

    def _pool_counts(self) -> "tuple[int, int]":
        """데이터 풀 ``(활성 항목 수, 손상 파일 수)``. 레지스트리 없으면 ``(0, 0)``.

        손상 파일은 격리 수집해 **수를 병기**한다(C5) — 예전의 '읽기 실패 전부 0' 포괄
        강등은 손상 데이터셋을 KPI 에서 무표시 증발시켰다(조용한 드롭 금지). 상세 조치는
        관리 표면(데이터 선택 다이얼로그)이 노출하고, 여기는 요약 카운트만 나른다. 파일 단위
        손상 밖의 실패(디렉터리 접근 불가 등)는 그대로 전파한다 — 0 으로 위장하지 않는다.
        """
        if self.pool_registry is None:
            return (0, 0)

        # 손상은 (Path, str) out-param 이 아니라 값 객체 목록으로 받는다(P2-22 #570 —
        # CorruptDatasetEntry). 이 VM 은 건수만 나르므로 파일 좌표를 만지지 않는다.
        active, corrupted = self.pool_registry.list_references(status=STATUS_ACTIVE)
        return (len(active), len(corrupted))

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
        """선택 갱신 — 값싸므로 재렌더 통지는 하지 않는다(표현 계층이 액션만 동기화)."""
        self._selected = name if name in {r.name for r in self._rows} else None

    def has_selection(self) -> bool:
        return self._selected is not None

    def delete(self, name: str) -> None:
        """작업 삭제 후 목록 갱신(확인 UI 는 컨트롤러 몫)."""
        delete_job(self.registry, name)
        if self._selected == name:
            self._selected = None
        self.refresh()

    def delete_corrupt(self, path: str) -> None:
        """손상 ``.job.json`` 삭제 — 잠금 참여·시간 축 재판정·unlink 는 포트 뒤로 하강했다.

        구판은 이 VM 이 ``write_lock()`` 을 직접 잡고 ``Path.unlink`` 를 불렀다(레지스트리
        API 를 우회하는 유일한 삭제). P2-21 #569 에서 그 임계구역이 External semantic op
        (:meth:`~hwpxfiller.external.job_store.JobRegistry.remove_corrupt_entry`)로 원문
        이동해, 여기는 use case 를 부르고 목록을 갱신할 뿐이다. 목록 밖 token 거절
        (``CORRUPT_PATH_REJECT`` ``ValueError``)의 의미는 그대로다.

        거절이어도 ``finally`` 로 refresh 한다 — 구판이 잠금 안 재판정 **전에** 목록을 새로
        만들어 통지했으므로, 거절 경로에서도 화면이 최신 손상 목록을 보던 관측 행동을 지킨다.
        """
        try:
            remove_corrupt_entry(self.registry, path)
        finally:
            self.refresh()

    def set_tags(self, name: str, raw) -> None:
        """작업의 분류 태그(축→값)를 통째로 교체·저장 — 빈 dict = 전체 해제(#26 D14).

        축·값은 모두 비어 있지 않은 문자열이어야 한다(loud — job_store.decode_job 의 타입 계약
        미러). 같은 이름 재저장은 자기-갱신이라 slug 가드를 자연 통과한다. 저장 후
        refresh 로 axes/facets 가 즉시 재발견된다(퇴화-코퍼스 불변식 유지). 검증까지
        여기 사는 이유: 이 뷰모델의 공개 표면이 seam 계약이다(#44) — 컨트롤러가
        registry 를 직접 만지면 규칙이 표면 밖으로 샌다.
        """
        if not isinstance(raw, dict):
            raise ValueError("태그는 {축: 값} 사전이어야 합니다")
        tags: "dict[str, str]" = {}
        for k, v in raw.items():
            if not isinstance(k, str) or not isinstance(v, str) or not k.strip() or not v.strip():
                raise ValueError("태그의 축·값은 비어 있지 않은 문자열이어야 합니다")
            if k.strip() in tags:  # 공백 변형 중복 축 — 조용한 last-wins 소실 금지(loud)
                raise ValueError(f"중복된 태그 축입니다: {k.strip()!r}")
            tags[k.strip()] = v.strip()
        # 읽기-수정-쓰기는 use case 의 잠긴 원자 왕복으로(#129 리뷰 3R P1, P2-21 #569) —
        # 손으로 load→save 를 엮으면 생성 스레드의 스탬프·에디터 저장과 겹쳐 늦게 착지한
        # 쪽이 상대 변경을 통째로 되돌린다(태그가 방금 찍힌 실행 시각을 지우거나 그 반대).
        # 부재·손상은 여전히 loud.
        update_tags(self.registry, name, tags)
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

    def _passes_facets(self, row: "JobRow", exclude_axis: str) -> bool:
        """facet 간 AND / facet 내 OR — ``exclude_axis`` 축은 제약에서 뺀다.

        자기 자신의 카운트를 셀 때 해당 축을 뺀다(표준 패싯 의미론: 한 facet 의 선택은
        그 facet 자신의 카운트를 좁히지 않는다).
        """
        for axis, sel in self.active_facets.items():
            if axis == exclude_axis or not sel:
                continue
            if row.tags.get(axis) not in sel:  # facet 내 OR(집합 소속) / facet 간 AND(전 축 통과)
                return False
        return True

    # ------------------------------------------------- 전역 라이브러리 보기(§19.6)
    def set_library_view(self, view: str) -> None:
        """보기 교체 — 미지 값은 「모든 작업」으로 퇴화(표면 오타가 빈 화면을 만들지 않는다)."""
        self.library_view = view if view in _VIEWS else VIEW_ALL
        self._notify()

    def set_library_mode(self, mode: str) -> None:
        self.library_mode = mode if mode in _MODES else MODE_ALL
        self._notify()

    def set_library_query(self, text: str) -> None:
        self.library_query = text
        self._notify()

    def _library_pool(self) -> "list[JobRow]":
        """보기 이전 단계 — **태그 facet** ∧ 작업 방식 ∧ 검색(이름·그룹·태그 값, §19.6).

        facet 은 보기 4종 전부와 AND 로 묶인다(§19.6 명문) — 사용자가 켜 둔 칩이 보기를
        바꿨다고 조용히 풀리면 화면이 자기 필터를 배신한다(리뷰 P2).
        """
        from ..domain.jamo import jamo_contains

        rows = [r for r in self._rows if self._passes_facets(r, exclude_axis="")]
        if self.library_mode != MODE_ALL:
            rows = [r for r in rows if library_mode_of(r) == self.library_mode]
        q = self.library_query.strip()
        if q:
            rows = [
                r for r in rows
                if jamo_contains(r.name, q)
                or jamo_contains(r.group, q)
                or any(jamo_contains(v, q) for v in r.tags.values())
            ]
        return rows

    def library_sections(self) -> "list[GroupSection]":
        """보기별 투영(§19.6 표) — 모든 작업만 구획, 나머지는 평면.

        - 모든 작업: 사용자 group 구획(그룹 이름순 → 「그룹 없음」 마지막), 그룹 안 이름순.
          저장된 이름 있는 group 이 하나도 없으면 헤더 없는 평면으로 퇴화한다(1구획 반환).
        - 최근 사용: `last_run_at` 최신순 / 즐겨찾기: `favorited_at` 최신순 / 확인 필요:
          심각도 → 이름순. 동률은 전부 이름순(결정적 순서).
        """
        rows = self._library_pool()
        if self.library_view == VIEW_RECENT:
            picked = [r for r in rows if r.last_run_at]
            picked.sort(key=lambda r: r.name)
            picked.sort(key=lambda r: r.last_run_at, reverse=True)
            return [GroupSection(value="", count=len(picked), rows=picked)]
        if self.library_view == VIEW_FAVORITES:
            picked = [r for r in rows if r.favorited_at]
            picked.sort(key=lambda r: r.name)
            picked.sort(key=lambda r: r.favorited_at, reverse=True)
            return [GroupSection(value="", count=len(picked), rows=picked)]
        if self.library_view == VIEW_NEEDS:
            picked = [r for r in rows if library_health(r)[0] > 0]
            picked.sort(key=lambda r: r.name)
            picked.sort(key=lambda r: library_health(r)[0], reverse=True)
            return [GroupSection(value="", count=len(picked), rows=picked)]
        named: "dict[str, list[JobRow]]" = {}
        for r in sorted(rows, key=lambda r: r.name):
            named.setdefault(r.group, []).append(r)
        groups = sorted(g for g in named if g)
        if not groups:  # 저장된 이름 있는 group 0개 = 헤더 없는 평면(퇴화 불변식)
            flat = [r for r in sorted(rows, key=lambda r: r.name)]
            return [GroupSection(value="", count=len(flat), rows=flat)]
        sections = [
            GroupSection(value=g, count=len(named[g]), rows=named[g]) for g in groups
        ]
        if "" in named:
            # 「그룹 없음」은 명명 group 뒤 1급 구획(§19.6). ``is_untagged`` 로 퇴화 평면
            # 버킷(같은 value="")과 정체성을 가른다 — 표면이 헤더 유무를 여기서 읽는다.
            sections.append(GroupSection(
                value="", count=len(named[""]), rows=named[""], is_untagged=True,
            ))
        return sections

    def library_counts(self) -> "dict[str, int]":
        """보기 탭 라벨의 건수 — **검색 전** 작업 방식 필터까지만 반영한다.

        탭은 라이브러리에 대한 사실이라 검색어에 따라 흔들리면 "여기 몇 건인가"를 잃는다
        (문서 탐색 탭과 같은 규칙). 작업 방식·태그 facet 은 사용자가 켜 둔 **필터 축**이라
        반영한다 — 켜진 칩 밖의 건수를 세면 탭 숫자가 화면과 어긋난다.
        """
        rows = [r for r in self._rows if self._passes_facets(r, exclude_axis="")]
        if self.library_mode != MODE_ALL:
            rows = [r for r in rows if library_mode_of(r) == self.library_mode]
        return {
            VIEW_ALL: len(rows),
            VIEW_RECENT: sum(1 for r in rows if r.last_run_at),
            VIEW_FAVORITES: sum(1 for r in rows if r.favorited_at),
            VIEW_NEEDS: sum(1 for r in rows if library_health(r)[0] > 0),
        }

    def facets(self) -> "list[FacetAxis]":
        """발견된 모든 분류 축 = facet. 각 값에 건수·활성 여부(D10).

        group-by 렌즈 은퇴 뒤로는 축을 섹션으로 쓰는 소비자가 없어 하나도 빼지 않는다.

        건수는 **자기 축을 제외한** 다른 facet 제약 하의 행 수 — 표준 패싯 의미론. 0건 값도
        돌려주고(표현 계층이 회색/억제), 값 순서는 알파벳(D11 보류).

        고아(orphaned) 활성 facet 표면화(confirm-or-alarm): 지금 어떤 행도 지니지 않는
        축/값이 :attr:`active_facets` 에 남아 있으면(그 유일 작업이 삭제·재태깅된 뒤 렌즈가
        복원한 경우) 그 축은 :meth:`axes` 에 안 나와 칩이 하나도 안 그려지는데, 그래도
        :meth:`_passes_facets` 는 여전히 강제해 :meth:`library_sections` 가 전부 비어 보인다 —
        범인 필터가 보이지 않는 채로 실재 작업을 숨기는 위반. 그런 선택을 count=0·
        active=True 인 켜진 칩으로 노출해 사용자가 보고 끌 수 있게 한다(축이 axes() 에 아예
        없으면 FacetAxis 를 새로 만든다).

        비용: 축마다 값별로 전체 행을 재스캔(O(값×행))하지 않고 **행을 한 번만** 순회해
        값별 건수를 집계한다(O(행)). axes() 도 상단에서 1회만 계산한다(FINDING #10).
        """
        result: "list[FacetAxis]" = []
        # 행이 지닌 축 ∪ 활성 facet 축(고아 포함) — 결정적 정렬.
        for axis in sorted(set(self.axes()) | set(self.active_facets)):
            sel = self.active_facets.get(axis, set())
            # 단일 그룹 패스: 자기 축 제외 제약을 통과한 행만 값별 카운터에 가산(FINDING #10).
            counts: "dict[str, int]" = {}
            present: "set[str]" = set()  # 이 축 값을 지닌 모든 행의 값(카운트 0도 노출)
            for r in self._rows:
                v = r.tags.get(axis)
                if not v:
                    continue
                present.add(v)
                if self._passes_facets(r, exclude_axis=axis):
                    counts[v] = counts.get(v, 0) + 1
            # 행 유래 값 ∪ 고아 활성 값(어떤 행도 안 지닌 선택). 고아는 count=0·active=True.
            fvals = [
                FacetValue(value=v, count=counts.get(v, 0), active=v in sel)
                for v in sorted(present | sel)
            ]
            result.append(FacetAxis(axis=axis, values=fvals))
        return result

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
