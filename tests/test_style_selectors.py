"""스타일 셀렉터 계약 — mark() 발화 (프로퍼티, 값) 조합이 전부 BASE_QSS 셀렉터에
매칭되는지 가드(V2 / UD-12·13·16·23·31).

Qt QSS 는 **무매칭 셀렉터를 조용히 무시**한다 — 코드가 ``mark(btn,'level','danger')``
를 걸어도 ``QPushButton[level="danger"]`` 규칙이 없으면 렌더 무효(죽은 표식)로 조용히
통과한다. UD-12(파괴 버튼)·UD-13(RAW·보관 배지)이 정확히 이 구멍이었다. 이 테스트는
gui/*.py 의 mark() 호출을 정적 스캔해 (위젯타입, 프로퍼티, 값) 조합을 뽑고, 각 조합에
대응하는 셀렉터가 BASE_QSS 에 실재하는지 단언한다(조용한 무매칭 통과 차단).

순수 스캔 + 문자열 검사라 QApplication 은 불필요하나, style 임포트가 PySide6 를
요구하므로 미설치 환경에서는 skip 한다.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from hwpxfiller.gui import style  # noqa: E402

GUI_DIR = Path(style.__file__).parent
BASE_QSS = style.BASE_QSS

# 값이 변형 셀렉터를 선택하는 프로퍼티(`[prop="value"]`).
# emphasis(V14/UD-22): 카드 반복 액션 보조 시각 등급 — mark(btn,"emphasis","card").
VALUE_PROPS = {"level", "pill", "fb", "kpi", "emphasis"}
# 불리언 프로퍼티(`mark(w, prop, True)` → `[prop="true"]`).
BOOL_PROPS = {"heading", "muted", "primary", "card"}
# 값이 빈 문자열/False 면 '레벨 해제'라 셀렉터가 없어도 정상(기본 렌더로 복귀).
CLEARING = {"", "False", "None"}

_WIDGET_CTORS = ("QLabel", "QPushButton", "QFrame", "ContrastProgressBar")
_ASSIGN_RE = re.compile(
    r"^\s*([\w.]+)\s*=\s*(" + "|".join(_WIDGET_CTORS) + r")\("
)
_MARK_RE = re.compile(
    r'mark\(\s*([\w.]+)\s*,\s*"(\w+)"\s*,\s*(.*?)\)\s*(?:#.*)?$'
)
_STR_LIT_RE = re.compile(r'"([^"]*)"|\'([^\']*)\'')

# 위젯 생성자 → 셀렉터 접두사(ContrastProgressBar 는 진행바라 mark 대상 아님).
_CTOR_TO_SELECTOR = {"QLabel": "QLabel", "QPushButton": "QPushButton", "QFrame": "QFrame"}

# 동적 값(변수·함수 호출) mark — 리터럴 스캔이 못 잡는 (위젯, 프로퍼티, 값역)을 명시.
# 근거 파일: home/template_manager(pill=badge_level), dataset_pool(level=badge_level),
# run_view(level=gate/preflight/note.level), txt_view(fb=tok.state).
_DYNAMIC = [
    ("QLabel", "pill", ["muted", "warn", "ok", "danger"]),   # CompileState 배지(홈·템플릿관리)
    ("QLabel", "level", ["ok", "muted"]),                    # dataset_pool 상태 배지
    ("QLabel", "level", ["warn", "danger", "ok"]),           # 실행/나라/매트릭스 결과·게이트
    ("QLabel", "fb", ["fill", "blank", "missing"]),          # txt 토큰 상태 배지
]


def _scan_marks() -> "list[tuple[str | None, str, str, Path, int]]":
    """(셀렉터접두사|None, 프로퍼티, 값리터럴, 파일, 라인) 목록 — 리터럴 값 mark 만."""
    out: "list[tuple[str | None, str, str, Path, int]]" = []
    for path in sorted(GUI_DIR.glob("*.py")):
        var_type: "dict[str, str]" = {}
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            am = _ASSIGN_RE.match(line)
            if am:
                var_type[am.group(1)] = am.group(2)
            mm = _MARK_RE.search(line)
            if not mm:
                continue
            var, prop, value_expr = mm.group(1), mm.group(2), mm.group(3)
            ctor = var_type.get(var)
            prefix = _CTOR_TO_SELECTOR.get(ctor) if ctor else None
            lits = [a or b for a, b in _STR_LIT_RE.findall(value_expr)]
            if lits:
                for lit in lits:
                    out.append((prefix, prop, lit, path, i))
            elif value_expr.strip() == "True":
                out.append((prefix, prop, "True", path, i))
            # 그 외(동적 변수/함수 호출)는 _DYNAMIC 이 커버.
    return out


def _selector_present(prefix: "str | None", prop: str, value: str) -> bool:
    if prop in BOOL_PROPS and value == "True":
        needle = f'[{prop}="true"]'
    else:
        needle = f'[{prop}="{value}"]'
    if prefix:
        return f"{prefix}{needle}" in BASE_QSS
    return needle in BASE_QSS  # 위젯 타입 미상 — 어느 위젯에라도 규칙이 있으면 통과


def test_every_literal_mark_has_matching_selector():
    """gui/*.py 의 리터럴 값 mark 가 전부 대응 셀렉터를 가진다(죽은 표식 0)."""
    unmatched = []
    for prefix, prop, value, path, line in _scan_marks():
        if value in CLEARING:
            continue
        if prop not in VALUE_PROPS and prop not in BOOL_PROPS:
            continue  # 스타일 무관 프로퍼티(예: 목록 id) — 셀렉터 계약 밖
        if not _selector_present(prefix, prop, value):
            sel = f'{prefix or "*"}[{prop}="{value}"]'
            unmatched.append(f"{path.name}:{line} → {sel} 무매칭")
    assert not unmatched, (
        "무매칭 mark(조용한 QSS 통과) 발견 — style.py 에 셀렉터를 신설하세요:\n  "
        + "\n  ".join(unmatched)
    )


def test_dynamic_mark_value_domains_have_selectors():
    """동적 값 mark(badge_level·gate.level·tok.state)의 값역이 전부 셀렉터를 가진다."""
    missing = []
    for prefix, prop, values in _DYNAMIC:
        for v in values:
            if v in CLEARING:
                continue
            if not _selector_present(prefix, prop, v):
                missing.append(f'{prefix}[{prop}="{v}"]')
    assert not missing, "동적 값역 무매칭 셀렉터: " + ", ".join(missing)


def test_v2_new_selectors_exist():
    """V2 가 신설한 셀렉터가 실재(회귀 가드)."""
    # UD-12 파괴 버튼 등급
    assert 'QPushButton[level="danger"]' in BASE_QSS
    # UD-13 RAW·보관 배지 muted 소생
    assert 'QLabel[level="muted"]' in BASE_QSS
    # UD-16 drift 전용 정체성 + fb 버튼 disabled 변형
    assert 'QLabel[fb="drift"]' in BASE_QSS
    assert 'QPushButton[fb="ack"]:disabled' in BASE_QSS


def test_ud23_primary_disabled_converges_to_muted_grammar():
    """UD-23: 비활성 primary 가 MUTED 채움을 재전용하지 않고 일반 disabled 문법으로 수렴."""
    m = re.search(
        r'QPushButton\[primary="true"\]:disabled\s*\{([^}]*)\}', BASE_QSS
    )
    assert m, "primary:disabled 규칙을 찾을 수 없음"
    body = m.group(1)
    # 위계 역전의 원인이던 'background: MUTED' 재전용이 사라지고 회색 글자/옅은 배경으로.
    assert f"background: {style.MUTED}" not in body, "MUTED 채움 재전용이 잔존(위계 역전)"
    assert f"color: {style.MUTED}" in body, "비활성 글자색이 MUTED(부차)로 하강해야 함"


def test_ud31_contrast_progress_bar():
    """UD-31: 대비 복원 진행바가 QProgressBar 서브클래스로 존재하고 텍스트를 끈다."""
    from PySide6.QtWidgets import QProgressBar

    assert issubclass(style.ContrastProgressBar, QProgressBar)
    # 기본 QProgressBar QSS(매트릭스 등 공유 표면)는 그대로 유지되어야 함.
    assert "QProgressBar::chunk" in BASE_QSS
