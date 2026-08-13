# HWPX native MetaTag S1 spike 관찰 기록

> **문서 상태:** 유효 결정 (판정 **PASS-A (semantic)** — §12.1 의 편차 기재를 함께 읽는다)
> **권위 범위:** 한컴 native metadata carrier 의 wire format 관찰과 보존성 실험 설계
> **후속 정본:** 우리 코드의 동작은 `tests/_hwpx_metatag_spike.py` 와 `tests/test_metatag_s1.py`,
> 구조 범위 primitive 는 `docs/HWPX_STRUCTURAL_RANGE_S0.md`
> **편집 정책:** 새 native evidence(특히 한글 open/save 결과)가 생길 때만 판정과 근거를 함께 갱신

## 1. 목적과 비목표

질문은 하나다. **한컴이 실제로 생성·보존하는 HWPX MetaTag 의 wire format 은 무엇이며,
hwpx-filler 가 넣은 opaque payload 가 한글 open/save 뒤에도 살아남는가.**

Slot Product Domain, 선택 UI, TXT syntax, 최종 schema·naming·versioning 은 이 spike 의 비목표다.
`hwpxcore` 에 production API 를 추가하지 않았고 제품 코드는 한 줄도 바꾸지 않았다. 실험은
`tests/` 안의 spike helper·fixture·owner test 로만 국소화했다.

## 2. 전제 (S0 에서 이미 증명된 것)

- native block BOOKMARK 는 `fieldBegin type="BOOKMARK"` / `fieldEnd@beginIDRef` 범위다.
- `hp:bookmark` 는 이름만 가진 point marker 다.
- `hp:p@id` 와 `fieldid` 는 identity 로 쓸 수 없다.
- 제약된 resolve/remove 는 `hwpxcore.bookmark_region` 이 production 으로 소유한다.
- 프로그램이 생성한 최소 BOOKMARK 를 한글이 인식하고 재저장해도 pair/extent 가 보존된다(S0-D6).

BOOKMARK 범위 자체의 correctness 는 이 spike 에서 재발명하지 않고 기존 primitive 를 그대로 썼다.

## 3. 실험 환경

- 저장소 HEAD `75db8b4`, 브랜치 `codex/hwpx-bookmark-region`
- 관찰 대상 corpus: `tests/corpus/**` 의 tracked HWPX 전량, 특히 S0 native corpus
  (`version.xml` = Hancom Office Hangul `12, 0, 0, 4426 WIN32LEWindows_10`)
- 공식 source: `hancom-io/hwpx-owpml-model` @ `1453388472c703a4b299a0834f425cdac16644b9`,
  `hancom-io/metatag-ex` @ `7c5e09ee1d7dd318f79a7ea1ec307b9841ee47db` (둘 다 shallow clone 후 grep)
- 설치본 문자열 자원: `Hancom Office 2022` 의 `Bin/Hwp.String.{ko-KR,en-US}.dll`
- 한글 실행 표본(M·G 계열): 한/글 `12, 0, 0, 4547 WIN32LEWindows_10`
- **한글 프로그램·COM 자동화는 사용하지 않았다.** open/save 는 전부 사람이 GUI 로 수행했고,
  절차는 §10, 결과는 §7·§9 다. 자동화한 것은 관찰·생성·대조뿐이다.

## 4. 관찰 — 한컴이 정의한 wire format

### 4.1 carrier 는 하나가 아니라 셋이고, 철자가 다르다

| carrier | wire 표기 | 값의 자리 | 공식 model 근거 |
|---|---|---|---|
| object/document metaTag **element** | `hp:metaTag`, `hh:metaTag` (camel) | **element text** | `OWPML/Class/Para/MetaTag.cpp` |
| ParaListType **attribute** | `metatag` (전부 소문자) | attribute value | `OWPML/Class/Para/ParaListType.cpp` L80·L99 |
| (모델 밖) fieldBegin **attribute** | `metaTag` (camel) | attribute value | 공식 model 에 **없음**. corpus 에만 있음 |

`CMetaTag` 는 `CStringValueObject` 를 상속해 값 하나를 문자열로만 갖는다. 자체 attribute 도
child 도 없고(`InitMap` 이 비어 있고 `ReadAttribute` 가 no-op), element 이름은 클래스가 아니라
**부모의 child map** 이 정한다. 그래서 같은 클래스가 `hp:` 와 `hh:` 두 이름으로 직렬화된다.

`metatag` 소문자 attribute 를 선언하는 클래스는 저장소 전체에서 `CParaListType` 하나뿐이고,
그 클래스가 wire 에 나오는 이름은 `subList` 뿐이다. 즉 **`<hp:subList metatag="…">` 형태로만**
존재한다. `PType`(`hp:p`)에는 attribute·child 어느 쪽도 없다.

### 4.2 element 를 받는 부모 (공식 child map)

`hh:metaTag` 는 `hh:head`(= `Contents/header.xml` 루트) 한 곳이다. 이것이 **문서 수준 carrier** 다.

`hp:metaTag` 는 24개 부모가 받는다. 그중 이 spike 에 직접 관련된 것:
`fieldBegin`, `tbl`, `secPr`, `pic`, `rect`, `container`, `ellipse`, `line`, `chart`, `equation`,
`ole`, `video`, `textart`, `unknownObject` 등 개체 계열 전부.

`Contents/content.hpf` 의 `opf:metadata` 는 `title/language/identifier/meta` 만 받고 metaTag 는
없다. **패키지 수준에는 metaTag 가 없다.**

### 4.3 escape 규칙

element text 경로(`ConvertInvalidStr(isValue=true)`)는 `&`, `<`, `>` 만 치환하고 `"` 와 `'` 는
그대로 둔다. attribute 경로는 여기에 `"` → `&quot;` 를 더한다. 양쪽 모두 C0 제어문자와
`U+FFFE`/`U+FFFF` 는 공백 한 칸으로 바꾼다. 앞뒤 공백이 있으면 `xml:space="preserve"` 를 붙인다.

**공개 source 에는 길이 제한·문자 제한·유일성 강제가 없다.** 저장은 무한 길이 `wstring` 이고
metatag-ex 는 같은 tag 이름이 여러 개체에 붙는 것을 `multimap` 으로 **정상 취급**한다. XSD·RNG·DTD
같은 선언적 schema 도 두 저장소에 없다. 그러나 §4.6 이 보이듯 **출하 제품은 UI 층에서 별도로 강제한다.**

### 4.4 payload 는 opaque string 이지만 한컴에는 사실상의 관례가 있다

`HwpMetatagDef.h` 는 파일 전체가 `#define METATAGDEF_NAME L"name"` 한 줄이고,
`Object.cpp` 에 주석 처리된 `IsMetaTagVaild` 는 `name` 멤버의 존재를 검사한다. metatag-ex 는
저장된 문자열에서 **첫 `#` 부터 마지막 `"` 까지**를 잘라 tag 이름으로 쓴다.

세 지점을 합치면 관례는 `{"name":"#태그명"}` 형태의 JSON 문자열이다. 이 절을 쓸 당시에는
**추론**이었다 — 어느 문서에도 명시돼 있지 않고 참조 fixture 도 없었다. **§7 에서 한컴이 직접
생성한 실물로 확정됐다.**

이 slice 규칙에는 직접적인 설계 함의가 있다. payload 를 확장할 때 `name` 을 **마지막에** 두고
`#` 을 `name` 값 안에서만 쓰면, 한컴 자신의 도구가 잘라도 여전히 맨 tag 이름이 나온다. 이
성질은 `tests/test_metatag_s1.py` 가 단언으로 고정한다.

### 4.5 corpus 관찰 — 모델과 어긋나는 한 지점

tracked HWPX 전량에서:

| 관찰 | 수 |
|---|---|
| `metaTag`/`metatag` **element** | **0** |
| `metaTag` **attribute** (`hp:fieldBegin` 위, 값은 전부 빈 문자열) | 165 |
| 그 밖의 owner | 0 |

즉 한글 12.0.0.4426 이 저장한 실물에는 `<hp:fieldBegin … metaTag="">` 가 있는데, 공식 OWPML
모델에는 그 attribute 가 **없다**. 확정 사실은 여기까지다. 아래는 추론이다.

- (추론) 출하 한글 writer 가 공개 filter model 이 모르는 attribute 를 쓰거나, 더 새 format
  revision 이다. source 로는 어느 쪽인지 가릴 수 없다.
- (확정) `CObject::ReadAttribute` 는 클래스가 명시하지 않은 attribute 를 저장하지 않고
  `WriteElement` 는 명시한 것만 다시 쓴다. unknown **element** 보존 경로(`CAnyElement`)는 있지만
  unknown **attribute** 보존 경로는 없다. 따라서 **OWPML 기반 도구를 거치면 이 attribute 는
  읽기에서도 쓰기에서도 사라진다.**

이 하나 때문에 "MetaTag" 를 단일 carrier 로 가정하면 안 된다. 이 spike 가 세 파일을 만드는 이유다.

**§7 가 이 어긋남을 해소했다** — 한글은 element carrier 에 태그를 쓰면서도 이 camel attribute 는
계속 비워 둔다. 즉 쓰이지 않는 잔재이며 우리 payload 의 자리가 아니다.

### 4.6 출하 한글이 강제하는 제약 (설치본 문자열 자원)

설치된 `Hancom Office 2022`(한글 12.0.0.4426)의 `Bin/Hwp.String.ko-KR.dll` 과
`Bin/Hwp.String.en-US.dll` 에서 확정한 사실이다. 문자열 ID 표는
`IDS_MetaTag`, `IDS_MetaTagDlg`, `IDS_MetaTagDlg_Modify/delete(_DOC/_MSG)`, `IDS_MetaTag_Cell`,
`IDS_MetaTag_Document`, `IDS_MetaTagNameInput`, `IDS_MetaTagNoSharp`, `IDS_MetaTagNoChar`,
`IDS_MetaTagoverlap`, `IDS_MetaTagMaxSize`, `IDS_MetaTaghas`, `IDS_NOLIST_WS_METATAG` 16개다.

| 확정 사실 | 근거 문자열 |
|---|---|
| 한국어 UI 용어는 **「메타태그」가 아니라 「태그」** | `메타태그` 는 ko-KR 자원에 0회. 대조군 `책갈피` 는 82회 |
| 명령은 **태그 넣기 / 태그 고치기 / 태그 지우기**, 목록 제목은 **태그 이름** | `태그 넣기`, `태그 고치기`, `태그 지우기`, `태그 이름` |
| 저장된 tag 이름은 **항상 `#` 로 시작한다** — 검증이 아니라 **자동 정규화**다(§7.3) | "태그 이름은 '#'로 시작해야 합니다." |
| **2,083자 상한** | "태그 이름은 2,083자를 초과할 수 없습니다." |
| **중복 지정 불가** | "태그는 중복하여 설정할 수 없습니다.", "태그 이름이 이미 입력되어 있습니다. 태그 이름을 변경할까요?" |
| **셀 수준·문서 수준 지정이 따로 있다** | `IDS_MetaTag_Cell`, `IDS_MetaTag_Document`, `…_Modify_DOC`, `…_delete_DOC` |
| **저장 형식에 따라 태그가 전부 삭제된다** | "이 파일을 현재 선택한 파일 형식으로 저장하면 모든 태그 정보가 삭제됩니다." |

마지막 항목은 실험 절차의 제약이다 — **HWPX 로만 저장해야 한다.** `.hwp` 등으로 저장하면 태그가
사라지고, 그 소실은 carrier 의 결함이 아니라 형식 선택의 결과다.

`#` 강제와 2,083자 상한은 §4.4 의 `{"name":"#태그명"}` 형태와 정확히 맞물린다(§7 에서 확정). 현재 probe 의
payload 는 715~752자라 상한 아래에 있으므로, 소실이 관찰되더라도 길이 때문은 아니다.

### 4.7 공식 도움말이 정의한 UI 경로와 대상 (한/글 2022)

정본: [한/글 2022 도움말 「태그 이름」](https://help.hancom.com/hoffice120/ko-KR/Hwp/view/workwindow/workwindow(tag).htm).
**리본 명령이 아니다.** 경로는 셋뿐이다.

- 개체: 개체를 **마우스 오른쪽 단추** → 빠른 메뉴 **[태그 넣기]**
- 문서 전체: **[파일 - 문서 정보]** → 대화 상자의 **[태그 넣기]**
- 확인·관리: **[보기 - 작업 창 - 태그 이름]**

도움말이 열거한 대상과 유형은 다음과 같고, **그 「유형」 열이 §4.1 의 carrier 삼분과 그대로
대응한다.** 이 예상은 §7 의 M1 실물에서 **전건 확인됐다**.

| 도움말의 유형 | 대상 | 대응 예상 carrier |
|---|---|---|
| 컨트롤 | 누름틀, 표, 그림, 도형, 하이퍼링크, 교정 부호, 상호 참조, 계산식 | `hp:metaTag` **child element** |
| 목록 | 글상자, **셀** | `hp:subList@metatag` **소문자 attribute** |
| 문서 | 문서 정보 | `hh:metaTag` (`header.xml`) |

이름 규칙도 도움말이 명시한다 — 「해시 기호(#) 다음에 **공백 없이** 한 글자 이상」이며 공백을
넣으면 태그로 인식되지 않는다. 그리고 **hwpx·hwtx 에서만 지원되고 hwp·hwt 로 저장하면 모든
태그가 손실된다**(§4.6 의 경고 문자열과 같은 내용).

이 기능은 한/글 2020 에도 있었고, 2024 는 개체를 넘어 **본문 영역**에도 태그를 허용한다
(Hancom FAQ 2846). 2024 의 본문 태그 동작을 2022 에 적용하지 않는다.

HwpCtrl COM 에도 `SetCurMetatagName` / `GetMetatagList` / `RenameMetatag` 등 대응 메서드가 있으나
이 저장소는 COM 자동화를 쓰지 않으므로 기록만 남긴다.

## 5. 후보 저장 위치 평가

| # | 후보 | 모델 근거 | 이 spike 의 probe |
|---|---|---|---|
| 1 | BOOKMARK 자체(`fieldBegin@name`) | name 만 있음 | 사용 안 함. 이름에 의미를 인코딩하지 않는다 |
| 2 | BOOKMARK 인접 native control | — | 사용 안 함. 인접성은 편집에 취약(S0 T1·T7) |
| 3 | object-level `hp:metaTag` **child** (fieldBegin/tbl) | 공식 child map | **G1**, **G2** |
| 4 | `hp:subList@metatag` 소문자 attribute | 공식 attribute | **G2** |
| 5 | document-level `hh:metaTag` (`header.xml`) | 공식 child map | **G1** |
| 6 | 그 밖의 package carrier(`opf:meta`, package-local entry) | OWPML 밖 | **G3** |
| 7 | (모델 밖) `hp:fieldBegin@metaTag` camel attribute | corpus 에만 있음 | **G2** |

**object-local 이 가능한가 / document-level catalog 가 더 자연스러운가**는 미리 정하지 않았다.
G1 이 둘을 같은 파일에 함께 넣어 한 번의 round-trip 으로 두 답을 동시에 받게 했다.

## 6. 생성한 probe fixture

세 파일 모두 한글이 저장한 S0 native corpus 를 입력으로 삼고, 각 파일이 **하나의 carrier 군**만
건드린다. 한 파일이 열리지 않아도 나머지 증거가 함께 죽지 않게 하려는 분리다.

| 파일 | 입력 | 넣은 carrier | SHA-256 |
|---|---|---|---|
| `G1-element-carriers.hwpx` | `R0-plain.hwpx` | BOOKMARK 3개의 `hp:metaTag` child + `hh:metaTag` 문서 catalog | `26967F868B2CDDD022F9264941D4AFFA50276FC91B10527C9EC8B52DE9B54EF0` |
| `G2-attribute-carriers.hwpx` | `R3-table-crossing.hwpx` | `fieldBegin@metaTag`(camel) + `tbl` 의 `hp:metaTag` child + `subList@metatag`(소문자) | `328DB9796ACEA99B52DC932062F6987822350239313C030734D494CA904D3CEB` |
| `G3-package-carriers.hwpx` | `R0-plain.hwpx` | `opf:meta[@name=hwpxFiller:s1probe]` + 선언한 package entry 1 + 선언 안 한 package entry 1 | `3E216B4E4EF0FF1CD6081B07A705839E27A7838E722D5FFA48C16AB2415F4685` |

재생성 명령은 결정적이다.

```powershell
uv run python tests/_hwpx_metatag_spike.py build-element   tests/corpus/structural_range_s0/R0-plain.hwpx          tests/corpus/metatag_s1/G1-element-carriers.hwpx
uv run python tests/_hwpx_metatag_spike.py build-attribute tests/corpus/structural_range_s0/R3-table-crossing.hwpx tests/corpus/metatag_s1/G2-attribute-carriers.hwpx
uv run python tests/_hwpx_metatag_spike.py build-package   tests/corpus/structural_range_s0/R0-plain.hwpx          tests/corpus/metatag_s1/G3-package-carriers.hwpx
uv run python tests/_hwpx_metatag_spike.py dump FILE.hwpx
```

### 6.1 G1 이 실제로 쓴 XML

```xml
<hp:ctrl><hp:fieldBegin id="1700000001" type="BOOKMARK" name="HF_S1_ANCHOR">
  <hp:metaTag>{"hwpxFiller": {"v": 1, "label": "추가 지급 안내",
    "quoted": "he said \"yes\" &amp; &lt;no&gt;", "uuid": "…", "spaced": "  …  ",
    "long": "가"×512, "anchor": "HF_S1_ANCHOR"}, "name": "#hf_s1_anchor"}</hp:metaTag>
</hp:fieldBegin></hp:ctrl>
```

```xml
<hh:trackchageConfig flags="56"/>
<hh:metaTag>{"hwpxFiller": {"v": 1, "slots": [{"id": "extra_notice",
  "label": "추가 지급 안내", "cardinality": "exactly_one", "min_options": 2,
  "anchor": "HF_S1_ANCHOR", "options": [{"id": "bonus", "anchor": "HF_S1_OPT_BONUS"},
  {"id": "special", "anchor": "HF_S1_OPT_SPECIAL"}]}]}, "name": "#hf_s1_catalog"}</hh:metaTag>
```

payload 는 §4.4 의 한컴 관례를 **깨지 않고 확장**한 형태다(case C). `name` 이 마지막이고 `#` 은
그 값에만 있다. 실제 escape 결과도 §4.3 규칙과 일치한다 — element text 에서 `&`·`<`·`>` 만
치환되고 `"` 는 JSON escape(`\"`)로만 남았다.

### 6.2 §4 결합 실험 — BOOKMARK identity 를 metadata 가 참조한다

G1 은 R0 의 BBB/CCC/DDD 에 서로 겹치지 않는 native BOOKMARK 세 개를 만든다
(`HF_S1_ANCHOR`, `HF_S1_OPT_BONUS`, `HF_S1_OPT_SPECIAL`). 문서 catalog 는 그 세 이름을 참조해
아래 논리 구조를 표현한다.

```text
Slot  id=extra_notice  label=추가 지급 안내  cardinality=exactly_one  min_options=2
  options  bonus   → HF_S1_OPT_BONUS
           special → HF_S1_OPT_SPECIAL
```

세 region 은 `resolve_bookmark_regions()` 로 그대로 resolve 되고, catalog 의 anchor 이름 집합이
resolve 된 region 이름 집합과 일치하는지를 owner test 가 단언한다. 겹침·중첩이 없어 기존
production 계약 안에 머문다.

## 7. 결과 — 한컴이 직접 생성한 MetaTag (M 계열, 우선순위 1 증거)

사용자가 §10.1 절차대로 한/글 `12, 0, 0, 4547 WIN32LEWindows_10` 에서 만든
`M1-hancom-authored.hwpx` 를 `tests/corpus/metatag_s1/` 에 원본 그대로 보존했다. 5문단 본문 +
표 1 + 도형(polygon) 1 + 누름틀 1 에 태그 5개를 지정한 문서다. `metatag_carriers()` 관찰 결과:

| 지정 대상 | 실제 저장 위치 | 값 |
|---|---|---|
| 문서 전체 | `Contents/header.xml` → `hh:head/hh:metaTag` **element text** | `{"name":"#hf_test_doc"}` |
| 표 | `hp:tbl/hp:metaTag` **element text** | `{"name":"#hf_test_table"}` |
| 누름틀 | `hp:ctrl/hp:fieldBegin/hp:metaTag` **element text** | `{"name":"#hf_test_field"}` |
| 도형 | `hp:polygon/hp:metaTag` **element text** | `{"name":"#hf_test_shape"}` |
| **셀** | `hp:tbl/tr/tc/hp:subList@metatag` **소문자 attribute** | `{"name":"#hf_test_cell"}` |

**§4.7 의 「컨트롤 / 목록 / 문서」 유형 ↔ carrier 대응 예상은 전건 확인됐다.** 추론이던 것이
관찰이 됐다.

두 가지가 더 확정됐다.

- **payload 는 정확히 `{"name":"#태그명"}` 이다.** §4.4 에서 코드 세 곳으로 추론했던 형태가
  실물과 일치한다. 저자는 이렇게 갈린다.
  - 사용자가 대화 상자에 입력한 것: 태그 이름(`hf_test_field`).
  - 한글이 만든 것: `{"name": … }` **JSON 껍데기**, 공백 없는 compact 직렬화, 그리고 **`#` 접두**.

  `#` 는 §7.3 이 보이듯 한글이 보장한다. 다만 **우리는 대화 상자를 거치지 않고 XML 을 직접
  쓰므로 그 보장 밖에 있다** — `#` 를 우리가 넣지 않으면 아무도 넣어 주지 않는다. 현재 probe 는
  `"name": "#hf_s1_anchor"` 처럼 직접 넣어 이 조건을 만족한다.

  여기서 미확정 질문이 하나 남는다 — **껍데기의 저자가 한글의 대화 상자라면, 우리가 껍데기 안에
  넣은 여분 property 를 「태그 고치기」가 다시 쓸 때 지우는가?** G 계열이 답할 대상이다.
- **`hp:fieldBegin@metaTag`(camel attribute)는 child element 와 공존하되 비어 있다.** 같은
  누름틀에 element 로 태그가 들어간 상태에서도 attribute 는 `""` 였다. §4.5 의 어긋남은
  "한글이 attribute 를 쓴다"가 아니라 **"한글이 이 attribute 를 늘 비워 둔다"** 로 해소된다.
  실 carrier 는 child element 이고 camel attribute 는 사용되지 않는 잔재다.

### 7.1 case A — 편집 후 재저장 baseline

`M1-resaved.hwpx`(본문 `AAA`→`AAX` 한 곳만 수정 후 저장)와 M1 을 carrier 단위로 비교하면
**`content.hpf` 의 `ModifiedDate` 를 뺀 전 carrier 가 문자 단위로 동일**하다. 태그 5개 전부
값·위치·carrier 종류가 보존됐다.

### 7.2 case B — 태그 이름 변경

`M2-renamed.hwpx`(「태그 고치기」로 누름틀 태그만 `#hf_test_field`→`#hf_slot_test`)에서
바뀐 carrier 는 **정확히 그 하나뿐**이고 값은 `{"name":"#hf_slot_test"}` 다. 나머지 4개는
무손실이다. 이름 변경이 다른 태그를 오염시키지 않는다.

### 7.3 `#` 접두는 한글이 보장한다 (M3)

`M3-no-sharp.hwpx` 는 같은 문서에서 **태그 이름을 `#` 없이 입력해** 저장한 것이다. 저장 결과의
태그 5개는 M1 과 문자 단위로 동일했고(`header.xml` 은 아예 byte 동일), section0 의 유일한 차이는
도형 `lineShape` 에 `endCap="FLAT"` 이 붙은 무관한 정규화였다.

파일만으로는 「거부됐다」와 「자동으로 붙었다」를 가를 수 없었다. **사용자가 UI 를 다시 관찰해
확정한 결과는 후자다** — `#` 없이 저장해도 한글이 붙이고, 「태그 고치기」로 다시 열면 `#` 가
붙은 상태로 나온다.

이 대목은 계측 교훈이기도 하다. §4.6 에서 오류 문자열 `IDS_MetaTagNoSharp` 의 **존재**로
「UI 가 거부한다」를 유도했는데 그것은 틀렸다. **문자열 자원이 있다는 것은 그 경로가 실제로
발화한다는 증거가 아니다.** 선언은 살아 있고 결과는 다를 수 있다.

따라서 불변식은 이렇게 적어야 한다 — **UI 를 통해 저장된 태그 이름은 항상 `#` 로 시작한다.**
그 이유는 검증이 아니라 정규화다.

### 7.4 판정

- 한컴 native MetaTag 의 wire format: **확정**(추론 아님).
- 한글 자신이 만든 태그의 open/save 보존: **PASS**.
- 태그 이름 변경의 국소성: **PASS**.
- 이 판정은 한/글 12.0.0.4547 과 위 5개 대상에 한정한다. **우리가 만든 payload 의 보존성은
  이 결과가 증명하지 않는다** — M 계열은 전부 한글이 스스로 쓴 값이다.

## 8. 결과 — 우리 round-trip (claim A)

`tests/test_metatag_s1.py` 4건이 고정한 것:

| 확인 항목 | 결과 |
|---|---|
| 세 carrier 모양(element text / camel attr / 소문자 attr) 모두에 payload 기록 | PASS |
| ASCII·한글·UUID·앞뒤 공백·따옴표·`&`·`<`·`>`·512자 문자열 보존 | PASS |
| `to_bytes()` → `from_bytes()` 뒤 carrier 값 전부 동일 | PASS |
| 같은 입력 재생성 시 byte 동일(결정성) | PASS |
| 기존 non-empty carrier 값 무변경 | PASS |
| BOOKMARK 3 region resolve + catalog anchor 대조 | PASS |
| metatag-ex slice(첫 `#` ~ 마지막 `"`)가 여전히 맨 tag 이름을 낸다 | PASS |
| 선언/미선언 package entry 동시 추가 | PASS |

**이것은 claim A 일 뿐이다.** 한글이 이 payload 를 어떻게 다루는지는 여기서 아무것도 증명하지
않는다.

## 9. 결과 — 우리가 만든 payload 의 한글 보존성 (G 계열, claim B·C)

사용자가 §10.2 절차대로 G1~G3 을 한/글 12.0.0.4547 에서 열고 본문 한 곳을 고쳐 저장한
`G1-resaved.hwpx`·`G2-resaved.hwpx`·`G3-resaved.hwpx` 를 보존했다. **세 파일 모두 경고 없이
열렸다**(claim B: PASS).

### 9.1 carrier 별 판정

| carrier | 판정 | 관찰 |
|---|---|---|
| `hp:metaTag` child element (BOOKMARK fieldBegin ×3) | **보존** | JSON 의미 동등, `hwpxFiller` 미지 property 온전 |
| `hp:metaTag` child element (`tbl`) | **보존** | 동일 |
| `hh:metaTag` (`header.xml` 문서 catalog) | **보존** | slot·option 구조 전체 온전 |
| `hp:subList@metatag` 소문자 attribute (셀) | **보존** | 동일 |
| `hp:fieldBegin@metaTag` camel attribute | **소실** | 720자 payload → `""`. 값만 지워지고 attribute 는 남음 |
| `opf:meta[@name=hwpxFiller:s1probe]` | **소실** | element 자체가 제거됨 |
| package entry (manifest 선언함) | **소실** | ZIP 에서 제거 |
| package entry (manifest 미선언) | **소실** | ZIP 에서 제거 |

**모델이 아는 carrier 는 전부 살고, 모델 밖은 전부 죽는다.** 예외가 없다. 세는 단위를 분명히
하면 — 살아남은 **wire 형태는 3종**(`hp:metaTag` element / `hh:metaTag` element /
`subList@metatag` attribute)이고, 그 위에 실린 **payload 실체는 6개**다. owner test 의
`survived` 집합이 그 6개를 열거한다.

§4.5 에서 OWPML 소스로 세운 추론 — unknown element 보존 경로는 있고 unknown attribute 보존 경로는 없다 — 이
실물에서 그대로 확인됐다. 선언한 package entry 조차 살아남지 못한 것은 한글이 자기가 아는 part
집합만 다시 쓴다는 뜻이다.

### 9.2 보존의 정확한 의미 — 정규화는 있고 손실은 없다

살아남은 payload 6개(`hh:metaTag` 1 + BOOKMARK `fieldBegin` 의 `hp:metaTag` 3 + `tbl` 의
`hp:metaTag` 1 + 셀 `subList@metatag` 1)는 **byte 동일이 아니다.** 한글이 JSON 을 자기 방식으로 다시 쓴다.

```text
before  {"hwpxFiller": {"v": 1, "label": "추가 지급 안내", …}, "name": "#hf_s1_anchor"}   742자
after   {"hwpxFiller":{"v":1,"label":"추가 지급 안내",…},"name":"#hf_s1_anchor"}          726자
```

차이는 `": "`→`":"`, `", "`→`","` 뿐이다. 실제로 `json.dumps(…, separators=(",", ":"))` 와
byte 단위로 일치한다. 그리고 다음이 전부 보존됐다.

- **미지 property `hwpxFiller` 전체** — 한글이 모르는 이름인데 지우지 않았다.
- **key 순서** — `name` 이 여전히 마지막이라 §4.4 의 metatag-ex slice 안전성이 유지된다.
- 값 문자열 — 한글, `"` 와 `&`·`<`·`>`, 앞뒤 공백 2칸, 512자 문자열, UUID, `#` 접두.

따라서 **동등성 판정은 byte 가 아니라 JSON 파싱 결과로 해야 한다.** 이것이 이 spike 가 낸
가장 실무적인 제약이다. payload 를 서명하거나 해시로 봉인하는 설계는 그대로는 쓸 수 없다 —
한글이 재직렬화하는 순간 해시가 깨진다.

### 9.3 BOOKMARK 결합의 왕복 복원

`G1-resaved.hwpx` 에서 §6.2 의 논리 구조가 **전건 복원**됐다.

| 복원 대상 | 결과 |
|---|---|
| 세 native BOOKMARK region resolve | `HF_S1_ANCHOR`(1,1)·`HF_S1_OPT_BONUS`(2,2)·`HF_S1_OPT_SPECIAL`(3,3) |
| Slot identity·label | `extra_notice` / `추가 지급 안내` |
| cardinality·min_options | `exactly_one` / `2` |
| option identity | `bonus`·`special` |
| option ↔ BOOKMARK region 관계 | 두 anchor 이름이 모두 resolve 된 region 과 일치 |
| 개체 payload 의 anchor 집합 | resolve 된 region 집합과 동일 |

한글은 우리가 만든 BOOKMARK 를 S0-D6 과 같은 방식으로 정규화했다 — `editable`·`dirty`·`zorder`·
`fieldid`·빈 `metaTag` attribute 와 `parameters` child 를 보충했다. **그러면서 우리 `hp:metaTag`
child 는 형제로 그대로 두었다.** 정규화가 미지 child 를 밀어내지 않는다는 직접 증거다.

## 10. 한글 open/save 절차 (M·G 계열 모두 완료 — 재현용 기록)

한글 GUI 자동화는 이 저장소의 규율상 쓰지 않는다(제품이 HWP 프로그램·COM 에 의존하지 않는다).
S0 native corpus 와 D6 재저장본이 그랬듯 이 단계는 사람이 수행한다. 파일을 압축 해제하거나 XML 을
편집하지 않는다.

### 10.1 M 계열 — 한컴이 직접 생성한 MetaTag (**완료**, 결과는 §7)

UI 명령 이름은 **「태그 넣기」** 이고 리본에 없다(§4.7). 새 문서를 S0 와 같은 5문단
`AAA`~`BBB`~`CCC`~`DDD`~`EEE` 로 만들고 표 1개, 그림 1개, 누름틀 1개를 넣은 뒤 지정한다.
이름은 `#` 다음에 공백 없이 이어 써야 하고 서로 중복되면 안 된다.

| 태그 | 대상 | 경로 |
|---|---|---|
| `#hf_test_field` | 누름틀 | 개체 오른쪽 단추 → [태그 넣기] |
| `#hf_test_table` | 표 (표 테두리 선택) | 개체 오른쪽 단추 → [태그 넣기] |
| `#hf_test_cell` | 표 안의 셀 하나 | 셀 선택 후 오른쪽 단추 → [태그 넣기] |
| `#hf_test_shape` | 그림 또는 도형 | 개체 오른쪽 단추 → [태그 넣기] |
| `#hf_test_doc` | 문서 전체 | **[파일 - 문서 정보]** → [태그 넣기] |

지정 결과는 **[보기 - 작업 창 - 태그 이름]** 목록으로 확인한다.

**HWPX 형식으로만 저장한다.** 다른 형식으로 저장하면 제품이 태그를 전부 지운다.
저장본은 `tests/corpus/metatag_s1/M1-hancom-authored.hwpx` 로 보존한다. 실제 수행본은
`M1-hancom-authored.hwpx`·`M1-resaved.hwpx`·`M2-renamed.hwpx` 세 개이고 한/글 12.0.0.4547 이
저장했다. 그림 대신 도형(polygon)을 썼다.

지정 가능한 개체 종류가 예상과 다르면(예: 셀에는 못 붙음) 그 사실을 기록한다. 거절 문구가 뜨면
문구를 그대로 옮긴다 — 그것도 관찰 결과다.

### 10.2 G 계열 — 우리가 만든 payload 의 보존성 (claim B·C)

세 파일 각각에 대해 아래를 **누적하지 않고 독립으로** 수행한다.

1. 한글에서 연다. 경고·복구·거절 문구가 뜨면 문구를 그대로 기록한다(= claim B 결과).
2. 정상적으로 열리면 본문 `AAA` 를 `AAX` 로 한 곳만 고친다(G2 는 `BBB`→`BBX`).
3. 다른 이름으로 저장한다.

| 입력 | 저장본 이름 |
|---|---|
| `G1-element-carriers.hwpx` | `G1-resaved.hwpx` |
| `G2-attribute-carriers.hwpx` | `G2-resaved.hwpx` |
| `G3-package-carriers.hwpx` | `G3-resaved.hwpx` |

M1 도 같은 방식으로 한 번 더 열고 고쳐 저장해 `M1-resaved.hwpx` 를 만든다(case A baseline).
M1 을 다시 열어 「태그 고치기」로 `#hf_test_field` → `#hf_slot_test` 로 바꾼 뒤 저장한 것이
`M2-renamed.hwpx`(case B)다. 세 변형은 서로 **누적하지 않고** 매번 M1 원본에서 시작한다.

### 10.3 판정 절차

저장본이 모이면 각 파일에 대해 다음을 돌려 before/after 를 대조한다.

```powershell
uv run python tests/_hwpx_metatag_spike.py dump tests/corpus/metatag_s1/G1-element-carriers.hwpx
uv run python tests/_hwpx_metatag_spike.py dump tests/corpus/metatag_s1/G1-resaved.hwpx
```

carrier 별로 셋 중 하나를 기록한다: **보존 / 정규화(값이 바뀜) / 소실**. 소실이면 marker 자체가
사라졌는지 값만 비었는지를 구분한다.

### 10.4 corpus 인벤토리

`tests/corpus/metatag_s1/` 10개 파일이 이 spike 의 전체 증거다. M 계열과 `*-resaved` 는 한글이
저장한 원본을 손대지 않고 그대로 보존했고, `G1`~`G3` 원본은 §6 명령으로 재생성할 수 있다.

| 파일 | 출처·변형 | SHA-256 |
|---|---|---|
| `M1-hancom-authored.hwpx` | 한글 UI 「태그 넣기」로 태그 5개 지정 (우선순위 1 증거) | `5684BE9EC8400B2A4F5BE51CC9C154F821C809E46A7DED58FF8DFBFF95FD4FDE` |
| `M1-resaved.hwpx` | M1 을 열어 `AAA`→`AAX` 후 저장 (case A) | `DE3F45DA532B495F915DC35345E7A49179F25C99EBC60AFB552D57419FE120A0` |
| `M2-renamed.hwpx` | M1 에서 누름틀 태그만 「태그 고치기」로 개명 (case B) | `5710FBA66B875134F7C900C02C2B98A5694303192B5C4BCC81B5778D9EBCE79E` |
| `M3-no-sharp.hwpx` | 태그 이름을 `#` 없이 입력해 저장 (§7.3) | `10E57E31ECC9C454B59AB0992989CE78B8DB364A40D7DE8A8248EA7D0D732A37` |
| `G1-element-carriers.hwpx` | 우리 생성 — `hp:metaTag` ×3 + `hh:metaTag` catalog | `26967F868B2CDDD022F9264941D4AFFA50276FC91B10527C9EC8B52DE9B54EF0` |
| `G1-resaved.hwpx` | G1 을 한글에서 열어 `AAA`→`AAX` 후 저장 | `247CC7EE2403A56496C4A076CAFE7C658611C7AC7DC8C2C71E0DBF9DE7CEFE9B` |
| `G2-attribute-carriers.hwpx` | 우리 생성 — camel attr + `tbl` element + `subList@metatag` | `328DB9796ACEA99B52DC932062F6987822350239313C030734D494CA904D3CEB` |
| `G2-resaved.hwpx` | G2 를 한글에서 열어 `BBB`→`BBX` 후 저장 | `C041CD8CFF6B3C7092FA6D4B0E83903AD6B4D5429D49C12D7B6D112D9C2EBC02` |
| `G3-package-carriers.hwpx` | 우리 생성 — `opf:meta` + package entry 2 | `3E216B4E4EF0FF1CD6081B07A705839E27A7838E722D5FFA48C16AB2415F4685` |
| `G3-resaved.hwpx` | G3 를 한글에서 열어 저장 | `CBDF8FBFCA6444562E15DAD9208DC9D1E874238D7141A8650F17581B4D42737A` |

## 11. 사전 등록한 판정 규칙

결과를 보고 기준을 고르지 않도록 규칙을 먼저 적는다.

- **PASS-A** — object-level 또는 document-level `metaTag` element 가 §6.1 payload 를 **문자 단위로
  그대로** 되돌려주고, unknown property(`hwpxFiller`)가 살아남는다. 이때 canonical 후보는
  `BOOKMARK + native metaTag semantic payload` 다.
- **PASS-B** — 한글이 payload 를 정규화하거나 잘라내지만(예: `{"name":"#tag"}` 로 축소) tag 이름
  수준의 작은 안정 참조는 보존한다. 이때는 `BOOKMARK + 작은 native reference + package 내부
  semantic catalog` 를 후속 탐색 대상으로 올린다. sidecar 파일은 이 단계에서 채택하지 않는다.
- **FAIL** — marker 가 사라지거나, 문서가 열리지 않거나, 값이 조용히 바뀌어 신뢰할 수 없다.

carrier 마다 판정이 다를 수 있으므로 **carrier 별로** 적고, 종합 판정은 가장 좋은 carrier 를
기준으로 내리되 그 carrier 이름을 함께 적는다.

## 12. 최종 판정 — **PASS-A (semantic)**, 사전 등록 규칙 대비 편차 있음

| 주장 | 상태 |
|---|---|
| our round-trip | **PASS** (§8) |
| Hancom open | **PASS** — G1~G3 세 파일 모두 경고 없이 열림 (§9) |
| Hancom save preserve | **PASS(semantic)** — 모델이 아는 wire 형태 3종에 실린 payload 6개 전부, 미지 property 포함. 단 byte 는 아니다 (§9.1·§9.2) |

### 12.1 사전 등록 규칙과 어긋난 지점

먼저 이것부터 적는다. **관찰 결과는 §11 의 두 label 중 어느 쪽에도 정확히 들어맞지 않는다.**

- **PASS-A 의 문구는 "payload 를 문자 단위로 그대로 되돌려준다" 였고, 그 조건은 실패했다.**
  한글은 살아남은 payload 6개를 전부 compact JSON 으로 재직렬화한다(§9.2).
- **PASS-B 의 문구도 맞지 않는다.** PASS-B 는 정규화를 "arbitrary rich payload 에는 부적합"
  과 묶어 두었는데, 관찰은 그 반대다 — 정규화가 일어나면서도 unknown property 를 포함한
  rich payload 가 **의미 단위로 온전히** 살아남았다.

원인은 결과가 아니라 **규칙에 있다.** §11 을 쓸 때 byte 충실도와 의미 충실도를 하나의 축으로
묶어, "정규화 = 손실"을 암묵 전제로 깔았다. 실제 format 은 그 둘을 분리한다. 사전 등록의 값어치는
편차를 숨기지 않는 데 있으므로, label 을 조용히 갈아끼우는 대신 **어긋났다는 사실과 어긋난
방향을 함께 남긴다.**

### 12.2 판정

그 위에서 판정은 **PASS-A (semantic)** 이다. 즉 §11 PASS-A 의 설계 결론 — 한컴 MetaTag 를 rich
native carrier 로 쓸 수 있다 — 은 성립하고, 그 근거는 byte 동일성이 아니라 **파싱된 payload 의
동등성**이다. 동등성 판정 기준이 바뀌었으므로 §12.3 의 경계 2를 계약에 반드시 담아야 한다.

따라서 canonical 후보는 다음과 같다.

```text
HWPX canonical Slot
=
native BOOKMARK region        (structural identity, S0)
+
native metaTag element payload (semantic identity, S1)
```

### 12.3 경계

**PASS-A (semantic) 은 세 개의 경계를 달고 있다.**

1. **carrier 를 골라야 한다.** 「MetaTag」 전체가 통과한 것이 아니다. 통과한 것은 공식 모델이
   아는 셋(`hp:metaTag` element / `hh:metaTag` element / `subList@metatag`)뿐이고,
   `fieldBegin@metaTag` camel attribute 와 package 수준 carrier 는 **전부 죽었다**.
2. **byte 동등이 아니라 JSON 동등이다.** 한글이 compact 로 재직렬화한다(§9.2). payload 를
   해시·서명으로 봉인하는 설계는 그대로 쓸 수 없다.
3. **한/글 12.0.0.4547 과 이 표본에 한정한다.** 다른 버전, 다른 개체 종류, 2,083자 초과 payload,
   여러 태그 동시 편집은 시험하지 않았다.

## 13. Q1~Q7

**Q1. MetaTag 의 실제 HWPX wire format 은?**
**확정**(§4.1·§7 — 공식 모델 + 한컴이 직접 생성한 실물). 셋이다. ① 개체·문서에 붙는
`hp:metaTag`/`hh:metaTag` **element** — 값은 element text. ② `hp:subList` 의 소문자
`metatag` **attribute**(셀·글상자). ③ 공식 모델에 없고 한글이 늘 비워 두는
`hp:fieldBegin@metaTag` camel attribute. payload 는 `{"name":"#태그명"}` 형태의 compact JSON
문자열이고, `#` 는 UI 가 자동으로 붙인다(§7.3).

**Q2. arbitrary payload 를 보존할 수 있는가?**
**예.** 한글·따옴표·`&<>`·앞뒤 공백·UUID·512자 문자열이 전부 왕복했다(§9.2). format 측
길이·문자 제한도 없다. 다만 UI 가 강제하는 2,083자 상한이 있고 그 이상은 시험하지 않았다.

**Q3. 한글 open/save 뒤 unknown data 가 살아남는가?**
**carrier 에 따라 정확히 갈린다.** 모델이 아는 element·attribute 안에서는 미지 property 가
온전히 살아남는다. 모델 밖(camel attribute, `opf:meta`, package entry)에서는 예외 없이
소실된다. OWPML 소스에서 세운 추론이 실물로 확인됐다(§9.1).

**Q4. BOOKMARK 와 stable 하게 결합할 수 있는가?**
**예.** 결합 키는 bookmark `name` 이다. 한글이 BOOKMARK 를 정규화하면서도 우리 `metaTag`
child 를 형제로 남겼고, 왕복 뒤 세 region 이 그대로 resolve 됐다(§9.3). `begin@id`·`fieldid`·
`hp:p@id` 는 S0 판정대로 쓰지 않았다.

**Q5. rich semantic 전체인가 reference 뿐인가?**
**전체다.** slot id·label·cardinality·min_options·option 목록·option↔region 관계가 한 payload
안에서 왕복했다.

**Q6. `BOOKMARK + native MetaTag` 로 설계할 근거가 충분한가?**
**충분하다.** 다만 §12 의 경계 셋을 계약에 명시해야 한다 — 특히 **carrier 를 어느 것으로
할지**와 **동등성을 JSON 으로 판정한다**는 것.

**Q7. 다음 vertical slice 전에 추가 native 실험이 필요한가?**
**Slot 수직 슬라이스를 막을 만한 것은 없다.** 다만 §15 의 미확정 항목은 설계 결정에 앞서
답이 필요하다 — 특히 「태그 고치기」 UI 가 우리 payload 를 어떻게 표시·재작성하는지, 그리고
개체 수준과 문서 수준 중 어디를 정본으로 삼을지.

## 14. 검증

관찰 커밋 시점의 게이트 실측이다.

| 게이트 | 결과 |
|---|---|
| `.	est.ps1` 전체 | **PASS**, exit 0 — `2287 passed in 181.20s` |
| web build/seal | OK — Node v24.18.1 · npm 11.16.0 · Vite 8.1.5, `--verify` 통과 |
| Node 단위 테스트 | `tests 308 / pass 308 / fail 0` |
| Ruff (`src tests scripts`) | All checks passed |
| Pyright | `0 errors, 0 warnings, 0 informations` |
| coverage | TOTAL 92%, 패키지별 하한 게이트 통과 |
| S1 owner (`tests/test_metatag_s1.py`) | 8 passed in 0.12s |

- 신규 test file 1개(`tests/test_metatag_s1.py`, 8건), 신규 spike helper 1개
  (`tests/_hwpx_metatag_spike.py`), 신규 fixture 10개. 기존 test 는 수정하지 않았다.
- **heavy-resource launch delta 0** — 새 test 는 순수 Python·lxml 이고 WebView2·Chrome·Win32 를
  쓰지 않는다. 한글 실행은 사람이 GUI 로 1회 수행했고 자동 lane 에 들어가지 않는다.
- **production source 변경 0.** `src/` 아래 파일은 한 줄도 바뀌지 않았으므로 package coverage
  하한에 영향이 없다.

S1 owner test 8건이 소유하는 것은 다음이다 — 우리 authoring 의 결정성과 payload 왕복(claim A),
한컴이 직접 생성한 carrier 3종의 좌표와 값(§7), 한글 편집·개명 뒤 보존(§7.1·§7.2), 한글
open/save 뒤 carrier 별 생존·소실 행렬과 JSON 동등·key 순서(§9.1·§9.2), BOOKMARK region 과
Slot semantic 의 왕복 복원(§9.3).

## 15. Follow-up (이 spike 에서 고치지 않은 것)

제품 코드는 선제적으로 고치지 않았다. Slot 수직 슬라이스는 이 두 건의 답을 입력으로 받는다.

### 15.1 후속 미확정 2건

1. **「태그 고치기」 UI 를 직접 열고 저장했을 때 unknown payload 가 보존되는가.**
   G 계열은 본문만 고쳤고 태그 대화 상자는 열지 않았다. §7.3 이 보인 대로 한글은 태그를 다시 쓸
   때 자기 규칙으로 정규화하므로, 사용자가 우리 payload 를 담은 태그를 대화 상자에서 열고
   저장하면 `hwpxFiller` 가 살아남는지 모른다. 「태그 이름」 작업 창이 우리 payload 를 어떤
   문자열로 보여 주는지도 미관찰이다. **사용자가 실제로 밟을 경로라 제품 결정 전에 답이 필요하다.**
2. **object-level 과 document-level 중 무엇을 canonical authority 로 삼을 것인가.**
   §9.1 에서 둘 다 보존됐으므로 그대로 두면 같은 상태를 두 곳이 판정하게 된다(confirm-or-alarm
   위반의 구조적 얼굴). 이 spike 는 대조 목적으로 일부러 둘 다 넣었을 뿐 어느 쪽도 정본으로
   주장하지 않는다. **최종 제품 결정 사항이다.**

### 15.2 그 밖의 미확정 (판정 범위 밖)

- **2,083자 상한을 넘는 payload.** UI 상한이지 format 상한이 아니다. 우리는 XML 을 직접 쓰므로
  넘길 수 있으나 그때 한글이 어떻게 반응하는지 시험하지 않았다.
- **다른 버전·다른 개체.** 한/글 12.0.0.4547 과 이 표본에 한정된 판정이다.

### 15.3 확정된 설계 제약 (계약에 담아야 할 것)

- **byte 동등을 전제하지 마라.** 한글이 JSON 을 compact 로 재직렬화한다(§9.2). payload 를
  해시·서명으로 봉인하거나 byte 비교로 변경을 감지하는 설계는 성립하지 않는다. 동등성은 파싱
  결과로 판정해야 한다.
- **carrier 를 명시적으로 골라야 한다.** `fieldBegin@metaTag` camel attribute 와 package 수준
  carrier 는 실증적으로 죽는다. "MetaTag 를 쓴다"는 표현으로 뭉뚱그리면 조용히 데이터를 잃는
  경로가 생긴다.
- **`#` 는 우리가 넣어야 한다.** UI 를 거치지 않으므로 자동 정규화(§7.3) 밖에 있다. `name` 을
  마지막에 두고 `#` 을 그 값에만 쓰는 규약도 함께 지켜야 한컴 도구의 slice 가 깨지지 않는다.
  이 규약의 단일 출처를 어디에 둘지는 Slot 슬라이스에서 정한다.
- **`hh:metaTag` 는 section 이 아니라 `header.xml` 에 산다.** 현재 kernel 의 변형 경로
  (`serialize_modified_section`)는 section 전용이므로, 문서 수준 carrier 를 production 으로
  올린다면 header 쓰기 경로의 계약을 따로 정의해야 한다.
- **metatag-ex 의 slice 는 방어가 없다.** `#` 없는 payload 를 넣으면 한컴 sample 도구가 비정상
  동작한다. 우리가 규약을 지키는 한 문제되지 않지만, 규약을 어기는 payload 를 만들지 않는 것이
  정책이라면 그 정책을 강제하는 자리가 필요하다.

## 16. Canonical Slot 실물 왕복 (#621 S1)

2026-08-13에 `tests/corpus/slots/canonical.hwpx`를 한글 12.0.0.4426에서 열어 본문
`AAA`를 `AAX`로 한 곳만 수정하고 `canonical-resaved.hwpx`로 저장했다.

| 파일 | SHA-256 |
|---|---|
| `canonical.hwpx` | `E67BA4461FE98A3E9E0EBCB61F4903441BDF6D8B1184159BB9AC55D3B38127A1` |
| `canonical-resaved.hwpx` | `2AF0DA5323D48E506D9BF65F69BF1999DDE3C31F7784E27629A3096BE19376B9` |

두 파일은 byte 단위로 다르지만 `tests/test_slot_inspection.py`의 동일 판독 경로에서 Slot 1개와
Option 2개를 같은 순서·값으로 복원하고 진단은 비어 있다. 이로써 #621이 정본으로 고른
BOOKMARK별 object-local `hp:metaTag` payload가 실제 한글 open/edit/save 뒤에도 의미 단위로
보존됨을 고정한다. 구형 document-level catalog는 제품 권위로 사용하지 않는다.
