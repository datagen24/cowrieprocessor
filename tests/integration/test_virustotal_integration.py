"""Integration tests for VirusTotal enrichment with quota management."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from enrichment_handlers import EnrichmentService
from cowrieprocessor.enrichment.virustotal_handler import VirusTotalHandler


class TestVirusTotalIntegration:
    """Integration tests for VirusTotal enrichment."""
    
    def test_enrichment_service_with_vt_handler(self, tmp_path: Path) -> None:
        """Test that EnrichmentService properly integrates with VirusTotalHandler."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        
        # Mock VirusTotal response
        mock_vt_response = {
            "data": {
                "id": "test-file-id",
                "type": "file",
                "attributes": {
                    "last_analysis_stats": {
                        "malicious": 5,
                        "harmless": 10,
                        "suspicious": 2,
                        "undetected": 20,
                    },
                    "md5": "test-md5",
                    "sha1": "test-sha1",
                    "sha256": "test-sha256",
                    "size": 1024,
                }
            }
        }
        
        with patch('cowrieprocessor.enrichment.virustotal_handler.vt.Client') as mock_client_class:
            # Mock the client and file object
            mock_file_obj = Mock()
            mock_file_obj.id = "test-file-id"
            mock_file_obj.type = "file"
            mock_file_obj.last_analysis_stats = {"malicious": 5, "harmless": 10, "suspicious": 2, "undetected": 20}
            mock_file_obj.last_analysis_results = {}
            mock_file_obj.first_submission_date = 1234567890
            mock_file_obj.last_submission_date = 1234567890
            mock_file_obj.md5 = "test-md5"
            mock_file_obj.sha1 = "test-sha1"
            mock_file_obj.sha256 = "test-sha256"
            mock_file_obj.size = 1024
            mock_file_obj.type_description = "PE32"
            mock_file_obj.names = ["test.exe"]
            mock_file_obj.tags = ["trojan"]
            mock_file_obj.reputation = 50
            mock_file_obj.total_votes = 10
            mock_file_obj.meaningful_name = "test.exe"
            
            mock_client = Mock()
            mock_client.get_object.return_value = mock_file_obj
            mock_client_class.return_value = mock_client
            
            # Create enrichment service with VirusTotal handler
            service = EnrichmentService(
                cache_dir=cache_dir,
                vt_api="test-api-key",
                dshield_email=None,
                urlhaus_api=None,
                spur_api=None,
                enable_vt_quota_management=True,
            )
            
            # Test file enrichment
            result = service.enrich_file("test-hash", "test.exe")
            
            assert result is not None
            assert "file_hash" in result
            assert "filename" in result
            assert "enrichment" in result
            
            enrichment = result["enrichment"]
            assert "virustotal" in enrichment
            
            vt_data = enrichment["virustotal"]
            assert vt_data is not None
            assert "data" in vt_data
            assert vt_data["data"]["id"] == "test-file-id"
            
            # Test quota status
            quota_status = service.get_vt_quota_status()
            assert "status" in quota_status
            
            # Cleanup
            service.close()
    
    def test_vt_handler_caching(self, tmp_path: Path) -> None:
        """Test VirusTotal handler caching functionality."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        
        # Create test data
        test_data = {
            "data": {
                "id": "cached-file-id",
                "attributes": {
                    "last_analysis_stats": {"malicious": 3, "harmless": 15}
                }
            }
        }
        
        handler = VirusTotalHandler(
            api_key="test-key",
            cache_dir=cache_dir,
            skip_enrich=False,
            enable_quota_management=False,  # Disable for simpler testing
        )
        
        # Save test data to cache
        handler._save_cached_response("cached-hash", test_data)
        
        # Load from cache
        cached_result = handler._load_cached_response("cached-hash")
        assert cached_result == test_data
        
        # Test enrichment with cached data
        result = handler.enrich_file("cached-hash")
        assert result == test_data
        
        # Cleanup
        handler.close()
    
    def test_quota_management_integration(self, tmp_path: Path) -> None:
        """Test quota management integration with enrichment service."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        
        with patch('cowrieprocessor.enrichment.virustotal_quota.vt.Client') as mock_client_class:
            # Mock quota API responses
            mock_client = Mock()
            mock_client_class.return_value = mock_client
            
            # Mock user info and quota responses
            mock_client.get_json.side_effect = [
                {"data": {"id": "test-user-id"}},
                {"data": {"attributes": {"api_requests_daily": 500, "api_requests_hourly": 200, "api_requests_monthly": 5000, "api_requests": 1000}}},
                {"data": {"attributes": {"api_requests_daily": 100, "api_requests_hourly": 50, "api_requests_monthly": 1000, "api_requests": 250}}}
            ]
            
            service = EnrichmentService(
                cache_dir=cache_dir,
                vt_api="test-api-key",
                dshield_email=None,
                urlhaus_api=None,
                spur_api=None,
                enable_vt_quota_management=True,
            )
            
            # Test quota status retrieval
            quota_status = service.get_vt_quota_status()
            assert quota_status["status"] in ["healthy", "warning", "critical", "unknown"]
            assert "daily" in quota_status
            assert "hourly" in quota_status
            assert "can_make_request" in quota_status
            
            # Cleanup
            service.close()


if __name__ == "__main__":
    pytest.main([__file__])
