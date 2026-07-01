from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from ucloud_workflow.utilization import analyze_job_report, render_utilization_analysis


def write_report(path: Path, rows: list[tuple[str, float, float, float, float]]) -> Path:
    lines = [
        "timestamp_utc,cpu_util_pct,cpu_limit_pct,memory_bytes,memory_limit_bytes",
    ]
    for timestamp, cpu_util_pct, cpu_limit_pct, memory_bytes, memory_limit_bytes in rows:
        lines.append(
            f"{timestamp},{cpu_util_pct:.3f},{cpu_limit_pct:.3f},{memory_bytes:.3f},{memory_limit_bytes:.3f}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_gpu_report(
    path: Path,
    rows: list[tuple[str, float, float, float, float, float, float, float, float]],
) -> Path:
    lines = [
        "timestamp_utc,cpu_util_pct,cpu_limit_pct,memory_bytes,memory_limit_bytes,gpu_util_pct,gpu_limit_pct,gpu_memory_bytes,gpu_memory_limit_bytes",
    ]
    for (
        timestamp,
        cpu_util_pct,
        cpu_limit_pct,
        memory_bytes,
        memory_limit_bytes,
        gpu_util_pct,
        gpu_limit_pct,
        gpu_memory_bytes,
        gpu_memory_limit_bytes,
    ) in rows:
        lines.append(
            f"{timestamp},{cpu_util_pct:.3f},{cpu_limit_pct:.3f},{memory_bytes:.3f},{memory_limit_bytes:.3f},"
            f"{gpu_util_pct:.3f},{gpu_limit_pct:.3f},{gpu_memory_bytes:.3f},{gpu_memory_limit_bytes:.3f}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_analyze_job_report_recommends_decrease(tmp_path: Path) -> None:
    report_path = write_report(
        tmp_path / "job-report.csv",
        [
            ("2026-06-11T07:55:39.621Z", 120.0, 12800.0, 110_000_000.0, 384_000_000_000.0),
            ("2026-06-11T07:55:40.621Z", 80.0, 12800.0, 100_000_000.0, 384_000_000_000.0),
            ("2026-06-11T07:55:41.621Z", 90.0, 12800.0, 105_000_000.0, 384_000_000_000.0),
        ],
    )

    analysis = analyze_job_report(report_path)

    assert analysis.recommendation.action == "decrease"
    assert analysis.report.sample_count == 3
    assert analysis.report.peak_cpu_utilization_of_limit_pct < 20.0
    assert "decrease" in analysis.recommendation.summary.lower()
    assert "Utilization analysis" in render_utilization_analysis(analysis)


def test_analyze_job_report_includes_next_machine_suggestion(tmp_path: Path) -> None:
    report_path = write_report(
        tmp_path / "job-report.csv",
        [
            ("2026-06-11T07:55:39.621Z", 120.0, 12800.0, 110_000_000.0, 384_000_000_000.0),
            ("2026-06-11T07:55:40.621Z", 80.0, 12800.0, 100_000_000.0, 384_000_000_000.0),
        ],
    )

    analysis = analyze_job_report(report_path, current_machine_product="cpu-amd-zen5-64-vcpu")
    rendered = render_utilization_analysis(analysis)

    assert analysis.recommendation.action == "decrease"
    assert analysis.machine_recommendation is not None
    assert analysis.machine_recommendation.suggested_machine is not None
    assert analysis.machine_recommendation.suggested_machine.product == "cpu-amd-zen5-32-vcpu"
    assert "Current machine: `cpu-amd-zen5-64-vcpu`" in rendered
    assert "Suggested machine: `cpu-amd-zen5-32-vcpu`" in rendered


def test_analyze_job_report_recommends_increase(tmp_path: Path) -> None:
    report_path = write_report(
        tmp_path / "job-report.csv",
        [
            ("2026-06-11T07:55:39.621Z", 12000.0, 12800.0, 300_000_000_000.0, 384_000_000_000.0),
            ("2026-06-11T07:55:40.621Z", 12300.0, 12800.0, 350_000_000_000.0, 384_000_000_000.0),
            ("2026-06-11T07:55:41.621Z", 12750.0, 12800.0, 380_000_000_000.0, 384_000_000_000.0),
        ],
    )

    analysis = analyze_job_report(report_path)

    assert analysis.recommendation.action == "increase"
    assert analysis.report.peak_cpu_utilization_of_limit_pct > 85.0
    assert analysis.report.peak_memory_utilization_of_limit_pct > 85.0


def test_analyze_job_report_handles_gpu_reports_and_memory_pressure(tmp_path: Path) -> None:
    report_path = write_gpu_report(
        tmp_path / "job-report.csv",
        [
            (
                "2026-06-11T07:55:39.621Z",
                120.0,
                12800.0,
                365_000_000_000.0,
                384_000_000_000.0,
                5000.0,
                6000.0,
                20_000_000_000.0,
                24_000_000_000.0,
            ),
            (
                "2026-06-11T07:55:40.621Z",
                90.0,
                12800.0,
                372_000_000_000.0,
                384_000_000_000.0,
                5500.0,
                6000.0,
                21_000_000_000.0,
                24_000_000_000.0,
            ),
        ],
    )

    analysis = analyze_job_report(report_path)

    assert analysis.report.metric("gpu") is not None
    assert analysis.recommendation.action == "increase"
    assert "memory" in analysis.recommendation.summary.lower()
    assert "gpu" in render_utilization_analysis(analysis).lower()


def test_analyze_job_report_script(tmp_path: Path) -> None:
    report_path = write_report(
        tmp_path / "job-report.csv",
        [
            ("2026-06-11T07:55:39.621Z", 120.0, 12800.0, 110_000_000.0, 384_000_000_000.0),
            ("2026-06-11T07:55:40.621Z", 80.0, 12800.0, 100_000_000.0, 384_000_000_000.0),
        ],
    )
    script_path = Path(__file__).resolve().parents[1] / "examples" / "analyze_job_report.py"

    completed = subprocess.run(
        [sys.executable, str(script_path), str(report_path), "--current-machine", "cpu-amd-zen5-64-vcpu"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "Utilization analysis" in completed.stdout
    assert "Action: `decrease`" in completed.stdout
    assert "Suggested machine: `cpu-amd-zen5-32-vcpu`" in completed.stdout
