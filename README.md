# HWPX Tools

공통 HWPX 파서 위에 선 **독립 제품 둘** — 모노레포(서브프로젝트 구조):

```
src/hwpxcore/     공통 파서 — OCF 패키지(zip)·문서 트리 추출·검증. 제품 로직 없음.
src/hwpxdiff/     ① 규격서 개정 비교(읽기 도구) — 전문 신구대비표 GUI + CLI + 단독 exe
src/hwpxfiller/   ② 누름틀 값 주입(쓰기 도구) — UnivContractor VBA 엔진의 Python 포트
```

의존 방향은 아래로만: `hwpxdiff → hwpxcore ← hwpxfiller` (두 제품 간 상호 임포트 금지).

- **의존성 최소화**: `zipfile` + `lxml` 만으로 HWPX 처리 (PowerShell/MSXML/FSO 불필요)
- **OCF 정확 준수**: `mimetype` 무압축·최상단 규칙을 정확히 재현
- **hwpxfiller** — 데이터 소스 플러그인: Excel/CSV·나라장터 조달청 API, 장기적으로 ERP 확장
- **hwpxdiff** — 두 판본의 본문·조항·표를 의미 기반 비교, 원문 전체를 좌우 대조(신구대비표)로
  렌더. GUI `hwpx-diff`(또는 `python -m hwpxdiff`), CLI `hwpxdiff OLD NEW [--html]`,
  단독 배포는 `packaging/`(PyInstaller 단일 exe)

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

# 규격서 개정 비교(별도 제품 hwpxdiff): 의미 기반 diff (--html 없으면 요약만)
python -m hwpxdiff.cli v2025.hwpx v2026.hwpx [--html report.html]

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

# 앱 A(hwpxdiff) — 규격서 개정 diff 리뷰어(전문 신구대비표 + 변경 그룹 리스트)
python -m hwpxdiff
```

## 구조

**hwpxcore — 공통 파서** (제품 로직 없음)

| 모듈 | 역할 | VBA 원본 |
|------|------|----------|
| `hwpxcore/package.py` | HWPX OCF ZIP 열기/저장 | `api_Compression` |
| `hwpxcore/text_extract.py` | 본문 텍스트 추출기(섹션/문단/표/셀)+커버리지 원장 | (신규 — diff/생성/검증 공용 토대) |
| `hwpxcore/validate.py` | 사전검증(누락/빈값) | `modHWPgen` |

**hwpxdiff — 개정 비교** (읽기 도구, `hwpxcore` 에만 의존)

| 모듈 | 역할 | VBA 원본 |
|------|------|----------|
| `hwpxdiff/diff.py` | 의미 diff: 문단 정렬·낱말 강조·전문 대조 스트림·변경항목 | (신규 — 트랙 A, VBA선 불가) |
| `hwpxdiff/app.py` | GUI: 전문 신구대비표 + 변경 그룹 네비게이션 | (신규 — VBA선 불가) |
| `hwpxdiff/cli.py` | CLI: 요약 출력·HTML 리포트 저장 | (신규) |

**hwpxfiller — 누름틀 주입** (쓰기 도구, `hwpxcore` 에만 의존)

| 모듈 | 역할 | VBA 원본 |
|------|------|----------|
| `core/fields.py` | 누름틀 XML DOM 주입 | `clsHWPXParser` |
| `core/schema.py` | 템플릿 스키마 추출(필드·타입·표 영역·라벨) | (신규 — 매핑/폼 토대) |
| `core/authoring.py` | 저작 보조: 평문 `{{토큰}}` → 누름틀 컴파일 | (신규 — `set_field`의 역연산) |
| `core/lint.py` | 템플릿 관리: 위생 lint + 판본 간 필드 드리프트 | (신규 — `modFuzzyMatch` 아이디어) |
| `core/mapping.py` | 소스 레코드 → 템플릿 필드 매핑(alias·N→1 합성·변환)+프로파일 | `frmErpPreview`+`modFuzzyMatch` |
| `core/engine.py` | 단일 문서 생성 조율 | `modHWPXEngine` |
| `core/job.py` | 작업(Job) 앵커 — durable {템플릿·매핑·파일명} + 레지스트리 + 집행요청 | (신규 — 원본의 일급 Job 부재를 수리) |
| `naming.py` | 파일명 패턴(`{{키}}`) 치환 | (파일명 규칙) |
| `batch.py` | 일괄 생성 | `Process_HWP_Generation` |
| `data/excel.py` | 엑셀/CSV 데이터 소스 | (대시보드 페이로드) |
| `data/nara.py` | 나라장터 조달청 API 취득 소스(stdlib urllib) | (신규 — 웹 취득, VBA선 불가) |
| `gui/` | 앱 B: 작업 홈(`home`)·에디터(`job_editor`)·집행(`run_view`) | (대시보드 버튼) |

## 테스트

```bash
pytest
```
