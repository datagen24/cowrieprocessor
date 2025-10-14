"""Tests for the enrichment cleanup script."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

from cowrieprocessor.enrichment import EnrichmentCacheManager


class TestEnrichmentCleanup:
    """Test the enrichment cleanup functionality."""

    def test_cleanup_script_with_dry_run(self) -> None:
        """Test cleanup script in dry run mode."""
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_dir = Path(temp_dir)
            
            # Create some test cache files
            cache_manager = EnrichmentCacheManager(base_dir=cache_dir)
            
            # Store some test data
            test_data = {"test": "data", "timestamp": "2025-01-01T00:00:00Z"}
            cache_manager.store_cached("test_service", "test_key", test_data)
            
            # Verify file was created
            cache_path = cache_manager.get_path("test_service", "test_key")
            assert cache_path.exists()
            
            # Test dry run
            from scripts.enrichment_cleanup import main
            
            with patch('sys.argv', ['enrichment_cleanup.py', '--cache-dir', str(cache_dir), '--dry-run']):
                result = main()
                assert result == 0

    def test_cleanup_script_with_nonexistent_directory(self) -> None:
        """Test cleanup script with nonexistent cache directory."""
        nonexistent_dir = Path("/nonexistent/cache/directory")
        
        from scripts.enrichment_cleanup import main
        
        with patch('sys.argv', ['enrichment_cleanup.py', '--cache-dir', str(nonexistent_dir)]):
            result = main()
            assert result == 1

    def test_cleanup_script_with_file_instead_of_directory(self) -> None:
        """Test cleanup script with file instead of directory."""
        with tempfile.NamedTemporaryFile() as temp_file:
            temp_path = Path(temp_file.name)
            
            from scripts.enrichment_cleanup import main
            
            with patch('sys.argv', ['enrichment_cleanup.py', '--cache-dir', str(temp_path)]):
                result = main()
                assert result == 1

    def test_cleanup_script_verbose_mode(self) -> None:
        """Test cleanup script with verbose logging."""
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_dir = Path(temp_dir)
            
            from scripts.enrichment_cleanup import main
            
            with patch('sys.argv', ['enrichment_cleanup.py', '--cache-dir', str(cache_dir), '--verbose', '--dry-run']):
                result = main()
                assert result == 0

    def test_cleanup_script_actual_cleanup(self) -> None:
        """Test cleanup script performing actual cleanup."""
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_dir = Path(temp_dir)
            
            # Create cache manager and store test data
            cache_manager = EnrichmentCacheManager(base_dir=cache_dir)
            
            # Store some test data using a service with known TTL
            test_data = {"test": "data"}
            cache_manager.store_cached("dshield", "test_key", test_data)  # Use dshield which has 7-day TTL
            
            # Verify file was created
            cache_path = cache_manager.get_path("dshield", "test_key")
            assert cache_path.exists()
            
            # Manually expire the file by modifying its timestamp
            import os
            old_time = os.path.getmtime(cache_path) - (8 * 24 * 3600)  # 8 days ago (older than 7-day TTL)
            os.utime(cache_path, (old_time, old_time))
            
            # Run cleanup
            from scripts.enrichment_cleanup import main
            
            with patch('sys.argv', ['enrichment_cleanup.py', '--cache-dir', str(cache_dir)]):
                result = main()
                assert result == 0
            
            # Verify file was deleted
            assert not cache_path.exists()

    def test_cleanup_script_with_multiple_services(self) -> None:
        """Test cleanup script with multiple services."""
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_dir = Path(temp_dir)
            
            # Create cache manager
            cache_manager = EnrichmentCacheManager(base_dir=cache_dir)
            
            # Store data for multiple services
            services = ["dshield", "virustotal", "urlhaus", "spur"]
            for service in services:
                test_data = {"service": service, "data": "test"}
                cache_manager.store_cached(service, f"test_key_{service}", test_data)
            
            # Verify files were created
            for service in services:
                cache_path = cache_manager.get_path(service, f"test_key_{service}")
                assert cache_path.exists()
            
            # Run dry run cleanup
            from scripts.enrichment_cleanup import main
            
            with patch('sys.argv', ['enrichment_cleanup.py', '--cache-dir', str(cache_dir), '--dry-run']):
                result = main()
                assert result == 0

    def test_cleanup_script_error_handling(self) -> None:
        """Test cleanup script error handling."""
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_dir = Path(temp_dir)
            
            # Create a cache manager
            cache_manager = EnrichmentCacheManager(base_dir=cache_dir)
            
            # Store some test data
            test_data = {"test": "data"}
            cache_manager.store_cached("test_service", "test_key", test_data)
            
            # Mock the EnrichmentCacheManager class to raise an exception
            with patch('scripts.enrichment_cleanup.EnrichmentCacheManager') as mock_class:
                mock_instance = mock_class.return_value
                mock_instance.snapshot.return_value = {"hits": 0, "misses": 0, "stores": 1}
                mock_instance.cleanup_expired.side_effect = Exception("Test error")
                
                from scripts.enrichment_cleanup import main
                
                with patch('sys.argv', ['enrichment_cleanup.py', '--cache-dir', str(cache_dir)]):
                    result = main()
                    assert result == 1

    def test_cleanup_script_permission_error(self) -> None:
        """Test cleanup script with permission errors."""
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_dir = Path(temp_dir)
            
            # Create cache manager
            cache_manager = EnrichmentCacheManager(base_dir=cache_dir)
            
            # Store some test data
            test_data = {"test": "data"}
            cache_manager.store_cached("test_service", "test_key", test_data)
            
            # Mock cleanup_expired to return errors
            mock_stats = {"scanned": 1, "deleted": 0, "errors": 1}
            with patch('scripts.enrichment_cleanup.EnrichmentCacheManager') as mock_class:
                mock_instance = mock_class.return_value
                mock_instance.snapshot.return_value = {"hits": 0, "misses": 0, "stores": 1}
                mock_instance.cleanup_expired.return_value = mock_stats
                
                from scripts.enrichment_cleanup import main
                
                with patch('sys.argv', ['enrichment_cleanup.py', '--cache-dir', str(cache_dir)]):
                    result = main()
                    assert result == 1
