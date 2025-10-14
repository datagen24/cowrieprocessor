"""Extract passwords from Cowrie login events."""

from __future__ import annotations

import hashlib
from typing import Any, Dict, List

from ..db.models import RawEvent


class PasswordExtractor:
    """Extract password attempts from Cowrie events.
    
    Identifies login events (success and failed) and extracts password details
    for breach checking and credential stuffing detection.
    """

    LOGIN_EVENT_TYPES = [
        'cowrie.login.success',
        'cowrie.login.failed',
    ]

    def extract_from_events(self, events: List[RawEvent]) -> List[Dict[str, Any]]:
        """Extract password attempts from raw events.
        
        Args:
            events: List of RawEvent objects to process
            
        Returns:
            List of dictionaries containing password attempt details:
                - password: The actual password (for HIBP checking)
                - password_sha256: SHA-256 hash for tracking
                - username: Username from the login attempt
                - timestamp: Timestamp of the attempt
                - success: Whether login was successful
                - event_type: Original event type
        """
        passwords = []
        
        for event in events:
            if event.event_type not in self.LOGIN_EVENT_TYPES:
                continue
            
            if not event.payload:
                continue
                
            password = event.payload.get('password')
            if not password or not isinstance(password, str):
                continue
            
            # Generate SHA-256 hash for tracking (never log the actual password)
            password_sha256 = hashlib.sha256(password.encode('utf-8')).hexdigest()
            
            passwords.append({
                'password': password,
                'password_sha256': password_sha256,
                'username': event.payload.get('username', ''),
                'timestamp': event.event_timestamp or '',
                'success': 'success' in event.event_type,
                'event_type': event.event_type,
            })
        
        return passwords

    def extract_unique_passwords(self, events: List[RawEvent]) -> List[str]:
        """Extract unique passwords from events (for bulk checking).
        
        Args:
            events: List of RawEvent objects to process
            
        Returns:
            List of unique passwords
        """
        password_attempts = self.extract_from_events(events)
        unique_passwords = list({attempt['password'] for attempt in password_attempts})
        return unique_passwords


__all__ = ['PasswordExtractor']

