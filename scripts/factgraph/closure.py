"""production Python source closure — 무엇이 계측 대상인가의 단일 출처.

분모는 배포 정본에서 유도한다: ``pyproject.toml`` 의 wheel ``packages`` 루트가 곧 계측
폐포다. 손으로 든 목록은 새 패키지를 조용히 빠뜨리고, 배포에 실리는 것과 계측되는 것이
다르면 「전수」 주장이 거짓이 된다 — 그래서 목록이 아니라 유도다.

죽은 트리 방어: 유도된 루트 밖 ``src/`` 하위에 ``.py`` 가 나타나면 조용히 편입하지도
무시하지도 않고 오류로 든다(#512 — 조용한 skip 금지). 현재 저장소의 ``src/hwpxdiff/`` 는
``.py`` 0 의 잔존 트리라 이 방어의 실측 표적이다.

순수 함수다 — ``repo_root`` 를 받아 그 트리만 본다. 합성 트리를 겨눈 음성 대조가 1좌표
변이로 설 수 있게 하기 위해서다(승계 형질 S4).
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from .schema import FactGraphError


@dataclass(frozen=True)
class ModuleFile:
    module: str  # 예: "hwpxcore.native.dialogs"
    path: str  # 저장소 상대 posix 경로, 예: "src/hwpxcore/native/dialogs.py"


@dataclass(frozen=True)
class Closure:
    roots: tuple[str, ...]  # 예: ("src/hwpxcore", "src/hwpxfiller")
    modules: tuple[ModuleFile, ...]  # module 이름 정렬


def wheel_package_roots(repo_root: Path) -> tuple[str, ...]:
    """``pyproject.toml`` wheel packages 에서 폐포 루트를 유도한다."""
    pyproject = repo_root / "pyproject.toml"
    if not pyproject.is_file():
        raise FactGraphError(f"pyproject.toml 이 없다: {pyproject}")
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    try:
        packages = data["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]
    except KeyError as exc:
        raise FactGraphError(
            "pyproject 에서 [tool.hatch.build.targets.wheel].packages 를 찾지 못했다 — "
            "폐포 분모를 유도할 수 없다"
        ) from exc
    if not packages:
        raise FactGraphError("wheel packages 가 비었다 — 폐포 분모가 없다")
    for root in packages:
        if not str(root).replace("\\", "/").startswith("src/"):
            raise FactGraphError(f"wheel package 루트가 src/ 밖이다: {root!r}")
    return tuple(str(root).replace("\\", "/") for root in packages)


def production_closure(repo_root: Path) -> Closure:
    repo_root = Path(repo_root)
    roots = wheel_package_roots(repo_root)
    modules: list[ModuleFile] = []
    for root in roots:
        base = repo_root / root
        if not base.is_dir():
            raise FactGraphError(f"폐포 루트가 디렉터리가 아니다: {root}")
        files = sorted(base.rglob("*.py"))
        if not files:
            # 빈 폐포는 초록이 될 수 없다 — 루트가 통째로 사라진 것을 0건 통과로 읽지 않는다.
            raise FactGraphError(f"폐포 루트에 .py 가 하나도 없다: {root}")
        for f in files:
            rel = f.relative_to(repo_root).as_posix()
            modules.append(ModuleFile(module=_module_name(root, rel), path=rel))

    _reject_strays(repo_root, roots)

    modules.sort(key=lambda m: m.module)
    seen: dict[str, str] = {}
    for m in modules:
        if m.module in seen:
            raise FactGraphError(f"모듈 이름 충돌: {m.module} ({seen[m.module]} ↔ {m.path})")
        seen[m.module] = m.path
    return Closure(roots=roots, modules=tuple(modules))


def _module_name(root: str, rel_path: str) -> str:
    """``src/hwpxcore`` + ``src/hwpxcore/native/dialogs.py`` → ``hwpxcore.native.dialogs``."""
    package = root.rsplit("/", 1)[-1]
    inner = rel_path[len(root) + 1 :]
    parts = inner.split("/")
    leaf = parts[-1]
    parts = parts[:-1] if leaf == "__init__.py" else parts[:-1] + [leaf.removesuffix(".py")]
    return ".".join([package, *parts]) if parts else package


def _reject_strays(repo_root: Path, roots: tuple[str, ...]) -> None:
    """루트 밖 ``src/`` 하위 ``.py`` 는 편입도 무시도 아닌 오류다(죽은 트리 방어)."""
    src = repo_root / "src"
    if not src.is_dir():
        raise FactGraphError(f"src/ 가 없다: {src}")
    prefixes = tuple(f"{root}/" for root in roots)
    strays = sorted(
        p.relative_to(repo_root).as_posix()
        for p in src.rglob("*.py")
        if not p.relative_to(repo_root).as_posix().startswith(prefixes)
    )
    if strays:
        raise FactGraphError(
            "폐포 루트 밖 src/ 하위에 .py 가 있다 — 배포 정본(pyproject wheel packages)과 "
            f"소스 트리가 어긋났다: {strays}"
        )
