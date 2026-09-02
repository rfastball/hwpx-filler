"""서식 폴더(템플릿 루트) 도출(U6-A · #975) — 설정한 폴더 → 앱 홈 기본 폴더.

템플릿 목록의 루트는 **하나**다(U6 §2.3). hwpx·txt 가 같은 루트를 재귀로 읽고, 그 루트를
고르는 자리는 셸 설정 모달 한 곳이다. 이 모듈은 「지금 어느 폴더가 루트인가」의 **판정**만
소유한다 — 설정 읽기·존재 관찰·파일 나열은 전부 호출자(:mod:`hwpxfiller.external.template_root`)
가 진다.

**저장 폴더 도출과 다른 점 — 기본값으로 내려가지 않는다.**
:func:`~hwpxfiller.domain.output_folder_default.resolve_output_folder` 는 설정한 폴더가
사라지면 템플릿 옆 ``Results`` 로 **내려가고** 사유를 병기한다. 여기서는 내려가지 않는다:
저장 폴더가 갈리면 문서가 다른 자리에 떨어질 뿐이지만, 서식 폴더가 갈리면 **사용자가 고른
것과 다른 템플릿 집합**이 목록에 선다 — 홈 폴더에 남아 있던 옛 서식으로 문서를 만드는
길이고, 그것이 이 저장소가 금지하는 조용한 추측이다. 그래서 설정값이 있으면 그 경로를 그대로
루트로 세우고, 없는 폴더면 목록이 비는 대신 :attr:`TemplateRootResolution.notice` 로 사유를
시끄럽게 말한다(빈 목록 안내는 링1 ``empty_hint`` 가 잇는다).

**순수 함수다** — 파일 시스템을 만지지 않는다. 설정한 폴더가 실제로 있는지는 호출자가 관찰해
``configured_exists`` 로 건넨다(관찰은 호출자, 판정은 여기).
"""

from __future__ import annotations

from dataclasses import dataclass

#: 사용자가 설정 모달에서 고른 서식 폴더.
SOURCE_CONFIGURED = "configured"
#: 지정이 없을 때의 앱 홈 기본 폴더(``~/.hwpxfiller/templates``).
SOURCE_DEFAULT = "default"

#: 출처의 사용자 문안. 표면은 이 라벨을 그대로 그린다(재조립 금지).
SOURCE_LABELS: "dict[str, str]" = {
    SOURCE_CONFIGURED: "설정한 폴더",
    SOURCE_DEFAULT: "기본 폴더",
}

_CONFIGURED_MISSING = "설정한 서식 폴더를 찾을 수 없습니다: {directory}"


def source_label(source: str) -> str:
    """출처의 사용자 문안 — 미상 출처는 ``""``."""
    return SOURCE_LABELS.get(source, "")


@dataclass(frozen=True)
class TemplateRootResolution:
    """도출된 서식 폴더 + 출처 + 사유 문안(표면은 읽기만 한다)."""

    directory: str
    source: str
    notice: str = ""

    @property
    def source_label(self) -> str:
        """출처의 사용자 문안 — :func:`source_label` 위임."""
        return source_label(self.source)


def resolve_templates_root(
    *,
    configured: str = "",
    configured_exists: bool = False,
    default_root: str = "",
) -> TemplateRootResolution:
    """서식 폴더 도출 — ① 설정한 폴더(존재와 **무관**) ② 앱 홈 기본 폴더.

    ``configured`` 가 비어 있으면 기본 폴더가 루트다(사유 없음 — 지정하지 않은 것은 결함이
    아니다). 비어 있지 않으면 그 경로가 루트이고, ``configured_exists`` 가 거짓일 때만
    사유를 병기한다. **기본값으로 내려가지 않는다** — 모듈 docstring 의 이유 그대로다.
    """
    if not configured:
        return TemplateRootResolution(default_root, SOURCE_DEFAULT)
    notice = "" if configured_exists else _CONFIGURED_MISSING.format(directory=configured)
    return TemplateRootResolution(configured, SOURCE_CONFIGURED, notice)
