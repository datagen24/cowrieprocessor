"""Report builder implementations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Dict, Iterable, List, Optional

from .dal import (
    CommandStatRow,
    EnrichedSessionRow,
    FileDownloadRow,
    ReportingRepository,
    SessionStatistics,
)


@dataclass(slots=True)
class ReportContext:
    """Context describing the reporting interval and sensor filter."""

    start: datetime
    end: datetime
    date_label: str
    sensor: Optional[str]


class BaseReportBuilder:
    """Base class for report builders."""

    def __init__(self, repository: ReportingRepository, top_n: int = 10) -> None:
        """Initialise builder with repository and top N configuration."""
        self.repository = repository
        self.top_n = top_n

    def build(self, context: ReportContext) -> Dict[str, object]:
        """Build a report for the supplied context."""
        raise NotImplementedError

    def _base_payload(self, report_type: str, context: ReportContext) -> Dict[str, object]:
        """Return base metadata shared by all report types."""
        now = datetime.now(UTC).isoformat()
        return {
            "@timestamp": now,
            "generated_at": now,
            "report_type": report_type,
            "date": context.date_label,
            "sensor": context.sensor or "aggregate",
        }


class DailyReportBuilder(BaseReportBuilder):
    """Construct daily reports from aggregated session data."""

    def build(self, context: ReportContext) -> Dict[str, object]:
        """Build a daily report payload."""
        payload = self._base_payload("daily", context)

        stats = self.repository.session_stats(context.start, context.end, context.sensor)
        commands = list(self.repository.top_commands(context.start, context.end, self.top_n, context.sensor))
        downloads = list(self.repository.top_file_downloads(context.start, context.end, self.top_n, context.sensor))
        enrichments = self.repository.enriched_sessions(context.start, context.end, sensor=context.sensor)

        payload["sessions"] = _session_stats_dict(stats)
        payload["commands"] = _top_commands(commands)
        payload["files"] = _top_downloads(downloads)
        payload["enrichments"] = _enrichment_summary(enrichments)
        # Optional: add password intelligence hints if the repository exposes them later
        # payload["password_intelligence"] = self.repository.password_intelligence_hints(...)
        return payload


class WeeklyReportBuilder(BaseReportBuilder):
    """Construct weekly reports from aggregated session data."""

    def build(self, context: ReportContext) -> Dict[str, object]:
        """Build a weekly report payload."""
        payload = self._base_payload("weekly", context)
        stats = self.repository.session_stats(context.start, context.end, context.sensor)
        payload["sessions"] = _session_stats_dict(stats)
        return payload


class MonthlyReportBuilder(BaseReportBuilder):
    """Construct monthly reports from aggregated session data."""

    def build(self, context: ReportContext) -> Dict[str, object]:
        """Build a monthly report payload."""
        payload = self._base_payload("monthly", context)
        stats = self.repository.session_stats(context.start, context.end, context.sensor)
        payload["sessions"] = _session_stats_dict(stats)
        return payload


def build_context_for_date(date_str: str, sensor: Optional[str] = None) -> ReportContext:
    """Create a daily report context for the supplied date string."""
    start = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=UTC)
    end = start + timedelta(days=1)
    return ReportContext(start=start, end=end, date_label=date_str, sensor=sensor)


def _session_stats_dict(stats: SessionStatistics) -> Dict[str, object]:
    return {
        "total": stats.total_sessions,
        "avg_commands": round(stats.avg_commands, 2),
        "max_commands": stats.max_commands,
        "min_commands": stats.min_commands,
        "file_downloads": stats.file_downloads,
        "login_attempts": stats.login_attempts,
        "vt_flagged": stats.vt_flagged,
        "dshield_flagged": stats.dshield_flagged,
        "unique_ips": stats.unique_ips,
    }


def _top_commands(rows: Iterable[CommandStatRow]) -> Dict[str, object]:
    return {
        "top": [
            {
                "command": row.command,
                "occurrences": row.occurrences,
            }
            for row in rows
        ]
    }


def _top_downloads(rows: Iterable[FileDownloadRow]) -> Dict[str, object]:
    return {
        "top": [
            {
                "url": row.url,
                "occurrences": row.occurrences,
            }
            for row in rows
        ]
    }


def _enrichment_summary(rows: Iterable[EnrichedSessionRow]) -> Dict[str, object]:
    entries = []
    for row in rows:
        ips: List[Dict[str, object]] = []
        files: List[Dict[str, object]] = []
        entry: Dict[str, object] = {
            "session": row.session_id,
            "sensor": row.sensor or "aggregate",
            "first_seen": row.first_event_at.isoformat() if row.first_event_at else None,
            "last_seen": row.last_event_at.isoformat() if row.last_event_at else None,
            "ips": ips,
            "files": files,
        }

        session_data = row.enrichment.get("session", {})
        if isinstance(session_data, dict):
            for ip, details in list(session_data.items())[:3]:
                ip_entry: Dict[str, object] = {"ip": ip}
                if isinstance(details, dict):
                    if "dshield" in details:
                        ip_entry["dshield"] = details.get("dshield")
                    if "urlhaus" in details:
                        ip_entry["urlhaus"] = details.get("urlhaus")
                    if "spur" in details:
                        ip_entry["spur"] = details.get("spur")
                ips.append(ip_entry)

        vt_data = row.enrichment.get("virustotal", {})
        if isinstance(vt_data, dict):
            for file_hash, payload in list(vt_data.items())[:3]:
                vt_entry: Dict[str, object] = {"hash": file_hash}
                attributes = {}
                if isinstance(payload, dict):
                    data_obj = payload.get("data")
                    if isinstance(data_obj, dict):
                        attributes = data_obj.get("attributes", {})
                if isinstance(attributes, dict):
                    stats = attributes.get("last_analysis_stats", {})
                    if isinstance(stats, dict) and "malicious" in stats:
                        vt_entry["malicious"] = stats.get("malicious")
                    classification = attributes.get("popular_threat_classification")
                    if isinstance(classification, dict):
                        label = classification.get("suggested_threat_label")
                        if label:
                            vt_entry["label"] = label
                    first_seen = attributes.get("first_submission_date")
                    if first_seen:
                        vt_entry["first_seen"] = first_seen
                files.append(vt_entry)

        entries.append(entry)

    return {"flagged": entries}
