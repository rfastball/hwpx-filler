"""101 예제 템플릿 결정적 생성 — ``authoring.compile_document`` 기반.

이 폴더의 ``templates/발주요청서.hwpx`` 를 **단일 진실원**(이 스크립트에 박힌 필드
레이아웃)에서 결정적으로 파생한다. 같은 입력 → 같은 출력이라, 손으로 연 hwpx 가
어쩌다 깨져도 언제든 되돌린다. ``scripts/gen_scenario_fixtures.py`` 의 축소판이다.

무엇을 만드나
--------------
- ``templates/발주요청서.hwpx`` — 6필드 최소 템플릿(101 학습용).
- ``data/발주목록.csv`` (utf-8-sig) — 한글 헤더 = 템플릿 필드(직접 매칭).

저작 방식
---------
실코퍼스 스켈레톤(``form_purchase_v1.hwpx``)의 header/secPr 를 물려받아 본문만 평문
``{{토큰}}`` 문단으로 갈아끼운 뒤 :func:`authoring.compile_document` 로 누름틀 컴파일한다.

실행(저장소 루트에서)::

    .venv/Scripts/python examples/quickstart-101/make_template.py
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

from lxml import etree

from hwpxcore.package import HwpxPackage
from hwpxfiller.core.authoring import compile_document

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
SKELETON = ROOT / "tests" / "corpus" / "real" / "form_purchase_v1.hwpx"

# ------------------------------------------------------------------ 데이터(진실원)
# 한글 헤더 = 템플릿 필드명. 그래서 매핑 프로파일 없이 CSV 열이 곧바로 누름틀에 꽂힌다
# (101 의 핵심: "직접 매칭" 경로). 값은 원문 그대로(서식 미적용).
FIELDS = ["공고번호", "수요기관", "공고명", "추정가격", "납품기한", "담당자"]

RECORDS = [
    {
        "공고번호": "2026-001", "수요기관": "해양수산부",
        "공고명": "사무용 복합기 구매", "추정가격": "12000000",
        "납품기한": "2026-08-31", "담당자": "김담당",
    },
    {
        "공고번호": "2026-002", "수요기관": "국립수산과학원",
        "공고명": "회의실 빔프로젝터 구매", "추정가격": "8500000",
        "납품기한": "2026-09-15", "담당자": "박담당",
    },
    {
        "공고번호": "2026-003", "수요기관": "부산지방해양수산청",
        "공고명": "현장 안전화 구매", "추정가격": "3200000",
        "납품기한": "2026-08-20", "담당자": "이담당",
    },
]

# 두 번째 데이터 파일 — 같은 헤더(FIELDS)·다른 행. "여러 데이터 → 한 템플릿" 패턴에서
# 같은 out 폴더로 반복 실행해 누적하는 걸 보이려는 두 번째 배치다(다른 수요기관 3건).
RECORDS_2 = [
    {
        "공고번호": "2026-101", "수요기관": "동해어업관리단",
        "공고명": "순찰정 통신장비 구매", "추정가격": "27000000",
        "납품기한": "2026-10-10", "담당자": "최담당",
    },
    {
        "공고번호": "2026-102", "수요기관": "동해어업관리단",
        "공고명": "구명조끼 일괄 구매", "추정가격": "4600000",
        "납품기한": "2026-09-05", "담당자": "최담당",
    },
]

# ------------------------------------------------------------------ 템플릿 레이아웃
# 각 줄은 평문 {{토큰}} 문단으로 저작 → 컴파일하면 누름틀이 된다.
# 두 템플릿이 **같은 데이터**(발주목록.csv)를 먹는다 — "한 데이터 → 여러 템플릿" 패턴.
# 발주요청서: 6필드 전량. 구매요청서: 4필드 부분집합(여분 열은 무시된다).
BID_LINES = [
    "공고번호: {{공고번호}}",
    "수요기관: {{수요기관}}",
    "공고명: {{공고명}}",
    "추정가격: {{추정가격}}",
    "납품기한: {{납품기한}}",
    "담당자: {{담당자}}",
]
PURCHASE_LINES = [
    "수요기관: {{수요기관}}",
    "품명: {{공고명}}",
    "추정가격: {{추정가격}}",
    "담당자: {{담당자}}",
]

# (파일명, 제목, 본문줄)
TEMPLATES = [
    ("발주요청서.hwpx", "■ 발 주 요 청 서", BID_LINES),
    ("구매요청서.hwpx", "■ 구 매 요 청 서", PURCHASE_LINES),
]


def _hp(tag: str) -> str:
    return f"{{{HP}}}{tag}"


def _text_para(root: etree._Element, text: str) -> None:
    """평문 한 줄을 담은 ``hp:p`` (charPr/paraPr=0). 컴파일 전 저작 문단."""
    p = etree.SubElement(
        root, _hp("p"),
        {"paraPrIDRef": "0", "styleIDRef": "0",
         "pageBreak": "0", "columnBreak": "0", "merged": "0"},
    )
    run = etree.SubElement(p, _hp("run"), {"charPrIDRef": "0"})
    etree.SubElement(run, _hp("t")).text = text


def _build_section(title: str, body_lines: "list[str]") -> bytes:
    """스켈레톤 header/secPr 를 물려받아 제목+토큰 본문으로 section0.xml 을 짓는다."""
    skel = HwpxPackage.open(str(SKELETON))
    root = etree.fromstring(skel.entries["Contents/section0.xml"])
    sec_pr = root.find(".//" + _hp("secPr"))
    if sec_pr is None:  # 방어: 스켈레톤이 바뀌면 시끄럽게(조용한 추측 금지).
        raise RuntimeError(f"스켈레톤에 secPr 없음: {SKELETON}")

    for child in list(root):
        root.remove(child)

    # 제목 문단: run[0]=secPr, run[1]=제목 텍스트.
    title_p = etree.SubElement(
        root, _hp("p"),
        {"id": "3121190098", "paraPrIDRef": "0", "styleIDRef": "0",
         "pageBreak": "0", "columnBreak": "0", "merged": "0"},
    )
    sec_run = etree.SubElement(title_p, _hp("run"), {"charPrIDRef": "0"})
    sec_run.append(sec_pr)
    title_run = etree.SubElement(title_p, _hp("run"), {"charPrIDRef": "0"})
    etree.SubElement(title_run, _hp("t")).text = title

    _text_para(root, "")  # 제목 아래 빈 줄
    for line in body_lines:
        _text_para(root, line)

    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def build_template(filename: str, title: str, body_lines: "list[str]") -> None:
    pkg = HwpxPackage.open(str(SKELETON))
    pkg.entries["Contents/section0.xml"] = _build_section(title, body_lines)

    compiled, report = compile_document(pkg)
    if report.skipped:
        raise RuntimeError(f"{filename}: 컴파일 못한 토큰 {[s.name for s in report.skipped]}")

    out = HERE / "templates" / filename
    out.parent.mkdir(parents=True, exist_ok=True)
    compiled.save(str(out))
    print(f"  templates/{filename}: 누름틀 {len(report.compiled)}개")


def write_csv(filename: str, records: "list[dict]") -> None:
    out = HERE / "data" / filename
    out.parent.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=FIELDS, lineterminator="\n")
    w.writeheader()
    for rec in records:
        w.writerow(rec)
    out.write_text(buf.getvalue(), encoding="utf-8-sig")
    print(f"  data/{filename}: {len(records)}건")


def main() -> None:
    print("101 예제 재생성:")
    for filename, title, body_lines in TEMPLATES:
        build_template(filename, title, body_lines)
    write_csv("발주목록.csv", RECORDS)
    write_csv("발주목록_2.csv", RECORDS_2)
    print("완료.")


if __name__ == "__main__":
    main()
