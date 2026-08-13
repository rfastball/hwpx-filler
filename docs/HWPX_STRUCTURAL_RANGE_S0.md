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

사용자가 한글 UI로 만들고 HWPX로 저장한 표본을 `tests/corpus/structural_range_s0/`에 원본
그대로 보존했다. `version.xml`의 `application`은 모두 `Hancom Office Hangul`이지만
**`appVersion`은 두 갈래**다.

- R0~R4와 T0~T7: `12, 0, 0, 4426 WIN32LEWindows_10`
- R5 두 파일(§19에서 추가): `12, 0, 0, 4547 WIN32LEWindows_10`

두 버전이 같은 encoding을 쓴다는 것 자체는 이 corpus가 보이는 사실이지만, 버전 간 차이를
따로 조사하지는 않았다.

| 파일 | SHA-256 | native marker | probe 위치 |
|---|---|---|---|
| R0-plain.hwpx | `F07E0156159856A1D99B9AD04DB1169F55334E1D86AA047B21A67B47333539DE` | 없음 | 본문 5문단 |
| R1-point-bookmark.hwpx | `89C86C11CF82800E0B9A77AD894273987B3A00AD46F609D6E35B0BFAC5ADD404` | `<hp:bookmark name="S0_POINT"/>` 1개 | section0 / p[2] / run[0], `CCC` 앞 |
| R2-block-bookmark.hwpx | `1ABCFD6810636E9EEC00E1A14252AC46571B34AC7198F8EA38824EA5B759D55C` | `fieldBegin type="BOOKMARK"` + `fieldEnd` 1쌍 | section0 / p[1] / run[0]의 `BBB` 앞부터 p[3] / run[0]의 `DDD` 뒤까지 |
| R3-table-crossing.hwpx | `A0921B67AFDEAC1194DFC09ACBD7F89F1785078280E4D0754C1DB58599FA4B7A` | `fieldBegin type="BOOKMARK" name="S0_TABLE"` + `fieldEnd` 1쌍 | BBB 앞부터 DDD 뒤까지; 사이에 table paragraph와 cell paragraph 포함 |
| R4-adjacent.hwpx | `DAD403351011A11CF19F84809EC98BB60583ED4357ABB8AAF6279915CA512F2B` | `S0_LEFT`, `S0_RIGHT` BOOKMARK pair 각 1쌍 | 연속된 LEFT p[1], RIGHT p[2]에 begin→text→matching end 순서 |
| R5-nested.hwpx | `3212AF6CA24355CD8D400434713B22E554FE4A94A54A4E4808803E5B1F198EA1` | `S0_SLOT` 안에 `S0_OPT_A`, `S0_OPT_B`가 중첩된 BOOKMARK 3쌍 | slot=p[1]~p[4], option=p[2], p[3] (§19) |
| R5-nested-resaved.hwpx | `D0AB9A1DC820108387C303A5F7E9E1B88CC016773D08FED5783D6AE68A25EF0D` | 위와 동일 | `AAA`→`AAX` 편집 후 한글 재저장 (§19) |

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
| R5 native | 한글 UI가 중첩 생성을 거절하지 않았고 문서 순서가 `SLOT > A > A' > B > B' > SLOT'` | proper nesting은 native로 생성·표현되며 crossing 과 결정적으로 구분된다(§19) |
| R5 재저장 | marker record 6개와 begin id가 전부 불변 | nesting 은 한글 open/save 를 견딘다. 다만 nested region 의 **제거** 의미는 미검증 |
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

nesting 표본도 완료됐다(S0-E, §19).

6. `R5-nested.hwpx`: `BBB`~`EEE`에 `S0_SLOT`을 만든 뒤 그 안의 `CCC`, `DDD` 문단에 각각
   `S0_OPT_A`, `S0_OPT_B` 생성. 한글 UI가 거절하지 않았다.
7. `R5-nested-resaved.hwpx`: 6을 다시 열어 `AAA`→`AAX`만 고치고 저장.

겹침(crossing) 표본은 아직 없다. nesting과 crossing은 다른 질문이므로 §19의 판정을 crossing에
적용하지 않는다.

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
제약된 production primitive로 승격했다. partial paragraph, cross-section, crossing, Slot은
구현하거나 판정하지 않았다.

nesting은 이후 §19(S0-E)에서 **관찰만** 했다. production resolver는 여전히 거부하며 이 spike는
그것을 바꾸지 않았다.

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
  `end_paragraph`는 section 직계 `hp:p`의 0-based inclusive 위치다. `parent`는 바로 바깥의
  region이고 최상위면 `None`이다(§20). 중첩된 두 region이 같은 문단 범위를 가질 수 있으므로
  포함 관계는 문단 색인이 아니라 **문서 순서**가 정한다.
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

partial-paragraph, cross-section, **crossing** BOOKMARK, 비-native containment, section의 모든
paragraph 제거, malformed/ambiguous pair는 명시적으로 거부한다. proper nesting은 §20에서 resolve
대상으로 승격했고, **중첩에 참여하는 region의 제거는 여전히 거부한다** — S0가 증명한 제거 범위는
서로 겹치지 않는 region뿐이다. 다른 Field의 의미를
`FieldDocument._field_span()`과 합치거나 검증하지 않는다. 단, 제거 extent가 다른 field pair의
한쪽 marker만 자르거나 그 pair 안에 중첩되면 orphan/collateral damage를 막기 위해 제거 전에
거부한다. section/boundary marker는 공식 `hs`/`hp` namespace만 수용하며, `markpen` 또는
change-tracking begin/end가 extent 안에 있거나 extent를 감쌀 가능성이 있으면 별도의 generic
pairing 의미를 추정하지 않고 제거를 거부한다.

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

S0-D6 당시 test-only generator는 native R0의 top-level BBB run 시작과 DDD run 끝에 다음 최소
pair만 삽입했다. S1.6 #633에서 같은 생성 의미는 production `create_bookmark_region()`으로
승격됐고, 이 generator는 제거했다.

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

S0-D6 시점에는 production `create_*` API, Slot, Authoring Anchor, 기존 resolve/remove 계약을
변경하지 않았다. production 승격과 mutation 대칭성은 후속 S1.6 #633이 소유한다.

### 18.4 검증

- owner before/after: probe 3 + production owner 5 = 8 → probe 4 + production owner 5 = 9 passed
- owner runtime: 0.14s → 0.15s(실행 편차 포함)
- targeted package/Field/production owner/D6 probe: 55 passed, 0.31s
- Ruff: D6 spike/helper owner 통과
- Pyright: D6 spike/helper owner 0 errors
- heavy-resource launch delta: 저장소 자동 test lane 0; 사용자 한글 UI 확인/재저장 1회
- production source·coverage floor 영향 없음

## 19. S0-E nested BOOKMARK native 관찰

### 19.1 방법과 표본

한글 `12, 0, 0, 4547 WIN32LEWindows_10`에서 5문단 `AAA`~`EEE`를 만들고 다음 순서로 책갈피 3개를
생성한 뒤 HWPX로 저장했다. 바깥을 먼저 만들고 안쪽 둘을 나중에 넣었다.

| 이름 | 범위 |
|---|---|
| `S0_SLOT` | `BBB` 시작 ~ `EEE` 끝 (4문단) |
| `S0_OPT_A` | `CCC` 문단 전체 |
| `S0_OPT_B` | `DDD` 문단 전체 |

**한글 UI는 중첩 책갈피 생성을 거절하지 않았다.** 이는 §8 항목 6이 열어 둔 조건("UI가 허용할
때만")에 대한 답이다. 재저장본은 `AAA`→`AAX` 한 곳만 고쳐 저장했다.

| 파일 | SHA-256 |
|---|---|
| `R5-nested.hwpx` | `3212AF6CA24355CD8D400434713B22E554FE4A94A54A4E4808803E5B1F198EA1` |
| `R5-nested-resaved.hwpx` | `D0AB9A1DC820108387C303A5F7E9E1B88CC016773D08FED5783D6AE68A25EF0D` |

### 19.2 native document order

probe가 낸 marker 순서는 정확히 다음이다. 문단 색인은 section 직계 `hp:p` 기준이다.

```text
0  fieldBegin S0_SLOT    id=1166752276  p[1] (BBB)
1  fieldBegin S0_OPT_A   id=1166752277  p[2] (CCC)
2  fieldEnd   beginIDRef=1166752277     p[2]
3  fieldBegin S0_OPT_B   id=1166752278  p[3] (DDD)
4  fieldEnd   beginIDRef=1166752278     p[3]
5  fieldEnd   beginIDRef=1166752276     p[4] (EEE)
```

세 begin은 서로 다른 id를 갖고 각 end는 자기 begin만 참조한다. `fieldid`는 셋 모두
`627207531`로 같아 pair 구분에 기여하지 않는다 — R4에서 확인한 것과 같다. 여섯 marker 모두
native `ctrl → run → section 직계 hp:p` 아래에 있고, 경계 marker 바깥에 같은 문단의 텍스트가
없다(full-paragraph boundary).

### 19.3 판정

| 확인 항목 | 결과 |
|---|---|
| 한글 UI의 nested BOOKMARK 생성 | **가능**. 거절 문구 없음 |
| 세 pair의 독립 결합(`begin id ↔ end beginIDRef`) | **PROVEN**. begin id 3개가 서로 다르고 end가 각자 자기 begin만 참조 |
| Option이 Slot range에 완전 포함 | **PROVEN**. slot(0..5) 안에 A(1..2), B(3..4) |
| 두 Option의 관계 | **disjoint 형제**. A end(2) < B begin(3) |
| proper nesting vs crossing | **결정적으로 nesting**. 열린 순서의 역순으로 닫힌다(`SLOT > A > A' > B > B' > SLOT'`) |
| 한글 재저장 뒤 보존 | **PROVEN**. marker record 6개가 완전히 동일. begin id 재발급 없음 |

재저장본에서 `Contents/section0.xml`의 비-layout 차이는 `AAA`→`AAX` 한 줄뿐이다. 다른 package
entry 중 내용이 바뀐 것은 `content.hpf`(수정 시각), `settings.xml`(캐럿), `Preview/*`(본문 변경
반영)이고 `header.xml`은 byte 동일하다.

판정 범위를 좁게 적는다. 이 표본이 **증명하지 않는 것**은 다음이다.

- **제거 의미.** S0-D 계열과 달리 제거 실험은 하지 않았다. 안쪽만 지울 때 바깥이 어떻게 되는지,
  바깥을 지울 때 안쪽이 어떻게 되는지는 미검증이다.
- **범위 안쪽 편집의 내구성.** 재저장본의 편집 지점 `AAA`는 p[0]이라 slot(p[1]~p[4]) **바깥**이다.
  S0-C의 T1~T7이 R2에 대해 한 것처럼 범위 안 문단 삽입·삭제·수정을 nested 구조에 대해 반복하지
  않았다. 따라서 "한글이 nesting을 보존한다"는 판정은 **범위 밖 편집 1회**에 한정된다.
- **crossing.** 겹치는 표본을 만들지 않았으므로 한글이 crossing을 허용하는지는 여전히 UNKNOWN이다.
- **더 깊은 중첩과 복수 Slot.** 2단 1개 표본이다.

### 19.4 현재 production resolver와의 차이

`resolve_bookmark_regions()`는 이 native 파일을 **의도적으로 거부**한다.

```text
ValueError: Contents/section0.xml: nested BOOKMARK regions are unsupported: 'S0_SLOT', 'S0_OPT_A'
```

`_reject_bookmark_overlap()`은 region별 검증이 **모두 끝난 뒤에** 호출되므로, 이 메시지가 났다는
것은 세 region이 boundary 형상·partial-paragraph·비-paragraph child·cross-section 검사를 전부
통과했다는 뜻이다. 즉 **읽지 못하는 것이 아니라 읽지 않기로 한 것**이고, 막는 규칙은 §17.2의
nesting 금지 하나뿐이다.

**이 절은 S0-E 관찰 시점의 기록이다.** 여기서 지목한 규칙은 이후 §20에서 바뀌었다 — resolve는
proper nesting을 받아들이고 containment를 표현하며, crossing 거부와 nested 제거 금지는 유지한다.

### 19.5 S0-E 검증

- owner: `tests/test_hwpx_structure_probe.py`에 native R5 관찰 test 1건 추가(4 → 5 passed)
- 거부 계약: `tests/test_bookmark_regions.py`의 기존 거부 표에 native R5 case 1건 추가
  (합성 nested case와 실패 원인이 다르다 — 전자는 규칙의 존재, 후자는 실물 적용)
- 두 owner 합계 10 passed, 0.21s
- Ruff·Pyright 통과, heavy-resource launch delta 0
- production source 변경 없음

## 20. proper nesting resolution 승격

§19가 native 증거를 세웠으므로 resolve 계약을 그 증거 범위만큼 넓혔다. crossing 거부는 그대로다.

### 20.1 바뀐 것

- `_reject_bookmark_overlap()`을 `_link_containment()`로 바꿨다. 문서 순서로 정렬된 region을
  훑으며 아직 닫히지 않은 region을 스택으로 들고, 바로 위 항목을 그 region의 `parent`로 기록한다.
- **crossing 판정은 그대로 거부**한다. 열린 역순으로 닫히지 않으면 — 즉 안쪽이 바깥보다 늦게
  끝나면 — `crossing BOOKMARK regions are unsupported`로 실패한다. 진단 문안과 실패 지점은
  바뀌지 않았다.
- `BookmarkRegion`에 `parent` 필드가 생겼다. 최상위는 `None`이고 중첩 깊이는 제한하지 않는다.
- `remove_bookmark_region()`은 **중첩에 참여하는 region을 거부**한다. 자신이 `parent`를 갖거나
  다른 region의 `parent`이면 `removing a nested BOOKMARK region is unsupported`로 실패한다.

### 20.2 제거는 한때 잠겨 있었다 (S0-F에서 해제)

§19.3이 적었듯 S0-E는 nested 구조의 **제거 의미를 증명하지 않았다.** 그래서 resolve를 넓히면서도
`remove_bookmark_region()`은 중첩에 참여하는 region을 거부하도록 잠갔다 — 읽기를 넓혔다고 쓰기까지
따라 넓히면 증명되지 않은 변형을 조용히 수행하게 되기 때문이다.

**그 잠금은 §22(S0-F)에서 근거를 얻어 풀렸다.** 한글이 같은 범위를 지운 결과와 우리 제거가 문단·
marker 단위로 일치한다는 것이 확인됐다.

같은 이유로 `parent`가 표현하는 것은 **포함 관계뿐**이고 Slot·Option 같은 제품 의미는 아니다.
`hwpxcore`는 여전히 제품 의미를 모른다.

### 20.2-1 경계가 같은 문단에서 겹치는 중첩 (S0-G에서 해제)

이 절을 쓸 당시에는 full-paragraph 경계 규칙이 그대로 살아 있어, 안쪽 region이 바깥과 **같은
문단에서 시작하거나 끝나면** `partial-paragraph BOOKMARK begin/end is unsupported`로 거부됐다.
경계 marker 사이에 본문이 없어도 그랬다 — 검사가 이웃한 BOOKMARK `hp:ctrl`을 payload로 셌기
때문이다.

**§23(S0-G)에서 한글이 그 모양을 실제로 만든다는 것이 확인돼 규칙을 완화했다.** 아울러 그
완화가 제거 쪽에 만드는 위험도 §23.4에서 함께 막았다.

### 20.3 검증

- resolve: native `R5-nested.hwpx`가 3 region으로 resolve되고 `S0_OPT_A`·`S0_OPT_B`의 `parent`가
  `S0_SLOT`이다. 재저장본도 같은 topology를 낸다.
- 스택 pop: 앞 region이 닫힌 뒤 열리는 region은 형제로 잡힌다(자식으로 오인하지 않는다).
- 깊이 2 이상: `OUTER > MID > INNER` 합성 표본으로 부모 사슬을 확인한다.
- crossing: 기존 거부 표본이 그대로 실패한다.
- 제거: R5의 세 region 전부 거부되고, 형제 관계인 region은 기존대로 제거된다.
- owner `tests/test_bookmark_regions.py` + `tests/test_hwpx_structure_probe.py` 11 passed.

## 21. 후속 native 실험 후보

§20까지의 판정이 남긴 미검증 지점이고, 각각 한글 실물 표본이 먼저다.

| ID | 질문 | 상태 |
|---|---|---|
| S0-F | nested 구조에서 **제거**가 무엇을 남기는가 | **완료 — §22.** 제거 잠금 해제 |
| S0-G | 한글이 **경계가 겹치는 중첩**을 만드는가(§20.2-1) | **완료 — §23.** 경계 규칙 완화 |
| S0-H | 한글이 **crossing**을 허용하는가 | **완료 — §24.** 만들지 못한다. 거부 유지 |

세 후속이 모두 닫혔다. 남은 확장은 native 관찰이 아니라 제품 설계의 몫이다.

## 22. S0-F nested BOOKMARK 제거 native 관찰

### 22.1 방법과 표본

매번 원본 `R5-nested.hwpx`를 새로 복제해 한글 `12, 0, 0, 4547`에서 변형 하나만 수행하고 HWPX로
저장했다. 변형을 누적하지 않았다(S0-C와 같은 규율). 원본은 `tests/corpus/structural_range_s0/F/`에
보존했다. 기준 구조는 `S0_SLOT`이 p[1]~p[4](BBB~EEE), `S0_OPT_A`가 p[2](CCC), `S0_OPT_B`가
p[3](DDD)다.

| 파일 | 변형 | SHA-256 |
|---|---|---|
| `F1-delete-inner-paragraph.hwpx` | `CCC` 문단 삭제 = `S0_OPT_A` range 전체 | `35185E329D43237277E748092E526A4E5060A75EF16F7F6E4C098B059B213A5E` |
| `F2-delete-outer-range.hwpx` | `BBB`~`EEE` 삭제 = `S0_SLOT` range 전체 | `8E5558E676DA9884A2A4BE05CEC39037C0750B12EA4D30E5D2BFE1E09C3FD2E1` |
| `F3-delete-outer-start.hwpx` | `BBB` 문단만 삭제 = SLOT 시작 경계 | `7C2B2510871FA75AFCE398B3EB3CFAEA460C654A7FF2E4863924ECBBEC414809` |
| `F4-delete-outer-end.hwpx` | `EEE` 문단만 삭제 = SLOT 끝 경계 | `EBA0067E5DCD598C2C778A6DBC195852B304DE28EFE4540922BA0E499260CB33` |
| `F5-remove-inner-bookmark.hwpx` | 책갈피 `S0_OPT_A` 만 지우기(본문 유지) | `19CB956ED83E9F4B0429E42798293AE9CD90B581AFAF8F06C172A0A75DE72BD4` |
| `F6-remove-outer-bookmark.hwpx` | 책갈피 `S0_SLOT` 만 지우기(본문 유지) | `6CAEAE4B3D18AEAAC3C277C93B3A6CFB8FC0A738DB2593D469A92D88457D8C36` |

### 22.2 관찰

| ID | 남은 본문 | 남은 marker | 판정 |
|---|---|---|---|
| F1 | AAA·BBB·DDD·EEE | `S0_SLOT` p[1]~p[3], `S0_OPT_B` p[2] | 안쪽 하나가 사라지고 **바깥은 살아남되 extent가 줄었다**. 형제도 온전 |
| F2 | AAA | 없음 | 바깥 range 전체 삭제가 **안쪽 둘까지 함께** 없앴다 |
| F3 | AAA·CCC·DDD·EEE | `S0_OPT_A` p[1], `S0_OPT_B` p[2] | 시작 경계 문단 삭제가 **`S0_SLOT` pair 전체**를 지웠고, **안쪽 둘은 최상위로 승격** |
| F4 | AAA·BBB·CCC·DDD | `S0_OPT_A` p[2], `S0_OPT_B` p[3] | 끝 경계에서도 대칭으로 같은 결과 |
| F5 | 5문단 전부 | `S0_SLOT`, `S0_OPT_B` | 본문을 남기고 표식만 제거 가능. 나머지 둘 온전 |
| F6 | 5문단 전부 | `S0_OPT_A`, `S0_OPT_B` | 바깥 표식만 제거해도 **안쪽 identity가 살아 최상위로 승격** |

**여섯 경우 모두 orphan이 없다.** 짝 없는 `fieldBegin`이나 `fieldEnd`가 하나도 남지 않았다.
R2의 T4/T5에서 확인한 "한글은 경계 문단을 지울 때 pair 전체를 함께 지운다"가 중첩에서도 같고,
그때 **자식은 고아가 되지 않고 최상위 region이 된다**는 것이 새로 확인된 사실이다.

### 22.3 우리 구현과의 대조

`remove_bookmark_region()`이 하는 일은 region의 문단 shell 삭제다. 그 결과를 한글의 같은 범위
삭제와 대조했다.

| 우리 호출 | 한글 대응 | 문단 | marker | 남은 region |
|---|---|---|---|---|
| `remove(S0_OPT_A)` | F1 | 일치 | 일치 | `S0_SLOT`(1~3) + `S0_OPT_B`(2) |
| `remove(S0_SLOT)` | F2 | 일치 | 일치 | 없음 |

문단 텍스트 순서와 marker의 (문단, 종류, 이름) 순서가 모두 같다. `hp:p@id`와 layout은 한글이
따로 재계산하므로 byte 대조는 하지 않았다 — S0-D 계열과 같은 기준이다.

### 22.4 판정

- nested 구조에서 한글의 제거 결과: **orphan 없음**, PROVEN.
- 안쪽 제거 시 바깥 생존과 extent 축소: **PROVEN**(F1).
- 바깥 제거 시 안쪽 동반 삭제: **PROVEN**(F2).
- 경계 문단만 삭제할 때 자식의 최상위 승격: **PROVEN**(F3·F4·F6).
- 우리 문단-shell 삭제와 한글 결과의 일치: **PROVEN**, 위 두 방향에 한정.

따라서 §20.2의 제거 잠금을 **해제**한다. `remove_bookmark_region()`은 이제 중첩에 참여하는
region도 제거하며, **container를 제거하면 그 안의 region이 함께 사라진다**는 사실을 docstring에
명시한다. 한글이 같은 결과를 내므로 이것은 놀라운 동작이 아니라 native 의미와의 일치다.

### 22.5 이 판정이 포함하지 않는 것

- **표식만 제거하는 조작.** F5·F6이 보인 "본문을 남기고 책갈피만 지우기"는 우리 API에 없다.
  필요해지면 별도 primitive이며 이 판정이 그것을 승인하지 않는다.
- **경계 문단만 삭제하는 조작.** F3·F4도 우리 API가 제공하지 않는다. 다만 그 결과로 생긴
  "승격된 최상위 region" 상태는 resolve가 그대로 읽는다.
- 깊이 3 이상, 복수 Slot, crossing은 여전히 범위 밖이다.

### 22.6 검증

- owner `tests/test_bookmark_regions.py`: 제거 잠금 test를 native 대조 test로 **대체**했다.
  F1·F2 일치, 여섯 파일 전부의 orphan 부재, F3·F4·F6의 승격을 함께 고정한다.
- owner 7 passed. 정적 게이트와 인접 owner 114 passed.
- production 변경은 `remove_bookmark_region()`의 잠금 제거와 docstring뿐이다.

## 23. S0-G 경계가 겹치는 중첩 native 관찰

### 23.1 방법과 표본

`R0-plain.hwpx`(책갈피 없는 5문단)에서 매번 새로 시작해 바깥을 먼저, 안쪽을 나중에 만들었다.
한글 `12, 0, 0, 4547`. **세 경우 모두 한글이 거절하지 않았다.**

| 파일 | 구조 | SHA-256 |
|---|---|---|
| `G1-coincident-start.hwpx` | `S0_OPT_A`(p1~p4)와 `S0_SLOT`(p1)이 **같은 문단에서 시작** | `AFED1D94A2B53F29A3EC8DCD84D6ACB0A741BF50F40C2CA3E9D66BCBFFC45E7A` |
| `G1-resaved.hwpx` | G1 을 열어 `AAA`→`AAX` 만 고치고 저장 | `07D6CBA2364B2B17B9083348033114642F808F6F5340347022953EF0C4292A79` |
| `G2-coincident-end.hwpx` | `S0_SLOT`(p1~p4)와 `S0_OPT_B`(p4)가 **같은 문단에서 종료** | `1CB7772772CF9FAE0066315EC5B85EA680338349C3B0B24DB94D8C1452BF6153` |
| `G3-same-range.hwpx` | `S0_SLOT`과 `S0_OPT_X`가 **완전히 같은 범위**(p1~p4) | `20C83C8D66C490AE7BF544F750946912E8AF2808C6821B496EB7C025B485BEF6` |

**G1의 이름은 레시피 의도와 반대다.** 바깥이 `S0_OPT_A`(p1~p4), 안쪽이 `S0_SLOT`(p1)이다.
S0에서 bookmark name은 identity가 아니므로 구조 증거로서는 영향이 없으나, 이 파일을 인용할 때
이름으로 안팎을 판단하면 안 된다. G2·G3는 의도와 일치한다.

### 23.2 관찰한 wire 형상

경계가 겹치는 지점에서 한글은 두 marker를 **같은 run 안에 본문 없이 나란히** 쓴다.

```text
G1  p[1]  BEGIN S0_OPT_A | BEGIN S0_SLOT | TEXT 'BBB' | END→S0_SLOT | TEXT ''
    p[4]  TEXT 'EEE' | END→S0_OPT_A | TEXT ''

G3  p[1]  BEGIN S0_SLOT | BEGIN S0_OPT_X | TEXT 'BBB'
    p[4]  TEXT 'EEE' | END→S0_OPT_X | END→S0_SLOT | TEXT ''
```

G3에서 **두 region의 문단 범위가 (1,4)로 완전히 같다.** 문단 색인만으로는 어느 쪽이 바깥인지
결정할 수 없고, 오직 문서 순서가 그것을 정한다. `BookmarkRegion.parent`가 파생 정보가 아니라
**필요한 정보**라는 직접 증거다.

`G1-resaved`의 marker는 G1과 완전히 동일하다. 경계 겹침 중첩도 한글 open/save를 견딘다.

### 23.3 경계 규칙 완화

`_payload_outside_boundary()`가 이웃 marker를 본문으로 세던 것을 고쳤다. `hp:ctrl`이 **BOOKMARK
range marker만** 담고 있으면 payload로 세지 않는다(`_is_bookmark_boundary_ctrl`). 다른 필드의
pair가 끼어드는 경우는 기존 extent 검사가 계속 잡는다.

완화 뒤 네 표본이 모두 resolve되고 R2·R3·R4·R5의 기존 판정은 그대로다. 본문이 경계 옆에 있으면
여전히 `partial-paragraph`로 거부한다 — 면제 대상은 BOOKMARK marker뿐이다.

### 23.4 완화가 만든 제거 위험과 그 차단

읽기를 넓히자 제거 쪽에 새 위험이 생겼다. 경계를 공유하면 **안쪽을 지우는 것이 바깥의 marker를
함께 잘라낸다.** 실측으로 확인했다 — G1에서 안쪽 `S0_SLOT`(p1)을 지우면 p[1]에 있던
`S0_OPT_A`의 begin이 함께 사라지고 p[4]의 end만 남아 **orphan이 생겼다**.

그래서 `remove_bookmark_region()`에 가드를 넣었다. 지울 문단 범위가 **대상도 아니고 대상의
자손도 아닌** region의 marker를 건드리면 거부한다.

| 조작 | 결과 |
|---|---|
| G1·G2·G3의 **안쪽** 제거 | 거부 — `removing … would cut BOOKMARK markers outside it: …` |
| G1·G2·G3의 **바깥** 제거 | 성공, 남는 문단 `AAA`, orphan 0 |
| R5의 안쪽·바깥 제거(겹침 없음) | §22 판정 그대로 |

이것은 보수적 선택이 아니라 **손상 방지**다. 가드가 없으면 orphan을 만드는 경로가 실재한다.

### 23.5 판정

- 한글의 경계 겹침 중첩 생성: **PROVEN**(시작·끝·완전 동일 세 경우 모두).
- 재저장 보존: **PROVEN**(G1).
- 중첩된 두 region의 문단 범위 동일 가능성: **PROVEN**(G3) — 포함 판정은 문서 순서가 진다.
- 경계 규칙 완화: 적용. 면제는 BOOKMARK marker만.
- 겹친 경계에서 안쪽 제거: **거부**. 손상 없이 수행할 방법을 아직 모른다.

겹친 경계에서 안쪽만 제거하려면 문단 shell 삭제가 아니라 **marker만 제거하는 조작**이 필요하다.
그 조작은 §22.5가 적었듯 우리 API에 없고 F5·F6의 관찰이 그것을 승인하지도 않는다.

### 23.6 S1.6 후속 승격 (#633)

§23.4~23.5의 거부는 당시 문단-shell 구현의 계약이다. S1.6은 경계 문단에서 살아남아야 할
바깥 BOOKMARK marker와 그 조상 shell만 보존하는 제거를 추가해 G1·G2·G3의 안쪽 제거를
승격했다. 관계없는 marker를 자르는 범위, crossing, section 정의(`secPr`/`colPr`)를 지우는
범위는 계속 원자적으로 거부한다. 후보 XML을 직렬화·재해석해 남은 topology를 검증한 뒤에만
원본 entry를 한 번 교체한다.

같은 변경에서 최소 native pair 생성, 본문 보존 unwrap, ordered MetaTag replace/remove도 production
API로 승격했다. 생성은 기존 topology와 요청한 parent를 보존하며 pairing id 충돌을 피하고,
unwrap은 F5·F6의 한글 구조와 일치한다. Slot/Option id 해석은 core가 아니라 External adapter가
소유한다.

## 24. S0-H crossing native 관찰

### 24.1 방법과 표본

`R0-plain.hwpx`에서 시작해 서로 걸치는 두 책갈피를 지정했다. 한글 `12, 0, 0, 4547`.

```text
지정   S0_LEFT  = BBB 시작 ~ DDD 끝   (p1~p3)
       S0_RIGHT = CCC 시작 ~ EEE 끝   (p2~p4)
의도   LEFT begin > RIGHT begin > LEFT end > RIGHT end   = crossing
```

| 파일 | 변형 | SHA-256 |
|---|---|---|
| `H1-crossing.hwpx` | LEFT 먼저 생성 | `0493C6B9A8FAFEE9589C7E128D31C46A18D4E519A64E63CE50BC9B488EBC3B95` |
| `H1-resaved.hwpx` | H1 을 열어 `AAA`→`AAX` 만 고치고 저장 | `03B80FC1E2A931EE4FF9C37B3C46880FB20E1713A0BC825E40C3AE3E2723E3DC` |
| `H2-reverse-order.hwpx` | 같은 지정을 RIGHT 먼저 생성 | `B4689D03B27E8A36374129F350E7AAC0D452521A0F649201AC5E06368E039E81` |
| `H3-overlap-deleted.hwpx` | H1 에서 겹치던 `CCC`·`DDD` 삭제 | `DE8E2224E04E7B93642EC89BFEFC5996E978A7EF38215968E0F61EAD8E1E58A6` |

### 24.2 관찰 — crossing 은 저장되지 않는다

저장된 것은 crossing 이 아니라 **proper nesting** 이다.

| | 지정한 범위 | 저장된 범위 |
|---|---|---|
| `S0_LEFT` | BBB~DDD = p[1..3] | **p[1..4]** — EEE 를 삼켰다 |
| `S0_RIGHT` | CCC~EEE = p[2..4] | **p[2..3]** — EEE 를 내놓았다 |

바꾼 방식이 구체적이다. end marker 의 **물리적 위치는 순진하게** 찍혔다 — DDD 뒤(p[3])와 EEE
뒤(p[4]). 그대로 짝지으면 crossing 이 된다. 그런데 실제 XML 은 **짝을 뒤집었다**.

```xml
<hp:p><hp:run><hp:t>DDD</hp:t>
  <hp:ctrl><hp:fieldEnd beginIDRef="…800"/></hp:ctrl>   <!-- S0_RIGHT. LEFT 자리였다 -->
</hp:run></hp:p>
<hp:p><hp:run><hp:t>EEE</hp:t>
  <hp:ctrl><hp:fieldEnd beginIDRef="…799"/></hp:ctrl>   <!-- S0_LEFT. RIGHT 자리였다 -->
</hp:run></hp:p>
```

`beginIDRef` 를 바꿔 끼워 중첩이 되게 만들었고, 그 결과 **두 책갈피의 범위가 사용자 지정과
달라졌다.**

확정된 부수 사실:

- **생성 순서와 무관하다.** H2(RIGHT 먼저)도 결과가 같다. 항상 먼저 시작하는 쪽이 바깥이 된다.
- **재저장이 아니라 생성 시점의 일이다.** H1 과 H1-resaved 의 `section0`은 본문 수정과 layout 을
  빼면 완전히 동일하다.
- **경고 문구는 없었다.** 사용자가 UI 를 다시 확인해 범위를 정확히 지정했음을 확인했고, 어떤
  대화상자도 뜨지 않았다.
- H3 에서 겹치던 두 문단을 지우니 안쪽이 통째로 사라지고 바깥만 p[1..2]로 남았다. orphan 은
  여기서도 0 이다.

### 24.3 판정

- 한글이 crossing 을 저장하는가: **DISPROVEN**. 지정해도 nesting 으로 정규화된다.
- 정규화가 사용자 지정 범위를 바꾸는가: **PROVEN**, 그리고 **조용하다**.
- 우리 `crossing BOOKMARK regions are unsupported` 거부: **유지**. 완화 근거가 없을 뿐 아니라
  완화할 대상 자체가 native 로는 생기지 않는다. 남는 발생원은 깨진 도구가 만든 파일뿐이고
  그것은 계속 시끄럽게 거부하는 것이 맞다.

### 24.4 제품 설계에 남기는 함의

이 관찰의 값어치는 resolver 가 아니라 **저작 표면**에 있다. 사용자가 겹치는 범위를 지정하면
한글은 묻지도 알리지도 않고 범위를 고쳐 저장한다. Slot 저작이 한글 UI 를 경유하는 한, 사용자가
의도한 것과 다른 Slot 구조가 저장될 수 있다.

이 저장소의 confirm-or-alarm 원칙은 우리 코드에 적용되는 것이지 한글을 바꿀 수는 없다. 대신
**우리가 읽을 때 그 차이를 드러낼 수 있다** — 저작 의도를 따로 기록해 두면(예: MetaTag 의 Slot
descriptor) 저장된 구조와 대조해 "한글이 범위를 바꿨다"를 사용자에게 알릴 수 있다. S1 이 증명한
carrier 가 그 자리에 쓰일 수 있다는 뜻이며, 구체 설계는 이 문서 밖이다.

### 24.5 검증

- owner `tests/test_bookmark_regions.py` 에 S0-H test 1건 추가(8 → 9 passed). H1·H1-resaved·H2 가
  같은 nesting 으로 resolve 되는 것, H3 의 결과, 네 파일 전부의 orphan 부재를 고정한다.
- production 변경 없음. crossing 거부 경로는 그대로이고 합성 표본이 계속 그것을 지킨다.
