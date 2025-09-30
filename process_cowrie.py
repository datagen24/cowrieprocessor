import os
import io
import json
import time
import bz2
import gzip
import logging
import collections
import datetime
import sqlite3
from pathlib import Path
from typing import List, Dict, Optional
import dropbox
import requests

class CowrieProcessor:
    """
    CowrieProcessor encapsulates the complete pipeline for processing Cowrie honeypot logs:
    reading files, parsing commands, analyzing sessions, computing statistics, generating
    summaries, and optional Dropbox uploads. Designed to be importable and testable without
    side effects at import time.
    """

    def __init__(
        self,
        db_path: str,
        log_location: str,
        hostname: Optional[str] = None,
        jq_normalize: bool = False,
        max_line_bytes: Optional[int] = None,
        file_timeout: Optional[int] = None,
    ):
        """
        Initialize the CowrieProcessor with paths and optional limits.

        Args:
            db_path (str): Path to the SQLite database.
            log_location (str): Directory containing log files.
            hostname (Optional[str]): Hostname for session attribution.
            jq_normalize (bool): Whether to attempt JSON normalization pass.
            max_line_bytes (Optional[int]): Maximum line size to read from logs.
            file_timeout (Optional[int]): Maximum seconds to process a single file.
        """
        self.db_path = db_path
        self.log_location = log_location
        self.hostname = hostname or os.uname().nodename
        self.jq_normalize = jq_normalize
        self.max_line_bytes = max_line_bytes
        self.file_timeout = file_timeout

        self.con = sqlite3.connect(db_path)
        self.data: List[Dict] = []
        self.data_by_session: Dict[str, List[Dict]] = {}
        self.abnormal_attacks = set()
        self.uncommon_command_counts = set()
        self.vt_recent_submissions = []
        self.number_of_commands: List[int] = []
        self.abnormal_command_counts: List[int] = []
        self.vt_classifications: List[str] = []

    def db_commit(self):
        """
        Commit any pending transactions to the SQLite database.
        """
        self.con.commit()

    def open_json_lines(self, path: str):
        """
        Open a JSON Lines file, supporting .jsonl, .bz2, and .gz files.

        Args:
            path (str): Path to the log file.

        Returns:
            TextIOWrapper: File-like object for reading text lines.
        """
        if path.endswith('.bz2'):
            bz2_raw = bz2.BZ2File(path, 'rb')
            return io.TextIOWrapper(bz2_raw, encoding='utf-8', errors='replace')
        if path.endswith('.gz'):
            gz_raw = gzip.GzipFile(filename=path, mode='rb')
            return io.TextIOWrapper(gz_raw, encoding='utf-8', errors='replace')
        return open(path, 'r', encoding='utf-8', errors='replace')

    def process_file(self, filepath: str):
        """
        Process a single log file, parsing JSON entries and storing in memory.

        Args:
            filepath (str): Full path to the log file.

        Returns:
            int: Number of lines successfully read from the file.
        """
        file_started_at = time.time()
        line_count = 0
        t_last = time.time()
        for each_line in self.open_json_lines(filepath):
            if self.file_timeout and (time.time() - file_started_at) > self.file_timeout:
                logging.error("File processing timeout after %ss: %s", self.file_timeout, filepath)
                break
            if self.max_line_bytes and len(each_line) > self.max_line_bytes:
                logging.warning("Oversized JSON line skipped in %s", filepath)
                continue
            try:
                json_file = json.loads(each_line.replace('\0', ''))
                if isinstance(json_file, dict):
                    json_file['__source_file'] = os.path.basename(filepath)
                    self.data.append(json_file)
            except Exception:
                continue
            line_count += 1
            if line_count % 5000 == 0 or (time.time() - t_last) >= 5:
                t_last = time.time()
        return line_count

    def get_commands(self, session: str) -> str:
        """
        Collect all commands executed in a given session and store them in the database.

        Args:
            session (str): Session ID to process.

        Returns:
            str: Concatenated string of all commands prefixed by '# '.
        """
        cur = self.con.cursor()
        commands = ""
        for each_entry in self.data:
            if each_entry['session'] == session and "cowrie.command.input" in each_entry['eventid']:
                commands += "# " + each_entry['input'] + "\n"
                utc_time = datetime.datetime.strptime(each_entry['timestamp'], "%Y-%m-%dT%H:%M:%S.%fZ")
                epoch_time = (utc_time - datetime.datetime(1970, 1, 1)).total_seconds()
                cur.execute('''SELECT * FROM commands WHERE session=? and command=? and timestamp=? and hostname=?''',
                            (session, each_entry['input'], epoch_time, self.hostname))
                if not cur.fetchall():
                    cur.execute('''INSERT INTO commands(session, command, timestamp, added, hostname) VALUES (?,?,?,?,?)''',
                                (session, each_entry['input'], epoch_time, time.time(), self.hostname))
        self.db_commit()
        return commands

    def evaluate_sessions(self, target_sessions: List[str]):
        """
        Evaluate a list of sessions to identify abnormal or uncommon command counts.

        Args:
            target_sessions (List[str]): List of session IDs to evaluate.
        """
        for session_key in target_sessions:
            session_data = self.data_by_session.get(session_key, self.data)
            command_count = self.get_command_total(session_key, session_data)
            if command_count in self.abnormal_command_counts:
                self.abnormal_attacks.add(session_key)
                self.uncommon_command_counts.add(session_key)

    def get_command_total(self, session: str, session_data: List[Dict]) -> int:
        """
        Count total number of commands executed in a given session.

        Args:
            session (str): Session ID.
            session_data (List[Dict]): List of event dictionaries for the session.

        Returns:
            int: Total number of commands.
        """
        return sum(1 for entry in session_data if entry.get('session') == session and "cowrie.command.input" in entry.get('eventid', ''))

    def compute_command_statistics(self) -> Dict[int, int]:
        """
        Compute frequency statistics for the number of commands across sessions
        and identify abnormal command counts.

        Returns:
            Dict[int, int]: Mapping of command count -> occurrence count.
        """
        counts = collections.Counter(self.number_of_commands)
        self.number_of_commands.sort(key=lambda x: -counts[x])
        commands_set = set(self.number_of_commands)
        command_number_dict = {command: self.number_of_commands.count(command) for command in commands_set}
        sorted_command_counts = sorted(command_number_dict.items(), key=lambda x: x[1])
        self.abnormal_command_counts = [k for k, v in sorted_command_counts][:int(len(sorted_command_counts) * 2 / 3)]
        return command_number_dict

    def collect_vt_classifications(self) -> set:
        """
        Collect VirusTotal classifications and return unique set.

        Returns:
            set: Unique VT classifications.
        """
        counts = collections.Counter(self.vt_classifications)
        self.vt_classifications.sort(key=lambda x: -counts[x])
        return set(self.vt_classifications)

    def generate_summary_string(self, attack_count: int, command_number_dict: Dict[int, int]) -> str:
        """
        Generate a formatted summary string containing attack and command statistics.

        Args:
            attack_count (int): Total number of attacks.
            command_number_dict (Dict[int, int]): Command frequency dictionary.

        Returns:
            str: Formatted summary report string.
        """
        summarystring = f"{'Total Number of Attacks:':>40s}  {attack_count:10d}\n"
        most_common_commands = self.number_of_commands[0] if self.number_of_commands else "N/A"
        summarystring += f"{'Most Common Number of Commands:':>40s}  {str(most_common_commands):10s}\n\n"
        summarystring += f"{'Number of Commands':>40s}  {'Times Seen':10s}\n"
        summarystring += f"{'------------------':>40s}  {'----------':10s}\n"
        for key, value in command_number_dict.items():
            summarystring += f"{str(key):>40s}  {str(value):10s}\n"
        return summarystring

    def upload_to_dropbox(self, files: List[str], token: str):
        """
        Upload files to Dropbox.

        Args:
            files (List[str]): List of file paths to upload.
            token (str): Dropbox access token.
        """
        dbx = dropbox.Dropbox(token)
        for file_path in files:
            with open(file_path, 'rb') as f:
                dbx.files_upload(f.read(), "/" + os.path.basename(file_path))
