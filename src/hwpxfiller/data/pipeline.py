"""소스 조립 파이프라인 — 여러 :class:`DataSource` → 하나의 :class:`DataSource`.

ADR K(조립 소스/데이터 파이프라인): "여러 데이터 → 한 순간 한 문서"(동시 결합)를 사용자가
저작·미리보기하는 **Power-Query식 파이프라인**으로 착지 — ``DataSource`` 를 *생산*하는 층
(이음새 아래)이지 추론 엔진이 아니다. 조립 결과는 ``DataSource`` 프로토콜(``records()``/
``fields()`` — :mod:`~hwpxfiller.data.base`)을 만족해 **다운스트림(매핑·엔진·작업·실행)엔
단일 소스로 보인다**. 필드 *값* 가공(``mapping.apply_transform``)과는 **다른 층** — 저건
레코드 *내부* 값, 이건 레코드 *집합* 조립이다(혼동 금지).

**교체 가능한 이음새(``format_engine.ENGINE`` 선례).** 실제 테이블 연산(merge/append)은
:data:`ENGINE` 한 곳에서 갈아끼운다. v1 은 순수 stdlib(``list[dict]`` 위 구현, **의존성 0
추가**) — 후일 "고급 편집 = raw SQL" 실수요가 오면 petl/DuckDB 구현으로 **이 한 줄만** 교체
(호출부 무변경). ADR K 결정 1의 "경량 엔진 + 교체점"을 stdlib 첫 구현으로 착지한다
(``StdlibFormatEngine`` now, babel later 의 정확한 미러).

**v1 스텝셋 = merge(키 조인) + append(union) 뿐**(ADR K 결정 3). filter(행)·select/rename(열)·
raw SQL 은 v1 밖(기본 노출 시 ETL 팽창 신호). **falsifiable 가드: 스텝셋이 이 둘을 넘어 자라면
= "능력 없는 슬롯 발명" 재발 신호 → 정지.**

**degrade = 시끄럽게**([[confirm-or-alarm-principle]]). 스텝 실패(조인 키 부재·소스 인덱스
범위초과·미지 op)는 **조용히 베이스로 물러서지 않고** :class:`AssemblyError` 로 raise 한다 —
헤드리스 코어의 유일한 "시끄러운" 채널. GUI(KB)가 이 예외를 잡아 미리보기에서 베이스+경고로
표시(조용한 추측·빈 결과 금지).
"""

from __future__ import annotations

from typing import Protocol


class AssemblyError(RuntimeError):
    """조립 스텝 실패 — 조용한 degrade 금지, 시끄럽게 표면화(confirm-or-alarm)."""


# ------------------------------------------------------------------ 엔진 프로토콜
class AssemblyEngine(Protocol):
    """테이블 조립 해석기. petl/DuckDB 로 교체하려면 이 프로토콜을 구현해 ``ENGINE`` 에 꽂는다.

    레코드 = ``dict[str, str]``, 테이블 = ``list[dict[str, str]]``(:mod:`~hwpxfiller.data.base`
    ``Record`` 규약). 실패는 :class:`AssemblyError` 로 시끄럽게.
    """

    def merge(
        self,
        left: "list[dict[str, str]]",
        right: "list[dict[str, str]]",
        *,
        on: str,
        how: str,
    ) -> "list[dict[str, str]]":
        """``left`` ⋈ ``right`` on ``on``. ``how`` = ``"inner"`` | ``"left"``(명시 필수)."""
        ...

    def append(
        self, tables: "list[list[dict[str, str]]]"
    ) -> "list[dict[str, str]]":
        """테이블들의 행을 concat(union). 필드 = 키 합집합, 누락 셀 = ``""``."""
        ...


# ------------------------------------------------------------------ 순수 헬퍼
def _union_keys(rows: "list[dict[str, str]]") -> "list[str]":
    """행들의 키 합집합을 **등장 순서**(중복 제거)로."""
    seen: "set[str]" = set()
    keys: "list[str]" = []
    for r in rows:
        for k in r:
            if k not in seen:
                seen.add(k)
                keys.append(k)
    return keys


def _normalize(rows: "list[dict[str, str]]") -> "list[dict[str, str]]":
    """레코드를 직사각형으로 — 모든 행이 키 합집합을 갖게(누락 = ``""``).

    다운스트림(엔진·매핑)이 소스별 헤더 균일을 기대하므로(Excel 헤더 규약과 동형)
    조립 결과도 폭을 통일한다 — 조용한 결측 대신 명시적 빈 문자열.
    """
    keys = _union_keys(rows)
    return [{k: r.get(k, "") for k in keys} for r in rows]


def _require_key(table: "list[dict[str, str]]", key: str, where: str) -> None:
    """``table`` 이 조인 키 ``key`` 를 가졌는지 검증 — 없으면 시끄럽게(:class:`AssemblyError`).

    레코드 폭 균일 가정(Excel/나라 소스 규약)이라 첫 행만 검사한다. 빈 테이블은 검사할 행이
    없어 통과(빈 결과로 자연 귀결) — 키 유무를 단정할 수 없으므로 조용히 넘긴다.
    """
    for r in table:
        if key not in r:
            raise AssemblyError(f"{where} 소스에 조인 키 {key!r} 가 없습니다.")
        return


def _combine(left: "dict[str, str]", right: "dict[str, str]") -> "dict[str, str]":
    """merge 매칭 행 결합 — **좌측(베이스) 우선**, 우측의 새 컬럼만 뒤에 덧붙임.

    비-키 겹침 컬럼에서 우측이 좌측을 **조용히 덮지 않는다**(베이스 보존, confirm-or-alarm).
    조인 키는 양측 동값이라 충돌하지 않는다. 필드 순서 = 좌측 먼저·우측 신규 뒤.
    """
    out = dict(left)
    for k, v in right.items():
        if k not in out:
            out[k] = v
    return out


# ------------------------------------------------------------------ stdlib 엔진
class StdlibAssemblyEngine:
    """stdlib 조립 엔진 — ``list[dict]`` 위 merge/append. **의존성 0**.

    후일 raw-SQL 실수요 시 petl/DuckDB 구현으로 ``ENGINE`` 을 교체한다(이 클래스는 무변경).
    """

    def merge(
        self,
        left: "list[dict[str, str]]",
        right: "list[dict[str, str]]",
        *,
        on: str,
        how: str,
    ) -> "list[dict[str, str]]":
        if how not in ("inner", "left"):
            raise AssemblyError(f"merge how 는 'inner'|'left' 여야 합니다: {how!r}")
        _require_key(left, on, "merge 좌측")
        _require_key(right, on, "merge 우측")
        # 우측 인덱스: 키값 → [행...]. 다중 매칭은 표준 조인처럼 행 곱을 낸다.
        index: "dict[str, list[dict[str, str]]]" = {}
        for r in right:
            index.setdefault(r.get(on, ""), []).append(r)
        out: "list[dict[str, str]]" = []
        for lrow in left:
            matches = index.get(lrow.get(on, ""), [])
            if matches:
                out.extend(_combine(lrow, rrow) for rrow in matches)
            elif how == "left":
                out.append(dict(lrow))  # 무매칭 좌측 유지(우측 필드는 정규화가 채움)
        return _normalize(out)

    def append(
        self, tables: "list[list[dict[str, str]]]"
    ) -> "list[dict[str, str]]":
        rows: "list[dict[str, str]]" = []
        for t in tables:
            rows.extend(dict(r) for r in t)
        return _normalize(rows)


# ---------------------------------------------------- 어댑터 (교체 지점) --
# petl/DuckDB 등으로 바꾸려면 이 한 줄만 다른 AssemblyEngine 구현으로 교체한다.
ENGINE: AssemblyEngine = StdlibAssemblyEngine()


# ------------------------------------------------------------------ 파이프라인 소스
class PipelineSource:
    """여러 소스를 스텝 레시피로 접어 하나의 :class:`DataSource` 로 만드는 조립 소스.

    **선형 fold(Power-Query "적용된 단계").** 씨앗 = ``sources[0]``, 각 스텝이 소스 하나를
    현재 결과에 접는다. 스텝은 소스를 **인덱스**로 참조한다(``{"source": i}``):

    - ``{"op": "append", "source": i}`` — 현재 결과에 ``sources[i]`` 행 union.
    - ``{"op": "merge", "source": i, "on": "키", "how": "inner"|"left"}`` — 조인.

    레코드·행을 **스냅샷하지 않는다** — ``records()`` 호출 때 서브소스를 재읽어(싱크) 레시피를
    재실행한다(1회 캐시). 조립 결과가 스텝 실패로 무너지면 :class:`AssemblyError`(시끄럽게).
    """

    def __init__(
        self,
        sources: "list",
        steps: "list[dict]",
        *,
        engine: "AssemblyEngine | None" = None,
    ):
        self.sources = list(sources)
        self.steps = [dict(s) for s in steps]
        self.engine = engine if engine is not None else ENGINE
        self._records: "list[dict[str, str]] | None" = None

    # --------------------------------------------------------------- 조립
    def _source_records(self, i) -> "list[dict[str, str]]":
        if not isinstance(i, int) or isinstance(i, bool) or i < 0 or i >= len(self.sources):
            raise AssemblyError(
                f"스텝이 존재하지 않는 소스 인덱스를 참조합니다: {i!r} "
                f"(소스 {len(self.sources)}개)"
            )
        return self.sources[i].records()

    def _build(self) -> "list[dict[str, str]]":
        if not self.sources:
            raise AssemblyError("파이프라인에 소스가 없습니다.")
        current = list(self._source_records(0))  # 씨앗 = sources[0]
        for n, step in enumerate(self.steps):
            op = step.get("op")
            try:
                if op == "append":
                    src = self._source_records(step["source"])
                    current = self.engine.append([current, src])
                elif op == "merge":
                    src = self._source_records(step["source"])
                    current = self.engine.merge(
                        current, src, on=step["on"], how=step.get("how", "inner")
                    )
                else:
                    raise AssemblyError(
                        f"알 수 없는 조립 스텝 op 입니다: {op!r} (v1 = merge|append)"
                    )
            except AssemblyError:
                raise
            except KeyError as exc:
                raise AssemblyError(
                    f"조립 스텝 {n}({op})에 필수 인자 {exc} 가 없습니다."
                ) from None
        return current

    # ---------------------------------------------------------- DataSource
    def records(self) -> "list[dict[str, str]]":
        if self._records is None:
            self._records = self._build()
        return self._records

    def fields(self) -> "list[str]":
        return _union_keys(self.records())

    def field_labels(self) -> "dict[str, str]":
        """서브소스들의 어휘 병합 — 나라 sub-source 의 한글 라벨을 상속한다.

        조립은 소스 *집합* 가공이라 자기 어휘를 발명하지 않는다. 하위 소스가 선언한
        어휘(예: 나라장터 영문 코드 → 한글)를 합쳐 다운스트림 퍼지 매칭에 그대로 노출한다.
        키가 겹치면 먼저 선언한 소스가 우선(등장 순서).
        """
        labels: "dict[str, str]" = {}
        for s in self.sources:
            fl = getattr(s, "field_labels", None)
            if callable(fl):
                for k, v in fl().items():
                    labels.setdefault(k, v)
        return labels
