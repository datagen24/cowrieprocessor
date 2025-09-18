"""Data processing utilities for Cowrie log analysis.

This module contains functions for processing and indexing Cowrie log data
efficiently, including session-based data extraction and command counting.
"""

import logging
from typing import Dict, List, Any, Optional


def pre_index_data_by_session(data: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Pre-index data by session for much better performance.
    
    Args:
        data: List of Cowrie event dictionaries
        
    Returns:
        Dictionary mapping session IDs to lists of their events
    """
    logging.info("Pre-indexing data by session for better performance...")
    data_by_session = {}
    for entry in data:
        session = entry.get('session')
        if session:
            if session not in data_by_session:
                data_by_session[session] = []
            data_by_session[session].append(entry)
    
    logging.info(f"Pre-indexed data for {len(data_by_session)} sessions")
    return data_by_session


def get_session_id(data: List[Dict[str, Any]], type: str, match: str) -> List[str]:
    """Extract unique session IDs from data based on criteria.
    
    Args:
        data: List of Cowrie event dictionaries
        type: Type of extraction ("all", "tty", "download")
        match: Match criteria
        
    Returns:
        List of unique session ID strings
    """
    logging.info("Extracting unique sessions...")
    sessions = set()
    
    if type == "tty":
        for each_entry in data:
            if "ttylog" in each_entry:
                if each_entry['ttylog'] == ("var/lib/cowrie/tty/" + match):
                    sessions.add(each_entry['session'])
    elif type == "download":
        for each_entry in data:
            if "shasum" in each_entry:
                if each_entry['shasum'] == match:
                    sessions.add(each_entry['session'])
    elif type == "all":
        for each_entry in data:
            if each_entry['eventid'] == "cowrie.login.success":
                sessions.add(each_entry['session'])
    
    return list(sessions)


def get_protocol_login(session: str, data: List[Dict[str, Any]]) -> Optional[str]:
    """Get protocol from session connection.
    
    Args:
        session: Session ID string
        data: List of Cowrie event dictionaries
        
    Returns:
        Protocol string (e.g., "ssh" or "telnet") if found, else None
    """
    logging.info("Getting protocol from session connection...")
    for each_entry in data:
        if each_entry['session'] == session:
            if each_entry['eventid'] == "cowrie.session.connect":
                return each_entry['protocol']
    return None


def get_session_duration(session: str, data: List[Dict[str, Any]]) -> str:
    """Get session duration.
    
    Args:
        session: Session ID string
        data: List of Cowrie event dictionaries
        
    Returns:
        Duration string
    """
    logging.info("Getting session durations...")
    duration = ""
    for each_entry in data:
        if each_entry['session'] == session:
            if each_entry['eventid'] == "cowrie.session.closed":
                duration = each_entry['duration']
    return duration


def get_login_data(session: str, data: List[Dict[str, Any]]) -> tuple:
    """Extract login details for a session.
    
    Args:
        session: Session ID string
        data: List of Cowrie event dictionaries
        
    Returns:
        Tuple (username, password, timestamp, src_ip) for the first
        cowrie.login.success entry in the session, or None if absent
    """
    for each_entry in data:
        if each_entry['session'] == session:
            if each_entry['eventid'] == "cowrie.login.success":
                return each_entry['username'], each_entry['password'], each_entry['timestamp'], each_entry['src_ip']
    return None


def get_command_total(session: str, data: List[Dict[str, Any]]) -> int:
    """Count commands executed in a session.
    
    Args:
        session: Session ID string
        data: List of Cowrie event dictionaries
        
    Returns:
        Integer count of events whose eventid starts with cowrie.command.
    """
    count = 0
    for each_entry in data:
        if each_entry['session'] == session:
            if "cowrie.command." in each_entry['eventid']:
                count += 1
    return count


def get_file_download(session: str, data: List[Dict[str, Any]]) -> List[List[str]]:
    """Collect file download events for a session.
    
    Args:
        session: Session ID string
        data: List of Cowrie event dictionaries
        
    Returns:
        A list of [url, shasum, src_ip, destfile] for each download
    """
    import re
    
    url = ""
    download_ip = ""
    shasum = ""
    destfile = ""
    returndata = []
    
    for each_entry in data:
        if each_entry['session'] == session:
            if each_entry['eventid'] == "cowrie.session.file_download":
                if "url" in each_entry:
                    url = each_entry['url'].replace(".", "[.]").replace("://", "[://]")
                    try:
                        download_ip = re.findall(
                            r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})",
                            each_entry['url'],
                        )[0]
                    except Exception:
                        download_ip = re.findall(r"\:\/\/(.*?)\/", each_entry['url'])[0]
                if "shasum" in each_entry:
                    shasum = each_entry['shasum']
                if "destfile" in each_entry:
                    destfile = each_entry['destfile']
                returndata.append([url, shasum, download_ip, destfile])
    return returndata


def get_file_upload(session: str, data: List[Dict[str, Any]]) -> List[List[str]]:
    """Collect file upload events for a session.
    
    Args:
        session: Session ID string
        data: List of Cowrie event dictionaries
        
    Returns:
        A list of [url, shasum, src_ip, filename] for each upload
    """
    import re
    
    url = ""
    upload_ip = ""
    shasum = ""
    destfile = ""
    returndata = []
    
    for each_entry in data:
        if each_entry['session'] == session:
            if each_entry['eventid'] == "cowrie.session.file_upload":
                if "url" in each_entry:
                    url = each_entry['url'].replace(".", "[.]").replace("://", "[://]")
                    try:
                        upload_ip = re.findall(
                            r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})",
                            each_entry['url'],
                        )[0]
                    except Exception:
                        upload_ip = re.findall(r"\:\/\/(.*?)\/", each_entry['url'])[0]
                if "shasum" in each_entry:
                    shasum = each_entry['shasum']
                if "filename" in each_entry:
                    destfile = each_entry['filename']
                returndata.append([url, shasum, upload_ip, destfile])
    return returndata
