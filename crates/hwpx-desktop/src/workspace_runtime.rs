//! Assemble one real product graph for either the user's home or an isolated lesson home.

use crate::authoring_controller::AuthoringController;
use crate::dataset_registry::DatasetPoolRegistry;
use crate::editor_controller::EditorController;
use crate::generation_gate::GenerationGate;
use crate::job_controller::JobController;
use crate::job_registry::JobRegistry;
use crate::library_controller::{LibraryController, LibraryStores};
use crate::locations::Locations;
use crate::onboarding_controller::OnboardingController;
use crate::pool_controller::PoolController;
use crate::preset_registry::PresetRegistry;
use crate::shell_settings::ShellSettings;
use crate::slot_configuration_product::SlotConfigurationProduct;
use crate::template_change_coordinator::TemplateChangeCoordinator;
use crate::template_controller::TemplateController;
use crate::template_files::TemplateFileStore;
use crate::template_root::TemplateRoot;
use crate::workbench_controller::WorkbenchController;
use crate::workbench_materialization::{materialization_port, selection_port};
use crate::workspace_switch::{GraphError, PushGate, ScreenController, WorkspaceGraph};
use std::path::Path;
use std::sync::Arc;

#[derive(Clone)]
pub struct RuntimeResources {
    pub jobs: Arc<JobRegistry>,
    pub datasets: Arc<DatasetPoolRegistry>,
    pub generation: Arc<GenerationGate>,
    pub settings: Arc<ShellSettings>,
    pub templates: Arc<TemplateRoot>,
    pub template_files: Arc<TemplateFileStore>,
    pub template: Arc<TemplateController>,
    pub authoring: Arc<AuthoringController>,
    pub library: Arc<LibraryController>,
    pub editor: Arc<EditorController>,
    pub job: Arc<JobController>,
    pub pool: Arc<PoolController>,
    pub workbench: Arc<WorkbenchController>,
}

pub struct RuntimeBuilder {
    pub locations: Locations,
    pub onboarding: Arc<OnboardingController>,
    pub generation: Arc<GenerationGate>,
    pub alert: Arc<dyn Fn(&str) + Send + Sync>,
}

impl RuntimeBuilder {
    pub fn build(
        &self,
        home: Option<&Path>,
        push: PushGate,
        token: u64,
    ) -> Result<WorkspaceGraph<RuntimeResources>, GraphError> {
        self.build_inner(home, push, token, false)
    }

    /// Native GUI startup opts into user-home registration discovery. Practice graphs never do.
    pub fn build_with_registered_data(
        &self,
        home: Option<&Path>,
        push: PushGate,
        token: u64,
    ) -> Result<WorkspaceGraph<RuntimeResources>, GraphError> {
        self.build_inner(home, push, token, true)
    }

    fn build_inner(
        &self,
        home: Option<&Path>,
        push: PushGate,
        token: u64,
        registered_data: bool,
    ) -> Result<WorkspaceGraph<RuntimeResources>, GraphError> {
        let mut locations = self.locations.clone();
        locations.activate_workspace(home.map(Path::to_path_buf));
        let settings = Arc::new(ShellSettings::new(locations.global_settings(), {
            let alert = self.alert.clone();
            move |message| alert(message)
        }));
        let workspace_settings = Arc::new(ShellSettings::new(locations.workspace_settings(), {
            let alert = self.alert.clone();
            move |message| alert(message)
        }));
        let templates = Arc::new(TemplateRoot::new(
            workspace_settings.clone(),
            locations.templates(),
        )?);
        let jobs = Arc::new(JobRegistry::new(locations.jobs(), {
            let templates = templates.clone();
            move || templates.path()
        })?);
        let datasets = Arc::new(DatasetPoolRegistry::new(locations.datasets())?);
        if home.is_none() {
            self.onboarding
                .bind_legacy_cleanup(crate::legacy_practice::LegacyPractice::new(
                    templates.path(),
                    locations.home(),
                    locations.global_settings(),
                    jobs.clone(),
                    datasets.clone(),
                    {
                        let alert = self.alert.clone();
                        move |message| alert(message)
                    },
                )?)?;
        }
        let presets = Arc::new(PresetRegistry::new(locations.presets())?);
        let template_files = Arc::new(TemplateFileStore::new({
            let templates = templates.clone();
            move || templates.path()
        }));
        let change = Arc::new(TemplateChangeCoordinator::new(
            &locations.template_authority(),
            jobs.clone(),
            || chrono::Local::now().format("%Y-%m-%dT%H:%M:%S").to_string(),
        )?);
        let selection = Arc::new(SlotConfigurationProduct::new(
            &locations.template_authority(),
            jobs.clone(),
            || chrono::Local::now().format("%Y-%m-%dT%H:%M:%S").to_string(),
        ));
        let selected = selection_port(selection, jobs.clone());
        let workbench = Arc::new(WorkbenchController::new(
            jobs.clone(),
            workspace_settings,
            push.clone(),
            Some(selected),
            Some(materialization_port(
                locations.template_authority(),
                jobs.clone(),
            )),
        )?);
        let job = JobController::new(
            jobs.clone(),
            datasets.clone(),
            change.clone(),
            self.generation.clone(),
            locations.workspace_settings(),
            self.alert.clone(),
        )
        .with_push_gate(push.clone())
        .with_progress_sink({
            let push = push.clone();
            let alert = self.alert.clone();
            move |progress| {
                if let Err(error) = push.push("job", &progress) {
                    alert(&format!("생성 진행 상태 전달 실패: {error}"));
                }
            }
        })
        .with_workbench_open({
            let workbench = workbench.clone();
            move |job, rows| workbench.open(job, rows)
        });
        let job = if registered_data && home.is_none() {
            job.with_registered_data({
                let datasets = datasets.clone();
                move || crate::registered_contract_data::discover_registered_data(&datasets)
            })
        } else {
            job
        };
        let job = Arc::new(job);
        let editor = Arc::new(
            EditorController::new(
                jobs.clone(),
                templates.clone(),
                datasets.clone(),
                push.clone(),
            )?
            .with_generation_gate(self.generation.clone())
            .with_binding_pending({
                let job = job.clone();
                move |name| job.binding_confirm_pending(name).map_err(Into::into)
            })
            .with_after_mapping_saved({
                let job = job.clone();
                move |name| {
                    job.after_mapping_saved(name)
                        .map(|_| ())
                        .map_err(Into::into)
                }
            })
            .with_output_directory({
                let job = job.clone();
                move || job.remembered_output_directory().map_err(Into::into)
            }),
        );
        let authoring = Arc::new(
            AuthoringController::new(&locations, jobs.clone(), push.clone())
                .with_proposal_data(datasets.clone(), {
                    let job = job.clone();
                    move || job.current_pool_source().map_err(|error| error.to_string())
                })
                .with_template_change(change)
                .with_mutation_sink({
                    let editor = editor.clone();
                    move |kind, path| editor.reconcile_template_mutation(kind, path)
                }),
        );
        let template = Arc::new(TemplateController::new_live(
            templates.clone(),
            Arc::new(crate::template_groups::GroupSettings::new(
                locations.workspace_settings(),
                {
                    let alert = self.alert.clone();
                    move |message| alert(message)
                },
            )),
            push.clone(),
            Arc::new({
                let editor = editor.clone();
                move |kind, path| editor.reconcile_template_mutation(kind, path)
            }),
            Arc::new({
                let job = job.clone();
                move |path| job.note_template_compiled(path).map_err(Into::into)
            }),
        ));
        let library = Arc::new(LibraryController::new(
            LibraryStores {
                jobs: jobs.clone(),
                datasets: datasets.clone(),
                presets,
                template_files: template_files.clone(),
            },
            locations.clone(),
            false,
            push.clone(),
            Arc::new({
                let job = job.clone();
                move |name| job.session_guard_for(name).map_err(Into::into)
            }),
            Arc::new({
                let generation = self.generation.clone();
                move || generation.is_active()
            }),
        ));
        let pool = Arc::new(PoolController::new(datasets.clone(), push.clone()));
        self.onboarding.bind_push(push, home.is_some());
        let controllers: Vec<(String, Arc<dyn ScreenController>)> = vec![
            ("authoring".into(), authoring.clone()),
            ("library".into(), library.clone()),
            ("editor".into(), editor.clone()),
            ("job".into(), job.clone()),
            ("tpl".into(), template.clone()),
            ("pool".into(), pool.clone()),
            ("workbench".into(), workbench.clone()),
            ("tutorial".into(), self.onboarding.clone()),
        ];
        Ok(WorkspaceGraph::new(
            home.map(Path::to_path_buf),
            controllers,
            RuntimeResources {
                jobs,
                datasets,
                generation: self.generation.clone(),
                settings,
                templates,
                template_files,
                template,
                authoring,
                library,
                editor,
                job,
                pool,
                workbench,
            },
            token,
        ))
    }
}
