//! Regenerate deterministic native Quickstart 101 SX-05 template fixtures.
//! Run: cargo run -p hwpx-desktop --example live101_fixture --no-default-features --offline --locked
use hwpx_core::bookmark_region::{
    BookmarkRegion, append_bookmark_metatag, create_bookmark_region, resolve_bookmark_topology,
    unwrap_bookmark_region,
};
use hwpx_core::package::{HwpxPackage, PackageLimits};
use hwpx_filler::hwpx_product_inspection::{serialize_slot_metatag, serialize_slot_option_metatag};
use hwpx_filler::hwpx_qualification::inspect_hwpx_qualification;
use hwpx_filler::slot::{Slot, SlotOption};
use sha2::{Digest, Sha256};
use std::fs;
use std::path::{Path, PathBuf};

const SECTION: &str = "Contents/section0.xml";
type OptionSpec = (&'static str, usize, &'static str, &'static str);
type SlotSpec = (
    &'static str,
    usize,
    usize,
    &'static str,
    &'static str,
    [OptionSpec; 2],
);
const SPECS: [SlotSpec; 3] = [
    (
        "SX05-S1",
        2,
        3,
        "s7f0c2a91",
        "공고 기본 정보",
        [
            ("SX05-S1-A", 2, "o91aa4301", "공고번호 표시"),
            ("SX05-S1-B", 3, "ob4de5820", "수요기관 표시"),
        ],
    ),
    (
        "SX05-S2",
        4,
        5,
        "s41bd77e0",
        "공고 상세 정보",
        [
            ("SX05-S2-A", 4, "o0c22d6f4", "공고명 표시"),
            ("SX05-S2-B", 5, "o8d735ba2", "추가 확인 표시"),
        ],
    ),
    (
        "SX05-S3",
        6,
        7,
        "sd2e84c13",
        "업무 후속 정보",
        [
            ("SX05-S3-A", 6, "o773a912f", "납품기한 표시"),
            ("SX05-S3-B", 7, "of0a165c8", "담당자 표시"),
        ],
    ),
];

fn current(package: &HwpxPackage, name: &str) -> Result<BookmarkRegion, String> {
    let found = resolve_bookmark_topology(package)
        .map_err(|error| error.to_string())?
        .into_iter()
        .filter(|region| region.name.as_deref() == Some(name))
        .collect::<Vec<_>>();
    if found.len() != 1 {
        return Err(format!(
            "SX-05 BOOKMARK count differs for {name}: {}",
            found.len()
        ));
    }
    Ok(found.into_iter().next().unwrap())
}

fn variant(base: &[u8], successor: bool) -> Result<Vec<u8>, Box<dyn std::error::Error>> {
    let mut package = HwpxPackage::from_bytes(base, PackageLimits::default())?;
    for (name, start, end, slot_id, label, options) in SPECS {
        let outer = create_bookmark_region(&mut package, SECTION, start, end, name, None)?;
        let slot = Slot {
            id: slot_id.into(),
            label: Some(label.into()),
            options: options
                .iter()
                .enumerate()
                .map(|(order, (_, _, id, text))| SlotOption {
                    id: (*id).into(),
                    order,
                    label: Some((*text).into()),
                })
                .collect(),
        };
        append_bookmark_metatag(&mut package, &outer, &serialize_slot_metatag(&slot)?)?;
        for (order, (option_name, paragraph, option_id, option_label)) in
            options.into_iter().enumerate()
        {
            let parent = current(&package, name)?;
            let child = create_bookmark_region(
                &mut package,
                SECTION,
                paragraph,
                paragraph,
                option_name,
                Some(&parent),
            )?;
            append_bookmark_metatag(
                &mut package,
                &child,
                &serialize_slot_option_metatag(&SlotOption {
                    id: option_id.into(),
                    order,
                    label: Some(option_label.into()),
                })?,
            )?;
        }
    }
    if successor {
        for name in ["SX05-S2-A", "SX05-S3-A", "SX05-S3-B", "SX05-S3"] {
            let handle = current(&package, name)?;
            unwrap_bookmark_region(&mut package, &handle)?;
        }
        let entry = package
            .entries
            .iter_mut()
            .find(|entry| entry.name == SECTION)
            .ok_or("SX-05 section missing")?;
        let xml = String::from_utf8(entry.data.clone())?;
        if !xml.contains("추정가격") {
            return Err("SX-05 replacement field missing".into());
        }
        entry.data = xml.replace("추정가격", "추가확인").into_bytes();
    }
    let bytes = package.to_bytes()?;
    let inspected = inspect_hwpx_qualification(&bytes)?;
    if inspected.structure.is_none() || !inspected.diagnostics.is_empty() {
        return Err(format!("SX-05 qualification failed: {:?}", inspected.diagnostics).into());
    }
    Ok(bytes)
}

fn digest(bytes: &[u8]) -> String {
    Sha256::digest(bytes)
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

fn write(root: &Path, name: &str, bytes: &[u8]) -> std::io::Result<()> {
    fs::write(root.join(name), bytes)?;
    println!("{name} {} {}", bytes.len(), digest(bytes));
    Ok(())
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let repo = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let base = fs::read(repo.join("examples/quickstart-101/templates/발주요청서.hwpx"))?;
    let out = repo.join("scripts/live101_native/fixtures");
    fs::create_dir_all(&out)?;
    write(&out, "initial.hwpx", &variant(&base, false)?)?;
    write(&out, "successor.hwpx", &variant(&base, true)?)?;
    println!("base {} {}", base.len(), digest(&base));
    Ok(())
}
