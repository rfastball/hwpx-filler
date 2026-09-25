# 문서 지도

> manifest.toml에서 생성한다. 직접 편집하지 않는다.

현재 동작은 코드·테스트·빌드 설정이 최종 권위다. 같은 목적의 새 파일 대신 소유 절을 갱신한다.
절차·이름·예산·검토 명령은 [기여 규칙](../CONTRIBUTING.md)을 따른다.

## 읽기와 쓰기의 다섯 목적지

| 목적 | 정본 |
|---|---|
| `product` | [제품](product.md) |
| `architecture` | [아키텍처](architecture.md) |
| `workflow` | [작업 흐름](workflow.md) |
| `ui-style` | [화면 규칙](ui-style.md) |
| `contributing` | [기여와 검증](../CONTRIBUTING.md) |

## 주제별 작성 라우팅

| 주제 | 갱신할 절 |
|---|---|
| `product-purpose` | [목적과 사용자](product.md#product-purpose) |
| `product-scope` | [지원 경계](product.md#product-scope) |
| `product-direction` | [재개 조건](product.md#product-direction) |
| `architecture-boundaries` | [계층과 실행 자산](architecture.md#architecture-boundaries) |
| `architecture-runtime` | [통신과 화면 수명](architecture.md#architecture-runtime) |
| `architecture-authority` | [의미 권위와 제어면](architecture.md#architecture-authority) |
| `workflow-definition` | [작업 정의와 저장](workflow.md#workflow-definition) |
| `workflow-template` | [템플릿 저작·적용·구성](workflow.md#workflow-template) |
| `workflow-data` | [데이터 세션·선택·범위](workflow.md#workflow-data) |
| `workflow-generation` | [생성과 덮어쓰기](workflow.md#workflow-generation) |
| `workflow-results` | [결과 관찰과 TXT 복사](workflow.md#workflow-results) |
| `workflow-storage` | [라이브러리·폴더·설정](workflow.md#workflow-storage) |
| `ui-terms` | [용어·빈 값·단위](ui-style.md#ui-terms) |
| `ui-copy` | [문안과 검수](ui-style.md#ui-copy) |
| `ui-visual` | [시각·배치·접근성](ui-style.md#ui-visual) |
| `development` | [환경·검증·출하](../CONTRIBUTING.md#development) |
| `changes` | [변경과 리뷰](../CONTRIBUTING.md#changes) |
| `documentation` | [문서 작성과 라우팅](../CONTRIBUTING.md#documentation) |

## 진입점·생성 참조

- [런타임 참조](reference/runtime.md)
- [Impeccable 호환 출력](../PRODUCT.md)
- [사용자 소개·실행](../README.md)
- [작업 진입점·Codex 설정](../AGENTS.md)
- [Claude 진입점·도구 설정](../CLAUDE.md)
- [시각 부품 갤러리](reference/ui-gallery.html)

## 실행 가능한 원장

- [모듈 의존 좌표](../tests/contracts/module-rings.toml)
- [패키지 coverage 하한](../tests/contracts/package-coverage-floors.toml)
- [사용자 문장 원장](../tests/contracts/ui-copy-census.toml)
- [공개 경계·vendor 계약](../tests/architecture_contract.toml)

## 관측과 연구

- [HWPX 구조 구간 관측](evidence/hwpx-ranges.md)
- [HWPX MetaTag 관측](evidence/hwpx-metatags.md)
- [문서 표현 권위 연구](research/document-authority.md)

기능 계획·진행·담당·완료·리뷰는 GitHub 이슈·PR, 재현 입력은 테스트 fixture에 둔다.
작은 제안은 이슈로, 독립 장문 모델만 연구로 분리한다. 증거·연구는 현재 계약을 대신하지 않는다.
예제 설명·코퍼스·테스트/제품 HTML도 manifest에 용도별 정확한 경로로 등록한다.
