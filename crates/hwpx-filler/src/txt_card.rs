//! One TXT review card rendered through the shared mapping and segment authority.

use crate::mapping::{MappingError, MappingProfile};
use crate::text_render::{
    RenderReport, RenderSegment, align_segments, render_segments, segments_have_space_run,
};
use chrono::NaiveDateTime;
use serde_json::{Map, Value};
use std::collections::HashMap;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CardRender {
    pub segments: Vec<RenderSegment>,
    pub report: RenderReport,
    pub space_run: bool,
    pub fullwidth: bool,
}
pub fn render_card(
    template: &str,
    mapping: &MappingProfile,
    record: &Map<String, Value>,
    fullwidth: bool,
    now: Option<NaiveDateTime>,
) -> Result<CardRender, MappingError> {
    let values = mapping
        .apply(record, now)?
        .into_iter()
        .collect::<HashMap<_, _>>();
    let (segments, report) = render_segments(template, &values);
    let space_run = segments_have_space_run(&segments);
    Ok(CardRender {
        segments: if fullwidth {
            align_segments(&segments)
        } else {
            segments
        },
        report,
        space_run,
        fullwidth,
    })
}
pub fn card_text(segments: &[RenderSegment]) -> String {
    segments
        .iter()
        .map(|segment| segment.text.as_str())
        .collect()
}
pub fn gate_empty_fields(report: &RenderReport, mapping: &MappingProfile) -> Vec<String> {
    let declared = mapping.declared_empty_fields();
    report
        .empty_fields
        .iter()
        .filter(|name| !declared.contains(name))
        .cloned()
        .collect()
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::{card_text, gate_empty_fields, render_card};
    use crate::mapping::{FieldMapping, MappingProfile};
    use serde_json::{Map, Value};
    #[test]
    fn card_shares_rendered_text_and_excludes_confirmed_empty_from_gate() {
        let profile = MappingProfile::new(
            "",
            vec![
                FieldMapping::new("받는이", "열", "text", "", "", None).unwrap(),
                FieldMapping::new("비움", "", "const", "", "", None).unwrap(),
            ],
            Map::new(),
        )
        .unwrap();
        let record =
            serde_json::from_value::<Map<String, Value>>(serde_json::json!({"열":"홍길동"}))
                .unwrap();
        let card = render_card(
            "수신  {{받는이}} / {{비움}} / {{미정}}",
            &profile,
            &record,
            false,
            None,
        )
        .unwrap();
        assert_eq!(card_text(&card.segments), "수신  홍길동 /  / {{미정}}");
        assert!(card.space_run);
        assert_eq!(card.report.missing_fields, ["미정"]);
        assert_eq!(card.report.empty_fields, ["비움"]);
        assert!(gate_empty_fields(&card.report, &profile).is_empty());
    }
}
