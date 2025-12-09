"""Node reporter - real-time log monitoring with .env config"""

import requests
import re
import time
import os
import json
import subprocess
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

# Load .env file
def load_env():
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ.setdefault(key.strip(), value.strip())

load_env()

# Configuration from .env
LOG_SERVER_URL = os.environ.get('LOG_SERVER_URL', 'http://localhost:5000/log')
NODE_NAME = os.environ.get('NODE_NAME', 'node-1')
XRAY_LOG_PATH = os.environ.get('XRAY_LOG_PATH', '/var/log/xray/access.log')
API_PORT = int(os.environ.get('API_PORT', '5001'))
API_SECRET = os.environ.get('API_SECRET', 'change_this_secret')

blocked_ips = {}
blocked_ips_lock = threading.Lock()
session = requests.Session()


def parse_log_line(line):
    """Parse Xray log line, returns (username, ip)"""
    ip_match = re.search(r'from (?:tcp:)?(\d+\.\d+\.\d+\.\d+):\d+', line)
    email_match = re.search(r'email:\s*(\S+)', line)
    if ip_match and email_match:
        return email_match.group(1), ip_match.group(1)
    return None, None


def report_connection(username, ip):
    """Send connection to central server immediately"""
    try:
        session.post(
            LOG_SERVER_URL,
            json={"user_email": username, "ip_address": ip, "node_name": NODE_NAME},
            timeout=2
        )
    except:
        pass


def tail_log_file():
    """Tail log file and report connections in real-time"""
    print(f"[START] Watching {XRAY_LOG_PATH}")
    
    while not os.path.exists(XRAY_LOG_PATH):
        print(f"[WAIT] Log file not found, waiting...")
        time.sleep(5)
    
    f = open(XRAY_LOG_PATH, 'r')
    f.seek(0, 2)  # Go to end
    current_inode = os.stat(XRAY_LOG_PATH).st_ino
    
    while True:
        line = f.readline()
        if line:
            username, ip = parse_log_line(line.strip())
            if username and ip:
                report_connection(username, ip)
        else:
            # Check for log rotation
            try:
                if os.stat(XRAY_LOG_PATH).st_ino != current_inode:
                    print("[INFO] Log rotated, reopening")
                    f.close()
                    f = open(XRAY_LOG_PATH, 'r')
                    current_inode = os.stat(XRAY_LOG_PATH).st_ino
            except:
                pass
            time.sleep(0.1)


def block_ip(ip, duration=60):
    """Block IP using iptables"""
    try:
        check = subprocess.run(
            ['iptables', '-C', 'INPUT', '-s', ip, '-j', 'DROP'],
            capture_output=True
        )
        if check.returncode != 0:
            subprocess.run(
                ['iptables', '-I', 'INPUT', '-s', ip, '-j', 'DROP'],
                check=True
            )
            print(f"[BLOCKED] {ip} for {duration}s")
        
        with blocked_ips_lock:
            blocked_ips[ip] = time.time() + duration
        return True
    except Exception as e:
        print(f"[ERROR] Block {ip}: {e}")
        return False


def unblock_ip(ip):
    """Unblock IP"""
    try:
        subprocess.run(
            ['iptables', '-D', 'INPUT', '-s', ip, '-j', 'DROP'],
            capture_output=True
        )
        print(f"[UNBLOCKED] {ip}")
    except:
        pass


def cleanup_loop():
    """Periodic cleanup of expired blocks"""
    while True:
        now = time.time()
        to_unblock = []
        
        with blocked_ips_lock:
            for ip, expire_time in list(blocked_ips.items()):
                if now >= expire_time:
                    to_unblock.append(ip)
                    del blocked_ips[ip]
        
        for ip in to_unblock:
            unblock_ip(ip)
        
        time.sleep(10)


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
            
            if self.path == '/block_ip':
                ip = data.get('ip')
                duration = data.get('duration', 60)
                if ip:
                    ok = block_ip(ip, duration)
                    self.send_response(200 if ok else 500)
                else:
                    self.send_response(400)
            
            elif self.path == '/unblock_ip':
                ip = data.get('ip')
                if ip:
                    unblock_ip(ip)
                    with blocked_ips_lock:
                        blocked_ips.pop(ip, None)
                self.send_response(200)
            
            elif self.path == '/clear_iptables':
                subprocess.run(['iptables', '-F', 'INPUT'], capture_output=True)
                with blocked_ips_lock:
                    blocked_ips.clear()
                print("[CLEARED] All iptables rules")
                self.send_response(200)
            
            else:
                self.send_response(404)
            
            self.end_headers()
        
        except Exception as e:
            print(f"[ERROR] API: {e}")
            self.send_response(500)
            self.end_headers()
    
    def do_GET(self):
        if self.path == '/health':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({
                "status": "ok",
                "node": NODE_NAME,
                "blocked_count": len(blocked_ips)
            }).encode())
        elif self.path == '/blocked':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            with blocked_ips_lock:
                self.wfile.write(json.dumps(list(blocked_ips.keys())).encode())
        else:
            self.send_response(404)
            self.end_headers()


def run_api():
    """Run HTTP API server"""
    server = HTTPServer(('0.0.0.0', API_PORT), Handler)
    print(f"[API] Listening on port {API_PORT}")
    server.serve_forever()


def main():
    print(f"[START] Node Reporter - {NODE_NAME}")
    print(f"[CONFIG] Server: {LOG_SERVER_URL}")
    print(f"[CONFIG] Log: {XRAY_LOG_PATH}")
    print(f"[CONFIG] API port: {API_PORT}")
    
    # Start API server
    api_thread = threading.Thread(target=run_api, daemon=True)
    api_thread.start()
    
    # Start cleanup loop
    cleanup_thread = threading.Thread(target=cleanup_loop, daemon=True)
    cleanup_thread.start()
    
    # Start tailing log (main thread)
    tail_log_file()


if __name__ == '__main__':
    main()
