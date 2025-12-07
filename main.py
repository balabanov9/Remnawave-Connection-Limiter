"""Main entry point - runs log server and checker together"""

import asyncio
import signal
import sys
import threading
from log_server import app
from checker import ConnectionChecker
from database import init_db
from config import LOG_SERVER_HOST, LOG_SERVER_PORT


def run_flask():
    """Run Flask in a separate thread"""
    app.run(host=LOG_SERVER_HOST, port=LOG_SERVER_PORT, threaded=True, use_reloader=False)


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

    # Запускаем Flask в отдельном потоке
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    print("[MAIN] VPN Connection Checker started")
    print(f"[MAIN] Log server: http://{LOG_SERVER_HOST}:{LOG_SERVER_PORT}")

    # Запускаем async checker
    await checker.start()


if __name__ == '__main__':
    asyncio.run(main())
