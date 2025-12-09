"""Events log for admin panel with console capture"""

import sys
import time
from collections import deque
from threading import Lock

# Хранилище последних событий (максимум 200)
MAX_EVENTS = 200
events = deque(maxlen=MAX_EVENTS)
events_lock = Lock()

# Оригинальный stdout
_original_stdout = sys.stdout


class LogCapture:
    """Capture print() output and send to events log"""
    
    def __init__(self, original):
        self.original = original
    
    def write(self, text):
        # Пишем в оригинальный stdout
        self.original.write(text)
        
        # Добавляем в events если не пустая строка
        text = text.strip()
        if text:
            event_type = "info"
            if "[ERROR]" in text:
                event_type = "error"
            elif "[DROP]" in text or "[EXCESS]" in text:
                event_type = "drop"
            elif "[WARN]" in text:
                event_type = "warn"
            
            add_event(event_type, text)
    
    def flush(self):
        self.original.flush()


def start_capture():
    """Start capturing print output"""
    sys.stdout = LogCapture(_original_stdout)


def add_event(event_type: str, message: str, details: dict = None):
    """Add event to log"""
    event = {
        "time": time.strftime("%H:%M:%S"),
        "timestamp": int(time.time()),
        "type": event_type,
        "message": message,
        "details": details or {}
    }
    with events_lock:
        events.appendleft(event)


def get_events(limit: int = 50) -> list:
    """Get recent events"""
    with events_lock:
        return list(events)[:limit]


def clear_events():
    """Clear all events"""
    with events_lock:
        events.clear()


# Event types
def log_drop(username: str, ip_count: int, limit: int, dropped_ips: list):
    """Log drop event"""
    add_event(
        "drop",
        f"User {username}: {ip_count} IPs, limit {limit}",
        {"username": username, "ip_count": ip_count, "limit": limit, "dropped": dropped_ips}
    )


def log_error(message: str, details: dict = None):
    """Log error event"""
    add_event("error", message, details)


def log_info(message: str, details: dict = None):
    """Log info event"""
    add_event("info", message, details)
