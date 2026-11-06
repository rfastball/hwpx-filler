//! Shipping media inspection bound to an exact candidate revision and immutable profile manifest.

use crate::execution_structure::{
    ExecutionTemplateStructure, LABELED_EXECUTION_QUALIFICATION_PROFILE_ID,
    LABELED_EXECUTION_STRUCTURE_PROJECTION_SCHEMA, QualificationProfileManifest,
};
use crate::hwpx_qualification::{
    QualificationInspectError, QualificationInspection, inspect_hwpx_qualification,
};
use crate::qualification_evidence::{
    ManifestInput, QualificationDiagnostic, QualificationResult, build_manifest,
};
use crate::text_template_inspection::{inspect_txt_qualification, txt_qualification_manifest};
use serde_json::json;

pub const INSPECTION_ERROR_CODE: &str = "inspection-error";
pub const INSPECTION_CONTRACT_ERROR_CODE: &str = "inspection-contract-error";

pub fn qualification_profile_id(media: &str) -> Option<&'static str> {
    match media {
        "hwpx" => Some(LABELED_EXECUTION_QUALIFICATION_PROFILE_ID),
        "txt" => Some(crate::execution_structure::TXT_EXECUTION_QUALIFICATION_PROFILE_ID),
        _ => None,
    }
}
pub fn shipping_qualification_manifest(
    media: &str,
    created_at: &str,
) -> Option<QualificationProfileManifest> {
    match media {
        "hwpx" => Some(build_manifest(ManifestInput {
            qualification_profile_id: LABELED_EXECUTION_QUALIFICATION_PROFILE_ID,
            media: "hwpx",
            adapter_contract_version: "hwpx-inspection-v4",
            product_rule_version: "hwpx-qualification-rules-v4",
            operation_alphabet_version: "hwpx-operations-v1",
            projection_schema_version: LABELED_EXECUTION_STRUCTURE_PROJECTION_SCHEMA,
            manifest_payload: &json!({}),
            created_at,
        })),
        "txt" => Some(txt_qualification_manifest(created_at)),
        _ => None,
    }
}

pub struct QualifiedCandidate {
    pub result: QualificationResult,
    pub execution_structure: Option<ExecutionTemplateStructure>,
}
fn inspection_consistent(inspection: &QualificationInspection) -> bool {
    match (&inspection.structure, &inspection.execution_structure) {
        (None, None) => !inspection.diagnostics.is_empty(),
        (None, Some(_)) => false,
        (Some(product), execution) => {
            inspection.diagnostics.is_empty()
                && execution
                    .as_ref()
                    .is_none_or(|execution| &execution.product_structure == product)
        }
    }
}
pub fn classify_inspection(
    revision_id: &str,
    profile_id: &str,
    inspection: Result<QualificationInspection, QualificationInspectError>,
) -> QualifiedCandidate {
    let inspected = match inspection {
        Ok(value) => value,
        Err(error) => {
            return QualifiedCandidate {
                result: QualificationResult::AttemptErrored {
                    revision_id: revision_id.into(),
                    qualification_profile_id: profile_id.into(),
                    error_code: match error {
                        QualificationInspectError::Contract(_) => INSPECTION_CONTRACT_ERROR_CODE,
                        QualificationInspectError::Inspection(_) => INSPECTION_ERROR_CODE,
                    }
                    .into(),
                },
                execution_structure: None,
            };
        }
    };
    if !inspection_consistent(&inspected) {
        return QualifiedCandidate {
            result: QualificationResult::AttemptErrored {
                revision_id: revision_id.into(),
                qualification_profile_id: profile_id.into(),
                error_code: INSPECTION_CONTRACT_ERROR_CODE.into(),
            },
            execution_structure: None,
        };
    }
    let QualificationInspection {
        structure,
        diagnostics,
        execution_structure,
    } = inspected;
    match structure {
        Some(structure) => QualifiedCandidate {
            result: QualificationResult::Passed {
                revision_id: revision_id.into(),
                qualification_profile_id: profile_id.into(),
                structure,
            },
            execution_structure,
        },
        None => QualifiedCandidate {
            result: QualificationResult::Failed {
                revision_id: revision_id.into(),
                qualification_profile_id: profile_id.into(),
                diagnostics: diagnostics
                    .into_iter()
                    .map(|item| QualificationDiagnostic {
                        kind: item.kind,
                        message: item.message,
                    })
                    .collect(),
            },
            execution_structure: None,
        },
    }
}
pub fn qualify_exact(revision_id: &str, media: &str, bytes: &[u8]) -> Option<QualifiedCandidate> {
    let profile_id = qualification_profile_id(media)?;
    let inspection = match media {
        "hwpx" => inspect_hwpx_qualification(bytes),
        "txt" => inspect_txt_qualification(bytes),
        _ => unreachable!(),
    };
    Some(classify_inspection(revision_id, profile_id, inspection))
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use crate::execution_structure::TemplateStructure;
    use crate::hwpx_qualification::QualificationDiagnostic as InspectionDiagnostic;

    #[test]
    fn qualification_binds_revision_and_refuses_contradictory_inspection() {
        let shipping = shipping_qualification_manifest("hwpx", "2020-01-01T00:00:00").unwrap();
        assert_eq!(
            qualification_profile_id("hwpx"),
            Some("hwpx-template-qualification-v4")
        );
        assert_eq!(qualification_profile_id("other"), None);
        assert!(shipping_qualification_manifest("other", "2020-01-01T00:00:00").is_none());
        assert_eq!(
            [
                shipping.qualification_profile_id.as_str(),
                shipping.media.as_str(),
                shipping.adapter_contract_version.as_str(),
                shipping.product_rule_version.as_str(),
                shipping.operation_alphabet_version.as_str(),
                shipping.projection_schema_version.as_str(),
            ],
            [
                "hwpx-template-qualification-v4",
                "hwpx",
                "hwpx-inspection-v4",
                "hwpx-qualification-rules-v4",
                "hwpx-operations-v1",
                "hwpx-structure-projection-v4",
            ]
        );
        let empty = TemplateStructure {
            root_fields: vec![],
            slots: vec![],
        };
        let passed = classify_inspection(
            "revision",
            "profile",
            Ok(QualificationInspection {
                structure: Some(empty.clone()),
                diagnostics: vec![],
                execution_structure: None,
            }),
        );
        assert!(matches!(passed.result, QualificationResult::Passed {
            revision_id, qualification_profile_id, ..
        } if revision_id == "revision" && qualification_profile_id == "profile"));
        let contradictory = classify_inspection(
            "revision",
            "profile",
            Ok(QualificationInspection {
                structure: Some(empty),
                diagnostics: vec![InspectionDiagnostic {
                    kind: "invalid".into(),
                    message: "broken".into(),
                }],
                execution_structure: None,
            }),
        );
        assert!(
            matches!(contradictory.result, QualificationResult::AttemptErrored {
            error_code, ..
        } if error_code == INSPECTION_CONTRACT_ERROR_CODE)
        );
        let failed = classify_inspection(
            "revision",
            "profile",
            Ok(QualificationInspection {
                structure: None,
                diagnostics: vec![InspectionDiagnostic {
                    kind: "invalid".into(),
                    message: "broken".into(),
                }],
                execution_structure: None,
            }),
        );
        assert!(
            matches!(failed.result, QualificationResult::Failed {diagnostics, ..}
            if diagnostics.len() == 1 && diagnostics[0].message == "broken")
        );
        for (error, expected) in [
            (
                QualificationInspectError::Contract("pair contract broke".into()),
                INSPECTION_CONTRACT_ERROR_CODE,
            ),
            (
                QualificationInspectError::Inspection("resource unavailable".into()),
                INSPECTION_ERROR_CODE,
            ),
        ] {
            let qualified = classify_inspection("R8", "profile-v1", Err(error));
            assert_eq!(
                qualified.result,
                QualificationResult::AttemptErrored {
                    revision_id: "R8".into(),
                    qualification_profile_id: "profile-v1".into(),
                    error_code: expected.into(),
                }
            );
            assert!(qualified.execution_structure.is_none());
        }
        let bytes = b"Hello {{name}}";
        let qualified = qualify_exact("R8", "txt", bytes).unwrap();
        let execution = qualified.execution_structure.unwrap();
        let structure = execution.product_structure.clone();
        for (revision, profile) in [("R8", "profile-v1"), ("R9", "profile-v2")] {
            let inspection = QualificationInspection {
                structure: Some(structure.clone()),
                diagnostics: vec![],
                execution_structure: Some(execution.clone()),
            };
            for _ in 0..2 {
                let qualified = classify_inspection(revision, profile, Ok(inspection.clone()));
                assert_eq!(
                    qualified.result,
                    QualificationResult::Passed {
                        revision_id: revision.into(),
                        qualification_profile_id: profile.into(),
                        structure: structure.clone()
                    }
                );
                assert_eq!(qualified.execution_structure, Some(execution.clone()));
            }
        }
        let diag = InspectionDiagnostic {
            kind: "invalid".into(),
            message: "broken".into(),
        };
        for inspection in [
            QualificationInspection {
                structure: None,
                diagnostics: vec![],
                execution_structure: None,
            },
            QualificationInspection {
                structure: None,
                diagnostics: vec![diag],
                execution_structure: Some(execution.clone()),
            },
            QualificationInspection {
                structure: Some(TemplateStructure::default()),
                diagnostics: vec![],
                execution_structure: Some(execution),
            },
        ] {
            let qualified = classify_inspection("R8", "profile", Ok(inspection));
            assert_eq!(
                qualified.result,
                QualificationResult::AttemptErrored {
                    revision_id: "R8".into(),
                    qualification_profile_id: "profile".into(),
                    error_code: INSPECTION_CONTRACT_ERROR_CODE.into()
                }
            );
            assert!(qualified.execution_structure.is_none());
        }
        assert!(qualify_exact("R8", "unknown", bytes).is_none());
    }
}
