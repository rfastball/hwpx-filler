# 제품

<a id="product-purpose"></a>
## 목적과 사용자

### Platform

web

### Users

한국어 Windows 환경에서 HWPX 서식과 표 데이터로 반복 문서를 만드는 사용자다.

### Product Purpose

문서나르미는 템플릿·데이터 연결·파일명 규칙을 재사용 가능한 작업으로 묶는다.
사용자는 HWPX를 생성해 결과를 확인하거나 TXT 내용을 검토·복사한다.

### Positioning

한글 프로그램이나 COM 자동화 없이 ZIP/XML로 HWPX를 직접 다룬다.

### Operating Context

Windows pywebview/WebView2에서 실행하는 데스크톱 앱이다. 브라우저 SaaS나 모바일 제품이 아니다.
작업의 저장·실행 규칙은 [작업 흐름](workflow.md)을 따른다.

### Capabilities and Constraints

입력은 `.xlsx`, `.xlsm`, `.csv`와 계약 목록 SQLite다. 기준 환경은 Windows 11 x64와
WebView2 Runtime이다. 생성에는 한글 프로그램이 필요 없지만 결과 파일을 열려면 HWPX
지원 앱이 필요하다.

### Brand Commitments

제품명은 문서나르미다. 제품 마크는 [narmi-mark.svg](../frontend/img/narmi-mark.svg),
원천 브랜드 자산은 [assets/branding](../assets/branding)에 둔다.

### Evidence on Hand

[사용자 소개](../README.md), [실습](../examples/quickstart-101/README.md),
[연결 화면](../assets/readme/proof-mapping.png).

### Product Principles

자동 제안·누락·실패를 숨기지 않는다. 사용자 문서와 데이터를 임의로 변경하거나 잃지 않게 한다.

### Accessibility & Inclusion

키보드·초점·ARIA, reduced motion과 대비 규칙은 [화면 규칙](ui-style.md#ui-visual)을 따른다.

<a id="product-scope"></a>
## 지원 경계

| 기능 | 현재 상태 |
|---|---|
| 작업·템플릿 태그와 그룹 | 웹 UI 비노출. 기존 모델·영속 데이터는 보존 |
| 온보딩 튜토리얼 | 웹 진입·마운트 없음. 배포 자산에 포함하지 않음 |
| 나라장터 API | 웹 UI 비노출. 기존 데이터 풀 항목에는 미지원 사유 표시 |

[온보딩 예제](../examples/onboarding)는 유지 자산이며
[실습](../examples/quickstart-101/README.md)이나 배포 튜토리얼과 구분한다.
로컬 SQLite의 계약 목록(pclm)은 지원 대상이며 제공 범위는 `PCLM_DOC_VIEWS`와 제품 게이트가 정한다.
등록 목록·버전은 [런타임 참조](reference/runtime.md)를 따른다.

임의 조건식의 자동 섹션 조립, 문서 수준 서식 조립, 여러 레코드의 단일 문서 병합,
조판 수준 HWPX→PDF 내보내기는 지원하지 않는다. 작성자가 선언한 항목·선택을 고르는 구성
기능과 산출물의 구조 관찰은 이들 기능과 다르다.
