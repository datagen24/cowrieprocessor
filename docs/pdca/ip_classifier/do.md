# Do: IPClassifier Service Implementation

**Feature**: IP Infrastructure Classification Service
**Started**: 2025-11-10
**Status**: 🔄 In Progress

## Implementation Log (Chronological)

### 2025-11-10 - Session Start

**Time**: Session initialization

**Actions**:
1. Loaded PM Agent session context
2. Read brainstorming memory (infrastructure enrichment complete)
3. Created PDCA documentation structure
4. Created implementation plan (docs/pdca/ip_classifier/plan.md)
5. Created implementation log (this file)

**Status**: Ready to begin Phase 1 implementation

---

## Phase 1: Core Components (Days 1-5)

### Task 1.1: Create Package Structure

**Status**: Pending

**Actions**:
```bash
# Create package directory
mkdir -p cowrieprocessor/enrichment/ip_classification

# Create __init__.py files
touch cowrieprocessor/enrichment/ip_classification/__init__.py
touch cowrieprocessor/enrichment/ip_classification/models.py
touch cowrieprocessor/enrichment/ip_classification/matchers.py
touch cowrieprocessor/enrichment/ip_classification/cache.py
touch cowrieprocessor/enrichment/ip_classification/classifier.py
touch cowrieprocessor/enrichment/ip_classification/factory.py
```

**Expected**: Clean package structure following project conventions

---

### Task 1.2: Update Dependencies

**Status**: Pending

**Actions**:
```bash
# Add to pyproject.toml dependencies
pytricia>=1.0.0  # CIDR prefix trees for fast IP matching
aiohttp>=3.9.0   # Async HTTP for data source downloads

# Add to dev dependencies
pytest-asyncio>=0.21.0  # Async test support
responses>=0.24.0       # HTTP request mocking
```

**Expected**: Dependencies added, `uv sync` completes successfully

---

### Task 1.3: Implement Data Models (models.py)

**Status**: Pending

**File**: `cowrieprocessor/enrichment/ip_classification/models.py`

**Code**:
```python
"""Data models for IP classification."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class IPType(str, Enum):
    """IP classification types.

    Ordered by threat priority (TOR highest, UNKNOWN lowest).
    """
    TOR = "tor"
    CLOUD = "cloud"
    DATACENTER = "datacenter"
    RESIDENTIAL = "residential"
    UNKNOWN = "unknown"


@dataclass(slots=True, frozen=True)
class IPClassification:
    """Immutable IP classification result.

    Attributes:
        ip_type: Classification category
        provider: Optional provider name (e.g., "aws", "tor")
        confidence: Classification confidence (0.0 to 1.0)
        source: Data source used (e.g., "tor_bulk_list")
        classified_at: UTC timestamp of classification

    Example:
        >>> classification = IPClassification(
        ...     ip_type=IPType.CLOUD,
        ...     provider="aws",
        ...     confidence=0.99,
        ...     source="cloud_ranges_aws",
        ... )
        >>> classification.ip_type
        <IPType.CLOUD: 'cloud'>
    """
    ip_type: IPType
    provider: Optional[str]
    confidence: float
    source: str
    classified_at: datetime = None  # Auto-populated in __post_init__

    def __post_init__(self) -> None:
        """Validate fields and set defaults."""
        # Validate confidence range
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be between 0.0 and 1.0, got {self.confidence}")

        # Set classified_at to current UTC time if not provided
        if self.classified_at is None:
            object.__setattr__(self, 'classified_at', datetime.now(timezone.utc))
```

**Tests**:
```python
# tests/unit/enrichment/ip_classification/test_models.py
def test_ip_type_enum():
    assert IPType.TOR.value == "tor"
    assert IPType.CLOUD.value == "cloud"
    assert IPType.DATACENTER.value == "datacenter"
    assert IPType.RESIDENTIAL.value == "residential"
    assert IPType.UNKNOWN.value == "unknown"

def test_ip_classification_valid():
    classification = IPClassification(
        ip_type=IPType.CLOUD,
        provider="aws",
        confidence=0.99,
        source="cloud_ranges_aws",
    )
    assert classification.ip_type == IPType.CLOUD
    assert classification.provider == "aws"
    assert classification.confidence == 0.99
    assert classification.classified_at is not None

def test_ip_classification_invalid_confidence():
    with pytest.raises(ValueError, match="confidence must be between 0.0 and 1.0"):
        IPClassification(
            ip_type=IPType.CLOUD,
            provider="aws",
            confidence=1.5,  # Invalid
            source="test",
        )

def test_ip_classification_immutable():
    classification = IPClassification(
        ip_type=IPType.TOR,
        provider="tor",
        confidence=0.95,
        source="tor_bulk_list",
    )
    with pytest.raises(AttributeError):
        classification.confidence = 0.5  # Should fail (frozen)
```

**Expected**: Data models complete, 100% test coverage, mypy passes

---

### Task 1.4: Implement Base IPMatcher (matchers.py - Part 1)

**Status**: Pending

**File**: `cowrieprocessor/enrichment/ip_classification/matchers.py`

**Code**:
```python
"""IP matching components for classification."""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, Dict
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class IPMatcher(ABC):
    """Abstract base class for IP matchers.

    All matchers implement:
    - match(ip: str) -> Optional[dict]: Check if IP matches this type
    - _download_data(): Download data from source
    - _update_data(force: bool): Update data if stale
    """

    def __init__(
        self,
        data_url: str,
        update_interval_seconds: int,
        cache_dir: Path,
    ) -> None:
        """Initialize matcher.

        Args:
            data_url: URL to download data from
            update_interval_seconds: How often to update data
            cache_dir: Directory to cache downloaded data
        """
        self.data_url = data_url
        self.update_interval_seconds = update_interval_seconds
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self.last_update: Optional[datetime] = None
        self._data_loaded = False

    @abstractmethod
    def match(self, ip: str) -> Optional[Dict[str, str]]:
        """Check if IP matches this matcher's type.

        Args:
            ip: IP address to check

        Returns:
            Dict with match metadata if matched, None otherwise
            Example: {'provider': 'aws', 'region': 'us-east-1'}
        """
        pass

    def _is_stale(self) -> bool:
        """Check if data needs updating."""
        if not self._data_loaded or self.last_update is None:
            return True

        age_seconds = (datetime.now(timezone.utc) - self.last_update).total_seconds()
        return age_seconds > self.update_interval_seconds

    def _update_data(self, force: bool = False) -> None:
        """Update data if stale or forced.

        Args:
            force: Force update even if not stale
        """
        if not force and not self._is_stale():
            return

        try:
            self._download_data()
            self.last_update = datetime.now(timezone.utc)
            self._data_loaded = True
            logger.info(f"{self.__class__.__name__}: Data updated successfully")
        except Exception as e:
            logger.error(f"{self.__class__.__name__}: Data update failed: {e}")
            if not self._data_loaded:
                # No fallback data, raise error
                raise
            # Use stale data if available
            logger.warning(f"{self.__class__.__name__}: Using stale data (last update: {self.last_update})")

    @abstractmethod
    def _download_data(self) -> None:
        """Download and parse data from source.

        Must be implemented by subclasses.
        """
        pass
```

**Expected**: Base class complete, abstract methods defined

---

## Learnings During Implementation

*(Will be populated as implementation progresses)*

### Lesson 1: [Title]
- **Issue**: [What happened]
- **Root Cause**: [Why it happened]
- **Solution**: [How it was fixed]
- **Prevention**: [How to avoid in future]

---

## Trial-and-Error Log

*(Will capture all attempts, errors, and solutions)*

### Attempt 1: [Task]
- **Approach**: [What was tried]
- **Result**: [Success/Failure]
- **Evidence**: [Error messages, test results]
- **Learning**: [What was learned]

---

## Code Quality Metrics

*(Will be updated after each phase)*

### Phase 1 Metrics
- **Lines of Code**: TBD
- **Test Coverage**: Target 95%
- **Type Coverage**: Target 100% (mypy --strict)
- **Linting Issues**: Target 0 (ruff check)

---

**Implementation Status**: 🟡 Planning Complete, Ready to Execute
**Next Action**: Begin Task 1.1 - Create package structure
**Blockers**: None
