# 문서 지도

> `manifest.toml`에서 생성한다. 이 파일은 직접 편집하지 않는다.

현재 동작은 코드·테스트·빌드 설정이 최종 권위다. 현재 계약을 먼저 읽는다.
변경 이력·완료 보고는 Git, 실행 상태는 GitHub 이슈가 소유한다.
문서의 생성·검토·삭제 절차는 [유지 규칙](MAINTENANCE.md)을 따른다.

## 현재 계약

| 문서 | 소유하는 내용 |
|---|---|
| [UI_CONTRACT.md](UI_CONTRACT.md) | 현재 UI 계약의 읽기 경로와 변경 단위 |
| [core-workflow.md](core-workflow.md) | 개체·권위·정의에서 관찰까지의 전이 |
| [runtime.md](ui/runtime.md) | UI 계층·통신·React·셸·오버레이 책임 |
| [editor.md](ui/editor.md) | 작업 편집·연결 확인·저장 경계 |
| [execution.md](ui/execution.md) | 데이터 세션·생성·산출물 관찰·TXT 복사 |
| [storage.md](ui/storage.md) | 작업 목록·설정·출력 폴더·템플릿 루트 |
| [CONTROL_PLANE_SCOPE.md](CONTROL_PLANE_SCOPE.md) | Profile·token·의미 판정·영속 제어면의 경계 |
| [FEATURE_SCOPE.md](FEATURE_SCOPE.md) | 코드가 남아 있는 비노출·비출하 기능 |
| [DESIGN_LANGUAGE.md](DESIGN_LANGUAGE.md) | 시각 원칙·토큰·상호작용 검증 책임 |
| [UI_VOCABULARY.md](UI_VOCABULARY.md) | 사용자 가시 명칭·빈 값·수량 단위 |
| [COPY_STYLE_GUIDE.md](COPY_STYLE_GUIDE.md) | 사용자 문장의 형식·예산·금지 패턴 |
| [DEVELOPMENT_ENVIRONMENT.md](DEVELOPMENT_ENVIRONMENT.md) | 설치·검증·패키징·출하 절차 |
| [ROADMAP.md](ROADMAP.md) | 장기 방향과 착수 전 필요한 증거 |
| [MAINTENANCE.md](MAINTENANCE.md) | 문서 분류·재생성·의미 검토·CI 정책 |
| [UI_GALLERY.html](UI_GALLERY.html) | 제품 CSS를 사용하는 시각 부품 갤러리 |
| [README.md](../README.md) | 사용자 제품 소개·설치·실행 진입 |
| [PRODUCT.md](../PRODUCT.md) | 제품 맥락·범위·사용 원칙 요약 |
| [CLAUDE.md](../CLAUDE.md) | 에이전트 공통 작업 규율 |
| [AGENTS.md](../AGENTS.md) | 에이전트 진입점과 위임 정책 |

## 자동 생성 참조

| 문서 | 소유하는 내용 |
|---|---|
| [runtime.md](reference/runtime.md) | 설정·AST에서 추출한 환경·메서드·dispatch·CI |

## 기계 판독 정본

| 문서 | 소유하는 내용 |
|---|---|
| [module_rings.toml](module_rings.toml) | 제품 모듈 ring 좌표와 의존 방향 |
| [package_coverage_floors.toml](package_coverage_floors.toml) | 패키지별 line·branch coverage 하한 |
| [ui_copy_census.toml](ui_copy_census.toml) | 화면 문장 다중집합과 유예 예산 |

## 형식 관측 증거

| 문서 | 소유하는 내용 |
|---|---|
| [HWPX_STRUCTURAL_RANGE_S0.md](HWPX_STRUCTURAL_RANGE_S0.md) | HWPX 구조 구간의 원관측·재현 근거 |
| [HWPX_METATAG_S1_SPIKE.md](HWPX_METATAG_S1_SPIKE.md) | MetaTag 인코딩·식별과 한글 관측 근거 |

## 연구·제안

| 문서 | 소유하는 내용 |
|---|---|
| [DOCUMENT_AUTHORITY_LAYERS.md](DOCUMENT_AUTHORITY_LAYERS.md) | 문서 표현의 권위 계층을 위한 이론·제안 |

증거·연구는 현재 구현의 다른 정본이 아니다. 관측의 맥락과 미래 제안을 구분한다.
