from ucloud_workflow.settings import Settings


def test_settings_mount_paths_are_empty_when_mount_is_unset(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("UCLOUD_MOUNT_PATH", raising=False)

    settings = Settings.from_env(token="token", project="Moody's Datahub")

    assert settings.mount_paths == []


def test_settings_mount_paths_pick_up_optional_env_value(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("UCLOUD_MOUNT_PATH", "/123/shared-input")

    settings = Settings.from_env(token="token", project="Moody's Datahub")

    assert settings.mount_paths == ["/123/shared-input"]


def test_settings_template_job_id_picks_up_optional_env_value(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("UCLOUD_TEMPLATE_JOB_ID", "job-abc123")

    settings = Settings.from_env(token="token", project="Moody's Datahub")

    assert settings.template_job_id == "job-abc123"


def test_settings_template_job_id_is_loaded_from_dotenv_file(tmp_path, monkeypatch) -> None:
    (tmp_path / ".env").write_text("UCLOUD_TEMPLATE_JOB_ID=job-abc123\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("UCLOUD_TEMPLATE_JOB_ID", raising=False)

    settings = Settings.from_env(token="token", project="Moody's Datahub")

    assert settings.template_job_id == "job-abc123"


def test_settings_template_job_id_for_prefers_profile_specific_value(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("UCLOUD_TEMPLATE_JOB_ID", "job-global")
    monkeypatch.setenv("UCLOUD_TEMPLATE_JOB_ID_CPU_PYTHON_BATCH", "job-profile")

    settings = Settings.from_env(token="token", project="Moody's Datahub")

    assert settings.template_job_id_for("cpu-python-batch") == "job-profile"


def test_settings_template_job_id_for_falls_back_to_global(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("UCLOUD_TEMPLATE_JOB_ID", "job-global")
    monkeypatch.delenv("UCLOUD_TEMPLATE_JOB_ID_GPU_BATCH_INFERENCE", raising=False)

    settings = Settings.from_env(token="token", project="Moody's Datahub")

    assert settings.template_job_id_for("gpu-batch-inference") == "job-global"
