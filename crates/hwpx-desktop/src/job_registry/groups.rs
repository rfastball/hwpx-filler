//! Group membership writes and the group name listing.

use super::*;

impl JobRegistry {
    pub fn set_group(&self, name: &str, group: &str) -> Result<(), StoreError> {
        self.mutate(name, |job| job.group = group.trim().into())?;
        Ok(())
    }
    pub fn groups(&self) -> Result<Vec<String>, StoreError> {
        let mut groups = self
            .list_jobs_with_corruption()?
            .0
            .into_iter()
            .map(|job| job.group)
            .filter(|group| !group.is_empty())
            .collect::<Vec<_>>();
        groups.sort();
        groups.dedup();
        Ok(groups)
    }
    pub fn update_group_members(&self, name: &str, new_group: &str) -> Result<usize, StoreError> {
        if name.is_empty() {
            return Err(StoreError::Invalid("대상 그룹 이름이 비어 있습니다".into()));
        }
        self.transaction(|session| {
            let mut count = 0;
            for mut job in session.list_jobs_with_corruption()?.0 {
                if job.group == name {
                    job.group = new_group.into();
                    session.save(&mut job, true)?;
                    count += 1;
                }
            }
            Ok(count)
        })
    }
    pub fn rename_group(&self, name: &str, new_name: &str) -> Result<usize, StoreError> {
        let new_name = new_name.trim();
        if new_name.is_empty() {
            return Err(StoreError::Invalid("그룹 이름이 비어 있습니다".into()));
        }
        self.update_group_members(name, new_name)
    }
    pub fn disband_group(&self, name: &str) -> Result<usize, StoreError> {
        self.update_group_members(name, "")
    }
}
