#!/usr/bin/env python3
"""
Connection Limiter - Node Agent
- Sends log file to central server periodically
- Handles DROP commands via iptables
"""

import os
import time
import json
import subprocess
import threading
from pathlib import Path
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
SEND_INTERVAL = int(os.getenv('SEND_INTERVAL', '5'))  # seconds
MAX_LINES = int(os.getenv('MAX_LINES', '1000'))  # max lines to send

# ============ STATE ============

blocked_ips = {}  # ip -> expire_time
blocked_lock = threading.Lock()
session = requests.Session()
stats = {'sent': 0, 'errors': 0, 'last_send': 0}
last_position = 0  # Track file position

# ============ LOG SENDING ============

def read_new_lines():
    """Read new lines from log file"""
    global last_position
    
    if not os.path.exists(LOG_PATH):
        return []
    
    try:
        with open(LOG_PATH, 'r') as f:
            # Check if file was rotated (smaller than last position)
            f.seek(0, 2)  # End of file
            current_size = f.tell()
            
            if current_size < last_position:
                # File was rotated, start from beginning
                print(f"[*] Log rotated, reading from start")
                last_position = 0
            
            # Read from last position
            f.seek(last_position)
            lines = f.readlines()
            last_position = f.tell()
            
            # Limit lines
            if len(lines) > MAX_LINES:
                lines = lines[-MAX_LINES:]
            
            return [l.strip() for l in lines if l.strip()]
    except Exception as e:
        print(f"[!] Read error: {e}")
        return []

def send_logs():
    """Send log lines to server"""
    lines = read_new_lines()
    
    if not lines:
        return 0
    
    try:
        url = SERVER_URL.rstrip('/') + '/log_upload'
        resp = session.post(url, json={
            'node': NODE_NAME,
            'lines': lines,
            'secret': API_SECRET
        }, timeout=10)
        
        if resp.status_code == 200:
            data = resp.json()
            processed = data.get('processed', 0)
            stats['sent'] += processed
            stats['last_send'] = time.time()
            if processed > 0:
                print(f"[OK] Sent {len(lines)} lines, {processed} processed")
            return processed
        else:
            stats['errors'] += 1
            print(f"[!] Server returned {resp.status_code}")
    except Exception as e:
        stats['errors'] += 1
        print(f"[!] Send error: {e}")
    
    return 0

def sender_loop():
    """Background thread that sends logs periodically"""
    print(f"[*] Sender started, interval: {SEND_INTERVAL}s")
    
    while True:
        time.sleep(SEND_INTERVAL)
        send_logs()

# ============ IP BLOCKING ============

def block_ip(ip: str, duration: int = 600):
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
                duration = data.get('duration', 600)
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
                "stats": stats,
                "log_path": LOG_PATH,
                "log_exists": os.path.exists(LOG_PATH)
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
    print(f"  Node Agent: {NODE_NAME}")
    print("=" * 50)
    print(f"Server: {SERVER_URL}")
    print(f"Log: {LOG_PATH}")
    print(f"API Port: {API_PORT}")
    print(f"Send Interval: {SEND_INTERVAL}s")
    print()
    
    # Check log file
    if os.path.exists(LOG_PATH):
        print(f"[OK] Log file found")
    else:
        print(f"[!] Log file not found, will wait...")
    
    # Start API server
    threading.Thread(target=run_api, daemon=True).start()
    
    # Start cleanup loop
    threading.Thread(target=cleanup_loop, daemon=True).start()
    
    # Start sender loop
    threading.Thread(target=sender_loop, daemon=True).start()
    
    # Keep main thread alive
    print("[*] Node agent running...")
    while True:
        time.sleep(60)
        print(f"[STATS] Sent: {stats['sent']}, Errors: {stats['errors']}, Blocked: {len(blocked_ips)}")

if __name__ == '__main__':
    main()
