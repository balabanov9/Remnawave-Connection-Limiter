"""Database operations for tracking connections"""

import sqlite3
import time
from config import DB_PATH, IP_WINDOW_SECONDS


def init_db():
    """Initialize SQLite database"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Таблица подключений
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS connections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_email TEXT NOT NULL,
            ip_address TEXT NOT NULL,
            port TEXT,
            node_name TEXT,
            timestamp INTEGER NOT NULL
        )
    ''')
    
    # Добавляем колонку port если её нет (для миграции)
    try:
        cursor.execute('ALTER TABLE connections ADD COLUMN port TEXT')
    except sqlite3.OperationalError:
        pass  # Колонка уже существует
    

    
    # Индексы для быстрого поиска
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_user_email ON connections(user_email)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_timestamp ON connections(timestamp)')
    
    conn.commit()
    conn.close()


def log_connection(user_email: str, ip_address: str, port: str = None, node_name: str = None):
    """Log a new connection"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute(
        'INSERT INTO connections (user_email, ip_address, port, node_name, timestamp) VALUES (?, ?, ?, ?, ?)',
        (user_email, ip_address, port, node_name, int(time.time()))
    )
    
    conn.commit()
    conn.close()


def log_connections_batch(connections: list):
    """Log multiple connections at once (faster)
    connections: list of tuples (user_email, ip_address, port, node_name)
    """
    if not connections:
        return
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    timestamp = int(time.time())
    
    # Batch insert
    cursor.executemany(
        'INSERT INTO connections (user_email, ip_address, port, node_name, timestamp) VALUES (?, ?, ?, ?, ?)',
        [(c[0], c[1], c[2], c[3], timestamp) for c in connections]
    )
    
    conn.commit()
    conn.close()


def get_unique_ips(user_email: str) -> list:
    """Get unique IPs for user within time window"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cutoff_time = int(time.time()) - IP_WINDOW_SECONDS
    
    cursor.execute(
        'SELECT DISTINCT ip_address FROM connections WHERE user_email = ? AND timestamp > ?',
        (user_email, cutoff_time)
    )
    
    ips = [row[0] for row in cursor.fetchall()]
    conn.close()
    
    return ips


def get_unique_ips_with_ports(user_email: str) -> list:
    """Get unique IP:port pairs for user within time window"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cutoff_time = int(time.time()) - IP_WINDOW_SECONDS
    
    cursor.execute(
        'SELECT DISTINCT ip_address, port FROM connections WHERE user_email = ? AND timestamp > ?',
        (user_email, cutoff_time)
    )
    
    results = [(row[0], row[1]) for row in cursor.fetchall()]
    conn.close()
    
    return results


def get_all_active_users() -> list:
    """Get all users with recent connections"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cutoff_time = int(time.time()) - IP_WINDOW_SECONDS
    
    cursor.execute(
        'SELECT DISTINCT user_email FROM connections WHERE timestamp > ?',
        (cutoff_time,)
    )
    
    users = [row[0] for row in cursor.fetchall()]
    conn.close()
    
    return users


def add_blocked_user(user_email: str, blocked_until: int, original_status: str):
    """Add user to blocked list"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute(
        'INSERT OR REPLACE INTO blocked_users (user_email, blocked_until, original_status) VALUES (?, ?, ?)',
        (user_email, blocked_until, original_status)
    )
    
    conn.commit()
    conn.close()


def get_users_to_unblock() -> list:
    """Get users whose block time has expired"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    current_time = int(time.time())
    
    cursor.execute(
        'SELECT user_email, original_status FROM blocked_users WHERE blocked_until <= ?',
        (current_time,)
    )
    
    users = cursor.fetchall()
    conn.close()
    
    return users


def remove_blocked_user(user_email: str):
    """Remove user from blocked list"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('DELETE FROM blocked_users WHERE user_email = ?', (user_email,))
    
    conn.commit()
    conn.close()


def is_user_blocked(user_email: str) -> bool:
    """Check if user is currently blocked"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute(
        'SELECT 1 FROM blocked_users WHERE user_email = ? AND blocked_until > ?',
        (user_email, int(time.time()))
    )
    
    result = cursor.fetchone() is not None
    conn.close()
    
    return result


def cleanup_old_connections(max_age_seconds: int = 120):
    """
    Remove old connection records
    Default: удаляем записи старше 2 минут (держим только актуальные)
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cutoff_time = int(time.time()) - max_age_seconds
    
    cursor.execute('DELETE FROM connections WHERE timestamp < ?', (cutoff_time,))
    deleted = cursor.rowcount
    
    conn.commit()
    conn.close()
    
    if deleted > 0:
        print(f"[CLEANUP] Deleted {deleted} old connection records")
    
    return deleted


def get_user_ips_with_nodes(user_email: str) -> list:
    """Get IPs with their node names for a user"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cutoff_time = int(time.time()) - IP_WINDOW_SECONDS
    
    cursor.execute(
        'SELECT DISTINCT ip_address, node_name FROM connections WHERE user_email = ? AND timestamp > ?',
        (user_email, cutoff_time)
    )
    
    results = cursor.fetchall()
    conn.close()
    
    return results


def get_db_stats() -> dict:
    """Get database statistics"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('SELECT COUNT(*) FROM connections')
    total_connections = cursor.fetchone()[0]
    
    conn.close()
    
    return {
        "total_connections": total_connections
    }


def get_users_with_multiple_ips() -> list:
    """Get users who have more than 1 unique IP - returns [(username, [(ip, port), ...]), ...]"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cutoff_time = int(time.time()) - IP_WINDOW_SECONDS
    
    # First get users with >1 unique IP
    cursor.execute('''
        SELECT user_email, COUNT(DISTINCT ip_address) as ip_count
        FROM connections 
        WHERE timestamp > ?
        GROUP BY user_email
        HAVING ip_count > 1
    ''', (cutoff_time,))
    
    users_with_multi_ip = [row[0] for row in cursor.fetchall()]
    
    if not users_with_multi_ip:
        conn.close()
        return []
    
    # Get IP:port data for these users
    result = []
    for username in users_with_multi_ip:
        cursor.execute(
            'SELECT DISTINCT ip_address, port FROM connections WHERE user_email = ? AND timestamp > ?',
            (username, cutoff_time)
        )
        ip_data = [(row[0], row[1]) for row in cursor.fetchall()]
        result.append((username, ip_data))
    
    conn.close()
    return result
