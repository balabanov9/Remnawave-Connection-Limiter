"""
Script to run on VPN nodes to report connections and handle IP blocking
Deploy this on each VPN node
"""

import requests
import re
import time
import os
import json
import subprocess
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

# Configuration - adjust for your setup
LOG_SERVER_URL = "http://your-server:5000/log"  # URL центрального сервера
NODE_NAME = "node-1"  # Имя этой ноды
XRAY_LOG_PATH = "/var/log/xray/access.log"  # Путь к логам Xray
STATE_FILE = "/tmp/node_reporter_state.json"  # Файл для сохранения позиции
READ_INTERVAL = 60  # Читать лог каждые 60 секунд

# API server for receiving block commands
API_PORT = 5001  # Порт для приема команд блокировки
API_SECRET = "change_this_secret"  # Секретный ключ для авторизации

# Blocked IPs storage
blocked_ips = {}  # {ip: unblock_time}
blocked_ips_lock = threading.Lock()


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
    """Parse Xray access log line"""
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
    
    if state["inode"] != current_inode:
        print("[INFO] Log file rotated, starting from beginning")
        state["position"] = 0
        state["inode"] = current_inode
    
    file_size = os.path.getsize(XRAY_LOG_PATH)
    
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
    
    save_state(new_position, current_inode)
    
    # Deduplicate
    seen = set()
    unique_connections = []
    for conn in connections:
        key = f"{conn['user_email']}:{conn['ip_address']}"
        if key not in seen:
            seen.add(key)
            unique_connections.append(conn)
    
    return unique_connections


# ============ IP BLOCKING ============

def block_ip(ip: str, duration: int = 120):
    """Block IP using iptables"""
    try:
        # Check if already blocked
        result = subprocess.run(
            ['iptables', '-C', 'INPUT', '-s', ip, '-j', 'DROP'],
            capture_output=True
        )
        
        if result.returncode != 0:
            # Not blocked, add rule
            subprocess.run(
                ['iptables', '-A', 'INPUT', '-s', ip, '-j', 'DROP'],
                check=True
            )
            print(f"[BLOCKED] IP {ip} for {duration}s")
        else:
            print(f"[INFO] IP {ip} already blocked")
        
        # Schedule unblock
        with blocked_ips_lock:
            blocked_ips[ip] = time.time() + duration
        
        return True
    except Exception as e:
        print(f"[ERROR] Failed to block IP {ip}: {e}")
        return False


def unblock_ip(ip: str):
    """Unblock IP"""
    try:
        subprocess.run(
            ['iptables', '-D', 'INPUT', '-s', ip, '-j', 'DROP'],
            check=True,
            capture_output=True
        )
        print(f"[UNBLOCKED] IP {ip}")
        return True
    except Exception as e:
        # Rule might not exist
        return False


def cleanup_expired_blocks():
    """Remove expired IP blocks"""
    current_time = time.time()
    to_unblock = []
    
    with blocked_ips_lock:
        for ip, unblock_time in list(blocked_ips.items()):
            if current_time >= unblock_time:
                to_unblock.append(ip)
                del blocked_ips[ip]
    
    for ip in to_unblock:
        unblock_ip(ip)


# ============ HTTP API SERVER ============

class BlockAPIHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Suppress default logging
    
    def do_POST(self):
        if self.path == '/block_ip':
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length).decode('utf-8')
            
            try:
                data = json.loads(body)
                
                # Check secret
                if data.get('secret') != API_SECRET:
                    self.send_response(403)
                    self.end_headers()
                    self.wfile.write(b'{"error": "Invalid secret"}')
                    return
                
                ip = data.get('ip')
                duration = data.get('duration', 120)
                
                if not ip:
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(b'{"error": "Missing ip"}')
                    return
                
                success = block_ip(ip, duration)
                
                self.send_response(200 if success else 500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"success": success, "ip": ip}).encode())
                
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())
        
        elif self.path == '/unblock_ip':
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length).decode('utf-8')
            
            try:
                data = json.loads(body)
                
                if data.get('secret') != API_SECRET:
                    self.send_response(403)
                    self.end_headers()
                    return
                
                ip = data.get('ip')
                if ip:
                    unblock_ip(ip)
                    with blocked_ips_lock:
                        blocked_ips.pop(ip, None)
                
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"success": true}')
                
            except Exception as e:
                self.send_response(500)
                self.end_headers()
        
        else:
            self.send_response(404)
            self.end_headers()
    
    def do_GET(self):
        if self.path == '/health':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"status": "ok"}')
        else:
            self.send_response(404)
            self.end_headers()


def run_api_server():
    """Run HTTP API server for block commands"""
    server = HTTPServer(('0.0.0.0', API_PORT), BlockAPIHandler)
    print(f"[API] Listening on port {API_PORT}")
    server.serve_forever()


# ============ MAIN ============

def run_reporter():
    """Main reporter loop"""
    print(f"[START] Node reporter started for {NODE_NAME}")
    print(f"[INFO] Log file: {XRAY_LOG_PATH}")
    print(f"[INFO] Server: {LOG_SERVER_URL}")
    print(f"[INFO] API port: {API_PORT}")
    
    # Start API server in background
    api_thread = threading.Thread(target=run_api_server, daemon=True)
    api_thread.start()
    
    while True:
        try:
            # Read and report connections
            connections = read_new_lines()
            
            if connections:
                print(f"[INFO] Found {len(connections)} unique connections")
                report_connections(connections)
            
            # Cleanup expired blocks
            cleanup_expired_blocks()
        
        except Exception as e:
            print(f"[ERROR] {e}")
        
        time.sleep(READ_INTERVAL)


if __name__ == '__main__':
    run_reporter()
