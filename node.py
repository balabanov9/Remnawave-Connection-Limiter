#!/usr/bin/env python3
"""
Connection Limiter - Node Reporter (Enhanced)
- Real-time log monitoring with batch sending
- Handles DROP commands via iptables
"""

import os
import re
import time
import json
import subprocess
import threading
from pathlib import Path
from collections import deque
from http.server import HTTPServer, BaseHTTPRequestHandler
import requests

# ============ CONFIG ============

def load_env():
    env_file = Path(__file__).parent / '.env'
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.strip() and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip())

load_env()

SERVER_URL = os.getenv('SERVER_URL', 'http://localhost:5000')
NODE_NAME = os.getenv('NODE_NAME', 'node-1')
LOG_PATH = os.getenv('LOG_PATH', '/var/log/remnanode/access.log')
API_PORT = int(os.getenv('API_PORT', '5001'))
API_SECRET = os.getenv('API_SECRET', 'secret')
BATCH_SIZE = int(os.getenv('BATCH_SIZE', '50'))
BATCH_INTERVAL = float(os.getenv('BATCH_INTERVAL', '1.0'))

# ============ STATE ============

blocked_ips = {}  # ip -> expire_time
blocked_lock = threading.Lock()
pending_entries = deque()
pending_lock = threading.Lock()
session = requests.Session()
stats = {'sent': 0, 'parsed': 0, 'errors': 0}

# ============ LOG PARSING ============

# Multiple patterns for different Xray log formats
PATTERNS = [
    # Standard: from tcp:1.2.3.4:12345 ... email: user_123
    (re.compile(r'from (?:tcp:)?(\d+\.\d+\.\d+\.\d+):\d+'), re.compile(r'email:\s*(\S+)')),
    # Alternative: [user_123] 1.2.3.4:12345
    (re.compile(r'\[([^\]]+)\].*?(\d+\.\d+\.\d+\.\d+)'), None),
]

def parse_line(line: str):
    """Parse Xray log line -> (user, ip) or (None, None)"""
    # Try standard pattern first
    ip_match = re.search(r'from (?:tcp:)?(\d+\.\d+\.\d+\.\d+):\d+', line)
    email_match = re.search(r'email:\s*(\S+)', line)
    
    if ip_match and email_match:
        return email_match.group(1), ip_match.group(1)
    
    # Try to find any IP and user pattern
    ip_match = re.search(r'(\d+\.\d+\.\d+\.\d+)', line)
    user_match = re.search(r'(user_\d+)', line)
    
    if ip_match and user_match:
        return user_match.group(1), ip_match.group(1)
    
    return None, None

def send_batch(entries):
    """Send batch of entries to server"""
    if not entries:
        return
    
    try:
        url = SERVER_URL.rstrip('/') + '/log_batch'
        resp = session.post(url, json={
            'node': NODE_NAME,
            'entries': list(entries)
        }, timeout=5)
        
        if resp.status_code == 200:
            stats['sent'] += len(entries)
        else:
            stats['errors'] += 1
            print(f"[!] Server returned {resp.status_code}")
    except Exception as e:
        stats['errors'] += 1
        print(f"[!] Send error: {e}")

def batch_sender():
    """Background thread that sends batches"""
    while True:
        time.sleep(BATCH_INTERVAL)
        
        with pending_lock:
            if pending_entries:
                batch = []
                while pending_entries and len(batch) < BATCH_SIZE:
                    batch.append(pending_entries.popleft())
                
                if batch:
                    send_batch(batch)

def tail_log():
    """Tail log file and collect entries"""
    print(f"[*] Watching {LOG_PATH}")
    print(f"[*] Server: {SERVER_URL}")
    print(f"[*] Node: {NODE_NAME}")
    
    while not os.path.exists(LOG_PATH):
        print(f"[WAIT] Log file not found, waiting...")
        time.sleep(5)
    
    print(f"[OK] Log file found")
    
    f = open(LOG_PATH, 'r')
    f.seek(0, 2)  # End of file
    inode = os.stat(LOG_PATH).st_ino
    last_report = time.time()
    
    while True:
        line = f.readline()
        if line:
            user, ip = parse_line(line.strip())
            if user and ip:
                stats['parsed'] += 1
                with pending_lock:
                    pending_entries.append({'user': user, 'ip': ip})
        else:
            # Check for log rotation
            try:
                current_inode = os.stat(LOG_PATH).st_ino
                if current_inode != inode:
                    print("[*] Log rotated, reopening...")
                    f.close()
                    f = open(LOG_PATH, 'r')
                    inode = current_inode
            except FileNotFoundError:
                print("[!] Log file disappeared, waiting...")
                f.close()
                while not os.path.exists(LOG_PATH):
                    time.sleep(1)
                f = open(LOG_PATH, 'r')
                inode = os.stat(LOG_PATH).st_ino
            
            # Periodic stats
            if time.time() - last_report > 60:
                print(f"[STATS] Parsed: {stats['parsed']}, Sent: {stats['sent']}, Errors: {stats['errors']}")
                last_report = time.time()
            
            time.sleep(0.05)

# ============ IP BLOCKING ============

def block_ip(ip: str, duration: int = 300):
    """Block IP with iptables"""
    try:
        # Check if already blocked
        r = subprocess.run(['iptables', '-C', 'INPUT', '-s', ip, '-j', 'DROP'], 
                          capture_output=True)
        if r.returncode != 0:
            subprocess.run(['iptables', '-I', 'INPUT', '-s', ip, '-j', 'DROP'], check=True)
            print(f"[BLOCK] {ip} for {duration}s")
        
        with blocked_lock:
            blocked_ips[ip] = time.time() + duration
        return True
    except Exception as e:
        print(f"[!] Block error: {e}")
        return False

def unblock_ip(ip: str):
    """Unblock IP"""
    try:
        subprocess.run(['iptables', '-D', 'INPUT', '-s', ip, '-j', 'DROP'], capture_output=True)
        print(f"[UNBLOCK] {ip}")
    except:
        pass

def cleanup_loop():
    """Cleanup expired blocks"""
    while True:
        now = time.time()
        to_unblock = []
        
        with blocked_lock:
            for ip, expire in list(blocked_ips.items()):
                if now >= expire:
                    to_unblock.append(ip)
                    del blocked_ips[ip]
        
        for ip in to_unblock:
            unblock_ip(ip)
        
        time.sleep(5)

# ============ HTTP API ============

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass
    
    def do_POST(self):
        try:
            length = int(self.headers.get('Content-Length', 0))
            data = json.loads(self.rfile.read(length)) if length else {}
            
            if data.get('secret') != API_SECRET:
                self.send_response(403)
                self.end_headers()
                return
            
            if self.path == '/block':
                ip = data.get('ip')
                duration = data.get('duration', 300)
                ok = block_ip(ip, duration) if ip else False
                self.send_response(200 if ok else 400)
            
            elif self.path == '/unblock':
                ip = data.get('ip')
                if ip:
                    unblock_ip(ip)
                    with blocked_lock:
                        blocked_ips.pop(ip, None)
                self.send_response(200)
            
            elif self.path == '/clear':
                # Clear all iptables rules we added
                with blocked_lock:
                    for ip in list(blocked_ips.keys()):
                        unblock_ip(ip)
                    blocked_ips.clear()
                print("[*] Cleared all blocks")
                self.send_response(200)
            
            else:
                self.send_response(404)
            
            self.end_headers()
        except Exception as e:
            print(f"[!] API error: {e}")
            self.send_response(500)
            self.end_headers()
    
    def do_GET(self):
        if self.path == '/health':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({
                "node": NODE_NAME,
                "blocked": len(blocked_ips),
                "stats": stats
            }).encode())
        elif self.path == '/stats':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({
                "node": NODE_NAME,
                "blocked_ips": list(blocked_ips.keys()),
                "stats": stats
            }).encode())
        else:
            self.send_response(404)
            self.end_headers()

def run_api():
    server = HTTPServer(('0.0.0.0', API_PORT), Handler)
    print(f"[*] API listening on port {API_PORT}")
    server.serve_forever()

# ============ MAIN ============

def main():
    print("=" * 50)
    print(f"  Node Reporter: {NODE_NAME}")
    print("=" * 50)
    print(f"Server: {SERVER_URL}")
    print(f"Log: {LOG_PATH}")
    print(f"API Port: {API_PORT}")
    print(f"Batch: {BATCH_SIZE} entries / {BATCH_INTERVAL}s")
    print()
    
    # Start API server
    threading.Thread(target=run_api, daemon=True).start()
    
    # Start cleanup loop
    threading.Thread(target=cleanup_loop, daemon=True).start()
    
    # Start batch sender
    threading.Thread(target=batch_sender, daemon=True).start()
    
    # Tail log (main thread)
    tail_log()

if __name__ == '__main__':
    main()
