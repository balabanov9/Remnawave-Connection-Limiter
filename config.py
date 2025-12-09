"""Configuration - loads from .env file or environment variables"""

import os
from pathlib import Path

# Load .env file if exists
env_file = Path(__file__).parent / '.env'
if env_file.exists():
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ.setdefault(key.strip(), value.strip())

def get_env(key: str, default: str = '') -> str:
    return os.environ.get(key, default)

def get_env_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, default))
    except:
        return default

def parse_nodes(nodes_str: str) -> dict:
    """Parse nodes from string format: name1:ip1,name2:ip2"""
    if not nodes_str:
        return {}
    result = {}
    for item in nodes_str.split(','):
        item = item.strip()
        if ':' in item:
            name, ip = item.split(':', 1)
            result[name.strip()] = ip.strip()
    return result

# Remnawave API settings
REMNAWAVE_API_URL = get_env('REMNAWAVE_API_URL', 'http://localhost:3000')
REMNAWAVE_API_TOKEN = get_env('REMNAWAVE_API_TOKEN', '')

# Log collection settings
LOG_SERVER_HOST = '0.0.0.0'
LOG_SERVER_PORT = get_env_int('LOG_SERVER_PORT', 5000)

# Check settings
CHECK_INTERVAL_SECONDS = get_env_int('CHECK_INTERVAL_SECONDS', 10)
IP_WINDOW_SECONDS = get_env_int('IP_WINDOW_SECONDS', 60)
DROP_DURATION_SECONDS = get_env_int('DROP_DURATION_SECONDS', 60)

# Database
DB_PATH = get_env('DB_PATH', 'connections.db')

# Telegram notifications
TELEGRAM_BOT_TOKEN = get_env('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = get_env('TELEGRAM_CHAT_ID', '')

# Node API settings
NODE_API_PORT = get_env_int('NODE_API_PORT', 5001)
NODE_API_SECRET = get_env('NODE_API_SECRET', 'change_this_secret')

# Nodes
NODES = parse_nodes(get_env('NODES', ''))
