"""
Script to run on VPN nodes to report connections
Deploy this on each VPN node

Reads log every minute, saves position to continue from last read
"""

import requests
import re
import time
import os
import json

# Configuration - adjust for your setup
LOG_SERVER_URL = "http://your-server:5000/log"  # URL центрального сервера
NODE_NAME = "node-1"  # Имя этой ноды
XRAY_LOG_PATH = "/var/log/xray/access.log"  # Путь к логам Xray
STATE_FILE = "/tmp/node_reporter_state.json"  # Файл для сохранения позиции
READ_INTERVAL = 60  # Читать лог каждые 60 секунд


def load_state() -> dict:
    """Load last read position from state file"""
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, 'r') as f:
                return json.load(f)
    except Exception as e:
        print(f"[WARN] Could not load state: {e}")
    return {"position": 0, "inode": 0}


def save_state(position: int, inode: int):
    """Save current position to state file"""
    try:
        with open(STATE_FILE, 'w') as f:
            json.dump({"position": position, "inode": inode}, f)
    except Exception as e:
        print(f"[WARN] Could not save state: {e}")


def get_file_inode(filepath: str) -> int:
    """Get file inode to detect log rotation"""
    try:
        return os.stat(filepath).st_ino
    except:
        return 0


def parse_xray_log_line(line: str) -> tuple:
    """
    Parse Xray access log line
    Returns (username, ip) or (None, None)
    
    Example log format:
    2025/12/07 15:02:32.056701 from 178.176.86.81:16708 accepted tcp:... email: user_848055128
    """
    ip_pattern = r'from (\d+\.\d+\.\d+\.\d+):\d+'
    email_pattern = r'email:\s*(\S+)'
    
    ip_match = re.search(ip_pattern, line)
    email_match = re.search(email_pattern, line)
    
    if ip_match and email_match:
        ip = ip_match.group(1)
        username = email_match.group(1)
        return username, ip
    
    return None, None


def report_connections(connections: list):
    """Send batch of connections to central server"""
    if not connections:
        return
    
    try:
        response = requests.post(
            LOG_SERVER_URL.replace('/log', '/log_batch'),
            json={"connections": connections},
            timeout=30
        )
        if response.status_code == 200:
            print(f"[OK] Reported {len(connections)} connections")
        else:
            print(f"[ERROR] Server returned {response.status_code}")
    except requests.RequestException as e:
        print(f"[ERROR] Failed to report: {e}")


def read_new_lines():
    """Read new lines from log file since last position"""
    if not os.path.exists(XRAY_LOG_PATH):
        print(f"[WARN] Log file not found: {XRAY_LOG_PATH}")
        return []
    
    state = load_state()
    current_inode = get_file_inode(XRAY_LOG_PATH)
    
    # Если inode изменился — лог ротировался, читаем сначала
    if state["inode"] != current_inode:
        print("[INFO] Log file rotated, starting from beginning")
        state["position"] = 0
        state["inode"] = current_inode
    
    file_size = os.path.getsize(XRAY_LOG_PATH)
    
    # Если файл стал меньше — тоже ротация
    if file_size < state["position"]:
        print("[INFO] Log file truncated, starting from beginning")
        state["position"] = 0
    
    connections = []
    new_position = state["position"]
    
    try:
        with open(XRAY_LOG_PATH, 'r', encoding='utf-8', errors='ignore') as f:
            f.seek(state["position"])
            
            for line in f:
                username, ip = parse_xray_log_line(line.strip())
                if username and ip:
                    connections.append({
                        "user_email": username,
                        "ip_address": ip,
                        "node_name": NODE_NAME
                    })
            
            new_position = f.tell()
    
    except Exception as e:
        print(f"[ERROR] Failed to read log: {e}")
        return []
    
    # Сохраняем новую позицию
    save_state(new_position, current_inode)
    
    # Дедупликация — оставляем только уникальные пары user:ip
    seen = set()
    unique_connections = []
    for conn in connections:
        key = f"{conn['user_email']}:{conn['ip_address']}"
        if key not in seen:
            seen.add(key)
            unique_connections.append(conn)
    
    return unique_connections


def run_reporter():
    """Main reporter loop"""
    print(f"[START] Node reporter started for {NODE_NAME}")
    print(f"[INFO] Log file: {XRAY_LOG_PATH}")
    print(f"[INFO] Server: {LOG_SERVER_URL}")
    print(f"[INFO] Read interval: {READ_INTERVAL}s")
    
    while True:
        try:
            connections = read_new_lines()
            
            if connections:
                print(f"[INFO] Found {len(connections)} unique connections")
                report_connections(connections)
            else:
                print("[INFO] No new connections")
        
        except Exception as e:
            print(f"[ERROR] {e}")
        
        time.sleep(READ_INTERVAL)


if __name__ == '__main__':
    run_reporter()
