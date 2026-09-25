# 제어면 범위

제품은 문서를 만드는 데 필요한 동사만 노출한다. backend에 존재하는 개체마다 관리 화면,
원장, 선택기, 등록·승인 수명주기를 만들지 않는다.

## 출하 Profile

지원 매체별로 하나의 불변 출하 Profile(HWPX용·TXT용)을 사용한다. 전체 제품에 Profile이
단 하나라는 뜻이 아니다. 사용자 선택·생성·게시·admission·history·fence 관리 기능은 없다.
Profile은 형식 처리의 qualification identity이지 새 운영 제어면이 아니다.

현재 공개 API와 vendor 경계는 [architecture_contract.toml](../tests/architecture_contract.toml),
실제 공개 브리지·dispatch 목록은 [생성 참조](reference/runtime.md)가 소유한다.
관찰 당시의 consumer 수·행 번호를 문서에 별도 원장으로 보관하지 않는다.

## 의미 판정은 backend만 소유

선택의 해석, digest, 적용 판본, 최신성, 준비·실행 가능 여부, blocker와 복구 동사는
application이 판정한다. 웹은 불투명 token과 projection을 전달·표시하고 표시 상태만 소유한다.
코드가 낸 현재성이나 준비 수치를 JS에서 다시 계산하지 않는다.

구성 편집·프리셋 적용은 새 token과 view를 반환한다. 실패는 기존 상태의 성공 변경인 척하지
않고 이유를 남긴다. 어떤 동사가 존재하는지는 registry에서 생성하므로 여기 고정 목록을
복제하지 않는다. 엔진 내부의 능력을 제품 UI의 지원 동작으로 간주하지 않는다.

## HMAC의 위협 모델

HMAC은 backend가 발급한 컨텍스트의 무결성과 용도·작업 결속을 검증하는 수단이다.
독립적인 사용자 권한 체계나 현재 revision·Work·실행 가능성의 증명은 아니다.
서명 검증과 현재 상태 대조, 잠금, 재전송·소비 검사는 각각 필요하다.
유효한 서명만 보고 오래된 선택이나 다른 작업에 명령을 적용하지 않는다.

## 영속 상태와 효과

외부 효과를 안전하게 수행하는 데 필요한 영속만 둔다. 새 first-seen 원장이나 범용
등록·승인 ledger를 추가할 때에는 재전송·중복·복구에 왜 필요한지 실제 소비 경계와
음성 테스트로 증명한다. 이미 있는 이름 유일성·CAS·token version으로 해결되는 문제에
새 durable 원장을 중복 도입하지 않는다.

선택 자동 유지의 보수적 조건은 [핵심 워크플로](core-workflow.md)가 소유한다.
미지원·손상·최신성 불명 상태를 성공 fallback으로 낮추지 않는다.

## 강제 검사

[제어면 축소 검사](../tests/repo_contract/test_control_surface_reduction.py),
[브리지 계약](../tests/repo_contract/test_bridge_contract.py),
[구성 제품 테스트](../tests/test_slot_configuration_product.py),
[제어면 증거 테스트](../tests/test_control_plane_evidence.py)가 경계를 지킨다.
문서 재생성과 별개로 이 검사들이 실제 코드의 금지·허용 동작을 판단한다.
