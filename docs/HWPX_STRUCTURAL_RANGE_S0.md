# HWPX structural range S0 관찰 기록

> **문서 상태:** 유효 결정
> **권위 범위:** structural range 설계 전 format-kernel 관찰, corpus 증거와 미해결 질문
> **후속 정본:** production 동작·지원 범위는 `src/hwpxcore/bookmark_region.py`, 회귀 oracle은
> `tests/test_bookmark_regions.py`; native evidence와 Q1~Q7 판정은 이 문서
> **편집 정책:** 새 native evidence가 생길 때만 판정과 근거를 함께 갱신

## 1. 범위와 방법

S0 관찰 단계에서는 Slot 기능이나 structural range production API를 만들지 않았다. 저장소 HEAD
`207fb3ceec6638ede575ee33ff9d596dda327e0b`에서 다음만 수행했다.

- `src/hwpxcore/`의 OCF package, XML parsing, section ordering, deterministic serialization 확인
- 기존 `FieldDocument._field_span()`의 실제 걸음 범위 확인
- Git이 추적하는 `tests/corpus/**`의 모든 HWPX 내부 XML과 fragment XML 검색
- 한컴 공식 [OWPML 공개 안내](https://license.hancom.com/support/downloadCenter/hwpOwpml)와
  [OWPML filter model](https://github.com/hancom-io/hwpx-owpml-model) 대조
- 합성 HWPX로 observer 자체만 검증
- 한글이 저장한 R0~R4와 T0~T7 실물로 point/block bookmark 표현, 편집 내구성,
  table/container 횡단 대조

한컴 프로그램, COM, synthetic native-semantics 추론은 사용하지 않았다.

## 2. 기존 kernel과 Field 형상

### hwpxcore

- `HwpxPackage.from_bytes()`는 ZIP 엔트리를 메모리에 순서대로 읽고 OCF `mimetype` 규칙을 검증한다.
- `HwpxPackage.to_bytes()`는 `mimetype`을 첫 STORED 엔트리로 쓰고 timestamp를 고정한다. 같은 열린
  package의 반복 직렬화와 serialize/reparse 결과는 기존 `tests/test_package.py`가 고정한다.
- `section_xml_names()`는 `sectionN.xml`만 숫자순으로 반환한다.
- XML은 `lxml.etree.XMLParser(remove_blank_text=False, resolve_entities=False)`로 읽는다.
- 변형된 section은 `serialize_modified_section()`이 `linesegarray`를 제거한 뒤 UTF-8로 직렬화한다.

### 기존 Field

`fieldBegin`은 `hp:ctrl` 아래 있고 `fieldEnd`도 같은 형상이다. `_field_span()`은 begin이 속한
`run`에서 시작해 `run.getnext()`가 계속 `run`인 동안 첫 `fieldEnd`까지 걷는다. 따라서:

- 같은 문단의 형제 run과 같은 run 내부는 처리한다.
- 문단, 표, section 경계를 넘지 않는다.
- `fieldEnd@beginIDRef`를 대조해 짝을 고르는 알고리즘은 아니다.
- 현재 구현은 inline field span이며 document structural region의 증거가 아니다.

R2는 같은 native field begin/end primitive가 실제 block bookmark에서 세 문단을 가로지를 수 있음을
보였다. 이 입력에서 현재 `_field_span()`은 첫 문단의 다음 sibling인 `linesegarray`에서 멈춰 DDD
문단의 end를 찾지 못한다. 비교 대상이라는 이유만으로 기존 inline 구현을 document range로
일반화하지 않는다.

## 3. read-only structure probe

`tests/_hwpx_structure_probe.py`는 package를 수정하지 않고 section별 JSON Lines를 낸다.

```powershell
uv run python tests/_hwpx_structure_probe.py tests/corpus/real/form_purchase_v1.hwpx
```

각 record는 section entry/index, section 안의 전체 paragraph 순서, `hp:p@id`, XPath형 containment,
run 순서와 직접 `hp:t` 텍스트, control tag/attributes/direct children, 부모 안의 `child_index`를 담는다. `tbl`, `tr`, `tc`,
`subList`, `caption`은 container record로 표시한다. `bookmark`, `metaTag`, `fieldBegin`, `fieldEnd`와
이름이 `Begin`/`End`/`Start`로 끝나는 marker는 `role`로 눈에 띄게 표시하지만, 서로를 range로
결합하지 않는다. 속성과 JSON key는 정렬되고 section/paragraph/run은 문서 순서라 diff가 안정적이다.

합성 테스트가 증명하는 것은 발견, 위치 계산, 속성 출력, table containment, generic control dump,
동일 입력 결정성, package serialize/reparse 뒤 관찰 동일성뿐이다. 한글 native serialization은
증명하지 않는다.

## 4. 공식 OWPML 모델 대조

확정 사실:

- [`bookmark.cpp`](https://github.com/hancom-io/hwpx-owpml-model/blob/main/OWPML/Class/Para/bookmark.cpp)는
  `name` 하나만 읽고 쓴다. start/end, id/ref, payload 속성은 모델에 없다.
- [`ctrl.cpp`](https://github.com/hancom-io/hwpx-owpml-model/blob/main/OWPML/Class/Para/ctrl.cpp)는
  `bookmark`, `fieldBegin`, `fieldEnd`를 각각 독립 control child로 둔다.
- [`fieldBegin.cpp`](https://github.com/hancom-io/hwpx-owpml-model/blob/main/OWPML/Class/Para/fieldBegin.cpp)는
  `id`, `type`, `name`, `editable`, `dirty`, `zorder`, `fieldid`와 `parameters`, `subList`, `metaTag`
  child를 모델링한다.
- [`fieldEnd.cpp`](https://github.com/hancom-io/hwpx-owpml-model/blob/main/OWPML/Class/Para/fieldEnd.cpp)는
  `beginIDRef`, `fieldid`를 모델링한다.
- [`PType.cpp`](https://github.com/hancom-io/hwpx-owpml-model/blob/main/OWPML/Class/Para/PType.cpp)는
  paragraph `id`를 숫자 속성으로 읽고 쓸 뿐 안정성·유일성 의미를 부여하지 않는다.
- [`MetaTag.cpp`](https://github.com/hancom-io/hwpx-owpml-model/blob/main/OWPML/Class/Para/MetaTag.cpp)는
  MetaTag를 문자열 값으로 모델링한다. 공식 source의 child map에는 fieldBegin, section definition,
  table과 여러 drawing/shape object에 `metaTag`가 붙을 수 있다.
- 다른 begin/end형 inline marker로 `markpenBegin`/`markpenEnd`, 변경 추적
  `insertBegin`/`insertEnd`, `deleteBegin`/`deleteEnd`가 있다. 이는 각각 형광펜·변경 추적 구조이며
  bookmark나 generic document range라는 증거가 아니다.

## 5. tracked corpus audit

### HWPX

| 분류/파일 | bookmark element | metaTag element | fieldBegin / fieldEnd | paragraph id 관찰 | 증거 등급 |
|---|---:|---:|---:|---|---|
| real/bid_notice_limited_under100m.hwpx | 0 | 0 | 29 / 29 | 338개, 고유값 2개(`2147483648`, `0`) | repository real corpus |
| real/filled_notice_marine.hwpx | 0 | 0 | 29 / 29 | 338개, 고유값 2개 | repository real corpus |
| real/form_purchase_v1.hwpx | 0 | 0 | 1 / 1 | 2개, 고유값 2개 | repository real corpus |
| real/form_purchase_v2.hwpx | 0 | 0 | 0 / 0 | 1개 | repository real corpus |
| real/spec_revision_2025.hwpx | 0 | 0 | 1 / 1 | 393개, 고유값 2개(`2147483648`, `0`) | commit이 실제 규격서라고 명시 |
| real/spec_revision_2026.hwpx | 0 | 0 | 1 / 1 | 393개, 고유값 2개 | commit이 실제 규격서라고 명시 |
| scenario/templates/입찰공고서.hwpx | 0 | 0 | 25 / 25 | script 생성 | synthetic/scenario |
| scenario/templates/구매요청서.hwpx | 0 | 0 | 10 / 10 | script 생성 | synthetic/scenario |

real 6파일의 `fieldBegin` 61개는 모두 빈 `metaTag=""` attribute를 가진다. 이것은 MetaTag element가
아니며, 현재 corpus에는 non-empty native metadata가 없다. `golden/*.json`은 추출 결과라 native XML
증거가 아니다.

### S0 native bookmark corpus

사용자가 한글 UI로 만들고 HWPX로 저장한 R0~R4와 T0~T7을
`tests/corpus/structural_range_s0/`에 원본 그대로 보존했다. `version.xml`은 모두
`application="Hancom Office Hangul"`, `appVersion="12, 0, 0, 4426 WIN32LEWindows_10"`이다.

| 파일 | SHA-256 | native marker | probe 위치 |
|---|---|---|---|
| R0-plain.hwpx | `F07E0156159856A1D99B9AD04DB1169F55334E1D86AA047B21A67B47333539DE` | 없음 | 본문 5문단 |
| R1-point-bookmark.hwpx | `89C86C11CF82800E0B9A77AD894273987B3A00AD46F609D6E35B0BFAC5ADD404` | `<hp:bookmark name="S0_POINT"/>` 1개 | section0 / p[2] / run[0], `CCC` 앞 |
| R2-block-bookmark.hwpx | `1ABCFD6810636E9EEC00E1A14252AC46571B34AC7198F8EA38824EA5B759D55C` | `fieldBegin type="BOOKMARK"` + `fieldEnd` 1쌍 | section0 / p[1] / run[0]의 `BBB` 앞부터 p[3] / run[0]의 `DDD` 뒤까지 |
| R3-table-crossing.hwpx | `A0921B67AFDEAC1194DFC09ACBD7F89F1785078280E4D0754C1DB58599FA4B7A` | `fieldBegin type="BOOKMARK" name="S0_TABLE"` + `fieldEnd` 1쌍 | BBB 앞부터 DDD 뒤까지; 사이에 table paragraph와 cell paragraph 포함 |
| R4-adjacent.hwpx | `DAD403351011A11CF19F84809EC98BB60583ED4357ABB8AAF6279915CA512F2B` | `S0_LEFT`, `S0_RIGHT` BOOKMARK pair 각 1쌍 | 연속된 LEFT p[1], RIGHT p[2]에 begin→text→matching end 순서 |

R1 원본 XML의 point bookmark는 다음과 같다.

```xml
<hp:run charPrIDRef="0">
  <hp:ctrl><hp:bookmark name="S0_POINT"/></hp:ctrl>
  <hp:t>CCC</hp:t>
</hp:run>
```

R2 원본 XML은 두 `hp:bookmark`가 아니라 명시적으로 연결된 field pair다.

```xml
<!-- BBB 문단의 run 시작 -->
<hp:ctrl>
  <hp:fieldBegin id="1166046405" type="BOOKMARK" name="S0_BLOCK"
                 editable="0" dirty="1" zorder="-1"
                 fieldid="627207531" metaTag="">
    <hp:parameters cnt="1" name=""><hp:integerParam name="Prop">2</hp:integerParam></hp:parameters>
  </hp:fieldBegin>
</hp:ctrl>
<hp:t>BBB</hp:t>

<!-- DDD 문단의 run 끝 -->
<hp:t>DDD</hp:t>
<hp:ctrl><hp:fieldEnd beginIDRef="1166046405" fieldid="627207531"/></hp:ctrl>
<hp:t/>
```

따라서 이 한글 버전에서 UI로 만든 block bookmark는 paragraph를 가로지르는 native `fieldBegin` /
`fieldEnd` 범위다. `fieldEnd@beginIDRef`가 begin의 `id`를 직접 참조하며 `fieldid`도 일치한다.
이는 point bookmark와 별개의 encoding이다. 세 파일의 BBB~EEE 문단 id는 모두 `0`이므로 경계
결합에 paragraph id가 쓰였다는 증거도 없다.

R3에서도 같은 encoding을 사용한다. begin은 top-level BBB 문단의 text 앞, end는 top-level DDD
문단의 text 뒤에 있고, 그 사이 문서 순서에는 table을 소유한 top-level paragraph와
`tbl/tr/tc/subList` 아래의 `TBL` cell paragraph가 모두 존재한다. boundary 자체를 table 안에
복제하지 않고 pair가 container 전체를 감싼다.

다음은 namespace와 비핵심 attribute/child를 생략한 containment 발췌다.

```xml
<hp:p id="0"><hp:run>
  <hp:ctrl><hp:fieldBegin id="1166058052" type="BOOKMARK" name="S0_TABLE" .../></hp:ctrl>
  <hp:t>BBB</hp:t>
</hp:run></hp:p>
<hp:p id="0"><hp:run><hp:tbl id="1166058047"><hp:tr><hp:tc><hp:subList>
  <hp:p id="0"><hp:run><hp:t>TBL</hp:t></hp:run></hp:p>
</hp:subList></hp:tc></hp:tr></hp:tbl></hp:run></hp:p>
<hp:p id="0"><hp:run>
  <hp:t>DDD</hp:t>
  <hp:ctrl><hp:fieldEnd beginIDRef="1166058052" fieldid="627207531"/></hp:ctrl>
</hp:run></hp:p>
```

R4 원본 XML에서는 연속된 두 top-level paragraph가 각각 완결된 pair 하나를 가진다. 비핵심
attribute와 child는 생략했다.

```xml
<hp:p id="0"><hp:run>
  <hp:ctrl><hp:fieldBegin id="1166079346" type="BOOKMARK" name="S0_LEFT"
                           fieldid="627207531" .../></hp:ctrl>
  <hp:t>LEFT</hp:t>
  <hp:ctrl><hp:fieldEnd beginIDRef="1166079346" fieldid="627207531"/></hp:ctrl>
  <hp:t/>
</hp:run></hp:p>
<hp:p id="0"><hp:run>
  <hp:ctrl><hp:fieldBegin id="1166079347" type="BOOKMARK" name="S0_RIGHT"
                           fieldid="627207531" .../></hp:ctrl>
  <hp:t>RIGHT</hp:t>
  <hp:ctrl><hp:fieldEnd beginIDRef="1166079347" fieldid="627207531"/></hp:ctrl>
  <hp:t/>
</hp:run></hp:p>
```

document-order marker 순서는 LEFT begin → LEFT end → RIGHT begin → RIGHT end다. LEFT end와
RIGHT begin 사이에는 paragraph/layout 경계가 있지만 다른 BOOKMARK marker는 없다. 두 begin id는
서로 다르고 각 end가 자기 begin만 참조한다. 반면 두 paragraph id는 모두 `0`이고 두 pair의
`fieldid`는 모두 `627207531`이므로 이 값들은 pair 구분에 기여하지 않는다.

### fragment

`frag/ctrl_between.xml`에 `<hp:bookmark/>` 한 개가 있다. 이름도 없는 최소 synthetic fragment이며
probe/authoring 경계 테스트용이다. 나머지 fragment에는 조사 대상 marker가 없다. 이 bookmark는
한글이 저장한 책갈피 표현이나 block bookmark pair의 증거로 사용하지 않는다.

### 실제 field XML 표본

`real/form_purchase_v1.hwpx`, `Contents/section0.xml`, section paragraph 0의 관찰은 다음과 같다.

```xml
<hp:ctrl>
  <hp:fieldBegin id="2073595120" type="CLICK_HERE" name="진행상태"
                 fieldid="627272811" metaTag="">...</hp:fieldBegin>
</hp:ctrl>
<hp:run charPrIDRef="7"><hp:t>{{진행상태}}</hp:t></hp:run>
<hp:ctrl>
  <hp:fieldEnd beginIDRef="2073595120" fieldid="627272811"/>
</hp:ctrl>
```

확정 사실은 end가 begin의 `id`를 참조한다는 점이다. 같은 real 문서의 많은 서로 다른 field가
동일 `fieldid="627272811"`을 공유하므로 `fieldid` 단독 identity 가설은 성립하지 않는다.

## 6. native evidence table

| Evidence | 관찰 | 판정 |
|---|---|---|
| 한컴 공식 bookmark 모델 | `name`만 존재 | point marker에 가까운 schema 증거. native block serialization은 아님 |
| tracked real HWPX 6개 | bookmark 0, metaTag element 0 | block bookmark와 metadata durability 증거 없음 |
| R0 native | marker 없음 | 대조군 |
| R1 native | `hp:bookmark name="S0_POINT"` 1개가 `CCC` 앞에 존재 | point bookmark는 name-only point marker |
| R2 native | `fieldBegin type="BOOKMARK" name="S0_BLOCK"`이 `BBB` 앞, 이를 참조하는 `fieldEnd`가 `DDD` 뒤에 존재 | block bookmark는 cross-paragraph explicit field range |
| R3 native | 같은 field pair가 top-level paragraph → table/cell paragraph → top-level paragraph를 감쌈 | block bookmark는 table/container를 넘는 document-order structural range |
| R4 native | LEFT begin/end 뒤 RIGHT begin/end가 이어지고 각 end ref가 서로 다른 자기 begin id를 참조 | 인접 block bookmark 두 개는 ambiguity 없는 독립 pair |
| T0~T3 native | 재저장, 범위 앞/안 문단 삽입, 내부 문구 수정 뒤 begin/end attrs 불변 | 이 편집들에서는 pair identity와 경계가 보존됨 |
| T4/T5 native | 시작 또는 끝 경계 문단 하나를 삭제하면 begin/end가 모두 사라짐 | 한글이 orphan marker를 남기지 않고 block bookmark 전체를 제거함 |
| T6 native | 복사된 BBB~DDD에는 marker가 없고 원본 pair만 남음 | copy는 block bookmark를 복제하지 않아 identity 충돌이 없음 |
| T7 native | 이동한 pair의 name/fieldid는 유지, begin id는 `1166046405`→`1166054281`, end ref도 갱신 | cut/paste는 range를 이동하되 begin identity를 재발급함 |
| real field 61쌍 | `fieldEnd@beginIDRef == fieldBegin@id`; 동일 fieldid 반복 | explicit inline pair 증거, generic range 증거 아님 |
| real paragraph ids | 대형 문서 수백 문단이 두 id 값만 공유 | `hp:p@id`는 identity/locator로 부적합 |
| synthetic fragment | 익명 `<hp:bookmark/>` 1개 | probe 대상만 증명; native 의미 증거 아님 |

선행 가설 “`hp:bookmark`는 name만 가진 point marker에 가깝다”는 R1에서 확인됐다. 다만 이를
block bookmark에도 그대로 적용하는 추론은 R2가 깨뜨렸다. block bookmark는 같은 이름의 point
marker 두 개가 아니라 `type="BOOKMARK"` field pair다. 기존에 깨진 “paragraph id를 stable
identity로 쓸 수 있다” 가설도 그대로다. 편집 전부터 유일하지 않다.

## 7. S0 decision matrix

| 질문 | 판정 | 근거 |
|---|---|---|
| Q1. native block/document range가 직접 존재하는가? | **PROVEN** | R2는 문단, R3는 table/container를 가로지르는 `fieldBegin type="BOOKMARK"` / `fieldEnd@beginIDRef`로 직접 직렬화됨. 모든 generic range가 같다는 뜻은 아님 |
| Q2. 두 point marker로 안정적인 range를 표현할 수 있는가? | **UNKNOWN** | Q1의 “직접 존재하지 않는다면” 전제는 R2에서 성립하지 않으며, 두 `hp:bookmark`의 pairing·내구성 증거도 없음 |
| Q3. `hp:p@id`를 locator/identity로 신뢰할 수 있는가? | **DISPROVEN** | 동일 section에서 id가 중복되고 새 문단도 `0`; T7 이동 뒤 CCC/DDD는 `0`에서 `2147483648`로 변함 |
| Q4. native metadata는 어디에 붙고 round-trip을 견디는가? | **UNKNOWN** | 빈 `fieldBegin@metaTag`는 marker가 남은 T0~T3/T6/T7에서 보존됐으나 non-empty metadata와 MetaTag element의 한글 round-trip 증거는 없음 |
| Q5. copy/paste 시 marker와 identity는 어떻게 되는가? | **PROVEN** | T6 copy는 marker를 복제하지 않음. T7 cut/paste는 name/fieldid를 보존하고 begin id와 end ref를 함께 재발급함. 이 한글 버전과 조작에 한정 |
| Q6. 한 boundary 소실을 format kernel이 결정적으로 감지할 수 있는가? | **PROVEN** | explicit begin id/end ref로 orphan을 구조적으로 검사 가능. T4/T5에서 한글은 한 경계 문단 삭제 시 양 marker를 함께 제거해 orphan을 남기지 않음 |
| Q7. range 구조 제거 뒤 나머지를 손실 없이 deterministic serialize/reparse 가능한가? | **PROVEN** | S0-D1/D2에서 native R2와 table/container를 가로지르는 R3를 제거했고, S0-D4/D5에서 native R4 adjacent pair의 독립·양방향 순차 제거를 검증했다. 범위 밖 XML과 다른 package entry가 보존됐고 pair·container·빈 owner 잔재 없이 serialize/reparse와 probe 결정성이 통과했다. 변형 section의 `linesegarray` 전량 제거는 기존 kernel 계약이며 overlap/nesting·partial-paragraph 의미는 포함하지 않음 |

## 8. native corpus recipe와 후속 입력

한글에서 새 문서를 만들고 각 파일을 **HWPX로 저장**한다. 파일을 압축 해제하거나 XML을 수정하지
않는다. 본문은 정확히 다섯 문단으로 만든다.

```text
P1  AAA
P2  BBB
P3  CCC
P4  DDD
P5  EEE
```

완료된 파일:

1. `R0-plain.hwpx`: 표식 없이 저장.
2. `R1-point-bookmark.hwpx`: `CCC` 안 한 위치에 일반 책갈피 `S0_POINT` 생성 후 저장.
3. `R2-block-bookmark.hwpx`: `BBB` 시작부터 `DDD` 끝까지 블록 선택하고 책갈피 `S0_BLOCK` 생성 후 저장.
4. `R3-table-crossing.hwpx`: BBB와 DDD 사이에 `TBL` 1×1 표를 놓고 BBB 시작부터 DDD 끝까지
   선택해 `S0_TABLE` 생성 후 저장.

네 파일은 이 recipe로 생성됐고 native corpus에 보존됐다. package 자체의 `version.xml`과
`content.hpf`가 한글 버전과 수정 시각을 기록하므로 별도 메모 없이도 이 표본의 provenance를
되읽을 수 있다.

인접 pair 표본도 완료됐다.

5. `R4-adjacent.hwpx`: 연속된 LEFT/RIGHT 문단에 `S0_LEFT`, `S0_RIGHT` 생성.

다음 표본은 nesting 설계 판단이 필요해질 때만 추가한다.

6. `R5-overlap.hwpx`: UI가 허용할 때만 겹치거나 중첩된 `S0_OUTER`, `S0_INNER` 생성. 거절되면
   거절 사실과 문안을 기록하고 파일을 합성하지 않는다.

## 9. S0-C 편집 내구성 matrix

매번 원본 `R2-block-bookmark.hwpx`를 새 파일로 복제하고 한글에서 변형 하나만 수행한다. 서로의
변형을 누적하지 않았다. 원본은 `tests/corpus/structural_range_s0/T/`에 보존했다.

| ID | 변형 | native 관찰 | 판정 |
|---|---|---|---|
| T0 | 편집 없이 재저장 | `section0.xml` byte 동일; `content.hpf` 수정 시각만 변화 | 한글 round-trip에서 pair와 paragraph id 보존 |
| T1 | BBB 앞에 `BEFORE` 문단 삽입 | begin/end attrs 불변; 위치 p[1]/p[3]→p[2]/p[4]; 새 문단 id `0` | 범위 앞 삽입에 경계가 내용과 함께 밀림 |
| T2 | CCC와 DDD 사이에 `INSIDE` 문단 삽입 | attrs 불변; begin p[1], end p[3]→p[4]; 새 문단 id `0` | 삽입 문단이 기존 두 boundary 안에 포함됨 |
| T3 | CCC→CXC 수정 | pair attrs와 위치 불변 | 내부 문구 수정에 내구 |
| T4 | BBB 문단 전체 삭제 | begin/end 모두 없음; CCC/DDD/EEE만 남음 | 끝 boundary를 orphan으로 남기지 않고 range marker 전체 제거 |
| T5 | DDD 문단 전체 삭제 | begin/end 모두 없음; BBB/CCC/EEE만 남음 | 시작 boundary를 orphan으로 남기지 않고 range marker 전체 제거 |
| T6 | BBB~DDD 복사 후 EEE 뒤 붙여넣기 | 원본 pair 1쌍만 존재; 복사본 BBB/CCC/DDD에는 marker 없음 | marker/identity를 복제하지 않아 충돌 없음 |
| T7 | BBB~DDD 잘라 EEE 뒤 붙여넣기 | pair 이동; name/fieldid 유지; begin id 재발급 및 end ref 갱신 | content와 boundary는 동행하지만 begin id는 stable identity가 아님 |

T6의 복사 문단 id는 `0`, `2147483648`, `2147483648`이고 T7에서 이동한 CCC/DDD도
`2147483648`로 바뀌었다. paragraph id는 생성·이동 모두에서 locator로 사용할 수 없다.

## 10. 다음 단계

S0-D5는 R4 adjacent region의 양방향 순차 제거 판정에서 멈췄다. 이 증거 범위만 이후 §17의
제약된 production primitive로 승격했다. R5, partial paragraph, cross-section, overlap/nesting,
Slot은 구현하거나 판정하지 않았다.

## 11. S0 관찰 단계 검증

- `pytest tests/test_package.py tests/test_fields.py tests/test_hwpx_structure_probe.py`: 53 passed
- Ruff: 새 probe와 owner test 통과
- Pyright: 새 probe와 owner test 0 errors
- R0~R4와 T0~T7 각각 `HwpxPackage.to_bytes()` 후 reparse 시 probe JSONL 동일
- 당시 production source, UI, ViewModel, Slot API 변경 없음

## 12. S0-D1 R2 BOOKMARK range 제거 실험

### 12.1 실험 코드와 삭제 의미

`tests/_hwpx_bookmark_region_experiment.py`는 S0-D 당시 production API가 아닌 R2 전용
test-only spike였다. §17 승격에서 동작을 `hwpxcore.bookmark_region`으로 옮기고 이 파일은
삭제했다.
`Contents/section0.xml`에서 `fieldBegin type="BOOKMARK" name="S0_BLOCK"` 하나를 찾고, 그
`id`와 같은 `fieldEnd@beginIDRef` 하나를 결합한다. 이 값은 pair 결합에만 쓰며 durable identity로
해석하지 않는다. `fieldid`와 `hp:p@id`는 사용하지 않는다.

R2에서 실제 제거한 node는 section 직계 child인 다음 세 `hp:p`다.

- BBB paragraph: 첫 run 안의 `fieldBegin`, `parameters`, `hp:t`와 `linesegarray` 포함
- CCC paragraph: `hp:t`와 `linesegarray` 포함
- DDD paragraph: `hp:t`, matching `fieldEnd`, 빈 trailing `hp:t`, `linesegarray` 포함

marker 두 개만 떼어낸 것이 아니라 begin 조상 paragraph부터 end 조상 paragraph까지 세 shell을
통째로 제거했다. 변형 section은 기존 kernel의 `serialize_modified_section()`을 사용하므로 남은
AAA/EEE의 stale `linesegarray`도 전량 제거된다. 이는 선택적 layout cache를 재계산하게 하는 기존
write 계약이며, 테스트는 그 외 AAA/EEE XML과 다른 ZIP entry가 보존되는지 별도로 비교한다.

### 12.2 결과

| 확인 항목 | 결과 |
|---|---|
| BBB / CCC / DDD | 세 paragraph shell과 함께 제거 |
| BOOKMARK begin/end | 제거된 시작/끝 paragraph 안에서 함께 제거; 잔재 0 |
| AAA / EEE | text와 비-layout XML 보존 |
| 빈 구조 | 빈 `hp:p` 또는 `hp:run` 없음 |
| package collateral | `Contents/section0.xml` 외 모든 entry byte 동일 |
| serialize/reparse | 성공 |
| 결정성 | reparse 전후 probe 동일, 같은 R2 입력을 다시 변환한 package bytes 동일 |

native 한글 UI의 삭제 결과와 byte 단위로 대조할 oracle은 없다. 따라서 이 실험은 kernel이 R2
구조를 손실 없이 제거하고 재직렬화할 수 있음을 증명하지만, 한글 UI가 내부적으로 같은 node
선택을 한다고 주장하지 않는다.

### 12.3 판정

- R2 BOOKMARK range 제거: **가능**.
- 범위 밖 구조: **보존**. 단, stale `linesegarray`는 기존 kernel 계약대로 제거.
- 빈 구조/collateral damage: **관찰되지 않음**.
- Q7: **PROVEN**, 단 native R2의 same-section, top-level full-paragraph BOOKMARK에 한정.
- R3, adjacency, partial paragraph, generic production abstraction: **S0-D1 범위 밖**.

### 12.4 S0-D1 검증

- owner baseline: 기존 package/fields/probe 49 passed
- owner after: `tests/test_hwpx_structure_probe.py` 4 passed(기존 3 + 신규 1)
- targeted package/fields/probe: 50 passed
- Ruff: experimental helper와 owner test 통과
- Pyright: experimental helper와 owner test 0 errors
- heavy-resource launch delta: 0
- production source, UI, ViewModel, Product Contract, Slot API 변경 없음

## 13. S0-D2 R3 table-crossing BOOKMARK 제거 실험

### 13.1 실험 코드와 삭제 의미

S0-D1 당시 test-only remover는 begin/end 조상인 top-level paragraph와 그 사이 section 직계
child를 shell째 제거한다. S0-D2에서는 generic resolver를 만들지 않고 R3 fixture 전용
`remove_r3_bookmark_range()`만 같은 내부 경로에 연결했다. pair 결합에는
`fieldBegin@id == fieldEnd@beginIDRef`만 사용하며 `hp:p@id`와 `fieldid`는 사용하지 않는다.

R3에서 제거한 section 직계 child는 다음 세 `hp:p`다.

- BBB paragraph: `fieldBegin type="BOOKMARK" name="S0_TABLE"`과 BBB 포함
- table owner paragraph: `hp:run` 아래 `tbl → tr → tc → subList → cell hp:p → hp:run → hp:t(TBL)` 전체 포함
- DDD paragraph: DDD와 matching `fieldEnd` 포함

테스트는 제거 전 위 부모 관계를 element identity로 검증하고, 제거 후 text뿐 아니라
`tbl/tr/tc/subList`, BOOKMARK pair, 빈 owner paragraph/run이 모두 사라졌는지 검사한다.

### 13.2 결과와 판정

| 확인 항목 | 결과 |
|---|---|
| BBB / DDD | 경계 paragraph shell과 함께 제거 |
| table/container | owner paragraph를 포함해 `tbl/tr/tc/subList`와 cell paragraph 전체 제거 |
| BOOKMARK begin/end | 잔재 0 |
| 빈 owner 구조 | 빈 `hp:p` 또는 `hp:run` 없음 |
| AAA / EEE | text와 비-layout XML 보존 |
| package collateral | `Contents/section0.xml` 외 모든 entry byte 동일 |
| serialize/reparse | 성공 |
| 결정성 | reparse 전후 probe 동일, 같은 R3 입력을 다시 변환한 package bytes 동일 |

의도된 section-wide `linesegarray` 제거 외 collateral damage는 관찰되지 않았다. 따라서 Q7의
PROVEN 범위를 native R2 plain paragraphs에서 native R3의 **table/container-crossing,
same-section, top-level full-paragraph BOOKMARK region**까지 확장한다. adjacency, partial paragraph,
production abstraction은 이 판정에 포함하지 않는다.

### 13.3 S0-D2 검증

- owner before: `tests/test_hwpx_structure_probe.py` 4 passed
- owner after: `tests/test_hwpx_structure_probe.py` 5 passed(신규 1)
- targeted package/fields/probe: 51 passed
- Ruff: experimental helper와 owner test 통과
- Pyright: experimental helper와 owner test 0 errors
- heavy-resource launch delta: 0
- production source, UI, ViewModel, Product Contract, Slot API 변경 없음

## 14. S0-D3 R4 adjacent BOOKMARK native 관찰

### 14.1 관찰

한글 `12, 0, 0, 4426 WIN32LEWindows_10`이 저장한 R4에는 BOOKMARK `fieldBegin` 두 개와
`fieldEnd` 두 개가 있다. probe와 원본 XML의 document order는 다음과 같다.

1. p[1] `S0_LEFT` begin id `1166079346`
2. p[1] end `beginIDRef="1166079346"`
3. p[2] `S0_RIGHT` begin id `1166079347`
4. p[2] end `beginIDRef="1166079347"`

따라서 LEFT extent와 RIGHT extent는 각각 자기 paragraph 안에서 닫히며 교차하거나 중첩되지 않는다.
begin id/ref만으로 두 region을 독립 결합할 수 있다. 두 `hp:p@id`와 `fieldid`가 서로 같다는 사실은
오히려 이들을 locator/identity로 쓰지 않아야 한다는 기존 결론을 재확인한다.

### 14.2 판정

- 인접한 두 native BOOKMARK region의 독립 pair 표현: **PROVEN**.
- adjacency로 인한 pairing ambiguity: **DISPROVEN**.
- 두 region의 독립 document-order resolve 가능성: **PROVEN**.

이는 R4의 native 관찰 판정이다. region 제거, adjacency removal, R5, generic resolver나 production
API는 구현하거나 시험하지 않았다.

### 14.3 S0-D3 검증

- owner before/after: `tests/test_hwpx_structure_probe.py` 5 passed(기존 test 1건 확장, collected delta 0)
- targeted package/fields/probe: 51 passed
- heavy-resource launch delta: 0
- production source와 experimental remover 변경 없음

## 15. S0-D4 R4 adjacent BOOKMARK 독립 제거 실험

### 15.1 방법

Case A와 Case B는 각각 원본 `R4-adjacent.hwpx`를 새로 열었다. 당시 test-only private remover에
R4의 정확한 이름과 extent만 고정한 `remove_r4_left_bookmark_range()`와
`remove_r4_right_bookmark_range()`를 추가했다. generic resolver/API로 확대하지 않았다.

남은 region의 보존은 text만으로 판정하지 않았다. `linesegarray`만 제외한 AAA, EEE, surviving
BOOKMARK paragraph XML을 변환 전후 byte 비교하고, probe에서 surviving begin의 id와 end의
`beginIDRef`를 다시 결합했다. 다른 package entry도 byte 비교했다.

### 15.2 결과

| Case | 제거 결과 | surviving region | 구조·직렬화 |
|---|---|---|---|
| A: LEFT만 제거 | `S0_LEFT` pair와 LEFT paragraph shell 제거 | RIGHT text와 `S0_RIGHT` pair XML 보존; end ref가 기존 begin id를 다시 참조 | AAA/RIGHT/EEE, 빈 p/run·marker 잔재 없음, serialize/reparse probe 동일 |
| B: RIGHT만 제거 | `S0_RIGHT` pair와 RIGHT paragraph shell 제거 | LEFT text와 `S0_LEFT` pair XML 보존; end ref가 기존 begin id를 다시 참조 | AAA/LEFT/EEE, 빈 p/run·marker 잔재 없음, serialize/reparse probe 동일 |

두 case 모두 `Contents/section0.xml` 외 package entry는 byte 동일했다. 변형 section의
`linesegarray` 전량 제거 외 collateral damage는 관찰되지 않았다.

### 15.3 판정

- LEFT 단독 제거 후 RIGHT 완전 보존: **PROVEN**.
- RIGHT 단독 제거 후 LEFT 완전 보존: **PROVEN**.
- surviving region 독립 re-resolve: **PROVEN**.
- adjacent BOOKMARK region 독립 제거: **PROVEN**.

LEFT→RIGHT 또는 RIGHT→LEFT 순차 제거는 수행하지 않았고 이 판정에 포함하지 않는다. R5,
partial paragraph, production 승격도 범위 밖이다.

### 15.4 S0-D4 검증

- owner before/after: `tests/test_hwpx_structure_probe.py` 5 → 6 passed(대칭 case를 test 1건에서 실행)
- targeted package/fields/probe: 52 passed
- owner runtime: 0.09s → 0.11s
- targeted runtime: 0.26s → 0.35s
- heavy-resource launch delta: 0
- coverage-floor impact: 없음; production source 변경 없음

## 16. S0-D5 R4 adjacent BOOKMARK 순차 제거 실험

### 16.1 방법

두 case는 각각 원본 R4에서 시작했다. 첫 region 제거 뒤 반드시 `HwpxPackage.to_bytes()`와
`HwpxPackage.from_bytes()`를 거쳐 새 package를 만들고, probe에서 surviving begin/end를
`fieldBegin@id == fieldEnd@beginIDRef`로 다시 결합한 다음 기존 반대쪽 R4 wrapper를 호출했다.
S0-D5 당시에는 새 remover나 resolver abstraction을 추가하지 않았다.

### 16.2 결과

| Case | 중간 reparse | 두 번째 제거 뒤 |
|---|---|---|
| LEFT → RIGHT | AAA/RIGHT/EEE, `S0_RIGHT` begin/end 재결합 성공 | AAA/EEE, marker 0, 빈 p/run 0 |
| RIGHT → LEFT | AAA/LEFT/EEE, `S0_LEFT` begin/end 재결합 성공 | AAA/EEE, marker 0, 빈 p/run 0 |

양쪽 모두 AAA/EEE의 비-layout XML과 `Contents/section0.xml` 외 package entry가 보존됐고 최종
serialize/reparse가 성공했다. 두 순서의 최종 `section0.xml`과 probe 출력은 완전히 동일했다.
의도된 `linesegarray` 제거 외 collateral damage는 관찰되지 않았다.

### 16.3 판정

- LEFT→RIGHT 순차 제거: **PROVEN**.
- RIGHT→LEFT 순차 제거: **PROVEN**.
- 중간 surviving region re-resolve: **PROVEN**.
- 제거 순서와 무관한 최종 semantic structure: **PROVEN**.
- native R4 adjacent BOOKMARK 제거 composability: **PROVEN**.

이 판정은 R4의 two adjacent, same-section, top-level full-paragraph BOOKMARK pair에 한정한다. R5,
partial paragraph, production API나 generic abstraction은 포함하지 않는다.

### 16.4 S0-D5 검증

- owner before/after: `tests/test_hwpx_structure_probe.py` 6 → 7 passed(양 순서를 test 1건에서 실행)
- targeted package/fields/probe: 53 passed
- owner runtime: 0.11s → 0.11s
- targeted runtime: 0.35s → 0.30s(실행 편차 포함)
- heavy-resource launch delta: 0
- coverage-floor impact: 없음; production source 변경 없음

## 17. 제약된 BOOKMARK region production 승격

### 17.1 위치와 API

production 구현은 `src/hwpxcore/bookmark_region.py` 한 모듈에 둔다. 제품 의미나 generic
structural range 계층을 만들지 않고 다음 세 이름만 공개한다.

- `BookmarkRegion`: 현재 section snapshot에만 유효한 opaque handle. `start_paragraph`와
  `end_paragraph`는 section 직계 `hp:p`의 0-based inclusive 위치다.
- `resolve_bookmark_regions(pkg)`: 문서 순서로 지원 가능한 native BOOKMARK region을 검증·반환한다.
- `remove_bookmark_region(pkg, region)`: 같은 snapshot에서 다시 resolve한 정확한 region의
  top-level paragraph shell을 제거하고 기존 `serialize_modified_section()`으로 직렬화한다.

begin id와 end `beginIDRef`는 private pairing reference로만 사용한다. `hp:p@id`, `fieldid`,
bookmark name을 durable identity로 쓰지 않으며 section이 변하면 handle을 다시 resolve해야 한다.

### 17.2 production 계약

계약은 S0에서 PROVEN인 다음 범위뿐이다.

- same-section `fieldBegin type="BOOKMARK"` / matching `fieldEnd@beginIDRef`
- native `ctrl → run → section-direct hp:p`의 full-paragraph boundary
- 중간 paragraph가 table/container owner여도 paragraph shell째 제거
- R4 adjacent region의 독립 제거와 serialize/reparse 뒤 양방향 순차 제거
- 범위 밖 paragraph의 non-layout XML과 다른 package entry 보존
- 변형 section의 `linesegarray` 전량 제거와 deterministic serialize/reparse

partial-paragraph, cross-section, crossing/nesting BOOKMARK, 비-native containment, section의 모든
paragraph 제거, malformed/ambiguous pair는 명시적으로 거부한다. 다른 Field의 의미를
`FieldDocument._field_span()`과 합치거나 검증하지 않는다. 단, 제거 extent가 다른 field pair의
한쪽 marker만 자르거나 그 pair 안에 중첩되면 orphan/collateral damage를 막기 위해 제거 전에
거부한다.

### 17.3 실험 코드 정리와 owner

중복 remover였던 `tests/_hwpx_bookmark_region_experiment.py`와 fixture별 wrapper는 삭제했다.
read-only probe인 `tests/_hwpx_structure_probe.py`와 관찰 test 3건은 증거 도구로 유지한다.
R2/R3/R4 resolve·remove·adjacent composability와 미지원 진단은
`tests/test_bookmark_regions.py`가 production behavior를 직접 소유한다. root `hwpxcore` facade,
Slot, application/UI wiring, 기존 Field 구현은 변경하지 않았다.

### 17.4 검증

- owner: `tests/test_bookmark_regions.py` 5 + read-only probe owner 3 = 8 passed, 0.12s
- test portfolio delta: S0-D5의 probe/spike 7건에서 probe 3 + production owner 5건으로 +1;
  superseded experimental remover와 fixture wrapper는 삭제, heavy-resource launch delta 0
- targeted package/Field/architecture/owner: 67 passed
- repository 전체 `test.ps1`: web build/seal, npm test, Ruff, Pyright, pytest/coverage 모두 PASS;
  2,278 passed in 179.34s
- `hwpxcore` package coverage: line 96.01%(530/552, floor 95%), branch 89.18%(239/268,
  floor 87%), PASS

## 18. S0-D6 BOOKMARK 생성 spike

### 18.1 생성 방법

`tests/_hwpx_bookmark_creation_spike.py`는 production API가 아닌 test-only generator다. native R0의
top-level BBB run 시작과 DDD run 끝에 다음 최소 pair만 삽입했다.

```xml
<hp:ctrl>
  <hp:fieldBegin id="1600000001" type="BOOKMARK" name="S0_GENERATED"/>
</hp:ctrl>
<!-- BBB ... CCC ... DDD -->
<hp:ctrl><hp:fieldEnd beginIDRef="1600000001"/></hp:ctrl>
```

R2에서 관찰한 위치와 pairing 규칙은 사용했지만 `editable`, `dirty`, `zorder`, `fieldid`,
`metaTag`, `parameters`, trailing empty `hp:t`는 의도적으로 생성하지 않았다. begin id는 이
실험 snapshot의 결합 참조일 뿐 durable identity로 해석하지 않는다. 생성본은
`D6-generated-minimal.hwpx`, 사용자가 한글에서 정상 block bookmark로 확인하고 편집 없이 다른
이름으로 저장한 결과는 `D6-generated-resaved.hwpx`로 보존한다.

### 18.2 한글 인식과 재저장 관찰

사용자는 한글 UI에서 `S0_GENERATED`가 BBB~DDD block bookmark로 정상 인식됐다고 판정했다.
재저장본의 `version.xml`은 앞선 native corpus와 같은 Hancom Office Hangul
`12, 0, 0, 4426 WIN32LEWindows_10`을 기록한다.

| 항목 | 생성본 | 한글 재저장본 | 관찰 |
|---|---|---|---|
| begin 핵심 | `id=1600000001`, `type=BOOKMARK`, `name=S0_GENERATED` | 동일 | pairing id/name/type 보존; 재발급 없음 |
| end 핵심 | `beginIDRef=1600000001` | 동일 | pair 보존 |
| begin attrs | 핵심 3개뿐 | `editable=1`, `dirty=0`, `zorder=-1`, `fieldid=627207531`, `metaTag=""` 추가 | 인식에는 불필요했으나 한글 저장 시 정규화 |
| begin child | 없음 | `parameters(cnt=1,name="")/integerParam(name=Prop)=2` 추가 | 인식에는 불필요했으나 한글 저장 시 정규화 |
| end attrs | ref뿐 | `fieldid=627207531` 추가 | begin/end에 같은 fieldid 보충 |
| DDD run tail | marker 뒤 node 없음 | 빈 `hp:t` 추가 | native R2/R4와 같은 trailing shape로 정규화 |
| boundary 위치 | p[1] BBB 앞 ~ p[3] DDD 뒤 | 동일 | document-order extent 보존 |
| layout | `linesegarray` 0 | 5개 | 한글이 전체 문단 layout cache 재생성 |

ZIP entry 11개의 이름과 순서는 유지됐다. byte가 달라진 entry는 `Contents/section0.xml`과
`Contents/content.hpf`뿐이며, 후자는 `ModifiedDate`만 변경됐다. 나머지 9개 entry는 byte
동일하다. 생성본과 재저장본 SHA-256은 각각
`21F4283AEEB1B8786E498A50943B17685CF391D9C205F882A46F9D4A2629E142`,
`56E74322DCA526089B28FFB25C8EB71411CDE98A3B4F5DD47916C1538E8D314B`다.

### 18.3 판정

- 프로그램 생성 BOOKMARK의 한글 인식: **PROVEN**.
- 한글 재저장 뒤 pair/extent 보존: **PROVEN**.
- 최소 생성에 필요한 것으로 확인된 구조: full-paragraph 위치의
  `fieldBegin(id,type=BOOKMARK,name)` + matching `fieldEnd(beginIDRef)`.
- 추가 native 속성과 `parameters`는 이 표본의 **인식에는 필수가 아니었고**, 한글이 재저장하며
  보충했다. 다른 한글 버전에서도 불필요하다고 일반화하지 않는다.
- 생성 capability: **PROVEN**, 단 R0 shape, same-section, top-level BBB~DDD full-paragraph,
  Hancom Office Hangul 12.0.0.4426에 한정한다.

production `create_*` API, Slot, Authoring Anchor, 기존 resolve/remove 계약은 변경하지 않았다.

### 18.4 검증

- owner before/after: probe 3 + production owner 5 = 8 → probe 4 + production owner 5 = 9 passed
- owner runtime: 0.14s → 0.15s(실행 편차 포함)
- targeted package/Field/production owner/D6 probe: 55 passed, 0.31s
- Ruff: D6 spike/helper owner 통과
- Pyright: D6 spike/helper owner 0 errors
- heavy-resource launch delta: 저장소 자동 test lane 0; 사용자 한글 UI 확인/재저장 1회
- production source·coverage floor 영향 없음
