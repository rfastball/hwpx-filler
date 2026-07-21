from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _import_roots(package: str) -> set[str]:
    roots: set[str] = set()
    for path in (ROOT / "src" / package).rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                roots.add(node.module.split(".", 1)[0])
    return roots


def test_products_do_not_import_each_other() -> None:
    assert "hwpxfiller" not in _import_roots("hwpxdiff")
    assert "hwpxdiff" not in _import_roots("hwpxfiller")


def test_src_has_no_pyside6_runtime_imports() -> None:
    """웹 이관(#20·#22·#23) 후 src/ 전체에 PySide6/shiboken6 런타임 임포트가 0 임을 못박는다.

    Qt 위젯 계층은 물리 삭제됐고 두 제품 프론트엔드는 pywebview 다 — 어떤 모듈이든 Qt 를
    다시 끌어오면(위젯 부활·실수 임포트) 여기서 시끄럽게 막는다(재유입 차단). 링1 상태
    모듈이 docstring 에 'PySide6' 를 언급해도 실 임포트가 아니면 통과한다(AST 임포트만 스캔)."""
    forbidden = {"PySide6", "shiboken6"}
    offenders: list[str] = []
    for package in ("hwpxcore", "hwpxdiff", "hwpxfiller"):
        for path in (ROOT / "src" / package).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                names: list[str] = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                if any(n.split(".", 1)[0] in forbidden for n in names):
                    offenders.append(str(path.relative_to(ROOT)))
    assert not offenders, f"src 에 PySide6 런타임 임포트 재유입: {sorted(set(offenders))}"


def test_hwpxcore_native_stays_product_agnostic() -> None:
    """hwpxcore.native(공용 Win32 글루)는 제품·Qt 를 임포트하지 않는다.

    diff·filler 웹이 파일 다이얼로그·클립보드를 이 공용 계층으로만 공유한다 — core 가
    제품(hwpxfiller/hwpxdiff)이나 PySide6 로 역의존하면 그 공유 전제가 무너지므로 시끄럽게
    막는다. stdlib+ctypes 만 허용."""
    forbidden = {"PySide6", "shiboken6", "hwpxfiller", "hwpxdiff"}
    roots = _import_roots("hwpxcore")  # native 는 hwpxcore 하위 — 패키지 전체를 스캔
    native_roots: set[str] = set()
    for path in (ROOT / "src" / "hwpxcore" / "native").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                native_roots.update(a.name.split(".", 1)[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                native_roots.add(node.module.split(".", 1)[0])
    assert not (forbidden & native_roots), (
        f"hwpxcore.native 가 금지 패키지를 임포트한다: {forbidden & native_roots}"
    )
    assert forbidden.isdisjoint(roots), "hwpxcore 가 제품/Qt 로 역의존한다 — core 는 아래로만"


def test_hwpxdiff_core_module_is_qt_free() -> None:
    """hwpxdiff/diff.py(+cli.py)는 stdlib+hwpxcore 만 — 성형·그룹화·렌더 로직이 뷰로
    돌아가 GUI/CLI 표면이 갈라지는 회귀(RC-17)를 막는다."""
    for module in ("diff.py", "cli.py"):
        path = ROOT / "src" / "hwpxdiff" / module
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            assert not any(n.split(".", 1)[0] in ("PySide6", "shiboken6") for n in names), (
                f"hwpxdiff/{module} 에 Qt 임포트가 들어왔다 — 순수 계층을 지켜라"
            )


def test_filler_data_package_imports_no_core_or_qt() -> None:
    """data/ 는 헤드리스 어댑터 계층 — hwpxfiller.core·PySide6 역의존 금지.

    풀 항목 복원(source_from_pool_item)이 덕타입(.kind/.opts)만 읽는 이유가 이
    불변식이다. 시트 열거 헬퍼(sheet_overview) 등 신규 코드가 코어·Qt 를 끌어오면
    여기서 시끄럽게 알린다.
    """
    forbidden = {"PySide6", "shiboken6"}
    for path in (ROOT / "src" / "hwpxfiller" / "data").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
                # 상대 임포트(from ..core import …)도 core 역의존이다.
                if node.level >= 2:
                    assert node.module.split(".", 1)[0] != "core", (
                        f"data/{path.name} 가 상대 경로로 core 를 임포트한다 — 역의존 금지"
                    )
            for n in names:
                root = n.split(".", 1)[0]
                assert root not in forbidden, (
                    f"data/{path.name} 에 Qt 임포트가 들어왔다 — 헤드리스 계층을 지켜라"
                )
                assert not n.startswith("hwpxfiller.core"), (
                    f"data/{path.name} 가 hwpxfiller.core 를 임포트한다 — 역의존 금지"
                )


def test_pool_registry_construction_has_one_call_site() -> None:
    """webapp 의 ``DatasetPoolRegistry(...)`` 생성은 ``screens.py`` 의
    ``default_pool_registry()`` 단일 출처를 통해서만 — 인라인 재구현 재유입 차단.

    2026-07-16 high 코드리뷰(#26 웹 패리티 2차)에서 이 팩토리보다 나중에 커밋된
    ``screen_editor.py``가 팩토리를 쓰지 않고 ``DatasetPoolRegistry(default_dataset_pool_dir())``
    를 그대로 복붙한 결함이 확정됐다(``screen_pool.py`` 도 동형 — 다만 그쪽은 팩토리
    도입보다 먼저 작성돼 역사적으로는 이해 가능하나 지금은 정합 대상). 팩토리가 나중에
    바뀌면(캐싱·환경변수 오버라이드 등) 인라인 사본은 조용히 구식 동작을 유지한다 — 그
    드리프트를 재유입 즉시 차단한다. ``gui/`` 계층(Qt 시절 VM, 팩토리보다 먼저 존재)은
    이 규칙 밖이다 — webapp 이 아래로 임포트하는 방향이라 gui 가 webapp 을 참조할 수 없다.
    """
    pattern = re.compile(r"\bDatasetPoolRegistry\(")
    offenders: list[str] = []
    webapp_dir = ROOT / "src" / "hwpxfiller" / "webapp"
    for path in sorted(webapp_dir.glob("*.py")):
        if path.name == "screens.py":
            continue  # 단일 출처(default_pool_registry 정의부)
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if pattern.search(line):
                offenders.append(f"{path.relative_to(ROOT)}:{lineno}: {line.strip()}")
    assert not offenders, (
        "DatasetPoolRegistry 인라인 재구현 재유입 — "
        "webapp/screens.py 의 default_pool_registry() 를 참조하라:\n" + "\n".join(offenders)
    )


def test_home_controller_does_not_bypass_vm_registry() -> None:
    """webapp/screen_home.py 는 ``self.vm.registry`` 에 직접 접근하지 않는다(#44).

    HomeViewModel 의 공개 표면(JobRow 필드 + 메서드)이 seam 계약이다(home_state.py
    docstring). 2026-07-16 리뷰에서 ``_do_set_tags`` 만 이 계약을 우회해 컨트롤러가
    ``vm.registry.load/save`` 를 직접 호출한 결함이 확정됐다 — 검증 규칙이 Qt-free
    계층 밖으로 새고, 다른 모든 액션(위임 규약)과 어긋난다. 스코프를 ``screen_home.py``
    단일 파일로 좁힌 이유: 저장소에는 별개 개념의 registry(데이터 풀)가 공존하고
    ``screen_pool.py`` 는 그걸 정당하게 직접 소유한다 — 파일 전역 문자열 grep 은
    두 개념을 뒤섞으므로 AST 로 ``self.vm.registry`` 접근 경로만 정확히 잡는다.
    """
    path = ROOT / "src" / "hwpxfiller" / "webapp" / "screen_home.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    offenders: list[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and node.attr == "registry"
            and isinstance(node.value, ast.Attribute)
            and node.value.attr == "vm"
            and isinstance(node.value.value, ast.Name)
            and node.value.value.id == "self"
        ):
            offenders.append(f"screen_home.py:{node.lineno}")
    assert not offenders, (
        "홈 컨트롤러가 VM seam 을 우회해 vm.registry 에 직접 접근한다 — "
        "HomeViewModel 메서드로 위임하라(#44): " + ", ".join(offenders)
    )


def test_core_mapping_carries_no_source_specific_vocabulary() -> None:
    """범용 코어(core/mapping.py)는 특정 API 어휘를 품지 않는다(V1 소스 어휘 소유권).

    어휘(예: 나라장터 영문 코드 키·NARA_ALIASES)는 소유 소스(data/nara.py)로
    승격됐다. suggest_mappings 의 aliases 는 순수 범용 인자다 — 코어에 API별
    문자열이 새로 스며들면 README "core = no product logic" 규칙 위반을 알린다.
    """
    text = (ROOT / "src" / "hwpxfiller" / "core" / "mapping.py").read_text(
        encoding="utf-8"
    )
    for forbidden in ("NARA_ALIASES", "bidNtce", "presmptPrce", "opengDate"):
        assert forbidden not in text, (
            f"core/mapping.py 에 소스별 어휘 {forbidden!r} 가 남아 있다 — 소스로 승격하라"
        )


def test_job_panel_imports_ring1_and_does_not_reimplement() -> None:
    """#87(R-flow 슬라이스 1): 「작업」 패널 컨트롤러는 링1 VM 을 임포트하고 재구현하지 않는다.

    부록 A 의 구조 관찰("계약 대부분은 링1이 소유하고, 죽는 것은 링2 표면뿐")을 못박는다 —
    패널은 새 링2 표면이되 실행 결정(사전검증·게이트 단일 산출·생성 계획·ack 상태기계)은
    :class:`RunViewModel`/:class:`SelectionModel` 이 소유한다. 컨트롤러가 이 링1 결정 메서드를
    스스로 정의하면(우회 재구현) 이중 진실이 재발하므로 시끄럽게 막는다. AST 만 스캔한다.
    """
    path = ROOT / "src" / "hwpxfiller" / "webapp" / "screen_job.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    # (1) 링1 VM 을 실제로 임포트한다(docstring 언급이 아니라 AST 임포트).
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported.update(a.name for a in node.names)
    for required in ("RunViewModel", "SelectionModel"):
        assert required in imported, (
            f"screen_job.py 가 링1 {required} 를 임포트하지 않는다 — 패널은 링1 VM 을 "
            "소유·위임해야 한다(재구현 금지, #87)."
        )

    # (2) 링1 결정 메서드를 스스로 정의하지 않는다(우회 재구현 차단). 이들은 self.vm 에서
    #     호출만 해야 한다. 'generate' 는 컨트롤러의 오케스트레이션이라 허용(계획 조립은 VM).
    forbidden_methods = {
        "refresh", "gate_state", "validate_generate", "build_generation_plan",
        "unmet_blanks", "output_conflicts", "structure_drift", "mapped_records",
        "_compose_gate", "_compose_field_states", "_compose_preflight",
    }
    defined: set[str] = set()
    for cls in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)):
        for item in cls.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                defined.add(item.name)
    reimplemented = forbidden_methods & defined
    assert not reimplemented, (
        "screen_job.py 가 링1 결정 메서드를 재구현한다(우회 이중 진실): "
        f"{sorted(reimplemented)} — RunViewModel 에 위임하라(#87)."
    )


# 작업 durable 쓰기의 **허용 호출 지점**(#129 리뷰 3R P1). 값 = 그 자리가 정당한 이유.
# 새 호출 지점이 생기면 여기 올리기 전까지 실패한다 — "잠금 밖 writer 가 조용히 는다"는
# 세 라운드 연속 재발한 결함류라, 개별 결함이 아니라 **재유입 경로**를 막는다.
_ALLOWED_JOB_WRITE_SITES = {
    ("webapp/screen_editor.py", "save"):
        "저장 임계구역(_save_locked)이 registry.write_lock() 안 — 보존값 재읽기~저장 원자",
}


def test_job_registry_writes_go_through_the_locked_path() -> None:
    """레지스트리 밖에서 Job 을 쓰는 자리는 잠긴 경로(mutate/stamp_last_run)뿐이다.

    ``registry.load(...)`` 로 읽어 고친 뒤 ``registry.save(...)`` 로 통째 저장하는 손 엮음은
    다른 writer 와 겹칠 때 **읽은 시점이 낡은** 저장이 되어 상대 변경을 되돌린다(lost update).
    그 패턴이 세 라운드 연속 새로 발견됐으므로(스탬프 → delete → set_tags·relink) 호출 지점
    자체를 봉쇄한다: 남아도 되는 자리는 위 화이트리스트에 사유와 함께 적는다.
    """
    # 수신자까지 잡아 **별개 개념 레지스트리**(데이터 풀·txt 라이브러리)를 이름으로 가른다 —
    # 줄 어딘가에 'pool' 이 있으면 건너뛰는 식은 판별력이 없다(주석 한 줄로 규칙이 뚫린다).
    # 겨누는 것은 ``save``(통째 저장 = RMW 의 완결부)뿐이다. ``delete``·``clone``·``rename``
    # 은 레지스트리 안에서 스스로 잠그는 원자 연산이라 밖에서 불러도 안전하다 — 위험한 것은
    # **밖에서 읽어 밖에서 조립한 객체**를 덮어쓰는 자리다.
    pattern = re.compile(r"([A-Za-z_][A-Za-z_0-9]*)\.save\(")
    # 별개 개념 레지스트리를 소유한 모듈(데이터 풀·파이프라인·템플릿) — 같은 ``self.registry``
    # 이름을 쓰지만 작업 레지스트리가 아니다. 수신자 이름만으로는 갈라지지 않아 모듈로 가른다.
    other_registry_modules = ("pool", "dataset", "pipeline", "template")
    offenders: list[str] = []
    for sub in ("webapp", "gui", "cli"):
        base = ROOT / "src" / "hwpxfiller" / sub
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            if any(word in path.name for word in other_registry_modules):
                continue
            rel = path.relative_to(ROOT / "src" / "hwpxfiller").as_posix()
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                for receiver in pattern.findall(line):
                    if not receiver.endswith("registry") or "pool" in receiver.lower():
                        continue
                    if (rel, "save") in _ALLOWED_JOB_WRITE_SITES:
                        continue
                    offenders.append(f"{rel}:{lineno}: {line.strip()}")
    assert not offenders, (
        "잠금 밖 Job durable 쓰기 재유입 — JobRegistry.mutate()/stamp_last_run() 같은 잠긴 "
        "경로를 쓰거나, 정당하면 _ALLOWED_JOB_WRITE_SITES 에 사유와 함께 등록하라:\n"
        + "\n".join(offenders)
    )


# hwpx 전용 소비 경로의 **허용 파싱 지점**(R-info 3부 결정 13 · 3층 재유입 가드). 코어 밖에서
# hwpx 를 파싱하는(HwpxEngine·extract_schema·compile_status·template_path_drift) 자리는 전부
# 여기 사유와 함께 등재된다. 새 자리가 생기면 등재 전까지 실패한다 — "txt 기안 작업이 hwpx
# 코드에 조용히 닿는다"를 개별 결함이 아니라 **재유입 경로**로 막는다(결정 4 매체 유도의 짝).
# 사유는 셋 중 하나다: ①진입 가드(require_hwpx/require_hwpx_template) 아래 ②hwpx 전용 표면
# (에디터·매핑·템플릿 라이브러리 — 조회 경계 1층이 매체를 보장, Job 매체 분기 아님) ③매체 교차
# 재확인(relink, 결정 13 예외) 또는 사용자 지정 raw 경로(CLI 역할 테스터, Job 아님).
# **값 = (호출 수, 사유).** 호출 지점 정체를 (파일, 심볼)로만 잡으면 이미 등재된 파일에 같은
# 심볼의 **새 미가드 호출**이 조용히 통과한다(리뷰 #2) — 등재 수를 함께 못박아, 한 자리라도
# 늘거나 줄면 실패시켜 새 호출 지점을 리뷰 경계에 세운다.
_ALLOWED_HWPX_CONSUMERS = {
    ("gui/home_state.py", "compile_status"):
        (1, "_derive_compile — from_job 이 job.media 로 선분기 후 require_hwpx_template 백스톱"),
    ("gui/run_state.py", "HwpxEngine"):
        (3, "RunViewModel 메서드 — __init__ 의 require_hwpx(job) 진입 가드 아래"),
    ("gui/run_state.py", "template_path_drift"):
        (1, "RunViewModel.structure_drift — __init__ 의 require_hwpx(job) 아래"),
    ("webapp/screens.py", "template_path_drift"):
        (1, "relink_job_template — 매체 교차는 차단 아닌 재확인(결정 13 예외), 화면 게이트 소관"),
    ("webapp/screen_editor.py", "extract_schema"):
        (2, "에디터 = hwpx 전용 소비 표면(조회 경계 1층) — Job 아닌 편집 중 hwpx 템플릿 소비"),
    ("gui/mapping_state.py", "compile_status"):
        (1, "매핑 에디터(hwpx 전용 표면) — 라이브러리 hwpx 템플릿 소비, Job 매체 분기 아님"),
    ("gui/mapping_state.py", "extract_schema"):
        (1, "매핑 에디터(hwpx 전용 표면) — 위와 동일"),
    ("gui/template_manager_state.py", "compile_status"):
        (1, "템플릿 관리(hwpx 라이브러리 표면) — 라이브러리가 매체를 구획 분리(2부 결정 3)"),
    ("batch.py", "HwpxEngine"):
        (1, "generate_batch — 첫머리 require_hwpx_template(template_path) 진입 가드 아래"),
    ("batch.py", "template_path_drift"):
        (1, "generate_batch — 위와 동일"),
    ("cli.py", "extract_schema"):
        (1, "CLI schema 덤프 — 사용자 지정 raw hwpx 경로(역할 테스터·Job 아님)"),
    ("cli.py", "HwpxEngine"):
        (1, "CLI fill — 사용자 지정 raw hwpx 경로"),
    ("cli.py", "template_path_drift"):
        (1, "CLI fill 드리프트 — 위와 동일"),
}


def test_hwpx_consumers_are_media_guarded() -> None:
    """코어 밖에서 hwpx 를 파싱하는 자리는 전부 매체 가드 아래이거나 화이트리스트에 등재된다.

    저장 기계는 hwpx·txt 가 하나(JobRegistry)이고 매체는 ``template_path`` 에서 유도되므로
    (3부 결정 4), txt 기안 작업이 hwpx 전용 코드(``HwpxEngine``·``extract_schema``·
    ``compile_status``·``template_path_drift``)에 닿으면 ``.txt`` 를 hwpx zip 으로 파싱해
    **조용한 오작동**(엉뚱한 오류 배지·거짓 드리프트)이 된다. 진입 경계는 :func:`require_hwpx`
    /:func:`require_hwpx_template` 가 loud 로 막고(2층), 이 테스트가 **새 소비자가 그 가드
    없이 느는 것**을 3층에서 막는다. 코어(``core/``)는 매체-내재 프리미티브라 스캔 밖 —
    가드는 그 호출 경계에 놓인다(프리미티브 자신에 넣으면 CLI 의 raw 경로·bytes 입력과
    고도가 어긋난다).

    **호출 수까지 못박는다(리뷰 #2)**: (파일, 심볼)로만 잡으면 이미 등재된 파일에 같은 심볼의
    새 미가드 호출이 조용히 통과한다. 각 (파일, 심볼)의 실 매치 수가 등재 수와 다르면(늘거나
    줄거나) 실패시켜, 새 호출 지점 하나하나를 리뷰 경계에 세운다.
    """
    symbols = ("HwpxEngine", "extract_schema", "compile_status", "template_path_drift")
    pattern = re.compile(r"\b(" + "|".join(symbols) + r")\(")
    base = ROOT / "src" / "hwpxfiller"
    scan_dirs = [base / "webapp", base / "gui"]
    scan_files = [base / "batch.py", base / "cli.py"]
    paths = [p for d in scan_dirs if d.is_dir() for p in d.rglob("*.py")]
    paths += [f for f in scan_files if f.is_file()]
    unlisted: list[str] = []
    counts: dict[tuple[str, str], int] = {}
    for path in sorted(paths):
        rel = path.relative_to(base).as_posix()
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            for symbol in pattern.findall(line):
                key = (rel, symbol)
                counts[key] = counts.get(key, 0) + 1
                if key not in _ALLOWED_HWPX_CONSUMERS:
                    unlisted.append(f"{rel}:{lineno}: {line.strip()}")
    assert not unlisted, (
        "가드 없는 hwpx 소비자 재유입 — Job 을 소비하면 진입점에 require_hwpx(job)/"
        "require_hwpx_template(path) 를 두고, 정당하면 _ALLOWED_HWPX_CONSUMERS 에 (수, 사유)로 "
        "등재하라:\n" + "\n".join(unlisted)
    )
    # 등재 수 대조 — 한 자리라도 늘거나 줄면(새 호출·삭제) 실패(리뷰 #2: 파일·심볼 재사용 뚫림 봉합).
    miscounts = [
        f"{rel}:{symbol} 등재 {exp}회 ≠ 실제 {counts.get((rel, symbol), 0)}회"
        for (rel, symbol), (exp, _reason) in _ALLOWED_HWPX_CONSUMERS.items()
        if counts.get((rel, symbol), 0) != exp
    ]
    assert not miscounts, (
        "hwpx 소비 호출 수가 등재와 다릅니다 — 새 호출 지점이 이미 등재된 (파일, 심볼) 뒤에 "
        "숨었거나 삭제됐습니다. 각 자리가 가드 아래인지 확인하고 수를 갱신하라:\n"
        + "\n".join(miscounts)
    )


def test_home_dir_idiom_has_one_source() -> None:
    """홈 해석 관용구는 ``core/paths.py`` 한 곳에만 산다(#76).

    ``os.environ.get("HWPXFILLER_HOME") or ~/.hwpxfiller`` 를 다시 적는 사본이 생기면 홈
    규약이 바뀔 때 lockstep 이 깨지고, 설정(settings.json)과 레지스트리가 **다른 디렉터리로
    조용히 갈라진다** — 사용자에겐 작업이 사라진 것으로 보인다. 겨누는 것은 환경변수를 직접
    읽는 자리뿐이다(docstring 언급은 무해하므로 잡지 않는다).
    """
    pattern = re.compile(r"""environ(?:\.get)?[\[(]\s*["']HWPXFILLER_HOME["']""")
    single_source = ROOT / "src" / "hwpxfiller" / "core" / "paths.py"
    offenders: list[str] = []
    for path in sorted((ROOT / "src").rglob("*.py")):
        if path == single_source:
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if pattern.search(line):
                offenders.append(f"{path.relative_to(ROOT).as_posix()}:{lineno}: {line.strip()}")
    assert not offenders, (
        "홈 경로 관용구 재유입 — hwpxfiller.core.paths.home_dir() 를 쓰라:\n" + "\n".join(offenders)
    )
