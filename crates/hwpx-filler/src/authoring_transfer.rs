//! Media dispatch for the explicit TXT/HWPX semantic clipboard.

use crate::hwpx_authoring_transfer::{
    SemanticCapture, TransferError, capture_semantic as capture_hwpx, paste_semantic as paste_hwpx,
};
use crate::txt_authoring_transfer::{capture_txt, paste_txt};
use hwpx_core::package::HwpxPackage;
use serde_json::Value;

pub enum TransferSource<'a> {
    Txt(&'a str),
    Hwpx(&'a HwpxPackage),
    Other,
}
pub enum TransferTarget<'a> {
    Txt(&'a str),
    Hwpx(&'a mut HwpxPackage),
    Other,
}
pub enum CapturedMeaning {
    Txt(Value),
    Hwpx(SemanticCapture),
    Foreign(Value),
}
impl CapturedMeaning {
    fn media(&self) -> Option<&str> {
        match self {
            Self::Txt(value) | Self::Foreign(value) => value["media"].as_str(),
            Self::Hwpx(value) => Some(&value.media),
        }
    }
}
pub enum PasteOutcome {
    Txt { text: String, impact: Value },
    Hwpx { impact: Value },
}
fn error(message: &str) -> TransferError {
    TransferError(message.into())
}
pub fn capture_document(
    media: &str,
    source: TransferSource<'_>,
    selector: &Value,
) -> Result<CapturedMeaning, TransferError> {
    match (media, source) {
        ("txt", TransferSource::Txt(text)) => capture_txt(text, selector)
            .map(CapturedMeaning::Txt)
            .map_err(|error| TransferError(error.0)),
        ("hwpx", TransferSource::Hwpx(package)) => {
            capture_hwpx(package, selector).map(CapturedMeaning::Hwpx)
        }
        ("hwpx", _) => Err(error("HWPX package required")),
        _ => Err(error("지원하지 않는 복사 형식입니다.")),
    }
}
pub fn paste_document(
    media: &str,
    target: TransferTarget<'_>,
    captured: &CapturedMeaning,
    destination: &Value,
    with_meaning: bool,
) -> Result<PasteOutcome, TransferError> {
    if captured.media() != Some(media) {
        return Err(error(
            "서로 다른 파일 형식 사이의 의미 붙여넣기는 지원하지 않습니다.",
        ));
    }
    match (media, target, captured) {
        ("txt", TransferTarget::Txt(text), CapturedMeaning::Txt(value)) => {
            let (text, impact) = paste_txt(text, value, destination, with_meaning)
                .map_err(|error| TransferError(error.0))?;
            Ok(PasteOutcome::Txt { text, impact })
        }
        ("txt", TransferTarget::Txt(text), CapturedMeaning::Foreign(value)) => {
            let (text, impact) = paste_txt(text, value, destination, with_meaning)
                .map_err(|error| TransferError(error.0))?;
            Ok(PasteOutcome::Txt { text, impact })
        }
        ("txt", _, _) => Err(error("지원하지 않는 붙여넣기 형식입니다.")),
        ("hwpx", TransferTarget::Hwpx(package), CapturedMeaning::Hwpx(value)) => {
            paste_hwpx(package, value, destination, with_meaning)
                .map(|impact| PasteOutcome::Hwpx { impact })
        }
        ("hwpx", TransferTarget::Hwpx(_), _) => {
            Err(error("복사한 의미 데이터가 올바르지 않습니다."))
        }
        ("hwpx", _, _) => Err(error("HWPX package required")),
        _ => Err(error("지원하지 않는 붙여넣기 형식입니다.")),
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn media_dispatch_refuses_unknown_and_cross_media_before_target_parsing() {
        assert_eq!(
            capture_document("docx", TransferSource::Other, &Value::Null)
                .err()
                .unwrap()
                .0,
            "지원하지 않는 복사 형식입니다."
        );
        let foreign = CapturedMeaning::Foreign(json!({"media":"docx"}));
        assert_eq!(
            paste_document("docx", TransferTarget::Other, &foreign, &Value::Null, true)
                .err()
                .unwrap()
                .0,
            "지원하지 않는 붙여넣기 형식입니다."
        );
        let txt = CapturedMeaning::Txt(json!({"media":"txt","kind":"text","text":"x","plain":"x"}));
        assert_eq!(
            paste_document("hwpx", TransferTarget::Other, &txt, &Value::Null, true)
                .err()
                .unwrap()
                .0,
            "서로 다른 파일 형식 사이의 의미 붙여넣기는 지원하지 않습니다."
        );
    }
}
