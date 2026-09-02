"""컴파일 수명주기 상태 파생 — 저장하지 않는 **계산값**(호출마다 재산출).

한글에서 평문 ``{{계약명}}`` 을 타이핑 → ``authoring.compile_document`` 로 누름틀 컴파일
→ ``fields.set_field`` 로 값 주입, 이 세 단계가 문서의 수명주기다. 그런데 "어디까지 왔나"
는 파일 어딘가에 도장으로 찍혀 있지 않다 — 그런 도장은 사용자가 한글에서 문서를 재편집한
순간 거짓이 된다(드리프트). 그래서 이 모듈은 상태를 **읽을 때마다 다시 계산**한다:
스키마(누름틀 수)·스캔(잔존 토큰)·실제 필드 값을 그 자리에서 읽어 4-상태로 환원한다.

**단일 진실원.** 컴파일 상태 가독성의 유일 출처 — 웨이브-2 GUI 유닛(C3/C4/C5)이 모두 이
계산값 위에 앉는다. 저장·캐시·상태 전이 부작용은 없다(재산출 원칙 위반).

**설계 원칙**("묻고 확정하게 하라, 아니면 시끄럽게 알려라")의 준수:
- 필드는 있는데 잔존 토큰(미컴파일·파편·본문 평문)이나 **미변환 구간 표기**가 남은
  "다 된 것 같지만 아닌" 위험 상태를 ``PARTIAL`` 로 **시끄럽게** 구분한다(조용히
  COMPILED 로 통과시키지 않는다).
- ``COMPILED`` vs ``FILLED`` 는 추측이 아니라 실제 누름틀 값을 결정적으로 **읽어** 판정한다.

**읽기 전용.** 재사용하는 ``scan_tokens``·``extract_schema`` 와 아래 로컬 값 리더는
모두 파싱 사본 위에서 동작한다 — 입력 패키지를 전혀 변형하지 않는다.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from pathlib import Path

from hwpxcore.text_extract import require_package
from hwpxfiller.domain.authoring import scan_structure, scan_tokens
from hwpxfiller.domain.fields import FieldDocument, normalize_field_id
from hwpxfiller.domain.schema import extract_schema


# 작업 실행의 기본 저장 하위폴더 이름(screen_job: 템플릿/Results). 라이브러리 루트 밑에 산출물이
# 쌓이므로 재귀 템플릿 스캔이 이 이름의 하위트리를 **템플릿으로 재수집하면 안 된다**(#136 리뷰 F2)
# — 실행할수록 라이브러리가 완성 문서로 오염되고 모든 산출물을 상태 분석하게 된다. 스캔 제외와
# 저장 위치가 같은 이름을 봐야 어긋나지 않아 여기 단일 출처로 둔다.
OUTPUT_SUBDIR_NAME = "Results"

# 옛 삭제 동사가 만들던 휴지통 하위폴더 이름. **앱은 더 이상 이 폴더를 만들지 않는다**
# (U6 §2.3 — 사용자 서식 폴더에 쓰지 않는다: 삭제·복원 동사는 U6-A 에서 퇴역했다). 그래도
# 상수와 스캔 제외는 남는다: 옛 홈 폴더에 이미 만들어진 ``.trash`` 가 있고, 그것을 걸러내지
# 않으면 지웠던 템플릿이 ``타임스탬프-uuid-이름`` 으로 목록에 재등장한다(#267 리뷰).
TRASH_DIR_NAME = ".trash"

#: 재귀 나열·이관에서 건너뛰는 하위트리 이름 — 산출물(``Results``)과 옛 삭제 보관소
#: (``.trash``). **두 매체 walker 와 레거시 이관이 이 하나를 본다**: U6-A(#975) 이후 hwpx·txt
#: 가 사용자가 고른 같은 루트를 읽으므로, 한쪽만 거르면 같은 폴더가 매체마다 다르게 보인다.
EXCLUDED_DIR_NAMES: "tuple[str, ...]" = (TRASH_DIR_NAME, OUTPUT_SUBDIR_NAME)


def is_excluded_subtree(relative_parts: "tuple[str, ...]") -> bool:
    """루트 상대 경로 성분에 제외 하위트리가 끼어 있는가 — 술어도 한 곳이다."""
    return any(name in relative_parts for name in EXCLUDED_DIR_NAMES)



def library_display_name(root: "Path | None", path: "str | Path") -> str:
    """서식 폴더 항목의 **표시명** — 루트 상대경로, 확장자 제외, POSIX(``온나라/기안``).

    U6-A(#975)의 통일 규칙이다. 종전에는 hwpx 가 basename(``공고서.hwpx``), txt 가 루트
    상대경로(``온나라/기안``)를 이름으로 써서 같은 폴더의 두 파일이 다른 문법으로 불렸다 —
    루트가 재귀이고 하위폴더가 정리 축인 이상 basename 은 **유일하지도 않다**(``a/계약``과
    ``b/계약``이 한 이름으로 접힌다). 파일명 기반 정체성(``rel_key``)은 이 규칙과 별개로
    불변이다: 이름은 사람이 읽는 것이고 키는 기계가 무는 것이다.

    ``root`` 가 ``None`` 이거나 경로가 루트 밖이면 확장자 없는 basename 으로 강등한다 —
    루트를 모르는 자리(명시 경로 주입)에서 이름이 통째로 비는 것을 막는다.
    """
    target = Path(path)
    if root is not None:
        try:
            return target.relative_to(Path(root)).with_suffix("").as_posix()
        except ValueError:
            pass
    return target.stem


# (default_templates_dir 는 P2-21(#569)에서 Host 로 승격 —
#  :func:`hwpxfiller.host.locations.default_templates_dir`. 홈 해석은 실행 환경을 읽는
#  Host 책임이라 이 Domain 모듈엔 기본값 해석이 남지 않는다.)


class CompileState(str, enum.Enum):
    """HWPX 컴파일 수명주기의 4-상태.

    - ``RAW``: 진짜 필드 0개 + 본문에 ``{{}}`` 평문 토큰(미컴파일 원문).
    - ``PARTIAL``: 필드 有 + skip/파편/본문 잔존 토큰 또는 미변환 구간 표기가 남음
      ("다 된 것 같지만 아닌" 위험).
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
    평문에 남은 ``{{}}`` 수. ``structure_marker_n`` 은 아직 native Slot 으로 변환되지 않고
    본문에 남은 **구간 표기 마커** 수(:attr:`~hwpxfiller.domain.authoring.StructureSummary.markers`
    를 그대로 싣는다 — 여기서 다시 세지 않는다). ``state`` 는 이 카운트 + 실제 값 판독에서
    파생된다.

    ``structure_marker_n`` 만 기본값을 갖는 이유는 하나다: 생산자는
    :func:`compile_status` 하나뿐이고 그것은 항상 실측값을 싣는다. 값 객체를 직접 짓는
    테스트·시험 코드가 기존 다섯 필드 계약을 그대로 쓰게 두려는 하위 호환이다.
    """

    state: CompileState
    field_n: int
    compilable_n: int
    skipped_n: int
    stray_n: int
    structure_marker_n: int = 0

    def to_dict(self) -> dict:
        return {
            "state": self.state.value,
            "field_n": self.field_n,
            "compilable_n": self.compilable_n,
            "skipped_n": self.skipped_n,
            "stray_n": self.stray_n,
            "structure_marker_n": self.structure_marker_n,
        }


def _is_placeholder(value: str, name: str) -> bool:
    """값이 아직 미충전 placeholder 인가 — ``{{ ... }}`` 껍질을 벗겨 안쪽을 필드명과 비교.

    compile_document 는 값 런에 원문 토큰(내부 공백 포함, 예 ``{{ 계약명 }}``)을 그대로
    남기고 fieldBegin@name 은 공백을 벗긴 이름을 쓴다. 그 비대칭을 여기서 흡수한다 —
    문자열 재조립("{{"+name+"}}")은 공백 토큰을 FILLED 로 오판정하므로 쓰지 않는다.
    """
    v = value.strip()
    if v.startswith("{{") and v.endswith("}}"):
        return normalize_field_id(v) == name
    return False


def _read_field_values(pkg: object) -> "list[tuple[str, str]]":
    """주입 대상 XML 전체에서 (필드명, 값) 목록을 읽는다(파싱 사본 — 무변형)."""
    pkg2 = require_package(pkg)
    out: "list[tuple[str, str]]" = []
    for name in pkg2.content_xml_names():
        out.extend(FieldDocument(pkg2.entries[name], entry=name).field_values())
    return out


# ------------------------------------------------------------------ 공개 API
def compile_status(pkg: object) -> TemplateStatus:
    """열린 HWPX package 의 컴파일 수명주기 상태를 **계산**해 반환.

    **package-only**(P2-19R) — 경로는 호출측 External adapter가 연다.
    저장된 값을 읽지 않고 매 호출 재산출한다 — 재편집 드리프트에도 항상 진실.
    입력을 전혀 변형하지 않는다(읽기 전용).
    """
    pkg = require_package(pkg)  # 덕타이핑 관문(경로/바이트는 loud 거절)

    schema = extract_schema(pkg)
    field_n = len(schema.field_names())
    stray_n = len(schema.stray_tokens)

    sites = scan_tokens(pkg)
    compilable_n = sum(1 for s in sites if s.compilable)
    skipped_n = sum(1 for s in sites if not s.compilable)

    # 구간 표기 마커는 sigil 선행 분류(S8-01)로 ``scan_tokens`` 에서 빠진다. 그래서 이 수치를
    # 따로 읽지 않으면 「컴파일된 필드 + 잔존 마커」 문서가 어느 카운트에도 안 잡혀 COMPILED
    # 로 뜨고, 모든 선택지가 든 채 마커 텍스트까지 새는 문서가 조용히 생성된다(#835 D5).
    # 재산출 비용(scan_structure 1회 추가)은 scan_tokens 와 같은 compute-not-store 원칙의
    # 대가다 — 마커를 여기서 다시 세어 값을 싸게 얻는 길은 판정 이중화라 택하지 않는다.
    structure_marker_n = scan_structure(pkg).summary.markers

    if field_n == 0:
        # 진짜 필드 없음 → 미컴파일 원문. 토큰이 아예 없어도 정직하게 RAW(컴파일된 것 없음).
        # 마커만 남은 문서도 RAW 다: RAW 는 이미 실행 불가이고 수선 동선(누름틀·구간 변환)이
        # 같으므로, 마커의 존재만으로 상태를 새로 쪼개지 않는다(#835 — 새 enum 멤버 없음).
        state = CompileState.RAW
    elif skipped_n > 0 or stray_n > 0 or compilable_n > 0 or structure_marker_n > 0:
        # 필드는 있는데 잔존 토큰·구간 표기가 남음 → "다 된 것 같지만 아닌" 위험 상태.
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
        structure_marker_n=structure_marker_n,
    )
