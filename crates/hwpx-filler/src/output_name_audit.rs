//! Batch name audit over the same pattern parser, renderer and collision suffix policy.

use crate::output_name::{
    OUTPUT_NAME_PATTERN_INVALID, dedupe_output_names, guard_output_name, parse_filename_pattern,
    render_output_name,
};
use chrono::NaiveDateTime;
use serde_json::{Map, Value};
use std::path::Path;

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct OutputNameAudit {
    pub names: Vec<String>,
    pub converged: Vec<usize>,
    pub too_long: Vec<usize>,
    pub refusal_code: String,
}
impl OutputNameAudit {
    pub fn has_warning(&self) -> bool {
        !self.too_long.is_empty()
    }
}

pub fn audit_output_names(
    pattern: &str,
    records: &[Map<String, Value>],
    out_dir: &str,
    now: Option<NaiveDateTime>,
    max_path: Option<usize>,
) -> OutputNameAudit {
    let tokens = match parse_filename_pattern(&Value::String(pattern.into())) {
        Ok(tokens) => tokens,
        Err(error) => {
            return OutputNameAudit {
                refusal_code: error.code.unwrap_or(OUTPUT_NAME_PATTERN_INVALID).into(),
                ..OutputNameAudit::default()
            };
        }
    };
    let mut base = Vec::with_capacity(records.len());
    for (index, record) in records.iter().enumerate() {
        let rendered = render_output_name(&tokens, record, (index + 1) as i64, now, true).and_then(
            |(name, _)| {
                guard_output_name(&name)?;
                Ok(name)
            },
        );
        match rendered {
            Ok(name) => base.push(name),
            Err(error) => {
                return OutputNameAudit {
                    refusal_code: error.code.unwrap_or(OUTPUT_NAME_PATTERN_INVALID).into(),
                    ..OutputNameAudit::default()
                };
            }
        }
    }
    let names = dedupe_output_names(&base, &[]);
    let limit = max_path.unwrap_or(if cfg!(windows) { 260 } else { 0 });
    let root = if out_dir.is_empty() || limit == 0 {
        None
    } else {
        Some(Path::new(out_dir))
    };
    let converged = base
        .iter()
        .zip(&names)
        .enumerate()
        .filter_map(|(index, (a, b))| (a != b).then_some(index))
        .collect();
    let too_long = names
        .iter()
        .enumerate()
        .filter_map(|(index, name)| {
            root.and_then(|root| {
                (root.join(name).to_string_lossy().chars().count() >= limit).then_some(index)
            })
        })
        .collect();
    OutputNameAudit {
        names,
        converged,
        too_long,
        refusal_code: String::new(),
    }
}
