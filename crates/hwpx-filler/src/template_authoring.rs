//! Pure shared authoring labels and small command projections for TXT and HWPX.

use crate::text_render::{python_str, python_truthy};
use serde_json::{Map, Value, json};
use std::fmt;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TemplateAuthoringError(pub String);
impl fmt::Display for TemplateAuthoringError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for TemplateAuthoringError {}

fn command_name(action: &str) -> Option<&'static str> {
    Some(match action {
        "create_field" => "필드로 만들기",
        "create_slot" => "항목으로 만들기",
        "create_option" => "선택으로 만들기",
        "rename_field" => "필드 이름 변경",
        "relink_field" => "필드 연결 변경",
        "unset_field" => "필드 의미 해제",
        "rename_slot" => "항목 속성 변경",
        "rename_option" => "선택 속성 변경",
        "adjust_range" => "범위 조정",
        "unwrap" => "의미만 해제",
        "delete" => "내용까지 삭제",
        "duplicate" => "복제",
        "move" => "이동",
        "revert_template" => "원본 템플릿으로 되돌리기",
        _ => return None,
    })
}
fn value_text(value: Option<&Value>, default: &str) -> String {
    value.map_or_else(|| default.into(), python_str)
}
fn target_value(target: Option<&Value>) -> Option<&Value> {
    target.filter(|value| !value.is_null() && *value != "")
}
fn object_particle(name: &str) -> &'static str {
    let Some(last) = name.chars().last() else {
        return "을";
    };
    let code = last as u32;
    if (0xAC00..=0xD7A3).contains(&code) {
        if (code - 0xAC00).is_multiple_of(28) {
            "를"
        } else {
            "을"
        }
    } else {
        "을(를)"
    }
}
/// Shared undo-menu label; the command is the product command object.
pub fn command_label(command: &Map<String, Value>, target: Option<&Value>) -> String {
    let action = value_text(command.get("type"), "");
    let target = target_value(target);
    let quoted = target.map_or_else(String::new, |value| format!("‘{}’", python_str(value)));
    match action.as_str() {
        "create_field" => {
            let name = value_text(command.get("name"), "");
            format!(
                "‘{name}’{} {}",
                object_particle(&name),
                command_name(&action).unwrap()
            )
        }
        "create_slot" | "create_option" => {
            let subject = target
                .or_else(|| command.get("label").filter(|value| python_truthy(value)))
                .or_else(|| command.get("id").filter(|value| python_truthy(value)));
            let subject = value_text(subject, "");
            format!(
                "‘{subject}’{} {}",
                object_particle(&subject),
                command_name(&action).unwrap()
            )
        }
        "rename_field" => format!("{quoted} 이름 변경").trim().into(),
        "unwrap" | "delete" | "duplicate" | "move" => {
            let noun = if command.get("kind") == Some(&Value::String("option".into())) {
                "선택"
            } else {
                "항목"
            };
            format!("{quoted} {noun} {}", command_name(&action).unwrap())
                .trim()
                .into()
        }
        "repair_marker" => target
            .filter(|value| python_truthy(value))
            .map_or_else(|| "마커 수정".into(), python_str),
        "compile_token" => format!("‘{}’ 누름틀 변환", value_text(command.get("name"), "")),
        _ => command_name(&action).map_or(action.clone(), |name| {
            format!("{quoted} {name}").trim().into()
        }),
    }
}
/// Names and counts for the field picker; no other analysis data leaks into the picker.
pub fn field_candidates(fields: &[Value]) -> Result<Vec<Value>, TemplateAuthoringError> {
    fields
        .iter()
        .map(|item| {
            let data = item
                .as_object()
                .ok_or_else(|| TemplateAuthoringError("field candidate 가 사전이 아니다".into()))?;
            let name = data
                .get("name")
                .ok_or_else(|| TemplateAuthoringError("field candidate name 누락".into()))?;
            let count = data
                .get("count")
                .ok_or_else(|| TemplateAuthoringError("field candidate count 누락".into()))?;
            let mut result = Map::new();
            result.insert("name".into(), name.clone());
            result.insert("count".into(), count.clone());
            Ok(Value::Object(result))
        })
        .collect()
}
pub fn revert_template_message(count: usize) -> String {
    format!("사라지는 것: 필드 값 {count}개")
}

pub fn rename_field_message(affected: usize, name: &str) -> String {
    let particle = name.chars().last().map_or("(으)로", |last| {
        let code = last as u32;
        if (0xAC00..=0xD7A3).contains(&code) {
            if (code - 0xAC00).is_multiple_of(28) || (code - 0xAC00) % 28 == 8 {
                "로"
            } else {
                "으로"
            }
        } else {
            "(으)로"
        }
    });
    format!("현재 문서의 사용 위치 {affected}곳이 ‘{name}’{particle} 변경됩니다.")
}
pub fn document_commands(media: &str, analysis: &Value) -> Vec<Value> {
    let filled = media == "hwpx"
        && analysis["fields"]
            .as_array()
            .into_iter()
            .flatten()
            .any(|field| {
                let name = field["name"].as_str().unwrap_or("");
                field["occurrences"]
                    .as_array()
                    .into_iter()
                    .flatten()
                    .any(|occurrence| {
                        let value = occurrence["raw"]["value"].as_str().unwrap_or("");
                        let text = crate::structure_scan::python_trim(value);
                        !text.is_empty()
                            && (!text.starts_with("{{")
                                || !text.ends_with("}}")
                                || crate::fields::normalize_field_id(text).as_deref() != Some(name))
                    })
            });
    let reason = if filled {
        Value::Null
    } else {
        Value::String("되돌릴 필드 값이 없습니다.".into())
    };
    vec![json!({"type":"revert_template","enabled":filled,"reason":reason,"alternative":null})]
}
pub fn authoring_lint(media: &str, analysis: &Value) -> Vec<Value> {
    let fields: Vec<&Value> = analysis["fields"]
        .as_array()
        .into_iter()
        .flatten()
        .collect();
    let names: Vec<String> = fields
        .iter()
        .filter_map(|item| item["name"].as_str().map(str::to_owned))
        .collect();
    crate::lint::near_duplicate_pairs(&names).into_iter().map(|(first,second)|{
        let left=fields.iter().find(|field|field["name"]==first).expect("known name");
        let right=fields.iter().find(|field|field["name"]==second).expect("known name");
        let count=|item:&Value|item["count"].as_u64().unwrap_or_else(||item["occurrences"].as_array().map_or(0,|rows|rows.len() as u64));
        let (target,other)=if count(left)<count(right){(left,right)}else{(right,left)};
        let name=target["name"].as_str().unwrap_or("");
        let other_name=other["name"].as_str().unwrap_or("");
        let occurrence=target["occurrences"].as_array().and_then(|rows|rows.first());
        let location=if let Some(occurrence)=occurrence {
            if media=="txt" {
                let mut map=Map::new();
                for key in ["line","start","end"] {if let Some(value)=occurrence.get(key){map.insert(key.into(),value.clone());}}
                Value::Object(map)
            } else if occurrence["paragraph"].as_u64().is_some(){
                let mut map=json!({"entry":occurrence["entry"],"paragraph":occurrence["paragraph"]});
                if let Some(path)=occurrence.get("cell_path").filter(|value|!value.is_null()){map["cell_path"]=path.clone();}
                if occurrence["start"].as_u64().is_some() && occurrence["end"].as_u64().is_some(){
                    map["start"]=occurrence["start"].clone();map["end"]=occurrence["end"].clone();
                }
                map
            } else if occurrence["anchor_paragraph"].as_u64().is_some(){
                json!({"entry":occurrence["entry"],"paragraph":occurrence["anchor_paragraph"]})
            } else {Value::Null}
        }else{Value::Null};
        let mut actions=vec![json!({"label":"원문으로 이동","kind":"navigate","location":location})];
        if count(target)==1 && let Some(occurrence)=occurrence {
            let command=if media=="txt" {json!({"type":"relink_field","start":occurrence["start"],
                "end":occurrence["end"],"name":other_name})}
                else{json!({"type":"relink_field","entry":occurrence["entry"],
                    "occurrence":occurrence["occurrence"],"pairing_id":occurrence["pairing_id"],
                    "old_name":name,"name":other_name})};
            actions.push(json!({"label":"필드 연결 변경","kind":"command","command":command}));
        }
        json!({"kind":"near_duplicate","severity":"warning","category":"authoring",
            "message":"공백만 다른 필드 이름이 있습니다.","target":name,"location":location,"actions":actions})
    }).collect()
}
pub fn whole_field_unset(command: &Map<String, Value>) -> bool {
    command.get("type") == Some(&Value::String("unset_field".into()))
        && command.get("occurrences").is_some_and(Value::is_array)
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use serde_json::json;
    #[test]
    fn shared_labels_preserve_particle_and_whole_field_boundary() {
        let command: Map<String, Value> =
            serde_json::from_value(json!({"type":"create_field","name":"학교"})).unwrap();
        assert_eq!(command_label(&command, None), "‘학교’를 필드로 만들기");
        let command: Map<String, Value> =
            serde_json::from_value(json!({"type":"unset_field","occurrences":[]})).unwrap();
        assert!(whole_field_unset(&command));
        assert_eq!(revert_template_message(2), "사라지는 것: 필드 값 2개");
        assert_eq!(
            rename_field_message(2, "학교"),
            "현재 문서의 사용 위치 2곳이 ‘학교’로 변경됩니다."
        );
        assert_eq!(
            rename_field_message(1, "계약"),
            "현재 문서의 사용 위치 1곳이 ‘계약’으로 변경됩니다."
        );
        assert_eq!(
            field_candidates(&[json!({"name":"a","count":2,"other":1})]).unwrap(),
            [json!({"name":"a","count":2})]
        );
    }
}
