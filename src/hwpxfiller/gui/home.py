"""홈 — 투트랙 허브 대시보드 + 라우팅(오케스트레이터).

트랙 이원성([[hwpx-filler-scope]], DECISIONS §트랙 이원성): 홈은 단순 목록이 아니라 **두 트랙의
허브 대시보드**다 — 좌: HWPX 문서 생성(Job-앵커·재사용 자산), 우: 즉시 기안(txt, 경량·
render→copy). 상단 요약은 **행동 가능한 실재 데이터만** 남긴다 — 작업·경고·기안 템플릿 수와
최근 실행 작업의 재진입 목록(핸드오프 관통 경고: 없던 기능 발명 금지).

레이어링: 위젯은 얇은 렌더러 — 목록 성형·KPI·선택은 :class:`~hwpxfiller.gui.home_state.HomeViewModel`
(Qt 비의존, 링1)이 소유. **네비게이션 시그널 계약 불변** — HWPX(new/edit/run/delete_job_requested,
아이템 text=작업명)에 txt(new_txt/open_txt_requested)를 더한다. 작업 목록은 계속 QListWidget
(self.list)에 카드로 얹는다(findItems·스모크 계약 보존).
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMenu,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..core.job import JobRegistry
from .compile_badge import badge_level
from .flow_layout import FlowLayout
from .home_state import (
    BADGE_CORRUPT,
    CorruptJobRow,
    FacetValue,
    HomeViewModel,
    JobRow,
    TxtRow,
)
from .style import BASE_QSS, SPACE_MD, SPACE_SM, SPACE_XS, mark
from .view_helpers import (
    ElidedLabel,
    build_empty_state,
    busy_cursor,
    hide_item_text,
    load_home_lens,
    resync_card_item_heights,
    save_home_lens,
    wire_refresh_shortcut,
)

# group-by 축 선택 메뉴의 'flat'(그룹핑 없음) 항목 라벨. 빈 축 키("")로 매핑된다.
_GROUP_NONE_LABEL = "그룹 없음"
# 섹션 헤더·손상 행 등 '작업 아님' 아이템 표식(Qt.UserRole) — findItems(작업명)·더블클릭
# 게이트가 이 아이템을 카드로 오인하지 않게 한다.
_ROLE_SECTION = "section-header"

# 미태깅 섹션의 정체성 토큰 — 접기 상태(_collapsed)·인-플레이스 접기 매핑의 키다. 표시
# 라벨(NO_VALUE_LABEL "(값 없음)")을 그대로 키로 재사용하면, 사용자가 그 문자열을 실제 태그
# 값으로 입력했을 때 명명 섹션과 정체성이 충돌해 마지막 기록이 상대를 덮고(접기가 엉뚱한
# 섹션을 건드림) D12(미태깅 1급)·D8(인-플레이스 접기) 불변식이 깨진다. 표시 문자열과 분리된
# 유일 토큰으로 키잉해 '(값 없음)' 이 유기적 카테고리로도 왕복하게 둔다(정체성 분리).
_UNTAGGED_SECTION_KEY = object()

# 카드 제목의 말줄임 상한(UD-30) — 긴 작업명·파일명이 상태 배지를 밀어내지 않도록
# sizeHint 폭을 눌러 pill 을 온전히 남긴다. 잘리면 전체 이름은 툴팁으로 노출된다.
_CARD_TITLE_MAX = 340
# 대시보드는 최근 실행 이력을 전부 복제하지 않고, 바로 재진입할 상위 작업만 노출한다.
_CONTINUE_RUN_LIMIT = 3


class JobCard(QWidget):
    """HWPX 작업 카드 — 이름 + 상태 배지 + 메타 + 최근 실행 + 카드별 액션(실행/편집/삭제).

    성형된 :class:`JobRow` 와 콜백만 받는다(Job·레지스트리 직접 접근 없음).
    """

    def __init__(self, row: JobRow, on_run, on_edit, on_delete, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(SPACE_XS)  # 카드 행간 통일(UD-33 ② — 3/2/1 산포 → SPACE_XS)

        name_row = QHBoxLayout()
        # 긴 작업명은 말줄임+툴팁(UD-30) — 상태 배지를 밀어내거나 카드 폭을 넘기지 않는다.
        lbl_name = ElidedLabel(row.name, max_width=_CARD_TITLE_MAX)
        mark(lbl_name, "heading", True)
        name_row.addWidget(lbl_name)
        # C2 파생 컴파일 상태 배지(부재·원문·미확인 N개·실행 준비) — 기존 '템플릿 없음'
        # pill 어휘를 확장한다. 문구는 JobRow.compile_badge(seam), 심각도 레벨은
        # compile_badge.badge_level(링1 단일 출처 — 템플릿 관리 배지와 동일 어휘, RC-29).
        # 실행 화면 필드 상태 셀렉터(fb)를 다른 뜻으로 재전용하지 않는다.
        if row.compile_badge:
            lbl_badge = QLabel(row.compile_badge)
            mark(lbl_badge, "pill", badge_level(row.compile_state))
            name_row.addWidget(lbl_badge)
        name_row.addStretch(1)
        root.addLayout(name_row)

        lbl_meta = QLabel(row.meta_line())
        mark(lbl_meta, "muted", True)
        lbl_meta.setWordWrap(True)  # 카드 폭에 맞춰 줄바꿈(가로 넘침 방지)
        root.addWidget(lbl_meta)

        foot = QHBoxLayout()
        lbl_run = QLabel(row.last_run_display)
        mark(lbl_run, "muted", True)
        foot.addWidget(lbl_run)
        foot.addStretch(1)
        btn_run = QPushButton("실행")
        # 실행 진입 판정을 badge_level 단일 술어에 연결(UD-03): danger(부재·손상·오류)는
        # 비활성 — 더블클릭 경로도 같은 게이트(JobRow.is_runnable)를 공유한다. 카드 안 주
        # 액션 강조는 '실행 준비'(ok)에만 준다 — RAW/PARTIAL 은 활성이되 최소 강등해 '지금
        # 실행 준비 vs 아직 손봐야 함'을 시각으로 가른다. 강조는 화면 전역 primary(채움)가
        # 아니라 카드 반복 액션용 보조 등급(emphasis=card, UD-22) — 카드 곱셈으로 primary 가
        # 11개까지 늘어 시선 유도가 소실되던 것을, 화면당 primary 1개 규율로 되돌린다.
        btn_run.setEnabled(row.is_runnable())
        if badge_level(row.compile_state) == "ok":
            mark(btn_run, "emphasis", "card")
        btn_run.clicked.connect(lambda: on_run(row.name))
        btn_edit = QPushButton("작업 편집")
        btn_edit.clicked.connect(lambda: on_edit(row.name))
        btn_del = QPushButton("삭제")
        mark(btn_del, "level", "danger")  # 파괴 버튼 시각 등급(UD-12) — 안전 버튼과 구별
        btn_del.clicked.connect(lambda: on_delete(row.name))
        foot.addWidget(btn_run)
        foot.addWidget(btn_edit)
        foot.addWidget(btn_del)
        root.addLayout(foot)


# 하위호환 별칭(RC-35): 스모크 테스트 등 크로스모듈 인용이 실재하는 공용 표면 —
# 기존 `_JobCard` 임포트는 이 별칭으로 계속 동작한다.
_JobCard = JobCard


class _ContinueRunCard(QWidget):
    """최근 실행 작업 1건 — 실행 화면으로 돌아가는 행동형 행(AD966C89-B)."""

    def __init__(self, row: JobRow, on_continue, parent=None):
        super().__init__(parent)
        root = QHBoxLayout(self)
        root.setContentsMargins(10, SPACE_XS, 10, SPACE_XS)
        root.setSpacing(SPACE_SM)

        lbl_name = ElidedLabel(row.name, max_width=_CARD_TITLE_MAX)
        mark(lbl_name, "heading", True)
        root.addWidget(lbl_name, 1)

        lbl_when = QLabel(row.last_run_display)
        mark(lbl_when, "muted", True)
        root.addWidget(lbl_when)

        btn = QPushButton("이어서 실행")
        mark(btn, "emphasis", "card")
        if not row.is_runnable():
            btn.setToolTip("현재 상태로 바로 실행할 수 없습니다. 누르면 확인할 항목을 안내합니다.")
        btn.clicked.connect(lambda: on_continue(row))
        root.addWidget(btn)


class _SectionHeader(QWidget):
    """group-by 섹션 헤더 — 비선택 리스트 아이템에 얹는 클릭형 접기 컨트롤(JOB_BROWSER_DESIGN D8).

    '▾/▸ 구간라벨 · N건' 전폭 버튼. 클릭하면 ``on_toggle(key)`` 로 접기 상태를 뒤집는다 —
    ``key`` 는 표시 ``value`` 와 별개인 섹션 정체성(미태깅은 :data:`_UNTAGGED_SECTION_KEY`)이라
    '(값 없음)' 라벨이 실제 태그 값과 겹쳐도 접기가 엉뚱한 섹션을 건드리지 않는다. ``key``
    미지정 시 ``value`` 로 폴백(하위호환). 카드 스펙(JobCard)은 건드리지 않는다.
    """

    def __init__(self, value: str, count: int, collapsed: bool, on_toggle,
                 parent=None, *, key=None):
        super().__init__(parent)
        self._value = value
        self._count = count
        skey = value if key is None else key
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.btn = QPushButton(self._label(collapsed))
        mark(self.btn, "section", "header")
        self.btn.clicked.connect(lambda: on_toggle(skey))
        root.addWidget(self.btn)

    def _label(self, collapsed: bool) -> str:
        arrow = "▸" if collapsed else "▾"
        return f"{arrow}  {self._value} · {self._count}건"

    def set_collapsed(self, collapsed: bool) -> None:
        """접힘 화살표만 갱신한다(전체 재렌더 없이 인-플레이스 토글 — 카드 재파싱 없음)."""
        self.btn.setText(self._label(collapsed))


class _FacetChip(QPushButton):
    """facet 값 토글 칩 — on/off 상태(JOB_BROWSER_DESIGN D10). '값 · 건수' 표기.

    0건 값은 비활성(회색)으로 강등하되(막다른 길 차단), 이미 활성이면 해제 가능하게 유지한다.
    """

    def __init__(self, axis: str, fv: FacetValue, on_toggle, parent=None):
        super().__init__(f"{fv.value} · {fv.count}", parent)
        mark(self, "chip", "on" if fv.active else "off")
        # 0건은 비활성 — 단 이미 켜진 칩은 끌 수 있어야 하므로 활성 유지(막다른 길 회피).
        self.setEnabled(fv.count > 0 or fv.active)
        self.clicked.connect(lambda: on_toggle(axis, fv.value))


class _CorruptJobCard(QWidget):
    """손상 ``.job.json`` 행 카드 — 파일명 + '손상됨' 배지 + 오류·경로(RC-05).

    실행/편집은 없지만(파싱 불가라 실행 대상이 아님) 앱 내 해소 동선은 제공한다(UD-44):
    원인 파일을 폴더에서 열어 수동 복구하거나, 확인을 거쳐 삭제할 수 있다 — 정상 카드와
    같은 파괴 어휘([삭제]·confirm_destructive)라 '해소 불가 상시 경보'의 습관화를 막는다.
    """

    def __init__(self, row: CorruptJobRow, on_open=None, on_delete=None, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(SPACE_XS)  # 카드 행간 통일(UD-33 ② — 3/2/1 산포 → SPACE_XS)

        name_row = QHBoxLayout()
        lbl_name = ElidedLabel(row.file_name, max_width=_CARD_TITLE_MAX)  # 파일명 말줄임+툴팁(UD-30)
        mark(lbl_name, "heading", True)
        name_row.addWidget(lbl_name)
        lbl_badge = QLabel(BADGE_CORRUPT)
        # 손상 = 상태 판정 불가(None)와 같은 심각도(danger) — compile_badge 어휘 재사용.
        mark(lbl_badge, "pill", badge_level(None))
        name_row.addWidget(lbl_badge)
        name_row.addStretch(1)
        root.addLayout(name_row)

        lbl_meta = QLabel(f"{row.detail_line()}\n경로: {row.path}")
        mark(lbl_meta, "muted", True)
        lbl_meta.setWordWrap(True)
        root.addWidget(lbl_meta)

        # 해소 동선(UD-44) — 콜백은 손상 파일 경로를 나른다(이름 없음 → 경로 식별).
        foot = QHBoxLayout()
        foot.addStretch(1)
        btn_open = QPushButton("폴더 열기")
        if on_open is not None:
            btn_open.clicked.connect(lambda: on_open(row.path))
        btn_del = QPushButton("삭제")
        mark(btn_del, "level", "danger")  # 파괴 버튼 시각 등급(정상 카드와 동일 어휘)
        if on_delete is not None:
            btn_del.clicked.connect(lambda: on_delete(row.path))
        foot.addWidget(btn_open)
        foot.addWidget(btn_del)
        root.addLayout(foot)


class _TxtCard(QWidget):
    """txt 기안 템플릿 카드 — 이름 + 필드 수 + [기안 열기]."""

    def __init__(self, row: TxtRow, on_open, parent=None):
        super().__init__(parent)
        root = QHBoxLayout(self)
        root.setContentsMargins(10, 7, 10, 7)
        box = QVBoxLayout()
        box.setSpacing(SPACE_XS)  # 카드 행간 통일(UD-33 ②)
        lbl_name = ElidedLabel(f"{row.name}.txt", max_width=_CARD_TITLE_MAX)  # 제목 말줄임+툴팁(UD-30)
        # 카드 제목 타이포 통일(UD-33 ③): 인라인 스타일시트로 font-weight:600 만 주어 JobCard
        # heading(15/700)과 분열하던 것을 같은 heading 위계로 수렴(인라인 탈출구 제거).
        mark(lbl_name, "heading", True)
        lbl_fields = QLabel(f"필드 {row.field_count}개")
        mark(lbl_fields, "muted", True)
        box.addWidget(lbl_name)
        box.addWidget(lbl_fields)
        root.addLayout(box)
        root.addStretch(1)
        btn_open = QPushButton("기안 작성")
        # 카드 반복 주 액션은 보조 등급(UD-22): txt 카드마다 반복돼 화면 전역 primary 로 두면
        # 홈 뷰포트의 강조가 곱절 — emphasis=card 로 강등(화면당 primary 1개 규율).
        mark(btn_open, "emphasis", "card")
        btn_open.setToolTip(f"{row.name}.txt 템플릿을 선택해 기안을 시작합니다.")
        btn_open.clicked.connect(lambda: on_open(row.name))
        root.addWidget(btn_open)


class JobListHome(QWidget):
    """투트랙 허브 대시보드. :class:`HomeViewModel` 을 렌더하고 액션을 시그널로 방출한다.

    셸 페이지(ST-01, SHELL_DESIGN §2): 최상위 창이 아니라 :class:`~hwpxfiller.gui.shell.ShellWindow`
    의 스택에 임베드된다 — 창 크롬(지오메트리 지속·closeEvent)은 셸이 소유하고, 홈은
    시그널 계약을 든 렌더러로 남는다. 독립 생성(테스트)도 계속 동작한다.
    """

    # HWPX 트랙(불변 계약)
    new_job_requested = Signal()
    edit_job_requested = Signal(str)
    run_job_requested = Signal(str)
    delete_job_requested = Signal(str)
    # txt 트랙(신규)
    new_txt_requested = Signal()
    open_txt_requested = Signal(str)  # 템플릿 이름
    # 데이터 풀 관리(J1) — 앱 컨트롤러(app.py)가 직결 배선한다.
    manage_pool_requested = Signal()
    # 여러 작업 일괄 실행(J2 매트릭스).
    matrix_run_requested = Signal()
    # 매핑 프로파일 관리(J3 — 공유 매핑 프로파일 계보). 시그널명은 코드 심볼로 유지.
    manage_vocab_requested = Signal()
    # 템플릿 관리 워크숍(C5) — 헤더 [템플릿 관리] 버튼이 방출(RC-04 소생 진입점).
    manage_templates_requested = Signal()
    # 손상 작업 파일 해소 동선(UD-44) — 앱 컨트롤러가 폴더 열기·확인 삭제로 처리.
    # 손상 행은 이름이 없어(파싱 불가) 인자는 파일 경로다(run_job_requested 의 작업명 계약과 별개).
    reveal_corrupt_requested = Signal(str)
    delete_corrupt_requested = Signal(str)

    def __init__(self, registry: JobRegistry, text_registry=None, parent=None,
                 pool_registry=None):
        super().__init__(parent)
        self.registry = registry
        # 기본 txt 레지스트리(주입 없으면 표준 루트) — 대시보드 txt 트랙.
        if text_registry is None:
            from ..core.text_registry import TextTemplateRegistry, default_text_templates_dir
            text_registry = TextTemplateRegistry(default_text_templates_dir())
        self.text_registry = text_registry
        # 기본 데이터 풀 레지스트리(durable 참조) — 대시보드 KPI + 관리 진입.
        if pool_registry is None:
            from ..core.dataset_pool import DatasetPoolRegistry, default_dataset_pool_dir
            pool_registry = DatasetPoolRegistry(default_dataset_pool_dir())
        self.pool_registry = pool_registry
        self.vm = HomeViewModel(registry, text_registry, pool_registry)

        # 창 제목은 유지(페이지 정체·테스트 호환) — 지오메트리 지속은 셸("shell" 키)이
        # 소유한다(SHELL_DESIGN D7: 구 "home" 키는 읽기·쓰기 중단, INI 잔존 무해).
        self.setWindowTitle("HWPX Filler — 대시보드")
        self.setStyleSheet(BASE_QSS)
        root = QVBoxLayout(self)

        # ---- 헤더 ----
        header = QHBoxLayout()
        title = QLabel("대시보드")
        mark(title, "heading", True)
        sub = QLabel("내 작업 보관함")
        mark(sub, "muted", True)
        # 부제는 제목 인접(UD-36) — 헤더 버튼 뒤 최우단 표류를 해소해 '무엇의 라벨인지'를
        # 위치로 말한다. 액션 버튼은 stretch 뒤 우측에 모은다.
        header.addWidget(title)
        header.addWidget(sub)
        header.addStretch(1)
        # 니모닉(&, ST-12): Alt+글자로 키보드 접근. Alt+M 템플릿·P 풀·V 매핑 프로파일.
        # 개념 툴팁(ST-26): 전문 용어(누름틀·데이터 풀·매핑 프로파일)를 한 줄로 설명한다.
        self.btn_templates = QPushButton("템플릿 관리(&M)")
        self.btn_templates.setToolTip(
            "누름틀 템플릿(.hwpx)의 컴파일 상태를 보고 스키마 추출·누름틀 변환·검토를 합니다."
        )
        self.btn_templates.clicked.connect(self.manage_templates_requested)
        self.btn_pool = QPushButton("데이터 관리(&P)")
        self.btn_pool.setToolTip(
            "재사용할 데이터 참조(엑셀/CSV 경로·나라장터 쿼리·조립 파이프라인)를 "
            "등록하고 관리합니다."
        )
        self.btn_pool.clicked.connect(self.manage_pool_requested)
        self.btn_vocab = QPushButton("매핑 프로파일 관리(&V)")
        self.btn_vocab.setToolTip(
            "여러 작업이 공유하는 필드↔소스 매핑 베이스를 저작·재사용합니다."
        )
        self.btn_vocab.clicked.connect(self.manage_vocab_requested)
        header.addWidget(self.btn_templates)
        header.addWidget(self.btn_pool)
        header.addWidget(self.btn_vocab)
        root.addLayout(header)

        # ---- KPI 타일(내용은 _render 가 채운다) ----
        self.kpi_row = QHBoxLayout()
        self.kpi_row.setSpacing(10)
        root.addLayout(self.kpi_row)

        # 최근 실행은 읽기 전용 KPI가 아니라 해당 실행 화면으로 돌아가는 행동형 목록이다.
        self.continue_panel = self._panel("이어서 실행")
        continue_box = self.continue_panel.layout()
        self.continue_list = QListWidget()
        self.continue_list.setObjectName("jobList")
        self.continue_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        continue_box.addWidget(self.continue_list)
        root.addWidget(self.continue_panel)

        # ---- 투트랙 ----
        tracks = QHBoxLayout()
        tracks.setSpacing(14)

        # 좌: HWPX
        hwpx = self._panel("HWPX 문서 생성")
        hp = hwpx.layout()
        hhead = QHBoxLayout()
        self.btn_new = QPushButton("＋ 새 문서 작업(&N)")  # Alt+N(ST-12)
        mark(self.btn_new, "primary", True)
        self.btn_new.clicked.connect(self.new_job_requested)
        self.btn_matrix = QPushButton("여러 작업 일괄 실행")
        self.btn_matrix.clicked.connect(self.matrix_run_requested)
        lbl_hwpx_hint = QLabel("누름틀 템플릿 + 매핑 → .hwpx 생성")
        mark(lbl_hwpx_hint, "muted", True)  # 부연 라벨 위계 통일(UD-36) — 화면 전체 muted
        # group-by 렌즈 선택(D4) — 발견된 축으로 묶기. 축이 없으면(태그 0) _render 가 숨겨
        # 오늘과 동일한 평면 목록으로 강등한다(퇴화-코퍼스 불변식). 메뉴는 _render 가 채운다.
        self.btn_groupby = QPushButton()
        self.btn_groupby.setToolTip("작업을 어느 분류 축으로 묶을지 고릅니다(그룹 없음=평면 목록).")
        self._groupby_menu = QMenu(self.btn_groupby)
        self.btn_groupby.setMenu(self._groupby_menu)
        # 메뉴가 열릴 때마다 체크 상태를 새로 그린다(RC — 활성 축 재클릭이 set_group_by
        # 조기반환으로 재렌더를 안 태워 체크가 사라지던 거짓말 방지). 재구성은 멱등하다.
        self._groupby_menu.aboutToShow.connect(self._render_groupby_button)
        hhead.addWidget(lbl_hwpx_hint)
        hhead.addWidget(self.btn_groupby)
        hhead.addStretch(1)
        hhead.addWidget(self.btn_matrix)
        hhead.addWidget(self.btn_new)
        hp.addLayout(hhead)
        # facet 칩바(D10) — group-by 외 축들이 여기 토글 칩으로. _render 가 채우고 표시/숨김한다.
        self.facet_bar = QWidget()
        self._facet_flow = FlowLayout(self.facet_bar, margin=0, spacing=SPACE_SM)
        hp.addWidget(self.facet_bar)
        self.stack = QStackedWidget()
        self.list = QListWidget()
        self.list.setObjectName("jobList")
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)  # 카드가 뷰포트 폭에 맞음
        # 더블클릭 실행 진입 — 버튼 경로와 같은 게이트를 공유한다(UD-03). 무조건 배선하던
        # 과거는 손상 카드(비작업)를 조용한 크래시로, 실행 불가 카드를 무게이트 우회로 보냈다.
        self.list.itemDoubleClicked.connect(self._on_job_double_click)
        self.stack.addWidget(self.list)                    # 0 = 목록
        self.stack.addWidget(self._build_empty_state())    # 1 = 빈 상태(코퍼스 자체가 빔)
        # 2 = 필터-빈 상태 — 코퍼스는 비어 있지 않은데 활성 facet 이 전부 가렸을 때(RC).
        # 조용한 백지 대신 원인(필터)과 해소 동선을 시끄럽게 고지한다. 칩바는 스택 위에
        # 남아 있으므로 CTA 는 '필터 해제'(활성 제약 일괄 해제) 하나로 충분하다.
        filtered_empty = build_empty_state(
            "필터에 맞는 작업이 없습니다",
            "지금 켜진 필터가 모든 작업을 가렸습니다. 위 칩바에서 켜진 필터를 끄거나 "
            "'필터 해제'로 되돌리세요.",
            cta_text="필터 해제",
            on_cta=self._clear_facets,
        )
        self.btn_filtered_clear = filtered_empty.cta  # 빈 상태 CTA seam(테스트)
        self.stack.addWidget(filtered_empty)               # 2 = 필터-빈 상태
        hp.addWidget(self.stack, 1)
        tracks.addWidget(hwpx, 3)

        # 우: txt
        txt = self._panel("즉시 기안")
        tp = txt.layout()
        thead = QHBoxLayout()
        self.btn_new_txt = QPushButton("＋ 새 기안(&T)")  # Alt+T(ST-12)
        mark(self.btn_new_txt, "primary", True)
        self.btn_new_txt.clicked.connect(self.new_txt_requested)
        lbl_txt_hint = QLabel("기안 템플릿으로 문안 미리보기")
        mark(lbl_txt_hint, "muted", True)  # 부연 라벨 위계 통일(UD-36)
        thead.addWidget(lbl_txt_hint)
        thead.addStretch(1)
        thead.addWidget(self.btn_new_txt)
        tp.addLayout(thead)
        self.txt_list = QListWidget()
        self.txt_list.setObjectName("jobList")
        self.txt_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.txt_list.itemDoubleClicked.connect(self._emit_txt_for_item)
        # 즉시 기안 목록 빈 상태(UD-17) — 좌측 HWPX 트랙과 대칭으로, 0건일 때 테두리만 있는
        # 백지 대신 상태 재진술 + CTA(＋ 새 기안)를 공용 빈 상태 뷰로 노출한다.
        self.txt_stack = QStackedWidget()
        self.txt_stack.addWidget(self.txt_list)                     # 0 = 목록
        txt_empty = build_empty_state(
            "기안 템플릿이 없습니다",
            "자주 쓰는 문안을 기안 템플릿으로 만들어 데이터로 즉시 채워 복사·저장하세요.",
            cta_text="＋ 새 기안",
            on_cta=self.new_txt_requested,
        )
        self.btn_txt_empty_new = txt_empty.cta
        self.txt_stack.addWidget(txt_empty)                         # 1 = 빈 상태
        tp.addWidget(self.txt_stack, 1)
        tracks.addWidget(txt, 2)

        root.addLayout(tracks, 1)

        # 렌즈 복원(D4) — 지속된 group-by/facet 을 VM 에 주입한다. 구독 전이라 통지는 무해.
        self._collapsed: "set" = set()  # 접힌 섹션의 정체성 키(값 문자열 또는 미태깅 토큰)
        # 인-플레이스 접기용 매핑(RC) — group 값 → 멤버 아이템들 / 섹션 헤더 위젯. _render 가
        # 매 렌더마다 새로 채우고, _toggle_section 이 이걸로 전체 재렌더 없이 숨김/화살표만 뒤집는다.
        self._section_items: "dict" = {}       # 정체성 키 → 멤버 아이템들
        self._section_headers: "dict" = {}      # 정체성 키 → 섹션 헤더 위젯
        gb, facets = load_home_lens()
        if gb is not None:  # None=미저장(씨앗 렌즈 유지), ""=사용자가 flat 명시 선택
            self.vm.set_group_by(gb)
        if facets:
            self.vm.set_facets(facets)

        self.vm.subscribe(self._render)
        self._render()
        wire_refresh_shortcut(self)  # F5 → 목록 새로고침(ST-12)

    # ------------------------------------------------------------- 빌더
    @staticmethod
    def _panel(title: str) -> QFrame:
        frame = QFrame()
        frame.setProperty("card", True)
        box = QVBoxLayout(frame)
        # 카드 여백을 space 토큰으로 수렴(UD-33 ②): 패널(14,12)·KPI 타일(13,11)의 ±1px
        # 산포를 단일 SPACE_MD 로 정규화(예약 space 스케일 실배선 — V2 가 미룬 것).
        box.setContentsMargins(SPACE_MD, SPACE_MD, SPACE_MD, SPACE_MD)
        lbl = QLabel(title)
        mark(lbl, "heading", True)
        box.addWidget(lbl)
        return frame

    def _build_empty_state(self) -> QWidget:
        panel = QWidget()
        box = QVBoxLayout(panel)
        box.addStretch(2)
        lbl = QLabel("저장된 작업이 없습니다")
        mark(lbl, "heading", True)
        lbl.setAlignment(Qt.AlignCenter)
        sub = QLabel("템플릿과 매핑을 묶어 첫 작업을 만드세요.\n데이터·행은 실행할 때 고릅니다.")
        mark(sub, "muted", True)
        sub.setAlignment(Qt.AlignCenter)
        self.btn_empty_new = QPushButton("＋ 새 문서 작업")
        mark(self.btn_empty_new, "primary", True)
        self.btn_empty_new.clicked.connect(self.new_job_requested)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.btn_empty_new)
        row.addStretch(1)
        box.addWidget(lbl)
        box.addWidget(sub)
        box.addLayout(row)
        box.addStretch(3)
        return panel

    def _kpi_tile(self, value: str, label: str, warn: bool = False) -> QFrame:
        tile = QFrame()
        tile.setProperty("card", True)
        box = QVBoxLayout(tile)
        box.setContentsMargins(SPACE_MD, SPACE_MD, SPACE_MD, SPACE_MD)  # 패널과 동일 여백(UD-33 ②)
        box.setSpacing(SPACE_XS)
        # KPI 값은 말줄임+툴팁(UD-30) — 긴 값이 타일 폭을 넘겨 우측 타일을 압착·화면
        # 밖으로 밀어내지 않게 한다(타일은 동일 폭 배분).
        v = ElidedLabel(value)
        mark(v, "kpi", "value")
        if warn:
            mark(v, "level", "warn")
        lbl = QLabel(label)
        mark(lbl, "kpi", "label")
        box.addWidget(v)
        box.addWidget(lbl)
        return tile

    # ------------------------------------------------------------- 렌더
    def refresh(self) -> None:
        """배선(app.py)이 저장·삭제·실행 후 호출 → 뷰모델 재적재 → _render 통지."""
        with busy_cursor():  # 템플릿 전수 재파싱(compile 상태) 동안 대기 커서(ST-16)
            self.vm.refresh()

    def _render(self) -> None:
        # KPI
        while self.kpi_row.count():
            item = self.kpi_row.takeAt(0)
            w = item.widget() if item is not None else None
            if w is not None:
                w.deleteLater()
        k = self.vm.kpi()
        # 타일을 동일 폭(stretch=1)으로 배분한다(UD-30). 등록 데이터 수는 다음 행동을 만들지
        # 못하는 허영 지표라 제거하고(AD966C89-A), 최근 실행은 아래 행동형 목록으로 옮긴다.
        self.kpi_row.addWidget(self._kpi_tile(str(k.job_count), "저장된 작업 · HWPX"), 1)
        self.kpi_row.addWidget(
            self._kpi_tile(str(k.missing_template_count), "템플릿 없는 작업", warn=k.missing_template_count > 0), 1
        )
        self.kpi_row.addWidget(self._kpi_tile(str(k.txt_template_count), "기안 템플릿 · txt"), 1)

        # 최신 실행 순으로 최대 3건. 실행 가능 여부는 클릭 시 기존 단일 게이트를 통과시켜,
        # 템플릿이 사라진 작업을 조용히 열거나 무시하지 않고 원인을 경고한다.
        self.continue_list.clear()
        recent_rows = sorted(
            (row for row in self.vm.rows() if row.last_run_at),
            key=lambda row: row.last_run_at,
            reverse=True,
        )[:_CONTINUE_RUN_LIMIT]
        for row in recent_rows:
            self.continue_list.addItem(row.name)
            item = self.continue_list.item(self.continue_list.count() - 1)
            hide_item_text(item)
            item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
            card = _ContinueRunCard(row, self._request_run)
            item.setSizeHint(card.sizeHint())
            self.continue_list.setItemWidget(item, card)
        if recent_rows:
            # QListWidget의 Expanding 기본 정책이 1~3개 행 아래에 큰 공백을 만들지 않도록
            # 실제 카드 높이 합만 차지한다. 항목 수 상한이 3이라 스크롤도 생기지 않는다.
            content_height = sum(
                self.continue_list.item(i).sizeHint().height()
                for i in range(self.continue_list.count())
            )
            self.continue_list.setFixedHeight(content_height + 2 * self.continue_list.frameWidth())
        self.continue_panel.setVisible(bool(recent_rows))

        # HWPX 작업 목록 — group-by 접이식 섹션 + facet(JOB_BROWSER_DESIGN §4).
        # 카드는 계속 self.list(QListWidget)에 얹는다(findItems·스모크 계약 보존, home docstring).
        self._render_groupby_button()
        self._render_facet_bar()
        prev = self.vm.selected_name
        self.list.blockSignals(True)
        self.list.clear()

        sections = self.vm.grouped_rows()
        # 인-플레이스 접기 매핑을 매 렌더 새로 채운다(구 아이템은 clear 로 사라짐).
        self._section_items = {}
        self._section_headers = {}
        # 헤더는 구분할 그룹이 2개 이상이거나 활성 facet 이 있을 때(GroupSection 계약: 섹션 ≤1
        # 이고 활성 facet 도 없을 때만 억제). group-by 로 단일 그룹만 남아도 활성 facet 이 있으면
        # '· N건' 헤더가 지금 무엇으로 좁혀졌는지 말해야 한다(퇴화-코퍼스 불변식은 태그 0 경로만).
        show_headers = len(sections) > 1 or bool(self.vm.active_facets)
        total_rows = 0  # 실제로 렌더된 카드 행 수(facet 이 전부 가렸는지 판정 — 필터-빈 게이트)
        for sec in sections:
            collapsed = False
            members: "list" = []
            # 섹션 정체성 키 — 미태깅은 표시 라벨과 별개인 유일 토큰(정체성 충돌 방지).
            skey = _UNTAGGED_SECTION_KEY if sec.is_untagged else sec.value
            if show_headers:
                collapsed = skey in self._collapsed
                self.list.addItem("")  # 헤더 아이템 — text 빈 값(findItems 작업명 계약과 무충돌)
                hitem = self.list.item(self.list.count() - 1)
                hitem.setData(Qt.UserRole, _ROLE_SECTION)
                # 손상행 선례(L445)와 같은 비선택 플래그 — 헤더는 실행/선택 대상이 아니다.
                hitem.setFlags(hitem.flags() & ~Qt.ItemIsSelectable)
                header = _SectionHeader(
                    sec.value, sec.count, collapsed, self._toggle_section, key=skey
                )
                hitem.setSizeHint(header.sizeHint())
                self.list.setItemWidget(hitem, header)
                self._section_headers[skey] = header
            for row in sec.rows:
                total_rows += 1
                self.list.addItem(row.name)
                item = self.list.item(self.list.count() - 1)
                members.append(item)
                hide_item_text(item)  # 이름은 아이템 text(계약), 표시는 카드(UD-33 공용 이디엄)
                if collapsed:
                    item.setHidden(True)  # 접힌 섹션 멤버 숨김(계약 아이템은 살아 있음)
                card = JobCard(
                    row,
                    on_run=self.run_job_requested.emit,
                    on_edit=self.edit_job_requested.emit,
                    on_delete=self.delete_job_requested.emit,
                )
                item.setSizeHint(card.sizeHint())
                self.list.setItemWidget(item, card)
            self._section_items[skey] = members  # 인-플레이스 접기용 멤버 기억(정체성 키)
        # 손상 .job.json 행(RC-05) — 정상 작업 뒤에 '손상됨' 배지 카드로 시끄럽게 노출.
        # 아이템 text 는 파일명(이름을 알 수 없음 — findItems 작업명 계약과 충돌 없음).
        corrupt_rows = self.vm.corrupt_rows()
        for crow in corrupt_rows:
            self.list.addItem(crow.file_name)
            item = self.list.item(self.list.count() - 1)
            hide_item_text(item)
            # 손상 행은 실행 대상이 아니다(UD-03 증상 3) — 선택 하이라이트로 실행 대상처럼
            # 보이지 않게 선택 플래그를 내린다. 더블클릭도 _on_job_double_click 가 무작업 처리.
            item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
            card = _CorruptJobCard(
                crow,
                on_open=self.reveal_corrupt_requested.emit,
                on_delete=self.delete_corrupt_requested.emit,
            )
            item.setSizeHint(card.sizeHint())
            self.list.setItemWidget(item, card)
        # 스택 우선순위(RC): 코퍼스 자체가 빔(is_empty) → 1; 코퍼스는 있으나 렌더된 행이 0
        # (facet 이 전부 가림) → 2 필터-빈; 그 외 → 0 목록. 손상 카드도 '렌더된 행'이라 하나라도
        # 있으면 목록을 보인다(조용한 백지 금지).
        if self.vm.is_empty():
            self.stack.setCurrentIndex(1)
        elif total_rows == 0 and not corrupt_rows:
            self.stack.setCurrentIndex(2)
        else:
            self.stack.setCurrentIndex(0)
        # 선택 하이라이트는 실제로 보이는(숨김 아님)·선택 가능한 행에만 복원한다(RC) — 접힘/
        # facet 으로 사라진 행을 가리키는 유령 선택을 남기지 않는다. VM 의 selected_name 은
        # 건드리지 않으므로 섹션을 다시 펴면 하이라이트가 돌아올 수 있다.
        self.list.setCurrentItem(None)
        if prev is not None:
            for it in self.list.findItems(prev, Qt.MatchExactly):
                if not it.isHidden() and bool(it.flags() & Qt.ItemIsSelectable):
                    self.list.setCurrentItem(it)
                    break
        self.list.blockSignals(False)

        # txt 기안 템플릿 목록
        self.txt_list.clear()
        txt_rows = self.vm.txt_rows()
        for trow in txt_rows:
            self.txt_list.addItem(trow.name)
            item = self.txt_list.item(self.txt_list.count() - 1)
            hide_item_text(item)
            card = _TxtCard(trow, on_open=self.open_txt_requested.emit)
            item.setSizeHint(card.sizeHint())
            self.txt_list.setItemWidget(item, card)
        self.txt_stack.setCurrentIndex(1 if not txt_rows else 0)  # 0건 → 빈 상태(UD-17)

        # 폭/높이 동기화는 레이아웃이 자리잡은 뒤로 미룬다(생성 시 viewport 폭이 아직 미확정).
        self._sync_item_widths()
        QTimer.singleShot(0, self._sync_item_widths)

    # --------------------------------------------------- 작업 브라우저(group/facet)
    def _render_groupby_button(self) -> None:
        """group-by 메뉴를 발견된 축으로 채운다. 축이 없으면(태그 0) 버튼을 숨겨 퇴화 평면."""
        axes = self.vm.axes()
        self.btn_groupby.setVisible(bool(axes))
        self._groupby_menu.clear()
        if not axes:
            return
        eff = self.vm.effective_group_by()
        self.btn_groupby.setText(f"그룹: {eff or _GROUP_NONE_LABEL} ▾")
        act_none = self._groupby_menu.addAction(_GROUP_NONE_LABEL)
        act_none.setCheckable(True)
        act_none.setChecked(eff == "")
        act_none.triggered.connect(lambda checked=False: self._set_group_by(""))
        for axis in axes:
            act = self._groupby_menu.addAction(axis)
            act.setCheckable(True)
            act.setChecked(axis == eff)
            act.triggered.connect(lambda checked=False, a=axis: self._set_group_by(a))

    def _render_facet_bar(self) -> None:
        """facet 칩바 재구성 — group-by 외 축의 값들을 토글 칩으로(D10). 없으면 바를 숨긴다."""
        while self._facet_flow.count():  # 기존 칩 제거
            it = self._facet_flow.takeAt(0)
            w = it.widget() if it is not None else None
            if w is not None:
                w.deleteLater()
        facets = self.vm.facets()
        has_active = bool(self.vm.active_facets)
        self.facet_bar.setVisible(bool(facets) or has_active)
        if not facets and not has_active:
            return
        for fa in facets:
            for fv in fa.values:
                self._facet_flow.addWidget(_FacetChip(fa.axis, fv, self._toggle_facet))
        if has_active:  # 활성 제약 일괄 해제(D10) — 개별 해제는 켜진 칩 재클릭
            btn_clear = QPushButton("필터 해제")
            btn_clear.clicked.connect(self._clear_facets)
            self._facet_flow.addWidget(btn_clear)

    def _persist_lens(self) -> None:
        """현재 렌즈(group-by+facet)를 INI 에 저장(D4). 링1 VM 은 지속을 모른다 — 위젯 몫."""
        save_home_lens(self.vm.active_group_by, self.vm.active_facets)

    def _set_group_by(self, axis: str) -> None:
        self._collapsed.clear()  # 축이 바뀌면 접힘 상태는 무의미(구 값 기준)
        self.vm.set_group_by(axis)  # 통지 → _render 재구성
        self._persist_lens()

    def _toggle_facet(self, axis: str, value: str) -> None:
        self.vm.toggle_facet(axis, value)  # 통지 → _render 재구성
        self._persist_lens()

    def _clear_facets(self) -> None:
        self.vm.clear_facets()  # 통지 → _render 재구성
        self._persist_lens()

    def _toggle_section(self, key) -> None:
        """섹션 접기/펴기 — 전체 재렌더 없이 그 섹션 멤버의 숨김·헤더 화살표만 인-플레이스로
        뒤집는다(카드 재파싱 없어 값쌈 — 리스트 clear/재빌드·칩바·메뉴 재구성 회피, RC).

        ``key`` 는 섹션 정체성(명명 섹션은 값 문자열, 미태깅은 :data:`_UNTAGGED_SECTION_KEY`)
        이다 — 표시 라벨('(값 없음)')이 실제 태그 값과 겹쳐도 서로의 접기를 침범하지 않는다.
        VM 상태·selected_name 은 불변이다. 다만 접으면 선택이 숨겨진 행을 가리킬 수 있으므로
        보이는 선택 불변식(유령 하이라이트 금지)을 여기서도 지킨다.
        """
        if key in self._collapsed:
            self._collapsed.discard(key)
            collapsed = False
        else:
            self._collapsed.add(key)
            collapsed = True
        for item in self._section_items.get(key, []):
            item.setHidden(collapsed)
        header = self._section_headers.get(key)
        if header is not None:
            header.set_collapsed(collapsed)
        cur = self.list.currentItem()
        if cur is not None and cur.isHidden():
            self.list.setCurrentItem(None)  # 접혀 사라진 선택은 유령 — 하이라이트 제거

    def _sync_item_widths(self) -> None:
        """카드 폭을 뷰포트에 고정한 뒤 그 폭에서의 높이로 아이템을 잡는다(UD-11 공용 헬퍼).

        미폴리시 시점 sizeHint 박제로 액션 버튼이 압착되던 함정의 지연 재동기 — 홈 로컬
        구현이던 것을 :func:`~hwpxfiller.gui.view_helpers.resync_card_item_heights` 로
        추출해 풀·프로파일·템플릿 관리 패널과 공유한다.
        """
        resync_card_item_heights(self.list, self.txt_list)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_item_widths()

    # ------------------------------------------------------------- 선택/보조
    def selected_job_name(self) -> "str | None":
        it = self.list.currentItem()
        return it.text() if it is not None else None

    def _job_row_by_name(self, name: str) -> "JobRow | None":
        """이름으로 성형 행을 찾는다(더블클릭 게이트가 상태를 조회할 이음새)."""
        for r in self.vm.rows():
            if r.name == name:
                return r
        return None

    def _on_job_double_click(self, item) -> None:
        """더블클릭 실행 진입 — 버튼 [실행]과 같은 게이트(is_runnable)를 공유한다(UD-03).

        손상 행(비작업)은 무작업으로 무시하고(카드 자체 [폴더 열기]/[삭제]로 해소),
        실행 불가 상태(danger)는 조용한 no-op/크래시 대신 사유를 시끄럽게 고지한다.
        정상·실행 가능 행만 run_job_requested(작업명)를 방출한다 — 손상 행 파일명을
        방출하던 계약 위반(seam 은 작업명)도 함께 막힌다.
        """
        row = self._job_row_by_name(item.text())
        if row is None:
            return  # 손상/비작업 행 — 실행 대상 아님
        self._request_run(row)

    def _request_run(self, row: JobRow) -> None:
        """카드·최근 실행 목록이 공유하는 실행 진입 게이트(confirm-or-alarm)."""
        if not row.is_runnable():
            self._warn_not_runnable(row)
            return
        self.run_job_requested.emit(row.name)

    def _warn_not_runnable(self, row: "JobRow") -> None:
        """실행 불가 카드 진입 시 시끄러운 사유 고지(UD-03) — stderr 침묵 금지."""
        from PySide6.QtWidgets import QMessageBox

        QMessageBox.information(
            self, "실행할 수 없습니다",
            f"'{row.name}' 은(는) 지금 실행할 수 없습니다 — {row.compile_badge or '템플릿 미설정'}.\n"
            "작업을 수정해 템플릿을 연결하거나 복구한 뒤 실행하세요.",
        )

    def _emit_txt_for_item(self, item) -> None:
        if item is not None:
            self.open_txt_requested.emit(item.text())
