//! Template library status and row words shared by HWPX and TXT channels.

use crate::authoring::scan_tokens;
use crate::fields::{FillNote, FillNoteKind, fill_precheck};
use crate::home_state::CompileState;
use crate::hwpx_product_inspection::inspect_slots;
use crate::hwpx_structure::scan_structure;
use crate::schema::extract_schema;
use hwpx_core::package::HwpxPackage;
use serde_json::{Value, json};

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TemplateRootResolution {
    pub directory: String,
    pub source: &'static str,
    pub notice: String,
}
impl TemplateRootResolution {
    pub fn source_label(&self) -> &'static str {
        match self.source {
            "configured" => "설정한 폴더",
            "default" => "기본 폴더",
            _ => "",
        }
    }
    pub fn to_dict(&self) -> Value {
        json!({"directory":self.directory,"source":self.source,
        "source_label":self.source_label(),"notice":self.notice})
    }
    pub fn empty_hint(&self, exists: bool) -> String {
        if !exists {
            format!(
                "서식 폴더가 없습니다: {}\n설정에서 서식 폴더를 다시 지정하세요.",
                self.directory
            )
        } else {
            format!("서식 폴더에 템플릿이 없습니다: {}", self.directory)
        }
    }
}
pub fn resolve_templates_root(
    configured: &str,
    configured_exists: bool,
    default_root: &str,
) -> TemplateRootResolution {
    if configured.is_empty() {
        TemplateRootResolution {
            directory: default_root.into(),
            source: "default",
            notice: String::new(),
        }
    } else {
        TemplateRootResolution {
            directory: configured.into(),
            source: "configured",
            notice: if configured_exists {
                String::new()
            } else {
                format!("설정한 서식 폴더를 찾을 수 없습니다: {configured}")
            },
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TemplateStatus {
    pub state: CompileState,
    pub field_n: usize,
    pub compilable_n: usize,
    pub skipped_n: usize,
    pub stray_n: usize,
    pub structure_marker_n: usize,
}
impl TemplateStatus {
    pub fn inspect(package: &HwpxPackage) -> Result<Self, String> {
        let schema = extract_schema(package).map_err(|error| error.to_string())?;
        let sites = scan_tokens(package).map_err(|error| error.to_string())?;
        let structure = scan_structure(package).map_err(|error| error.to_string())?;
        let field_n = schema.field_names().len();
        let compilable_n = sites.iter().filter(|site| site.compilable).count();
        let skipped_n = sites.len() - compilable_n;
        let stray_n = schema.stray_tokens.len();
        let structure_marker_n = structure.summary.markers;
        let remaining = compilable_n + skipped_n + stray_n + structure_marker_n;
        let state = if field_n == 0 {
            CompileState::Raw
        } else if remaining > 0 {
            CompileState::Partial { remaining }
        } else {
            CompileState::Compiled
        };
        Ok(Self {
            state,
            field_n,
            compilable_n,
            skipped_n,
            stray_n,
            structure_marker_n,
        })
    }
    pub fn to_dict(&self) -> Value {
        json!({"state":self.state.code(),"field_n":self.field_n,"compilable_n":self.compilable_n,
            "skipped_n":self.skipped_n,"stray_n":self.stray_n,"structure_marker_n":self.structure_marker_n})
    }
}
impl CompileState {
    pub fn code(&self) -> &'static str {
        match self {
            Self::Raw => "raw",
            Self::Partial { .. } => "partial",
            Self::Compiled => "compiled",
        }
    }
}
pub fn describe_precheck_note(note: &FillNote) -> String {
    match note.kind {
        FillNoteKind::InlineStripped => format!(
            "누름틀 '{}' 값 안에 인라인 요소({})가 있습니다. 다른 값을 채우면 값과 함께 제거됩니다.",
            note.field,
            note.detail.join(", ")
        ),
        FillNoteKind::SlotSynthesized => format!(
            "빈 누름틀 '{}': 채울 때 값 자리를 새로 만듭니다.",
            note.field
        ),
        FillNoteKind::OccurrenceUnfillable => format!(
            "누름틀 '{}' 자리 중 구조상 기입할 수 없는 곳이 있습니다. 그 자리는 채워지지 않습니다.",
            note.field
        ),
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TemplateRow {
    pub name: String,
    pub path: String,
    pub status: Option<TemplateStatus>,
    pub field_count: usize,
    pub error: String,
    pub media: &'static str,
    pub fill_warns: Vec<String>,
}
impl TemplateRow {
    pub fn hwpx(name: &str, path: &str, package: &HwpxPackage) -> Result<Self, String> {
        let status = TemplateStatus::inspect(package)?;
        let notes = fill_precheck(package).map_err(|error| error.to_string())?;
        Ok(Self {
            name: name.into(),
            path: path.into(),
            field_count: status.field_n,
            status: Some(status),
            error: String::new(),
            media: "hwpx",
            fill_warns: notes.iter().map(describe_precheck_note).collect(),
        })
    }
    pub fn txt(name: &str, path: &str, field_count: usize, error: &str) -> Self {
        Self {
            name: name.into(),
            path: path.into(),
            status: None,
            field_count,
            error: error.into(),
            media: "txt",
            fill_warns: Vec::new(),
        }
    }
    pub fn error(name: &str, path: &str, media: &'static str, error: &str) -> Self {
        Self {
            name: name.into(),
            path: path.into(),
            status: None,
            field_count: 0,
            error: error.into(),
            media,
            fill_warns: Vec::new(),
        }
    }
    pub fn badge_label(&self) -> &'static str {
        if self.media == "txt" {
            "TXT"
        } else if !self.error.is_empty() {
            "오류"
        } else {
            match self.status.as_ref().map(|status| &status.state) {
                Some(CompileState::Raw) => "원문",
                Some(CompileState::Partial { .. }) => "부분 변환",
                Some(CompileState::Compiled) => "변환됨",
                None => "오류",
            }
        }
    }
    pub fn badge_level(&self) -> &'static str {
        if self.media == "txt" {
            "muted"
        } else if !self.error.is_empty() {
            "danger"
        } else {
            self.status
                .as_ref()
                .map_or("danger", |status| status.state.badge_level())
        }
    }
    pub fn detail_line(&self) -> String {
        if !self.error.is_empty() {
            return format!("읽기 실패: {}", self.error);
        }
        let mut parts = vec![format!("필드 {}개", self.field_count)];
        if let Some(status) = &self.status {
            for (number, label) in [
                (status.compilable_n, "미변환"),
                (status.skipped_n, "수동"),
                (status.stray_n, "남은 토큰"),
                (status.structure_marker_n, "구간 표기"),
            ] {
                if number > 0 {
                    parts.push(format!("{label} {number}개"));
                }
            }
        }
        parts.join(" · ")
    }
    pub fn select_block_reason(&self) -> String {
        if !self.error.is_empty() {
            return format!("읽을 수 없어 고를 수 없습니다: {}", self.error);
        }
        if self.media == "txt" {
            return String::new();
        }
        match self.status.as_ref().map(|status| &status.state) {
            Some(CompileState::Raw | CompileState::Partial { .. }) => {
                "누름틀·구간 변환을 해야 고를 수 있습니다.".into()
            }
            Some(CompileState::Compiled) => String::new(),
            None => "상태를 확인할 수 없어 고를 수 없습니다.".into(),
        }
    }
    pub fn actions(&self) -> Vec<Value> {
        if !self.error.is_empty() {
            return Vec::new();
        }
        match self.status.as_ref().map(|status| &status.state) {
            Some(CompileState::Raw) => vec![json!({"key":"compile","label":"누름틀·구간 변환"})],
            Some(CompileState::Partial { .. }) => {
                vec![json!({"key":"compile","label":"마저 변환"})]
            }
            _ => Vec::new(),
        }
    }
    pub fn pool_row(&self, key: &str) -> Value {
        let reason = self.select_block_reason();
        json!({"key":key,"name":self.name,"sub":self.detail_line(),"reason":reason,
            "warns":self.fill_warns,"badge_label":self.badge_label(),"badge_level":self.badge_level(),
            "icon":self.media,"selectable":reason.is_empty(),"path":self.path,"actions":self.actions()})
    }
}

pub fn template_hwpx_detail(
    name: &str,
    path: &str,
    package: &HwpxPackage,
) -> Result<Value, String> {
    let row = TemplateRow::hwpx(name, path, package)?;
    let fields = extract_schema(package)
        .map_err(|error| error.to_string())?
        .field_names();
    let (slots, diagnostics) = inspect_slots(package).map_err(|error| error.to_string())?;
    let diagnostic_messages: Vec<String> =
        diagnostics.into_iter().map(|item| item.message).collect();
    let slot_rows = slots.iter().map(|slot| json!({
        "id":slot.id,"label":slot.label.as_deref().unwrap_or(""),
        "option_count":slot.options.len(),
        "options":slot.options.iter().map(|option|option.label.as_deref().unwrap_or(&option.id)).collect::<Vec<_>>()
    })).collect::<Vec<_>>();
    let slot_summary = if !diagnostic_messages.is_empty() {
        format!("구간 구조를 읽을 수 없습니다: {name}")
    } else if slots.is_empty() {
        format!("구간 항목이 없습니다: {name}")
    } else {
        format!(
            "항목 {}개 · 선택 {}개",
            slots.len(),
            slots.iter().map(|slot| slot.options.len()).sum::<usize>()
        )
    };
    Ok(
        json!({"path":path,"name":name,"media":"hwpx","state":row.status.as_ref().map_or("",|status|status.state.code()),
        "badge_label":row.badge_label(),"badge_level":row.badge_level(),"field_count":fields.len(),
        "field_summary":if fields.is_empty(){"채울 필드가 없습니다.".to_owned()}else{format!("필드 {}개",fields.len())},
        "fields":fields.iter().map(|field|json!({"name":field,"type_hint":crate::schema::infer_type(field)})).collect::<Vec<_>>(),
        "actions":row.actions(),"diagnostics":diagnostic_messages,
        "slots":{"summary":slot_summary,"rows":slot_rows},"error":""}),
    )
}

pub fn template_txt_detail(name: &str, path: &str, fields: &[String], error: &str) -> Value {
    let summary = if !error.is_empty() {
        format!("읽기 실패: {error}")
    } else if fields.is_empty() {
        "채울 필드가 없습니다.".into()
    } else {
        format!("필드 {}개", fields.len())
    };
    json!({"path":path,"name":name,"media":"txt","state":"","badge_label":"TXT","badge_level":"muted",
        "field_count":fields.len(),"field_summary":summary,
        "fields":fields.iter().map(|field|json!({"name":field,"type_hint":crate::schema::infer_type(field)})).collect::<Vec<_>>(),
        "actions":[],"diagnostics":[],"slots":null,"error":error})
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::{TemplateRow, TemplateStatus};
    use crate::home_state::CompileState;
    #[test]
    fn template_root_keeps_missing_selection_and_unknown_source_distinct() {
        use super::{TemplateRootResolution, resolve_templates_root};
        for exists in [false, true] {
            let default = resolve_templates_root("", exists, "D:/기본");
            assert_eq!(
                default.to_dict(),
                serde_json::json!({
                    "directory":"D:/기본", "source":"default", "source_label":"기본 폴더", "notice":""
                })
            );
            let configured = resolve_templates_root("D:/서식", exists, "D:/기본");
            assert_eq!(
                configured.to_dict(),
                serde_json::json!({
                    "directory":"D:/서식", "source":"configured", "source_label":"설정한 폴더",
                    "notice":if exists {""} else {"설정한 서식 폴더를 찾을 수 없습니다: D:/서식"}
                })
            );
        }
        let unknown = TemplateRootResolution {
            directory: "D:/서식".into(),
            source: "자라나는미상",
            notice: String::new(),
        };
        assert_eq!(unknown.source_label(), "");
        assert_eq!(unknown.to_dict()["source_label"], "");
    }
    #[test]
    fn template_rows_keep_partial_repair_and_txt_selection_distinct() {
        assert_status_channels();
        assert_placeholder_identity_and_filled_values();
        assert_row_presentations();
        assert_fill_precheck_rows();
        let partial = TemplateRow {
            name: "서식".into(),
            path: "C:/서식.hwpx".into(),
            status: Some(TemplateStatus {
                state: CompileState::Partial { remaining: 3 },
                field_n: 2,
                compilable_n: 1,
                skipped_n: 1,
                stray_n: 0,
                structure_marker_n: 1,
            }),
            field_count: 2,
            error: String::new(),
            media: "hwpx",
            fill_warns: Vec::new(),
        };
        assert_eq!(
            partial.detail_line(),
            "필드 2개 · 미변환 1개 · 수동 1개 · 구간 표기 1개"
        );
        assert_eq!(partial.pool_row("a")["actions"][0]["label"], "마저 변환");
        assert_eq!(partial.pool_row("a")["selectable"], false);
        let txt = TemplateRow::txt("본문", "C:/본문.txt", 1, "");
        assert_eq!(txt.pool_row("b")["selectable"], true);
        assert_eq!(txt.pool_row("b")["badge_label"], "TXT");
        let corrupt = TemplateRow::error("실패", "C:/실패.hwpx", "hwpx", "손상");
        assert_eq!(
            corrupt.select_block_reason(),
            "읽을 수 없어 고를 수 없습니다: 손상"
        );
        assert!(corrupt.actions().is_empty());
    }

    fn assert_fill_precheck_rows() {
        for (body, warned) in [("V<hp:markpenBegin/><hp:markpenEnd/>", true), ("값", false)] {
            let document = package(&format!(
                r#"<hp:p><hp:run><hp:ctrl><hp:fieldBegin name="공고명"/></hp:ctrl></hp:run><hp:run><hp:t>{body}</hp:t></hp:run><hp:run><hp:ctrl><hp:fieldEnd/></hp:ctrl></hp:run></hp:p>"#
            ));
            let before = document.clone();
            let row = TemplateRow::hwpx("서식", "서식.hwpx", &document).unwrap();
            assert_eq!(row.fill_warns.len(), usize::from(warned));
            if warned {
                assert!(
                    row.fill_warns[0].contains("markpenBegin")
                        && row.fill_warns[0].contains("제거됩니다")
                );
            }
            assert_eq!(
                row.pool_row("서식.hwpx")["warns"],
                serde_json::json!(row.fill_warns)
            );
            assert_eq!(document, before);
        }
    }

    fn assert_row_presentations() {
        use serde_json::json;
        let mut document = package("<hp:p><hp:run><hp:t>{{계약명}}</hp:t></hp:run></hp:p>");
        let raw = TemplateRow::hwpx("서식", "서식.hwpx", &document).unwrap();
        assert_eq!(
            raw.actions(),
            [json!({"key":"compile","label":"누름틀·구간 변환"})]
        );
        assert_eq!(raw.badge_label(), "원문");
        assert_eq!(raw.badge_level(), "muted");
        assert!(!raw.select_block_reason().is_empty());
        crate::authoring::compile_document(&mut document, None).unwrap();
        let compiled = TemplateRow::hwpx("서식", "서식.hwpx", &document).unwrap();
        assert!(compiled.actions().is_empty() && compiled.select_block_reason().is_empty());
        assert_eq!(compiled.detail_line(), "필드 1개");
        assert_eq!(compiled.badge_label(), "변환됨");
        assert_eq!(compiled.badge_level(), "ok");
        document.entries[0].data = String::from_utf8(document.entries[0].data.clone())
            .unwrap()
            .replace(
                "</hs:sec>",
                "<hp:p><hp:run><hp:t>{{#항목 특약}}{{/항목}}</hp:t></hp:run></hp:p></hs:sec>",
            )
            .into_bytes();
        let partial = TemplateRow::hwpx("서식", "서식.hwpx", &document).unwrap();
        assert_eq!(partial.badge_label(), "부분 변환");
        assert_eq!(partial.badge_level(), "warn");
        assert_eq!(partial.detail_line(), "필드 1개 · 구간 표기 2개");
        assert_eq!(
            partial.actions(),
            [json!({"key":"compile","label":"마저 변환"})]
        );
        let txt = TemplateRow::txt("온나라/기안", "C:/lib/온나라/기안.txt", 1, "");
        assert_eq!(txt.detail_line(), compiled.detail_line());
        assert!(txt.select_block_reason().is_empty());
        let detail = super::template_txt_detail(&txt.name, &txt.path, &["공고명".into()], "");
        assert_eq!(detail["name"], txt.name);
        assert_eq!(detail["badge_label"], txt.badge_label());
        assert_eq!(detail["badge_level"], txt.badge_level());
        assert_eq!(detail["fields"][0]["name"], "공고명");
        assert_eq!(detail["actions"], json!([]));
        assert_eq!(detail["slots"], serde_json::Value::Null);
        assert_eq!(detail["state"], "");
        assert_eq!(
            super::template_txt_detail("빈 문서", "empty.txt", &[], "")["field_summary"],
            "채울 필드가 없습니다."
        );
        let txt_error = TemplateRow::txt("손상", "broken.txt", 0, "cp949 로 저장된 파일");
        let mut hwpx_error =
            TemplateRow::error("손상", "broken.hwpx", "hwpx", "cp949 로 저장된 파일");
        assert_eq!(txt_error.detail_line(), hwpx_error.detail_line());
        assert_eq!(
            txt_error.select_block_reason(),
            hwpx_error.select_block_reason()
        );
        assert_eq!(hwpx_error.badge_label(), "오류");
        assert_eq!(hwpx_error.badge_level(), "danger");
        hwpx_error.error.clear();
        assert!(
            hwpx_error
                .select_block_reason()
                .contains("상태를 확인할 수 없어")
        );
        assert!(hwpx_error.actions().is_empty());
    }

    fn package(body: &str) -> hwpx_core::package::HwpxPackage {
        hwpx_core::package::HwpxPackage { entries: vec![hwpx_core::package::PackageEntry {
            name: "Contents/section0.xml".into(),
            data: format!("<hs:sec xmlns:hs='http://www.hancom.co.kr/hwpml/2011/section' xmlns:hp='{}'>{body}</hs:sec>", hwpx_core::text_model::HP_NS).into_bytes(),
            stored: false,
        }] }
    }

    fn assert_status(
        package: &hwpx_core::package::HwpxPackage,
        state: CompileState,
        counts: [usize; 5],
    ) {
        let before = package.clone();
        let status = TemplateStatus::inspect(package).unwrap();
        assert_eq!(status.state, state);
        assert_eq!(
            [
                status.field_n,
                status.compilable_n,
                status.skipped_n,
                status.stray_n,
                status.structure_marker_n
            ],
            counts
        );
        assert_eq!(
            status.to_dict(),
            serde_json::json!({"state":state.code(),"field_n":counts[0],"compilable_n":counts[1],"skipped_n":counts[2],"stray_n":counts[3],"structure_marker_n":counts[4]})
        );
        assert_eq!(TemplateStatus::inspect(package).unwrap(), status);
        assert_eq!(crate::home_state::compile_status(package).unwrap(), state);
        assert_eq!(
            package, &before,
            "status observation must not write a stamp"
        );
    }

    fn assert_status_channels() {
        use crate::authoring::compile_document;
        use crate::fields::FieldDocument;
        let paragraph = |text: &str| format!("<hp:p><hp:run><hp:t>{text}</hp:t></hp:run></hp:p>");
        for (body, counts) in [
            (paragraph("본문만 있고 토큰 없음"), [0, 0, 0, 0, 0]),
            (paragraph("{{계약명}}"), [0, 1, 0, 1, 0]),
            (paragraph("{{#항목 특약}}{{/항목}}"), [0, 0, 0, 0, 2]),
        ] {
            assert_status(&package(&body), CompileState::Raw, counts);
        }
        let mut compiled = package(&paragraph("{{계약명}}"));
        compile_document(&mut compiled, None).unwrap();
        assert_status(&compiled, CompileState::Compiled, [1, 0, 0, 0, 0]);
        let original = String::from_utf8(compiled.entries[0].data.clone()).unwrap();
        for (extra, counts, remaining) in [
            (paragraph("{{계약명}}"), [1, 1, 0, 0, 0], 1),
            ("<hp:p><hp:run><hp:t>{{계약</hp:t></hp:run><hp:run><hp:t>명}}</hp:t></hp:run></hp:p>".into(), [1, 0, 1, 0, 0], 1),
            (paragraph("추가항목: {{추가}}"), [1, 1, 0, 1, 0], 2),
            (paragraph("{{#항목 특약 특약 사항}}{{/항목}}"), [1, 0, 0, 0, 2], 2),
            (paragraph("{{/항목}}"), [1, 0, 0, 0, 1], 1),
        ] {
            compiled.entries[0].data = original.replace("</hs:sec>", &format!("{extra}</hs:sec>")).into_bytes();
            assert_status(&compiled, CompileState::Partial { remaining }, counts);
        }
        compiled.entries[0].data = original.clone().into_bytes();
        assert_status(&compiled, CompileState::Compiled, [1, 0, 0, 0, 0]);
        FieldDocument::new(&mut compiled, "Contents/section0.xml")
            .unwrap()
            .set_field("계약명", "{{미결}}")
            .unwrap();
        assert_status(
            &compiled,
            CompileState::Partial { remaining: 1 },
            [1, 0, 0, 1, 0],
        );
        for (text, state, stray) in [
            ("structural content", CompileState::Compiled, 0),
            ("{{계약명}}", CompileState::Partial { remaining: 1 }, 1),
        ] {
            let bookmark = format!(
                "<hp:p><hp:run><hp:ctrl><hp:fieldBegin id='99' type='BOOKMARK' name='STRUCT'/></hp:ctrl><hp:t>{text}</hp:t><hp:ctrl><hp:fieldEnd beginIDRef='99'/></hp:ctrl></hp:run></hp:p>"
            );
            compiled.entries[0].data = original
                .replace("</hs:sec>", &format!("{bookmark}</hs:sec>"))
                .into_bytes();
            assert_status(&compiled, state, [1, 0, 0, stray, 0]);
        }
    }

    fn assert_placeholder_identity_and_filled_values() {
        use crate::authoring::compile_document;
        use crate::fields::FieldDocument;
        for (body, name, value, fields) in [
            (
                "<hp:p><hp:run><hp:t>{{ 계약명 }}</hp:t></hp:run></hp:p>",
                "계약명",
                "정보시스템 구축",
                1,
            ),
            (
                "<hp:p><hp:run><hp:t>{{계약명}} 예산 {{사업예산}}</hp:t></hp:run></hp:p>",
                "계약명",
                "정보시스템 구축",
                2,
            ),
            (
                "<hp:p><hp:run><hp:tbl><hp:tr><hp:tc><hp:subList><hp:p><hp:run><hp:t>{{공급가액}}</hp:t></hp:run></hp:p></hp:subList></hp:tc></hp:tr></hp:tbl></hp:run></hp:p>",
                "공급가액",
                "1,000,000원",
                1,
            ),
        ] {
            let mut compiled = package(body);
            compile_document(&mut compiled, None).unwrap();
            assert_status(&compiled, CompileState::Compiled, [fields, 0, 0, 0, 0]);
            assert!(
                FieldDocument::new(&mut compiled, "Contents/section0.xml")
                    .unwrap()
                    .set_field(name, value)
                    .unwrap()
            );
            assert_status(&compiled, CompileState::Compiled, [fields, 0, 0, 0, 0]);
        }
        let manual_field = |name: &str, value: &str| {
            format!(
                "<hp:p><hp:run><hp:ctrl><hp:fieldBegin name='{name}'/></hp:ctrl></hp:run><hp:run><hp:t>{value}</hp:t></hp:run><hp:run><hp:ctrl><hp:fieldEnd/></hp:ctrl></hp:run></hp:p>"
            )
        };
        for (name, value) in [
            ("{{ 계약&#x9;명 }}", "{{계약\u{2003}명}}"),
            ("x{{계약명}}", "{{x{{계약명}}}}"),
        ] {
            let body = manual_field(name, value);
            assert_status(&package(&body), CompileState::Compiled, [1, 0, 0, 0, 0]);
        }
        let wrong_owner = manual_field("x{{계약명}}", "{{x{{계약명}}}}")
            + &manual_field("다른필드", "{{x{{계약명}}}}");
        assert_status(
            &package(&wrong_owner),
            CompileState::Partial { remaining: 1 },
            [2, 0, 0, 1, 0],
        );
    }
}
