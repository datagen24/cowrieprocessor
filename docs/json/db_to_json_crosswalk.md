### DB → JSON Crosswalk (Password Intelligence)

Mappings
- password_statistics.breached_count → password_intelligence_longtail.breached_passwords
- password_statistics.max_prevalence → password_intelligence_longtail.breach_prevalence_max
- password_tracking.password_hash (non-breached) → password_intelligence_longtail.novel_password_hashes
- password_session_usage.session_id (where password_tracking.breached = true) → password_intelligence_longtail.sessions_with_breached

Derived
- indicator_score is derived from breached ratios, session ratios, and prevalence; no direct DB column.
- total_attempts combines stored enrichment and any opportunistic checks during analysis.

