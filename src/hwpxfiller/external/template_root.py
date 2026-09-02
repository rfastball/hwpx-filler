"""서식 폴더 런타임 홀더 + 레거시 TXT 1회 이관(U6-A · #975).

**이 클래스 인스턴스 하나가 프로세스의 템플릿 루트 권위**다. 종전에는 매체마다 다른 기본
해석기(:func:`~hwpxfiller.host.locations.default_templates_dir` / 삭제된
``default_text_templates_dir``)를 소비자가 각자 불러 세 자리가 같은 질문에 각자 답했다 —
루트를 바꿀 수 있게 되는 순간 그 셋이 갈린다. 그래서 hwpx 목록·txt 목록·가져오기 복사·
Job 링크 해석이 전부 이 홀더(또는 그 :meth:`TemplateRoot.path` 콜러블)를 지난다.

판정은 여기 없다 — 도출은 링0
(:func:`hwpxfiller.domain.template_root_default.resolve_templates_root`)이 하고 이 모듈은
설정 읽기·존재 관찰·쓰기 같은 **효과**만 진다.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from hwpxfiller.domain.template_root_default import (
    SOURCE_DEFAULT,
    TemplateRootResolution,
    resolve_templates_root,
)
from hwpxfiller.domain.template_status import is_excluded_subtree
from hwpxfiller.domain.text_template import TEXT_TEMPLATE_SUFFIX
from hwpxfiller.host.locations import default_templates_dir

from .settings import load_templates_root, save_templates_root

#: 매체별 루트가 둘이던 시절의 txt 루트 폴더 이름(앱 홈 아래). 지금은 **이관의 출발지로만**
#: 산다 — 해석기(``host.locations.default_text_templates_dir``)는 U6-A 에서 삭제됐다.
LEGACY_TEXT_TEMPLATES_DIRNAME = "text_templates"


class TemplateRoot:
    """설정 + 존재 관찰 + 링0 도출을 묶은 루트 권위. **도출 1회 memo**를 든다.

    처음 이 클래스는 아무것도 캐시하지 않았다 — 「설정 변경 뒤 옛 값을 든 사본」이 이
    저장소의 지배 결함류이고, 매 호출 재판독이 그 결함을 구조적으로 불가능하게 했다.
    그 근거는 **이 홀더가 루트의 단일 권위**라는 사실 위에 서 있고(재지정 동사가 여기
    하나다 — hwpx 목록·txt 목록·가져오기 복사·Job 링크 해석이 전부 이 인스턴스를 지난다),
    그래서 런타임에 설정 파일을 다른 곳이 갈아 끼우는 일이 없다. 그 사실을 근거로 memo 를
    둔다: 무효화 지점은 :meth:`set` **하나**이고, 그것이 곧 루트가 바뀌는 전부다.

    memo 가 필요해진 이유(U6-D #978 리뷰 8): 편집기 스냅샷이 표시명을 짓느라 이 홀더를
    스냅샷마다 여러 번 지난다 — 재판독은 그때마다 ``settings.json`` 을 읽는 디스크 왕복이고,
    푸시 한 번이 같은 답을 세 번 사 오게 된다.
    """

    def __init__(
        self,
        *,
        load: "Callable[[], str]" = load_templates_root,
        save: "Callable[[str], None]" = save_templates_root,
        default_root: "Path | None" = None,
        exists: "Callable[[Path], bool]" = Path.is_dir,
    ) -> None:
        self._load = load
        self._save = save
        self._default_root = Path(default_root) if default_root is not None else None
        self._exists = exists
        #: 도출 memo — :meth:`set` 만이 비운다(그것이 루트가 바뀌는 유일한 전이다).
        self._cached: "TemplateRootResolution | None" = None

    def default_root(self) -> Path:
        """지정이 없을 때의 루트 — 주입이 없으면 앱 홈 ``templates``."""
        if self._default_root is not None:
            return self._default_root
        return default_templates_dir()

    def resolution(self) -> TemplateRootResolution:
        """지금의 루트 도출 — 설정 읽기 + 존재 관찰을 링0 판정에 먹인다(**1회 memo**).

        관찰(폴더가 지금도 있는가)까지 memo 에 든다. 사라진 폴더의 하향은 **다음 재지정
        까지** 옛 판정을 말할 수 있는데, 그 창은 이 프로세스가 루트를 바꾸는 유일한 동사가
        :meth:`set` 이라는 사실과 같은 크기다 — 그리고 그 하향을 실제로 사용자에게 말하는
        표면(설정 모달의 서식 폴더 행)은 재지정 왕복 뒤에 다시 그려진다.
        """
        if self._cached is None:
            configured = self._load()
            configured_exists = bool(configured) and self._exists(Path(configured))
            self._cached = resolve_templates_root(
                configured=configured,
                configured_exists=configured_exists,
                default_root=str(self.default_root()),
            )
        return self._cached

    def path(self) -> Path:
        """도출된 루트 경로 — 소비자에 주입되는 콜러블이 이것이다."""
        return Path(self.resolution().directory)

    def set(self, path: str) -> TemplateRootResolution:
        """서식 폴더 재지정 — 영속 뒤 **다시 도출한** 값을 돌려준다(사본 반환 금지).

        memo 무효화가 여기 하나인 것이 그 memo 의 계약이다(리뷰 8): 이 동사 말고 루트를
        바꾸는 자리가 생기면 그 자리도 여기서 비워야 한다.
        """
        self._save(path)
        self._cached = None
        return self.resolution()


@dataclass(frozen=True)
class TextTemplatesMigration:
    """레거시 TXT 이관 결과 — 옮긴 상대경로와 옮기지 못한 것(사유 병기)."""

    moved: "list[str]" = field(default_factory=list)
    skipped: "list[tuple[str, str]]" = field(default_factory=list)

    @property
    def happened(self) -> bool:
        """재진술할 것이 있는가 — 조용한 이관은 없다."""
        return bool(self.moved or self.skipped)

    def restate(self, root: Path) -> str:
        """부팅 뒤 한 번 재진술할 문안. 아무 일도 없었으면 ``""``."""
        if not self.happened:
            return ""
        lines: "list[str]" = []
        if self.moved:
            lines.append(f"TXT 템플릿 {len(self.moved)}건을 서식 폴더로 옮겼습니다: {root}")
        # 사유가 여럿일 수 있다(이름 충돌 · 나열이 거르는 하위트리) — 사유별로 한 줄씩 낸다:
        # 한 줄로 뭉치면 안 옮긴 이유가 파일마다 다른데 하나로 읽힌다.
        for reason in dict.fromkeys(item_reason for _n, item_reason in self.skipped):
            same = [name for name, item_reason in self.skipped if item_reason == reason]
            lines.append(f"옮기지 못한 파일 {len(same)}건 — {reason}: {', '.join(same)}")
        return "\n".join(lines)


_ALREADY_THERE = "같은 이름이 이미 있습니다"
#: 나열이 어차피 걸러 낼 하위트리(``Results``·``.trash``) — 옮기면 **옮긴 뒤 사라진다**.
_EXCLUDED_SUBTREE = "서식 폴더가 읽지 않는 하위 폴더입니다"


def migrate_legacy_text_templates(
    *, home: Path, root: TemplateRoot,
) -> TextTemplatesMigration:
    """앱 홈 ``text_templates/**/*.txt`` 를 기본 루트로 **1회 이관**한다(U6-A §4).

    설정 키가 지정돼 있으면 아무것도 하지 않는다 — 사용자가 고른 폴더에 앱이 파일을 넣지
    않는다. 지정이 없어 기본 루트를 쓰는 경우에만, 같은 상대 경로로 **옮긴다**(복사가 아니라
    이동이라 다음 부팅에는 걷을 것이 남지 않는다). 대상에 같은 이름이 이미 있으면 그 파일은
    건드리지 않고 사유에 남긴다(조용한 덮어쓰기 금지).

    **나열이 거르는 하위트리는 옮기지 않는다**(``Results``·``.trash`` —
    :func:`~hwpxfiller.domain.template_status.is_excluded_subtree` 와 **같은 술어**): 옮겨 봐야
    새 루트에서도 걸러져 목록에서 사라진다. 사라지는 것이 아니라 **안 옮겼다는 사실**이
    남아야 하므로 ``skipped`` 에 사유와 함께 싣는다(조용한 증발 금지).
    """
    if root.resolution().source != SOURCE_DEFAULT:
        return TextTemplatesMigration()
    legacy = Path(home) / LEGACY_TEXT_TEMPLATES_DIRNAME
    if not legacy.is_dir():
        return TextTemplatesMigration()
    destination = root.path()
    moved: "list[str]" = []
    skipped: "list[tuple[str, str]]" = []
    for source in sorted(legacy.rglob("*" + TEXT_TEMPLATE_SUFFIX)):
        if not source.is_file():
            continue
        relative = source.relative_to(legacy)
        if is_excluded_subtree(relative.parts):
            skipped.append((relative.as_posix(), _EXCLUDED_SUBTREE))
            continue
        target = destination / relative
        if target.exists():
            skipped.append((relative.as_posix(), _ALREADY_THERE))
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(target))
        moved.append(relative.as_posix())
    return TextTemplatesMigration(moved, skipped)
