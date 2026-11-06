//! Modified section serialization removes stale line-layout caches and keeps their tail text.

use crate::xml_dom::{XmlDocument, XmlError};

pub const LINESEG_LOCAL: &str = "linesegarray";

pub(crate) fn serialize_modified_section(document: &mut XmlDocument) -> Result<Vec<u8>, XmlError> {
    document.strip_local_elements(LINESEG_LOCAL);
    document.to_modified_bytes()
}
