//! Ordered record append/merge pipeline; source acquisition stays behind `DataSource`.

use crate::data_source::{DataSource, DataSourceError, Record};
use crate::text_render::python_repr;
use indexmap::{IndexMap, IndexSet};
use serde_json::{Map, Value};
use std::collections::HashMap;
use std::fmt;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AssemblyError(pub String);
impl fmt::Display for AssemblyError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for AssemblyError {}
fn fail(message: impl Into<String>) -> AssemblyError {
    AssemblyError(message.into())
}

pub fn union_keys(rows: &[Record]) -> Vec<String> {
    let mut seen = IndexSet::new();
    for row in rows {
        seen.extend(row.keys().cloned());
    }
    seen.into_iter().collect()
}
fn normalize(rows: Vec<Record>) -> Vec<Record> {
    let keys = union_keys(&rows);
    rows.into_iter()
        .map(|row| {
            keys.iter()
                .map(|key| (key.clone(), row.get(key).cloned().unwrap_or_default()))
                .collect()
        })
        .collect()
}
fn require_key(table: &[Record], key: &str, where_: &str) -> Result<(), AssemblyError> {
    if table.first().is_some_and(|row| !row.contains_key(key)) {
        return Err(fail(format!(
            "{where_} 소스에 조인 키 {} 가 없습니다.",
            python_repr(&Value::String(key.into()))
        )));
    }
    Ok(())
}
fn combine(left: &Record, right: &Record) -> Record {
    let mut out = left.clone();
    for (key, value) in right {
        out.entry(key.clone()).or_insert_with(|| value.clone());
    }
    out
}

#[derive(Clone, Copy, Default)]
pub struct StdlibAssemblyEngine;
impl StdlibAssemblyEngine {
    pub fn merge(
        &self,
        left: &[Record],
        right: &[Record],
        on: &str,
        how: &str,
    ) -> Result<Vec<Record>, AssemblyError> {
        if !["inner", "left"].contains(&how) {
            return Err(fail(format!(
                "merge how 는 'inner'|'left' 여야 합니다: {}",
                python_repr(&Value::String(how.into()))
            )));
        }
        require_key(left, on, "merge 좌측")?;
        require_key(right, on, "merge 우측")?;
        let mut index: HashMap<&str, Vec<&Record>> = HashMap::new();
        for row in right {
            index
                .entry(row.get(on).map_or("", String::as_str))
                .or_default()
                .push(row);
        }
        let mut out = Vec::new();
        for row in left {
            match index.get(row.get(on).map_or("", String::as_str)) {
                Some(matches) if !matches.is_empty() => {
                    out.extend(matches.iter().map(|item| combine(row, item)))
                }
                _ if how == "left" => out.push(row.clone()),
                _ => {}
            }
        }
        Ok(normalize(out))
    }
    pub fn append(&self, tables: &[Vec<Record>]) -> Vec<Record> {
        normalize(
            tables
                .iter()
                .flat_map(|table| table.iter().cloned())
                .collect(),
        )
    }
}

pub struct PipelineSource {
    pub sources: Vec<Box<dyn DataSource>>,
    pub steps: Vec<Map<String, Value>>,
    records: Option<Vec<Record>>,
    engine: StdlibAssemblyEngine,
}
impl PipelineSource {
    pub fn new(sources: Vec<Box<dyn DataSource>>, steps: Vec<Map<String, Value>>) -> Self {
        Self {
            sources,
            steps,
            records: None,
            engine: StdlibAssemblyEngine,
        }
    }
    fn source_records(&mut self, index: Option<&Value>) -> Result<Vec<Record>, AssemblyError> {
        let valid = index
            .and_then(Value::as_u64)
            .and_then(|index| usize::try_from(index).ok());
        match valid.and_then(|index| self.sources.get_mut(index)) {
            Some(source) => source.records().map_err(|err| fail(err.0)),
            None => Err(fail(format!(
                "스텝이 존재하지 않는 소스 인덱스를 참조합니다: {} (소스 {}개)",
                index.map_or_else(|| "None".into(), python_repr),
                self.sources.len()
            ))),
        }
    }
    fn build(&mut self) -> Result<Vec<Record>, AssemblyError> {
        if self.sources.is_empty() {
            return Err(fail("파이프라인에 소스가 없습니다."));
        }
        let mut current = self.source_records(Some(&Value::from(0)))?;
        for (n, step) in self.steps.clone().iter().enumerate() {
            let op = step.get("op");
            match op.and_then(Value::as_str) {
                Some("append") => {
                    let source = step.get("source").ok_or_else(|| {
                        fail(format!(
                            "조립 스텝 {n}(append)에 필수 인자 'source' 가 없습니다."
                        ))
                    })?;
                    let next = self.source_records(Some(source))?;
                    current = self.engine.append(&[current, next]);
                }
                Some("merge") => {
                    let source = step.get("source").ok_or_else(|| {
                        fail(format!(
                            "조립 스텝 {n}(merge)에 필수 인자 'source' 가 없습니다."
                        ))
                    })?;
                    let next = self.source_records(Some(source))?;
                    let on = step.get("on").and_then(Value::as_str).ok_or_else(|| {
                        fail(format!(
                            "조립 스텝 {n}(merge)에 필수 인자 'on' 가 없습니다."
                        ))
                    })?;
                    let how = step.get("how").and_then(Value::as_str).unwrap_or("inner");
                    current = self.engine.merge(&current, &next, on, how)?;
                }
                _ => {
                    return Err(fail(format!(
                        "알 수 없는 조립 스텝 op 입니다: {} (v1 = merge|append)",
                        op.map_or_else(|| "None".into(), python_repr)
                    )));
                }
            }
        }
        Ok(current)
    }
}
impl DataSource for PipelineSource {
    fn records(&mut self) -> Result<Vec<Record>, DataSourceError> {
        if self.records.is_none() {
            self.records = Some(self.build().map_err(|err| DataSourceError(err.0))?);
        }
        Ok(self.records.as_ref().expect("set above").clone())
    }
    fn fields(&mut self) -> Result<Vec<String>, DataSourceError> {
        self.records().map(|rows| union_keys(&rows))
    }
    fn field_labels(&self) -> IndexMap<String, String> {
        let mut labels = IndexMap::new();
        for source in &self.sources {
            for (key, value) in source.field_labels() {
                labels.entry(key).or_insert(value);
            }
        }
        labels
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use crate::data_source::InlineDataSource;
    use serde_json::json;

    fn row(pairs: &[(&str, &str)]) -> Record {
        pairs
            .iter()
            .map(|(key, value)| ((*key).into(), (*value).into()))
            .collect()
    }

    #[test]
    fn join_and_append_preserve_order_precedence_and_fail_loudly() {
        let engine = StdlibAssemblyEngine;
        let left = vec![
            row(&[("id", "1"), ("name", "원본")]),
            row(&[("id", "2"), ("name", "둘")]),
        ];
        let right = vec![
            row(&[("id", "1"), ("name", "덮기"), ("city", "서울")]),
            row(&[("id", "1"), ("city", "인천")]),
        ];
        let joined = engine.merge(&left, &right, "id", "left").unwrap();
        assert_eq!(joined.len(), 3);
        assert_eq!(
            joined[0].keys().map(String::as_str).collect::<Vec<_>>(),
            vec!["id", "name", "city"]
        );
        assert_eq!(joined[0]["name"], "원본");
        assert_eq!(joined[1]["city"], "인천");
        assert_eq!(joined[2]["city"], "");
        assert_eq!(
            engine.merge(&left, &right, "id", "inner").unwrap(),
            joined[..2]
        );
        assert!(
            engine
                .merge(&left, &right, "id", "outer")
                .unwrap_err()
                .to_string()
                .contains("'inner'|'left'")
        );
        assert!(
            engine
                .merge(&[row(&[("code", "1")])], &right, "id", "inner")
                .is_err()
        );
        assert!(engine.merge(&[], &right, "id", "inner").unwrap().is_empty());
        assert_eq!(engine.merge(&left, &[], "id", "left").unwrap(), left);
        assert!(
            engine
                .merge(&left, &[row(&[("code", "1")])], "id", "inner")
                .unwrap_err()
                .0
                .contains("조인 키")
        );
        let appended = engine.append(&[vec![row(&[("a", "1")])], vec![row(&[("b", "2")])]]);
        assert_eq!(appended[1]["a"], "");
        assert_eq!(appended[0]["b"], "");

        // The source protocol must fold ordered steps before exposing fields.
        let sources: Vec<Box<dyn DataSource>> = vec![
            Box::new(InlineDataSource::new(vec![row(&[
                ("id", "1"),
                ("name", "A"),
            ])])),
            Box::new(InlineDataSource::new(vec![row(&[
                ("id", "1"),
                ("city", "서울"),
            ])])),
            Box::new(InlineDataSource::new(vec![row(&[
                ("id", "2"),
                ("name", "C"),
                ("city", "대전"),
            ])])),
        ];
        let steps = vec![
            serde_json::from_value(json!({"op":"merge","source":1,"on":"id","how":"left"}))
                .unwrap(),
            serde_json::from_value(json!({"op":"append","source":2})).unwrap(),
        ];
        let mut pipeline = PipelineSource::new(sources, steps);
        assert_eq!(pipeline.fields().unwrap(), ["id", "name", "city"]);
        assert_eq!(
            pipeline.records().unwrap(),
            vec![
                row(&[("id", "1"), ("name", "A"), ("city", "서울")]),
                row(&[("id", "2"), ("name", "C"), ("city", "대전")]),
            ]
        );
        let mut missing = PipelineSource::new(vec![], vec![]);
        assert!(missing.records().unwrap_err().0.contains("소스가 없습니다"));
        for (step, message) in [
            (json!({"op":"append","source":9}), "소스 인덱스"),
            (json!({"op":"append","source":true}), "소스 인덱스"),
            (json!({"op":"append","source":-1}), "소스 인덱스"),
            (json!({"op":"append","source":"0"}), "소스 인덱스"),
            (json!({"op":"append"}), "필수 인자 'source'"),
            (json!({"op":"merge"}), "필수 인자 'source'"),
            (json!({"op":"merge","source":0}), "필수 인자 'on'"),
            (json!({"op":"filter","source":0}), "알 수 없는 조립 스텝 op"),
            (json!({}), "op 입니다: None"),
        ] {
            let mut invalid = PipelineSource::new(
                vec![Box::new(InlineDataSource::new(vec![row(&[("id", "1")])]))],
                vec![serde_json::from_value(step).unwrap()],
            );
            let error = invalid.records().unwrap_err().0;
            assert!(error.contains(message), "{error}");
            invalid.steps =
                vec![serde_json::from_value(json!({"op":"merge","source":0,"on":"id"})).unwrap()];
            assert_eq!(invalid.records().unwrap(), vec![row(&[("id", "1")])]);
        }
    }
}
