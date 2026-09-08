"""The M1 audit report (requirement 13), persisted and rendered."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from fiorino.data.identity.audit import BLOCKING, Finding

from .checks import COUNT_QUERIES, run_all_checks

__all__ = ["QualityReport", "generate_report", "render_markdown"]


@dataclass
class QualityReport:
    dq_run_id: str
    generated_at: datetime
    counts: dict[str, int]
    findings: list[Finding]
    teams_by_source: list[tuple[str, int]] = field(default_factory=list)
    coverage: list[tuple] = field(default_factory=list)
    cross_source: list[tuple] = field(default_factory=list)

    @property
    def blocking(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == BLOCKING]

    @property
    def passed(self) -> bool:
        return not self.blocking


def generate_report(con, *, persist: bool = True, code_version: str | None = None) -> QualityReport:
    dq_run_id = "dq_" + uuid.uuid4().hex[:10]
    started = datetime.now(timezone.utc)

    counts = {name: con.execute(sql).fetchone()[0] for name, sql in COUNT_QUERIES.items()}
    findings = run_all_checks(con)

    teams_by_source = con.execute(
        """SELECT source, count(DISTINCT team_id) FROM team_aliases
           WHERE status='APPROVED' GROUP BY source ORDER BY source"""
    ).fetchall()
    coverage = con.execute(
        "SELECT competition_id, season_id, n_matches, n_with_result, result_coverage "
        "FROM v_coverage ORDER BY competition_id, season_id"
    ).fetchall()
    cross_source = con.execute(
        "SELECT n_sources, count(*) FROM v_cross_source_matches GROUP BY 1 ORDER BY 1"
    ).fetchall()

    report = QualityReport(dq_run_id, started, counts, findings,
                           teams_by_source, coverage, cross_source)

    if persist:
        con.execute(
            """INSERT INTO data_quality_runs
               (dq_run_id, started_at, finished_at, status, n_findings, n_blocking, code_version)
               VALUES (?, ?, now(), ?, ?, ?, ?)""",
            [dq_run_id, started, "PASS" if report.passed else "FAIL",
             len(findings), len(report.blocking), code_version],
        )
        for f in findings:
            con.execute(
                """INSERT INTO data_quality_findings
                   (dq_run_id, check_name, severity, entity, detail, n_affected)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                [dq_run_id, f.check_name, f.severity, f.entity, f.detail, f.n_affected],
            )
    return report


def render_markdown(report: QualityReport) -> str:
    lines = [
        "# Fiorino Quant — M1 data quality audit",
        "",
        f"Run `{report.dq_run_id}` · {report.generated_at.isoformat(timespec='seconds')}",
        "",
        f"**Status: {'PASS' if report.passed else 'FAIL'}** — "
        f"{len(report.blocking)} blocking, "
        f"{len(report.findings) - len(report.blocking)} non-blocking",
        "",
        "## Counts",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
    ]
    lines += [f"| {k.replace('_', ' ')} | {v:,} |" for k, v in report.counts.items()]

    lines += ["", "## Teams by source", "", "| Source | Distinct teams |", "| --- | ---: |"]
    lines += [f"| {s} | {n:,} |" for s, n in report.teams_by_source]

    lines += ["", "## Cross-source corroboration", "",
              "| Sources per match | Matches |", "| ---: | ---: |"]
    lines += [f"| {n} | {c:,} |" for n, c in report.cross_source]

    lines += ["", "## Coverage by competition and season", "",
              "| Competition | Season | Matches | With result | Coverage |",
              "| --- | --- | ---: | ---: | ---: |"]
    for comp, season, n, with_res, cov in report.coverage:
        lines.append(f"| {comp} | {season} | {n:,} | {with_res:,} | {(cov or 0):.1%} |")

    lines += ["", "## Findings", ""]
    if not report.findings:
        lines.append("No findings.")
    else:
        lines += ["| Severity | Check | Detail | Affected |", "| --- | --- | --- | ---: |"]
        order = {"BLOCKING": 0, "WARNING": 1, "INFO": 2}
        for f in sorted(report.findings, key=lambda x: (order.get(x.severity, 9), x.check_name)):
            lines.append(f"| {f.severity} | {f.check_name} | {f.detail} | {f.n_affected:,} |")
    return "\n".join(lines) + "\n"
