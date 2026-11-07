//! Slot lifecycle writes: clone, rename, delete, trash restore, and corrupt-entry removal.

use super::*;

impl JobRegistry {
    pub fn clone_job(&self, name: &str) -> Result<String, StoreError> {
        self.transaction(|session| {
            let mut job = session.load(name)?;
            let base = format!("{name} (복사본)");
            let mut candidate = base.clone();
            let mut index = 2u64;
            while self.path_for(&candidate).exists() {
                candidate = format!("{name} (복사본 {index})");
                index = index.checked_add(1).ok_or_else(|| {
                    StoreError::Invalid("복사본 이름 공간이 소진되었습니다.".into())
                })?;
            }
            job.name = candidate.clone();
            job.last_run_at.clear();
            job.favorited_at.clear();
            job.reviewed_rules.clear();
            job.template_revision = 1;
            job.binding_revision = 1;
            job.previous_rules = serde_json::json!({});
            job.authority_id.clear();
            session.save(&mut job, false)?;
            Ok(candidate)
        })
    }
    pub fn rename(&self, name: &str, new_name: &str) -> Result<(), StoreError> {
        let new_name = new_name.trim();
        if new_name.is_empty() {
            return Err(StoreError::Invalid("이름이 비어 있습니다".into()));
        }
        if new_name == name {
            return Ok(());
        }
        self.transaction(|session| {
            let mut job = session.load(name)?;
            let source = self.path_for(name);
            let destination = self.path_for(new_name);
            if source != destination && destination.exists() {
                return Err(StoreError::Invalid(format!(
                    "이름 '{new_name}' 은(는) 이미 사용 중입니다"
                )));
            }
            job.name = new_name.into();
            session.save(&mut job, source == destination)?;
            if source != destination {
                fs::remove_file(source)?;
            }
            Ok(())
        })
    }
    pub fn delete(&self, name: &str) -> Result<(), StoreError> {
        self.transaction(|_| {
            let path = self.path_for(name);
            if path.exists() {
                fs::remove_file(path)?;
            }
            Ok(())
        })
    }
    pub fn soft_delete(&self, name: &str) -> Result<DeletedJobSlot, StoreError> {
        self.transaction(|_| {
            let original = self.path_for(name);
            if !original.exists() {
                return Err(StoreError::Invalid(format!(
                    "작업을 찾을 수 없습니다: {name}"
                )));
            }
            let trash = self.directory.join(".trash");
            fs::create_dir_all(&trash)?;
            reject_linked_directory(&trash)?;
            purge_trash(&trash);
            let now = SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .map_err(|error| StoreError::Io(io::Error::other(error)))?;
            for _ in 0..10 {
                let nonce = NEXT_TRASH.fetch_add(1, Ordering::Relaxed);
                let name = original
                    .file_name()
                    .expect("job slot has a name")
                    .to_string_lossy();
                let trashed = trash.join(format!(
                    "{}-{}-{nonce}-{name}",
                    now.as_secs(),
                    std::process::id()
                ));
                match move_exclusive(&original, &trashed) {
                    Ok(()) => return Ok(DeletedJobSlot { original, trashed }),
                    Err(error) if error.kind() == io::ErrorKind::AlreadyExists => continue,
                    Err(error) => return Err(StoreError::Io(error)),
                }
            }
            Err(StoreError::Io(io::Error::new(
                io::ErrorKind::AlreadyExists,
                "deleted job slot names exhausted",
            )))
        })
    }
    pub fn restore_soft_deleted(&self, slot: &DeletedJobSlot) -> Result<String, StoreError> {
        self.transaction(|session| {
            if slot.original.parent() != Some(self.directory.as_path())
                || slot.trashed.parent() != Some(self.directory.join(".trash").as_path())
            {
                return Err(StoreError::Invalid(
                    "되돌릴 작업 파일을 찾을 수 없습니다.".into(),
                ));
            }
            reject_linked_directory(&self.directory.join(".trash"))?;
            if !slot.trashed.exists() {
                return Err(StoreError::Invalid(
                    "되돌릴 작업 파일을 찾을 수 없습니다.".into(),
                ));
            }
            if slot.original.exists() {
                return Err(StoreError::Invalid(
                    "같은 이름의 작업이 이미 있어 복원할 수 없습니다.".into(),
                ));
            }
            fs::create_dir_all(&self.directory)?;
            move_exclusive(&slot.trashed, &slot.original)?;
            Ok(self.load_at(&slot.original, &session.root)?.name)
        })
    }
    pub fn remove_corrupt_entry(&self, token: &str) -> Result<(), StoreError> {
        self.transaction(|session| {
            let (_, corrupt) = session.list_jobs_with_corruption()?;
            if !corrupt.iter().any(|entry| entry.token == token) {
                return Err(StoreError::Invalid(
                    "손상 작업 목록에 없는 경로입니다. 새로고침 후 다시 시도하세요.".into(),
                ));
            }
            match fs::remove_file(token) {
                Ok(()) => Ok(()),
                Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(()),
                Err(error) => Err(StoreError::Io(error)),
            }
        })
    }
}
