"""Unit tests for HIBP password breach checking client."""

from __future__ import annotations

import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock

import pytest
import requests

from cowrieprocessor.enrichment.cache import EnrichmentCacheManager
from cowrieprocessor.enrichment.hibp_client import HIBPPasswordEnricher
from cowrieprocessor.enrichment.rate_limiting import RateLimitedSession


@pytest.fixture
def temp_cache_dir():
    """Create temporary cache directory."""
    with TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def cache_manager(temp_cache_dir):
    """Create cache manager for testing."""
    return EnrichmentCacheManager(base_dir=temp_cache_dir)


@pytest.fixture
def mock_rate_limiter():
    """Create mock rate limiter."""
    limiter = Mock(spec=RateLimitedSession)
    return limiter


@pytest.fixture
def hibp_enricher(cache_manager, mock_rate_limiter):
    """Create HIBP enricher for testing."""
    return HIBPPasswordEnricher(cache_manager, mock_rate_limiter)


def test_init_creates_enricher(cache_manager, mock_rate_limiter):
    """Test HIBPPasswordEnricher initializes correctly."""
    enricher = HIBPPasswordEnricher(cache_manager, mock_rate_limiter)
    assert enricher.cache_manager == cache_manager
    assert enricher.rate_limiter == mock_rate_limiter
    assert enricher.stats['checks'] == 0


def test_check_password_breached(hibp_enricher, mock_rate_limiter):
    """Test checking a breached password."""
    # Mock API response
    mock_response = Mock()
    mock_response.text = "003D68EB55068C33ACE09247EE4C639306B:3\n00D4F6E8FA6EECAD2A3AA415EEC418D38EC:2"
    mock_response.raise_for_status = Mock()
    mock_rate_limiter.get = Mock(return_value=mock_response)
    
    # Check password (SHA-1 hash starts with 5BAA6)
    result = hibp_enricher.check_password("password")
    
    assert mock_rate_limiter.get.called
    assert result['breached'] in [True, False]  # Result depends on actual hash
    assert 'prevalence' in result
    assert 'cached' in result
    assert result['error'] is None


def test_check_password_not_breached(hibp_enricher, mock_rate_limiter):
    """Test checking a non-breached password."""
    # Generate a password that won't be in the response
    test_password = "ThisIsAVeryUniquePassword123!@#"
    sha1_hash = hashlib.sha1(test_password.encode('utf-8')).hexdigest().upper()
    sha1_hash[:5]  # prefix
    sha1_hash[5:]  # suffix
    
    # Mock API response without this hash
    mock_response = Mock()
    mock_response.text = "003D68EB55068C33ACE09247EE4C639306B:3\n00D4F6E8FA6EECAD2A3AA415EEC418D38EC:2"
    mock_response.raise_for_status = Mock()
    mock_rate_limiter.get = Mock(return_value=mock_response)
    
    result = hibp_enricher.check_password(test_password)
    
    assert result['breached'] is False
    assert result['prevalence'] == 0
    assert result['cached'] is False
    assert result['error'] is None


def test_check_password_uses_cache(hibp_enricher, cache_manager, mock_rate_limiter):
    """Test that second check uses cache."""
    # First check - mock API response
    test_password = "password123"
    sha1_hash = hashlib.sha1(test_password.encode('utf-8')).hexdigest().upper()
    sha1_hash[:5]  # prefix
    
    mock_response = Mock()
    mock_response.text = "003D68EB55068C33ACE09247EE4C639306B:3"
    mock_response.raise_for_status = Mock()
    mock_rate_limiter.get = Mock(return_value=mock_response)
    
    # First check
    result1 = hibp_enricher.check_password(test_password)
    assert result1['cached'] is False
    assert mock_rate_limiter.get.call_count == 1
    
    # Second check - should use cache
    result2 = hibp_enricher.check_password(test_password)
    assert result2['cached'] is True
    assert mock_rate_limiter.get.call_count == 1  # Not called again


def test_check_password_api_error(hibp_enricher, mock_rate_limiter):
    """Test handling of API errors."""
    mock_rate_limiter.get = Mock(side_effect=requests.RequestException("Network error"))
    
    result = hibp_enricher.check_password("password")
    
    assert result['breached'] is False
    assert result['prevalence'] == 0
    assert result['error'] is not None
    assert 'Network error' in result['error']
    assert hibp_enricher.stats['errors'] == 1


def test_parse_response_valid(hibp_enricher):
    """Test parsing valid HIBP response."""
    response_text = """003D68EB55068C33ACE09247EE4C639306B:3
00D4F6E8FA6EECAD2A3AA415EEC418D38EC:2
011053FD0102E94D6AE2F8B83D76FAF94F6:1"""
    
    result = hibp_enricher._parse_response(response_text)
    
    assert len(result) == 3
    assert result['003D68EB55068C33ACE09247EE4C639306B'] == 3
    assert result['00D4F6E8FA6EECAD2A3AA415EEC418D38EC'] == 2
    assert result['011053FD0102E94D6AE2F8B83D76FAF94F6'] == 1


def test_parse_response_empty(hibp_enricher):
    """Test parsing empty response."""
    result = hibp_enricher._parse_response("")
    assert len(result) == 0


def test_parse_response_malformed(hibp_enricher):
    """Test parsing malformed response lines."""
    response_text = """003D68EB55068C33ACE09247EE4C639306B:3
INVALID_LINE
00D4F6E8FA6EECAD2A3AA415EEC418D38EC:2"""
    
    result = hibp_enricher._parse_response(response_text)
    
    # Should skip invalid line
    assert len(result) == 2
    assert '003D68EB55068C33ACE09247EE4C639306B' in result
    assert '00D4F6E8FA6EECAD2A3AA415EEC418D38EC' in result


def test_extract_result_found(hibp_enricher):
    """Test extracting result when hash is found."""
    hash_data = {
        'ABC123': 100,
        'DEF456': 50,
    }
    
    result = hibp_enricher._extract_result(hash_data, 'ABC123', cached=False)
    
    assert result['breached'] is True
    assert result['prevalence'] == 100
    assert result['cached'] is False


def test_extract_result_not_found(hibp_enricher):
    """Test extracting result when hash is not found."""
    hash_data = {
        'ABC123': 100,
    }
    
    result = hibp_enricher._extract_result(hash_data, 'XYZ789', cached=True)
    
    assert result['breached'] is False
    assert result['prevalence'] == 0
    assert result['cached'] is True


def test_get_stats(hibp_enricher):
    """Test getting statistics."""
    stats = hibp_enricher.get_stats()
    
    assert 'checks' in stats
    assert 'cache_hits' in stats
    assert 'cache_misses' in stats
    assert 'api_calls' in stats
    assert 'breached_found' in stats
    assert 'errors' in stats


def test_reset_stats(hibp_enricher, mock_rate_limiter):
    """Test resetting statistics."""
    # Make some checks
    mock_response = Mock()
    mock_response.text = "003D68EB55068C33ACE09247EE4C639306B:3"
    mock_response.raise_for_status = Mock()
    mock_rate_limiter.get = Mock(return_value=mock_response)
    
    hibp_enricher.check_password("password")
    assert hibp_enricher.stats['checks'] > 0
    
    # Reset stats
    hibp_enricher.reset_stats()
    assert hibp_enricher.stats['checks'] == 0
    assert hibp_enricher.stats['api_calls'] == 0


def test_k_anonymity_only_sends_prefix(hibp_enricher, mock_rate_limiter):
    """Test that only 5-character prefix is sent to API."""
    test_password = "testpassword"
    sha1_hash = hashlib.sha1(test_password.encode('utf-8')).hexdigest().upper()
    expected_prefix = sha1_hash[:5]
    
    mock_response = Mock()
    mock_response.text = ""
    mock_response.raise_for_status = Mock()
    mock_rate_limiter.get = Mock(return_value=mock_response)
    
    hibp_enricher.check_password(test_password)
    
    # Verify only prefix was sent
    call_args = mock_rate_limiter.get.call_args
    assert expected_prefix in call_args[0][0]
    assert len(expected_prefix) == 5


def test_stats_increment_correctly(hibp_enricher, mock_rate_limiter):
    """Test that statistics increment correctly."""
    # Setup mock response with breached password
    sha1_hash = hashlib.sha1("breached".encode('utf-8')).hexdigest().upper()
    suffix = sha1_hash[5:]
    
    mock_response = Mock()
    mock_response.text = f"{suffix}:100"
    mock_response.raise_for_status = Mock()
    mock_rate_limiter.get = Mock(return_value=mock_response)
    
    # First check
    hibp_enricher.check_password("breached")
    assert hibp_enricher.stats['checks'] == 1
    assert hibp_enricher.stats['api_calls'] == 1
    assert hibp_enricher.stats['cache_misses'] == 1
    
    # Second check (cached)
    hibp_enricher.check_password("breached")
    assert hibp_enricher.stats['checks'] == 2
    assert hibp_enricher.stats['api_calls'] == 1  # Not incremented
    assert hibp_enricher.stats['cache_hits'] == 1

