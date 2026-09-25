# Product

<!-- impeccable:product-schema 1 -->

> 이 문서는 제품 맥락의 요약이다. 현행 동작은 코드·테스트·빌드 설정이 정본이며, UI 계약은 [docs/UI_CONTRACT.md](docs/UI_CONTRACT.md)를 따른다.

## Platform

web

## Users

한국어 Windows 환경에서 HWPX 서식과 표 데이터를 이용해 반복 문서를 만드는 사용자다. HWPX 템플릿에 값을 채우고, 같은 입력을 다시 쓸 수 있게 작업으로 보관한다. 우선 직군과 개인·조직 사용 범위는 미확정이다.

## Product Purpose

문서나르미는 반복 입력을 재사용 가능한 작업으로 묶는다. 사용자는 HWPX를 생성한 뒤 결과 문서의 값과 파일명을 확인하거나, TXT 내용을 검토·복사한다. 성공은 사용자가 자동 연결이나 빈 값을 조용히 넘기지 않고 문서 결과를 확인하여 완성하는 것이다.

## Positioning

한글 프로그램이나 COM 자동화에 의존하지 않고 ZIP/XML로 HWPX를 직접 다룬다. 자동 연결 결과와 빈 값은 사람이 확인하도록 드러낸다. 시장 우월성 주장은 하지 않는다.

## Operating Context

Windows pywebview/WebView2 안에서 실행하는 웹 UI이며, 브라우저 SaaS나 모바일 제품이 아니다. 사용자는 문서 만들기와 문서 작업을 오가며 템플릿, 매핑, 파일명을 구성한다.

작업은 데이터 파일 경로·시트·헤더 행·종류에 결속된다. 실제 행 내용은 작업에 저장하지 않고, 명시적 로드·새로고침으로 데이터 세션을 만든다. 실행은 선택 행의 고정 사본을 사용한다. 상세 계약은 [핵심 워크플로](docs/core-workflow.md)를 따른다.

## Capabilities and Constraints

- 입력 데이터는 `.xlsx`, `.xlsm`, `.csv` 및 계약 목록 SQLite를 지원한다. 등록 가능한 계약 목록의 면과 제약은 코드의 제품 게이트가 소유한다.
- 기준 실행 환경은 Windows 11 x64와 WebView2 Runtime이다.
- 생성에 한글 프로그램은 필요하지 않다. 결과 HWPX를 열려면 HWPX를 지원하는 앱이 필요하다.
- UI는 한국어다. 문안과 용어의 정본은 [COPY_STYLE_GUIDE.md](docs/COPY_STYLE_GUIDE.md), [UI_VOCABULARY.md](docs/UI_VOCABULARY.md)다.
- 우선 직군, 조직 범위, 추가 제품·접근성 요구는 미확정이다.

## Brand Commitments

제품명은 문서나르미다. 마크 자산은 [narmi-mark.svg](frontend/img/narmi-mark.svg)에 있다.

## Evidence on Hand

- [README.md](README.md)와 [quickstart-101](examples/quickstart-101/README.md)은 실제 사용 흐름의 근거다.
- [proof-mapping.png](assets/readme/proof-mapping.png)는 매핑 화면 근거 자산이다.
- 출하 여부, 고객 사례, 성능 수치, 인증은 이 문서에서 추정하거나 만들지 않는다.

## Product Principles

1. 문서 생성 후 사용자가 결과 문서의 값과 파일명을 확인한다.
2. 오류·자동 연결·빈 값은 감추지 않고 이유와 함께 보인다.
3. 반복 입력은 재사용 작업으로 보존한다.
4. 사용자 문서와 데이터는 제품이 임의로 바꾸거나 잃지 않게 다룬다.

## Accessibility & Inclusion

기존 키보드·초점·ARIA 계약, OS의 reduced motion, 대비 계약은 [UI 계약](docs/UI_CONTRACT.md)과 코드·테스트에서 보존한다. 접근성 인증이나 추가 요구사항은 확정하지 않는다.
