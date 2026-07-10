"""HWPX 생성 엔진 — VBA ``modHWPXEngine`` 의 포트.

메모리 내에서 컨테이너를 열어 대상 XML 에 필드를 주입하고 새 HWPX 로 저장한다.
원본과 달리 임시 폴더 언집/재압축이 없다(순수 zipfile).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .fields import FieldDocument
from hwpxcore.package import HwpxPackage


@dataclass
class GenerateResult:
    ok: bool
    output_path: str
    # 실제로 값이 주입된 필드명들
    applied: "set[str]" = field(default_factory=set)
    # 데이터에 있었으나 템플릿에서 매칭 실패한 필드명들
    unmatched: "set[str]" = field(default_factory=set)
    error: str = ""


class HwpxEngine:
    """단일 템플릿 + 데이터 → 단일 HWPX 파일."""

    def generate(
        self,
        template_path: str,
        data: "dict[str, object]",
        output_path: str,
    ) -> GenerateResult:
        try:
            pkg = HwpxPackage.open(template_path)
        except Exception as exc:  # noqa: BLE001 - 상위에서 결과로 보고
            return GenerateResult(False, output_path, error=f"템플릿 열기 실패: {exc}")

        applied: set[str] = set()
        # 값이 있는 필드만 주입(원본과 동일: 빈 값은 건너뜀)
        active = {k: str(v) for k, v in data.items() if str(v).strip() != ""}

        try:
            for name in pkg.content_xml_names():
                doc = FieldDocument(pkg.entries[name])
                changed = False
                for key, val in active.items():
                    if doc.set_field(key, val):
                        applied.add(key)
                        changed = True
                if changed:
                    pkg.entries[name] = doc.to_bytes()
        except Exception as exc:  # noqa: BLE001
            return GenerateResult(False, output_path, error=f"XML 처리 실패: {exc}")

        try:
            pkg.save(output_path)
        except Exception as exc:  # noqa: BLE001
            return GenerateResult(False, output_path, error=f"저장 실패: {exc}")

        unmatched = set(active) - applied
        return GenerateResult(True, output_path, applied=applied, unmatched=unmatched)

    def required_fields(self, template_path: str) -> "list[str]":
        """템플릿이 요구하는 누름틀 이름 전체(사전검증용)."""
        pkg = HwpxPackage.open(template_path)
        seen: dict[str, None] = {}
        for name in pkg.content_xml_names():
            for f in FieldDocument(pkg.entries[name]).required_fields():
                seen.setdefault(f, None)
        return list(seen)
