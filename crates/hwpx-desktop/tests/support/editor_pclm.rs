//! 편집기 시험이 계약목록 작업자료를 짓고 세션에 연결하는 도우미.

use super::*;
use crate::pclm_fixture::PclmFixture;
use hwpx_filler::dataset_reference::DatasetReference;

/// 계약목록 작업자료를 `path` 에 새로 쓴다(뷰 `v_통합` 하나에 값을 담는다).
pub(super) fn write_pclm(path: &Path, headers: &[&str], rows: &[&[&str]]) {
    PclmFixture::work("editor-test")
        .view("v_통합", headers, rows)
        .write(path);
}

/// `path` 의 계약목록 `v_통합` 을 등록 데이터로 올려 편집 세션에 연결하고 등록 키를 돌려준다.
pub(super) fn mount_pclm(
    editor: &EditorController,
    pool: &DatasetPoolRegistry,
    path: &Path,
    label: &str,
) -> String {
    let reference = DatasetReference::new(
        label,
        "pclm",
        json!({"db":path,"view":"v_통합"})
            .as_object()
            .unwrap()
            .clone(),
    )
    .unwrap();
    let key = pool.add(&reference).unwrap();
    let mounted = editor
        .dispatch("use_pool_data", &json!({"key":key}))
        .unwrap();
    assert_eq!(mounted["ok"], true, "{mounted}");
    key
}
