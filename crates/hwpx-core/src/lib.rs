#![cfg_attr(coverage_nightly, feature(coverage_attribute))]

pub mod authoring_edit;
pub mod bookmark_region;
mod field_occurrence;
pub use field_occurrence::{FieldDiagnostic, FieldDiagnosticKind};
pub mod lineseg;
pub mod marker_edit;
pub mod native_admission;
pub mod native_authoring;
pub mod native_transfer;
pub mod package;
pub(crate) mod shape_text;
pub mod structural_boundary;
pub mod text_extract;
pub mod text_model;
pub(crate) mod xml_dom;
pub mod xml_view;

pub use xml_dom::{Attribute, Content, Name, Node, NodeId, XmlError};
