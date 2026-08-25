"""온보딩 예제 자산 결정적 생성 — 정본은 ``docs/ONBOARDING_TUTORIAL.md`` §2.

이 폴더의 템플릿·TXT·CSV 를 **단일 진실원**(이 스크립트에 박힌 문서 레이아웃과
``RECORDS``)에서 결정적으로 파생한다. 같은 입력 → 같은 bytes 라, 손으로 연 hwpx 가
어쩌다 갈라져도 언제든 되돌린다. ``examples/quickstart-101/make_template.py`` 의
자매편이고 자산 계약은 ``tests/test_onboarding_assets.py`` 가 지킨다.

무엇을 만드나
--------------
- ``templates/계약체결안내.hwpx`` — 누름틀 7필드(기본 티어의 첫 문서).
- ``templates/구매추진안내.hwpx`` — 누름틀 5필드 부분집합(응용 티어의 두 번째 작업).
- ``templates/공고서_연습.hwpx`` — **미컴파일**. 평문 ``{{토큰}}`` 5개 + 구간 표기
  (항목 1·그 안의 선택 갈래 2)를 그대로 남긴다. 고급 티어 T15 의 변환 재료다.
- ``text_templates/계약안내_기안.txt`` — 6필드 평문 기안.
- ``text_templates/오류연습_보증금.txt`` — CSV 에 **열이 없는** ``{{계약보증금}}`` 포함
  (저작측 결핍 → 비움 확정 게이트 학습).
- ``data/계약목록.csv`` (utf-8-sig) — 한글 헤더 8열 = 필드명 직접 매칭. 3건.
- ``data/계약목록_2.csv`` (utf-8-sig) — 같은 헤더 2건, 한 행의 ``납품조건`` 이 **의도
  결측**(데이터측 결핍 → 빈 값축 재승인 학습).

이름이 곧 값 유형이다(#915)
----------------------------
필드의 값 유형은 템플릿 어디에도 적혀 있지 않다 — 제품은 **이름 문자열**로 추정한다
(:func:`hwpxfiller.domain.schema.infer_type`: ``기한``·``일자``·``날짜`` 등이 들면 date).
그래서 「계약 후 90일 이내」 같은 **자유서식** 값을 담는 칸의 이름에 ``기한`` 을 쓰면,
그 이름이 선언한 날짜 유형과 실제 값이 어긋나 관리 경로에서 「먼저 데이터 문제를
확인하세요」로 막힌다(``RECORD_VALUE_TYPE_INVALID``). 원 공문의 표현이 자유서식이므로
값이 아니라 **이름**을 고쳤다 — 이 자산의 칸 이름은 ``납품조건`` 이고 유형은 text 다.
날짜 유형 필드를 배우는 자리는 quickstart-101(``납품기한`` = ISO 날짜)이 계속 진다.

허구화 규칙(§2.1, 예외 없음)
-----------------------------
실공문에서 차용한 것은 **문서 구조**(수신·제목·항목 나열·발신명의)뿐이다. 기관명·
업체명·인명·번호·연락처·금액·일자는 전부 신작이고 발신명의도 허구 기관이다. 원형
문서의 식별 가능한 값이 자산 어디에도 남지 않는 것이 게이트 조건이라, 금지 문자열
부재는 테스트가 매번 되짚는다.

구간 표기의 모양(재량 판단 기록)
--------------------------------
문법 정본은 :mod:`hwpxfiller.domain.structure_scan` 이다 — ``{{#항목 <id> <라벨>}}`` …
``{{/항목}}`` / ``{{#선택 <id> <라벨>}}`` … ``{{/선택}}``, 마커는 본문 직계 문단을
단독으로 차지하고 「선택」은 「항목」 직속만 가능하다. 선택 정책은 Slot 당
``EXACTLY_ONE``(:mod:`hwpxfiller.domain.slot_selection`)이라 **갈래가 없는 항목은
고를 수 있는 것이 없는 항목**이 된다. 그래서 「넣고 뺄 수 있는 절」을 갈래 둘
(실시/생략)로 짓는다 — 엔진이 가진 단 하나의 구성 동사로 「절을 넣은 문서」와
「절을 뺀 문서」가 둘 다 나온다.

저작 방식
---------
실코퍼스 스켈레톤(``form_purchase_v1.hwpx``)의 header/secPr 를 물려받아 본문만 평문
문단으로 갈아끼운다. 두 누름틀 템플릿은 :func:`authoring.compile_document` 로 필드
토큰을 컴파일하고, ``공고서_연습`` 은 **컴파일하지 않고** 표기 그대로 저장한다.

실행(저장소 루트에서)::

    uv run python examples/onboarding/make_assets.py
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

from lxml import etree

from hwpxfiller.domain.authoring import compile_document
from hwpxfiller.external.hwpx_package_io import read_hwpx_package, write_hwpx_package

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
SKELETON = ROOT / "tests" / "corpus" / "real" / "form_purchase_v1.hwpx"

# ------------------------------------------------------------------ 데이터(진실원)
# 헤더 = 필드명 정확 일치(§2.3) — 매핑 프로파일 없이 CSV 열이 곧바로 누름틀에 꽂힌다.
# 금액은 서식 미적용 원문(101 전례와 같은 표기 — 콤마·단위 없음).
FIELDS = [
    "공고번호",
    "수요기관",
    "품명",
    "사업명",
    "계약방법",
    "계약상대자",
    "계약금액",
    "납품조건",
]

RECORDS = [
    {
        "공고번호": "20260812-001",
        "수요기관": "한빛과학기술연구원",
        "품명": "질량분석기",
        "사업명": "2026년 분석장비 도입 사업",
        "계약방법": "일반(총액)",
        "계약상대자": "㈜다온정밀",
        "계약금액": "298500000",
        "납품조건": "계약 후 90일 이내",
    },
    {
        "공고번호": "20260812-002",
        "수요기관": "청람시시설관리공단",
        "품명": "통근버스 임차용역",
        "사업명": "2026년 하반기 통근버스 임차",
        "계약방법": "제한(총액)",
        "계약상대자": "새벽운수㈜",
        "계약금액": "96800000",
        "납품조건": "2026-12-31",
    },
    {
        "공고번호": "20260812-003",
        "수요기관": "미리내교육진흥원",
        "품명": "사무용 복합기",
        "사업명": "사무환경 개선 물품 구매",
        "계약방법": "일반(총액)",
        "계약상대자": "푸른들오에이",
        "계약금액": "24750000",
        "납품조건": "계약 후 30일 이내",
    },
]

# 둘째 배치 — 같은 헤더·다른 2건. 2행째 ``납품조건`` 이 **의도 결측**이다(§2.2):
# 열은 있고 값이 빈 결핍이라 실행마다 빈 값축 재승인이 서고 산출에는 표식이 남는다.
RECORDS_2 = [
    {
        "공고번호": "20260819-001",
        "수요기관": "한빛과학기술연구원",
        "품명": "초저온냉동고",
        "사업명": "연구장비 추가 도입",
        "계약방법": "일반(총액)",
        "계약상대자": "㈜다온정밀",
        "계약금액": "41200000",
        "납품조건": "계약 후 60일 이내",
    },
    {
        "공고번호": "20260819-002",
        "수요기관": "청람시시설관리공단",
        "품명": "청사 경비용역",
        "사업명": "2027년 청사 경비용역",
        "계약방법": "제한(총액)",
        "계약상대자": "세움경비㈜",
        "계약금액": "152300000",
        "납품조건": "",
    },
]

#: 발신명의 — 허구 기관 하나로 통일한다(실기관명 차용 금지, §2.1).
ISSUER = "누리공공계약원장"

# ------------------------------------------------------------------ 템플릿 레이아웃
# 각 줄이 본문 직계 문단 하나다. 컴파일 대상 둘은 {{토큰}} 이 누름틀이 되고,
# 공고서_연습 은 표기 그대로 남는다.
CONTRACT_LINES = [
    "",
    "수신  {{계약상대자}} 대표",
    "제목  「{{사업명}}」 낙찰자 선정 및 계약체결 안내",
    "",
    "1. 귀 사의 무궁한 발전을 기원합니다.",
    "2. 아래와 같이 낙찰자가 선정되었으므로 계약 체결을 안내합니다.",
    "",
    "  가. 공고번호   : {{공고번호}}",
    "  나. 수요기관   : {{수요기관}}",
    "  다. 품    명   : {{품명}}",
    "  라. 계약금액   : {{계약금액}} 원",
    "  마. 납품조건   : {{납품조건}}",
    "",
    "3. 계약서류는 이 안내를 받은 날부터 7일 이내에 제출하여 주시기 바랍니다.",
    "4. 제출 서류와 절차는 계약지원부로 문의하시기 바랍니다.  끝.",
    "",
    ISSUER,
]

PURCHASE_LINES = [
    "",
    "수신  {{수요기관}} 계약담당관",
    "제목  「{{품명}}」 계약방법 결정 및 구매추진 안내",
    "",
    "1. 요청하신 구매 건의 계약방법을 아래와 같이 결정하고 구매를 추진합니다.",
    "",
    "  가. 공고번호 : {{공고번호}}",
    "  나. 계약방법 : {{계약방법}}",
    "  다. 납품조건 : {{납품조건}}",
    "",
    "2. 공고 이후 일정이 바뀌면 다시 안내합니다.  끝.",
    "",
    ISSUER,
]

# 미컴파일 연습본 — 필드 토큰 5개 + 항목 1(그 안의 선택 갈래 2). 마커는 자기 문단을
# 단독으로 차지해야 하므로 각 마커가 한 줄이다(구간 표기 문법 v1).
NOTICE_LINES = [
    "",
    "1. 공고 개요",
    "  가. 공고번호 : {{공고번호}}",
    "  나. 수요기관 : {{수요기관}}",
    "  다. 품    명 : {{품명}}",
    "  라. 계약방법 : {{계약방법}}",
    "  마. 납품조건 : {{납품조건}}",
    "",
    "2. 입찰 참가 자격은 관계 법령과 이 공고에서 정한 바에 따릅니다.",
    "3. 입찰서는 공고에 적힌 마감 시각까지 제출하여야 합니다.",
    "",
    "{{#항목 현장설명회 현장설명회 안내}}",
    "{{#선택 실시 현장설명회 실시}}",
    "4. 현장설명회를 실시합니다. 일시와 장소는 따로 안내합니다.",
    "{{/선택}}",
    "{{#선택 생략 현장설명회 생략}}",
    "4. 현장설명회를 생략합니다.",
    "{{/선택}}",
    "{{/항목}}",
    "",
    "5. 이 공고서는 연습용으로 지은 허구 문서입니다.  끝.",
    "",
    ISSUER,
]

# (파일명, 제목, 본문줄, 필드 컴파일 여부)
TEMPLATES = [
    ("계약체결안내.hwpx", "■ 낙찰자 선정 및 계약체결 안내", CONTRACT_LINES, True),
    ("구매추진안내.hwpx", "■ 계약방법 결정 및 구매추진 안내", PURCHASE_LINES, True),
    ("공고서_연습.hwpx", "■ 입찰공고서(연습)", NOTICE_LINES, False),
]

# ------------------------------------------------------------------ TXT 레이아웃
DRAFT_TXT = """제목: [계약 안내] {{품명}} (공고 {{공고번호}})

1. {{수요기관}} 이 발주한 아래 건의 계약 체결을 안내합니다.

  가. 계약상대자 : {{계약상대자}}
  나. 계약금액   : {{계약금액}} 원
  다. 납품조건   : {{납품조건}}

2. 계약서류는 안내를 받은 날부터 7일 이내에 제출합니다.  끝.
"""

DEPOSIT_TXT = """제목: [오류 연습] {{품명}} 계약보증금 안내 — 없는 항목이 어떻게 보이는지 확인

이 초안은 연습용으로 데이터에 없는 토큰을 하나 넣어 두었다.
계약목록.csv 를 연결하면 아래 「계약보증금」 자리만 맞는 열이 없어서,
작업으로 저장할 때 '비움으로 확정'을 묻고 검토·복사 카드에는 (빈 값)으로 남는다.
조용히 지나가지 않는다는 것을 눈으로 확인하는 자리다.

  가. 공고번호   : {{공고번호}}
  나. 계약상대자 : {{계약상대자}}
  다. 계약보증금 : {{계약보증금}}   ← 계약목록.csv 에 없는 열(여기가 빈 값으로 남는다)

정상 초안은 계약안내_기안.txt 를 쓰면 된다.  끝.
"""

TEXT_TEMPLATES = [
    ("계약안내_기안.txt", DRAFT_TXT),
    ("오류연습_보증금.txt", DEPOSIT_TXT),
]


def _hp(tag: str) -> str:
    return f"{{{HP}}}{tag}"


def _text_para(root: etree._Element, text: str) -> None:
    """평문 한 줄을 담은 ``hp:p`` (charPr/paraPr=0). 컴파일 전 저작 문단."""
    p = etree.SubElement(
        root,
        _hp("p"),
        {
            "paraPrIDRef": "0",
            "styleIDRef": "0",
            "pageBreak": "0",
            "columnBreak": "0",
            "merged": "0",
        },
    )
    run = etree.SubElement(p, _hp("run"), {"charPrIDRef": "0"})
    etree.SubElement(run, _hp("t")).text = text


def _build_section(title: str, body_lines: "list[str]") -> bytes:
    """스켈레톤 header/secPr 를 물려받아 제목+본문으로 section0.xml 을 짓는다."""
    skel = read_hwpx_package(SKELETON)
    root = etree.fromstring(skel.entries["Contents/section0.xml"])
    sec_pr = root.find(".//" + _hp("secPr"))
    if sec_pr is None:  # 방어: 스켈레톤이 바뀌면 시끄럽게(조용한 추측 금지).
        raise RuntimeError(f"스켈레톤에 secPr 없음: {SKELETON}")

    for child in list(root):
        root.remove(child)

    # 제목 문단: run[0]=secPr, run[1]=제목 텍스트.
    title_p = etree.SubElement(
        root,
        _hp("p"),
        {
            "id": "3121190098",
            "paraPrIDRef": "0",
            "styleIDRef": "0",
            "pageBreak": "0",
            "columnBreak": "0",
            "merged": "0",
        },
    )
    sec_run = etree.SubElement(title_p, _hp("run"), {"charPrIDRef": "0"})
    sec_run.append(sec_pr)
    title_run = etree.SubElement(title_p, _hp("run"), {"charPrIDRef": "0"})
    etree.SubElement(title_run, _hp("t")).text = title

    for line in body_lines:
        _text_para(root, line)

    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def build_template(
    out_root: Path,
    filename: str,
    title: str,
    body_lines: "list[str]",
    compile_fields: bool,
) -> None:
    pkg = read_hwpx_package(SKELETON)
    pkg.entries["Contents/section0.xml"] = _build_section(title, body_lines)

    if compile_fields:
        pkg, report = compile_document(pkg)
        if report.skipped:
            raise RuntimeError(f"{filename}: 컴파일 못한 토큰 {[s.name for s in report.skipped]}")
        note = f"누름틀 {len(report.compiled)}개"
    else:
        note = "미컴파일(표기 원문 보존)"

    out = out_root / "templates" / filename
    out.parent.mkdir(parents=True, exist_ok=True)
    write_hwpx_package(out, pkg)
    print(f"  templates/{filename}: {note}")


def write_text_template(out_root: Path, filename: str, body: str) -> None:
    out = out_root / "text_templates" / filename
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(body, encoding="utf-8", newline="\n")
    print(f"  text_templates/{filename}: {len(body.splitlines())}줄")


def write_csv(out_root: Path, filename: str, records: "list[dict]") -> None:
    out = out_root / "data" / filename
    out.parent.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=FIELDS, lineterminator="\n")
    w.writeheader()
    for rec in records:
        w.writerow(rec)
    out.write_text(buf.getvalue(), encoding="utf-8-sig", newline="")
    print(f"  data/{filename}: {len(records)}건")


def main(out_root: "Path | None" = None) -> None:
    """자산 한 벌을 ``out_root``(기본값 이 폴더) 아래에 결정적으로 낳는다.

    ``out_root`` 가 인자인 이유는 재생성 결정론을 **임시 폴더에서** 되짚기 위해서다
    (``tests/test_onboarding_assets.py``) — 커밋된 자산을 건드리지 않고 같은 bytes 가
    나오는지 확인한다.
    """
    root = HERE if out_root is None else Path(out_root)
    print("온보딩 예제 재생성:")
    for filename, title, body_lines, compile_fields in TEMPLATES:
        build_template(root, filename, title, body_lines, compile_fields)
    for filename, body in TEXT_TEMPLATES:
        write_text_template(root, filename, body)
    write_csv(root, "계약목록.csv", RECORDS)
    write_csv(root, "계약목록_2.csv", RECORDS_2)
    print("완료.")


if __name__ == "__main__":
    main()
