### Database Dictionary – Password Intelligence

Tables
- password_statistics
  - id INTEGER PK
  - date DATE UNIQUE
  - total_attempts INTEGER
  - unique_passwords INTEGER
  - breached_count INTEGER
  - novel_count INTEGER
  - max_prevalence INTEGER
- password_tracking
  - id INTEGER PK
  - password_hash TEXT(64) UNIQUE INDEX
  - password_text TEXT (stored for back-compat; avoid exporting)
  - breached BOOLEAN
  - breach_prevalence INTEGER
  - last_hibp_check TIMESTAMP
  - first_seen TIMESTAMP
  - last_seen TIMESTAMP
  - times_seen INTEGER
  - unique_sessions INTEGER
- password_session_usage
  - id INTEGER PK
  - password_id INTEGER FK -> password_tracking.id
  - session_id TEXT FK -> session_summaries.session_id
  - username TEXT
  - success BOOLEAN
  - timestamp TIMESTAMP

Crosswalk to Longtail JSON
- breached_count -> breached_passwords (aggregated)
- max_prevalence -> breach_prevalence_max
- password_hash -> novel_password_hashes (when not breached)
- session_id -> sessions_with_breached

Security
- Do not export `password_text` outside of internal use. JSON outputs must only include SHA-256 hashes.

