"""Unit tests for file organizer utility."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock, patch

from cowrieprocessor.cli.file_organizer import _get_target_directory, main, organize_files


class TestFileOrganizer:
    """Test cases for FileOrganizer utility."""

    def test_organize_files_empty_directory(self, tmp_path: Path) -> None:
        """Test organize_files with empty directory."""
        result = organize_files(tmp_path)
        assert result["iptables_files"] == []
        assert result["cowrie_files"] == []
        assert result["webhoneypot_files"] == []
        assert result["unknown_files"] == []
        assert result["errors"] == []

    def test_organize_files_with_cowrie_json_file(self, tmp_path: Path) -> None:
        """Test organize_files detects cowrie JSON files."""
        # Create a cowrie JSON file
        cowrie_file = tmp_path / "cowrie.json"
        cowrie_file.write_text('{"eventid": "cowrie.session.connect", "session": "test123"}')

        result = organize_files(tmp_path, dry_run=True)

        assert len(result["cowrie_files"]) == 1
        assert result["cowrie_files"][0] == cowrie_file
        assert result["iptables_files"] == []
        assert result["webhoneypot_files"] == []

    def test_organize_files_with_iptables_file(self, tmp_path: Path) -> None:
        """Test organize_files detects iptables files."""
        # Create an iptables file with correct format (timestamp hostname kernel: DSHIELDINPUT)
        iptables_file = tmp_path / "iptables.log"
        iptables_file.write_text("1234567890 hostname kernel: DSHIELDINPUT DROP all")

        result = organize_files(tmp_path, dry_run=True)

        assert len(result["iptables_files"]) == 1
        assert result["iptables_files"][0] == iptables_file

    def test_organize_files_with_unknown_file(self, tmp_path: Path) -> None:
        """Test organize_files handles unknown file types."""
        # Create an unknown file
        unknown_file = tmp_path / "unknown.txt"
        unknown_file.write_text("random text content")

        result = organize_files(tmp_path, dry_run=True)

        assert len(result["unknown_files"]) == 1
        file_path, file_type, reason = result["unknown_files"][0]
        assert file_path == unknown_file
        assert file_type == "structured_log"  # Based on FileTypeDetector behavior

    def test_organize_files_with_mixed_content(self, tmp_path: Path) -> None:
        """Test organize_files with multiple file types."""
        # Create multiple files
        cowrie_file = tmp_path / "cowrie.json"
        cowrie_file.write_text('{"eventid": "cowrie.session.connect"}')

        iptables_file = tmp_path / "iptables.log"
        iptables_file.write_text("1234567890 hostname kernel: DSHIELDINPUT")

        unknown_file = tmp_path / "unknown.txt"
        unknown_file.write_text("random content")

        result = organize_files(tmp_path, dry_run=True)

        assert len(result["cowrie_files"]) == 1
        assert len(result["iptables_files"]) == 1
        assert len(result["unknown_files"]) == 1

    def test_organize_files_skips_already_organized_files(self, tmp_path: Path) -> None:
        """Test organize_files skips files already in organized directories."""
        # Create directory structure
        cowrie_dir = tmp_path / "cowrie"
        cowrie_dir.mkdir()

        # Create file already in cowrie directory
        cowrie_file = cowrie_dir / "session.json"
        cowrie_file.write_text('{"eventid": "cowrie.session.connect"}')

        result = organize_files(tmp_path, dry_run=True)

        # Should not detect files already in organized directories
        assert result["cowrie_files"] == []
        assert result["iptables_files"] == []
        assert result["unknown_files"] == []
        assert result["errors"] == []

    def test_organize_files_handles_file_processing_errors(self, tmp_path: Path) -> None:
        """Test organize_files handles file processing errors gracefully."""
        # Create a file that will cause an error (e.g., permission denied)
        # For this test, we'll mock the FileTypeDetector to raise an exception

        with patch('cowrieprocessor.cli.file_organizer.FileTypeDetector.should_process_as_json') as mock_detector:
            mock_detector.side_effect = Exception("Test error")

            error_file = tmp_path / "error.json"
            error_file.write_text('{"eventid": "cowrie.session.connect"}')

            result = organize_files(tmp_path, dry_run=True)

            assert len(result["errors"]) == 1
            file_path, error_msg = result["errors"][0]
            assert file_path == error_file
            assert "Test error" in error_msg

    def test_get_target_directory_with_nsm_directory(self, tmp_path: Path) -> None:
        """Test _get_target_directory finds NSM directory correctly."""
        # Create directory structure with NSM
        nsm_dir = tmp_path / "NSM"
        nsm_dir.mkdir()

        test_file = nsm_dir / "subdir" / "cowrie.json"
        test_file.parent.mkdir(parents=True)

        target = _get_target_directory(test_file, "cowrie")

        assert target == nsm_dir / "cowrie"

    def test_get_target_directory_without_nsm_directory(self, tmp_path: Path) -> None:
        """Test _get_target_directory creates NSM directory when not found."""
        test_file = tmp_path / "subdir" / "cowrie.json"
        test_file.parent.mkdir(parents=True)

        target = _get_target_directory(test_file, "cowrie")

        expected = test_file.parent / "NSM" / "cowrie"
        assert target == expected

    def test_get_target_directory_at_root(self, tmp_path: Path) -> None:
        """Test _get_target_directory handles root directory correctly."""
        # Create file directly in temp directory
        test_file = tmp_path / "cowrie.json"

        target = _get_target_directory(test_file, "cowrie")

        expected = tmp_path / "NSM" / "cowrie"
        assert target == expected

    @patch('cowrieprocessor.cli.file_organizer.argparse.ArgumentParser.parse_args')
    def test_main_with_dry_run(self, mock_args) -> None:
        """Test main function with dry run mode."""
        # Mock arguments
        mock_args.return_value = Mock(
            source="/test/dir",
            dry_run=True,
            move=False,
            verbose=False,
        )

        with (
            patch('cowrieprocessor.cli.file_organizer.Path.exists') as mock_exists,
            patch('cowrieprocessor.cli.file_organizer.organize_files') as mock_organize,
        ):
            mock_exists.return_value = True
            mock_organize.return_value = {
                'iptables_files': [],
                'cowrie_files': [],
                'webhoneypot_files': [],
                'unknown_files': [],
                'errors': [],
            }

            result = main()

            assert result == 0
            mock_organize.assert_called_once()

    @patch('cowrieprocessor.cli.file_organizer.argparse.ArgumentParser.parse_args')
    def test_main_with_nonexistent_directory(self, mock_args) -> None:
        """Test main function with nonexistent source directory."""
        # Mock arguments
        mock_args.return_value = Mock(
            source="/nonexistent/dir",
            dry_run=True,
            move=False,
            verbose=False,
        )

        with patch('cowrieprocessor.cli.file_organizer.Path.exists') as mock_exists:
            mock_exists.return_value = False

            result = main()

            assert result == 1

    @patch('cowrieprocessor.cli.file_organizer.argparse.ArgumentParser.parse_args')
    def test_main_with_move_mode(self, mock_args) -> None:
        """Test main function with move mode enabled."""
        # Mock arguments
        mock_args.return_value = Mock(
            source="/test/dir",
            dry_run=False,
            move=True,
            verbose=False,
        )

        with (
            patch('cowrieprocessor.cli.file_organizer.Path.exists') as mock_exists,
            patch('cowrieprocessor.cli.file_organizer.organize_files') as mock_organize,
            patch('cowrieprocessor.cli.file_organizer.print') as mock_print,
        ):
            mock_exists.return_value = True
            mock_organize.return_value = {
                'iptables_files': [],
                'cowrie_files': [],
                'webhoneypot_files': [],
                'unknown_files': [],
                'errors': [],
            }

            result = main()

            assert result == 0
            mock_print.assert_any_call("Mode: MOVING FILES")

    def test_organize_files_with_results_output(self, tmp_path: Path) -> None:
        """Test organize_files produces correct results structure."""
        # Create test files
        cowrie_file = tmp_path / "cowrie.json"
        cowrie_file.write_text('{"eventid": "cowrie.session.connect"}')

        iptables_file = tmp_path / "iptables.log"
        iptables_file.write_text("1234567890 kernel DSHIELDINPUT")

        result = organize_files(tmp_path, dry_run=True)

        # Verify structure
        assert isinstance(result, dict)
        assert "iptables_files" in result
        assert "cowrie_files" in result
        assert "webhoneypot_files" in result
        assert "unknown_files" in result
        assert "errors" in result

        # Verify types
        assert isinstance(result["iptables_files"], list)
        assert isinstance(result["cowrie_files"], list)
        assert isinstance(result["webhoneypot_files"], list)
        assert isinstance(result["unknown_files"], list)
        assert isinstance(result["errors"], list)

    def test_organize_files_with_nested_directories(self, tmp_path: Path) -> None:
        """Test organize_files handles nested directory structures."""
        # Create nested structure
        nested_dir = tmp_path / "subdir" / "nested"
        nested_dir.mkdir(parents=True)

        cowrie_file = nested_dir / "cowrie.json"
        cowrie_file.write_text('{"eventid": "cowrie.session.connect"}')

        result = organize_files(tmp_path, dry_run=True)

        assert len(result["cowrie_files"]) == 1
        assert result["cowrie_files"][0] == cowrie_file

    def test_organize_files_with_special_filenames(self, tmp_path: Path) -> None:
        """Test organize_files handles special characters in filenames."""
        # Create file with special characters
        special_file = tmp_path / "cowrie_special-123.json"
        special_file.write_text('{"eventid": "cowrie.session.connect"}')

        result = organize_files(tmp_path, dry_run=True)

        assert len(result["cowrie_files"]) == 1
        assert result["cowrie_files"][0] == special_file
