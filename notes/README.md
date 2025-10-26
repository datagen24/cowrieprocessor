# Notes Folder Organization

**Last Cleanup**: October 25, 2025
**Total Files**: 35 (down from 82)
**Active Projects**: Documentation, Test Suite Enhancement

This folder contains project notes, summaries, and documentation organized by status and purpose.

---

## 🚀 Active Projects (Currently Working)

### Documentation Project (10 files)
**Status**: ✅ Phase 3 Complete - Ready for ReadTheDocs deployment

**Sphinx Setup Documentation**:
- `sphinx-implementation-plan.md` - Overall Sphinx setup plan
- `sphinx-setup-status.md` - Status report with 4 implementation options
- `sphinx-validation-report.md` - Sphinx 7.4.7 validation results
- `phase3-sphinx-setup-summary.md` - **Phase 3 completion report** (18K)

**Documentation Validation**:
- `docs-currency-audit.md` - Audit of 16 markdown docs (14K)
- `docs-validation-report.md` - **Phase 2: All 6 docs validated** (15K)

**Schema Documentation**:
- `data-dictionary-update-summary.md` - **Phase 1: Schema v10 → v14** (6.7K)
- `schema-v11-v14-updates.md` - Complete schema changes v11-v14 (9.7K)

**Cleanup Documentation**:
- `CLEANUP_PLAN.md` - Notes folder cleanup plan
- `CLEANUP_SUMMARY.md` - **Cleanup results: 48 files deleted** (this guide)

**Next Steps**: Connect repository to ReadTheDocs and trigger first build

---

### Test Suite Enhancement (3 files)
**Status**: 🔄 Active - Tracking 91 pre-existing test failures

**Current Work**:
- `test_suite_status.txt` (121K) - Current test suite status
- `week3_day11_failures_full.txt` (124K) - Full failure output for analysis
- `day11_failure_categorization.md` (3.7K) - Failure analysis by category

**Categories**:
- Enrichment tests: ~35 failures (mock/patch issues)
- Database tests: ~25 failures (session management)
- CLI tests: ~20 failures (argument parser changes)
- Type system: ~11 failures (return type mismatches)

**Next Steps**: Dedicated sprint to fix 91 pre-existing failures (3-5 days estimated)

---

## 📋 Master Documents (Always Current)

These files provide comprehensive project status and are kept up-to-date:

- **`committed-notes.md`** (21K) - Condensed record of all significant completed work
- **`tech-debt.md`** (13K) - Known issues and technical debt tracking (for GitHub issues)
- **`README.md`** (this file) - Notes folder index and navigation guide

---

## 📊 Completed Work Summaries (Historical Reference)

### Weekly Summaries (3 files)
Comprehensive retrospectives for each week:

- **`WEEK2_SUMMARY.md`** (18K) - Week 2: Module coverage push, 40.4% → 53%
- **`WEEK3_SUMMARY.md`** (24K) - Week 3: Strategic pivot, high-value tests, 53% → 55%
- **`WEEK3_DAYS11-12_STRATEGIC_SUMMARY.md`** (12K) - Days 11-12 detailed summary

### Feature/Module Summaries (4 files)
Day-by-day detailed documentation of completed work:

- **`DAY13_MIGRATIONS_SUMMARY.md`** (12K) - Migrations testing (47% → 58% coverage)
- **`DAY14_SSH_ANALYTICS_SUMMARY.md`** (15K) - SSH key analytics (32% → 98% coverage)
- **`DAY16_REPORT_SUMMARY.md`** (11K) - Report CLI testing (63% → 76% coverage)
- **`MIGRATION_SUMMARY.md`** (8.5K) - Database migration framework

---

## 📈 Coverage Baselines (2 files)

Historical coverage data (final snapshots only):

- `coverage_week2_final.txt` (4.5K) - Week 2 final coverage (53%)
- `coverage_by_module.md` (9.6K) - Module-by-module breakdown

**Note**: Daily coverage snapshots removed during October 25 cleanup (20 files deleted)

---

## 🔬 Research & Reference (4 files)

Future features and operational documentation:

### Future Features
- `snowshoe-github-issues.md` (29K) - Snowshoe spam detection research
- `snowshoe-phase0-research.md` (50K) - Phase 0 snowshoe investigation

### Operational Documentation
- `deployment_configs.md` (9.2K) - Deployment configuration guide
- `quick_guide.md` (9.2K) - Quick reference guide
- `hang-180-day.md` (2.5K) - Troubleshooting bulk load issues

---

## 📚 Implementation Documentation (5 files)

Feature implementation details (may be archived):

- `HIBP_PASSWORD_ENRICHMENT_IMPLEMENTATION.md` - HIBP password enrichment
- `LONGTAIL_STORAGE_IMPLEMENTATION.md` - Longtail storage implementation
- `LONGTAIL_VECTOR_IMPLEMENTATION.md` - Longtail vector implementation
- `HOTPATCH_README.md` - Hotpatch procedure documentation
- `ISSUE_40_FIX.md` - Issue #40 fix documentation

**Note**: These may be candidates for future archival or migration to `docs/`

---

## Quick Navigation

### "I want to see what's been completed"
→ Read **`committed-notes.md`** for condensed summary
→ Check **CHANGELOG.md** (parent directory) for formal release notes
→ Review weekly summaries for detailed retrospectives

### "I want to see active work"
→ Check **Documentation Project** section above (Sphinx setup)
→ Check **Test Suite Enhancement** section above (91 failures)
→ Review `test_suite_status.txt` for current test status

### "I want to understand known issues"
→ Read **`tech-debt.md`** for tracked technical debt
→ Check GitHub issues for active work
→ Review test failure categorization in `day11_failure_categorization.md`

### "I want coverage metrics"
→ Read `WEEK2_SUMMARY.md` for Week 2 progress (40.4% → 53%)
→ Read `WEEK3_SUMMARY.md` for Week 3 progress (53% → 55%)
→ Check `coverage_by_module.md` for module breakdown
→ Review `DAY*_SUMMARY.md` files for specific module achievements

### "I want to understand a specific feature"
→ Check implementation documentation files (HIBP_*, LONGTAIL_*, etc.)
→ Read relevant `DAY*_SUMMARY.md` for implementation details
→ Check `committed-notes.md` for condensed summary

---

## Notes Folder Structure

```
notes/
├── README.md (this file)
├── committed-notes.md (completed work)
├── tech-debt.md (known issues)
├── CLEANUP_PLAN.md (cleanup plan)
├── CLEANUP_SUMMARY.md (cleanup results)
│
├── [ACTIVE: Documentation] (10 files, ~102K)
│   ├── sphinx-*.md (3 files)
│   ├── docs-*.md (2 files)
│   ├── phase3-sphinx-setup-summary.md
│   ├── data-dictionary-update-summary.md
│   ├── schema-v11-v14-updates.md
│   ├── CLEANUP_PLAN.md
│   └── CLEANUP_SUMMARY.md
│
├── [ACTIVE: Test Suite] (3 files, ~248K)
│   ├── test_suite_status.txt (121K)
│   ├── week3_day11_failures_full.txt (124K)
│   └── day11_failure_categorization.md
│
├── [COMPLETED: Summaries] (7 files, ~120K)
│   ├── WEEK2_SUMMARY.md
│   ├── WEEK3_SUMMARY.md
│   ├── WEEK3_DAYS11-12_STRATEGIC_SUMMARY.md
│   ├── DAY13_MIGRATIONS_SUMMARY.md
│   ├── DAY14_SSH_ANALYTICS_SUMMARY.md
│   ├── DAY16_REPORT_SUMMARY.md
│   └── MIGRATION_SUMMARY.md
│
├── [COVERAGE: Baselines] (2 files, ~14K)
│   ├── coverage_week2_final.txt
│   └── coverage_by_module.md
│
├── [RESEARCH] (5 files, ~100K)
│   ├── snowshoe-*.md (2 files)
│   ├── deployment_configs.md
│   ├── quick_guide.md
│   └── hang-180-day.md
│
└── [IMPLEMENTATION] (5 files, ~50K)
    ├── HIBP_PASSWORD_ENRICHMENT_IMPLEMENTATION.md
    ├── LONGTAIL_STORAGE_IMPLEMENTATION.md
    ├── LONGTAIL_VECTOR_IMPLEMENTATION.md
    ├── HOTPATCH_README.md
    └── ISSUE_40_FIX.md
```

---

## Recent Cleanup (October 25, 2025)

**Before**: 82 files (~1.1MB)
**After**: 35 files (~748KB)
**Deleted**: 47 files (57% reduction)

### Files Removed
- 10 daily progress files (rolled up to week summaries)
- 13 old plan files (work complete, in CHANGELOG)
- 20 coverage snapshot files (kept final baseline only)
- 10 bug fix documentation files (all in CHANGELOG)
- 1 reporting migration doc (migration complete)

**Details**: See `CLEANUP_SUMMARY.md` for complete cleanup report

---

## File Maintenance Guidelines

### When adding new notes:

1. **Daily progress**: Update active project files or create temporary working notes
2. **Completed work**: Update `committed-notes.md` with significant achievements
3. **Issues discovered**: Add to `tech-debt.md` immediately
4. **Feature docs**: Create feature-specific .md files as needed
5. **Cleanup**: Remove obsolete working notes quarterly

### Naming conventions:

- Weekly summaries: `WEEK<n>_SUMMARY.md`
- Daily/feature summaries: `DAY<n>_<TOPIC>_SUMMARY.md`
- Coverage tracking: `coverage_<type>_<checkpoint>.txt`
- Issue plans: `issue-<n>-plan.md`
- Feature docs: `<FEATURE_NAME>_<TYPE>.md`

---

## Document Status

### Master Documents
- ✅ **committed-notes.md** - Current as of October 25, 2025
- ✅ **tech-debt.md** - Current as of October 25, 2025
- ✅ **README.md** - Updated October 25, 2025 (this file)

### Active Projects
- ✅ **Documentation** - Phase 3 complete, ready for ReadTheDocs
- 🔄 **Test Suite** - Active work, 91 pre-existing failures tracked

### Completed Summaries
- ✅ **WEEK2_SUMMARY.md** - Complete
- ✅ **WEEK3_SUMMARY.md** - Complete
- ✅ **DAY13_MIGRATIONS_SUMMARY.md** - Complete
- ✅ **DAY14_SSH_ANALYTICS_SUMMARY.md** - Complete
- ✅ **DAY16_REPORT_SUMMARY.md** - Complete

---

## Contributing to Notes

### Best Practices:

1. **Keep it organized**: Use existing categories, create new ones if needed
2. **Update master docs**: Always update `committed-notes.md` when completing significant work
3. **Track issues**: Add discovered issues to `tech-debt.md` immediately
4. **Clean regularly**: Remove obsolete working notes quarterly
5. **Summarize**: Create summaries instead of keeping all daily progress files

### Quarterly Cleanup Checklist:

- [ ] Archive completed work summaries (>6 months old)
- [ ] Remove obsolete working notes and daily progress files
- [ ] Update README.md to reflect current structure
- [ ] Review implementation docs for archival candidates
- [ ] Consolidate coverage data (keep final snapshots only)

---

*Document created: October 25, 2025*
*Last updated: October 25, 2025*
*Files: 35 (after cleanup from 82)*
