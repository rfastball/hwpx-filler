"""THIRD_PARTY_NOTICES 가 실제 배포본 내용물의 정본과 어긋나지 않는지(FB-06 #1082, #1107).

생성 스크립트 대신 손으로 유지하는 고지 파일이므로, 이 테스트가 정본에서 **배포본에 실리는
것**을 계산해 고지 파일에 등장하는지 대조한다(전문 검증은 아니다).

- Python: ``uv.lock`` 의 Windows 런타임 폐포(직접 의존성 + ``gui`` extra, dev·build 그룹 제외).
  직접 의존성 이름만 보던 종전 검사는 pywebview 아래의 pythonnet·cffi 같은 전이 의존성을
  놓쳤다(#1107).
- rhwp: ``vendor/rhwp/studio-runtime.json`` 이 배포본 Studio 파일 목록이다. 그 안의 글꼴
  파일 이름과 CanvasKit·rhwp WASM 을 대조한다 — ``vite.config.mjs`` 가 Studio 산출물을
  통째로 복사하므로 고지가 "두 글꼴만 번들"이라고 적어도 아무도 잡지 못했다(#1107).
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

from packaging.markers import Marker

ROOT = Path(__file__).resolve().parent.parent
NOTICES = ROOT / "THIRD_PARTY_NOTICES"

#: 배포 대상 런타임 — Windows x64 CPython 3.13(``.python-version``).
WINDOWS_RUNTIME = {
    "os_name": "nt",
    "sys_platform": "win32",
    "platform_system": "Windows",
    "platform_machine": "AMD64",
    "implementation_name": "cpython",
    "platform_python_implementation": "CPython",
    "python_version": "3.13",
    "python_full_version": "3.13.0",
    "extra": "",
}

#: 런타임 폐포에 들어도 배포본에 싣지 않는 패키지 — spec ``excludes`` 와 함께 바꾼다.
#: 현재 폐포 안에서 뺀 것은 없다(Pillow·setuptools 는 dev·build 그룹에서만 들어와 폐포 밖).
EXCLUDED_FROM_BUNDLE: frozenset[str] = frozenset()


def _notices_text() -> str:
    return NOTICES.read_text(encoding="utf-8")


def _normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _lock_packages() -> dict[str, dict]:
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    return {_normalize(p["name"]): p for p in lock["package"]}


def _applies(dep: dict) -> bool:
    marker = dep.get("marker")
    return marker is None or Marker(marker).evaluate(WINDOWS_RUNTIME)


def runtime_closure() -> dict[str, str]:
    """``uv.lock`` 에서 배포 런타임 의존성 폐포를 계산한다 — {정규화 이름: 고정 버전}."""
    packages = _lock_packages()
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    root = packages[_normalize(project["name"])]
    queue = [d for d in root.get("dependencies", []) if _applies(d)]
    queue += [d for d in root.get("optional-dependencies", {}).get("gui", []) if _applies(d)]
    closure: dict[str, str] = {}
    while queue:
        dep = queue.pop()
        name = _normalize(dep["name"])
        package = packages[name]
        extras = dep.get("extra", [])
        if name not in closure:
            closure[name] = package["version"]
            queue += [d for d in package.get("dependencies", []) if _applies(d)]
        for extra in extras:
            optional = package.get("optional-dependencies", {}).get(extra, [])
            queue += [d for d in optional if _applies(d)]
    return closure


def test_notices_file_exists() -> None:
    assert NOTICES.is_file()


def test_runtime_closure_is_computed_from_lock() -> None:
    """폐포 계산 자체의 양성 대조 — 직접·extra·전이 의존성이 모두 잡히고 dev 그룹은 빠진다."""
    closure = runtime_closure()
    for expected in ("lxml", "openpyxl", "pywebview", "pythonnet", "cffi"):
        assert expected in closure
    for dev_only in ("pillow", "setuptools", "pytest", "pyinstaller"):
        assert dev_only not in closure


def test_python_runtime_closure_is_listed_with_locked_versions() -> None:
    text = _notices_text()
    rows = {
        _normalize(m.group(1)): m.group(2)
        for m in re.finditer(r"^\| ([A-Za-z0-9_.-]+) \| ([^ |]+) \|", text, re.MULTILINE)
    }
    closure = {
        name: version
        for name, version in runtime_closure().items()
        if name not in EXCLUDED_FROM_BUNDLE
    }
    missing = sorted(name for name in closure if name not in rows)
    assert not missing, f"uv.lock 런타임 폐포가 고지 표에 없음: {missing}"
    stale = sorted(
        f"{name}: 고지 {rows[name]} != lock {version}"
        for name, version in closure.items()
        if rows[name] != version
    )
    assert not stale, f"고지 표 버전이 uv.lock 과 다름: {stale}"


def test_npm_runtime_dependencies_are_listed() -> None:
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    names = set(package.get("dependencies", {}))
    text = _notices_text().lower()
    missing = [n for n in names if n.lower() not in text]
    assert not missing, f"package.json 런타임 의존성이 고지에 없음: {missing}"


def _studio_runtime_paths() -> list[str]:
    manifest = json.loads(
        (ROOT / "vendor" / "rhwp" / "studio-runtime.json").read_text(encoding="utf-8")
    )
    return [entry["path"] for entry in manifest["files"]]


def test_every_bundled_studio_font_is_listed() -> None:
    fonts = [Path(p).name for p in _studio_runtime_paths() if p.startswith("studio/fonts/")]
    assert fonts, "studio-runtime.json 에 글꼴이 없음 — 목록 구조가 바뀌었는지 확인"
    text = _notices_text()
    missing = sorted(name for name in fonts if f"`{name}`" not in text)
    assert not missing, f"배포본 rhwp 글꼴이 고지에 없음: {missing}"


def test_every_bundled_app_font_is_listed() -> None:
    fonts = sorted(p.name for p in (ROOT / "frontend" / "fonts").glob("*.woff2"))
    assert fonts
    text = _notices_text()
    missing = [name for name in fonts if f"`{name}`" not in text]
    assert not missing, f"앱 화면 글꼴이 고지에 없음: {missing}"


def test_rhwp_runtime_components_are_listed() -> None:
    paths = _studio_runtime_paths()
    text = _notices_text()
    assert any(Path(p).name.startswith("canvaskit-") for p in paths)
    assert "canvaskit-wasm" in text and "BSD-3-Clause" in text
    assert any(Path(p).name.startswith("rhwp_bg-") for p in paths)
    assert "licenses/rhwp/THIRD_PARTY_LICENSES.txt" in text


def test_font_license_texts_are_included() -> None:
    text = _notices_text()
    assert "SIL OPEN FONT LICENSE Version 1.1" in text
    assert "GUST Font License" in text and "LaTeX Project Public License" in text


def test_rhwp_source_pin_notice_files_exist() -> None:
    """``vendor/rhwp/source.json`` 이 가리키는 고지 파일이 실제로 있다."""
    pin = json.loads((ROOT / "vendor" / "rhwp" / "source.json").read_text(encoding="utf-8"))
    declared = [pin["licenseFile"], pin["thirdPartyLicenses"]]
    declared += pin["fontNotices"] + pin["bundledNpmLicenses"]
    missing = [path for path in declared if not (ROOT / path).is_file()]
    assert not missing, f"source.json 고지 경로가 없음: {missing}"
    third_party = (ROOT / pin["thirdPartyLicenses"]).read_text(encoding="utf-8")
    assert third_party.startswith("# Third-Party Licenses")


def test_project_license_is_referenced() -> None:
    text = _notices_text()
    assert "LICENSE" in text
    assert "MIT" in text
