# HWPX Filler

HWPX(한글) 문서의 누름틀(Field) 값을 일괄 주입하는 데스크톱 앱.
UnivContractor VBA 워크북의 HWPX 생성 엔진을 Python 단독 실행 앱으로 이식한 것.

- **의존성 최소화**: `zipfile` + `lxml` 만으로 HWPX 처리 (PowerShell/MSXML/FSO 불필요)
- **OCF 정확 준수**: `mimetype` 무압축·최상단 규칙을 정확히 재현
- **데이터 소스 플러그인**: 우선 Excel/CSV, 장기적으로 ERP API 확장 (`data/base.py`)

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

# 엑셀 데이터로 일괄 생성
python -m hwpxfiller.cli --template template.hwpx --data data.xlsx \
    --out ./out --pattern "공고서-{{계약명}}"
```

### GUI

```bash
python -m hwpxfiller.gui.app
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
| `core/engine.py` | 단일 문서 생성 조율 | `modHWPXEngine` |
| `core/validate.py` | 사전검증(누락/빈값) | `modHWPgen` |
| `batch.py` | 일괄 생성 | `Process_HWP_Generation` |
| `data/excel.py` | 엑셀/CSV 데이터 소스 | (대시보드 페이로드) |
| `gui/` | PySide6 데스크톱 UI | (대시보드 버튼) |

## 테스트

```bash
pytest
```
