//! One immutable selected-record run request; mapping and validation keep their authorities.

use crate::data_source::Record;
use crate::job::Job;
use crate::mapping::MappingError;
use crate::structure_scan::python_trim;
use crate::validation::{ValidationReport, validate};
use chrono::NaiveDateTime;
use serde_json::{Map, Value};

pub struct RunRequest<'a> {
    pub job: &'a Job,
    pub records: &'a [Record],
    pub selected_indices: &'a [usize],
}
impl RunRequest<'_> {
    fn selected_records(&self) -> Result<Vec<Map<String, Value>>, MappingError> {
        self.selected_indices
            .iter()
            .map(|&index| {
                let row = self.records.get(index).ok_or_else(|| {
                    MappingError(format!("행 인덱스가 범위를 벗어났습니다: {index}"))
                })?;
                Ok(row
                    .iter()
                    .map(|(key, value)| (key.clone(), Value::String(value.clone())))
                    .collect())
            })
            .collect()
    }
    pub fn mapped_records(
        &self,
        marker: &str,
        now: Option<NaiveDateTime>,
    ) -> Result<Vec<Map<String, Value>>, MappingError> {
        let mut mapped = self.job.mapping.apply_all(&self.selected_records()?, now)?;
        if marker.is_empty() {
            return Ok(mapped);
        }
        let fields = self.job.template_fields();
        for row in &mut mapped {
            for field in &fields {
                if let Some(Value::String(value)) = row.get(field)
                    && python_trim(value).is_empty()
                {
                    row.insert(
                        field.clone(),
                        Value::String(marker.replace("{field}", field)),
                    );
                }
            }
        }
        Ok(mapped)
    }
    pub fn source_report(&self) -> Result<ValidationReport, MappingError> {
        let records = self
            .records
            .iter()
            .map(|row| {
                row.iter()
                    .map(|(key, value)| (key.clone(), Value::String(value.clone())))
                    .collect()
            })
            .collect::<Vec<Map<String, Value>>>();
        Ok(validate(&self.job.source_keys(), &records))
    }
    pub fn output_report(
        &self,
        now: Option<NaiveDateTime>,
    ) -> Result<ValidationReport, MappingError> {
        Ok(validate(
            &self.job.template_fields(),
            &self.mapped_records("", now)?,
        ))
    }
    pub fn blank_fields(&self, now: Option<NaiveDateTime>) -> Result<Vec<String>, MappingError> {
        Ok(self.output_report(now)?.empty_valued)
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use crate::mapping::{FieldMapping, MappingProfile};

    #[test]
    fn selected_source_gap_and_blank_output_have_distinct_reports() {
        let job = Job {
            mapping: MappingProfile::new(
                "",
                vec![
                    FieldMapping::new("A", "source", "text", "", "", None).unwrap(),
                    FieldMapping::new("B", "missing", "text", "", "", None).unwrap(),
                ],
                Map::new(),
            )
            .unwrap(),
            ..Job::default()
        };
        let records = vec![
            [("source".into(), " ".into())]
                .into_iter()
                .collect::<Record>(),
        ];
        let request = RunRequest {
            job: &job,
            records: &records,
            selected_indices: &[0],
        };
        assert_eq!(
            request.source_report().unwrap().missing_columns,
            ["missing"]
        );
        assert_eq!(request.blank_fields(None).unwrap(), ["A", "B"]);
        let no_selection = RunRequest {
            job: &job,
            records: &records,
            selected_indices: &[],
        };
        assert_eq!(
            no_selection.source_report().unwrap().missing_columns,
            ["missing"]
        );
        assert!(
            no_selection
                .output_report(None)
                .unwrap()
                .empty_valued
                .is_empty()
        );
        let marked = request.mapped_records("〘미입력·{field}〙", None).unwrap();
        assert_eq!(marked[0]["A"], "〘미입력·A〙");
        assert_eq!(marked[0]["B"], "〘미입력·B〙");
        assert!(!validate(&job.template_fields(), &marked).has_issues());
        assert!(
            request
                .output_report(None)
                .unwrap()
                .missing_columns
                .is_empty()
        );
    }

    #[test]
    fn selected_rows_keep_formatting_and_declared_empty_values_without_rereading() {
        let job = Job {
            mapping: MappingProfile::new(
                "",
                vec![
                    FieldMapping::new("공고명", "name", "text", "", "", None).unwrap(),
                    FieldMapping::new("추정가격", "price", "amount", "", "{:,}", None).unwrap(),
                    FieldMapping::new("계약방법", "", "const", "", "", None).unwrap(),
                ],
                Map::new(),
            )
            .unwrap(),
            ..Job::default()
        };
        let records: Vec<Record> = [("가", "1000"), ("나", "2000"), ("", "3000")]
            .into_iter()
            .map(|(name, price)| {
                [("name".into(), name.into()), ("price".into(), price.into())]
                    .into_iter()
                    .collect()
            })
            .collect();
        let request = RunRequest {
            job: &job,
            records: &records,
            selected_indices: &[0, 2],
        };
        assert_eq!(
            serde_json::to_value(request.selected_records().unwrap()).unwrap(),
            serde_json::json!([
                {"name":"가", "price":"1000"}, {"name":"", "price":"3000"}
            ])
        );
        let mapped = request.mapped_records("", None).unwrap();
        assert_eq!(
            serde_json::to_value(&mapped).unwrap(),
            serde_json::json!([
                {"공고명":"가", "추정가격":"1,000", "계약방법":""},
                {"공고명":"", "추정가격":"3,000", "계약방법":""}
            ])
        );
        assert!(request.source_report().unwrap().missing_columns.is_empty());
        assert_eq!(request.source_report().unwrap().empty_valued, ["name"]);
        assert_eq!(
            request.output_report(None).unwrap().empty_valued,
            ["공고명"]
        );
        let marked = request.mapped_records("〘미입력·{field}〙", None).unwrap();
        assert_eq!(marked[0], mapped[0]);
        assert_eq!(marked[1]["공고명"], "〘미입력·공고명〙");
        assert_eq!(marked[1]["추정가격"], "3,000");
        assert_eq!(marked[1]["계약방법"], "");
        assert!(!validate(&job.template_fields(), &marked).has_issues());
        assert_eq!(records[2]["name"], "");
        let invalid = RunRequest {
            selected_indices: &[3],
            ..request
        };
        assert_eq!(
            invalid.mapped_records("", None).unwrap_err().0,
            "행 인덱스가 범위를 벗어났습니다: 3"
        );
    }
}
