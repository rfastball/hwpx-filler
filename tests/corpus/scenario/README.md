# 시나리오 코퍼스 — 여러 템플릿 × 여러 자료 실사용 재현

조달 담당자의 실제 워크플로 한 벌을 재현하는 **자족 fixture 번들**이다. 한 세트의 입찰
데이터를 여러 형식의 소스에서 읽어, 서로 다른 필드 집합의 템플릿(hwpx 2 + txt 2)에
채운다. 자동 회귀([`tests/test_scenario_e2e.py`](../../test_scenario_e2e.py))와 GUI 수동
QA 가 **같은 파일**을 공유한다.

`corpus/real/`(추출·diff 골든)과 분리된 별도 루트라 골든 파라미터라이즈에 휩쓸리지 않는다.

## 구성

```
scenario/
├─ templates/
│   ├─ 입찰공고서.hwpx      25필드 전량 — scenario 전용 저작(입찰개시·입찰마감·개찰 일자/시각 분리)
│   └─ 구매요청서.hwpx      10필드 부분집합 — fieldize(authoring.compile_document)로 저작
├─ text_templates/          ← HWPXFILLER_HOME 을 scenario/ 로 두면 GUI txt 화면이 나열
│   ├─ 온나라기안.txt        내부 기안문 — {{필드}} 평문
│   └─ 게시요약.txt          공개 게시 요약 — {{필드}} 평문
└─ data/
    ├─ 조달_한글.csv         한글 헤더 = 템플릿 필드(직접 매칭). 3건. utf-8-sig
    ├─ 조달_한글.xlsx        동일 데이터·다른 소스 형식(패리티 검증용·전 셀 텍스트)
    ├─ 나라장터_응답.json     영문 코드 키(bidNtceNo…) 표준서비스 응답 형태. 2건
    └─ 나라장터_매핑.json     영문 키 → 한글 필드 + 금액/일시 서식 정규화(MappingProfile)
```

모든 템플릿·데이터는 **같은 조달 어휘 25필드**를 공유한다. 그래서 한 소스가 여러
템플릿을 채우고, 소스 어휘 차이(영문 vs 한글)는 매핑 프로파일이 흡수한다.

**일시 단일프레임 분해.** 엄격 1:1 매핑 모델(한 필드 ← 한 소스 키, 결합 없음)에 맞춰
`입찰개시일시`·`입찰마감일시`·`개찰일시`를 각각 `…일자`(date 기본 서식) + `…시각`
(date `%H:%M`) 두 필드로 나눴다. CSV/xlsx 는 두 컬럼으로, txt 는 인접
`{{…일자}} {{…시각}}` 토큰으로, hwpx 는 두 누름틀로 심는다. 나라장터 매핑은
`bidBeginDate`/`bidBeginTm`·`bidClseDate`/`bidClseTm`·`opengDate`/`opengTm` 을 각각 잇는다.

## 매칭 표

| 소스 | 어휘 | 매핑 필요 | 입찰공고서(25) | 구매요청서(10) | txt 기안 |
|------|------|:---:|:---:|:---:|:---:|
| `조달_한글.csv` / `.xlsx` | 한글 헤더 = 필드 | ✗ (직접) | 전량 채움 | 부분집합 채움·여분 무시 | 원문 값 |
| `나라장터_응답.json` | 영문 코드 키 | ✓ `나라장터_매핑.json` | 16필드 채움·9필드 미충족 | — | 서식 값(WYSIWYG) |

핵심 대비: 한글 CSV 는 세부품명·수량 등 25필드를 **직접** 채우지만, 나라장터 소스엔
그 값이 원천에 없어 해당 누름틀이 **미충족으로 남는다**(더 풍부한 CSV 를 선호할 실증
근거). 반대로 나라장터 경로는 매핑이 금액(`45,000,000원`)·일시(개찰일자 `2026. 7. 22.`
+ 개찰시각 `10:00`)를 정규화한다.

## 자동 회귀

```bash
pytest tests/test_scenario_e2e.py
```

소스 형식 무관(CSV=xlsx) · 직접 매칭 배치 · 부분집합 템플릿 · 매핑 경로 · 얇은 소스
대비 · txt 렌더 — 실사용 불변식을 Qt 없이 검증한다.

## GUI 수동 QA

```powershell
$env:HWPXFILLER_HOME = "$PWD\tests\corpus\scenario"   # txt 트랙이 이 폴더를 나열
python -m hwpxfiller.webapp
```

**HWPX 작업 트랙**
1. 홈에서 새 작업 → 템플릿으로 `templates/입찰공고서.hwpx` 선택.
2. 에디터에서 데이터 `data/조달_한글.csv`(또는 `.xlsx`)를 물려 매핑 확정
   (한글 헤더라 대부분 항등 매핑). 파일명 패턴 `입찰공고서-{{입찰공고번호}}`.
3. 실행 화면에서 3건 중 선택 → 생성. 산출 3개, 값 주입 확인.
4. `templates/구매요청서.hwpx` 로 같은 데이터를 부분집합 템플릿에 채워 비교.
5. 나라장터 경로: `data/나라장터_응답.json`을 소스로, `data/나라장터_매핑.json`을
   매핑으로 물려 영문 키가 한글 필드로 이어지고 금액/일시가 서식되는지 확인.

**txt 기안 트랙**
- txt 화면에 `온나라기안`·`게시요약`이 뜬다. 데이터를 붙여 레코드 스텝으로 넘기며
  미충족 토큰(`{{입찰방법}}` 등)이 그대로 남아 시끄럽게 신호하는지 확인.

## CLI 등가

```bash
# 직접 매칭(한글 CSV → 25필드)
python -m hwpxfiller.cli --template tests/corpus/scenario/templates/입찰공고서.hwpx \
    --data tests/corpus/scenario/data/조달_한글.csv \
    --out ./out --pattern "입찰공고서-{{입찰공고번호}}"

# 매핑 경로(나라장터 응답 JSON 은 소스 어댑터/픽스처 경유 — 라이브 API 대신)
#   프로파일: tests/corpus/scenario/data/나라장터_매핑.json
```

## 결정적 재생성

fixture 한 벌(hwpx 템플릿 2 + csv + xlsx)은 **단일 진실원** 스크립트에서 파생한다:

```bash
python scripts/gen_scenario_fixtures.py
```

`form_purchase_v1.hwpx` 스켈레톤(header 스타일·secPr 페이지설정)을 물려받아 본문만 평문
`{{토큰}}` 문단으로 교체한 뒤 `authoring.compile_document`로 누름틀 컴파일한다(id 는 기존
정수 id 최댓값 위에서 결정적 할당). CSV(utf-8-sig)·xlsx 는 스크립트에 박힌 3건 데이터에서
같이 파생돼 두 형식이 동일 레코드를 낸다. `입찰공고서.hwpx`는 corpus/real 재사용에서
분리해 이 스크립트로 저작하므로 real 골든과 무관하다.

손 저작(리뷰 가독성 우선): `나라장터_매핑.json`·`나라장터_응답.json`·`text_templates/*.txt`.

`구매요청서.hwpx` 필드 10개는 모두 조달 어휘의 부분집합이다:
수요기관·공고명·세부품명·세부품명번호·수량·추정가격·납품기한·인도조건·담당자·담당자 전화번호.
