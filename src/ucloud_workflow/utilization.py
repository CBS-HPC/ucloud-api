from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import csv
from pathlib import Path
from statistics import fmean
from typing import Literal

from .catalog import MachineTypeInfo, machine_by_product, machine_ladder_for_product, next_machine_in_ladder


RecommendationAction = Literal["decrease", "keep", "increase"]

_LIMIT_SUFFIX_TO_UNIT = {
    "_limit_pct": "pct",
    "_limit_bytes": "bytes",
    "_limit_bytesps": "bytesps",
}

_METRIC_PRIORITY = {
    "cpu": 0,
    "memory": 1,
    "gpu": 2,
}


@dataclass(frozen=True, slots=True)
class MetricSummary:
    name: str
    unit: str
    sample_count: int
    average_value: float
    peak_value: float
    average_limit: float
    peak_limit: float
    average_utilization_of_limit_pct: float
    peak_utilization_of_limit_pct: float


@dataclass(frozen=True, slots=True)
class UtilizationReportSummary:
    report_path: Path
    sample_count: int
    start_timestamp_utc: datetime
    end_timestamp_utc: datetime
    duration_seconds: float
    metrics: tuple[MetricSummary, ...]

    def metric(self, name: str) -> MetricSummary | None:
        for metric in self.metrics:
            if metric.name == name:
                return metric
        return None

    def _metric_value(self, name: str, attribute: str, default: float = 0.0) -> float:
        metric = self.metric(name)
        if metric is None:
            return default
        return float(getattr(metric, attribute))

    @property
    def average_cpu_util_pct(self) -> float:
        return self._metric_value("cpu", "average_value")

    @property
    def peak_cpu_util_pct(self) -> float:
        return self._metric_value("cpu", "peak_value")

    @property
    def average_cpu_utilization_of_limit_pct(self) -> float:
        return self._metric_value("cpu", "average_utilization_of_limit_pct")

    @property
    def peak_cpu_utilization_of_limit_pct(self) -> float:
        return self._metric_value("cpu", "peak_utilization_of_limit_pct")

    @property
    def average_memory_bytes(self) -> float:
        return self._metric_value("memory", "average_value")

    @property
    def peak_memory_bytes(self) -> float:
        return self._metric_value("memory", "peak_value")

    @property
    def average_memory_utilization_of_limit_pct(self) -> float:
        return self._metric_value("memory", "average_utilization_of_limit_pct")

    @property
    def peak_memory_utilization_of_limit_pct(self) -> float:
        return self._metric_value("memory", "peak_utilization_of_limit_pct")

    @property
    def average_gpu_util_pct(self) -> float:
        return self._metric_value("gpu", "average_value")

    @property
    def peak_gpu_util_pct(self) -> float:
        return self._metric_value("gpu", "peak_value")

    @property
    def average_gpu_utilization_of_limit_pct(self) -> float:
        return self._metric_value("gpu", "average_utilization_of_limit_pct")

    @property
    def peak_gpu_utilization_of_limit_pct(self) -> float:
        return self._metric_value("gpu", "peak_utilization_of_limit_pct")


@dataclass(frozen=True, slots=True)
class UtilizationRecommendation:
    action: RecommendationAction
    summary: str
    reasons: tuple[str, ...]
    machine: "MachineRecommendation | None" = None


@dataclass(frozen=True, slots=True)
class MachineRecommendation:
    current_product: str
    current_machine: MachineTypeInfo | None
    suggested_machine: MachineTypeInfo | None
    ladder: tuple[MachineTypeInfo, ...]


@dataclass(frozen=True, slots=True)
class UtilizationAnalysis:
    report: UtilizationReportSummary
    recommendation: UtilizationRecommendation
    machine_recommendation: MachineRecommendation | None = None


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _ratio(value: float, limit: float) -> float:
    return value / limit if limit else 0.0


def _humanize_bytes(value: float) -> str:
    units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"]
    scaled = float(value)
    for unit in units:
        if abs(scaled) < 1024.0 or unit == units[-1]:
            return f"{scaled:.2f} {unit}"
        scaled /= 1024.0
    return f"{scaled:.2f} B"


def _titleize_metric_name(name: str) -> str:
    parts = name.split("_")
    titleized: list[str] = []
    for part in parts:
        lowered = part.lower()
        if lowered in {"cpu", "gpu", "io", "ram"}:
            titleized.append(lowered.upper())
        else:
            titleized.append(part.capitalize())
    return " ".join(titleized)


def _format_metric_value(metric: MetricSummary, value: float) -> str:
    if metric.unit == "bytes":
        return _humanize_bytes(value)
    if metric.unit == "bytesps":
        return f"{_humanize_bytes(value)}/s"
    return f"{value:.3f}"


def _resolve_value_column(metric_name: str, unit: str, columns: set[str]) -> str | None:
    if unit == "pct":
        candidates = [f"{metric_name}_util_pct", f"{metric_name}_pct"]
    elif unit == "bytes":
        candidates = [f"{metric_name}_bytes"]
    elif unit == "bytesps":
        candidates = [f"{metric_name}_bytesps"]
    else:
        candidates = [f"{metric_name}_{unit}"]

    for candidate in candidates:
        if candidate in columns:
            return candidate
    return None


def _discover_metric_specs(columns: set[str]) -> list[tuple[str, str, str, str]]:
    specs: list[tuple[str, str, str, str]] = []
    for column in columns:
        for suffix, unit in _LIMIT_SUFFIX_TO_UNIT.items():
            if not column.endswith(suffix):
                continue
            metric_name = column[: -len(suffix)]
            if not metric_name:
                continue
            value_column = _resolve_value_column(metric_name, unit, columns)
            if value_column is None:
                continue
            specs.append((metric_name, value_column, column, unit))
            break

    def sort_key(spec: tuple[str, str, str, str]) -> tuple[int, str]:
        name = spec[0]
        return (_METRIC_PRIORITY.get(name, 100), name)

    return sorted(specs, key=sort_key)


def _summarize_metric(
    rows: list[dict[str, str]],
    *,
    metric_name: str,
    value_column: str,
    limit_column: str,
    unit: str,
) -> MetricSummary:
    values: list[float] = []
    limits: list[float] = []
    for row in rows:
        value_raw = row.get(value_column)
        limit_raw = row.get(limit_column)
        if value_raw in (None, "") or limit_raw in (None, ""):
            raise ValueError(
                f"Utilization report is missing values for metric {metric_name!r} "
                f"in columns {value_column!r} and {limit_column!r}"
            )
        values.append(float(value_raw))
        limits.append(float(limit_raw))

    ratios = [_ratio(value, limit) for value, limit in zip(values, limits, strict=True)]
    return MetricSummary(
        name=metric_name,
        unit=unit,
        sample_count=len(rows),
        average_value=fmean(values),
        peak_value=max(values),
        average_limit=fmean(limits),
        peak_limit=max(limits),
        average_utilization_of_limit_pct=fmean(ratios) * 100.0,
        peak_utilization_of_limit_pct=max(ratios) * 100.0,
    )


def summarize_job_report(report_path: Path) -> UtilizationReportSummary:
    if not report_path.exists():
        raise FileNotFoundError(f"Missing utilization report: {report_path}")

    with report_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    if not rows:
        raise ValueError(f"Utilization report is empty: {report_path}")

    required_columns = ("timestamp_utc",)
    missing_columns = [column for column in required_columns if column not in rows[0]]
    if missing_columns:
        raise ValueError(
            f"Utilization report {report_path} is missing columns: {', '.join(missing_columns)}"
        )

    timestamps = [_parse_timestamp(row["timestamp_utc"]) for row in rows]
    columns = set(rows[0].keys())
    metric_specs = _discover_metric_specs(columns)
    if not metric_specs:
        raise ValueError(
            f"Utilization report {report_path} does not contain any supported metric pairs"
        )

    metrics = tuple(
        _summarize_metric(
            rows,
            metric_name=metric_name,
            value_column=value_column,
            limit_column=limit_column,
            unit=unit,
        )
        for metric_name, value_column, limit_column, unit in metric_specs
    )

    start_timestamp_utc = min(timestamps)
    end_timestamp_utc = max(timestamps)
    duration_seconds = max((end_timestamp_utc - start_timestamp_utc).total_seconds(), 0.0)

    return UtilizationReportSummary(
        report_path=report_path,
        sample_count=len(rows),
        start_timestamp_utc=start_timestamp_utc,
        end_timestamp_utc=end_timestamp_utc,
        duration_seconds=duration_seconds,
        metrics=metrics,
    )


def _pressure_score(metric: MetricSummary) -> float:
    return max(metric.average_utilization_of_limit_pct, metric.peak_utilization_of_limit_pct)


def _is_memory_metric(metric: MetricSummary) -> bool:
    return "memory" in metric.name


def _is_gpu_metric(metric: MetricSummary) -> bool:
    return metric.name.startswith("gpu")


def _high_pressure_reason(metric: MetricSummary) -> str | None:
    label = _titleize_metric_name(metric.name)
    average = metric.average_utilization_of_limit_pct
    peak = metric.peak_utilization_of_limit_pct

    if _is_memory_metric(metric):
        if peak >= 95.0 or average >= 85.0:
            return (
                f"{label} is at critical pressure: average {average:.2f}% of limit, "
                f"peak {peak:.2f}% of limit. This is close to out-of-memory territory."
            )
        if peak >= 90.0 or average >= 80.0:
            return (
                f"{label} is heavily loaded: average {average:.2f}% of limit, "
                f"peak {peak:.2f}% of limit. Consider more memory to avoid crashes."
            )

    if peak >= 95.0 or average >= 85.0:
        return (
            f"{label} is at critical pressure: average {average:.2f}% of limit, "
            f"peak {peak:.2f}% of limit."
        )
    if peak >= 90.0 or average >= 80.0:
        return (
            f"{label} is heavily loaded: average {average:.2f}% of limit, "
            f"peak {peak:.2f}% of limit."
        )
    return None


def _low_pressure_summary(metrics: tuple[MetricSummary, ...]) -> str:
    names = ", ".join(_titleize_metric_name(metric.name) for metric in metrics)
    return f"All tracked resources are lightly used ({names})."


def _resource_usage_lines(metrics: tuple[MetricSummary, ...]) -> list[str]:
    lines: list[str] = []
    for metric in metrics:
        label = _titleize_metric_name(metric.name)
        average_value = _format_metric_value(metric, metric.average_value)
        peak_value = _format_metric_value(metric, metric.peak_value)
        average_limit = _format_metric_value(metric, metric.average_limit)
        peak_limit = _format_metric_value(metric, metric.peak_limit)
        lines.append(
            f"- {label}: average {average_value} ({metric.average_utilization_of_limit_pct:.2f}% of limit, limit {average_limit}), "
        )
        lines[-1] += f"peak {peak_value} ({metric.peak_utilization_of_limit_pct:.2f}% of limit, peak limit {peak_limit})"
    return lines


def _machine_capacity_summary(machine: MachineTypeInfo) -> str:
    parts: list[str] = []
    if machine.cpu_vcpus is not None:
        parts.append(f"{machine.cpu_vcpus} vCPU")
    if machine.cpu_model:
        parts.append(machine.cpu_model)
    if machine.memory_gib is not None:
        parts.append(f"{machine.memory_gib} GiB RAM")
    if machine.memory_type:
        parts.append(machine.memory_type)
    if machine.gpu_count is not None:
        parts.append(f"{machine.gpu_count} GPU")
    if machine.gpu_model:
        parts.append(machine.gpu_model)
    if machine.mig_instances is not None:
        parts.append(f"{machine.mig_instances} MIG")
    if machine.mig_profile:
        parts.append(machine.mig_profile)
    return ", ".join(parts) if parts else machine.product


def recommend_machine_size(summary: UtilizationReportSummary) -> UtilizationRecommendation:
    metrics = summary.metrics
    if not metrics:
        raise ValueError("Utilization summary does not contain any metric series")

    high_pressure_metrics = [metric for metric in metrics if _pressure_score(metric) >= 80.0]
    critical_pressure_metrics = [metric for metric in metrics if _pressure_score(metric) >= 90.0]

    if critical_pressure_metrics:
        reasons = [reason for metric in critical_pressure_metrics if (reason := _high_pressure_reason(metric))]
        summary_text = "The job is close to saturation; increase machine size and rerun."
        if any(_is_memory_metric(metric) for metric in critical_pressure_metrics):
            summary_text = (
                "Memory pressure is very high and may cause crashes; increase machine size or memory capacity."
            )
        return UtilizationRecommendation(
            action="increase",
            summary=summary_text,
            reasons=tuple(reasons),
        )

    if high_pressure_metrics:
        reasons = [reason for metric in high_pressure_metrics if (reason := _high_pressure_reason(metric))]
        summary_text = "The job is close to saturation; increase machine size and rerun."
        if any(_is_memory_metric(metric) for metric in high_pressure_metrics):
            summary_text = "The job appears memory-bound; increase machine size to reduce crash risk."
        elif any(_is_gpu_metric(metric) for metric in high_pressure_metrics):
            summary_text = "The GPU workload is close to saturation; increase machine size or GPU capacity."
        return UtilizationRecommendation(
            action="increase",
            summary=summary_text,
            reasons=tuple(reasons),
        )

    if all(
        metric.peak_utilization_of_limit_pct <= 25.0 and metric.average_utilization_of_limit_pct <= 15.0
        for metric in metrics
    ):
        return UtilizationRecommendation(
            action="decrease",
            summary=_low_pressure_summary(metrics) + " Decrease machine size.",
            reasons=tuple(
                f"{_titleize_metric_name(metric.name)} averaged {metric.average_utilization_of_limit_pct:.2f}% of its limit "
                f"and peaked at {metric.peak_utilization_of_limit_pct:.2f}%."
                for metric in metrics
            ),
        )

    if all(
        metric.peak_utilization_of_limit_pct <= 40.0 and metric.average_utilization_of_limit_pct <= 25.0
        for metric in metrics
    ):
        return UtilizationRecommendation(
            action="decrease",
            summary="The job still has substantial headroom; test one smaller machine size.",
            reasons=tuple(
                f"{_titleize_metric_name(metric.name)} averaged {metric.average_utilization_of_limit_pct:.2f}% of its limit "
                f"and peaked at {metric.peak_utilization_of_limit_pct:.2f}%."
                for metric in metrics
            ),
        )

    return UtilizationRecommendation(
        action="keep",
        summary="The current machine size looks reasonable based on the observed utilization.",
        reasons=tuple(
            f"{_titleize_metric_name(metric.name)} averaged {metric.average_utilization_of_limit_pct:.2f}% of its limit "
            f"and peaked at {metric.peak_utilization_of_limit_pct:.2f}%."
            for metric in metrics
        ),
    )


def recommend_next_machine(
    current_machine_product: str | None,
    action: RecommendationAction,
) -> MachineRecommendation | None:
    if current_machine_product is None:
        return None

    current_machine = machine_by_product(current_machine_product)
    ladder = machine_ladder_for_product(current_machine_product)
    if current_machine is None:
        return MachineRecommendation(
            current_product=current_machine_product,
            current_machine=None,
            suggested_machine=None,
            ladder=ladder,
        )

    suggested_machine = current_machine if action == "keep" else next_machine_in_ladder(current_machine_product, action)
    return MachineRecommendation(
        current_product=current_machine_product,
        current_machine=current_machine,
        suggested_machine=suggested_machine,
        ladder=ladder,
    )


def analyze_job_report(
    report_path: Path,
    *,
    current_machine_product: str | None = None,
) -> UtilizationAnalysis:
    summary = summarize_job_report(report_path)
    recommendation = recommend_machine_size(summary)
    machine_recommendation = recommend_next_machine(current_machine_product, recommendation.action)
    return UtilizationAnalysis(
        report=summary,
        recommendation=UtilizationRecommendation(
            action=recommendation.action,
            summary=recommendation.summary,
            reasons=recommendation.reasons,
            machine=machine_recommendation,
        ),
        machine_recommendation=machine_recommendation,
    )


def render_utilization_analysis(analysis: UtilizationAnalysis) -> str:
    summary = analysis.report
    recommendation = analysis.recommendation
    lines = [
        "# Utilization analysis",
        "",
        f"- Report: `{summary.report_path}`",
        f"- Samples: {summary.sample_count}",
        f"- Time span: {summary.start_timestamp_utc.isoformat()} -> {summary.end_timestamp_utc.isoformat()}",
        f"- Duration: {summary.duration_seconds:.1f} seconds",
        "",
        "## Resource usage",
        "",
    ]
    lines.extend(_resource_usage_lines(summary.metrics))
    lines.extend(
        [
            "",
            "## Recommendation",
            "",
            f"- Action: `{recommendation.action}`",
            f"- Summary: {recommendation.summary}",
        ]
    )
    if recommendation.reasons:
        lines.append("- Reasons:")
        lines.extend(f"  - {reason}" for reason in recommendation.reasons)
    if analysis.machine_recommendation is not None:
        machine = analysis.machine_recommendation
        lines.extend(["", "## Machine suggestion", "", f"- Current machine: `{machine.current_product}`"])
        if machine.current_machine is not None:
            lines.append(f"- Current capacity: {_machine_capacity_summary(machine.current_machine)}")
        if machine.suggested_machine is None:
            lines.append("- Suggested machine: no adjacent machine in this ladder")
        elif machine.suggested_machine.product == machine.current_product:
            lines.append("- Suggested machine: keep the current machine")
        else:
            lines.append(f"- Suggested machine: `{machine.suggested_machine.product}`")
            lines.append(f"- Suggested capacity: {_machine_capacity_summary(machine.suggested_machine)}")
        if machine.ladder:
            lines.append("- Ladder: " + " -> ".join(item.product for item in machine.ladder))
    lines.append("")
    return "\n".join(lines)
