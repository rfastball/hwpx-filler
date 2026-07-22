# 앱 시각 디자인 언어 결정 기록 (2026-07-17)

> **문서 상태:** 유효 결정
> **권위 범위:** 제품의 시각 문법과 채택·기각 근거
> **후속 정본:** 실제 값과 렌더 표면은 `UI_GALLERY.html`·`web/css/`·디자인 토큰
> **편집 정책:** 결정 변경 시만 갱신

이 문서는 hwpx-filler가 **어떤 앱 디자인 언어를 의도적으로 택할 것인가**의 결정을
닫는다. [UI_DESIGN_DECISIONS.md](UI_DESIGN_DECISIONS.md)가 *상호작용 표면*(function→UX→UI)의
ADR이라면, 이 문서는 그 위에 입히는 *시각 문법*(색·타이포·여백·깊이·내비 형태)의 결정 기록이다.
[UI_GALLERY.html](UI_GALLERY.html)이 실 CSS를 링크한 드리프트-0 **라이브** 갤러리라면, 이
문서에 딸린 목업 HTML은 결정 시점의 **동결 제안**(토큰 인라인)이다 — 착지되면 진실의 원천은
다시 갤러리로 돌아온다.

## 배경 — 왜 이 결정이 나왔나 (스코프 오류 방지)

직전 라운드는 **KRDS(정부 웹 디자인시스템) 차용**을 검토했으나 기각으로 수렴했다
(`docs/KRDS_ADOPTION.md`, `feat/krds-color-adoption` 브랜치). 결론: KRDS는 **"웹 페이지" 문법**
(정부24식 콘텐츠 페이지·GNB/LNB·조회→결과)이고, 우리는 **"앱" 문법**(레일 내비·데이터 그리드·
매핑표·마법사·라이브 로그 콘솔·다중 패널 = VS Code/관리 콘솔 계열)이다 — 목적 함수 불일치.
KRDS를 두 층으로 갈랐을 때 토큰(색)은 이식 가능하나 레이아웃 문법은 카테고리 오류였고,
"색만" 따오면 진짜 정부-네이티브 신호(화면 *모양*)는 못 얹으므로 가치가 미미했다.

따라서 진짜 질문은 "KRDS냐"가 아니라 **"이 앱이 어떤 디자인 언어를 의도적으로 택할 것인가"**로
재설정됐다. 현행은 "범용 SaaS 어드민 방언" — 못난 건 아니나 **의도 없이 표류**한 상태였다.

## 방법 — 딥리서치 (2026-07-17)

6개 검색 각도로 팬아웃 → 24개 소스 페치 → 110개 falsifiable 주장 추출 → **25개를 3표 적대
검증**(2/3 반증 시 기각) → 종합. 22 확정·3 반증·0 미검증. 스코프: **데스크톱/생산성 "앱"
디자인 언어**만(웹 콘텐츠 사이트 디자인시스템 ❌ — KRDS 함정 재발 방지), **토큰·레이아웃 원리만**
(React/Vue 구현체 ❌ — 우리는 순수 HTML/CSS).

## 결론 — 세 후보, 하나의 DNA

조사한 후보(Linear·VS Code·Fluent 2·Primer·Geist·shadcn 등)가 **한 방향으로 수렴**했다:
quiet-UI 밀도 철학 · 무채색 베이스 + 단일 절제 액센트 · 그림자가 아닌 **1px 헤어라인 + surface
사다리**로 깊이 · 기계검증 WCAG AA를 붙인 단일출처 시맨틱 토큰 · **아이콘 우선(2줄 아님)** 레일.
세 후보는 경쟁이 아니라 **역할이 다르다** — 미감·거버넌스·부품 형태의 세 층.

| 후보 | 역할 | 우리에게 주는 것 | 비용 | 근거 강도 |
|------|------|------------------|------|-----------|
| **A. Linear** | 미감·태도 | 조용함·색 절제·보더>섀도·surface 사다리 (정체성 매치) | LOW~MED | 정체성=1차(high), 정확 토큰값=2차 CSS추출(med) |
| **B. Fluent 2 / Primer** | 거버넌스·감사 | 2층 토큰(global→alias)·fg/bg AA쌍 강제 — **우리가 이미 하는 것의 성문화** | LOW | 3-0 (Primer 가이드는 AI 저작 프롬프트라 "거버넌스" 라벨은 해석적, 실체는 진짜) |
| **C. VS Code / shadcn** | 부품 형태 | 레일=아이콘 글리프·3존(헤더/콘텐츠/푸터)·`data-[active]` 활성 (구조 원리만, 코드 아님) | LOW | 3-0 |

**택일.** **Linear를 주 정체성**(톤·색 절제·깊이)으로 채택 + **Primer/Fluent 토큰 거버넌스**는
이미 대부분 보유(validate-what-exists, 저비용) + **VS Code/shadcn 구조 문법**으로 레일 수선.

**결정 프레임.** 차별적·조용한·키보드 우선 제품 정체성이 우선 → Linear 주도. 토큰의 감사가능성·
거버넌스가 우선 → Primer/Fluent 주도. **레일 형태 질문은 어느 쪽이 주도하든 VS Code/shadcn이 답.**

**Geist 탈락(근거).** "APP 청중용" 주장이 검증에서 **0-3 반증**, React 결합=결격 주장은 1-2 미확정.
Linear 대비 검증된 추가가치가 없어 별개 방향에서 제외 — 추측으로 포함하지 않음.

## 액센트 색조 결정 — 정제 로열블루 `#2f5fbf` (2026-07-17 사용자 확정)

리서치 결론: 증거가 지지하는 건 **"액센트를 아껴 쓰는 규율"**이지 특정 색조가 아니다. 즉 색조는
순수 브랜드 선택. 세 후보를 같은 컴포넌트에 입혀 눈으로 비교했다:

| 후보 | 값 | 흰 배경 대비 | 판정 |
|------|-----|-------------|------|
| A 현행 청록블루 | `#2874a6` | ≈4.7:1 | 위험0·검증됨, 그러나 "표류"의 그 색 |
| **B 정제 로열블루** | **`#2f5fbf`** | **≈5.3:1** | **채택** — 기관 진중함 유지 + 표류 탈출 + 라벤더 리스크 회피 |
| C Linear 라벤더 | `#5e6ad2` | ≈5.9:1 | 미감 최상이나 정부 조달엔 소비자 SaaS처럼 가벼울 위험 |

셋 다 WCAG AA 통과(다크 변형은 밝기를 올려 대비 확보). **B 확정.**

- 라이트: `accent #2f5fbf` / `accent_hover #274fa0` / `accent_tint #dfe6fb` / `accent_ink #274fa0`
- 다크: `accent #6f97e8` / `accent_hover #8badf0` / `accent_tint #1e2846` / `accent_ink #8badf0`(=hover 겸용)
  - 다크 `accent_tint` 는 갤러리(`docs/UI_GALLERY.html`) 다크 눈검증에서 **불투명 남색 `#1e2846`** 으로
    튜닝됐다(초기 스펙 `rgba(111,151,232,.16)` 반투명에서 개정 — #131). 라이트 `accent_tint #dfe6fb` 도
    불투명이라 두 모드가 일관된다. `accent_ink` 는 라이트(`#274fa0`)·다크(`#8badf0`) 모두 `accent_hover`
    로 겸용 — 별도 토큰을 두지 않는다.
- **상태색(미확인 `#fff3bf`·미매칭 `#ffd8d8`·빈칸 `#b00020`)은 액센트와 분리 유지** — 값 상태는
  상태색, 액센트는 동작·활성·포커스에만. confirm-or-alarm과 Linear/Fluent 정석의 합류점.

## 제약 통과 — 오프라인·한글

- **폰트 = Pretendard.** SIL OFL이라 소프트웨어 동봉/임베드 적법(단독 판매만 금지) → 단일 exe 가능.
  Inter(라틴) + Source Han Sans(한글) 융합 설계라 **라틴 우선 미감이 한글에서 안 깨진다.**
- **폴백 = Malgun Gothic.** Windows Vista~11 전부 기본 탑재 → 오프라인 한글 폴백 보장.
- **반증됨:** Malgun Gothic이 라틴을 안정적으로 커버한다는 주장은 1-2 반증 → 라틴+한글 담체는
  **Pretendard**, Malgun은 한글 전용 폴백.

## 레일 내비 진단·처방

**진단.** 각 항목이 2줄(굵은 제목 + 회색 부제) + 채운-블록 활성 + 대문자 섹션 라벨의 누적 =
사용자 관찰 "흩어짐". NN/g: "모든 잉여 정보 단위는 관련 단위와 경쟁해 그 가시성을 깎는다."
다만 밀도 자체는 위반이 아니고(NN/g 16Personalities 예), 부제는 "메뉴명이 자명치 않아서"
있으므로 **무작정 제거 = 정보 손실** — 유지/강등 판단 문제(confirm-or-alarm과 정합).

**처방(VS Code/shadcn).** ① 선행 아이콘 추가 → 아이콘+이름이 자명 → 부제는 **호버 툴팁** 또는
비자명 항목만 캡션(손실0). ② 활성 = 채운블록 → **은은한 틴트 + 좌측 3px 액센트 막대**(`data-[active]`
구동). ③ 항목을 섹션 그룹 + **3존(헤더/콘텐츠/푸터)** 으로 → 평면 나열의 흩어짐 해소.

## 현행 대비 — 유지 / 변경

- **유지(이미 정답):** 단일출처 시맨틱 토큰 파이프라인 · 기계검증 WCAG AA · 상태 틴트를 액센트와
  분리 · radius 스케일(4/6/9/12/pill) · 밀도 자체.
- **변경:** 레일 2줄→아이콘+단일라벨 · 활성 채운블록→틴트+막대 · 깊이 그림자→헤어라인+surface
  사다리 · 액센트 장식 사용 제거(의미 자리에만) · 부제 툴팁/캡션 강등.

## 제목 타이포 역할 계약 (H-01)

제목은 컴포넌트마다 크기를 고르지 않고 아래 세 역할만 소비한다. 크기보다 역할과 굵기의
일관성을 우선하며, 새 제목도 가장 가까운 역할에 합류시킨다.

| 역할 | 토큰 · 굵기 | 소비 선택자 |
|------|-------------|-------------|
| 화면 제목 | `--fs-section` (19px) · 700 | `.scr-head h1` |
| 구획 제목 | `--fs-strong` (15px) · 700 | `.track .tt`, `.job-sec-head`, `.tpl-band .tb-t`, `.modal-card h3` |
| 존·소제목 | `--fs-dense` (13px) · 700 | `.zone-cap`, `.pane h4`, `.qd-formpane h4`, `.qd-prevpane h4` |

개별 선택자는 여백·색·배치만 소유한다. 특히 존 제목을 본문(`--fs-body`, 14px)보다 작게
두더라도 700 굵기와 `--n-header-ink`를 함께 써 캡션처럼 약해지지 않게 한다. 작업 단계(H-03)와
템플릿 매체 구획(H-04)은 각각 존·소제목과 구획 제목 역할을 그대로 소비한다.

## KRDS 색 브랜치(`feat/krds-color-adoption`) 처분 — 폐기 방향

이 리서치는 "정부색 스왑"이 아니라 **"현행 블루 유지 + Linear식 절제 규율"**을 지지한다. 진짜
정부-네이티브 신호는 색이 아니라 레이아웃 문법이었고(그건 위 레일·화면 처방으로 답이 나왔다),
색조는 로열블루로 독립 결정됐다. 따라서 KRDS 색 스왑 브랜치는 **폐기 수렴** — worktree 정리
대상. (KRDS 조사 자체의 산출물 `docs/KRDS_ADOPTION.md`는 그 브랜치에 보존.)

## 대기 이슈와 합류 (#58/#59/#60)

- **#58 타이포 위계** — Linear/Inter 계열은 크기 대비보다 **웨이트·색(ink/muted) 대비**로 위계.
  현행 8단(10~23px) 유지, 굵기·색 위계 강화 검토.
- **#59 radius 역할** — Linear 카드 12px + 헤어라인 → **카드=12·컨트롤=6** 역할 분리로.
- **#60 여백 리듬** — 밀도 유지 정당(NN/g). 여백은 조이는 방향, surface 사다리로 위계 보강.

## 열린 질문 (미확정 — 추측 안 함)

1. ~~Segoe/Malgun 스택 → 동봉 Pretendard GOV 이관~~ — **착지(#179 슬라이스 2)**. 가변 woff2 한
   파일(`web/fonts/PretendardGOVVariable.woff2`, ~5.15 MB, SIL OFL 1.1)로 100~900 전 웨이트 동봉,
   `web/css/app.css` `@font-face` + 스택 선두(`"Pretendard GOV Variable",…` , Malgun=한글 폴백).
   정적 2개 합성으로는 앱이 쓰는 400·500·600·700·800 굵기 위계가 뭉개져 가변 단일 파일 채택.
   exe 크기 비용 = **+~5.15 MB**(전 웨이트 가변; PyInstaller `web/` 트리 datas 로 자동 동봉).
   범위는 파일러 앱(`web/`)만 — diff 뷰어(web-diff)는 별도 제품이라 현행 스택 유지.
2. WebView2/Chromium 래스터라이저의 Pretendard **소자간 힌팅**이 10~13px 한글 밀집에서 native
   ClearType Malgun과 차이 나는지 미확인(글리프 메트릭은 동일). ← 착지 후 실앱 눈검증으로 좁힌다.
3. 레일 부제 강등의 실앱 최적형(호버 툴팁 전부 vs 비자명 항목만 캡션)은 within-app 실측 없음 — 원리만.

## 착지 경로

인프라상 채택 = **`src/hwpxfiller/gui/design_tokens.json` 편집 + `scripts/gen_design_tokens.py`
재생성 + `web/css` 조정 → `docs/UI_GALLERY.html` 라이트/다크 눈검증 + WCAG 대비 테스트**. 권장
순서: ① 로열블루 색 착지(저위험) → ② 레일 내비 개선 → ③ #58/#59/#60 합류.

## 목업 (결정 시점 동결 제안 — 라이브 아님)

토큰 인라인 독립 HTML. 착지 후 진실의 원천은 [UI_GALLERY.html](UI_GALLERY.html)로 복귀.

- [design_language_rail.html](design_language_rail.html) — 레일 내비 현행↔개선 + 활성표시·깊이·액센트 절제 라이브 데모
- [design_language_hue.html](design_language_hue.html) — 액센트 3후보(A 청록·B 로열·C 라벤더) 비교
- [design_language_screens.html](design_language_screens.html) — 로열블루로 그린 5화면(홈·매핑표·그리드·마법사·모달)

## 출처

- Linear 리디자인 — https://linear.app/now/how-we-redesigned-the-linear-ui
- Linear DESIGN.md (2차 CSS추출) — https://github.com/voltagent/awesome-design-md/blob/main/design-md/linear.app/DESIGN.md
- Fluent 2 토큰 — https://fluent2.microsoft.design/design-tokens
- Primer 토큰 가이드 — https://github.com/primer/primitives/blob/main/DESIGN_TOKENS_GUIDE.md
- Primer 색 사용 — https://primer.style/product/getting-started/foundations/color-usage/
- VS Code Activity Bar — https://code.visualstudio.com/api/ux-guidelines/activity-bar
- shadcn Sidebar — https://ui.shadcn.com/docs/components/radix/sidebar
- NN/g 미니멀리즘 — https://www.nngroup.com/articles/aesthetic-minimalist-design/
- Pretendard — https://github.com/orioncactus/pretendard/blob/main/packages/pretendard/docs/en/README.md
- Pretendard (Adobe Fonts) — https://fonts.adobe.com/fonts/pretendard
- Malgun Gothic (MS Learn) — https://learn.microsoft.com/en-us/typography/font-list/malgun-gothic
