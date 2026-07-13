"""시나리오 fixture 한 벌 결정적 재생성 — ``authoring.compile_document`` 기반.

``tests/corpus/scenario/`` 의 hwpx 템플릿·데이터(csv/xlsx)를 **단일 진실원**(이 스크립트에
박힌 3건 데이터 + 필드 레이아웃)에서 결정적으로 파생한다. 같은 입력 → 같은 출력이라
손 편집으로 갈라진 fixture 를 언제든 되돌린다.

무엇을 만드나
--------------
- ``templates/입찰공고서.hwpx`` (23필드) — corpus/real 재사용에서 **분리 저작**.
- ``templates/구매요청서.hwpx`` (10필드 부분집합).
- ``data/조달_한글.csv`` (utf-8-sig) — 한글 헤더 = 템플릿 필드(직접 매칭용).
- ``data/조달_한글.xlsx`` — 같은 데이터·다른 형식(전 셀 텍스트로 CSV 와 패리티).

무엇을 안 만드나(손 저작 텍스트 — 리뷰 가독성 우선)
  ``data/나라장터_매핑.json``, ``data/나라장터_응답.json``,
  ``text_templates/*.txt`` 는 사람이 직접 관리한다.

저작 방식
---------
실코퍼스 스켈레톤(``form_purchase_v1.hwpx``)의 header/secPr 를 물려받아 본문만 평문
``{{토큰}}`` 문단으로 갈아끼운 뒤 :func:`authoring.compile_document` 로 누름틀 컴파일한다
(``README`` 의 2번째 템플릿 저작 메모와 같은 관례). id/fieldid 는 XML 기존 정수 id
최댓값 위에서 결정적 할당.

실행::

    python scripts/gen_scenario_fixtures.py
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

from lxml import etree

from hwpxfiller.core.authoring import compile_document
from hwpxcore.package import HwpxPackage

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"

ROOT = Path(__file__).resolve().parent.parent
SCENARIO = ROOT / "tests" / "corpus" / "scenario"
SKELETON = ROOT / "tests" / "corpus" / "real" / "form_purchase_v1.hwpx"

# ------------------------------------------------------------------ 데이터(진실원)
# 조달 어휘. 일시 단일프레임은 **일자+시각 두 컬럼**으로 분해해 엄격 1:1 매핑 모델과
# 정합한다(개찰일시 → 개찰일자/개찰시각). 직접 매칭 경로라 값은 원문(서식 미적용).
FIELDS = [
    "입찰공고번호", "수요기관", "공고명", "계약방법", "세부품명",
    "사업예산", "추정가격", "수량", "분할납품", "입찰방법",
    "낙찰자결정방법", "납품기한", "인도조건", "하자담보기간", "입찰개시일시",
    "입찰마감일시", "개찰일자", "개찰시각", "등록마감일시", "담당부서",
    "담당자", "담당자 전화번호", "세부품명번호",
]

RECORDS = [
    {
        "입찰공고번호": "2026-001", "수요기관": "해양수산부",
        "공고명": "친환경 선박용 소화장비 구매", "계약방법": "일반경쟁입찰",
        "세부품명": "선박용 소화기", "사업예산": "50000000", "추정가격": "45000000",
        "수량": "20", "분할납품": "불가", "입찰방법": "전자입찰",
        "낙찰자결정방법": "적격심사", "납품기한": "2026-09-30", "인도조건": "수요기관 인도",
        "하자담보기간": "1년", "입찰개시일시": "2026-07-15 09:00",
        "입찰마감일시": "2026-07-21 17:00", "개찰일자": "2026-07-22", "개찰시각": "10:00",
        "등록마감일시": "2026-07-21 17:00", "담당부서": "장비구매팀", "담당자": "김담당",
        "담당자 전화번호": "044-200-1234", "세부품명번호": "1234567890",
    },
    {
        "입찰공고번호": "2026-002", "수요기관": "국립수산과학원",
        "공고명": "수산자원조사용 수중드론 구매", "계약방법": "제한경쟁입찰",
        "세부품명": "수중드론", "사업예산": "80000000", "추정가격": "72000000",
        "수량": "5", "분할납품": "가능", "입찰방법": "전자입찰",
        "낙찰자결정방법": "협상에의한계약", "납품기한": "2026-10-31", "인도조건": "수요기관 인도",
        "하자담보기간": "2년", "입찰개시일시": "2026-07-16 09:00",
        "입찰마감일시": "2026-07-22 17:00", "개찰일자": "2026-07-23", "개찰시각": "10:00",
        "등록마감일시": "2026-07-22 17:00", "담당부서": "연구지원팀", "담당자": "박담당",
        "담당자 전화번호": "051-720-5678", "세부품명번호": "9876543210",
    },
    {
        "입찰공고번호": "2026-003", "수요기관": "부산지방해양수산청",
        "공고명": "항만 CCTV 통합관제 장비 구매", "계약방법": "일반경쟁입찰",
        "세부품명": "네트워크 카메라", "사업예산": "120000000", "추정가격": "108000000",
        "수량": "40", "분할납품": "불가", "입찰방법": "전자입찰",
        "낙찰자결정방법": "적격심사", "납품기한": "2026-11-30", "인도조건": "현장 인도",
        "하자담보기간": "3년", "입찰개시일시": "2026-07-18 09:00",
        "입찰마감일시": "2026-07-25 17:00", "개찰일자": "2026-07-26", "개찰시각": "10:00",
        "등록마감일시": "2026-07-25 17:00", "담당부서": "정보화담당관", "담당자": "이담당",
        "담당자 전화번호": "051-609-8765", "세부품명번호": "5555512345",
    },
]

# ------------------------------------------------------------------ 템플릿 레이아웃
# 각 줄은 평문 {{토큰}} 문단으로 저작 → 컴파일하면 누름틀이 된다. 인접 토큰
# ({{개찰일자}} {{개찰시각}})은 리터럴 공백을 보존한 채 각각 별도 누름틀로 컴파일된다.
BID_NOTICE_LINES = [
    "공고번호: {{입찰공고번호}}",
    "수요기관: {{수요기관}}",
    "공고명: {{공고명}}",
    "계약방법: {{계약방법}}",
    "세부품명: {{세부품명}}  (품명번호 {{세부품명번호}})",
    "사업예산: {{사업예산}}",
    "추정가격: {{추정가격}}",
    "수량: {{수량}}    분할납품: {{분할납품}}",
    "입찰방법: {{입찰방법}}",
    "낙찰자결정방법: {{낙찰자결정방법}}",
    "납품기한: {{납품기한}}",
    "인도조건: {{인도조건}}",
    "하자담보기간: {{하자담보기간}}",
    "입찰개시일시: {{입찰개시일시}}",
    "입찰마감일시: {{입찰마감일시}}",
    "개찰일시: {{개찰일자}} {{개찰시각}}",
    "등록마감일시: {{등록마감일시}}",
    "담당부서: {{담당부서}}",
    "담당자: {{담당자}}  전화 {{담당자 전화번호}}",
]

PURCHASE_REQ_LINES = [
    "수요기관: {{수요기관}}",
    "요청건명: {{공고명}}",
    "세부품명: {{세부품명}}  (품명번호 {{세부품명번호}})",
    "수량: {{수량}}",
    "추정가격: {{추정가격}}",
    "납품기한: {{납품기한}}",
    "인도조건: {{인도조건}}",
    "담당자: {{담당자}}  전화 {{담당자 전화번호}}",
]

TEMPLATES = [
    ("입찰공고서.hwpx", "■ 입 찰 공 고 서", BID_NOTICE_LINES),
    ("구매요청서.hwpx", "■ 구 매 요 청 서", PURCHASE_REQ_LINES),
]


def _hp(tag: str) -> str:
    return f"{{{HP}}}{tag}"


def _text_para(root: etree._Element, text: str, para_id: "str | None" = None) -> etree._Element:
    """평문 한 줄을 담은 ``hp:p`` (charPr/paraPr=0). 컴파일 전 저작 문단."""
    attrs = {"paraPrIDRef": "0", "styleIDRef": "0",
             "pageBreak": "0", "columnBreak": "0", "merged": "0"}
    if para_id is not None:
        attrs = {"id": para_id, **attrs}
    p = etree.SubElement(root, _hp("p"), attrs)
    run = etree.SubElement(p, _hp("run"), {"charPrIDRef": "0"})
    t = etree.SubElement(run, _hp("t"))
    t.text = text
    return p


def _build_section(title: str, lines: "list[str]") -> bytes:
    """스켈레톤 header/secPr 를 물려받아 제목+토큰 본문 문단으로 section0.xml 을 짓는다."""
    skel = HwpxPackage.open(str(SKELETON))
    root = etree.fromstring(skel.entries["Contents/section0.xml"])
    sec_pr = root.find(".//" + _hp("secPr"))
    if sec_pr is None:  # 방어: 스켈레톤이 바뀌면 시끄럽게(조용한 추측 금지).
        raise RuntimeError(f"스켈레톤에 secPr 없음: {SKELETON}")

    # 본문 문단 전부 제거하고 처음부터 다시 쌓는다(secPr 는 위에서 확보).
    for child in list(root):
        root.remove(child)

    # 제목 문단: run[0]=secPr, run[1]=제목 텍스트(구매요청서 관례와 동형).
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
    for line in lines:
        _text_para(root, line)

    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def build_template(filename: str, title: str, lines: "list[str]") -> None:
    """토큰 본문을 컴파일해 시나리오 템플릿을 저장. 모든 줄의 토큰이 누름틀이 되어야 한다."""
    pkg = HwpxPackage.open(str(SKELETON))
    pkg.entries["Contents/section0.xml"] = _build_section(title, lines)

    compiled, report = compile_document(pkg)
    if report.skipped:
        raise RuntimeError(f"{filename}: 컴파일 못한 토큰 {[s.name for s in report.skipped]}")

    out = SCENARIO / "templates" / filename
    compiled.save(str(out))
    print(f"  templates/{filename}: 누름틀 {len(report.compiled)}개")


def write_csv() -> None:
    """조달_한글.csv (utf-8-sig) — 한글 헤더 = 템플릿 필드."""
    out = SCENARIO / "data" / "조달_한글.csv"
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=FIELDS, lineterminator="\n")
    w.writeheader()
    for rec in RECORDS:
        w.writerow(rec)
    out.write_text(buf.getvalue(), encoding="utf-8-sig")
    print(f"  data/조달_한글.csv: {len(RECORDS)}건")


def write_xlsx() -> None:
    """조달_한글.xlsx — CSV 와 같은 레코드. 전 셀 텍스트로 써 CSV 파서와 패리티."""
    from openpyxl import Workbook
    from openpyxl.cell.cell import WriteOnlyCell

    out = SCENARIO / "data" / "조달_한글.xlsx"
    wb = Workbook(write_only=True)
    ws = wb.create_sheet()

    def _row(values: "list[str]") -> list:
        cells = []
        for v in values:
            c = WriteOnlyCell(ws, value=v)
            c.data_type = "s"  # 강제 문자열(숫자형 추측 방지 → CSV 와 동일 dict)
            cells.append(c)
        return cells

    ws.append(_row(FIELDS))
    for rec in RECORDS:
        ws.append(_row([rec[f] for f in FIELDS]))
    wb.save(str(out))
    print(f"  data/조달_한글.xlsx: {len(RECORDS)}건")


def main() -> None:
    print("시나리오 fixture 재생성:")
    for filename, title, lines in TEMPLATES:
        build_template(filename, title, lines)
    write_csv()
    write_xlsx()
    print("완료.")


if __name__ == "__main__":
    main()
