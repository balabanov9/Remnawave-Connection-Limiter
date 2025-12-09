"""Main entry point - runs async log server and admin panel"""

import asyncio
import signal
import sys
import logging
import threading

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stderr)]
)
logger = logging.getLogger(__name__)

from events_log import start_capture
start_capture()

from log_server import LogServer
from web_admin import app as admin_app
from database import init_db
from config import LOG_SERVER_PORT

ADMIN_PORT = 8080


def run_admin_server():
    """Run admin panel Flask in a separate thread"""
    import logging as flask_log
    flask_log.getLogger('werkzeug').setLevel(flask_log.WARNING)
    admin_app.run(host='0.0.0.0', port=ADMIN_PORT, threaded=True, use_reloader=False)


async def main():
    logger.info("=== Connection Limiter Starting ===")
    
    init_db()
    logger.info("Database initialized")
    
    # Start admin panel in thread
    admin_thread = threading.Thread(target=run_admin_server, daemon=True)
    admin_thread.start()
    logger.info(f"Admin panel: http://0.0.0.0:{ADMIN_PORT}")
    
    # Start async log server
    server = LogServer()
    await server.start()
    logger.info(f"Log server: http://0.0.0.0:{LOG_SERVER_PORT}")
    logger.info("Real-time violation detection ACTIVE")
    
    # Keep running
    while True:
        await asyncio.sleep(3600)


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutting down...")
