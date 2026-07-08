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
| `core/engine.py` | 단일 문서 생성 조율 | `modHWPXEngine` |
| `core/validate.py` | 사전검증(누락/빈값) | `modHWPgen` |
| `batch.py` | 일괄 생성 | `Process_HWP_Generation` |
| `data/excel.py` | 엑셀/CSV 데이터 소스 | (대시보드 페이로드) |
| `gui/` | PySide6 데스크톱 UI | (대시보드 버튼) |

## 테스트

```bash
pytest
```
