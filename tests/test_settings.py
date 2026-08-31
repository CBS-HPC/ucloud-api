from ucloud_workflow.settings import Settings


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


def test_settings_uses_configured_ssh_config_and_discovers_its_private_keys(
    tmp_path,
    monkeypatch,
) -> None:
    config_path = tmp_path / "portable-ssh" / "config"
    config_path.parent.mkdir()
    ed25519_key = config_path.parent / "id_ed25519"
    rsa_key = config_path.parent / "id_rsa"
    ed25519_key.write_text("private key", encoding="utf-8")
    rsa_key.write_text("private key", encoding="utf-8")
    (config_path.parent / "id_ed25519.pub").write_text("public key", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("UCLOUD_SSH_CONFIG_PATH", str(config_path))
    monkeypatch.delenv("UCLOUD_SSH_IDENTITY_FILE", raising=False)

    settings = Settings.from_env(token="token", project="Moody's Datahub")

    assert settings.ssh_config_path == config_path
    assert settings.resolved_ssh_identity_files() == (rsa_key, ed25519_key)


def test_settings_uses_explicit_ssh_identity_file_over_discovery(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "ssh" / "config"
    config_path.parent.mkdir()
    (config_path.parent / "id_ed25519").write_text("discovered", encoding="utf-8")
    explicit_key = tmp_path / "keys" / "ucloud_ed25519"
    explicit_key.parent.mkdir()
    explicit_key.write_text("explicit", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("UCLOUD_SSH_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("UCLOUD_SSH_IDENTITY_FILE", str(explicit_key))

    settings = Settings.from_env(token="token", project="Moody's Datahub")

    assert settings.resolved_ssh_identity_files() == (explicit_key,)
