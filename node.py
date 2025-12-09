#!/usr/bin/env python3
"""
Connection Limiter Node Reporter
- Monitors Xray logs in real-time
- Reports connections to central server instantly
- Handles DROP commands via iptables
"""

import os
import re
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

SERVER_URL = os.getenv('SERVER_URL', 'http://localhost:5000/log')
NODE_NAME = os.getenv('NODE_NAME', 'node-1')
LOG_PATH = os.getenv('LOG_PATH', '/var/log/xray/access.log')
API_PORT = int(os.getenv('API_PORT', '5001'))
API_SECRET = os.getenv('API_SECRET', 'secret')

# ============ STATE ============

blocked_ips = {}  # ip -> expire_time
blocked_lock = threading.Lock()
session = requests.Session()

# ============ LOG PARSING ============

def parse_line(line: str):
    """Parse Xray log line -> (user, ip) or (None, None)"""
    ip_match = re.search(r'from (?:tcp:)?(\d+\.\d+\.\d+\.\d+):\d+', line)
    email_match = re.search(r'email:\s*(\S+)', line)
    if ip_match and email_match:
        return email_match.group(1), ip_match.group(1)
    return None, None

def report(user: str, ip: str):
    """Send connection to server"""
    try:
        session.post(SERVER_URL, json={"user": user, "ip": ip, "node": NODE_NAME}, timeout=2)
    except:
        pass

def tail_log():
    """Tail log file and report connections in real-time"""
    print(f"[*] Watching {LOG_PATH}")
    
    while not os.path.exists(LOG_PATH):
        print(f"[!] Waiting for {LOG_PATH}...")
        time.sleep(5)
    
    f = open(LOG_PATH, 'r')
    f.seek(0, 2)  # End of file
    inode = os.stat(LOG_PATH).st_ino
    
    while True:
        line = f.readline()
        if line:
            user, ip = parse_line(line.strip())
            if user and ip:
                report(user, ip)
        else:
            # Check rotation
            try:
                if os.stat(LOG_PATH).st_ino != inode:
                    print("[*] Log rotated")
                    f.close()
                    f = open(LOG_PATH, 'r')
                    inode = os.stat(LOG_PATH).st_ino
            except:
                pass
            time.sleep(0.05)  # 50ms poll

# ============ IP BLOCKING ============

def block_ip(ip: str, duration: int = 60):
    """Block IP with iptables"""
    try:
        # Check if already blocked
        r = subprocess.run(['iptables', '-C', 'INPUT', '-s', ip, '-j', 'DROP'], capture_output=True)
        if r.returncode != 0:
            subprocess.run(['iptables', '-I', 'INPUT', '-s', ip, '-j', 'DROP'], check=True)
            print(f"[+] Blocked {ip} for {duration}s")
        
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
        print(f"[-] Unblocked {ip}")
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
            data = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))))
            
            if data.get('secret') != API_SECRET:
                self.send_response(403)
                self.end_headers()
                return
            
            if self.path == '/block':
                ip = data.get('ip')
                duration = data.get('duration', 60)
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
                subprocess.run(['iptables', '-F', 'INPUT'], capture_output=True)
                with blocked_lock:
                    blocked_ips.clear()
                print("[*] Cleared all rules")
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
                "blocked": len(blocked_ips)
            }).encode())
        else:
            self.send_response(404)
            self.end_headers()

def run_api():
    server = HTTPServer(('0.0.0.0', API_PORT), Handler)
    print(f"[*] API on port {API_PORT}")
    server.serve_forever()

# ============ MAIN ============

def main():
    print(f"=== Node Reporter: {NODE_NAME} ===")
    print(f"Server: {SERVER_URL}")
    print(f"Log: {LOG_PATH}")
    
    # Start API
    threading.Thread(target=run_api, daemon=True).start()
    
    # Start cleanup
    threading.Thread(target=cleanup_loop, daemon=True).start()
    
    # Tail log (main thread)
    tail_log()

if __name__ == '__main__':
    main()
