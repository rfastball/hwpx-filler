# 테스트 포트폴리오 전수조사 — #168

> 기준: `8cace7a2648e602cd3e770902a74af1b2f288fe6` (`origin/master`, 2026-07-22).
> 기계 판독 원장은 [`test_portfolio_inventory.csv`](test_portfolio_inventory.csv), 생성 집계는
> [`TEST_PORTFOLIO_MATRIX.md`](TEST_PORTFOLIO_MATRIX.md)에 있다.
> 조사 브랜치를 최신 master에 재배치한 뒤 전체 게이트와 coverage 원장을 다시 수집했다.

## 결론

- 기존 제품 테스트 **1,590개**가 모두 통과했다. 조사 도구 자체 테스트 5개를 더한 최종 원장은
  **90파일·1,595 pytest 사례·1,553 실행 단위·4,360 assert 단언**을 포함한다.
- 전체 Python coverage는 **line 90.58%(8,387/9,259), branch 86.06%(2,396/2,784)**다.
  총계는 높지만 `hwpxcore.native`는 line 40.33%/branch 32.50%이고 JS/CSS, frozen subprocess,
  설치·서명은 이 백분율 밖이다. 단일 `fail_under`는 위험 지도를 왜곡한다.
- filler WebView2 게이트는 **41 pytest 사례 / 3 시나리오 / 실제 창 4회**다. 그중 클래스
  39개는 하나의 module-scope 프로브 결과를 공유하므로 39개의 독립 E2E가 아니다.
- diff는 headless frozen self-check는 있으나 **실제 WebView2 창 실행이 0회**다.
- pytest 안에는 `distribution` 계층 사례가 없다. 배포 계약은 외부 스크립트와 release workflow가
  소유한다. portable GUI 2종 빌드·self-check는 **22.99초**, 별도 CLI 번들은 **9.09초**로 통과했다.
- 정적 유사성만으로 삭제할 테스트는 확정하지 않았다. 동일 코퍼스 양성대조 한 쌍만
  `merge-candidate`로 기록했고, 실제 삭제는 대체 owner 확인 뒤 수행한다.

## 조사 방법과 분류

`pytest --cov-context=test`의 JUnit·coverage context, 테스트 AST, source/fixture 정적 검토를 결합했다.
파라미터 사례는 각 nodeid로 펼치되 파일→클래스→테스트 오버라이드를 상속한다. 분류는
`unit`, `contract`, `integration`, `ui-runtime`, `distribution` 중 하나이며 `regression`은 계층으로
사용하지 않는다. 위험 표면은 다음 10개 복수 태그다.

1. `document-package-integrity`
2. `extract-fill-transform`
3. `diff-correctness`
4. `mapping-validation-drift`
5. `durable-registry-persistence`
6. `data-ingestion-boundaries`
7. `application-workflows`
8. `web-runtime-bridge`
9. `native-packaging-release`
10. `architecture-design-system`

테스트별 Python 실행 모듈이 비어 있는 181개 사례는 정적 source 검사, subprocess/실창, 또는
Python production line을 직접 통과하지 않는 계약이다. 이를 미실행으로 오인하지 않고 검증 방식과
플랫폼으로 별도 기록했다. WebView2 subprocess는 pytest process coverage에 합산되지 않는다.

## 위험 표면별 소유권과 공백

| 위험 표면 | 대표 소유 테스트 | 알려진 공백·후속 작업 |
|---|---|---|
| 패키지 보존·원자 쓰기 | `test_atomic.py` 실패 보존, `test_extract_invariants.py::test_container_round_trip` | 적대 ZIP/OCF 입력 [#185](https://github.com/rfastball/hwpx-filler/issues/185), header/footer 왕복 [#186](https://github.com/rfastball/hwpx-filler/issues/186) |
| 추출↔채움·변형 | `test_fields.py`, `test_authoring.py` compile→fill, `test_engine.py` 재생성 안정성 | header/footer의 동명 필드·순서·diff [#186](https://github.com/rfastball/hwpx-filler/issues/186) |
| diff 정확성 | 합성 변화 `test_diff_synthetic.py`, 실제 골든 `test_diff_golden.py`, 재번호 `test_diff_renumber.py` | 병합/중첩 표·반복/이동 pairing [#187](https://github.com/rfastball/hwpx-filler/issues/187), diff 실창 [#188](https://github.com/rfastball/hwpx-filler/issues/188) |
| 매핑·검증·드리프트 | `test_mapping.py`, `test_mapping_state.py`, `test_run_state.py`, `test_batch_gate.py` | core formatter·state preview·surface gate의 상관을 분리 유지; 중복 삭제 전 owner 양성대조 필요 |
| 내구 레지스트리 | `test_job.py` 직렬화·lock, `test_dataset_pool.py`, `test_template_groups.py` | DatasetPool 원자성·경합 [#182](https://github.com/rfastball/hwpx-filler/issues/182), Job process 경계 [#192](https://github.com/rfastball/hwpx-filler/issues/192) |
| 데이터 경계 | `test_data_factory.py`, `test_nara.py`, `test_pipeline.py`, `test_scenario_e2e.py` | Excel 행 성형 [#183](https://github.com/rfastball/hwpx-filler/issues/183), Nara pagination/schema [#193](https://github.com/rfastball/hwpx-filler/issues/193) |
| 앱 상태·컨트롤러 | ring-1 state suites와 `test_webapp_{editor,job,draft,pool}.py` | 정적 action literal scan의 false-pass [#189](https://github.com/rfastball/hwpx-filler/issues/189) |
| Web runtime·bridge | `test_web_dom_contract.py`, `test_webapp_bridge.py`, filler `test_web_selftest_gate.py` | diff 실창 [#188](https://github.com/rfastball/hwpx-filler/issues/188), click→dispatch runtime [#189](https://github.com/rfastball/hwpx-filler/issues/189) |
| Native·배포 | `test_single_instance.py`, `test_motw.py`, `verify_specs.py`, frozen self-check, release install/uninstall | native 양성 경로 [#190](https://github.com/rfastball/hwpx-filler/issues/190), PR distribution gate [#191](https://github.com/rfastball/hwpx-filler/issues/191) |
| 아키텍처·디자인 | `test_architecture.py`, `test_design_tokens.py`, WCAG·UX·DOM 정적 계약 | 동일 JS source를 읽는 43개 사례를 `web-static-source` 상관 그룹으로 관리 |

## 중복과 상관 관계

| 그룹 | 판정 |
|---|---|
| `webview:selftest-main` | 39 사례가 filler 창 1회와 결과 JSON 하나를 공유한다. 계약 단언은 가치 있지만 독립 E2E 수에는 1로 센다. |
| `diff-renumber-real-pair` | 5 사례가 module-scope diff 결과 하나를 공유한다. 실행 단위 1, 단언 5로 센다. |
| `real-hwpx-corpus` | 61 사례가 실제 HWPX 6개에 의존한다. 코퍼스 기대치 결함 시 동시 false-pass/failure가 가능하다. |
| `web-static-source` | DOM/data-zone/R3 43 사례가 같은 JS source 구조를 정적으로 검사한다. runtime 보강이 없으면 독립 동작 증거가 아니다. |
| `mapping-format`, `multisheet-gate`, `nara-auth`, `pool-reregister`, `job-write-lock` | core/state/controller/CLI의 계층 보강이다. 외부 계층이 자기 surface의 상태·exit·문구를 단언하면 유지하고 동일 예외값만 재단언하면 병합 후보로 본다. |
| corpus 양성대조 | `test_extract_invariants.py::test_corpus_not_empty`를 owner로 두고 `test_diff_invariants.py::test_corpus_not_empty`를 유일한 확정 `merge-candidate`로 기록했다. 삭제는 후속 정리에서 수행한다. |

## 플랫폼과 배포 게이트

| 실행 위치 | 검증 | 측정/상태 |
|---|---|---|
| pytest Windows | ruff·pyright·1,595 사례·branch coverage | 1,595 passed, 63.59초 wall time |
| filler WebView2 | DOM/render/focus/scroll/theme/boot | 41 cases, 3 scenarios, 4 window launches |
| portable GUI build | spec→metadata→PyInstaller→bundle boundary→frozen self-check | filler+diff 통과, 22.99초 |
| portable CLI build | PyInstaller→schema/fieldize/lint/drift commands | 통과, 9.09초 |
| release workflow | optional signing, Inno build, install→self-check→uninstall, ZIP/checksum | 정의는 확인; 이번 조사에서는 인증서·release tag·Inno 조건 때문에 미실행 |
| diff WebView2 | 실제 창·브리지·결과 렌더 | 호출자 없음, 0회 — #188 |

## Coverage와 CI 권고

즉시 전체 `fail_under=90`을 넣지 않는다. 현재 수치를 내림한 package별 초기 floor를 #191에서
XML 판정기로 도입한다. line/branch 제안은 `hwpxcore` 95/87, `hwpxdiff` 96/90,
`hwpxdiff.webapp` 67/56, `hwpxfiller` 77/67, `hwpxfiller.core` 97/93,
`hwpxfiller.data` 96/88, `hwpxfiller.gui` 96/89, `hwpxfiller.webapp` 86/82다.

`hwpxcore.native`의 40/32를 낮은 floor로 정당화하지 않는다. #190의 Windows 양성 시나리오를
먼저 만들고 별도 필수 상태로 보고한다. JS/CSS 33개 자산, WebView2 subprocess, frozen bundle,
installer/signing은 Python coverage 분모에 넣지 않는다. PR/push에는 package coverage와 portable
3타깃 self-check를 별도 job으로 추가하고, installer/signing은 release 또는 required pre-release에 둔다.

## 후속 이슈

- [#182 DatasetPool 원자성·동시 쓰기](https://github.com/rfastball/hwpx-filler/issues/182)
- [#183 Excel/CSV 행 성형](https://github.com/rfastball/hwpx-filler/issues/183)
- [#185 HWPX OCF 적대 입력](https://github.com/rfastball/hwpx-filler/issues/185)
- [#186 header/footer 왕복](https://github.com/rfastball/hwpx-filler/issues/186)
- [#187 복합 구조 diff pairing](https://github.com/rfastball/hwpx-filler/issues/187)
- [#188 hwpxdiff WebView2 실창](https://github.com/rfastball/hwpx-filler/issues/188)
- [#189 action registry와 runtime dispatch](https://github.com/rfastball/hwpx-filler/issues/189)
- [#190 Windows native 양성 경로](https://github.com/rfastball/hwpx-filler/issues/190)
- [#191 package coverage·distribution CI](https://github.com/rfastball/hwpx-filler/issues/191)
- [#192 JobRegistry process 경계](https://github.com/rfastball/hwpx-filler/issues/192)
- [#193 Nara pagination·schema](https://github.com/rfastball/hwpx-filler/issues/193)

## 재생성과 완료 확인

```powershell
# test.ps1과 동등한 pytest 실행에 --cov-context=test를 추가해 JUnit/.coverage 생성
python -m coverage json --show-contexts -o build/test-portfolio/coverage-contexts.json
python scripts/audit_test_portfolio.py collect `
  --junit build/test-portfolio/pytest.xml `
  --coverage-contexts build/test-portfolio/coverage-contexts.json `
  --classification docs/test_portfolio_classification.toml `
  --repo-root . --output docs/test_portfolio_inventory.csv
python scripts/audit_test_portfolio.py validate docs/test_portfolio_inventory.csv `
  --junit build/test-portfolio/pytest.xml
python scripts/audit_test_portfolio.py render docs/test_portfolio_inventory.csv `
  --metadata docs/test_portfolio_metadata.json `
  --output docs/TEST_PORTFOLIO_MATRIX.md
```

- [x] 수집된 모든 pytest 사례가 계층·플랫폼·위험 표면에 귀속됨
- [x] WebView2 사례/시나리오/창 실행 수가 분리됨
- [x] JS/CSS·native·packaging·installer/release가 별도 지도에 포함됨
- [x] 핵심 위험 표면마다 대표 owner와 공백이 기록됨
- [x] 중복 후보는 owner·상관 관계를 먼저 기록하고 삭제하지 않음
- [x] 검증된 공백을 작은 후속 이슈로 분리함
