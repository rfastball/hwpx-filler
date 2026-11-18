//! 시험 전용 계약목록(pclm) 작업자료 짓개. 제품·CLI 에는 실리지 않는다.
//!
//! `examples/fixture_common` 처럼 `#[path]` 로 들여 쓴다. 단위 시험은 각 크레이트 `lib.rs` 의
//! `#[cfg(test)] mod pclm_fixture` 를, 통합 시험은 자기 파일의 `#[path]` 선언을 거친다.
//!
//! ```ignore
//! PclmFixture::work("source-id")
//!     .view("v_통합", &["공고명", "금액"], &[&["가", "1"]])
//!     .write(&path);
//! ```
#![allow(dead_code)]

use rusqlite::{Connection, params_from_iter};
use std::path::Path;

/// 작업자료가 약속하는 네 뷰. `data_pclm::registered_workfile_sheets` 가 이 넷을 요구한다.
pub const WORK_VIEWS: [&str; 4] = ["v_통합", "v_접수", "v_공고", "v_계약"];
/// `PCLM` — 실 작업자료의 `PRAGMA application_id`.
pub const APPLICATION_ID: u32 = 0x5043_4C4D;

struct View {
    name: String,
    headers: Vec<String>,
    rows: Vec<Vec<String>>,
}

/// 실 작업자료 모양(식별 행 + 표에 기댄 뷰)의 SQLite 파일을 짓는다.
pub struct PclmFixture {
    dataset_id: String,
    views: Vec<View>,
}

impl PclmFixture {
    /// `pclm_file(1,'work',dataset_id)` 와 네 작업 뷰. 뷰는 `.view` 로 바꾸기 전까지 `항목` 열 하나에 값 `1` 한 행이다.
    pub fn work(dataset_id: &str) -> Self {
        let mut fixture = Self {
            dataset_id: dataset_id.into(),
            views: Vec::new(),
        };
        for name in WORK_VIEWS {
            fixture = fixture.view(name, &["항목"], &[&["1"]]);
        }
        fixture
    }

    /// 같은 이름 뷰를 바꾸거나 새 뷰를 덧붙인다. 값은 모두 TEXT 로 들어간다.
    pub fn view(mut self, name: &str, headers: &[&str], rows: &[&[&str]]) -> Self {
        assert!(!headers.is_empty(), "뷰 {name} 에 열이 없다");
        for row in rows {
            assert_eq!(
                row.len(),
                headers.len(),
                "뷰 {name} 의 행 길이가 열 수와 다르다"
            );
        }
        let view = View {
            name: name.into(),
            headers: headers.iter().map(|item| (*item).into()).collect(),
            rows: rows
                .iter()
                .map(|row| row.iter().map(|item| (*item).into()).collect())
                .collect(),
        };
        match self.views.iter_mut().find(|item| item.name == name) {
            Some(slot) => *slot = view,
            None => self.views.push(view),
        }
        self
    }

    /// `path` 에 새로 쓴다(있던 파일은 지운다).
    pub fn write(&self, path: &Path) {
        let _ = std::fs::remove_file(path);
        let connection = Connection::open(path).unwrap();
        connection
            .execute_batch(&format!(
                "PRAGMA application_id = {APPLICATION_ID};
                 CREATE TABLE pclm_file(singleton INTEGER PRIMARY KEY, role TEXT, dataset_id TEXT);"
            ))
            .unwrap();
        connection
            .execute(
                "INSERT INTO pclm_file VALUES (1, 'work', ?1)",
                [&self.dataset_id],
            )
            .unwrap();
        for view in &self.views {
            let table = quote(&format!("{}_자료", view.name));
            let columns: Vec<String> = view.headers.iter().map(|item| quote(item)).collect();
            connection
                .execute_batch(&format!(
                    "CREATE TABLE {table} ({}); CREATE VIEW {} AS SELECT * FROM {table};",
                    columns
                        .iter()
                        .map(|column| format!("{column} TEXT"))
                        .collect::<Vec<_>>()
                        .join(", "),
                    quote(&view.name),
                ))
                .unwrap();
            let marks = vec!["?"; columns.len()].join(", ");
            let mut insert = connection
                .prepare(&format!("INSERT INTO {table} VALUES ({marks})"))
                .unwrap();
            for row in &view.rows {
                insert.execute(params_from_iter(row)).unwrap();
            }
        }
    }
}

fn quote(name: &str) -> String {
    format!("\"{}\"", name.replace('"', "\"\""))
}
