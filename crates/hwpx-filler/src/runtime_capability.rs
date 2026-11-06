//! Shipping runtime conformance manifests derived from the Rust materializer contracts.

use crate::canonical_execution_encoding::{CANONICAL_ENCODING_VERSION, canonical_execution_digest};
use crate::execution_capture::MATERIALIZATION_BASE_CONTRACT_ID;
use crate::execution_composition::{
    COMPOSITION_CONTRACT_ID, NATIVE_PRIMITIVE_CONTRACT_ID, PASS,
    RuntimeMaterializerConformanceManifest, RuntimeMaterializerConformanceRegistry,
    TXT_COMPOSITION_CONTRACT_ID, TXT_NATIVE_PRIMITIVE_CONTRACT_ID,
};
use crate::materialization_conformance::CONFORMANCE_CONTRACT_ID;
use crate::seal_execution_plan::SUPPORTED_PLAN_SCHEMAS;
use crate::shipping_seal_policy::SHIPPING_MATERIALIZATION_CONTRACT_ID;
use crate::text_materialization_conformance::TXT_CONFORMANCE_CONTRACT_ID;
use serde_json::{Value, json};

pub const HWPX_RUNTIME_CAPABILITY_MANIFEST_SCHEMA: &str = "hwpx-runtime-capability-manifest/v1";
pub const TXT_RUNTIME_CAPABILITY_MANIFEST_SCHEMA: &str = "txt-runtime-capability-manifest/v1";
pub const HWPX_RUST_MATERIALIZER: &str = "hwpx_filler::materialization_runner::materialize_hwpx";
pub const TXT_RUST_MATERIALIZER: &str = "hwpx_filler::materialization_runner::materialize_txt";

pub fn runtime_capability_manifest_payload(media: &str) -> Result<Value, String> {
    let (schema, identity, conformance, primitive, composition) = match media {
        "hwpx" => (
            HWPX_RUNTIME_CAPABILITY_MANIFEST_SCHEMA,
            HWPX_RUST_MATERIALIZER,
            CONFORMANCE_CONTRACT_ID,
            NATIVE_PRIMITIVE_CONTRACT_ID,
            COMPOSITION_CONTRACT_ID,
        ),
        "txt" => (
            TXT_RUNTIME_CAPABILITY_MANIFEST_SCHEMA,
            TXT_RUST_MATERIALIZER,
            TXT_CONFORMANCE_CONTRACT_ID,
            TXT_NATIVE_PRIMITIVE_CONTRACT_ID,
            TXT_COMPOSITION_CONTRACT_ID,
        ),
        _ => return Err(format!("unsupported runtime materializer media: {media}")),
    };
    Ok(
        json!({"capability_manifest_schema":schema,"materializer":identity,
        "conformance_contract_id":conformance,"native_primitive_contract_id":primitive,
        "materialization_contract_id":SHIPPING_MATERIALIZATION_CONTRACT_ID,
        "materialization_base_contract_id":MATERIALIZATION_BASE_CONTRACT_ID,
        "admitted_composition_contract_ids":[composition],
        "supported_plan_schema_versions":SUPPORTED_PLAN_SCHEMAS,
        "supported_canonical_encoding_versions":[CANONICAL_ENCODING_VERSION]}),
    )
}

pub fn shipping_runtime_conformance_manifest(
    media: &str,
) -> Result<RuntimeMaterializerConformanceManifest, String> {
    let payload = runtime_capability_manifest_payload(media)?;
    let string = |key| {
        payload[key]
            .as_str()
            .ok_or_else(|| format!("runtime capability {key} malformed"))
            .map(str::to_owned)
    };
    let list = |key| {
        payload[key]
            .as_array()
            .ok_or_else(|| format!("runtime capability {key} malformed"))?
            .iter()
            .map(|value| {
                value
                    .as_str()
                    .map(str::to_owned)
                    .ok_or_else(|| format!("runtime capability {key} malformed"))
            })
            .collect::<Result<Vec<_>, _>>()
    };
    Ok(RuntimeMaterializerConformanceManifest {
        runtime_capability_manifest_digest: canonical_execution_digest(&payload)
            .map_err(|e| e.to_string())?,
        materialization_contract_id: string("materialization_contract_id")?,
        materialization_base_contract_id: string("materialization_base_contract_id")?,
        native_primitive_contract_id: string("native_primitive_contract_id")?,
        admitted_composition_contract_ids: list("admitted_composition_contract_ids")?,
        supported_plan_schema_versions: list("supported_plan_schema_versions")?,
        supported_canonical_encoding_versions: list("supported_canonical_encoding_versions")?,
        conformance_status: PASS.into(),
    })
}

pub struct ShippingRuntimeCapabilities {
    pub registry: RuntimeMaterializerConformanceRegistry,
    pub hwpx: RuntimeMaterializerConformanceManifest,
    pub txt: RuntimeMaterializerConformanceManifest,
}

pub fn admitted_runtime_conformance_registry() -> Result<ShippingRuntimeCapabilities, String> {
    let hwpx = shipping_runtime_conformance_manifest("hwpx")?;
    let txt = shipping_runtime_conformance_manifest("txt")?;
    let mut registry = RuntimeMaterializerConformanceRegistry::default();
    registry.register(hwpx.clone()).map_err(|e| e.to_string())?;
    registry.register(txt.clone()).map_err(|e| e.to_string())?;
    Ok(ShippingRuntimeCapabilities {
        registry,
        hwpx,
        txt,
    })
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use crate::execution_composition::{
        RuntimeConformanceQuery, RuntimeMaterializerConformanceRegistry,
    };

    #[test]
    fn media_capability_is_derived_and_seven_axes_do_not_cross_admit() {
        let capabilities = admitted_runtime_conformance_registry().unwrap();
        assert_ne!(
            capabilities.hwpx.runtime_capability_manifest_digest,
            capabilities.txt.runtime_capability_manifest_digest
        );
        let query = RuntimeConformanceQuery {
            runtime_capability_manifest_digest: &capabilities
                .hwpx
                .runtime_capability_manifest_digest,
            materialization_contract_id: &capabilities.hwpx.materialization_contract_id,
            materialization_base_contract_id: &capabilities.hwpx.materialization_base_contract_id,
            native_primitive_contract_id: &capabilities.hwpx.native_primitive_contract_id,
            composition_contract_id: COMPOSITION_CONTRACT_ID,
            plan_schema_version: SUPPORTED_PLAN_SCHEMAS[0],
            canonical_encoding_version: CANONICAL_ENCODING_VERSION,
        };
        assert!(capabilities.registry.is_admitted(&query));
        assert!(
            !capabilities.registry.is_admitted(&RuntimeConformanceQuery {
                runtime_capability_manifest_digest: &capabilities
                    .txt
                    .runtime_capability_manifest_digest,
                ..query
            })
        );
    }

    #[test]
    fn manifests_derive_contract_axes_are_content_addressed_and_do_not_mutate_defaults() {
        let capabilities = admitted_runtime_conformance_registry().unwrap();
        let default_registry = RuntimeMaterializerConformanceRegistry::default();
        for (media, manifest, conformance, primitive, composition) in [
            (
                "hwpx",
                &capabilities.hwpx,
                CONFORMANCE_CONTRACT_ID,
                NATIVE_PRIMITIVE_CONTRACT_ID,
                COMPOSITION_CONTRACT_ID,
            ),
            (
                "txt",
                &capabilities.txt,
                TXT_CONFORMANCE_CONTRACT_ID,
                TXT_NATIVE_PRIMITIVE_CONTRACT_ID,
                TXT_COMPOSITION_CONTRACT_ID,
            ),
        ] {
            let payload = runtime_capability_manifest_payload(media).unwrap();
            assert_eq!(
                manifest.runtime_capability_manifest_digest,
                canonical_execution_digest(&payload).unwrap()
            );
            assert_eq!(manifest.conformance_status, PASS);
            assert_eq!(
                manifest.materialization_contract_id,
                SHIPPING_MATERIALIZATION_CONTRACT_ID
            );
            assert_eq!(
                manifest.materialization_base_contract_id,
                MATERIALIZATION_BASE_CONTRACT_ID
            );
            assert_eq!(manifest.native_primitive_contract_id, primitive);
            assert_eq!(
                manifest.admitted_composition_contract_ids,
                vec![composition.to_owned()]
            );
            assert_eq!(
                manifest.supported_plan_schema_versions,
                SUPPORTED_PLAN_SCHEMAS
                    .iter()
                    .map(|schema| (*schema).to_owned())
                    .collect::<Vec<_>>()
            );
            assert_eq!(
                manifest.supported_canonical_encoding_versions,
                vec![CANONICAL_ENCODING_VERSION.to_owned()]
            );
            assert_eq!(
                payload["conformance_contract_id"].as_str(),
                Some(conformance)
            );

            assert!(!default_registry.is_admitted(&RuntimeConformanceQuery {
                runtime_capability_manifest_digest: &manifest.runtime_capability_manifest_digest,
                materialization_contract_id: &manifest.materialization_contract_id,
                materialization_base_contract_id: &manifest.materialization_base_contract_id,
                native_primitive_contract_id: &manifest.native_primitive_contract_id,
                composition_contract_id: composition,
                plan_schema_version: &manifest.supported_plan_schema_versions[0],
                canonical_encoding_version: &manifest.supported_canonical_encoding_versions[0],
            }));
        }
    }
}
