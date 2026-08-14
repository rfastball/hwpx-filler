"""HWPX 누름틀(Field) 주입 — VBA ``clsHWPXParser`` 의 lxml 포트.

누름틀은 다음과 같은 구조를 갖는다::

    <hp:run>
      <hp:ctrl><hp:fieldBegin name="계약명" .../></hp:ctrl>
    </hp:run>
    <hp:run><hp:t>여기에 값</hp:t></hp:run>
    ...
    <hp:run><hp:ctrl><hp:fieldEnd .../></hp:ctrl></hp:run>

``fieldBegin`` 과 ``fieldEnd`` 사이의 첫 ``hp:t`` 에 값을 넣고, 뒤따르는 파편
``hp:t`` 는 비운다. 원본 VBA 의 run-형제 순회 의미를 그대로 유지한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from lxml import etree

from hwpxcore.field_occurrence import FieldOccurrence, resolve_field_occurrences
from hwpxcore.lineseg import serialize_modified_section
from hwpxcore.text_extract import local_name, require_package

HP_NS = "http://www.hancom.co.kr/hwpml/2011/paragraph"
_FIELD_PART_PATTERNS = (
    (0, re.compile(r"section(\d+)\.xml$", re.IGNORECASE)),
    (1, re.compile(r"header(\d+)\.xml$", re.IGNORECASE)),
    (2, re.compile(r"footer(\d+)\.xml$", re.IGNORECASE)),
)


@dataclass(frozen=True)
class FillNote:
    """채움이 "경고 후 진행"으로 처리한 사실의 기록(#154, confirm-or-alarm 완화).

    문안은 표면(CLI·웹) 소관 — 코어는 사실만 담는다.

    - ``kind="inline_stripped"``: 값 런의 인라인 자식 요소(형광펜 마커 등)를 제거하고
      기입했다. ``detail`` = 제거된 요소 로컬명(정렬·중복 제거). 짝 요소가 필드 경계를
      걸치면 한쪽만 제거될 수 있다 — 종류 명명이 그 검토 신호다.
    - ``kind="slot_synthesized"``: 값 ``hp:t`` 가 전혀 없는 빈 누름틀에 값 런을
      합성해 기입했다(과거엔 조용히 기입 불가 → unmatched 오보).
    """

    field: str
    kind: str
    detail: "tuple[str, ...]" = ()


def _subtree_names(child: etree._Element) -> "set[str]":
    """제거 대상 하위트리의 노드 이름 전체 — 최상위만 대면 손실 집합 과소 고지."""
    names: "set[str]" = set()
    for node in child.iter():
        if isinstance(node, etree._Comment):
            names.add("#comment")
        elif isinstance(node, etree._ProcessingInstruction):
            names.add("#pi")
        else:
            names.add(local_name(node.tag) or "#node")
    return names


def _strip_candidates(ts: "list[etree._Element]") -> "set[str]":
    """값 슬롯들의 인라인 자식 이름 집합 — 사전 판정과 사후 제거가 같은 집계를 쓴다."""
    names: "set[str]" = set()
    for t in ts:
        for child in t:
            names |= _subtree_names(child)
    return names


def _collapse_field_id(raw: object) -> "str | None":
    if not isinstance(raw, str):
        return None
    value = " ".join(raw.split())
    return value or None


def normalize_field_id(raw: object) -> "str | None":
    """제품 Field ID를 정규화하고 빈 값·비문자열은 거절한다.

    앞뒤와 내부의 Unicode 공백을 접고, 전체를 감싼 ``{{...}}`` 표기 한 겹만
    벗긴 뒤 다시 공백을 접는다. 문자열 안쪽의 중괄호는 Field ID의 일부다.
    """
    name = _collapse_field_id(raw)
    if name is None:
        return None
    if name.startswith("{{") and name.endswith("}}"):
        return _collapse_field_id(name[2:-2])
    return name


class FieldDocument:
    """단일 XML(section/header/footer) 문서에 대한 누름틀 편집기."""

    def __init__(self, xml_bytes: bytes, *, entry: str = "<content XML>"):
        # 공백 보존(remove_blank_text=False 기본). 원본 선언/인코딩 정보 확보.
        parser = etree.XMLParser(remove_blank_text=False, resolve_entities=False)
        self._tree = etree.fromstring(xml_bytes, parser=parser)
        self._entry = entry
        self._occurrences = resolve_field_occurrences(
            self._entry, self._tree
        ).require_usable()
        self._occurrences_dirty = False
        self._modified = False
        self._notes: "list[FillNote]" = []

    def _field_occurrences(self) -> "tuple[FieldOccurrence, ...]":
        """현재 트리의 신뢰 가능한 ordinary Field occurrence를 공용 seam에서 얻는다."""
        if self._occurrences_dirty:
            self._occurrences = resolve_field_occurrences(
                self._entry, self._tree
            ).require_usable()
            self._occurrences_dirty = False
        return self._occurrences

    @property
    def modified(self) -> bool:
        """실제 텍스트가 바뀌었는가 — 값이 기존과 동일한 재채움은 변형이 아니다.

        스트립 게이트(#95)가 이 플래그를 소비하므로, 동일 값 재생성이 여전히 유효한
        줄배치 캐시를 잃지 않는다.
        """
        return self._modified

    @property
    def notes(self) -> "list[FillNote]":
        """채움이 "경고 후 진행"으로 처리한 사실들(#154). 호출측이 표면화할 것."""
        return list(self._notes)

    def _note(self, field: str, kind: str, detail: "tuple[str, ...]" = ()) -> None:
        note = FillNote(field, kind, detail)
        if note not in self._notes:
            self._notes.append(note)

    # ---------------------------------------------------------- required
    def required_fields(self) -> "list[str]":
        """문서 내 모든 누름틀 이름을 중복 없이 반환. ``{{..}}`` 는 벗겨서."""
        seen: dict[str, None] = {}
        for occurrence in self._field_occurrences():
            name = normalize_field_id(occurrence.raw_name)
            if name is not None and name not in seen:
                seen[name] = None
        return list(seen)

    # --------------------------------------------------------------- read
    def read_field(self, field_name: str) -> "str | None":
        """첫 ``field_name`` 누름틀의 현재 값을 반환한다.

        값은 ``fieldBegin`` 뒤부터 ``fieldEnd`` 앞까지 등장하는 모든 ``hp:t``
        파편을 문서 순서대로 이어 붙인다. 이름은 ``NAME`` 과 ``{{NAME}}`` 표기를
        동일하게 취급하며, 해당 필드가 없을 때만 ``None`` 을 반환한다.
        """
        occurrences = self._matching_field_occurrences(field_name)
        if occurrences:
            return self._read_one(occurrences[0])
        return None

    def field_values(self) -> "list[tuple[str, str]]":
        """유효한 ordinary Field의 ``(정규 ID, 현재 값)`` 등장 목록."""
        values: "list[tuple[str, str]]" = []
        for occurrence in self._field_occurrences():
            field_id = normalize_field_id(occurrence.raw_name)
            if field_id is not None:
                values.append((field_id, self._read_one(occurrence)))
        return values

    def _read_one(self, occurrence: FieldOccurrence) -> str:
        """단일 ``fieldBegin`` 과 짝을 이루는 종료 지점 사이의 텍스트를 읽는다."""
        return "".join("".join(t.itertext()) for t in occurrence.texts)

    def _matching_field_occurrences(
        self, requested: object
    ) -> "list[FieldOccurrence]":
        """canonical ID를 우선하고, 없을 때만 ``{{ID}}`` raw alias를 허용한다.

        한 겹 제거는 의도적으로 비멱등이다. 예를 들어 raw ``{{{{X}}}}``의
        canonical ID는 ``{{X}}``이므로 required_fields가 돌려준 값을 다시
        정규화하지 않고 먼저 찾아야 read/write 왕복이 보존된다.
        """
        requested_text = _collapse_field_id(requested)
        if requested_text is None:
            return []
        identified = [
            (occurrence, normalize_field_id(occurrence.raw_name))
            for occurrence in self._field_occurrences()
        ]
        target = (
            requested_text
            if any(field_id == requested_text for _, field_id in identified)
            else normalize_field_id(requested)
        )
        if target is None:
            return []
        return [occurrence for occurrence, field_id in identified if field_id == target]

    # ----------------------------------------------------------- precheck
    def precheck(self) -> "list[FillNote]":
        """채움이 완화 처리(#154)를 일으킬 자리를 **변형 없이** 사전 열거한다.

        :meth:`set_field` 와 같은 occurrence·같은 어휘(FillNote)로 판정한다 — 사전
        고지와 사후 노트가 같은 사실을 가리키게(표면 문안만 시제가 다르다). 값
        비교가 없는 사전 판정이라 ``inline_stripped`` 는 "다른 값을 채우면
        제거된다"는 조건부 사실이다.
        """
        notes: "list[FillNote]" = []
        for occurrence in self._field_occurrences():
            name = normalize_field_id(occurrence.raw_name)
            if name is None:
                continue
            if occurrence.texts:
                stripped = _strip_candidates(list(occurrence.texts))
                if stripped:
                    notes.append(
                        FillNote(name, "inline_stripped", tuple(sorted(stripped)))
                    )
            elif occurrence.end_ctrl is occurrence.begin_ctrl:
                notes.append(FillNote(name, "occurrence_unfillable"))
            else:
                notes.append(FillNote(name, "slot_synthesized"))
        return list(dict.fromkeys(notes))

    # ------------------------------------------------------------- inject
    def set_field(self, field_name: str, new_value: str) -> bool:
        """``field_name`` 누름틀에 값 주입. 기입 가능한 자리가 하나라도 있으면 True.

        반환값은 매칭 보고용(값이 기존과 같아도 True — 호출측 unmatched 판정이
        거짓말하지 않게). 빈 누름틀(값 ``hp:t`` 부재)은 짝 ``fieldEnd`` 로 닫힘이
        확인된 경우에만 값 런을 합성해 기입한다(#154). malformed pairing은 공용
        resolver가 예외로 거절한다. False = 매칭된 자리가 없거나 모든 자리가 한
        ctrl 안의 퇴화 형상이라 기입 불가 — 호출측 unmatched 로 시끄럽게. 일부
        자리만 기입되면 True 이되 ``occurrence_unfillable`` 노트를 남긴다.

        **읽기-쓰기 대칭 계약**: 성공한 ``set_field(f, V)`` 뒤 ``read_field(f) == V``.
        이미 그 상태면 무연산(자식 요소·바이트 불변 — #95 동일 값 재채움 안정).
        값을 실제로 바꿀 때 값 런의 인라인 자식 요소는 구값 소속이라 값과 함께
        제거된다(#154 확정 — 제거 사실은 ``notes`` 로 시끄럽게). 실제 변경 여부는
        ``modified`` 가 추적한다. VBA SetField 와 동일하게 ``name`` 이 ``NAME`` 또는
        ``{{NAME}}`` 인 모든 누름틀을 처리한다.
        """
        occurrences = self._matching_field_occurrences(field_name)
        if not occurrences:
            return False
        clean = normalize_field_id(occurrences[0].raw_name)
        assert clean is not None

        updated = 0
        skipped = 0
        for occurrence in occurrences:
            if self._fill_one(occurrence, new_value, clean):
                updated += 1
            else:
                skipped += 1
        if skipped:
            # 기입 불가 자리가 하나라도 있으면 노트 — updated>0 조건을 걸면 다른
            # 섹션이 같은 이름을 채우는 경우(엔진이 applied 로 집계) 이 문서의 빈
            # 자리가 어디에도 안 나오는 조용한 소실이 된다(2라운드 리뷰 F1).
            # 전 자리 불가(updated=0)면 unmatched 와 겹치지만, unmatched 의 "매칭
            # 실패" 오진을 이 노트가 바로잡는다 — 과경고가 조용한 소실보다 낫다.
            self._note(clean, "occurrence_unfillable")
        return updated > 0

    def _fill_one(
        self, occurrence: FieldOccurrence, new_value: str, note_name: str
    ) -> bool:
        """단일 fieldBegin 에 대해 fieldEnd 까지 텍스트를 채운다.

        1) 공용 resolver occurrence에서 구간을 받고, 2) 이미 목표 상태면 무연산,
        3) 슬롯이 없으면 닫힌 구간에 값 런을 합성하며(#154), 4) 슬롯들의 인라인
        자식을 제거한 뒤 첫 슬롯에 값을 기입, 파편 슬롯은 비운다. 완화 처리
        (합성·자식 제거)는 ``_note`` 로 기록한다.
        """
        ts = list(occurrence.texts)

        # ---- 2) 목표 상태 선판정 — 이미 read_field == new_value 면 아무것도 안
        # 건드린다(#95 동일 값 재채움 바이트 안정: 무해한 자식 요소·캐시 보존).
        if ts and "".join("".join(t.itertext()) for t in ts) == new_value:
            return True

        # ---- 3) 빈 누름틀: 값 런 합성(#154 — 기입 불가 대신 경고 후 진행)
        if not ts:
            if occurrence.end_ctrl is occurrence.begin_ctrl:
                # begin·end가 한 ctrl 안인 퇴화 형상은 슬롯 자리가 없다.
                return False
            slot = etree.Element(f"{{{HP_NS}}}t")
            if occurrence.end_run is occurrence.begin_run:
                # begin 과 end 가 같은 런 — end ctrl 바로 앞에 슬롯 삽입
                occurrence.begin_run.insert(
                    occurrence.begin_run.index(occurrence.end_ctrl), slot
                )
            else:
                # begin 런의 속성(charPrIDRef 등)을 통째로 승계 — authoring 의
                # 런 팩토리 관례(dict(run.attrib) 승계)와 동일.
                new_run = etree.Element(
                    f"{{{HP_NS}}}run", dict(occurrence.begin_run.attrib)
                )
                new_run.append(slot)
                occurrence.end_run.addprevious(new_run)
            ts = [slot]
            self._modified = True  # 요소 삽입 자체가 변형
            self._occurrences_dirty = True
            self._note(note_name, "slot_synthesized")

        # ---- 4) 인라인 자식 제거 + 기입
        # 자식 요소(형광펜 마커 등)와 그 tail 텍스트는 구값 소속 — 값 교체와 함께
        # 제거한다(#154 확정: 읽기-쓰기 대칭이 계약. read_field 는 itertext 로 읽으므로
        # 자식 tail 이 남으면 기입값 ≠ 읽은값). detail 은 하위트리 전체를 열거한다 —
        # 최상위 이름만 대면 실제 손실 집합을 과소 고지한다(문안 정직성).
        stripped = _strip_candidates(ts)
        for t in ts:
            for child in list(t):
                t.remove(child)
                self._modified = True
        if stripped:
            self._note(note_name, "inline_stripped", tuple(sorted(stripped)))

        first = ts[0]
        if (first.text or "") != new_value:
            first.text = new_value
            self._modified = True  # 실제 변경만 변형으로 계상
        for frag in ts[1:]:
            if frag.text:
                # 파편 텍스트 제거 — 실제로 지울 텍스트가 있을 때만 대입한다
                # (무조건 "" 대입은 <hp:t/> 를 무플래그로 바이트 변이시킴)
                frag.text = ""
                self._modified = True
        return True

    # -------------------------------------------------------------- output
    def to_bytes(self) -> bytes:
        # 변형된 문서만 stale 줄배치 캐시를 스트립(#95) — 미변경 문서의 캐시는
        # 여전히 유효하므로 보존한다.
        if self._modified:
            return serialize_modified_section(self._tree)
        return etree.tostring(
            self._tree,
            xml_declaration=True,
            encoding="UTF-8",
            standalone=True,
        )


def field_xml_names(pkg) -> "list[str]":
    """필드 대상 XML을 본문→머리말→꼬리말, 각 번호순으로 반환한다.

    ``pkg`` 는 ``content_xml_names()``/``entries`` 를 가진 package-like 객체다(P2-19 —
    concrete :class:`hwpxcore.package.HwpxPackage` 타입 결합 없이 덕타이핑으로 받는다).

    동일 필드명이 여러 파트에 있어도 이 목록의 모든 파트를 채운다. 읽기에서 중복
    이름의 첫 값을 고를 때도 같은 순서를 사용해 package ZIP 엔트리 순서에 의미가
    새지 않게 한다. 숫자 접미사가 없는 ``header.xml`` 같은 스타일 파트는 필드가
    없을 때만 제외한다. 미지원 이름에 ``fieldBegin``이 있으면 조용히 누락하지 않고
    loud failure로 남긴다.
    """
    supported: "list[tuple[int, int, str]]" = []
    unsupported: "list[str]" = []
    for name in pkg.content_xml_names():
        base = name.rsplit("/", 1)[-1]
        for region_order, pattern in _FIELD_PART_PATTERNS:
            match = pattern.fullmatch(base)
            if match:
                supported.append((region_order, int(match.group(1)), name))
                break
        else:
            if FieldDocument(pkg.entries[name], entry=name).required_fields():
                unsupported.append(name)

    if unsupported:
        joined = ", ".join(sorted(unsupported))
        raise ValueError(f"지원하지 않는 필드 XML 파트: {joined}")

    supported.sort(key=lambda item: (item[0], item[1], item[2]))
    return [name for _, _, name in supported]


def fill_precheck(pkg: object) -> "list[FillNote]":
    """HWPX 패키지 전체의 채움 완화 사전 판정(#154) — 변형 없음, 중복 없이.

    **열린 package 전용**(P2-19R) — 경로는 호출측 External adapter가 연다.
    템플릿 점검 표면(라이브러리 등)이 "채우면 무슨 일이 생기는가"를 실행 전에
    고지하는 데 쓴다. 사후 노트(:attr:`FieldDocument.notes`)와 같은 어휘.
    """
    pkg = require_package(pkg)
    notes: "list[FillNote]" = []
    for xml_name in field_xml_names(pkg):
        notes.extend(FieldDocument(pkg.entries[xml_name], entry=xml_name).precheck())
    return list(dict.fromkeys(notes))


def read_fields(pkg: object) -> "dict[str, str]":
    """열린 HWPX package 의 모든 누름틀 현재 값을 반환한다.

    **package-only**(P2-19R) — 경로는 호출측 External adapter가 연다.
    같은 이름이 여러 번 등장하면 문서 순서상 첫 값을 사용한다. ``set_field`` 는 같은
    이름의 모든 누름틀을 함께 갱신하므로 정상 템플릿에서는 값이 동일하다.
    """
    pkg = require_package(pkg)
    values: "dict[str, str]" = {}
    for xml_name in field_xml_names(pkg):
        doc = FieldDocument(pkg.entries[xml_name], entry=xml_name)
        for field_name, value in doc.field_values():
            values.setdefault(field_name, value)
    return values
