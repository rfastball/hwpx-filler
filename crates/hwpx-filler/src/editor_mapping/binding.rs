//! User edits of one row's binding: source column, display type, slice and constant value.

use super::{EditorMappingError, EditorMappingModel, default_type, fail};
use crate::mapping::TYPES;
use crate::text_render::python_repr;
use crate::text_slice::text_slice_from_payload;
use serde_json::Value;

impl EditorMappingModel {
    pub fn set_source(&mut self, index: usize, source: &str) -> Result<(), EditorMappingError> {
        let row = self.row_mut(index)?;
        if matches!(row.field_type.as_str(), "const" | "today") {
            row.field_type = default_type(row.spec.as_ref(), &row.template_field);
            row.constant.clear();
            row.fmt.clear();
        }
        row.source = source.into();
        row.mark_edited();
        Ok(())
    }
    pub fn set_display(
        &mut self,
        index: usize,
        kind: &str,
        fmt: &str,
    ) -> Result<(), EditorMappingError> {
        if !TYPES.contains(&kind) {
            return Err(fail(format!(
                "지원하지 않는 유형: {} (지원: ('text', 'date', 'amount', 'const', 'today'))",
                python_repr(&Value::String(kind.into())),
            )));
        }
        let row = self.row_mut(index)?;
        row.field_type = kind.into();
        row.fmt = fmt.into();
        if matches!(kind, "const" | "today") {
            row.source.clear();
            row.slice = None
        }
        if kind != "const" {
            row.constant.clear()
        }
        row.mark_edited();
        Ok(())
    }
    pub fn set_slice(
        &mut self,
        index: usize,
        payload: Option<&Value>,
    ) -> Result<(), EditorMappingError> {
        let parsed = text_slice_from_payload(payload).map_err(|error| fail(error.to_string()))?;
        let row = self.row_mut(index)?;
        if parsed.is_some() && !row.slice_enabled() {
            return Err(fail(format!(
                "가공은 데이터 열 값에만 둘 수 있음: {}",
                python_repr(&Value::String(row.template_field.clone()))
            )));
        }
        row.slice = parsed;
        row.mark_edited();
        Ok(())
    }
    pub fn set_const(&mut self, index: usize, value: &str) -> Result<(), EditorMappingError> {
        let row = self.row_mut(index)?;
        row.constant = value.into();
        row.mark_edited();
        Ok(())
    }
    pub fn bind_column(
        &mut self,
        index: usize,
        source: &str,
        kind: &str,
    ) -> Result<(), EditorMappingError> {
        let row = self.row_mut(index)?;
        row.source = source.into();
        row.field_type = if kind.is_empty() {
            default_type(None, &row.template_field)
        } else {
            match kind {
                "date" => "date",
                "amount" => "amount",
                _ => "text",
            }
            .into()
        };
        row.constant.clear();
        row.fmt.clear();
        row.slice = None;
        row.mark_edited();
        Ok(())
    }
    pub fn set_manual(&mut self, index: usize, value: &str) -> Result<(), EditorMappingError> {
        let row = self.row_mut(index)?;
        row.field_type = "const".into();
        row.constant = value.into();
        row.slice = None;
        row.mark_edited();
        Ok(())
    }
    pub fn freeze_to_const(&mut self, index: usize, value: &str) -> Result<(), EditorMappingError> {
        let row = self.row_mut(index)?;
        row.field_type = "const".into();
        row.constant = value.into();
        row.source.clear();
        row.fmt.clear();
        row.slice = None;
        row.mark_edited();
        Ok(())
    }
    pub fn revert_binding(&mut self, index: usize, kind: &str) -> Result<bool, EditorMappingError> {
        let row = self.row_mut(index)?;
        if row.source.is_empty() {
            return Ok(false);
        }
        row.field_type = if kind.is_empty() {
            default_type(None, &row.template_field)
        } else {
            match kind {
                "date" => "date",
                "amount" => "amount",
                _ => "text",
            }
            .into()
        };
        row.constant.clear();
        row.fmt.clear();
        row.slice = None;
        row.mark_edited();
        Ok(true)
    }
    pub fn unbind(&mut self, index: usize) -> Result<(), EditorMappingError> {
        self.row_mut(index)?.reset_to_system();
        Ok(())
    }
}
