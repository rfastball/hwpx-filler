# 최소 UI 랩 준비 메모

이 문서는 기존 UI를 개선하는 작업이 아니라, 검증된 생성 배관 위에서 핵심 사용자
워크플로를 백지부터 비교·시연하기 위한 경계를 고정한다. 이 단계에서는 워크플로 UI를
구현하지 않는다.

## 격리

- 기준 워크트리: `hwpx-filler` / `master`
- 실험 워크트리: `hwpx-filler-ui-reboot` / `lab/ui-reboot`
- 기존 표면: `web/` — 비교 기준으로 수정하지 않는다.
- 실험 표면: `web-minimal/variants/<id>/`
- 정적 자산 선택 seam: `HWPXFILLER_WEB_DIR`

실행기는 Lab에서 `.ui-lab-home/<variant>/<scenario>/`를 사용한다. 따라서 기존 제품의
사용자 데이터 홈뿐 아니라 시안·시나리오 조합끼리도 상태가 섞이지 않는다.

## Git 구조

- `lab/ui-reboot`는 이 워크트리에 고정하는 장기 실험 브랜치다.
- 동시에 비교할 시안은 브랜치가 아니라 `web-minimal/variants/<id>/`로 공존시킨다.
- 공통 부팅·브리지·토큰은 `web-minimal/shared/`에 한 벌만 둔다.
- 시안 하나는 가능한 한 독립된 한 커밋으로 추가한다.
- 비교 라운드는 `ui-lab/rN` 태그와 `docs/ui-lab/round-NN.md` 기록으로 닫는다.
- 병렬 구현이 필요할 때만 `exp/ui-rNN-<id>` 임시 브랜치·워크트리를 만들고, 결과는
  해당 시안 디렉터리로 `lab/ui-reboot`에 합친다.
- 선정 시안은 이 브랜치를 제품 브랜치에 통째로 병합하지 않는다. `master`에서
  `feat/ui-reboot-v1`을 새로 만들어 필요한 공통 배관과 선정 시안만 의도적으로 옮긴다.

```text
web-minimal/
├─ shared/
├─ variants/
│  └─ blank/
├─ scenarios/
└─ variants.json
```

## 재사용할 배관

### 공통 왕복

- `initial(screen)`: 화면별 초기 스냅샷
- `dispatch(screen, action, payload)`: 검증된 액션 호출
- `window.__push(screen, snapshot)`: Python에서 브라우저로 상태 푸시

액션 payload는 `src/hwpxfiller/webapp/action_registry.py`가 검증한다. 새 UI가 백엔드
상태를 다시 계산하지 않고 스냅샷을 그리기만 하는 경계를 유지한다.

### 템플릿·매핑·작업 저장 (`editor`)

- 템플릿: `use_library_template`, `import_template_file("editor")`, `ack_gate`
- 단계: `goto_step`
- 데이터: `pick_data_file("editor")`, `load_data_sheet("editor", ...)`
- 매핑: `set_source`, `set_type`, `set_fmt`, `set_const`, `set_confirmed`
- 일괄 확인: `confirm_all`, `confirm_blanks`
- 저장 정보: `set_name`, `set_pattern`, `set_dataset_name`
- 저장: `save`

`editor` 스냅샷은 템플릿 필드, 데이터 헤더·표본, 매핑 행, 완료 여부, 저장 게이트를
제공한다. 자동 제안은 백엔드 소유이며, UI는 사용자의 확정만 수집한다.

### 실행·검증·생성 (`job`)

- 저장 작업 선택: `select_job`
- 데이터: `pick_data_file("job")`, `load_data_sheet("job", ...)`
- 출력 폴더: `pick_output_folder("job")`
- 빈 값 확인: `ack_field`, `unack_field`
- 생성: `generate("job", confirmOverwrite)`
- 중단: `cancel_generation`

`job` 스냅샷의 `gate`가 생성 가능 여부의 단일 출처다. `mirror`, `drift`,
`name_tokens`, `restate`도 백엔드가 계산한다. 새 UI에서 이 판단을 복제하지 않는다.

### 네이티브·수명주기

- 다중 시트 선택은 `pick_data_file`의 `needs_sheet` 반환을 반드시 확정한다.
- 덮어쓰기와 빈 값은 기존 confirm-or-alarm 왕복을 유지한다.
- 종료 시 `AppCloseGuard.prompt(state)`를 제공해야 한다.
- 부팅 시 `Theme`과 `Personalization` 전역 훅을 제공해야 현재 창 표시 과정이 완료된다.

## 최초 비교 대상

첫 UI 시연은 아래 한 경로만 다룬다.

`템플릿 선택 → 데이터 선택 → 매핑 확인 → 작업 저장 → 결과 확인 → 생성`

작업 목록 관리, 홈, 기안, 템플릿 관리, 데이터 관리, 그룹·태그·개인화는 첫 비교 대상에서
제외한다. 기능을 없앴다고 간주하지 않고, 핵심 흐름의 형태가 정해질 때까지 표면에 올리지 않는다.

## 구현 시작 전 게이트

- 기존 `web/`은 수정되지 않는다.
- `blank` 기준 시안은 백엔드 메서드를 호출하지 않는다.
- 기존 표면과 임의의 Lab 시안을 별도 명령으로 실행할 수 있다.
- 새 UI의 상태 판단은 `editor`/`job` 스냅샷을 소비하며 재구현하지 않는다.
- 핵심 흐름의 화면 수·단계 수를 먼저 비교한 뒤 구현한다.

## 실행

```powershell
.\run-ui-surface.ps1 -Surface Lab -Variant blank -Scenario blank
.\run-ui-surface.ps1 -Surface Legacy

# 창을 띄우지 않고 manifest·시나리오·index 경로만 검사
.\run-ui-surface.ps1 -Surface Lab -Variant blank -Scenario blank -ValidateOnly
```
