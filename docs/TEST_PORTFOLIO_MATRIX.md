# 테스트 포트폴리오 생성 매트릭스

> `scripts/audit_test_portfolio.py render`로 재생성한다. 수치는 위험 태그별 중복 집계를 허용한다.

- 기준 SHA: `8cace7a2648e602cd3e770902a74af1b2f288fe6`
- 수집 사례: **1595**
- 독립 실행 단위: **1553**
- 계약 단언: **4360**
- 합산 실행시간: **59.81s**

## 위험 표면 요약

| 위험 표면 | 사례 | 실행 단위 | 단언 | 시간(s) |
|---|---:|---:|---:|---:|
| `application-workflows` | 986 | 948 | 2778 | 50.80 |
| `architecture-design-system` | 103 | 103 | 245 | 1.66 |
| `data-ingestion-boundaries` | 447 | 447 | 1268 | 12.30 |
| `diff-correctness` | 84 | 80 | 220 | 1.84 |
| `document-package-integrity` | 113 | 113 | 281 | 1.67 |
| `durable-registry-persistence` | 427 | 427 | 1122 | 9.74 |
| `extract-fill-transform` | 370 | 370 | 1013 | 6.75 |
| `mapping-validation-drift` | 674 | 674 | 2000 | 16.94 |
| `native-packaging-release` | 12 | 12 | 19 | 0.10 |
| `web-runtime-bridge` | 156 | 118 | 510 | 33.22 |

## 계층 요약

| 계층 | 사례 | 실행 단위 |
|---|---:|---:|
| `contract` | 931 | 927 |
| `distribution` | 0 | 0 |
| `integration` | 290 | 290 |
| `ui-runtime` | 41 | 3 |
| `unit` | 333 | 333 |

## 계층 × 플랫폼

| 계층 | 플랫폼 | 사례 | 실행 단위 |
|---|---|---:|---:|
| `contract` | `cross-platform` | 926 | 922 |
| `contract` | `windows` | 5 | 5 |
| `integration` | `cross-platform` | 281 | 281 |
| `integration` | `windows` | 9 | 9 |
| `ui-runtime` | `windows-desktop-webview2` | 41 | 3 |
| `unit` | `cross-platform` | 333 | 333 |

## 상관 그룹

| 그룹 | 사례 | 실행 단위 |
|---|---:|---:|
| `diff-renumber-real-pair` | 5 | 1 |
| `job-write-lock` | 3 | 3 |
| `mapping-format` | 2 | 2 |
| `multisheet-gate` | 4 | 4 |
| `nara-auth` | 3 | 3 |
| `pool-reregister` | 2 | 2 |
| `real-hwpx-corpus` | 61 | 61 |
| `web-static-source` | 43 | 43 |
| `webview-selftest` | 2 | 2 |
| `webview:selftest-main` | 39 | 1 |

## 최장 실행 사례

| nodeid | 시간(s) |
|---|---:|
| `tests/test_web_selftest_gate.py::test_theme_choice_persists_across_restart_without_flicker` | 11.701 |
| `tests/test_web_selftest_gate.py::test_completed_boot_stamps_the_home_and_narrows_the_budget` | 9.508 |
| `tests/test_web_selftest_gate.py::TestWebSelftestGate::test_no_probe_error` | 9.363 |
| `tests/test_webapp_settings.py::test_save_theme_propagates_unreadable_file` | 0.519 |
| `tests/test_webapp_bridge.py::test_importing_webapp_screens_loads_no_qt` | 0.368 |
| `tests/test_architecture.py::test_src_has_no_pyside6_runtime_imports` | 0.261 |
| `tests/test_webapp_job.py::test_public_delete_during_stamp_does_not_resurrect_the_job` | 0.238 |
| `tests/test_job.py::test_write_lock_serializes_read_modify_write` | 0.227 |
| `tests/test_architecture.py::test_products_do_not_import_each_other` | 0.220 |
| `tests/test_ux_copy_round.py::test_backend_user_strings_free_of_banned_vocabulary` | 0.175 |
| `tests/test_cli.py::test_ledger_rerun_accumulates_evidence` | 0.134 |
| `tests/test_cli.py::test_ledger_is_optin_and_writes_evidence_sidecar` | 0.126 |
| `tests/test_webapp_editor.py::test_overwrite_confirm_reasks_when_the_situation_changed_under_the_modal` | 0.124 |
| `tests/test_webapp_editor.py::test_overwrite_confirm_requires_the_text_the_user_actually_read` | 0.121 |
| `tests/test_cli.py::test_nara_source_with_profile_fills_template` | 0.117 |
| `tests/test_webapp_editor.py::test_default_dataset_dead_corrupt_missing_are_restated` | 0.115 |
| `tests/test_webapp_editor.py::test_slug_collision_different_name_restates_victim_then_saves` | 0.112 |
| `tests/test_diff_invariants.py::test_deterministic_to_dict[spec_revision_2025.hwpx]` | 0.110 |
| `tests/test_webapp_editor.py::test_edit_save_preserves_authored_at_updates_updated_at` | 0.104 |
| `tests/test_cli.py::test_cli_overwrite_optin_passes` | 0.103 |
