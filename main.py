"""Main entry point - runs log server, checker and admin panel together"""

import asyncio
import signal
import sys
import threading

# Start log capture FIRST before any imports that might print
from events_log import start_capture
start_capture()

from log_server import app as log_app
from web_admin import app as admin_app
from checker import ConnectionChecker
from database import init_db
from config import LOG_SERVER_HOST, LOG_SERVER_PORT

ADMIN_PORT = 8080


def run_log_server():
    """Run log server Flask in a separate thread"""
    log_app.run(host=LOG_SERVER_HOST, port=LOG_SERVER_PORT, threaded=True, use_reloader=False)


def run_admin_server():
    """Run admin panel Flask in a separate thread"""
    admin_app.run(host='0.0.0.0', port=ADMIN_PORT, threaded=True, use_reloader=False)


async def main():
    init_db()
    checker = ConnectionChecker()

    # Graceful shutdown
    def signal_handler(sig, frame):
        print("\n[SHUTDOWN] Shutting down...")
        checker.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Запускаем Flask серверы в отдельных потоках
    log_thread = threading.Thread(target=run_log_server, daemon=True)
    log_thread.start()
    
    admin_thread = threading.Thread(target=run_admin_server, daemon=True)
    admin_thread.start()

    print("[MAIN] VPN Connection Checker started")
    print(f"[MAIN] Log server: http://{LOG_SERVER_HOST}:{LOG_SERVER_PORT}")
    print(f"[MAIN] Admin panel: http://0.0.0.0:{ADMIN_PORT}")

    # Запускаем async checker
    await checker.start()


if __name__ == '__main__':
    asyncio.run(main())
