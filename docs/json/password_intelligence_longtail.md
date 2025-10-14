### Password Intelligence - Longtail JSON Output

This document defines the JSON fields emitted by longtail analysis when password intelligence is enabled.

- version: 1.0
- producer: `cowrieprocessor.threat_detection.longtail.LongtailAnalyzer`
- audience: downstream analytics, MCP-based Elastic query engine

Fields
- total_attempts (int): Count of login password attempts considered across analyzed sessions.
- unique_passwords (int): Count of distinct passwords observed (from stored enrichment).
- breached_passwords (int): Total attempts where the password is known breached.
- breach_prevalence_max (int): Maximum HIBP breach prevalence observed among attempts.
- novel_password_hashes (list[str]): Sample of SHA-256 password hashes not seen as breached (capped at 100).
- sessions_with_breached (list[str]): Session IDs with at least one breached password attempt (capped at 100).
- enriched_gap_sessions (list[str]): Session IDs that were opportunistically enriched due to missing stats.
- enriched_details_sample (list[object]): Sample records (max 50) with keys:
  - session_id (str)
  - username (str)
  - password_sha256 (str)
  - breached (bool)
  - prevalence (int)
  - timestamp (str)
- indicator_score (float): 0.0–1.0 heuristic indicator for password risk.

Examples
```json
{
  "total_attempts": 124,
  "unique_passwords": 37,
  "breached_passwords": 19,
  "breach_prevalence_max": 4821,
  "novel_password_hashes": ["5e884898da..."],
  "sessions_with_breached": ["c0ffee01"],
  "enriched_gap_sessions": ["deadbeef"],
  "enriched_details_sample": [
    {
      "session_id": "deadbeef",
      "username": "root",
      "password_sha256": "5e884898da...",
      "breached": true,
      "prevalence": 4821,
      "timestamp": "2025-10-12T18:22:01Z"
    }
  ],
  "indicator_score": 0.71
}
```

Notes
- Cleartext passwords are never emitted; only SHA-256 hashes appear.
- Opportunistic enrichment uses k-anonymity HIBP API and rate limiting.

