"""P1-02C 효과 그래프 축 — persistence·external effect·host 경계의 전수 분류·digest 핀 원장.

02A 정적 그래프(기반+파생 사실)를 **입력**으로 받아, 폐포가 바깥 세계에 닿는 자리를
``reads_external``/``writes_external``/``invokes_external`` 로 분류하고, 효과를 품은 concrete
클래스의 조립 자리를 ``composes`` 로 잇는다(#515 설계 패킷). 제품 코드 접촉 0 — 전부 파생이다.

분류의 계약(패킷 「effect 후보 = direct effect ∪ explicit pure exclusion 독립 oracle」):

- 폐포의 모든 ``ext:`` 접촉 좌표는 **효과 분류 또는 명시 순수 제외 중 정확히 한쪽**에 앉는다.
  등록되지 않은 외부 이름이 나타나면 render 가 시끄럽게 죽는다 — 새 의존성이 분류 없이
  조용히 지나가는 세 번째 바구니를 만들지 않는다.
- 순수 path/naming 계산(``os.path.join``·``pathlib.Path`` 값 생성 등)은 '파일을 다룬다'는
  이유로 효과로 승격하지 않는다(#515 불변식). 그 판정은 ``path_value`` 순수 라벨로 **명시**
  기록되어 감사 가능하다.
- 함수-지역 ``import X`` 뒤의 ``X.attr(...)`` 는 기반 수집기가 ``?:local:`` 로 정직하게
  남긴 자리다. 지역 바인딩이 그 import 하나뿐임을 어휘 스코프 사슬로 증명할 수 있을 때만
  ``ext:`` 로 닫아 같은 표로 분류한다 — 증명 불가면 열린 원장 행으로 남긴다(임의 추측 금지).
- 수신자 타입을 모르는 ``?:`` 호출 중 **Path 판별력이 있는** 말단 메서드 이름(``write_text``
  등)은 ``INFERRED`` 등급의 효과 후보로만 적는다 — FACT 로 위조하지 않고, 그렇다고 파일
  쓰기 자리가 계측 밖으로 새게 두지도 않는다. ``save``/``read``/``replace`` 처럼 str 등과
  겹치는 이름은 넣지 않는다(거짓 양성이 판별력을 죽인다).

커밋 생성물은 02A 와 같은 규약: 전 사실이 아니라 **digest 핀 + 파생 원장**
(``docs/factgraph/effect_graph_02c.toml``)이고, 기반/02A digest 를 함께 실어 P1-03 이
「같은 측정 위에 선 shard 인가」를 검증한다.
"""

from __future__ import annotations

import ast
import json
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .closure import Closure
from .collect import call_site_anchor
from .schema import (
    Evidence,
    Fact,
    FactGraphError,
    Provenance,
    facts_digest,
    is_symbol_ref,
    parse_symbol_id,
)
from .static_graph import (
    BASELINE_SHA,
    StaticGraphResult,
    _baseline_source_problems,
    build as build_static,
)

COLLECTOR = "factgraph.effect_graph"

LEDGER_REL_PATH = "docs/factgraph/effect_graph_02c.toml"
REGEN_COMMAND = "uv run python scripts/gen_effect_graph_02c.py"

_EFFECT = "effect"
_PURE = "pure"

#: ``ext:`` dotted 이름 → 판정. 최장 dotted 접두 일치로 찾는다.
#:
#: 등록 규율(조용한 오분류 방지가 이 표의 존재 이유다):
#:
#: - **root 전체가 한 판정인 안전한 모듈만** root 키로 등록한다(``typing`` 등).
#: - 효과·순수가 섞이는 위험 모듈(``os``·``pathlib``·``ctypes``·``lxml``·``time`` 등)은
#:   **관측된 정확 이름만** 등록한다 — 새 이름이 나타나면 등록 전까지 render 가 빨갛다.
#:   특히 ``lxml.etree`` 를 접두로 등록하면 미래의 ``lxml.etree.parse``(파일 읽기)가
#:   조용히 순수로 분류된다 — 그래서 in-memory API 를 이름 단위로 명시한다.
#: - 순수 라벨: ``computation``(일반 계산) · ``path_value``(경로 값 계산 — #515 불변식의
#:   명시 기록) · ``marshalling``(ctypes 선언·변환 — FFI 호출 자체가 아니다) ·
#:   ``xml_memory``(lxml 의 in-memory XML 처리 — HWPX 바이트는 archive/fs 가 나른다).
CLASSIFICATION: "dict[str, tuple[str, str, str]]" = {
    # ---- 순수 root(접두 전체 순수) ---------------------------------------
    "__future__": (_PURE, "", "computation"),
    "argparse": (_PURE, "", "computation"),
    "calendar": (_PURE, "", "computation"),
    "collections": (_PURE, "", "computation"),
    "copy": (_PURE, "", "computation"),
    "csv": (_PURE, "", "computation"),  # reader 는 이미 열린 반복자를 파싱한다 — fs 는 open 몫
    "dataclasses": (_PURE, "", "computation"),
    "difflib": (_PURE, "", "computation"),
    "enum": (_PURE, "", "computation"),
    "hashlib": (_PURE, "", "computation"),
    "inspect": (_PURE, "", "computation"),
    "io": (_PURE, "", "computation"),  # BytesIO — in-memory
    "json": (_PURE, "", "computation"),  # dumps/loads — 직렬화 계산, I/O 는 별도 자리
    "operator": (_PURE, "", "computation"),
    "re": (_PURE, "", "computation"),
    "sys": (_PURE, "", "computation"),
    "threading": (_PURE, "", "computation"),  # in-process 동시성 — 외부 효과가 아니다
    "types": (_PURE, "", "computation"),
    "typing": (_PURE, "", "computation"),
    "urllib.parse": (_PURE, "", "computation"),
    "weakref": (_PURE, "", "computation"),
    # ---- builtins: open/print 만 효과, 나머지는 계산 ----------------------
    "builtins": (_PURE, "", "computation"),
    "builtins.open": (_EFFECT, "invokes_external", "fs"),  # 방향은 mode 인자 — 정적 미확정
    "builtins.print": (_EFFECT, "writes_external", "stdio"),
    # ---- os: 정확 이름만 ---------------------------------------------------
    "os.fspath": (_PURE, "", "path_value"),
    "os.path.join": (_PURE, "", "path_value"),
    "os.path.basename": (_PURE, "", "path_value"),
    "os.path.dirname": (_PURE, "", "path_value"),
    "os.path.normcase": (_PURE, "", "path_value"),
    "os.path.normpath": (_PURE, "", "path_value"),
    "os.path.splitext": (_PURE, "", "path_value"),
    "os.path.abspath": (_EFFECT, "reads_external", "env"),  # CWD 관측
    "os.path.realpath": (_EFFECT, "reads_external", "fs"),  # 심링크 해석 — FS 관측
    "os.environ": (_EFFECT, "reads_external", "env"),
    "os.environ.get": (_EFFECT, "reads_external", "env"),
    "os.getpid": (_EFFECT, "reads_external", "process"),
    "os.walk": (_EFFECT, "reads_external", "fs"),
    "os.remove": (_EFFECT, "writes_external", "fs"),
    "os.unlink": (_EFFECT, "writes_external", "fs"),
    "os.replace": (_EFFECT, "writes_external", "fs"),
    "os.rename": (_EFFECT, "writes_external", "fs"),
    "os.makedirs": (_EFFECT, "writes_external", "fs"),
    "os.fdopen": (_EFFECT, "invokes_external", "fs"),
    "os.startfile": (_EFFECT, "invokes_external", "process"),
    # ---- pathlib: 값 생성은 순수, 환경 조회는 효과 -------------------------
    "pathlib.Path": (_PURE, "", "path_value"),
    "pathlib.PurePath": (_PURE, "", "path_value"),
    "pathlib.PurePosixPath": (_PURE, "", "path_value"),
    "pathlib.PureWindowsPath": (_PURE, "", "path_value"),
    "pathlib.Path.home": (_EFFECT, "reads_external", "env"),
    "pathlib.Path.cwd": (_EFFECT, "reads_external", "env"),
    # ---- 파일·아카이브·엑셀 ------------------------------------------------
    "shutil.copy2": (_EFFECT, "writes_external", "fs"),
    "shutil.rmtree": (_EFFECT, "writes_external", "fs"),
    "shutil.move": (_EFFECT, "writes_external", "fs"),
    "shutil.which": (_EFFECT, "reads_external", "env"),  # PATH 탐색
    "tempfile.mkstemp": (_EFFECT, "writes_external", "fs"),
    "tempfile.gettempdir": (_EFFECT, "reads_external", "env"),
    "zipfile.ZipFile": (_EFFECT, "invokes_external", "archive"),  # 방향은 mode 인자
    "zipfile.ZipInfo": (_PURE, "", "computation"),  # 메타데이터 값 생성
    "openpyxl.load_workbook": (_EFFECT, "reads_external", "excel"),
    # ---- lxml: 관측된 in-memory API 만 명시 순수 ---------------------------
    "lxml.etree.Element": (_PURE, "", "xml_memory"),
    "lxml.etree.SubElement": (_PURE, "", "xml_memory"),
    "lxml.etree.XMLParser": (_PURE, "", "xml_memory"),
    "lxml.etree.fromstring": (_PURE, "", "xml_memory"),
    "lxml.etree.tostring": (_PURE, "", "xml_memory"),
    "lxml.etree.strip_elements": (_PURE, "", "xml_memory"),
    # ---- 시계·엔트로피 -----------------------------------------------------
    "datetime": (_PURE, "", "computation"),
    "datetime.datetime.now": (_EFFECT, "reads_external", "clock"),
    "time.time": (_EFFECT, "reads_external", "clock"),
    "time.monotonic": (_EFFECT, "reads_external", "clock"),
    "time.perf_counter": (_EFFECT, "reads_external", "clock"),
    "time.sleep": (_EFFECT, "invokes_external", "clock"),  # 스케줄러 대기 — 관측 가능한 지연
    "uuid.uuid4": (_EFFECT, "reads_external", "entropy"),
    "secrets.compare_digest": (_PURE, "", "computation"),
    "secrets.token_urlsafe": (_EFFECT, "reads_external", "entropy"),
    # ---- 프로세스·호스트 ---------------------------------------------------
    "subprocess.run": (_EFFECT, "invokes_external", "process"),
    "subprocess.Popen": (_EFFECT, "invokes_external", "process"),
    "fcntl": (_EFFECT, "invokes_external", "lock"),  # fd 제어 전부
    "msvcrt": (_EFFECT, "invokes_external", "lock"),
    "winreg.OpenKey": (_EFFECT, "reads_external", "registry"),
    "winreg.QueryValueEx": (_EFFECT, "reads_external", "registry"),
    "webview": (_EFFECT, "invokes_external", "host_webview"),  # 창 host 전부
    "ctypes.WinDLL": (_EFFECT, "invokes_external", "host_native"),
    "ctypes.CDLL": (_EFFECT, "invokes_external", "host_native"),
    "ctypes.windll": (_EFFECT, "invokes_external", "host_native"),
    "ctypes.oledll": (_EFFECT, "invokes_external", "host_native"),
    "ctypes.get_last_error": (_EFFECT, "reads_external", "host_native"),
    "ctypes.memmove": (_EFFECT, "invokes_external", "host_native"),
    "ctypes.wstring_at": (_EFFECT, "reads_external", "host_native"),
    "ctypes.POINTER": (_PURE, "", "marshalling"),
    "ctypes.Structure": (_PURE, "", "marshalling"),
    "ctypes.byref": (_PURE, "", "marshalling"),
    "ctypes.cast": (_PURE, "", "marshalling"),
    "ctypes.create_unicode_buffer": (_PURE, "", "marshalling"),
    "ctypes.sizeof": (_PURE, "", "marshalling"),
    "ctypes.wintypes": (_PURE, "", "marshalling"),
    # ---- 네트워크 ----------------------------------------------------------
    "urllib.request.urlopen": (_EFFECT, "invokes_external", "network"),
}

#: 수신자 미상 ``?:`` 호출의 Path 판별 말단 이름 — 방향까지 이름이 말해 주는 것만 넣는다.
#: ``open``/``read``/``write``/``save``/``replace`` 는 str·zipfile·workbook 등과 겹쳐
#: 제외한다(거짓 양성 방지) — 그 자리들은 02A 미해결 원장의 followup 귀속이 소유한다.
PATH_READ_METHODS = frozenset(
    {
        "read_text",
        "read_bytes",
        "exists",
        "stat",
        "is_file",
        "is_dir",
        "iterdir",
        "glob",
        "rglob",
        "resolve",
        "samefile",
    }
)
PATH_WRITE_METHODS = frozenset(
    {
        "write_text",
        "write_bytes",
        "mkdir",
        "rmdir",
        "unlink",
        "touch",
        "rename",
        "hardlink_to",
        "symlink_to",
    }
)

#: INFERRED 렌즈가 읽는 미해결 rule — 수신자가 지역 값/속성/이름/self 필드 사슬인 곳.
_INFERRED_MARKER_RULES = frozenset(
    {"call_via_local", "call_attr_unresolved", "call_name_unresolved", "call_self_chain"}
)

_LOCAL_OPEN_FOLLOWUP = "P1-02B 데이터플로(지역 재바인딩 추적) 또는 runtime trace"


def classify_external(dotted: str) -> "tuple[str, str, str] | None":
    """``ext:`` 을 벗긴 dotted 이름의 판정 — 최장 dotted 접두 일치, 미등록은 None."""
    parts = dotted.split(".")
    for length in range(len(parts), 0, -1):
        spec = CLASSIFICATION.get(".".join(parts[:length]))
        if spec is not None:
            return spec
    return None


@dataclass(frozen=True)
class PureRecord:
    """명시 순수 제외 한 건 — 효과가 아니라는 판정도 좌표와 함께 남는 기록이다."""

    src: str
    dst: str
    label: str
    file: str
    line: int
    anchor: str


@dataclass(frozen=True)
class LocalImportSite:
    """함수-지역 import 경유 외부 호출 — 닫힘(ext 복원)·열림(재바인딩 모호) 공통 좌표."""

    src: str
    marker: str
    resolved: str  # 닫히면 ext:..., 열리면 ""
    verdict: str  # effect relation / pure label / "open"
    file: str
    line: int
    anchor: str


@dataclass
class EffectGraphResult:
    static: StaticGraphResult
    effect_facts: tuple[Fact, ...] = field(repr=False)
    composes_facts: tuple[Fact, ...] = field(repr=False)
    pure_records: tuple[PureRecord, ...] = field(repr=False)
    local_sites: tuple[LocalImportSite, ...]
    effect_digest: str

    @property
    def facts(self) -> tuple[Fact, ...]:
        return tuple(
            sorted({*self.effect_facts, *self.composes_facts}, key=Fact.sort_key)
        )


def build(repo_root: Path) -> EffectGraphResult:
    repo_root = Path(repo_root)
    static = build_static(repo_root)
    graph_facts = static.facts

    effect: list[Fact] = []
    pure: list[PureRecord] = []

    # ---- ① ext: 접촉 좌표의 전수 분류(FACT 렌즈) ---------------------------
    for f in graph_facts:
        if not f.dst.startswith("ext:"):
            continue
        dotted = f.dst.removeprefix("ext:")
        if f.rel in ("imports_module", "imports_symbol"):
            # import 는 이름 결속이다 — 사용 좌표가 효과를 든다(모듈 초기화 부수효과는
            # 정적 도달 밖이라 여기서 위조하지 않는다).
            pure.append(
                PureRecord(
                    f.src, f.dst, "import_binding", f.evidence.file, f.evidence.line,
                    f.evidence.anchor,
                )
            )
            continue
        if f.rel == "inherits":
            pure.append(
                PureRecord(
                    f.src, f.dst, "inherit_type", f.evidence.file, f.evidence.line,
                    f.evidence.anchor,
                )
            )
            continue
        if f.rel != "calls":
            continue
        spec = classify_external(dotted)
        if spec is None:
            raise FactGraphError(
                f"미등록 외부 이름: {dotted!r} ({f.evidence.file}:{f.evidence.line}) — "
                "CLASSIFICATION 에 효과 또는 명시 순수로 등록하라(조용한 세 번째 바구니 금지)"
            )
        kind, relation, label = spec
        if kind == _PURE:
            pure.append(
                PureRecord(
                    f.src, f.dst, label, f.evidence.file, f.evidence.line, f.evidence.anchor
                )
            )
            continue
        effect.append(
            Fact(
                src=f.src,
                rel=relation,
                dst=f.dst,
                grade=f.grade,
                evidence=f.evidence,
                provenance=Provenance(COLLECTOR, f"effect_{label}"),
            )
        )

    # ---- ② 함수-지역 import 경유 외부 호출의 구조적 폐쇄 --------------------
    local_sites = _close_local_import_calls(repo_root, static)
    for site in local_sites:
        if site.verdict == "open" or not site.resolved:
            continue
        spec = classify_external(site.resolved.removeprefix("ext:"))
        if spec is None:  # _close_local_import_calls 가 이미 분류를 강제한다
            raise FactGraphError(f"지역 import 복원 이름이 미등록이다: {site.resolved!r}")
        kind, relation, label = spec
        if kind == _EFFECT:
            effect.append(
                Fact(
                    src=site.src,
                    rel=relation,
                    dst=site.resolved,
                    grade="STATIC_CONFIRMED",
                    evidence=Evidence(site.file, site.line, site.anchor),
                    provenance=Provenance(COLLECTOR, f"local_effect_{label}"),
                )
            )
        else:
            pure.append(
                PureRecord(
                    site.src, site.resolved, label, site.file, site.line, site.anchor
                )
            )

    # ---- ③ 수신자 미상 Path 판별 메서드의 INFERRED 렌즈 ---------------------
    closed_coords = {
        (s.file, s.line, s.anchor) for s in local_sites if s.verdict != "open"
    }
    for f in static.base_facts:
        if (
            f.rel != "calls"
            or not f.dst.startswith("?:")
            or f.provenance.rule not in _INFERRED_MARKER_RULES
            or "." not in f.dst
        ):
            continue
        if (f.evidence.file, f.evidence.line, f.evidence.anchor) in closed_coords:
            continue
        terminal = f.dst.rsplit(".", 1)[-1]
        if terminal in PATH_READ_METHODS:
            relation = "reads_external"
        elif terminal in PATH_WRITE_METHODS:
            relation = "writes_external"
        else:
            continue
        effect.append(
            Fact(
                src=f.src,
                rel=relation,
                dst=f.dst,
                grade="INFERRED",
                evidence=f.evidence,
                provenance=Provenance(COLLECTOR, f"fs_name_{terminal}"),
            )
        )

    effect_facts = tuple(sorted(set(effect), key=Fact.sort_key))

    # ---- ④ composes: 효과를 품은 모듈의 concrete 클래스 조립 자리 -----------
    effectful_modules = {parse_symbol_id(f.src)[0] for f in effect_facts}
    composes: list[Fact] = []
    for f in graph_facts:
        if f.rel != "constructs" or not is_symbol_ref(f.dst):
            continue
        if parse_symbol_id(f.dst)[0] not in effectful_modules:
            continue
        composes.append(
            Fact(
                src=f.src,
                rel="composes",
                dst=f.dst,
                grade=f.grade,
                evidence=f.evidence,
                provenance=Provenance(COLLECTOR, "composes_effectful"),
            )
        )
    composes_facts = tuple(sorted(set(composes), key=Fact.sort_key))

    symbol_ids = [s.id for s in static.symbols]
    effect_digest = facts_digest(symbol_ids, (*effect_facts, *composes_facts))
    return EffectGraphResult(
        static=static,
        effect_facts=effect_facts,
        composes_facts=composes_facts,
        pure_records=tuple(sorted(set(pure), key=lambda r: (
            r.src, r.dst, r.label, r.file, r.line, r.anchor
        ))),
        local_sites=local_sites,
        effect_digest=effect_digest,
    )


# ---------------------------------------------------------------------------
# 함수-지역 import 폐쇄
# ---------------------------------------------------------------------------


def _local_import_candidates(
    repo_root: Path, closure: Closure
) -> "dict[tuple[str, int, str], tuple[str, str, bool]]":
    """지역 plain ``import X`` 가 root 인 attribute 호출 좌표의 독립 전수.

    반환: (file, line, anchor) → (모듈 dotted, 호출 tail, 유일 바인딩 여부).
    유일성은 어휘 스코프 사슬로 판정한다 — 호출 지점에서 안쪽부터 그 이름을 묶는 첫
    스코프를 찾고, 그 스코프에서 결속이 해당 import 하나뿐일 때만 참이다. 모듈 스코프에
    닿으면 후보가 아니다(그건 기반 수집기가 이미 해석한다).
    """
    closure_modules = {mf.module for mf in closure.modules}
    out: dict[tuple[str, int, str], tuple[str, str, bool]] = {}

    for mf in closure.modules:
        tree = ast.parse((repo_root / mf.path).read_text(encoding="utf-8"), filename=mf.path)

        def bindings_of(fn: "ast.FunctionDef | ast.AsyncFunctionDef") -> "dict[str, list[str]]":
            """이 함수 스코프의 이름 → 결속 종류 목록. 중첩 def/class 내부는 내려가지 않는다.

            안쪽 스코프는 별도의 결속 표를 갖고 스택에 얹힌다 — 여기서 함께 세면
            바깥 import 를 안쪽 지역 변수가 가리는 경우를 유일 결속으로 오판한다.
            """
            found: dict[str, list[str]] = {}

            def record_target(t: ast.expr, kind: str) -> None:
                for name in _names_in_target(t):
                    found.setdefault(name, []).append(kind)

            def walk_stmts(stmts: "list[ast.stmt]") -> None:
                for stmt in stmts:
                    if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        found.setdefault(stmt.name, []).append("def")
                        continue  # 중첩 스코프 — 이 함수의 결속이 아니다
                    if isinstance(stmt, ast.Import):
                        for alias in stmt.names:
                            bound = alias.asname or alias.name.split(".", 1)[0]
                            target = alias.name if alias.asname else alias.name.split(".", 1)[0]
                            found.setdefault(bound, []).append(f"import:{target}")
                    elif isinstance(stmt, ast.ImportFrom):
                        for alias in stmt.names:
                            if alias.name != "*":
                                found.setdefault(alias.asname or alias.name, []).append("from")
                    elif isinstance(stmt, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                        targets = (
                            stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
                        )
                        for t in targets:
                            record_target(t, "assign")
                    elif isinstance(stmt, (ast.For, ast.AsyncFor)):
                        record_target(stmt.target, "assign")
                    elif isinstance(stmt, (ast.With, ast.AsyncWith)):
                        for item in stmt.items:
                            if item.optional_vars is not None:
                                record_target(item.optional_vars, "assign")
                    elif isinstance(stmt, ast.Delete):
                        for t in stmt.targets:
                            record_target(t, "assign")
                    for handler in getattr(stmt, "handlers", []) or []:
                        if handler.name:
                            found.setdefault(handler.name, []).append("assign")
                    # NamedExpr 등 식 안의 결속 — 중첩 def/lambda 서브트리는 건너뛰고 훑는다.
                    stack: list[ast.AST] = list(ast.iter_child_nodes(stmt))
                    while stack:
                        node = stack.pop()
                        if isinstance(
                            node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
                        ):
                            continue
                        if isinstance(node, ast.NamedExpr):
                            record_target(node.target, "assign")
                        stack.extend(ast.iter_child_nodes(node))
                    for block in _blocks(stmt):
                        walk_stmts(block)

            walk_stmts(fn.body)
            params = [
                *fn.args.posonlyargs,
                *fn.args.args,
                fn.args.vararg,
                *fn.args.kwonlyargs,
                fn.args.kwarg,
            ]
            for arg in params:
                if arg is not None:
                    found.setdefault(arg.arg, []).append("param")
            return found

        # 스코프 스택을 들고 걷는다 — 호출의 root 이름을 안쪽 스코프부터 해석한다.
        def descend(
            node: ast.AST,
            scope_stack: "list[dict[str, list[str]]]",
            module_path: str = mf.path,
        ) -> None:
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    descend(child, [*scope_stack, bindings_of(child)])
                    continue
                if isinstance(child, ast.Call):
                    base: ast.expr = child.func
                    parts: list[str] = []
                    while isinstance(base, ast.Attribute):
                        parts.insert(0, base.attr)
                        base = base.value
                    if isinstance(base, ast.Name) and parts and scope_stack:
                        root = base.id
                        for scope in reversed(scope_stack):
                            kinds = scope.get(root)
                            if kinds is None:
                                continue
                            imports = [k for k in kinds if k.startswith("import:")]
                            unique = len(kinds) == 1 and len(imports) == 1
                            if imports:
                                target = imports[0].removeprefix("import:")
                                if target not in closure_modules:
                                    key = (
                                        module_path,
                                        child.lineno,
                                        call_site_anchor(child),
                                    )
                                    out[key] = (target, ".".join(parts), unique)
                            break  # 가장 안쪽에서 이름을 묶은 스코프가 결정한다
                descend(child, scope_stack)

        descend(tree, [])
    return out


def _names_in_target(target: ast.expr) -> "set[str]":
    names: set[str] = set()
    stack = [target]
    while stack:
        t = stack.pop()
        if isinstance(t, ast.Name):
            names.add(t.id)
        elif isinstance(t, (ast.Tuple, ast.List)):
            stack.extend(t.elts)
        elif isinstance(t, ast.Starred):
            stack.append(t.value)
    return names


def _blocks(node: ast.stmt) -> "list[list[ast.stmt]]":
    blocks: list[list[ast.stmt]] = []
    for attr in ("body", "orelse", "finalbody"):
        block = getattr(node, attr, None)
        if isinstance(block, list) and block and isinstance(block[0], ast.stmt):
            blocks.append(block)
    for handler in getattr(node, "handlers", []) or []:
        blocks.append(handler.body)
    for case in getattr(node, "cases", []) or []:
        blocks.append(case.body)
    return blocks


def _close_local_import_calls(
    repo_root: Path, static: StaticGraphResult
) -> tuple[LocalImportSite, ...]:
    """``?:local:`` 마커 중 지역 plain import 경유 호출을 닫거나 열린 행으로 남긴다."""
    candidates = _local_import_candidates(repo_root, static.closure)
    sites: list[LocalImportSite] = []
    for f in static.base_facts:
        if f.rel != "calls" or f.provenance.rule != "call_via_local":
            continue
        key = (f.evidence.file, f.evidence.line, f.evidence.anchor)
        candidate = candidates.get(key)
        if candidate is None:
            continue
        module, tail, unique = candidate
        if not unique:
            sites.append(
                LocalImportSite(
                    f.src, f.dst, "", "open", f.evidence.file, f.evidence.line,
                    f.evidence.anchor,
                )
            )
            continue
        resolved = f"ext:{module}.{tail}"
        spec = classify_external(f"{module}.{tail}")
        if spec is None:
            raise FactGraphError(
                f"미등록 외부 이름: {module}.{tail} ({f.evidence.file}:{f.evidence.line}) — "
                "CLASSIFICATION 에 효과 또는 명시 순수로 등록하라(조용한 세 번째 바구니 금지)"
            )
        kind, relation, label = spec
        verdict = relation if kind == _EFFECT else label
        sites.append(
            LocalImportSite(
                f.src, f.dst, resolved, verdict,
                f.evidence.file, f.evidence.line, f.evidence.anchor,
            )
        )
    return tuple(
        sorted(sites, key=lambda s: (s.file, s.line, s.anchor, s.marker, s.resolved))
    )


# ---------------------------------------------------------------------------
# 「미수집 0」 오러클
# ---------------------------------------------------------------------------


def uncovered_external_contacts(result: EffectGraphResult) -> "list[str]":
    """모든 ``ext:`` 접촉 좌표가 효과 분류 ∪ 명시 순수 제외의 **정확히 한쪽**에 앉는가.

    분모는 정적 그래프에서 독립 재유도한다 — 생산 패스의 중간 상태를 믿지 않는다.
    """
    problems: list[str] = []
    effect_coords = {
        (f.evidence.file, f.evidence.line, f.evidence.anchor, f.dst)
        for f in result.effect_facts
        if f.provenance.rule.startswith("effect_")
    }
    pure_coords = {
        (r.file, r.line, r.anchor, r.dst)
        for r in result.pure_records
        if r.label not in ("import_binding", "inherit_type")
    }
    for f in result.static.facts:
        if not f.dst.startswith("ext:") or f.rel != "calls":
            continue
        dotted = f.dst.removeprefix("ext:")
        spec = classify_external(dotted)
        key = (f.evidence.file, f.evidence.line, f.evidence.anchor, f.dst)
        if spec is None:
            problems.append(
                f"{f.evidence.file}:{f.evidence.line} 미등록 외부 이름 {dotted!r}"
            )
            continue
        kind = spec[0]
        in_effect = key in effect_coords
        in_pure = key in pure_coords
        if kind == _EFFECT and (not in_effect or in_pure):
            problems.append(
                f"{f.evidence.file}:{f.evidence.line} 효과 좌표가 분할을 어겼다: {f.dst}"
            )
        if kind == _PURE and (in_effect or not in_pure):
            problems.append(
                f"{f.evidence.file}:{f.evidence.line} 순수 좌표가 분할을 어겼다: {f.dst}"
            )
    return sorted(set(problems))


def uncovered_local_import_calls(
    repo_root: Path, result: EffectGraphResult
) -> "list[str]":
    """지역 import 경유 외부 호출 후보 전수가 닫힘 ∪ 열린 원장 행에 앉는가."""
    candidates = _local_import_candidates(Path(repo_root), result.static.closure)
    covered = {(s.file, s.line, s.anchor) for s in result.local_sites}
    problems: list[str] = []
    for (file, line, anchor), (module, tail, _unique) in sorted(candidates.items()):
        if (file, line, anchor) not in covered:
            problems.append(
                f"{file}:{line} 지역 import 호출 {module}.{tail} 가 어느 원장에도 없다"
            )
    return problems


# ---------------------------------------------------------------------------
# 파생 산출 — 모듈 프로필·이중 조립
# ---------------------------------------------------------------------------


def _package_of(module: str) -> str:
    parts = module.split(".")
    return ".".join(parts[:2]) if len(parts) >= 2 else parts[0]


def effect_module_profiles(
    result: EffectGraphResult,
) -> "dict[str, dict[str, object]]":
    """모듈별 효과 프로필 — 방향별 사이트 수와 폐포 내 소비자(생산자/소비자 연결)."""
    per_module: dict[str, dict[str, int]] = {}
    for f in result.effect_facts:
        module = parse_symbol_id(f.src)[0]
        row = per_module.setdefault(
            module, {"reads": 0, "writes": 0, "invokes": 0, "inferred_fs": 0}
        )
        if f.grade == "INFERRED" and f.provenance.rule.startswith("fs_name_"):
            row["inferred_fs"] += 1
        elif f.rel == "reads_external":
            row["reads"] += 1
        elif f.rel == "writes_external":
            row["writes"] += 1
        else:
            row["invokes"] += 1
    consumers: dict[str, set[str]] = {module: set() for module in per_module}
    for f in result.static.facts:
        if f.rel not in ("calls", "constructs") or not is_symbol_ref(f.dst):
            continue
        dst_module = parse_symbol_id(f.dst)[0]
        src_module = parse_symbol_id(f.src)[0]
        if dst_module in consumers and src_module != dst_module:
            consumers[dst_module].add(src_module)
    return {
        module: {**counts, "consumers": tuple(sorted(consumers[module]))}
        for module, counts in sorted(per_module.items())
    }


def dual_assembly(result: EffectGraphResult) -> "list[dict[str, object]]":
    """효과를 품은 모듈의 심볼이 **둘 이상의 패키지 표면**에서 소비되는 좌표 전수.

    GUI 표면과 CLI 가 같은 effect 를 다르게 조립하는 경로가 이 표에 나타난다 —
    표면 이름을 하드코딩하지 않고 소비자 모듈의 패키지 접두(2단)로 유도한다.
    """
    effectful_modules = {
        parse_symbol_id(f.src)[0] for f in result.effect_facts
    }
    consumers: dict[str, set[str]] = {}
    for f in result.static.facts:
        if f.rel not in ("calls", "constructs") or not is_symbol_ref(f.dst):
            continue
        dst_module = parse_symbol_id(f.dst)[0]
        src_module = parse_symbol_id(f.src)[0]
        if dst_module not in effectful_modules or src_module == dst_module:
            continue
        consumers.setdefault(f.dst, set()).add(src_module)
    rows: list[dict[str, object]] = []
    for dst, modules in sorted(consumers.items()):
        packages = sorted({_package_of(module) for module in modules})
        if len(packages) < 2:
            continue
        rows.append(
            {"dst": dst, "packages": packages, "consumers": sorted(modules)}
        )
    return rows


# ---------------------------------------------------------------------------
# 원장 render/check/rewrite
# ---------------------------------------------------------------------------

_HEADER = f"""# 생성 파일 — 직접 편집 금지. P1-02C 효과 그래프 원장(#515).
# 원천: 고정 baseline src/ + scripts/factgraph 02A 정적 그래프 위의 효과 분류 파생
# 재생성: {REGEN_COMMAND}
# 검사:   {REGEN_COMMAND} --check
schema = "effect-graph-02c/v1"
"""


def render(repo_root: Path, *, _baseline_checked: bool = False) -> str:
    repo_root = Path(repo_root)
    if not _baseline_checked:
        baseline_problems = _baseline_source_problems(repo_root)
        if baseline_problems:
            raise FactGraphError("; ".join(baseline_problems))
    result = build(repo_root)
    contact_problems = uncovered_external_contacts(result)
    local_problems = uncovered_local_import_calls(repo_root, result)
    problems = [*contact_problems, *local_problems]
    if problems:
        sample = "; ".join(problems[:5])
        raise FactGraphError(f"효과 계측 미수집 좌표 {len(problems)}건: {sample}")

    profiles = effect_module_profiles(result)
    dual_rows = dual_assembly(result)
    confirmed = [
        f for f in result.effect_facts if not f.provenance.rule.startswith("fs_name_")
    ]
    inferred = [
        f for f in result.effect_facts if f.provenance.rule.startswith("fs_name_")
    ]
    local_closed = [s for s in result.local_sites if s.verdict != "open"]
    local_open = [s for s in result.local_sites if s.verdict == "open"]

    by_class: dict[str, int] = {}
    for f in confirmed:
        label = f.provenance.rule.removeprefix("effect_").removeprefix("local_effect_")
        by_class[label] = by_class.get(label, 0) + 1
    by_relation: dict[str, int] = {}
    for f in (*result.effect_facts, *result.composes_facts):
        by_relation[f.rel] = by_relation.get(f.rel, 0) + 1
    pure_by_label: dict[str, int] = {}
    for r in result.pure_records:
        pure_by_label[r.label] = pure_by_label.get(r.label, 0) + 1

    parts = [_HEADER, "\n[baseline]\n"]
    parts.append(f"git_sha = {_q(BASELINE_SHA)}\n")
    parts.append("\n# base/graph 핀은 02A 원장과 같은 값이어야 한다 — 같은 측정 위의 shard.\n")
    parts.append("[digests]\n")
    parts.append(f'base_facts = "{result.static.base_digest}"\n')
    parts.append(f'graph_facts = "{result.static.graph_digest}"\n')
    parts.append(f'effect_facts = "{result.effect_digest}"\n')

    parts.append("\n[counts]\n")
    parts.append(f"modules = {len(result.static.closure.modules)}\n")
    parts.append(f"symbols = {len(result.static.symbols)}\n")
    parts.append(f"effect_facts_confirmed = {len(confirmed)}\n")
    parts.append(f"effect_facts_inferred_fs = {len(inferred)}\n")
    parts.append(f"pure_records = {len(result.pure_records)}\n")
    parts.append(f"composes_edges = {len(result.composes_facts)}\n")
    parts.append(f"effect_modules = {len(profiles)}\n")
    parts.append(f"local_import_closed = {len(local_closed)}\n")
    parts.append(f"local_import_open = {len(local_open)}\n")
    parts.append(f"dual_assembly_rows = {len(dual_rows)}\n")
    parts.append("uncovered_external_contacts = 0\n")
    parts.append("uncovered_local_import_calls = 0\n")

    parts.append("\n[effect_by_class]\n")
    for label, count in sorted(by_class.items()):
        parts.append(f"{_q(label)} = {count}\n")
    parts.append("\n[effect_by_relation]\n")
    for relation, count in sorted(by_relation.items()):
        parts.append(f"{_q(relation)} = {count}\n")
    parts.append("\n# 명시 순수 제외 — '파일을 다룬다' ≠ 효과 판정의 감사 기록.\n")
    parts.append("[pure_by_label]\n")
    for label, count in sorted(pure_by_label.items()):
        parts.append(f"{_q(label)} = {count}\n")

    parts.append("\n# 모듈별 효과 프로필 — 방향별 사이트 수 + 폐포 내 소비자(생산자/소비자 연결).\n")
    for module, row in profiles.items():
        parts.append("\n[[effect_module]]\n")
        parts.append(f"module = {_q(module)}\n")
        parts.append(f"reads = {row['reads']}\n")
        parts.append(f"writes = {row['writes']}\n")
        parts.append(f"invokes = {row['invokes']}\n")
        parts.append(f"inferred_fs = {row['inferred_fs']}\n")
        consumers = row["consumers"]
        if not consumers:
            parts.append("consumers = []\n")
        else:
            parts.append("consumers = [\n")
            parts.extend(f"  {_q(consumer)},\n" for consumer in consumers)
            parts.append("]\n")

    parts.append("\n# 효과 모듈 심볼을 둘 이상의 패키지 표면이 소비하는 좌표 — GUI/CLI 조립 대조.\n")
    for row in dual_rows:
        parts.append("\n[[dual_assembly]]\n")
        parts.append(f"dst = {_q(row['dst'])}\n")
        parts.append("packages = [\n")
        parts.extend(f"  {_q(package)},\n" for package in row["packages"])
        parts.append("]\n")
        parts.append("consumers = [\n")
        parts.extend(f"  {_q(consumer)},\n" for consumer in row["consumers"])
        parts.append("]\n")

    parts.append("\n# 함수-지역 import 경유 외부 호출 — 닫힌 좌표 전수.\n")
    for site in local_closed:
        parts.append("\n[[local_import]]\n")
        parts.append(f"src = {_q(site.src)}\n")
        parts.append(f"marker = {_q(site.marker)}\n")
        parts.append(f"resolved = {_q(site.resolved)}\n")
        parts.append(f"verdict = {_q(site.verdict)}\n")
        parts.append(f"file = {_q(site.file)}\n")
        parts.append(f"line = {site.line}\n")
        parts.append(f"anchor = {_q(site.anchor)}\n")
    for site in local_open:
        parts.append("\n[[local_import_open]]\n")
        parts.append(f"src = {_q(site.src)}\n")
        parts.append(f"marker = {_q(site.marker)}\n")
        parts.append(f"file = {_q(site.file)}\n")
        parts.append(f"line = {site.line}\n")
        parts.append(f"anchor = {_q(site.anchor)}\n")
        parts.append(f"followup = {_q(_LOCAL_OPEN_FOLLOWUP)}\n")

    parts.append("\n# 수신자 미상 Path 판별 메서드 — INFERRED 렌즈 전수(FACT 로 위조하지 않는다).\n")
    for f in inferred:
        parts.append("\n[[inferred_fs]]\n")
        parts.append(f"src = {_q(f.src)}\n")
        parts.append(f"rel = {_q(f.rel)}\n")
        parts.append(f"dst = {_q(f.dst)}\n")
        parts.append(f"file = {_q(f.evidence.file)}\n")
        parts.append(f"line = {f.evidence.line}\n")
        parts.append(f"anchor = {_q(f.evidence.anchor)}\n")
    return "".join(parts)


def _q(value: str) -> str:
    """TOML basic string과 공통인 JSON 인코딩으로 진단 원문을 안전하게 싣는다."""
    return json.dumps(value, ensure_ascii=False)


def check(repo_root: Path) -> "list[str]":
    repo_root = Path(repo_root)
    baseline_problems = _baseline_source_problems(repo_root)
    if baseline_problems:
        return baseline_problems
    target = repo_root / LEDGER_REL_PATH
    expected = render(repo_root, _baseline_checked=True)
    if not target.is_file():
        return [f"{LEDGER_REL_PATH}: 생성물이 없습니다 — `{REGEN_COMMAND}` 로 생성하세요."]
    if target.read_text(encoding="utf-8") == expected:
        return []
    problems = [f"{LEDGER_REL_PATH}: 원장 드리프트 — `{REGEN_COMMAND}` 로 재생성하세요."]
    try:
        actual_digests = tomllib.loads(target.read_text(encoding="utf-8")).get("digests", {})
        expected_digests = tomllib.loads(expected).get("digests", {})
        for key in sorted(set(actual_digests) | set(expected_digests)):
            if actual_digests.get(key) != expected_digests.get(key):
                problems.append(
                    f"  digest {key}: 커밋본 {actual_digests.get(key)} ≠ 재계측 {expected_digests.get(key)}"
                )
    except tomllib.TOMLDecodeError as exc:
        problems.append(f"  커밋본을 파싱할 수 없다(직접 편집 흔적?): {exc}")
    return problems


def rewrite(repo_root: Path) -> Path:
    repo_root = Path(repo_root)
    baseline_problems = _baseline_source_problems(repo_root)
    if baseline_problems:
        raise FactGraphError("; ".join(baseline_problems))
    target = repo_root / LEDGER_REL_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(render(repo_root, _baseline_checked=True))
    return target


__all__ = [
    "BASELINE_SHA",
    "CLASSIFICATION",
    "COLLECTOR",
    "EffectGraphResult",
    "LEDGER_REL_PATH",
    "LocalImportSite",
    "PATH_READ_METHODS",
    "PATH_WRITE_METHODS",
    "PureRecord",
    "REGEN_COMMAND",
    "build",
    "check",
    "classify_external",
    "dual_assembly",
    "effect_module_profiles",
    "render",
    "rewrite",
    "uncovered_external_contacts",
    "uncovered_local_import_calls",
]
