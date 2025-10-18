-- Longtail Analysis Reporting Queries
-- Common time window queries for historical analysis data

-- ============================================================================
-- QUARTERLY REPORTS
-- ============================================================================

-- Q1 2024 Analysis Summary
SELECT 
    'Q1 2024' as period,
    COUNT(*) as total_analyses,
    SUM(rare_command_count) as total_rare_commands,
    SUM(outlier_session_count) as total_outlier_sessions,
    AVG(confidence_score) as avg_confidence,
    MIN(window_start) as earliest_analysis,
    MAX(window_end) as latest_analysis
FROM longtail_analysis 
WHERE window_start >= '2024-01-01' 
  AND window_end < '2024-04-01';

-- Q2 2024 Analysis Summary  
SELECT 
    'Q2 2024' as period,
    COUNT(*) as total_analyses,
    SUM(rare_command_count) as total_rare_commands,
    SUM(outlier_session_count) as total_outlier_sessions,
    AVG(confidence_score) as avg_confidence,
    MIN(window_start) as earliest_analysis,
    MAX(window_end) as latest_analysis
FROM longtail_analysis 
WHERE window_start >= '2024-04-01' 
  AND window_end < '2024-07-01';

-- Q3 2024 Analysis Summary
SELECT 
    'Q3 2024' as period,
    COUNT(*) as total_analyses,
    SUM(rare_command_count) as total_rare_commands,
    SUM(outlier_session_count) as total_outlier_sessions,
    AVG(confidence_score) as avg_confidence,
    MIN(window_start) as earliest_analysis,
    MAX(window_end) as latest_analysis
FROM longtail_analysis 
WHERE window_start >= '2024-07-01' 
  AND window_end < '2024-10-01';

-- Q4 2024 Analysis Summary
SELECT 
    'Q4 2024' as period,
    COUNT(*) as total_analyses,
    SUM(rare_command_count) as total_rare_commands,
    SUM(outlier_session_count) as total_outlier_sessions,
    AVG(confidence_score) as avg_confidence,
    MIN(window_start) as earliest_analysis,
    MAX(window_end) as latest_analysis
FROM longtail_analysis 
WHERE window_start >= '2024-10-01' 
  AND window_end < '2025-01-01';

-- ============================================================================
-- MONTHLY REPORTS
-- ============================================================================

-- Monthly Analysis Summary (Last 12 months)
SELECT 
    DATE_TRUNC('month', window_start) as month,
    COUNT(*) as total_analyses,
    SUM(rare_command_count) as total_rare_commands,
    SUM(outlier_session_count) as total_outlier_sessions,
    AVG(confidence_score) as avg_confidence,
    SUM(total_events_analyzed) as total_events
FROM longtail_analysis 
WHERE window_start >= CURRENT_DATE - INTERVAL '12 months'
GROUP BY DATE_TRUNC('month', window_start)
ORDER BY month DESC;

-- ============================================================================
-- WEEKLY REPORTS
-- ============================================================================

-- Weekly Analysis Summary (Last 12 weeks)
SELECT 
    DATE_TRUNC('week', window_start) as week,
    COUNT(*) as total_analyses,
    SUM(rare_command_count) as total_rare_commands,
    SUM(outlier_session_count) as total_outlier_sessions,
    AVG(confidence_score) as avg_confidence,
    SUM(total_events_analyzed) as total_events
FROM longtail_analysis 
WHERE window_start >= CURRENT_DATE - INTERVAL '12 weeks'
GROUP BY DATE_TRUNC('week', window_start)
ORDER BY week DESC;

-- ============================================================================
-- DAILY REPORTS
-- ============================================================================

-- Daily Analysis Summary (Last 30 days)
SELECT 
    DATE_TRUNC('day', window_start) as day,
    COUNT(*) as total_analyses,
    SUM(rare_command_count) as total_rare_commands,
    SUM(outlier_session_count) as total_outlier_sessions,
    AVG(confidence_score) as avg_confidence,
    SUM(total_events_analyzed) as total_events
FROM longtail_analysis 
WHERE window_start >= CURRENT_DATE - INTERVAL '30 days'
GROUP BY DATE_TRUNC('day', window_start)
ORDER BY day DESC;

-- ============================================================================
-- TOP THREATS BY PERIOD
-- ============================================================================

-- Top Rare Commands (Last 30 days)
SELECT 
    ld.detection_data->>'command' as command,
    COUNT(*) as detection_count,
    AVG(ld.confidence_score) as avg_confidence,
    AVG(ld.severity_score) as avg_severity,
    COUNT(DISTINCT lds.session_id) as unique_sessions
FROM longtail_detections ld
JOIN longtail_detection_sessions lds ON ld.id = lds.detection_id
JOIN longtail_analysis la ON ld.analysis_id = la.id
WHERE ld.detection_type = 'rare_command'
  AND la.window_start >= CURRENT_DATE - INTERVAL '30 days'
GROUP BY ld.detection_data->>'command'
ORDER BY detection_count DESC, avg_severity DESC
LIMIT 20;

-- Top Outlier Sessions (Last 30 days)
SELECT 
    ld.detection_data->>'session_id' as session_id,
    ld.detection_data->>'src_ip' as src_ip,
    COUNT(*) as detection_count,
    AVG(ld.confidence_score) as avg_confidence,
    AVG(ld.severity_score) as avg_severity,
    ld.detection_data->>'command_count' as command_count,
    ld.detection_data->>'login_attempts' as login_attempts
FROM longtail_detections ld
JOIN longtail_analysis la ON ld.analysis_id = la.id
WHERE ld.detection_type = 'outlier_session'
  AND la.window_start >= CURRENT_DATE - INTERVAL '30 days'
GROUP BY ld.detection_data->>'session_id', ld.detection_data->>'src_ip', 
         ld.detection_data->>'command_count', ld.detection_data->>'login_attempts'
ORDER BY avg_severity DESC, detection_count DESC
LIMIT 20;

-- ============================================================================
-- VECTOR ANALYSIS REPORTS (PostgreSQL + pgvector only)
-- ============================================================================

-- Command Vector Statistics (Last 30 days)
SELECT 
    COUNT(*) as total_vectors,
    COUNT(DISTINCT session_id) as unique_sessions,
    COUNT(DISTINCT analysis_id) as unique_analyses,
    AVG(array_length(sequence_vector, 1)) as avg_vector_dimensions,
    MIN(timestamp) as earliest_vector,
    MAX(timestamp) as latest_vector
FROM command_sequence_vectors 
WHERE analysis_id IS NOT NULL
  AND timestamp >= CURRENT_DATE - INTERVAL '30 days';

-- Most Similar Command Sequences (using cosine similarity)
-- Note: This requires pgvector extension
SELECT 
    csv1.session_id as session1,
    csv2.session_id as session2,
    csv1.command_sequence as sequence1,
    csv2.command_sequence as sequence2,
    1 - (csv1.sequence_vector <=> csv2.sequence_vector) as cosine_similarity
FROM command_sequence_vectors csv1
JOIN command_sequence_vectors csv2 ON csv1.id < csv2.id
WHERE csv1.analysis_id IS NOT NULL 
  AND csv2.analysis_id IS NOT NULL
  AND csv1.timestamp >= CURRENT_DATE - INTERVAL '7 days'
  AND csv2.timestamp >= CURRENT_DATE - INTERVAL '7 days'
ORDER BY cosine_similarity DESC
LIMIT 10;

-- ============================================================================
-- TREND ANALYSIS
-- ============================================================================

-- Threat Trend Analysis (Monthly)
SELECT 
    DATE_TRUNC('month', window_start) as month,
    SUM(rare_command_count) as rare_commands,
    SUM(outlier_session_count) as outlier_sessions,
    SUM(emerging_pattern_count) as emerging_patterns,
    SUM(high_entropy_payload_count) as high_entropy_payloads,
    AVG(confidence_score) as avg_confidence,
    SUM(total_events_analyzed) as total_events
FROM longtail_analysis 
WHERE window_start >= CURRENT_DATE - INTERVAL '12 months'
GROUP BY DATE_TRUNC('month', window_start)
ORDER BY month;

-- Detection Type Distribution
SELECT 
    detection_type,
    COUNT(*) as count,
    AVG(confidence_score) as avg_confidence,
    AVG(severity_score) as avg_severity,
    COUNT(DISTINCT analysis_id) as unique_analyses
FROM longtail_detections
WHERE analysis_id IN (
    SELECT id FROM longtail_analysis 
    WHERE window_start >= CURRENT_DATE - INTERVAL '30 days'
)
GROUP BY detection_type
ORDER BY count DESC;

-- ============================================================================
-- PERFORMANCE METRICS
-- ============================================================================

-- Analysis Performance Metrics
SELECT 
    DATE_TRUNC('day', window_start) as day,
    COUNT(*) as analyses_count,
    AVG(analysis_duration_seconds) as avg_duration_seconds,
    AVG(memory_usage_mb) as avg_memory_mb,
    AVG(total_events_analyzed) as avg_events_per_analysis,
    SUM(total_events_analyzed) as total_events_analyzed
FROM longtail_analysis 
WHERE window_start >= CURRENT_DATE - INTERVAL '30 days'
GROUP BY DATE_TRUNC('day', window_start)
ORDER BY day DESC;

-- ============================================================================
-- DATA QUALITY METRICS
-- ============================================================================

-- Data Quality Summary
SELECT 
    COUNT(*) as total_analyses,
    COUNT(CASE WHEN data_quality_score IS NOT NULL THEN 1 END) as analyses_with_quality_score,
    AVG(data_quality_score) as avg_data_quality,
    COUNT(CASE WHEN enrichment_coverage IS NOT NULL THEN 1 END) as analyses_with_enrichment,
    AVG(enrichment_coverage) as avg_enrichment_coverage,
    COUNT(CASE WHEN recommendation IS NOT NULL THEN 1 END) as analyses_with_recommendations
FROM longtail_analysis 
WHERE window_start >= CURRENT_DATE - INTERVAL '30 days';

-- ============================================================================
-- QUICK SUMMARY QUERIES
-- ============================================================================

-- Quick Status Check
SELECT 
    'Total Analyses' as metric,
    COUNT(*)::text as value
FROM longtail_analysis
UNION ALL
SELECT 
    'Total Detections' as metric,
    COUNT(*)::text as value
FROM longtail_detections
UNION ALL
SELECT 
    'Total Vectors' as metric,
    COUNT(*)::text as value
FROM command_sequence_vectors
UNION ALL
SELECT 
    'Latest Analysis' as metric,
    MAX(window_end)::text as value
FROM longtail_analysis;

-- Recent Activity Summary (Last 7 days)
SELECT 
    COUNT(*) as analyses_last_7_days,
    SUM(rare_command_count) as rare_commands_last_7_days,
    SUM(outlier_session_count) as outlier_sessions_last_7_days,
    AVG(confidence_score) as avg_confidence_last_7_days
FROM longtail_analysis 
WHERE window_start >= CURRENT_DATE - INTERVAL '7 days';

