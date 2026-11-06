//! One bounded host read of an editor template and its format facts.

use crate::library_observation::read_template;
use hwpx_core::package::{HwpxPackage, PackageLimits};
use hwpx_filler::job::template_media;
use hwpx_filler::partial_gate::PartialGate;
use hwpx_filler::schema::{FieldSpec, TemplateSchema, extract_schema, infer_type};
use hwpx_filler::text_render::{SEG_MISSING, render_segments, template_fields};
use std::collections::HashMap;
use std::path::Path;

pub const TXT_RAW_BLOCK: &str = "채울 {{토큰}}이 없는 TXT 템플릿입니다.\n목록의 행 ⋮ → '내용 편집'에서 원문에 {{필드이름}} 토큰을 넣은 뒤 다시 고르세요.";
pub const HWPX_RAW_BLOCK: &str = "이 템플릿에는 누름틀 필드가 없어 진행할 수 없습니다.\n한글에서 누름틀을 삽입하거나 누름틀 변환으로 토큰을 바꾼 템플릿을 쓰세요.";

pub struct TemplateIntake {
    pub schema: Option<TemplateSchema>,
    pub gate: Option<PartialGate>,
    pub gate_error: bool,
    pub raw_block: String,
}

fn txt_schema(text: &str) -> Option<TemplateSchema> {
    let names = template_fields(text);
    if names.is_empty() {
        return None;
    }
    let mut occurrences = HashMap::new();
    for segment in render_segments(text, &HashMap::new()).0 {
        if segment.kind == SEG_MISSING {
            *occurrences.entry(segment.name).or_insert(0usize) += 1;
        }
    }
    Some(TemplateSchema {
        fields: names
            .into_iter()
            .map(|name| FieldSpec {
                inferred_type: infer_type(&name).into(),
                occurrences: *occurrences.get(&name).unwrap_or(&1),
                name,
                in_table: false,
                context: String::new(),
            })
            .collect(),
        ..TemplateSchema::default()
    })
}

pub fn read_template_intake(path: &Path) -> Result<TemplateIntake, String> {
    let bytes = read_template(path).map_err(|error| error.to_string())?;
    if template_media(&path.to_string_lossy()) == "txt" {
        let text = String::from_utf8(bytes)
            .map_err(|error| format!("TXT 템플릿을 읽을 수 없습니다: {error}"))?;
        let schema = txt_schema(&text);
        return Ok(TemplateIntake {
            raw_block: if schema.is_none() {
                TXT_RAW_BLOCK.into()
            } else {
                String::new()
            },
            schema,
            gate: None,
            gate_error: false,
        });
    }
    let package = HwpxPackage::from_bytes(&bytes, PackageLimits::default())
        .map_err(|error| error.to_string())?;
    let schema = extract_schema(&package).map_err(|error| error.to_string())?;
    if schema.fields.is_empty() {
        return Ok(TemplateIntake {
            schema: None,
            gate: None,
            gate_error: false,
            raw_block: HWPX_RAW_BLOCK.into(),
        });
    }
    let gate = match PartialGate::inspect(&package, &schema) {
        Ok(gate) if gate.needs_gate() => Some(gate),
        Ok(_) => None,
        Err(_) => {
            return Ok(TemplateIntake {
                schema: Some(schema),
                gate: None,
                gate_error: true,
                raw_block: String::new(),
            });
        }
    };
    Ok(TemplateIntake {
        schema: Some(schema),
        gate,
        gate_error: false,
        raw_block: String::new(),
    })
}
