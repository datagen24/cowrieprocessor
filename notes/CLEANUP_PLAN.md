# Notes Folder Cleanup Plan

**Date**: October 25, 2025
**Current State**: 82 files in notes folder
**Active Projects**: Documentation, Test Suite Enhancement
**Goal**: Remove obsolete working notes, keep active work and historical references

---

## Summary

| Category | Files | Action | Reason |
|----------|-------|--------|--------|
| Active Projects | 13 | **KEEP** | Currently working on these |
| Master Documents | 3 | **KEEP** | Essential references |
| Week Summaries | 7 | **KEEP** | Historical value |
| Research | 4 | **KEEP** | Reference material |
| Daily Progress | 10 | **DELETE** | Rolled up to week summaries |
| Old Plans | 12 | **DELETE** | Work complete, in CHANGELOG |
| Coverage Files | 18 | **DELETE 16, KEEP 2** | Keep only final + summaries |
| Bug Fixes | 10 | **DELETE** | All in CHANGELOG |
| Other | 5 | **REVIEW INDIVIDUALLY** | Case by case |
| **TOTAL** | **82** | **KEEP 27, DELETE 55** | 67% reduction |

---

## KEEP (27 files, ~500K)

### Active Documentation Project (10 files, ~102K)
```
sphinx-implementation-plan.md (14K)
sphinx-setup-status.md (7.5K)
sphinx-validation-report.md (9.3K)
phase3-sphinx-setup-summary.md (18K)
docs-currency-audit.md (14K)
docs-validation-report.md (15K)
data-dictionary-update-summary.md (6.7K)
schema-v11-v14-updates.md (9.7K)
```
**Reason**: Active Documentation project - Sphinx setup just completed

### Active Test Suite Project (3 files, ~248K)
```
test_suite_status.txt (121K)
week3_day11_failures_full.txt (124K)
day11_failure_categorization.md (3.7K)
```
**Reason**: Active Test Suite Enhancement project - tracking 91 pre-existing failures

### Master Documents (3 files, ~42K)
```
committed-notes.md (21K)
tech-debt.md (13K)
README.md (7.7K)
```
**Reason**: Essential living documents, actively maintained

### Week/Phase Summaries (7 files, ~120K)
```
WEEK2_SUMMARY.md (18K)
WEEK3_SUMMARY.md (24K)
WEEK3_DAYS11-12_STRATEGIC_SUMMARY.md (12K)
DAY13_MIGRATIONS_SUMMARY.md (12K)
DAY14_SSH_ANALYTICS_SUMMARY.md (15K)
DAY16_REPORT_SUMMARY.md (11K)
MIGRATION_SUMMARY.md (8.5K)
```
**Reason**: Historical reference, comprehensive summaries

### Research/Reference (4 files, ~97K)
```
snowshoe-github-issues.md (29K)
snowshoe-phase0-research.md (50K)
deployment_configs.md (9.2K)
quick_guide.md (9.2K)
```
**Reason**: Future reference, snowshoe feature not yet implemented

---

## DELETE (55 files, ~600K)

### Category 1: Daily Progress Files (10 files, ~57K)
**Reason**: All content rolled up to WEEK2_SUMMARY, WEEK3_SUMMARY, or DAY*_SUMMARY files

```bash
# DELETE these 10 files:
day11_progress_summary.md (5.4K)
day11_realistic_plan.md (2.9K)
day11_strategic_assessment.md (3.1K)
DAY11_FINAL_SUMMARY.md (8.8K) ← superseded by WEEK3_DAYS11-12_STRATEGIC_SUMMARY.md
day12_final_assessment.md (6.8K) ← superseded by WEEK3_DAYS11-12_STRATEGIC_SUMMARY.md
day12_morning_update.txt (1.4K)
day8_botnet_analysis.md (4.8K) ← in WEEK2_SUMMARY
day9_report_analysis.md (4.7K) ← in WEEK2_SUMMARY
PHASE_0A_STATUS.md (6.2K) ← ancient, superseded
PHASE_1_DAY_1_PROGRESS.md (5.4K) ← ancient, superseded
```

**Verification**: Content in committed-notes.md and WEEK summaries

---

### Category 2: Old Plans (12 files, ~231K)
**Reason**: Work complete and documented in CHANGELOG, no longer needed

```bash
# DELETE these 12 files:
WEEK2_PLAN.md (9.6K) ← complete, see WEEK2_SUMMARY
WEEK3_PLAN.md (13K) ← complete, see WEEK3_SUMMARY
WEEK4_PLAN.md (18K) ← superseded by active work
PHASE_1_PLAN.md (5.7K) ← ancient phase work complete
phase-4-reporting-plan.md (3.4K) ← complete, see DAY16_REPORT_SUMMARY
phase6-validation-checklist.md (5.1K) ← validation complete
issue-16-plan.md (6.9K) ← issue closed
issue-17-plan.md (19K) ← issue closed
issue-31-plan.md (12K) ← issue closed
issue-32-plan.md (87K) ← HUGE, issue closed
issue-35-plan.md (26K) ← issue closed
issue-36-plan.md (18K) ← issue closed
issue-37-plan.md (14K) ← issue closed
```

**Verification**: All referenced issues/phases complete, in CHANGELOG

---

### Category 3: Coverage Tracking Files (16 of 18 files, ~73K to delete)
**Reason**: Keep only final week 2 coverage and summary, delete incremental snapshots

**KEEP (2 files)**:
```
coverage_week2_final.txt (4.5K) ← final Week 2 baseline
coverage_by_module.md (9.6K) ← module breakdown reference
```

**DELETE (16 files)**:
```bash
# DELETE these 16 coverage snapshot files:
coverage_baseline_day2.txt (4.5K)
coverage_day3_final_verified.txt (4.5K)
coverage_day4_checkpoint.txt (4.5K)
coverage_day4_final.txt (4.5K)
coverage_day4_summary.md (6.5K) ← info in WEEK2_SUMMARY
coverage_day5_final.txt (4.5K)
coverage_day5_morning_final.txt (4.5K)
coverage_day5_morning.txt (310 bytes)
coverage_day6_final.txt (4.5K)
coverage_day6_morning.txt (4.5K)
coverage_day7_final.txt (4.3K)
coverage_day7_morning.txt (4.5K)
coverage_day7_summary.md (11K) ← info in WEEK2_SUMMARY
coverage_day8_corrected.txt (4.5K)
coverage_day8_final.txt (4.4K)
coverage_day8_morning.txt (4.3K)
coverage_day8_summary.md (11K) ← info in WEEK2_SUMMARY
coverage_day9_final.txt (4.5K)
coverage_day9_summary.md (12K) ← info in WEEK2_SUMMARY
coverage_emergency_check.txt (4.5K)
```

**Verification**: All coverage milestones documented in WEEK2_SUMMARY.md and committed-notes.md

---

### Category 4: Bug Fix Documentation (10 files, ~62K)
**Reason**: All fixes documented in CHANGELOG, working notes no longer needed

```bash
# DELETE these 10 bug fix notes:
ENRICHMENT_ENHANCEMENT_SUMMARY.md (4.9K) ← in CHANGELOG
ENRICHMENT_OPTIMIZATION_FIX.md (4.3K) ← in CHANGELOG
ENRICHMENT_STATUS_FIX.md (4.0K) ← in CHANGELOG
MOCKING_ISSUES_ANALYSIS.md (2.9K) ← resolved, in committed-notes
UNICODE_CLEANUP_UTILITY.md (9.8K) ← in CHANGELOG
UNICODE_CONTROL_CHAR_SOLUTION.md (7.5K) ← in CHANGELOG
VIRUSTOTAL_ATTRIBUTE_FIX.md (5.4K) ← in CHANGELOG
VIRUSTOTAL_QUOTA_MANAGEMENT.md (9.5K) ← in CHANGELOG
VIRUSTOTAL_SERIALIZATION_FIX.md (5.4K) ← in CHANGELOG
VIRUSTOTAL_SUM_FIX.md (4.1K) ← in CHANGELOG
```

**Verification**: Check CHANGELOG for all these entries before deletion

---

### Category 5: Other Obsolete Files (7 files)

**DELETE**:
```bash
reporting-migration.md (4.9K) ← complete, see DAY16_REPORT_SUMMARY
hang-180-day.md (2.5K) ← investigate what this is, likely old issue
```

---

## Cleanup Commands

### Step 1: Verify CHANGELOG has bug fix entries
```bash
# Check CHANGELOG contains all bug fixes before deleting
grep -i "enrichment\|virustotal\|unicode" CHANGELOG.md
```

### Step 2: Remove daily progress files (10 files)
```bash
cd /home/speterson/cowrieprocessor/notes
rm -f day11_progress_summary.md day11_realistic_plan.md day11_strategic_assessment.md \
      DAY11_FINAL_SUMMARY.md day12_final_assessment.md day12_morning_update.txt \
      day8_botnet_analysis.md day9_report_analysis.md \
      PHASE_0A_STATUS.md PHASE_1_DAY_1_PROGRESS.md
```

### Step 3: Remove old plan files (12 files)
```bash
rm -f WEEK2_PLAN.md WEEK3_PLAN.md WEEK4_PLAN.md PHASE_1_PLAN.md \
      phase-4-reporting-plan.md phase6-validation-checklist.md \
      issue-16-plan.md issue-17-plan.md issue-31-plan.md \
      issue-32-plan.md issue-35-plan.md issue-36-plan.md issue-37-plan.md
```

### Step 4: Remove coverage snapshot files (16 files, keep 2)
```bash
rm -f coverage_baseline_day2.txt coverage_day3_final_verified.txt \
      coverage_day4_checkpoint.txt coverage_day4_final.txt coverage_day4_summary.md \
      coverage_day5_final.txt coverage_day5_morning_final.txt coverage_day5_morning.txt \
      coverage_day6_final.txt coverage_day6_morning.txt \
      coverage_day7_final.txt coverage_day7_morning.txt coverage_day7_summary.md \
      coverage_day8_corrected.txt coverage_day8_final.txt coverage_day8_morning.txt coverage_day8_summary.md \
      coverage_day9_final.txt coverage_day9_summary.md coverage_emergency_check.txt
# KEEP: coverage_week2_final.txt, coverage_by_module.md
```

### Step 5: Remove bug fix documentation (10 files)
```bash
rm -f ENRICHMENT_ENHANCEMENT_SUMMARY.md ENRICHMENT_OPTIMIZATION_FIX.md ENRICHMENT_STATUS_FIX.md \
      MOCKING_ISSUES_ANALYSIS.md \
      UNICODE_CLEANUP_UTILITY.md UNICODE_CONTROL_CHAR_SOLUTION.md \
      VIRUSTOTAL_ATTRIBUTE_FIX.md VIRUSTOTAL_QUOTA_MANAGEMENT.md \
      VIRUSTOTAL_SERIALIZATION_FIX.md VIRUSTOTAL_SUM_FIX.md
```

### Step 6: Remove other obsolete files (2 files, after review)
```bash
rm -f reporting-migration.md hang-180-day.md
```

---

## Post-Cleanup Structure

```
notes/
├── README.md (7.7K) ← Master index
├── committed-notes.md (21K) ← All completed work
├── tech-debt.md (13K) ← Known issues tracker
│
├── [ACTIVE: Documentation] (10 files, 102K)
│   ├── sphinx-implementation-plan.md
│   ├── sphinx-setup-status.md
│   ├── sphinx-validation-report.md
│   ├── phase3-sphinx-setup-summary.md
│   ├── docs-currency-audit.md
│   ├── docs-validation-report.md
│   ├── data-dictionary-update-summary.md
│   └── schema-v11-v14-updates.md
│
├── [ACTIVE: Test Suite] (3 files, 248K)
│   ├── test_suite_status.txt
│   ├── week3_day11_failures_full.txt
│   └── day11_failure_categorization.md
│
├── [COMPLETED: Week Summaries] (7 files, 120K)
│   ├── WEEK2_SUMMARY.md
│   ├── WEEK3_SUMMARY.md
│   ├── WEEK3_DAYS11-12_STRATEGIC_SUMMARY.md
│   ├── DAY13_MIGRATIONS_SUMMARY.md
│   ├── DAY14_SSH_ANALYTICS_SUMMARY.md
│   ├── DAY16_REPORT_SUMMARY.md
│   └── MIGRATION_SUMMARY.md
│
├── [COVERAGE: Baselines] (2 files, 14K)
│   ├── coverage_week2_final.txt
│   └── coverage_by_module.md
│
└── [RESEARCH] (4 files, 97K)
    ├── snowshoe-github-issues.md
    ├── snowshoe-phase0-research.md
    ├── deployment_configs.md
    └── quick_guide.md

TOTAL: 27 files (~583K, down from 82 files ~1.1MB)
REDUCTION: 55 files deleted (67% reduction)
```

---

## Verification Checklist

Before executing cleanup:

- [ ] Verify all bug fixes are in CHANGELOG.md
- [ ] Verify all daily progress is in week summaries
- [ ] Verify all plans reference completed work
- [ ] Verify coverage data preserved in final snapshots
- [ ] Check hang-180-day.md for any unique content
- [ ] Check reporting-migration.md for any unique content

After cleanup:

- [ ] Verify 27 files remain in notes/
- [ ] Verify active projects files intact
- [ ] Verify README.md still accurate
- [ ] Update README.md if structure changed
- [ ] Update committed-notes.md with cleanup action

---

## Space Savings

- **Before**: 82 files, ~1.1MB
- **After**: 27 files, ~583K
- **Deleted**: 55 files, ~517K
- **Reduction**: 67% fewer files, 47% smaller size

---

*Cleanup Plan Created: October 25, 2025*
*Ready for execution after verification*
