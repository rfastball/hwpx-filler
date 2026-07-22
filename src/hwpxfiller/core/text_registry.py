"""텍스트 기안 템플릿 레지스트리 — 정해진 루트의 ``.txt`` 템플릿 목록/로드.

**템플릿** 레지스트리다 — 저장되는 기안 **작업**(:class:`~hwpxfiller.core.job.JobRegistry`)과는
다른 층이다. (R-info 3부 결정 4 로 뒤집힘: 이전 주석의 "txt 트랙은 저장 Job 이 없다"는 낡았다 —
기안 작업도 이제 ``JobRegistry``·:class:`~hwpxfiller.core.job.Job` 을 쓰고 매체는 ``template_path``
접미사에서 유도한다[:func:`~hwpxfiller.core.job.template_media`]. 저장 기계는 hwpx 와 하나로 공유하고
화면만 둘이다.) 이 레지스트리는 그 작업들이 **재사용할 평문 템플릿**(``.txt``, ``{{필드}}`` 토큰)을
한 곳(루트)에 모아 고르게 한다 — hwpx 의 템플릿 라이브러리에 대응하는 txt 쪽이다.

Qt·엔진(lxml/openpyxl) 비의존 — 순수 파일 나열 + :func:`~hwpxfiller.core.text_render.template_fields`.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

from .paths import home_dir
from .text_render import template_fields


def default_text_templates_dir() -> Path:
    """txt 기안 템플릿 기본 루트 — ``~/.hwpxfiller/text_templates``.

    작업 레지스트리(``jobs/``)와 같은 홈 아래 별도 폴더. ``HWPXFILLER_HOME`` 로 재지정 가능
    (테스트·이식성 — 해석은 :func:`~hwpxfiller.core.paths.home_dir`). 레지스트리 *클래스* 는
    위치-불가지(생성자가 디렉터리를 받는다).
    """
    return home_dir() / "text_templates"


@dataclass
class TextTemplate:
    """평문 기안 템플릿 1개 — 이름 + 경로. 내용/필드는 필요 시 파일에서 읽는다."""

    name: str
    path: Path

    def content(self) -> str:
        return self.path.read_text(encoding="utf-8")

    def fields(self) -> "list[str]":
        """템플릿이 참조하는 ``{{필드}}`` 목록(등장순·중복제거)."""
        return template_fields(self.content())


class TextTemplateRegistry:
    """루트 디렉터리의 ``*.txt`` 를 기안 템플릿으로 나열/로드한다."""

    SUFFIX = ".txt"

    def __init__(self, directory: "str | Path"):
        self.directory = Path(directory)
        # 템플릿 파일 쓰기 직렬화 락(JobRegistry.write_lock 동형) — 「템플릿으로 저장」의 덮어쓰기
        # 재검증(내용 지문 재-읽기)과 실제 교체(write_text_atomic) 사이에 다른 스레드가 대상 파일을
        # 바꾸지 못하게 한 임계구역으로 묶는다(리뷰 F5). 효력은 **모든 템플릿 writer 가 함께
        # 잡아야** 성립한다 — 관리 화면 「새 TXT」·내용 편집(screen_template)과 「템플릿으로 저장」
        # (screen_draft)이 이 한 락을 공유한다. RLock(같은 스레드 재진입 허용).
        self._write_lock = threading.RLock()

    def write_lock(self) -> "threading.RLock":
        """템플릿 쓰기 임계구역 락(공유) — 덮어쓰기 재검증~교체를 한 임계구역으로 묶는다(F5)."""
        return self._write_lock

    def list_templates(self) -> "list[TextTemplate]":
        """루트의 ``*.txt`` 를 **재귀**로(하위폴더 포함) 나열한다(R-info 2부 결정 5).

        비재귀 ``glob`` 은 탐색기로 하위폴더에 떨군 템플릿을 조용히 누락했다(confirm-or-alarm
        위반) — ``rglob`` 으로 반드시 찾아 올린다("파일 등장은 관용, 폴더 조직은 불인정" —
        하위폴더는 조직이 아니라 관용된 등장지라 평평하게 나열된다).

        **이름 = 루트 상대경로(확장자 제외, POSIX)** — 루트 직속 파일은 곧 stem 이고 하위폴더
        파일은 ``하위폴더/이름``. 재귀가 ``a/동명.txt``·``b/동명.txt`` 를 stem 하나로 노출하면
        :meth:`load` 가 첫 파일만 열어 다른 항목을 골라도 조용히 첫 내용이 열린다(#136 리뷰 F1).
        상대경로 이름은 유일하므로 목록·선택·load 계약이 두 파일을 별개로 구분한다. 이름순 정렬."""
        if not self.directory.exists():
            return []
        return [
            TextTemplate(p.relative_to(self.directory).with_suffix("").as_posix(), p)
            for p in sorted(
                (p for p in self.directory.rglob("*" + self.SUFFIX) if p.is_file()),
                key=lambda p: (p.name, str(p)),
            )
        ]

    def names(self) -> "list[str]":
        return [t.name for t in self.list_templates()]

    def count(self) -> int:
        return len(self.list_templates())

    def load(self, name: str) -> TextTemplate:
        """이름으로 템플릿 로드 — **재귀 스캔에서 실제 경로를 찾는다**(하위폴더 파일도 올바르게
        연다). list→load 왕복 정합: 목록이 하위폴더 파일을 올렸는데 load 가 루트 경로만 재구성하면
        엉뚱한(없는) 파일을 겨눈다. 미발견(아직 없는 이름 등)이면 루트 경로로 구성해 하위호환."""
        for t in self.list_templates():
            if t.name == name:
                return t
        return TextTemplate(name, self.directory / (name + self.SUFFIX))
