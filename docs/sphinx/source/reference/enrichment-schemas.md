# Enrichment Data Schemas

This document describes the JSON schemas used for storing enrichment data in the `session_summaries.enrichment` and `files` tables.

## Overview

The enrichment system stores data from multiple sources in a single JSON field. Each enrichment module uses specific top-level keys to avoid conflicts:

- **IP/ASN Enrichment**: Uses keys like `dshield`, `urlhaus`, `spur`, `virustotal`
- **Password Enrichment**: Uses the key `password_stats`

## Session Enrichment Schema

The `session_summaries.enrichment` field contains a JSON object with the following structure:

```json
{
  "dshield": {
    "ip": {
      "count": "string",
      "attacks": "string",
      "asn": "string",
      "asname": "string",
      "ascountry": "string"
    },
    "error": "string (optional)"
  },
  "urlhaus": "string (comma-separated tags)",
  "spur": ["string", "string", "string", "string"],
  "virustotal": {
    "data": {
      "attributes": {
        "last_analysis_stats": {
          "malicious": "integer",
          "suspicious": "integer",
          "harmless": "integer",
          "undetected": "integer"
        }
      }
    }
  },
  "password_stats": {
    "total_attempts": "integer",
    "unique_passwords": "integer",
    "breached_passwords": "integer",
    "breach_prevalence_max": "integer",
    "novel_password_hashes": ["string"],
    "password_details": [
      {
        "username": "string",
        "password_sha256": "string",
        "breached": "boolean",
        "prevalence": "integer",
        "success": "boolean",
        "timestamp": "string (ISO 8601)"
      }
    ]
  }
}
```

### IP/ASN Enrichment Fields

#### DShield (`dshield`)
- **Purpose**: IP reputation and geolocation data from DShield
- **Source**: DShield API
- **Structure**:
  ```json
  {
    "ip": {
      "count": "Number of attacks from this IP",
      "attacks": "Attack count string",
      "asn": "Autonomous System Number",
      "asname": "AS Name",
      "ascountry": "AS Country Code"
    },
    "error": "Error message if lookup failed (optional)"
  }
  ```

#### URLHaus (`urlhaus`)
- **Purpose**: IP/URL reputation tags
- **Source**: URLHaus API
- **Structure**: Comma-separated string of tags (e.g., "malware,botnet")

#### SPUR (`spur`)
- **Purpose**: Infrastructure intelligence data
- **Source**: SPUR API
- **Structure**: Array of 4 strings containing infrastructure details

#### VirusTotal (`virustotal`)
- **Purpose**: File analysis results for downloaded files
- **Source**: VirusTotal API
- **Structure**: Contains VirusTotal API response data

### Password Enrichment Fields

#### Password Stats (`password_stats`)
- **Purpose**: HIBP password breach analysis results
- **Source**: HIBP (Have I Been Pwned) API
- **Structure**:
  ```json
  {
    "total_attempts": "Total number of login attempts",
    "unique_passwords": "Number of unique passwords tried",
    "breached_passwords": "Number of passwords found in breaches",
    "breach_prevalence_max": "Highest breach count for any password",
    "novel_password_hashes": ["Array of SHA256 hashes of non-breached passwords"],
    "password_details": [
      {
        "username": "Username attempted",
        "password_sha256": "SHA256 hash of the password",
        "breached": "Whether password was found in breaches",
        "prevalence": "Number of times password appears in breaches",
        "success": "Whether login was successful",
        "timestamp": "ISO 8601 timestamp of attempt"
      }
    ]
  }
  ```

## File Enrichment Schema

The `files` table stores VirusTotal enrichment data in dedicated columns and in the `enrichment` field:

### Dedicated Columns
- `vt_classification`: Threat classification string
- `vt_description`: File type description
- `vt_malicious`: Boolean indicating if file is malicious
- `vt_first_seen`: Timestamp of first submission to VirusTotal
- `vt_last_analysis`: Timestamp of last analysis
- `vt_positives`: Number of positive detections
- `vt_total`: Total number of engines that scanned the file
- `vt_scan_date`: Date of last scan

### Enrichment Field
The `enrichment` field contains the full VirusTotal API response:

```json
{
  "virustotal": {
    "data": {
      "id": "file_hash",
      "type": "file",
      "attributes": {
        "last_analysis_stats": {
          "malicious": "integer",
          "suspicious": "integer",
          "harmless": "integer",
          "undetected": "integer"
        },
        "last_analysis_results": {
          "engine_name": {
            "category": "malicious|suspicious|harmless|undetected",
            "result": "detection_name"
          }
        },
        "first_submission_date": "unix_timestamp",
        "last_submission_date": "unix_timestamp",
        "md5": "md5_hash",
        "sha1": "sha1_hash",
        "sha256": "sha256_hash",
        "size": "file_size_bytes",
        "type_description": "file_type_description",
        "names": ["file_names"],
        "tags": ["file_tags"],
        "reputation": "reputation_score",
        "total_votes": {
          "harmless": "integer",
          "malicious": "integer"
        }
      }
    }
  }
}
```

## Data Merging Strategy

When multiple enrichment modules update the same session, the system uses a merge strategy:

1. **Existing data is preserved**: Data from other enrichment modules is not overwritten
2. **New data takes precedence**: If the same key is updated, the newer data replaces the older data
3. **Graceful handling**: Invalid or corrupted JSON data is handled gracefully by starting fresh

### Example Merge

**Before** (password enrichment only):
```json
{
  "password_stats": {
    "total_attempts": 3,
    "unique_passwords": 2,
    "breached_passwords": 1
  }
}
```

**After** (IP enrichment added):
```json
{
  "password_stats": {
    "total_attempts": 3,
    "unique_passwords": 2,
    "breached_passwords": 1
  },
  "dshield": {
    "ip": {
      "count": "5",
      "attacks": "10",
      "asn": "AS1234",
      "asname": "Example Corp",
      "ascountry": "US"
    }
  },
  "urlhaus": "malware,botnet"
}
```

## Implementation Notes

- **Database Compatibility**: The schema works with both SQLite and PostgreSQL
- **JSON Validation**: All JSON data is validated before storage
- **Error Handling**: Failed enrichment lookups are recorded with error messages
- **Caching**: Enrichment responses are cached to avoid duplicate API calls
- **Rate Limiting**: API calls are rate-limited to respect service quotas

## Related Documentation

- [Enrichment Refresh Guide](../README.md#enrichment-refresh)
- [Password Enrichment CLI](../README.md#password-enrichment)
- [Database Schema](../docs/database-schema.md)



