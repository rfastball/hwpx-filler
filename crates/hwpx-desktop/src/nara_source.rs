//! Runtime-only Nara key injection for durable pool references.

use crate::nara_secret_store::NaraSecretStore;
use crate::nara_transport::nara_fetcher;
use chrono::{Local, NaiveDateTime};
use hwpx_filler::data_factory::{
    requires_nara_key, source_from_pool_item, source_from_pool_item_with_nara,
};
use hwpx_filler::data_source::{DataSource, DataSourceError};
use hwpx_filler::dataset_reference::DatasetReference;
use hwpx_filler::nara::NaraStdGateway;
use hwpx_filler::nara::{NARA_SERVICE_KEY_NAME, NaraFetcher};
use hwpx_filler::nara_acquire::{NaraAcquireViewModel, SecretStorePort};

fn local_clock() -> NaiveDateTime {
    Local::now().naive_local()
}

/// Native composition of the frozen acquisition port; no network call occurs until invoked.
pub fn nara_acquirer()
-> NaraAcquireViewModel<NaraSecretStore, NaraStdGateway, fn() -> NaiveDateTime> {
    NaraAcquireViewModel::with_default_name(
        NaraSecretStore,
        NaraStdGateway {
            fetcher: nara_fetcher(20_000),
        },
        local_clock,
    )
}

/// Reads the secret only when a Nara source occurs in this reference tree.
pub fn source_from_pool_reference(
    item: &DatasetReference,
    secrets: &impl SecretStorePort,
    fetcher: &NaraFetcher,
) -> Result<Box<dyn DataSource>, DataSourceError> {
    if !requires_nara_key(item) {
        return source_from_pool_item(item);
    }
    let key = secrets
        .get(NARA_SERVICE_KEY_NAME)
        .map_err(DataSourceError)?;
    match key {
        Some(key) if !key.is_empty() => source_from_pool_item_with_nara(item, &key, fetcher),
        _ => source_from_pool_item(item),
    }
}

/// Real Windows composition: no ServiceKey is persisted in the DatasetReference.
pub fn source_from_pool_reference_live(
    item: &DatasetReference,
) -> Result<Box<dyn DataSource>, DataSourceError> {
    source_from_pool_reference(item, &NaraSecretStore, &nara_fetcher(20_000))
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use serde_json::json;
    use std::sync::{
        Arc,
        atomic::{AtomicUsize, Ordering},
    };

    struct Keys {
        reads: Arc<AtomicUsize>,
        key: Option<String>,
    }
    impl SecretStorePort for Keys {
        fn get(&self, name: &str) -> Result<Option<String>, String> {
            assert_eq!(name, NARA_SERVICE_KEY_NAME);
            self.reads.fetch_add(1, Ordering::SeqCst);
            Ok(self.key.clone())
        }
        fn set(&self, _: &str, _: &str) -> Result<(), String> {
            unreachable!()
        }
        fn delete(&self, _: &str) -> Result<(), String> {
            unreachable!()
        }
    }

    #[test]
    fn durable_reference_reads_runtime_key_only_for_nara() {
        assert_pool_resolution_freezes_acquisition();
        let reads = Arc::new(AtomicUsize::new(0));
        let keys = Keys {
            reads: reads.clone(),
            key: Some("DUMMY".into()),
        };
        let fetches = Arc::new(AtomicUsize::new(0));
        let observed = fetches.clone();
        let fetcher: NaraFetcher = Arc::new(move |url| {
            assert!(url.contains("ServiceKey=DUMMY") && url.contains("numOfRows=50"));
            observed.fetch_add(1, Ordering::SeqCst);
            Ok(include_bytes!("../../../tests/fixtures/nara_std_response.json").to_vec())
        });
        let inline = DatasetReference::new(
            "plain",
            "inline",
            json!({
                "records":[{"name":"first"}]
            })
            .as_object()
            .unwrap()
            .clone(),
        )
        .unwrap();
        assert_eq!(
            source_from_pool_reference(&inline, &keys, &fetcher)
                .unwrap()
                .records()
                .unwrap()
                .len(),
            1
        );
        assert_eq!(reads.load(Ordering::SeqCst), 0);
        assert_eq!(fetches.load(Ordering::SeqCst), 0);

        let nara = DatasetReference::new(
            "나라",
            "nara",
            json!({
                "bgn_dt":"202606010000","end_dt":"202606302359","num_rows":50
            })
            .as_object()
            .unwrap()
            .clone(),
        )
        .unwrap();
        let mut restored = source_from_pool_reference(&nara, &keys, &fetcher).unwrap();
        assert_eq!(fetches.load(Ordering::SeqCst), 0);
        assert_eq!(restored.records().unwrap().len(), 2);
        assert_eq!(fetches.load(Ordering::SeqCst), 1);
        assert_eq!(reads.load(Ordering::SeqCst), 1);
        let absent = Keys {
            reads: reads.clone(),
            key: None,
        };
        assert!(
            source_from_pool_reference(&nara, &absent, &fetcher)
                .err()
                .unwrap()
                .to_string()
                .contains("서비스키가 필요합니다")
        );
        assert_eq!(reads.load(Ordering::SeqCst), 2);
    }

    fn assert_pool_resolution_freezes_acquisition() {
        use hwpx_filler::run_state::resolve_pool_source;
        use std::path::Path;
        let workbook =
            Path::new(env!("CARGO_MANIFEST_DIR")).join("../../tests/fixtures/multi_sheet.xlsx");
        let file = DatasetReference::new(
            "다중",
            "excel",
            json!({"path":workbook,"sheet":"낙찰현황"})
                .as_object()
                .unwrap()
                .clone(),
        )
        .unwrap();
        let mut factory_calls = 0;
        let (mut source, records) = resolve_pool_source(
            &file,
            |item| {
                factory_calls += 1;
                assert_eq!(item, &file);
                source_from_pool_item(item).map_err(|error| error.to_string())
            },
            |_| panic!("file resolution must not acquire Nara"),
        )
        .unwrap();
        assert_eq!(factory_calls, 1);
        assert_eq!(
            records
                .iter()
                .map(|row| row["업체명"].as_str())
                .collect::<Vec<_>>(),
            ["가나상사", "다라물산", "마바테크"]
        );
        assert_eq!(source.records().unwrap(), records);
        assert_eq!(
            resolve_pool_source(
                &file,
                |_| Err("source unavailable".into()),
                |_| panic!("unexpected acquisition")
            )
            .err()
            .unwrap(),
            "source unavailable"
        );
        let mut missing_sheet = file.clone();
        missing_sheet
            .opts
            .insert("sheet".into(), json!("없는 시트"));
        assert!(
            resolve_pool_source(
                &missing_sheet,
                |item| source_from_pool_item(item).map_err(|error| error.to_string()),
                |_| panic!("unexpected acquisition")
            )
            .is_err()
        );

        let nara = DatasetReference::new(
            "나라",
            "nara",
            json!({"bgn_dt":"202606010000","end_dt":"202606302359"})
                .as_object()
                .unwrap()
                .clone(),
        )
        .unwrap();
        let calls = Arc::new(AtomicUsize::new(0));
        let key = "aB3+xY/z9Q==pLm4Kn7";
        for (response, registered, expected_error, expected_count) in [
            (
                include_bytes!("../../../tests/fixtures/nara_std_response.json").to_vec(),
                true,
                None,
                2,
            ),
            (
                br#"{"response":{"header":{"resultCode":"00"},"body":{"items":[]}}}"#.to_vec(),
                true,
                None,
                0,
            ),
            (
                br#"{"response":{"header":{"resultCode":"07","resultMsg":"AUTH"},"body":{}}}"#
                    .to_vec(),
                true,
                Some("07"),
                0,
            ),
            (Vec::new(), false, Some("서비스키"), 0),
        ] {
            let before = calls.load(Ordering::SeqCst);
            let observed = calls.clone();
            let keys = Keys {
                reads: Arc::new(AtomicUsize::new(0)),
                key: registered.then(|| key.into()),
            };
            let gateway = NaraStdGateway {
                fetcher: Arc::new(move |_| {
                    observed.fetch_add(1, Ordering::SeqCst);
                    Ok(response.clone())
                }),
            };
            let mut acquirer = NaraAcquireViewModel::with_default_name(keys, gateway, || {
                panic!("acquisition must not read a clock")
            });
            let resolved = resolve_pool_source(
                &nara,
                |_| panic!("Nara must bypass the live pool factory"),
                |item| {
                    acquirer.acquire(
                        item.opts["bgn_dt"].as_str().unwrap(),
                        item.opts["end_dt"].as_str().unwrap(),
                        100,
                        1,
                    )
                },
            );
            if let Some(expected) = expected_error {
                let error = resolved.err().unwrap();
                assert!(error.starts_with("나라장터 데이터 취득 실패:"));
                assert!(error.contains(expected) && !error.contains(key));
            } else {
                let (mut snapshot, records) = resolved.unwrap();
                assert_eq!(records.len(), expected_count);
                for _ in 0..5 {
                    assert_eq!(snapshot.records().unwrap(), records);
                }
                if expected_count == 0 {
                    assert!(snapshot.fields().unwrap().is_empty());
                } else {
                    assert_eq!(snapshot.fields().unwrap()[0], "bidNtceNo");
                }
                assert_eq!(snapshot.field_labels()["bidNtceNm"], "공고명");
                assert_eq!(
                    snapshot.source_pointer().unwrap(),
                    "nara:취득 스냅샷(키 미포함)"
                );
            }
            assert_eq!(
                calls.load(Ordering::SeqCst),
                before + usize::from(registered)
            );
        }
        assert_eq!(calls.load(Ordering::SeqCst), 3);
        assert_eq!(
            resolve_pool_source(
                &nara,
                |_| panic!("unexpected factory"),
                |_| Err("secret store unavailable".into())
            )
            .err()
            .unwrap(),
            "secret store unavailable"
        );
    }
}
