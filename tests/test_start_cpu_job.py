from importlib import util
from pathlib import Path
from types import SimpleNamespace

from ucloud_workflow.settings import Settings


def load_start_cpu_job_module():
    module_path = Path(__file__).resolve().parents[1] / "examples" / "start_cpu_job.py"
    spec = util.spec_from_file_location("start_cpu_job", module_path)
    assert spec is not None and spec.loader is not None
    module = util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_start_cpu_job_terminates_job_and_uses_ssh_alias(monkeypatch) -> None:
    start_cpu_job = load_start_cpu_job_module()
    settings = Settings(
        server="https://cloud.sdu.dk",
        token="token",
        project="Moody's Datahub",
        mount_path="/8983017/moody_agent/",
        ssh_alias="ucloud",
        work_folder="/work/moody_agent",
    )

    terminated_job_ids: list[str] = []
    submitted_kwargs: dict[str, object] = {}

    class DummyClient:
        def __init__(self, _settings: Settings) -> None:
            self.settings = _settings

        def __enter__(self) -> "DummyClient":
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def terminate_job(self, job_id: str) -> None:
            terminated_job_ids.append(job_id)

    monkeypatch.setattr(start_cpu_job.Settings, "from_env", lambda: settings)
    monkeypatch.setattr(start_cpu_job, "UCloudClient", lambda _settings: DummyClient(_settings))
    monkeypatch.setattr(
        start_cpu_job,
        "submit_job_from_latest_template",
        lambda client, **kwargs: submitted_kwargs.update(kwargs) or SimpleNamespace(job_id="job-abc123"),
    )
    monkeypatch.setattr(start_cpu_job, "wait_for_running_job", lambda client, job_id: ({}, "ssh user@host -p 22"))
    monkeypatch.setattr(start_cpu_job, "update_ssh_config", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        start_cpu_job,
        "run_remote_python",
        lambda alias: (
            SimpleNamespace(returncode=0, stdout="ok\n", stderr="")
            if alias == settings.ssh_alias
            else (_ for _ in ()).throw(AssertionError(f"Unexpected alias: {alias!r}"))
        ),
    )

    exit_code = start_cpu_job.main()

    assert exit_code == 0
    assert submitted_kwargs["mounts"] == []
    assert terminated_job_ids == ["job-abc123"]
