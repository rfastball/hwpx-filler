# Control Plane Scope — v1 제어면 축소 (SG-03 · #735)

> **문서 상태:** 유효 결정
>
> **갱신(S6G-00 · #806, 2026-08-23):** 아래 본문은 SG-03(#735) 시점의 census 다. 그 **뒤에**
> R2-04a·R2-05a·R2-05b(#740)가 mutable Profile admission 제어면과 stored Plan first-seen ledger 를
> 실제로 **제거**했다. 그러므로 아래 「하나도 제거하지 않는다」는 SG-03 의 당시 약속이지 현재
> 형상이 아니다. 삭제된 것을 현재형으로 인용하던 자리(§1.1·§1.3·§1.4·§1.5·§2.3·§3)에 갱신 표시를
> 달았다 — S6(#807) 설계가 없는 개념을 되살리지 않게 하려는 것이 이 정정의 목적이다(#729 잔여위험 6).

S4·S5 가 심은 exact safety kernel(Qualification manifest, HMAC route/context token,
Python/TypeScript canonical code)은 그대로 둔다. 이 문서는 그 위에 **v1 제품이 실제로 소비하는
권위와 제어면**을 census 로 고정하고, 미래 변경이 조용히 그 표면을 재확장하지 못하게 하는 다섯
개의 scope 결정을 정본화한다.

SG-03 은 **제거 슬라이스가 아니라 pin/narrow 슬라이스**였다(제거는 R2 가 뒤이어 했다). 각 사실은
아래 census 로 기록되고 짝 게이트가 그것을 정적으로 지킨다. 현재 동작의 최종 권위는 코드·테스트
이고 이 문서는 그 경계의 이유를 보존한다.

## 1. 실제 소비자 census

변경 시점(master `92e8c6b`) 기준 production 소비자 전수. **실제 소비자 증거 없이 삭제하지
않는다** — 아래 표가 그 증거다.

### 1.1 Python canonical semantic (단일 권위)

| semantic | 소유 |
|---|---|
| selection canonical bytes/digest | `domain/slot_selection.py` (`canonicalize_selection_set`·`digest_selection_set`·`semantic_selection_equal`) |
| execution canonical bytes/digest | `domain/canonical_execution_encoding.py` (`canonical_execution_bytes`·`canonical_execution_digest`) |
| execution basis / Plan semantic digest | `application/seal_execution_plan.py`·`execution_structure.py`·`execution_compilation.py` |
| record validity | `application/record_validation.py`·`domain/raw_data_record.py` |
| resolved delivery path | `application/generation_delivery.py`·`domain/output_name.py` |
| semantic currentness · runtime admission · materialization readiness | `application/fresh_execution_observation.py` (`decide_runtime_policy_admission`·`decide_materialization_readiness`) |
| Workbench blocker / Primary Action | `application/slot_configuration_context.py`·`slot_configuration_projection.py`·`slot_reconciliation.py` |
| selection compatibility (AUTO_KEEP/REVIEW_REQUIRED/DETACHED) | `application/selection_compatibility.py` (SG-01 · §2.5) |

### 1.2 TypeScript canonical implementations + production import

- `frontend/src/domain/canonical_execution_encoding.ts` — `canonicalExecutionBytes`·`canonicalExecutionDigest`.
- `frontend/src/domain/slot_selection.ts` — `canonicalizeSelectionSet`·`digestSelectionSet`·`semanticSelectionEqual`·`validateSelectionSet`.
- **production importer = 0.** frontend/src·frontend/js 전역에서 이 두 모듈로 resolve 되는 import 는 없다(자기·상호 참조뿐).
- 허용 소비자: `tests/js/canonical_execution_encoding.test.js`·`tests/js/slot_selection.test.js`(wire codec parity), golden `tests/fixtures/execution_canonical_v1_golden.json`·`slot_selection_v1_golden.json`.
- frontend 표시 어휘 단일 출처: `frontend/src/contract/contract.gen.ts`(`scripts/gen_bridge_contract.py` 생성). wire/contract fixture 이지 semantic 재계산이 아니다.

### 1.3 Profile admission 제어면 — **R2-05a(#740)에서 전면 제거됨**

> **갱신(S6G-00 · #806):** 이 절은 원래 mutable Profile admission 제어면의 호출자 census 였다.
> 그 제어면은 R2-05a(#740)가 제거했고 아래 네 모듈은 저장소에 **없다** —
> `external/profile_admission_runner.py` · `host/profile_admission_fence.py` ·
> `domain/qualification_profile_admission.py` · `application/stored_profile_admission.py`.
> 삭제된 것을 현재형으로 인용하면 S6 설계가 그 개념을 되살릴 유인이 된다(#729 잔여위험 6).

지금 남은 것은 **immutable Qualification identity** 하나다.

| 사실 | 소유 | 현재 상태 |
|---|---|---|
| shipping Profile 상수 + manifest | `external/template_inspection.py` (`HWPX_QUALIFICATION_PROFILE` id `hwpx-template-qualification-v4`·`hwpx_qualification_manifest`) | `webapp/template_change.py` 가 소비 |
| `initialize_qualification_profile_admission` | — | **정의·호출 0**(모듈 삭제) |
| `register_published_qualification_profile_admission` | — | **정의·호출 0**(모듈 삭제) |
| `revoke_qualification_profile` | — | **정의·호출 0**(모듈 삭제) |
| per-Work mutation fence | `host/` per-work fence(`PerWorkMutationFence`) | ProfileFence 는 R2-05b(#740)에서 제거 |

production `QualificationProfile(...)` 생성은 정확히 1개다. 위 세 command 이름의 호출 0 은
`tests/repo_contract/test_control_surface_reduction.py` 의 `REMOVED_ADMISSION_CONTROL_CALLS`
census 가 지킨다 — 그 목록과 음성 대조가 같은 상수를 소비하므로 겨냥이 어긋날 수 없다(#805).

### 1.4 durable append-only record 필드 census

> **갱신(S6G-00 · #806):** 원래 표는 baseline **4** 를 말하며 `stored_execution_plan.py` 의
> `first_seen_ledger` 와 삭제된 `stored_profile_admission.py` 를 포함했다. 전자는 R2-04a(#740)가
> 제거했고(seal 은 historical outcome 을 replay 하지 않고 현재 authority 에서 재계산한다) 후자는
> 모듈째 사라졌다. **정본은 이 표가 아니라 게이트의 `LEDGER_BASELINE`** 이고, 아래는 그 사본이다.

| aggregate 모듈 | 필드 | record type |
|---|---|---|
| `application/stored_field_binding.py` | `current_by_application` | `ApplicationRevisionPointer` |
| `application/stored_field_binding.py` | `immutable_binding_revisions` | `FieldBindingRevision` |
| `application/stored_field_binding.py` | `migration_drafts` | `CommittedDraftRecord` |
| `application/stored_field_binding.py` | `application_review_drafts` | `CommittedDraftRecord` |
| `application/stored_field_binding.py` | `first_seen_command_ledger` | `FieldBindingIdempotencyRecord` |
| `application/stored_work_configuration.py` | `processed_requests` | `IdempotencyRecord` |
| `application/work_slot_configuration.py` | `configurations` | `WorkSlotConfigurationDraft` |

`application/work_slot_configuration.py` 는 **first-seen ledger** 를 명시적으로 두지 않는다
("발명 금지 … first-seen ledger(#673)") — 위 `configurations` 는 draft aggregate 이지 ledger 가 아니다.

### 1.5 HMAC token issuing/consuming route

- codec: `application/slot_token.py`(`sign_configuration_token`·`open_configuration_token`·`actor_binding_digest`). secret: `external/slot_token_secret.py`(`load_or_create_active_secret`).
- 유일 소비 route: `webapp/slot_configuration_product.py` — 발급 `_issue_token`, 소비 `_verify_token`. **authorization 은 token 과 독립**(`_route` 의 job load), currentness/version 은 runner(`_command_context`→context resolve/CAS)가 진다.
- **갱신(S6G-00 · #806):** SX 가 소비를 마쳤다 — `webapp/app.py` 가 `SlotConfigurationProduct` 를
  주입하고, 네 command 는 **dispatch 경로**(`action_registry.py` 의 `open_slot_configuration`·
  `refresh_slot_configuration`·`select_slot_option`·`clear_slot_selection`)로 도달한다. 직접
  브리지 경로(`frontend/js/bridge.js`)는 여전히 이 표면을 쓰지 않는다.
- **갱신(S9-03 · #829):** Selection Preset 동사 둘(`save_selection_preset`·
  `apply_selection_preset`)이 같은 route 의 dispatch 소비자로 합류했다 — token 발급·소비
  구조는 불변이고, 직접 브리지는 여전히 이 표면을 쓰지 않는다(census 6 command).

### 1.6 Workbench / Product observation 소비자

- backend: `application/fresh_execution_observation.py`(`PublishedPlanObservation`·`CurrentWorkExecutionObservation` DTO); `webapp/seal_execution_plan_product.py` 가 exact fact 를 공급.
- frontend: `frontend/src/screens/workbench.ts`·`workbench_state.ts` = backend snapshot → field value 순수 projection. `job_run*.ts`·`job_result.ts` = backend projection 렌더. digest/currentness/Plan 재계산 없음.

## 2. Scope 결정

### 2.1 shipping Qualification Profile = 1

기존 durable Profile manifest/admission/history/fence 는 유지한다. v1 제품 정책:

```
built-in shipping Profile = exactly 1
bootstrap explicit admission
user Profile selector = 0 · Profile management UI = 0
dynamic Profile publication product route = 0 · plugin Profile = 0
revoke = internal incident/test 경계 전용
```

복수 runtime/plugin/admin 운영 요구가 실제로 생기면 별도 설계로 #732/#620 에 상향한다.

### 2.2 backend/application 단일 semantic authority

selection canonical bytes·execution basis digest·Plan semantic digest·record validity·resolved
delivery path·semantic currentness·runtime admission·materialization readiness·Workbench
blocker/Primary Action 은 backend/application 이 판정한다. frontend 허용은 opaque ref/token 전달,
projection/observation DTO 렌더, focus/view state, Product command 호출뿐이다. TypeScript canonical
code 는 wire codec parity test·golden vector·contract fixture 범위로만 남고, production React path
의 독립 semantic canonicalization/currentness 판정은 0 이다.

### 2.3 신규 durable ledger allowlist

§1.4 census 의 현존 필드는 제거·migration 하지 않는다. 향후 신규 durable first-seen
ledger 는 **외부효과/중복결과가 입증된 경계**만 후보로 한다:

```
StartMaterialization · Artifact publication · filesystem delivery
overwrite/collision disposition · failed-item retry
```

일반 UI state·Work-local draft·단순 projection command 에 신규 ledger 를 더하려면 실제 재전송
중복효과 위험을 이슈에서 증명하고, allowlist 와 게이트 baseline 을 함께 넓힌다.

### 2.4 HMAC threat model

HMAC token 이 **증명하는 것**: backend-issued context integrity, authenticity of issued claims,
route/Work binding 지원, stale/cross-Work 혼입 탐지. **증명하지 않는 것**: authorization, current
Work/Application, expected aggregate version, per-Work fence acquisition, semantic command validity,
materialization readiness. 정상 gate 는 이 검증들을 독립 유지한다. 새 key-rotation UI/control
plane 이나 새 암호 라이브러리 도입은 이 문서의 목표가 아니다 — HMAC 을 실제 권한 경계로
승격해야 하면 #732/#620 으로 상향한다.

### 2.5 selection 보존은 전체 applied bytes 동일을 요구한다 (v1 수용)

> 등재: S6G-00 · #806. 발단: #729 SX-99 독립 감사 잔여위험 5. 감사자가 **S6 설계 전에 명시적
> 결정 기록이 필요하다**고 지목한 자리다.

`application/selection_compatibility.py::classify_selection` 은 `AUTO_KEEP` 에 두 증거를 **모두**
요구한다.

```text
(a) 구조 fingerprint 가 모든 hop 에서 present-and-identical
(b) applied content digest 가 모든 hop 에서 동일
    = applied candidate bytes 가 chain 전역에서 byte-identical
```

**긴장.** (b)는 문서 전체 bytes 를 본다. 그래서 Template 의 **어디를 고쳐도** — 손대지 않은 Slot
이라도 — 모든 선택이 `REVIEW_REQUIRED` 가 된다. 이는 #719 불변식 6「깨진 결정만 다시 요구한다」와
정면으로 긴장한다. 오타 하나를 고쳐도 사용자는 전건 재선택을 요구받는다.

**v1 판정: 현재 의미를 유지한다.** 근거 셋.

1. **비대칭 위험.** 잘못된 `AUTO_KEEP` 은 사용자가 고르지 않은 문구를 법적 효력이 있는 문서에
   넣는다. 잘못된 `REVIEW_REQUIRED` 는 다시 고르게 한다. 후자는 성가시고 전자는 되돌릴 수 없다.
2. **loud 하다.** 조용히 틀리는 경로가 아니라 시끄럽게 되묻는 경로다 — 이 저장소의 핵심 계약
   (「묻고 확정하게 하거나, 시끄럽게 알린다」)의 옳은 쪽에 선다.
3. **region-local digest 는 아직 없다.** 「이 Slot 의 본문만 같은가」를 exact 하게 답하려면
   region-local content digest 가 필요하고, 그것은 SG-00 D3 이 「필요한 fact 를 exact 복원 못 하면
   REVIEW」로 닫은 자리다. 없는 fact 를 추정으로 대체하지 않는다.

**상향 조건.** 실사용에서 이 재요구가 실제 마찰로 보고되면, region-local digest 를 도입해 (b)를
Slot 범위로 좁히는 것을 별도 이슈로 연다. **S6(#807)는 이 의미를 바꾸지 않는다** — materializer 는
selection 을 재판정하지 않기 때문이다(#807 불변식 S6-1).

## 3. 짝 게이트

| 계약 | 게이트 |
|---|---|
| C1 shipping Profile count == 1 (+ bootstrap 1 · publication/revoke route 0) | `tests/repo_contract/test_control_surface_reduction.py::test_exactly_one_shipping_qualification_profile` |
| C2 Profile selector/management UI == 0 | `…::test_no_profile_management_surface` |
| C3 frontend canonical semantic import == 0 | `…::test_frontend_does_not_import_canonical_semantics` |
| C4 frontend Plan/currentness/record/delivery 재판정 == 0 | `…::test_frontend_recomputes_no_semantics` |
| C5 backend projection ↔ frontend 표시 contract parity | `tests/repo_contract/test_bridge_contract.py` (생성 계약 drift + `test_frontend_display_sources_the_generated_contract`) |
| C6 신규 ledger allowlist gate (`LEDGER_BASELINE` pin) | `…test_control_surface_reduction.py::test_no_new_durable_ledger_outside_allowlist` |
| C7 valid HMAC 만으로 authorization/currentness 우회 불가 | `tests/test_slot_configuration_product.py` C7 2건 |
| C8 cross-Work/route mismatch token 거절 | `tests/test_slot_configuration_product.py` C8 4건 |
| C9 historical Profile/Plan/Configuration evidence 의미·bytes 불변 | `tests/test_control_plane_evidence.py` + 기존 golden 재현 테스트 |

frontend import-graph 스캐너(`_frontend_sources`·`_frontend_specifiers`·`_resolve_frontend_module`)는
`tests/_web_source.py` 에 단일 출처로 산다 — C3/C4 와 `test_p3_forbidden_edges` 의 vendor 배치
게이트가 같은 진실을 읽는다.

## 4. 상향 조건

아래가 실제로 성립하면 SG-03 에서 우회하지 않고 #732 또는 #620 으로 상향한다.

```
v1 에서 복수 shipping Profile 이 실제 사용자 흐름에 필수
frontend 독립 digest 계산이 오프라인/보안 요구상 필수
일반 UI command 가 durable replay ledger 없이 실제 중복 외부효과를 일으킴
HMAC 을 실제 권한 경계로 승격해야 함
기존 store 제거/migration 없이는 단일 semantic authority 를 만들 수 없음
```

SG-03 착지 시점에는 다섯 조건 모두 성립하지 않았다(census 가 근거다).
