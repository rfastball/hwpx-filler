"""Generate version resources from the single version in pyproject.toml.

``build-metadata.json`` 은 릴리스에 함께 실려 나가는 **유일한 서술 자산**이다. 종전에는
version/commit/python/pyinstaller 넷뿐이라 "이 릴리스가 어떤 프런트 산출물을 실었는가"를
메타데이터만으로는 말할 수 없었다(#383). 그래서 잠금과 sealed web artifact 의 identity 를
같이 싣는다 — 값은 전부 이미 있는 단일 출처(`uv.lock`·seal)에서 읽어오고 여기서 새로
계산하지 않는다.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

from hwpxfiller.web_artifact import (
    SEAL_FILENAME,
    WebArtifactViolation,
    resolve_web_artifact,
)

ROOT = Path(__file__).resolve().parents[1]

PRODUCTS = {
    "filler": {
        # 사용자 노출 제품명(#258). 기술 식별자(파일명·internal_name)는 hwpx-filler 유지.
        "product_name": "문서나르미",
        "description": "HWPX 누름틀 문서 생성기",
        "filename": "hwpx-filler-web.exe",
        "internal_name": "hwpx-filler-web",
    },
}


def _version() -> str:
    with (ROOT / "pyproject.toml").open("rb") as stream:
        return tomllib.load(stream)["project"]["version"]


def _numeric_version(version: str) -> tuple[int, int, int, int]:
    # PEP440 프리릴리스(rc1)·dev(.dev1)·로컬(+meta) 식별자는 숫자가 아니라
    # 마지막 릴리스 세그먼트에 바로 붙거나("0.3.0rc1") 구분자로 붙는다
    # ("0.3.0.dev1", "0.3.0+meta"). Windows 버전 리소스는 숫자 4개뿐이라
    # 선두의 점-구분 숫자열만 취한다.
    match = re.match(r"\d+(\.\d+)*", version)
    if not match:
        raise ValueError(f"버전에서 숫자 부분을 찾을 수 없습니다: {version}")
    parts = [int(part) for part in match.group().split(".")]
    if len(parts) > 4:
        raise ValueError(f"Windows 버전은 숫자 4개 이하여야 합니다: {version}")
    return tuple((parts + [0] * 4)[:4])  # type: ignore[return-value]


def _resource(product: dict[str, str], version: str) -> str:
    numeric = ", ".join(str(value) for value in _numeric_version(version))
    return f'''# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(filevers=({numeric}), prodvers=({numeric}), mask=0x3F,
    flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[StringFileInfo([StringTable("040904B0", [
    StringStruct("ProductName", "{product['product_name']}"),
    StringStruct("FileDescription", "{product['description']}"),
    StringStruct("FileVersion", "{version}"),
    StringStruct("ProductVersion", "{version}"),
    StringStruct("OriginalFilename", "{product['filename']}"),
    StringStruct("InternalName", "{product['internal_name']}"),
    StringStruct("LegalCopyright", ""),
  ])]), VarFileInfo([VarStruct("Translation", [1033, 1200])])],
)
'''


def _package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


#: unminified 번들이 남기는 vendor 경계 주석. 값은 ``node_modules/`` 뒤의 경로다.
#:
#: ``$`` 는 ``\r`` **앞에서 멈추지 않으므로** CRLF 산출물에서 이 그물이 조용히 0건이 된다.
#: 산출물 계약(``tests/artifact_contract/test_build_metadata.py``)이 CRLF 입력을 직접 대조한다 —
#: 개행 형식 때문에 수집이 조용히 0건이 되지 않도록 개행 앞 ``\r`` 을 명시로 문다(L16 반증).
_VENDOR_REGION_RE = re.compile(
    r"^//#region node_modules/(?P<path>[^\r\n]+?)\r?$", re.MULTILINE
)


def _vendor_package_name(region_path: str) -> str:
    """중첩 설치는 **마지막** ``node_modules/`` 뒤가 진짜 패키지다.

    ``react-dom/node_modules/scheduler/index.js`` 를 앞에서 읽으면 ``react-dom`` 으로
    보고돼, 중복 사본이 정상 이름표를 달고 지나간다(L16 반증).
    """
    tail = region_path.rsplit("node_modules/", 1)[-1]
    parts = tail.split("/")
    return f"{parts[0]}/{parts[1]}" if parts[0].startswith("@") else parts[0]


def _shipped_runtime_packages(repo_root: Path, artifact_root: Path) -> dict[str, str]:
    """출하 바이트가 실제로 담은 런타임 패키지 → 버전(R5-03).

    이름은 **산출물에서 유도**한다 — 손으로 적은 목록은 실물과 어긋나는 날이 오고, 그때
    메타데이터는 조용히 거짓을 말한다. 버전은 ``package-lock.json`` 에서 읽는다(이미 해시로
    봉인에 결속돼 있는 단일 출처).

    같은 사실은 ``tests/artifact_contract/test_build_metadata.py`` 가 정적 폐포 계약·lock과
    **대조**하고, 여기는 산출물에서 보고를 유도한다.
    """
    names: set[str] = set()
    for path in sorted(artifact_root.rglob("*.js")):
        text = path.read_text(encoding="utf-8")
        names.update(
            _vendor_package_name(match.group("path"))
            for match in _VENDOR_REGION_RE.finditer(text)
        )
    if not names:
        raise SystemExit(
            "출하 번들에서 런타임 패키지 경계를 하나도 찾지 못했습니다 — "
            "React 런타임이 실려 있어야 하고, 경계 주석은 unminified 빌드의 산출물입니다."
        )

    lock = json.loads((repo_root / "package-lock.json").read_text(encoding="utf-8"))
    packages = lock.get("packages", {})
    resolved: dict[str, str] = {}
    for name in sorted(names):
        entry = packages.get(f"node_modules/{name}")
        version = entry.get("version") if isinstance(entry, dict) else None
        if not version:
            raise SystemExit(
                f"출하 런타임 패키지의 lock 항목을 찾지 못했습니다: {name}"
            )
        resolved[name] = str(version)
    return resolved


def _web_metadata(repo_root: Path, *, skip_reason: str | None) -> dict[str, object]:
    """이 빌드가 실은 sealed web artifact 의 identity 를 릴리스 메타데이터에 싣는다.

    프런트를 싣는지 여부는 **빌드 계획의 속성**이지 디스크 상태가 아니다. 그래서 호출자가
    말한 대로만 움직인다:

    - ``skip_reason`` 이 없으면(=filler 를 싣는 빌드) 반드시 해소한다. ``resolve_web_artifact``
      는 fail-closed 라 seal·전체 트리·source 신선도를 통과하지 못하면 예외를 던지고, 그래서
      여기 실리는 값은 언제나 **검증을 통과한** 산출물의 것이다.
    - ``skip_reason`` 이 있으면(=CLI 전용 빌드) **산출물을 찾지도 않는다**. 앞선 filler 빌드가
      남긴 유효한 ``build/web`` 이 작업 폴더에 그대로 있어도 마찬가지다 — 그것을 발견해
      기록하면 ``datas=[]`` 인 CLI 번들이 프런트를 실었다고 메타데이터가 **거짓을 말한다**
      (#383 리뷰 지적, 실측: `-Target cli` 가 `present:true` 를 기록하는데
      `dist/hwpx-cli/_internal/web` 은 없었다).

    어느 쪽이든 키를 조용히 비우지 않는다 — 부재는 사유와 함께 기록된다.
    """
    if skip_reason is not None:
        return {"present": False, "reason": skip_reason}

    try:
        artifact = resolve_web_artifact(repo_root=repo_root)
    except (OSError, WebArtifactViolation) as exc:
        raise SystemExit(
            f"sealed web artifact 를 요구했지만 검증에 실패했습니다: {exc}"
        ) from exc

    seal = json.loads((artifact.root / SEAL_FILENAME).read_text(encoding="utf-8"))
    return {
        "present": True,
        "artifact_id": artifact.artifact_id,
        "tree_sha256": artifact.tree_sha256,
        "source_commit": seal["source"]["commit"],
        "package_lock_sha256": seal["package_lock"]["sha256"],
        # toolchain 은 **만든 도구**(node·npm·vite)다. R5 이후 제품 UI 런타임은 React 이고,
        # 그 사실이 릴리스 서술 자산에서 읽히지 않으면 "무엇을 실었는지 말할 수 있어야 한다"가
        # 반만 참이다 — 해시(package_lock_sha256)는 결속하지만 이름을 말하지는 않는다.
        "toolchain": seal["toolchain"],
        "runtime_packages": _shipped_runtime_packages(repo_root, artifact.root),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT / "build" / "version")
    # 프런트를 싣는지는 호출자가 **말해야** 한다. 기본값을 두면 그 기본값이 곧 추측이 되고,
    # 디스크에 남은 앞선 빌드의 산출물이 답을 대신 정해버린다(#383 리뷰).
    plan = parser.add_mutually_exclusive_group(required=True)
    plan.add_argument(
        "--require-web",
        action="store_true",
        help="이 빌드는 프런트를 싣는다 — sealed build/web 이 없거나 검증에 실패하면 실패",
    )
    plan.add_argument(
        "--no-web",
        metavar="REASON",
        help="이 빌드는 프런트를 싣지 않는다 — 산출물을 찾지 않고 사유와 함께 부재를 기록",
    )
    args = parser.parse_args(argv)
    if args.no_web is not None and not args.no_web.strip():
        parser.error("--no-web 에는 사유가 필요합니다")
    args.out.mkdir(parents=True, exist_ok=True)

    version = _version()
    for key, product in PRODUCTS.items():
        (args.out / f"hwpx_{key}_version.txt").write_text(
            _resource(product, version), encoding="utf-8"
        )
    version_info = ".".join(str(part) for part in _numeric_version(version))
    (args.out / "version.iss").write_text(
        f'#define AppVersion "{version}"\n'
        f'#define AppVersionInfo "{version_info}"\n',
        encoding="utf-8",
    )
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False
    ).stdout.strip()
    metadata = {
        "version": version,
        "commit": commit or None,
        "python": sys.version.split()[0],
        "pyinstaller": _package_version("pyinstaller"),
        "uv_lock_sha256": _file_sha256(ROOT / "uv.lock"),
        "web": _web_metadata(ROOT, skip_reason=args.no_web),
    }
    (args.out / "build-metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"build metadata: {version} -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
