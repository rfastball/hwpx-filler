"""텍스트 기안 템플릿 레지스트리 — 정해진 루트의 ``.txt`` 템플릿 목록/로드.

HWPX 작업 레지스트리(:class:`~hwpxfiller.core.job.JobRegistry`)와 **별도**다(ADR A: txt 진입은
Job 과 분리 설계). txt 트랙은 저장 Job 이 없다 — 경량·즉시(render→copy). 이 레지스트리는
재사용할 평문 템플릿(``.txt``, ``{{필드}}`` 토큰)을 한 곳(루트)에 모아 고르게 한다.

Qt·엔진(lxml/openpyxl) 비의존 — 순수 파일 나열 + :func:`~hwpxfiller.core.text_render.template_fields`.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .text_render import template_fields


def default_text_templates_dir() -> Path:
    """txt 기안 템플릿 기본 루트 — ``~/.hwpxfiller/text_templates``.

    작업 레지스트리(``jobs/``)와 같은 홈 아래 별도 폴더. ``HWPXFILLER_HOME`` 로 재지정 가능
    (테스트·이식성). 레지스트리 *클래스* 는 위치-불가지(생성자가 디렉터리를 받는다).
    """
    root = os.environ.get("HWPXFILLER_HOME") or (Path.home() / ".hwpxfiller")
    return Path(root) / "text_templates"


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

    def list_templates(self) -> "list[TextTemplate]":
        """루트의 ``*.txt`` 를 **재귀**로(하위폴더 포함) 나열한다(R-info 2부 결정 5).

        비재귀 ``glob`` 은 탐색기로 하위폴더에 떨군 템플릿을 조용히 누락했다(confirm-or-alarm
        위반) — ``rglob`` 으로 반드시 찾아 올린다("파일 등장은 관용, 폴더 조직은 불인정" —
        하위폴더는 조직이 아니라 관용된 등장지라 평평하게 나열된다). 이름순 정렬, 하위폴더
        동명(stem 충돌)은 경로로 안정 타이브레이크(둘 다 별개 항목으로 노출)."""
        if not self.directory.exists():
            return []
        return [
            TextTemplate(p.stem, p)
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
