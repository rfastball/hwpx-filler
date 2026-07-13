"""GUI 진입점 — 작업(Job) 목록 홈을 기동하고 능력들을 라우팅한다.

    python -m hwpxfiller.gui.app

홈(:class:`~hwpxfiller.gui.home.JobListHome`)이 오케스트레이터다: 새 작업은 에디터
(:class:`~hwpxfiller.gui.job_editor.JobEditorWizard`)로, 실행은 실행 화면
(:class:`~hwpxfiller.gui.run_view.RunView`)으로 보낸다. 자식 창의 수명은 여기서 소유한다
(Qt GC 방지). 초기엔 자식 창 — 임베드(QStackedWidget)는 후속 리팩터.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # 런타임 Qt 임포트는 main/헬퍼 안에서만(모듈 임포트 경량 유지)
    from PySide6.QtCore import QTranslator


def install_korean_translator(app) -> "QTranslator | None":
    """Qt 표준 문자열(qtbase — 위저드 Back/Next/Cancel, 확인 &Yes/&No)을 한국어로(RC-27).

    PySide6 는 번역을 자동 로드하지 않는다 — 부트스트랩에서 ``qtbase_ko`` 를 명시
    설치한다. 실패 시 조용한 폴백 금지: stderr 로 시끄럽게 알리고 ``None`` 을 돌려준다.
    성공 시 설치된 :class:`QTranslator` 를 돌려줘 테스트가 공유 QApplication 에서
    ``removeTranslator`` 로 원복할 수 있게 한다.

    hwpxdiff(app.py)도 같은 헬퍼 사본을 소유한다 — 제품 간 임포트 금지 규칙
    (tests/test_architecture.py) 때문에 공유하지 않는다.
    """
    from PySide6.QtCore import QLibraryInfo, QTranslator

    translations_dir = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    translator = QTranslator(app)
    if translator.load("qtbase_ko", translations_dir) and app.installTranslator(translator):
        return translator
    print(
        "경고: Qt 한국어 번역(qtbase_ko)을 설치하지 못했습니다 — 표준 버튼이 "
        f"영어로 표시됩니다. (탐색 경로: {translations_dir})",
        file=sys.stderr,
    )
    return None


class AppController:
    """홈 + 자식 창들의 배선·수명 소유자. QApplication 과 분리해 테스트 가능."""

    def __init__(self, registry):
        from .home import JobListHome
        from .shell import ShellWindow

        from ..core.mapping_base import MappingBaseRegistry, default_mapping_bases_dir

        self.registry = registry
        # 단일창 셸(ST-01, SHELL_DESIGN): 홈은 페이지로 즉시 임베드(허브 = 기저선),
        # 능력 페이지들은 라우트별 지연 factory 로 임베드한다(스테이지 순차 이관).
        self.shell = ShellWindow()
        self.shell.register_static("home", "대시보드", "작업 보관함 — 두 트랙 허브")
        self.home = JobListHome(registry)
        self.shell.activate("home", factory=lambda: self.home)
        # 레일 클릭 → 라우트 요청. 라우트 표는 스테이지 이관에 따라 자란다 — 미배선
        # 키는 조용한 no-op 대신 KeyError(RC-04: 배선 어긋남은 기동 즉시 시끄럽게).
        self._nav_routes: "dict[str, object]" = {"home": self.shell.go_home}
        self.shell.nav_requested.connect(self._on_nav)
        # 공유 매핑 프로파일 레지스트리(J3) — 관리 화면·에디터가 공유(1회 저작 후 재사용).
        self.base_registry = MappingBaseRegistry(default_mapping_bases_dir())
        self._children: "list[object]" = []  # Qt GC 방지 — 자식 창 참조 유지
        # 능력별 싱글턴(ST-10): 같은 관리 창·같은 작업 에디터가 이미 열려 있으면 새로
        # 만들지 않고 앞으로 가져와 중복 창 누적·동일 작업 다중 편집(last-save-wins)을 막는다.
        self._singletons: "dict[str, object]" = {}

        self.home.new_job_requested.connect(self._open_editor_new)
        self.home.edit_job_requested.connect(self._open_editor_edit)
        self.home.run_job_requested.connect(self._open_run)
        self.home.delete_job_requested.connect(self._delete_job)
        # 손상 작업 파일 해소 동선(UD-44) — 폴더 열기 / 확인 경유 삭제.
        self.home.reveal_corrupt_requested.connect(self._reveal_corrupt)
        self.home.delete_corrupt_requested.connect(self._delete_corrupt)
        # txt 트랙 라우팅(트랙 이원성) — 템플릿 열기 / 새 기안.
        self.home.open_txt_requested.connect(self._open_txt)
        self.home.new_txt_requested.connect(lambda: self._open_txt(None))
        # 워크숍 라우팅 — 홈 시그널에 **직결** 연결한다(RC-04). 과거 hasattr 전방호환
        # 가드는 홈 측 시그널 미착지를 조용한 no-op 으로 삼켜 템플릿 워크숍 전체를
        # 은폐했다 — 배선이 어긋나면 기동 즉시 AttributeError 로 시끄럽게 실패한다.
        self.home.manage_templates_requested.connect(self._open_template_manager)
        # 데이터 풀 관리(J1).
        self.home.manage_pool_requested.connect(self._open_pool_manager)
        # 여러 작업 일괄 실행(J2 매트릭스).
        self.home.matrix_run_requested.connect(self._open_matrix_run)
        # 매핑 프로파일 관리(J3 공유 매핑 프로파일).
        self.home.manage_vocab_requested.connect(self._open_vocab_workbench)

    # ------------------------------------------------------------------ 라우팅
    def _on_nav(self, key: str) -> None:
        """레일 선택 → 라우트 디스패치(배선 소유는 컨트롤러 — 핸드오프 §0)."""
        self._nav_routes[key]()  # 미배선 키 = KeyError (조용한 무시 금지)

    def _open_editor_new(self) -> None:
        from .job_editor import JobEditorWizard

        wiz = JobEditorWizard(self.registry, base_registry=self.base_registry)
        wiz.job_saved.connect(lambda _name: self.home.refresh())
        self._track(wiz)
        wiz.show()

    def _open_editor_edit(self, name: str) -> None:
        from .job_editor import JobEditorWizard

        # 같은 작업을 두 에디터로 열면 last-save-wins 로 조용히 충돌한다(ST-10) — 이미
        # 열린 편집기가 있으면 앞으로 가져온다.
        key = f"editor:{name}"
        if self._raise_singleton(key):
            return
        # 기존 작업 프리로드: 템플릿 자동 로드 + 매핑 프리시드 + 이름/패턴 프리필.
        # 이름을 바꿔 저장하면 구명 작업은 별개로 남는다(자동 삭제는 발명 — 삭제는 사용자 몫).
        wiz = JobEditorWizard(
            self.registry, initial_job=self.registry.load(name),
            base_registry=self.base_registry,
        )
        wiz.job_saved.connect(lambda _name: self.home.refresh())
        self._track(wiz, singleton_key=key)
        wiz.show()

    def _open_run(self, name: str) -> None:
        from .run_view import RunView

        # 진입 가드(UD-03) — 렌더~클릭 사이 삭제·손상으로 사라진 작업을 exists() 없이
        # load 직행하면 FileNotFoundError 가 stderr 로만 샌다(조용한 크래시). 먼저 확인해
        # 없으면 시끄럽게 알리고 목록을 새로고침한다(확인-또는-경보).
        if not self.registry.exists(name):
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.warning(
                self.home, "실행할 수 없습니다",
                f"작업 '{name}' 을(를) 찾을 수 없습니다 — 이미 삭제되었거나 파일이 "
                "손상되었을 수 있습니다.\n목록을 새로고침합니다.",
            )
            self.home.refresh()
            return
        job = self.registry.load(name)
        # 실행뷰가 홈과 같은 데이터 풀 레지스트리를 공유(풀에서 겨눔). 홈이 풀을 노출하면 주입.
        pool_registry = getattr(self.home, "pool_registry", None)
        view = RunView(job, pool_registry=pool_registry)
        # 성공 실행 → 작업 사용 메타(last_run_at) 갱신. RunView 는 레지스트리를 모른다
        # (뷰 계약 유지) — 시그널 수신자만 추가.
        view.run_finished.connect(lambda batch: self._record_run(name, batch))
        self._track(view)
        view.show()

    def _record_run(self, name: str, batch) -> None:
        from datetime import datetime

        if getattr(batch, "succeeded", 0) <= 0 or not self.registry.exists(name):
            return
        job = self.registry.load(name)
        job.last_run_at = datetime.now().isoformat(timespec="seconds")
        self.registry.save(job)
        self.home.refresh()

    def _open_txt(self, name: "str | None" = None) -> None:
        from .txt_view import TxtDraftView

        view = TxtDraftView(self.home.text_registry)
        if name:
            view.select_template(name)
        self._track(view)
        view.show()

    def _open_template_manager(self, library_dir: "str | None" = None) -> None:
        """템플릿 관리 워크숍(C5)을 연다. '작업 만들기'는 에디터로 프리로드 라우팅.

        ``library_dir=None``(홈 시그널은 무인자)이면 패널이 표준 라이브러리
        (:func:`~hwpxfiller.core.template_status.default_templates_dir`)를 겨눈다(RC-14).
        """
        if self._raise_singleton("template"):  # 중복 관리 창 방지(ST-10)
            return
        from .template_manager import TemplateManagerPanel

        panel = TemplateManagerPanel(library_dir)
        panel.make_job_requested.connect(self._open_editor_from_template)
        self._track(panel, singleton_key="template")
        panel.show()

    def _open_matrix_run(self) -> None:
        """여러 작업 일괄 실행(J2) 창을 연다 — 홈과 같은 풀 레지스트리 공유."""
        if self._raise_singleton("matrix"):  # 중복 관리 창 방지(ST-10)
            return
        from .matrix_view import MatrixRunView

        pool_registry = getattr(self.home, "pool_registry", None)
        view = MatrixRunView(self.registry, pool_registry=pool_registry)
        view.run_finished.connect(self._record_matrix_run)
        self._track(view, singleton_key="matrix")
        view.show()

    def _record_matrix_run(self, result) -> None:
        """매트릭스 생성 성공분을 작업별 last_run_at 에 기록하고 홈 갱신."""
        from datetime import datetime

        stamp = datetime.now().isoformat(timespec="seconds")
        touched = False
        for jr in getattr(result, "per_job", []):
            if getattr(jr.batch, "succeeded", 0) <= 0 or not self.registry.exists(jr.job_name):
                continue
            job = self.registry.load(jr.job_name)
            job.last_run_at = stamp
            self.registry.save(job)
            touched = True
        if touched:
            self.home.refresh()

    def _open_pool_manager(self) -> None:
        """데이터 풀 관리 워크숍(J1)을 연다. 변경 시 홈 KPI 를 갱신한다."""
        if self._raise_singleton("pool"):  # 중복 관리 창 방지(ST-10)
            return
        from .dataset_pool_panel import DatasetPoolPanel

        panel = DatasetPoolPanel(getattr(self.home, "pool_registry", None))
        panel.pool_changed.connect(self.home.refresh)
        self._track(panel, singleton_key="pool")
        panel.show()

    def _open_editor_from_template(self, template_path: str) -> None:
        """관리 패널의 '작업 만들기' → 새 작업 에디터(템플릿 경로 세션에 시드).

        에디터의 페이지 계약은 병렬 유닛 소유라 건드리지 않는다 — 새 위저드를 열고
        공유 세션 속성(``template_path``)만 시드한다(사용자가 템플릿 페이지에서 확정).
        """
        from .job_editor import JobEditorWizard

        wiz = JobEditorWizard(self.registry, base_registry=self.base_registry)
        wiz.template_path = template_path
        wiz.job_saved.connect(lambda _name: self.home.refresh())
        self._track(wiz)
        wiz.show()

    def _open_vocab_workbench(self) -> None:
        """매핑 프로파일 관리 화면(J3)을 연다 — 편집은 위저드를 베이스 시드로 개방."""
        if self._raise_singleton("vocab"):  # 중복 관리 창 방지(ST-10)
            return
        from .vocab_workbench import VocabWorkbenchPanel

        panel = VocabWorkbenchPanel(self.base_registry, job_registry=self.registry)
        panel.edit_base_requested.connect(self._open_editor_from_base)
        panel.base_changed.connect(self.home.refresh)
        self._track(panel, singleton_key="vocab")
        panel.show()

    def _open_editor_from_base(self, base_name: str) -> None:
        """워크벤치 '편집' → 베이스를 시드한 새 위저드(템플릿 선택 후 이름 교집합 투영)."""
        from PySide6.QtWidgets import QMessageBox

        from .job_editor import JobEditorWizard
        from .vocab_workbench import VocabWorkbenchPanel

        try:
            base = self.base_registry.load(base_name)
        except Exception as exc:  # noqa: BLE001 — 침묵 no-op 금지(RC-04): 알리고 재동기화
            QMessageBox.warning(
                self.home, "매핑 프로파일 열기 실패",
                f"매핑 프로파일 '{base_name}' 을(를) 불러올 수 없습니다.\n{exc}",
            )
            # 스테일 목록(삭제·손상된 베이스)일 수 있으니 열린 워크벤치를 갱신한다.
            for child in self._children:
                if isinstance(child, VocabWorkbenchPanel):
                    child.refresh()
            return
        wiz = JobEditorWizard(self.registry, base_registry=self.base_registry)
        wiz.base_mapping = base
        wiz.base_mapping_name = base_name
        wiz.job_saved.connect(lambda _name: self.home.refresh())
        self._track(wiz)
        wiz.show()

    def _delete_job(self, name: str) -> None:
        from .confirm import confirm_destructive

        # 공용 파괴 확인(RC-15): 기본=취소·한국어 명시 라벨 — Enter 반사로 삭제되지 않는다.
        if confirm_destructive(
            self.home, "작업 삭제",
            f"작업 '{name}' 을(를) 삭제할까요?\n삭제하면 되돌릴 수 없습니다.",
            "삭제",
        ):
            self.registry.delete(name)
            self.home.refresh()

    def _reveal_corrupt(self, path: str) -> None:
        """손상 작업 파일이 있는 폴더를 OS 탐색기로 연다(UD-44) — 수동 복구 동선.

        폴더 열기는 run/matrix 가 쓰는 공용 유틸(RC-22 단일 출처)을 소비한다.
        """
        from pathlib import Path

        from .batch_run import open_folder

        open_folder(str(Path(path).parent))

    def _delete_corrupt(self, path: str) -> None:
        """손상 작업 파일 삭제(UD-44) — 확인 경유(RC-15). 파싱 불가라 이름이 없어
        파일명으로 재진술한다. 삭제 후 홈을 새로고침해 상시 경보를 해소한다."""
        from pathlib import Path

        from .confirm import confirm_destructive

        p = Path(path)
        if confirm_destructive(
            self.home, "손상 파일 삭제",
            f"손상된 작업 파일 '{p.name}' 을(를) 삭제할까요?\n삭제하면 되돌릴 수 없습니다.",
            "삭제",
        ):
            try:
                p.unlink()
            except OSError:
                pass  # 이미 사라졌으면 목적 달성(무시)
            self.home.refresh()

    def _raise_singleton(self, key: str) -> bool:
        """같은 능력 창이 이미 열려 있으면 앞으로 가져오고 True(ST-10) — 없거나 닫혔으면 False.

        보이는(살아 있는) 창만 재사용한다 — 닫힌 창은 stale 로 보고 새로 연다(신선 상태).
        """
        win = self._singletons.get(key)
        if win is not None and win.isVisible():
            if win.isMinimized():
                win.showNormal()
            win.raise_()
            win.activateWindow()
            return True
        return False

    def _track(self, win, *, singleton_key: "str | None" = None) -> None:
        self._children.append(win)
        win.destroyed.connect(lambda *_: self._children.remove(win) if win in self._children else None)
        if singleton_key is not None:
            self._singletons[singleton_key] = win
            win.destroyed.connect(lambda *_: self._singletons.pop(singleton_key, None))


# 하위호환 별칭(RC-35): 컨트롤러는 앱 전체 배선·수명을 소유하는 사실상 공용 API 다 —
# 언더스코어 사명이 '프라이빗이니 자유 변경' 오신호를 주던 것을 공개화했다.
# 기존 임포트·docs 스니펫(`_AppController`)은 이 별칭으로 계속 동작한다.
_AppController = AppController


def main() -> int:
    from PySide6.QtWidgets import QApplication

    from ..core.job import JobRegistry, default_jobs_dir

    app = QApplication(sys.argv)
    install_korean_translator(app)  # Qt 표준 문자열 한국어화(RC-27)
    controller = AppController(JobRegistry(default_jobs_dir()))
    controller.shell.show()  # 단일창 셸 기동(ST-01) — 홈이 첫 페이지
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
