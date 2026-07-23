"""컴파일 수명주기 상태 파생 — 저장하지 않는 **계산값**(호출마다 재산출).

한글에서 평문 ``{{계약명}}`` 을 타이핑 → ``authoring.compile_document`` 로 누름틀 컴파일
→ ``fields.set_field`` 로 값 주입, 이 세 단계가 문서의 수명주기다. 그런데 "어디까지 왔나"
는 파일 어딘가에 도장으로 찍혀 있지 않다 — 그런 도장은 사용자가 한글에서 문서를 재편집한
순간 거짓이 된다(드리프트). 그래서 이 모듈은 상태를 **읽을 때마다 다시 계산**한다:
스키마(누름틀 수)·스캔(잔존 토큰)·실제 필드 값을 그 자리에서 읽어 4-상태로 환원한다.

**단일 진실원.** 컴파일 상태 가독성의 유일 출처 — 웨이브-2 GUI 유닛(C3/C4/C5)이 모두 이
계산값 위에 앉는다. 저장·캐시·상태 전이 부작용은 없다(재산출 원칙 위반).

**설계 원칙**("묻고 확정하게 하라, 아니면 시끄럽게 알려라")의 준수:
- 필드는 있는데 잔존 토큰(미컴파일·파편·본문 평문)이 남은 "다 된 것 같지만 아닌" 위험
  상태를 ``PARTIAL`` 로 **시끄럽게** 구분한다(조용히 COMPILED 로 통과시키지 않는다).
- ``COMPILED`` vs ``FILLED`` 는 추측이 아니라 실제 누름틀 값을 결정적으로 **읽어** 판정한다.

**읽기 전용.** 재사용하는 ``scan_tokens``·``extract_schema`` 와 아래 로컬 값 리더는
모두 파싱 사본 위에서 동작한다 — 입력 패키지를 전혀 변형하지 않는다.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from pathlib import Path

from lxml import etree

from hwpxcore.text_extract import HP_NS, _local, _text_of_t, _to_package
from hwpxfiller.core.authoring import scan_tokens
from hwpxfiller.core.paths import home_dir
from hwpxfiller.core.schema import extract_schema


# 작업 실행의 기본 저장 하위폴더 이름(screen_job: 템플릿/Results). 라이브러리 루트 밑에 산출물이
# 쌓이므로 재귀 템플릿 스캔이 이 이름의 하위트리를 **템플릿으로 재수집하면 안 된다**(#136 리뷰 F2)
# — 실행할수록 라이브러리가 완성 문서로 오염되고 모든 산출물을 상태 분석하게 된다. 스캔 제외와
# 저장 위치가 같은 이름을 봐야 어긋나지 않아 여기 단일 출처로 둔다.
OUTPUT_SUBDIR_NAME = "Results"

# 템플릿 삭제의 30일 휴지통 하위폴더 이름(screen_template._do_delete). 파일은 매체 루트 밑
# ``.trash`` 로 이동만 하므로, 재귀 스캔이 이 하위트리를 제외하지 않으면 삭제한 템플릿이
# ``타임스탬프-uuid-이름`` 으로 즉시 목록에 재등장한다(#267 리뷰). 저장 위치와 스캔 제외가
# 같은 이름을 봐야 하므로 여기 단일 출처로 둔다.
TRASH_DIR_NAME = ".trash"


def default_templates_dir() -> Path:
    """GUI 기본 템플릿 라이브러리 위치 — 사용자 홈(``~/.hwpxfiller/templates``).

    작업·베이스·txt·데이터셋 기본 루트 4종(:func:`~hwpxfiller.core.job.default_jobs_dir`
    미러)과 동일 홈 관례 — 템플릿 라이브러리만 기본 루트가 없어 관리 워크숍이 백지로
    떴다(RC-14). ``HWPXFILLER_HOME`` 로 재지정 가능(테스트·CI·이식성 — 해석은
    :func:`~hwpxfiller.core.paths.home_dir`). 관리 뷰모델 *클래스* 자체는 위치-불가지
    (생성자가 디렉터리를 받는다) — 이 함수는 GUI 기본값 해석기일 뿐이다.
    """
    return home_dir() / "templates"


class CompileState(str, enum.Enum):
    """HWPX 컴파일 수명주기의 4-상태.

    - ``RAW``: 진짜 필드 0개 + 본문에 ``{{}}`` 평문 토큰(미컴파일 원문).
    - ``PARTIAL``: 필드 有 + skip/파편/본문 잔존 토큰이 남음("다 된 것 같지만 아닌" 위험).
    - ``COMPILED``: 필드 有 + 잔존 토큰 0 + 값이 아직 ``{{X}}`` placeholder 리터럴.
    - ``FILLED``: 필드 有 + 값이 placeholder 와 다름(실제 값이 채워짐).
    """

    RAW = "raw"
    PARTIAL = "partial"
    COMPILED = "compiled"
    FILLED = "filled"


@dataclass
class TemplateStatus:
    """컴파일 상태 스냅샷 — 저장 대상이 아니라 ``compile_status`` 의 계산 결과.

    ``field_n`` 은 누름틀(fieldBegin) 이름 수, ``compilable_n``/``skipped_n`` 은
    ``scan_tokens`` 가 각각 컴파일 가능/불가로 신고한 잔존 토큰 수, ``stray_n`` 은 본문
    평문에 남은 ``{{}}`` 수. ``state`` 는 이 카운트 + 실제 값 판독에서 파생된다.
    """

    state: CompileState
    field_n: int
    compilable_n: int
    skipped_n: int
    stray_n: int

    def to_dict(self) -> dict:
        return {
            "state": self.state.value,
            "field_n": self.field_n,
            "compilable_n": self.compilable_n,
            "skipped_n": self.skipped_n,
            "stray_n": self.stray_n,
        }


# --------------------------------------------------------------- 로컬 값 리더
# TODO: when C1 fields.read_field lands, replace this local reader (dedupe).
# C1(값 읽기)이 병렬 저작 중이라 아직 미착지 → C2 자체 수용(4-상태 채워짐 판별)을
# 만족시키기 위해, fields.py 의 fieldBegin→fieldEnd 구조를 미러링한 최소 리더를
# 여기 자체적으로 둔다. 실제 문서 값을 결정적으로 읽는 것이지 추측이 아니다.
def _region_value(begin: etree._Element) -> str:
    """``fieldBegin`` 한 개의 값 = begin~fieldEnd 사이 ``hp:t`` 텍스트 이어붙임.

    ``fields._fill_one`` 의 런-형제 순회 의미를 그대로 읽기용으로 미러링한다. 값 런이
    begin 과 같은 런에 인라인이든 뒤 형제 런이든 동일하게 처리하고, fieldEnd 를 품은
    ctrl 에서 종료한다.
    """
    ctrl = begin.getparent()  # hp:ctrl
    run = ctrl.getparent() if ctrl is not None and _local(ctrl.tag) == "ctrl" else ctrl
    if run is None or _local(run.tag) != "run":
        return ""

    parts: "list[str]" = []
    found_begin = False
    current = run
    while current is not None and _local(current.tag) == "run":
        stop = False
        for inner in current:
            if not found_begin:
                if inner is ctrl or inner is begin:
                    found_begin = True
                continue
            ln = _local(inner.tag)
            if ln == "t":
                parts.append(_text_of_t(inner))
            elif ln == "ctrl":
                if any(_local(c.tag) == "fieldEnd" for c in inner):
                    stop = True
                    break
        if stop:
            break
        current = current.getnext()
    return "".join(parts)


def _is_placeholder(value: str, name: str) -> bool:
    """값이 아직 미충전 placeholder 인가 — ``{{ ... }}`` 껍질을 벗겨 안쪽을 필드명과 비교.

    compile_document 는 값 런에 원문 토큰(내부 공백 포함, 예 ``{{ 계약명 }}``)을 그대로
    남기고 fieldBegin@name 은 공백을 벗긴 이름을 쓴다. 그 비대칭을 여기서 흡수한다 —
    문자열 재조립("{{"+name+"}}")은 공백 토큰을 FILLED 로 오판정하므로 쓰지 않는다.
    """
    v = value.strip()
    if v.startswith("{{") and v.endswith("}}"):
        return v[2:-2].strip() == name
    return False


def _read_field_values(pkg: object) -> "list[tuple[str, str]]":
    """주입 대상 XML 전체에서 (필드명, 값) 목록을 읽는다(파싱 사본 — 무변형)."""
    pkg2 = _to_package(pkg)
    parser = etree.XMLParser(remove_blank_text=False, resolve_entities=False)
    out: "list[tuple[str, str]]" = []
    for name in pkg2.content_xml_names():
        root = etree.fromstring(pkg2.entries[name], parser=parser)
        for begin in root.iterfind(f".//{{{HP_NS}}}fieldBegin"):
            fname = (begin.get("name") or "").strip().replace("{{", "").replace("}}", "")
            if not fname:
                continue
            out.append((fname, _region_value(begin)))
    return out


# ------------------------------------------------------------------ 공개 API
def compile_status(pkg_or_path: object) -> TemplateStatus:
    """HWPX(경로/바이트/HwpxPackage)의 컴파일 수명주기 상태를 **계산**해 반환.

    저장된 값을 읽지 않고 매 호출 재산출한다 — 재편집 드리프트에도 항상 진실.
    입력을 전혀 변형하지 않는다(읽기 전용).
    """
    pkg = _to_package(pkg_or_path)  # 1회 정규화(경로/바이트도 한 번만 읽음)

    schema = extract_schema(pkg)
    field_n = len(schema.field_names())
    stray_n = len(schema.stray_tokens)

    sites = scan_tokens(pkg)
    compilable_n = sum(1 for s in sites if s.compilable)
    skipped_n = sum(1 for s in sites if not s.compilable)

    if field_n == 0:
        # 진짜 필드 없음 → 미컴파일 원문. 토큰이 아예 없어도 정직하게 RAW(컴파일된 것 없음).
        state = CompileState.RAW
    elif skipped_n > 0 or stray_n > 0 or compilable_n > 0:
        # 필드는 있는데 잔존 토큰이 남음 → "다 된 것 같지만 아닌" 위험 상태.
        state = CompileState.PARTIAL
    else:
        # 필드 有 + 잔존 토큰 0 → 실제 값을 읽어 COMPILED(placeholder) vs FILLED 구분.
        # 값이 아직 {{...}} placeholder(내부 공백 무관)면 미충전, 실제 내용이면 채워짐.
        # 값이 비어/공백뿐이면(코퍼스 관례상 placeholder 유지 취지) 채워지지 않은 것으로 본다.
        values = _read_field_values(pkg)
        filled = any(
            val.strip() and not _is_placeholder(val, name) for name, val in values
        )
        state = CompileState.FILLED if filled else CompileState.COMPILED

    return TemplateStatus(
        state=state,
        field_n=field_n,
        compilable_n=compilable_n,
        skipped_n=skipped_n,
        stray_n=stray_n,
    )
