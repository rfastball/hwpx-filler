"""N-03 M1: 제품 Vite 산출물 seal producer와 source/frozen resolver 계약."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

import pytest

import hwpxfiller.web_artifact as web_artifact
from hwpxfiller.web_artifact import (
    SEAL_FILENAME,
    VITE_MANIFEST_PATH,
    ToolchainVersions,
    WebArtifactViolation,
    resolve_web_artifact,
    seal_repository_web_artifact,
)

COMMIT = "a" * 40
OTHER_COMMIT = "b" * 40
TOOLCHAIN = ToolchainVersions(node="24.18.1", npm="11.16.0", vite="8.1.5")
_ORIGINAL_DETECT_TOOLCHAIN = web_artifact._detect_toolchain


@dataclass(frozen=True)
class ArtifactRepo:
    root: Path

    @property
    def frontend_entry(self) -> Path:
        return self.root / "frontend" / "src" / "main.js"

    @property
    def lock_path(self) -> Path:
        return self.root / "package-lock.json"

    @property
    def config_path(self) -> Path:
        return self.root / "vite.config.mjs"

    @property
    def artifact_root(self) -> Path:
        return self.root / "build" / "web"

    @property
    def seal_path(self) -> Path:
        return self.artifact_root / SEAL_FILENAME

    @property
    def index_path(self) -> Path:
        return self.artifact_root / "index.html"

    @property
    def entry_path(self) -> Path:
        return self.artifact_root / "assets" / "main.js"

    @property
    def manifest_path(self) -> Path:
        return self.artifact_root / Path(VITE_MANIFEST_PATH)


def _write_repo(root: Path) -> ArtifactRepo:
    frontend_src = root / "frontend" / "src"
    frontend_src.mkdir(parents=True)
    (frontend_src / "main.js").write_text(
        "import '../styles.css';\nwindow.boot = () => 'ready';\n",
        encoding="utf-8",
    )
    (root / "frontend" / "styles.css").write_text(
        ":root { color-scheme: light dark; }\n",
        encoding="utf-8",
    )
    (root / ".node-version").write_text("24.18.1\n", encoding="utf-8")
    (root / ".npmrc").write_text("engine-strict=true\n", encoding="utf-8")
    (root / "package.json").write_text(
        json.dumps(
            {
                "private": True,
                "packageManager": "npm@11.16.0",
                "devDependencies": {"vite": "8.1.5"},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "package-lock.json").write_text(
        json.dumps(
            {
                "name": "web-fixture",
                "lockfileVersion": 3,
                "packages": {"": {"devDependencies": {"vite": "8.1.5"}}},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "vite.config.mjs").write_text(
        "export default { base: './', build: { manifest: true } };\n",
        encoding="utf-8",
    )
    # tsconfig 는 R2-04 에서 봉인 입력으로 편입됐다(`_SOURCE_CONFIG_PATHS`) — Vite 의 `.ts`
    # 변환이 읽는 실빌드 입력이라서다. 없으면 `_required_file_record` 가 시끄럽게 죽는다.
    (root / "tsconfig.json").write_text(
        json.dumps({"compilerOptions": {"strict": True}}, indent=2) + "\n",
        encoding="utf-8",
    )

    artifact_root = root / "build" / "web"
    (artifact_root / "assets").mkdir(parents=True)
    (artifact_root / ".vite").mkdir()
    (artifact_root / "index.html").write_text(
        '<!doctype html><script type="module" src="./assets/main.js"></script>\n',
        encoding="utf-8",
    )
    (artifact_root / "assets" / "main.js").write_text(
        'const boot=()=> "ready";boot();\n',
        encoding="utf-8",
    )
    (artifact_root / "assets" / "app.css").write_text(
        ":root{color-scheme:light dark}\n",
        encoding="utf-8",
    )
    (artifact_root / ".vite" / "manifest.json").write_text(
        json.dumps(
            {
                "index.html": {
                    "file": "assets/main.js",
                    "isEntry": True,
                    "src": "index.html",
                }
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return ArtifactRepo(root)


@pytest.fixture
def unsealed_repo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> ArtifactRepo:
    fixture = _write_repo(tmp_path / "repo")
    monkeypatch.setattr(web_artifact, "_assert_source_inputs_clean", lambda _root: None)
    monkeypatch.setattr(web_artifact, "_current_git_commit", lambda _root: COMMIT)
    monkeypatch.setattr(
        web_artifact,
        "_detect_toolchain",
        lambda _root, **_kwargs: TOOLCHAIN,
    )
    return fixture


@pytest.fixture
def sealed_repo(unsealed_repo: ArtifactRepo) -> ArtifactRepo:
    seal_repository_web_artifact(unsealed_repo.root)
    return unsealed_repo


def _seal_document(fixture: ArtifactRepo) -> dict:
    document = json.loads(fixture.seal_path.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def _write_seal_document(fixture: ArtifactRepo, document: dict) -> None:
    fixture.seal_path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _frozen_root(fixture: ArtifactRepo, tmp_path: Path) -> Path:
    frozen_root = tmp_path / "frozen"
    shutil.copytree(fixture.artifact_root, frozen_root / "web")
    return frozen_root


def test_producer_writes_complete_stable_self_excluding_seal(
    sealed_repo: ArtifactRepo,
) -> None:
    first = resolve_web_artifact(repo_root=sealed_repo.root)
    document = _seal_document(sealed_repo)

    assert document["schema"] == 1
    assert document["artifact_id"] == first.artifact_id
    assert document["source"]["commit"] == COMMIT
    assert len(document["source"]["input_sha256"]) == 64
    assert document["package_lock"]["path"] == "package-lock.json"
    assert document["toolchain"] == {
        "node": "24.18.1",
        "npm": "11.16.0",
        "vite": "8.1.5",
    }
    assert document["vite_manifest"]["path"] == VITE_MANIFEST_PATH
    output_paths = [record["path"] for record in document["output"]["files"]]
    assert output_paths == [
        ".vite/manifest.json",
        "assets/app.css",
        "assets/main.js",
        "index.html",
    ]
    assert SEAL_FILENAME not in output_paths
    assert all(record["size"] >= 0 and len(record["sha256"]) == 64
               for record in document["output"]["files"])

    second = seal_repository_web_artifact(sealed_repo.root)
    assert second == first
    assert _seal_document(sealed_repo) == document


def test_source_and_frozen_resolvers_return_same_artifact_identity(
    sealed_repo: ArtifactRepo,
    tmp_path: Path,
) -> None:
    source = resolve_web_artifact(repo_root=sealed_repo.root)
    frozen = resolve_web_artifact(frozen_root=_frozen_root(sealed_repo, tmp_path))

    assert source.artifact_id == frozen.artifact_id
    assert source.tree_sha256 == frozen.tree_sha256
    assert source.index_path == sealed_repo.index_path.resolve()
    assert frozen.index_path.name == "index.html"


def test_frozen_resolver_never_uses_git_or_build_toolchain(
    sealed_repo: ArtifactRepo,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected(*_args, **_kwargs):
        raise AssertionError("frozen resolver attempted source/tool lookup")

    monkeypatch.setattr(web_artifact, "_current_git_commit", unexpected)
    monkeypatch.setattr(web_artifact, "_detect_toolchain", unexpected)

    verified = resolve_web_artifact(frozen_root=_frozen_root(sealed_repo, tmp_path))

    assert verified.artifact_id == _seal_document(sealed_repo)["artifact_id"]


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({}, "exactly one"),
        (
            {"repo_root": Path("repo"), "frozen_root": Path("frozen")},
            "exactly one",
        ),
    ],
)
def test_resolver_requires_exactly_one_runtime_mode(
    kwargs: dict[str, Path],
    message: str,
) -> None:
    with pytest.raises(WebArtifactViolation, match=message):
        resolve_web_artifact(**kwargs)


def test_artifact_directory_missing_is_loud(sealed_repo: ArtifactRepo) -> None:
    shutil.rmtree(sealed_repo.artifact_root)

    with pytest.raises(WebArtifactViolation, match="web artifact directory missing"):
        resolve_web_artifact(repo_root=sealed_repo.root)


def test_artifact_seal_missing_is_loud(sealed_repo: ArtifactRepo) -> None:
    sealed_repo.seal_path.unlink()

    with pytest.raises(WebArtifactViolation, match="web artifact seal missing"):
        resolve_web_artifact(repo_root=sealed_repo.root)


def test_multiple_artifact_seals_are_loud(sealed_repo: ArtifactRepo) -> None:
    nested = sealed_repo.artifact_root / "assets" / SEAL_FILENAME
    nested.write_text("{}\n", encoding="utf-8")

    with pytest.raises(WebArtifactViolation, match="exactly one root seal"):
        resolve_web_artifact(repo_root=sealed_repo.root)


def test_vite_manifest_missing_is_loud(sealed_repo: ArtifactRepo) -> None:
    sealed_repo.manifest_path.unlink()

    with pytest.raises(WebArtifactViolation, match="Vite manifest missing"):
        resolve_web_artifact(repo_root=sealed_repo.root)


def test_listed_output_missing_is_loud(sealed_repo: ArtifactRepo) -> None:
    sealed_repo.entry_path.unlink()

    with pytest.raises(
        WebArtifactViolation,
        match=r"listed web artifact file missing: assets/main\.js",
    ):
        resolve_web_artifact(repo_root=sealed_repo.root)


def test_extra_stale_output_is_loud(sealed_repo: ArtifactRepo) -> None:
    stale = sealed_repo.artifact_root / "assets" / "stale.js"
    stale.write_text("stale\n", encoding="utf-8")

    with pytest.raises(
        WebArtifactViolation,
        match=r"extra stale web artifact file: assets/stale\.js",
    ):
        resolve_web_artifact(repo_root=sealed_repo.root)


def test_producer_refuses_a_sourcemap_in_the_shipped_tree(
    unsealed_repo: ArtifactRepo,
) -> None:
    """봉인 **생산**이 먼저 거절한다 — 사본 넷이 같은 sourcemap 을 들면 정체성은 참이다.

    이 결함류는 `build.sourcemap` 한 줄이 만든다. 정체성 축은 그것을 통과시키므로(네 사본이
    똑같이 실어 나른다) 성질을 재는 술어가 따로 서지 않으면 조용히 출하된다(L12).
    """
    (unsealed_repo.artifact_root / "assets" / "main.js.map").write_text(
        '{"version":3,"sources":["../frontend/src/main.js"]}\n',
        encoding="utf-8",
    )

    with pytest.raises(
        WebArtifactViolation,
        match=r"shipped-composition closure: assets/main\.js\.map",
    ):
        seal_repository_web_artifact(unsealed_repo.root)

    # **생산자 호출 자리가 실재하는지**를 여기서 센다. 봉인 함수는 마지막에
    # ``_verify_artifact`` 를 다시 부르므로, 생산 쪽 호출을 지워도 위 ``raises`` 는 그대로
    # 통과한다 — 다만 그때는 위반 트리의 seal 이 **이미 디스크에 쓰인 뒤** 실패한다.
    # 그 차이를 단언하지 않으면 이 테스트는 이름이 가리키는 자리를 안 지킨다(L16 반증).
    assert not unsealed_repo.seal_path.exists(), (
        "위반 트리의 seal 이 디스크에 기록됐습니다 — 생산자가 쓰기 전에 거절해야 합니다"
    )


def test_resolver_refuses_a_dev_asset_that_was_sealed_with_the_tree(
    sealed_repo: ArtifactRepo,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """소비 쪽도 같은 술어를 진다 — 생산자만 물면 이미 봉인된 트리는 영영 통과한다.

    봉인 기록째 위반을 담은 상태(다른 생산자·낡은 봉인)를 재현하려고 파일을 더한 뒤 **다시**
    봉인한다. 생산 술어를 잠시 걷어 그 상태를 만든 다음, 소비 경로가 혼자서도 거절하는지 본다.
    """
    intruder = sealed_repo.artifact_root / "assets" / "main.ts"
    intruder.write_text("export const boot = () => 'ready';\n", encoding="utf-8")
    with monkeypatch.context() as sealing:
        sealing.setattr(web_artifact, "_validate_output_composition", lambda _records: None)
        seal_repository_web_artifact(sealed_repo.root)

    with pytest.raises(
        WebArtifactViolation,
        match=r"shipped-composition closure: assets/main\.ts",
    ):
        resolve_web_artifact(repo_root=sealed_repo.root)


def test_frozen_resolver_refuses_the_same_composition_violation(
    sealed_repo: ArtifactRepo,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """frozen 사본도 같은 술어를 진다 — 정체성만 대조하면 실린 것을 못 묻는다."""
    intruder = sealed_repo.artifact_root / "assets" / "vite.config.mjs"
    intruder.write_text("export default {};\n", encoding="utf-8")
    with monkeypatch.context() as sealing:
        sealing.setattr(web_artifact, "_validate_output_composition", lambda _records: None)
        seal_repository_web_artifact(sealed_repo.root)
        frozen_root = _frozen_root(sealed_repo, tmp_path)

    with pytest.raises(
        WebArtifactViolation,
        match=r"shipped-composition closure: assets/vite\.config\.mjs",
    ):
        resolve_web_artifact(frozen_root=frozen_root)


def test_composition_closure_accepts_exactly_todays_shipped_kinds() -> None:
    """음성 대조 — 정당한 산출물을 거절하지 않는가.

    양성만 세우면 "전부 거절"도 초록이다. 오늘 실제로 출하되는 형식 넷과 루트 파일 둘을
    직접 통과시켜, 이 폐포가 무엇을 **허용**하는지도 결과로 남긴다.
    """
    shipped = (
        "index.html",
        VITE_MANIFEST_PATH,
        "assets/index-DMG.js",
        "assets/style-30Od.css",
        "assets/narmi-mark.svg",
        "assets/PretendardGOVVariable.woff2",
    )
    records = tuple(
        web_artifact._FileRecord(path=path, size=1, sha256="0" * 64) for path in shipped
    )
    web_artifact._validate_output_composition(records)

    for offender in ("assets/main.js.map", "assets/deep/nested.js", "package.json"):
        with pytest.raises(WebArtifactViolation, match="shipped-composition closure"):
            web_artifact._validate_output_composition(
                (*records, web_artifact._FileRecord(path=offender, size=1, sha256="0" * 64))
            )


def test_one_byte_output_mutation_is_loud(sealed_repo: ArtifactRepo) -> None:
    before = sealed_repo.entry_path.read_bytes()
    after = bytearray(before)
    after[0] ^= 1
    sealed_repo.entry_path.write_bytes(after)
    assert len(before) == len(after)
    assert sum(left != right for left, right in zip(before, after, strict=True)) == 1

    with pytest.raises(
        WebArtifactViolation,
        match=r"web artifact byte digest mismatch: assets/main\.js",
    ):
        resolve_web_artifact(repo_root=sealed_repo.root)


def test_frontend_source_stale_is_loud(sealed_repo: ArtifactRepo) -> None:
    sealed_repo.frontend_entry.write_text(
        sealed_repo.frontend_entry.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )

    with pytest.raises(WebArtifactViolation, match="frontend/config source input stale"):
        resolve_web_artifact(repo_root=sealed_repo.root)


def test_vite_config_stale_is_loud(sealed_repo: ArtifactRepo) -> None:
    sealed_repo.config_path.write_text(
        sealed_repo.config_path.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )

    with pytest.raises(WebArtifactViolation, match="frontend/config source input stale"):
        resolve_web_artifact(repo_root=sealed_repo.root)


def test_tsconfig_stale_is_loud(sealed_repo: ArtifactRepo) -> None:
    """tsconfig 만 고친 채 봉인을 재사용하는 사각(R2-01 인계 ②)이 닫혔는가 — R2-04 편입의
    음성 대조. 편입 전에는 이 변조가 신선도 검사를 조용히 통과했다."""
    tsconfig = sealed_repo.root / "tsconfig.json"
    tsconfig.write_text(
        tsconfig.read_text(encoding="utf-8").replace('"strict": true', '"strict": false'),
        encoding="utf-8",
    )

    with pytest.raises(WebArtifactViolation, match="frontend/config source input stale"):
        resolve_web_artifact(repo_root=sealed_repo.root)


def test_seal_records_tsconfig_as_source_input(sealed_repo: ArtifactRepo) -> None:
    """양성 — 봉인 문서의 source 레코드에 tsconfig 가 실제로 실린다(편입의 존재 증명)."""
    document = _seal_document(sealed_repo)
    recorded = {record["path"] for record in document["source"]["files"]}
    assert "tsconfig.json" in recorded


def test_package_lock_stale_is_loud(sealed_repo: ArtifactRepo) -> None:
    sealed_repo.lock_path.write_text(
        sealed_repo.lock_path.read_text(encoding="utf-8").replace(
            '"lockfileVersion": 3',
            '"lockfileVersion": 4',
        ),
        encoding="utf-8",
    )

    with pytest.raises(WebArtifactViolation, match="package-lock input stale"):
        resolve_web_artifact(repo_root=sealed_repo.root)


def test_wrong_source_commit_is_loud(
    sealed_repo: ArtifactRepo,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(web_artifact, "_current_git_commit", lambda _root: OTHER_COMMIT)

    with pytest.raises(WebArtifactViolation, match="source commit mismatch"):
        resolve_web_artifact(repo_root=sealed_repo.root)


def test_wrong_declared_source_input_digest_is_loud(sealed_repo: ArtifactRepo) -> None:
    document = _seal_document(sealed_repo)
    document["source"]["input_sha256"] = "0" * 64
    _write_seal_document(sealed_repo, document)

    with pytest.raises(WebArtifactViolation, match="source input digest.*inconsistent"):
        resolve_web_artifact(repo_root=sealed_repo.root)


def test_wrong_artifact_id_is_loud(sealed_repo: ArtifactRepo) -> None:
    document = _seal_document(sealed_repo)
    document["artifact_id"] = "0" * 64
    _write_seal_document(sealed_repo, document)

    with pytest.raises(WebArtifactViolation, match="web artifact ID mismatch"):
        resolve_web_artifact(repo_root=sealed_repo.root)


def test_source_resolver_rejects_sealed_toolchain_different_from_current_pins(
    sealed_repo: ArtifactRepo,
) -> None:
    document = _seal_document(sealed_repo)
    document["toolchain"]["node"] = "23.0.0"
    core = {key: value for key, value in document.items() if key != "artifact_id"}
    document["artifact_id"] = web_artifact._canonical_sha256(core)
    _write_seal_document(sealed_repo, document)

    with pytest.raises(
        WebArtifactViolation,
        match="sealed toolchain does not match current exact pins",
    ):
        resolve_web_artifact(repo_root=sealed_repo.root)


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (
            '<!doctype html><script type="module" src="/assets/main.js"></script>\n',
            r"forbidden absolute /assets URL",
        ),
        (
            '<!doctype html><script type="module" src="file:///tmp/main.js"></script>\n',
            "forbidden file: URL",
        ),
        (
            '<!doctype html><script src="https://cdn.example/main.js"></script>\n',
            r"forbidden external HTTP\(S\) resource",
        ),
        # HTML 에는 불활성 면제가 **없다**(R2-01 · #405 + #484 Codex P2) — 등장 자체가
        # 로딩 맥락일 개연성이 지배적이라, 면제 목록의 URL 이라도 HTML 에선 죽는다.
        (
            '<!doctype html><img src="https://react.dev/errors/418">\n',
            r"forbidden external HTTP\(S\) resource",
        ),
        (
            '<!doctype html><script src="http://www.w3.org/2000/svg"></script>\n',
            r"forbidden external HTTP\(S\) resource",
        ),
        (
            '<!doctype html><script type="module" src="/@vite/client"></script>\n',
            "forbidden Vite dev client",
        ),
    ],
)
def test_producer_rejects_forbidden_runtime_reference(
    unsealed_repo: ArtifactRepo,
    content: str,
    message: str,
) -> None:
    unsealed_repo.index_path.write_text(content, encoding="utf-8")

    with pytest.raises(WebArtifactViolation, match=message):
        seal_repository_web_artifact(unsealed_repo.root)


@pytest.mark.parametrize(
    "snippet",
    [
        # 정확 열거 항목을 **연장**해 허용을 훔치는 모양 — 토큰 전체 대조가 잡는다.
        'const ns = "http://www.w3.org/2000/svg.evil.example/x.js";\n',
        # 허용 접두를 닮았지만 다른 경로.
        'const doc = "https://react.dev/errors-evil";\n',
        # 면제 목록 밖의 평범한 외부 URL.
        'const cdn = "https://cdn.example/x.js";\n',
    ],
)
def test_producer_rejects_non_inert_urls_even_inside_the_js_bundle(
    unsealed_repo: ArtifactRepo,
    snippet: str,
) -> None:
    """음성 대조(R2-01 · #405) — `.js` 면제는 열거 항목 그 토큰뿐이다."""
    js_path = unsealed_repo.artifact_root / "assets" / "main.js"
    js_path.write_text(js_path.read_text(encoding="utf-8") + snippet, encoding="utf-8")

    with pytest.raises(
        WebArtifactViolation, match=r"forbidden external HTTP\(S\) resource"
    ):
        seal_repository_web_artifact(unsealed_repo.root)


def test_producer_accepts_the_inert_url_census_of_a_react_bundle(
    unsealed_repo: ArtifactRepo,
) -> None:
    """양성 대조(R2-01 · #405) — React 번들의 불활성 URL 전수는 봉인을 통과한다.

    표본은 실측 그대로이고 **자리도 실측 그대로**(`.js` 번들 문자열)다: XML 네임스페이스
    식별자 넷(``createElementNS`` 의 이름 인자 — 어떤 로더도 fetch 하지 않는다)과 프로덕션
    오류 메시지의 문서 링크(코드가 뒤에 붙는 접두). 무맥락 전면 금지로 되돌리면 이 대조가
    빨갛게 서서 「프레임워크 번들 전부가 거짓 빨강」이던 자리를 지킨다.
    """
    js_path = unsealed_repo.artifact_root / "assets" / "main.js"
    js_path.write_text(
        js_path.read_text(encoding="utf-8")
        + 'createElementNS("http://www.w3.org/2000/svg");\n'
        + 'createElementNS("http://www.w3.org/1999/xlink");\n'
        + 'createElementNS("http://www.w3.org/XML/1998/namespace");\n'
        + 'createElementNS("http://www.w3.org/1998/Math/MathML");\n'
        + 'const help = "https://react.dev/errors/" + code;\n',
        encoding="utf-8",
    )

    artifact = seal_repository_web_artifact(unsealed_repo.root)

    assert artifact.index_path == unsealed_repo.index_path


def test_empty_vite_manifest_is_loud(unsealed_repo: ArtifactRepo) -> None:
    unsealed_repo.manifest_path.write_text("{}\n", encoding="utf-8")

    with pytest.raises(WebArtifactViolation, match="Vite manifest is empty"):
        seal_repository_web_artifact(unsealed_repo.root)


def test_producer_records_versions_measured_from_actual_commands(
    unsealed_repo: ArtifactRepo,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(web_artifact, "_detect_toolchain", _ORIGINAL_DETECT_TOOLCHAIN)
    versions = {"Node": "24.18.1", "npm": "11.16.0", "Vite": "8.1.5"}
    monkeypatch.setattr(
        web_artifact,
        "_command_version",
        lambda _command, *, cwd, role: versions[role],
    )

    seal_repository_web_artifact(
        unsealed_repo.root,
        node_command="node-exact",
        npm_command="npm-exact.cmd",
        vite_command="vite-exact.cmd",
    )

    assert _seal_document(unsealed_repo)["toolchain"] == {
        "node": "24.18.1",
        "npm": "11.16.0",
        "vite": "8.1.5",
    }


def test_producer_rejects_actual_toolchain_different_from_pins(
    unsealed_repo: ArtifactRepo,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(web_artifact, "_detect_toolchain", _ORIGINAL_DETECT_TOOLCHAIN)
    versions = {"Node": "25.6.0", "npm": "11.16.0", "Vite": "8.1.5"}
    monkeypatch.setattr(
        web_artifact,
        "_command_version",
        lambda _command, *, cwd, role: versions[role],
    )

    with pytest.raises(WebArtifactViolation, match="does not match exact pins"):
        seal_repository_web_artifact(
            unsealed_repo.root,
            node_command="node-wrong",
            npm_command="npm-exact.cmd",
            vite_command="vite-exact.cmd",
        )


def test_producer_rejects_non_exact_vite_declaration(
    unsealed_repo: ArtifactRepo,
) -> None:
    package_path = unsealed_repo.root / "package.json"
    package = json.loads(package_path.read_text(encoding="utf-8"))
    package["devDependencies"]["vite"] = "^8.1.5"
    package_path.write_text(json.dumps(package), encoding="utf-8")

    with pytest.raises(WebArtifactViolation, match="must be an exact semantic version"):
        web_artifact._declared_toolchain(unsealed_repo.root)


def test_producer_refuses_dirty_source_inputs(
    unsealed_repo: ArtifactRepo,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        web_artifact,
        "_assert_source_inputs_clean",
        lambda _root: (_ for _ in ()).throw(
            WebArtifactViolation("refusing to seal a dirty source tree")
        ),
    )

    with pytest.raises(WebArtifactViolation, match="dirty source tree"):
        seal_repository_web_artifact(unsealed_repo.root)
