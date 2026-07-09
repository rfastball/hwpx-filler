# HWPX Filler

HWPX(한글) 문서의 누름틀(Field) 값을 일괄 주입하는 데스크톱 앱.
UnivContractor VBA 워크북의 HWPX 생성 엔진을 Python 단독 실행 앱으로 이식한 것.

- **의존성 최소화**: `zipfile` + `lxml` 만으로 HWPX 처리 (PowerShell/MSXML/FSO 불필요)
- **OCF 정확 준수**: `mimetype` 무압축·최상단 규칙을 정확히 재현
- **데이터 소스 플러그인**: Excel/CSV·나라장터 조달청 API, 장기적으로 ERP API 확장 (`data/base.py`)
- **두 번째 능력 — 규격서 개정 diff**: 두 판본의 본문·조항·표를 의미 기반으로 비교해
  변경 항목(숫자·조항 신설/삭제)을 색상 HTML 리포트로 (`core/diff.py`)

## 설치

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev,gui]"
```

## 사용

### CLI

```bash
# 템플릿이 요구하는 필드 확인
python -m hwpxfiller.cli --template template.hwpx --fields

# 템플릿 스키마 추출(필드·타입·표 영역·라벨 → JSON)
python -m hwpxfiller.cli schema template.hwpx --out schema.json

# 저작 보조: 평문 {{토큰}} → 누름틀 컴파일 (--out 없으면 미리보기만)
python -m hwpxfiller.cli fieldize draft.hwpx            # 미리보기(dry-run)
python -m hwpxfiller.cli fieldize draft.hwpx --out template.hwpx

# 템플릿 관리: 위생 점검(유사 필드명·미치환 토큰), 판본 간 필드 드리프트
python -m hwpxfiller.cli lint template.hwpx [--vocab words.txt]
python -m hwpxfiller.cli drift v2025.hwpx v2026.hwpx

# 규격서 개정 비교: 본문·조항·표 의미 기반 diff (--html 없으면 요약만)
python -m hwpxfiller.cli diff v2025.hwpx v2026.hwpx [--html report.html]

# 엑셀 데이터로 일괄 생성
python -m hwpxfiller.cli --template template.hwpx --data data.xlsx \
    --out ./out --pattern "공고서-{{계약명}}"

# 나라장터(조달청 표준 API)에서 취득 → 매핑 프로파일로 템플릿 채우기
#   영문 코드 키(bidNtceNo 등)는 --profile 로 한글 필드에 잇는다(없으면 대부분 빈칸).
python -m hwpxfiller.cli --template template.hwpx --source nara \
    --service-key $DATA_GO_KR_KEY --bgn 202606010000 --end 202606302359 \
    --profile mapping.json --out ./out --pattern "공고서-{{입찰공고번호}}"
```

### GUI

```bash
# 앱 B — 문서 생성(작업 홈 → 에디터/집행)
python -m hwpxfiller.gui.app

# 앱 A — 규격서 개정 diff 리뷰어(판본 2개 → 변경항목 리스트 + HTML 리포트)
python -m hwpxfiller.gui.diff_app
```

## 구조

| 모듈 | 역할 | VBA 원본 |
|------|------|----------|
| `core/package.py` | HWPX OCF ZIP 열기/저장 | `api_Compression` |
| `core/fields.py` | 누름틀 XML DOM 주입 | `clsHWPXParser` |
| `core/schema.py` | 템플릿 스키마 추출(필드·타입·표 영역·라벨) | (신규 — 매핑/폼 토대) |
| `core/authoring.py` | 저작 보조: 평문 `{{토큰}}` → 누름틀 컴파일 | (신규 — `set_field`의 역연산) |
| `core/lint.py` | 템플릿 관리: 위생 lint + 판본 간 필드 드리프트 | (신규 — `modFuzzyMatch` 아이디어) |
| `core/mapping.py` | 소스 레코드 → 템플릿 필드 매핑(alias·N→1 합성·변환)+프로파일 | `frmErpPreview`+`modFuzzyMatch` |
| `core/text_extract.py` | 본문 텍스트 추출기(섹션/문단/표/셀)+커버리지 원장 | (신규 — diff/생성/검증 공용 토대) |
| `core/diff.py` | 규격서 개정 의미 diff: 문단 정렬·단어 강조·변경항목 추출·HTML | (신규 — 트랙 A, VBA선 불가) |
| `core/engine.py` | 단일 문서 생성 조율 | `modHWPXEngine` |
| `core/validate.py` | 사전검증(누락/빈값) | `modHWPgen` |
| `naming.py` | 파일명 패턴(`{{키}}`) 치환 | (파일명 규칙) |
| `batch.py` | 일괄 생성 | `Process_HWP_Generation` |
| `data/excel.py` | 엑셀/CSV 데이터 소스 | (대시보드 페이로드) |
| `data/nara.py` | 나라장터 조달청 API 취득 소스(stdlib urllib) | (신규 — 웹 취득, VBA선 불가) |
| `core/job.py` | 작업(Job) 앵커 — durable {템플릿·매핑·파일명} + 레지스트리 + 집행요청 | (신규 — 원본의 일급 Job 부재를 수리) |
| `gui/` | 앱 B: 작업 홈(`home`)·에디터(`job_editor`)·집행(`run_view`) | (대시보드 버튼) |
| `gui/diff_app.py` | 앱 A: 개정 diff 리뷰어(별도 진입점, 읽기 도구) | (신규 — VBA선 불가) |

## 테스트

```bash
pytest
```
