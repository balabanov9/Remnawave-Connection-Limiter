"""Web admin panel for configuration"""

import os
import json
from flask import Flask, render_template_string, request, redirect, jsonify

app = Flask(__name__)

CONFIG_PATH = "config.py"

# HTML шаблон
ADMIN_HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Connection Limiter - Admin</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #1a1a2e; 
            color: #eee; 
            min-height: 100vh;
            padding: 20px;
        }
        .container { max-width: 800px; margin: 0 auto; }
        h1 { 
            text-align: center; 
            margin-bottom: 30px; 
            color: #00d4ff;
        }
        .card {
            background: #16213e;
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 20px;
        }
        .card h2 {
            color: #00d4ff;
            margin-bottom: 15px;
            font-size: 18px;
        }
        .form-group {
            margin-bottom: 15px;
        }
        label {
            display: block;
            margin-bottom: 5px;
            color: #aaa;
            font-size: 14px;
        }
        input[type="text"], input[type="number"], input[type="password"], textarea {
            width: 100%;
            padding: 12px;
            border: 1px solid #333;
            border-radius: 8px;
            background: #0f0f23;
            color: #fff;
            font-size: 14px;
        }
        input:focus, textarea:focus {
            outline: none;
            border-color: #00d4ff;
        }
        textarea {
            min-height: 120px;
            font-family: monospace;
        }
        .btn {
            background: #00d4ff;
            color: #000;
            border: none;
            padding: 12px 30px;
            border-radius: 8px;
            cursor: pointer;
            font-size: 16px;
            font-weight: bold;
            width: 100%;
            margin-top: 10px;
        }
        .btn:hover { background: #00b8e6; }
        .btn-danger { background: #ff4757; color: #fff; }
        .btn-danger:hover { background: #ff3344; }
        .success { 
            background: #2ed573; 
            color: #000; 
            padding: 15px; 
            border-radius: 8px; 
            margin-bottom: 20px;
            text-align: center;
        }
        .error { 
            background: #ff4757; 
            color: #fff; 
            padding: 15px; 
            border-radius: 8px; 
            margin-bottom: 20px;
            text-align: center;
        }
        .hint {
            font-size: 12px;
            color: #666;
            margin-top: 5px;
        }
        .status {
            display: inline-block;
            padding: 5px 10px;
            border-radius: 5px;
            font-size: 12px;
        }
        .status-ok { background: #2ed573; color: #000; }
        .status-error { background: #ff4757; }
        .stats {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 15px;
            margin-bottom: 20px;
        }
        .stat-box {
            background: #0f0f23;
            padding: 15px;
            border-radius: 8px;
            text-align: center;
        }
        .stat-value {
            font-size: 24px;
            font-weight: bold;
            color: #00d4ff;
        }
        .stat-label {
            font-size: 12px;
            color: #666;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🔒 Connection Limiter</h1>
        
        {% if message %}
        <div class="{{ 'success' if success else 'error' }}">{{ message }}</div>
        {% endif %}
        
        <div class="stats">
            <div class="stat-box">
                <div class="stat-value">{{ stats.total_connections }}</div>
                <div class="stat-label">Connections</div>
            </div>
            <div class="stat-box">
                <div class="stat-value">{{ stats.active_users }}</div>
                <div class="stat-label">Active Users</div>
            </div>
            <div class="stat-box">
                <div class="stat-value">{{ config.CHECK_INTERVAL_SECONDS }}s</div>
                <div class="stat-label">Check Interval</div>
            </div>
        </div>
        
        <form method="POST" action="/save">
            <div class="card">
                <h2>🔑 Remnawave API</h2>
                <div class="form-group">
                    <label>API URL</label>
                    <input type="text" name="REMNAWAVE_API_URL" value="{{ config.REMNAWAVE_API_URL }}">
                    <div class="hint">URL панели без /api (например: http://localhost:3000)</div>
                </div>
                <div class="form-group">
                    <label>API Token</label>
                    <input type="password" name="REMNAWAVE_API_TOKEN" value="{{ config.REMNAWAVE_API_TOKEN }}">
                </div>
            </div>
            
            <div class="card">
                <h2>⏱️ Настройки проверки</h2>
                <div class="form-group">
                    <label>Интервал проверки (секунды)</label>
                    <input type="number" name="CHECK_INTERVAL_SECONDS" value="{{ config.CHECK_INTERVAL_SECONDS }}">
                </div>
                <div class="form-group">
                    <label>Окно времени для IP (секунды)</label>
                    <input type="number" name="IP_WINDOW_SECONDS" value="{{ config.IP_WINDOW_SECONDS }}">
                    <div class="hint">За какой период считать уникальные IP</div>
                </div>
                <div class="form-group">
                    <label>Длительность дропа (секунды)</label>
                    <input type="number" name="DROP_DURATION_SECONDS" value="{{ config.DROP_DURATION_SECONDS }}">
                </div>
            </div>
            
            <div class="card">
                <h2>📱 Telegram</h2>
                <div class="form-group">
                    <label>Bot Token</label>
                    <input type="password" name="TELEGRAM_BOT_TOKEN" value="{{ config.TELEGRAM_BOT_TOKEN }}">
                    <div class="hint">Получить у @BotFather</div>
                </div>
                <div class="form-group">
                    <label>Chat ID</label>
                    <input type="text" name="TELEGRAM_CHAT_ID" value="{{ config.TELEGRAM_CHAT_ID }}">
                    <div class="hint">Узнать через @getmyid_bot</div>
                </div>
            </div>
            
            <div class="card">
                <h2>🖥️ Ноды</h2>
                <div class="form-group">
                    <label>Node API Port</label>
                    <input type="number" name="NODE_API_PORT" value="{{ config.NODE_API_PORT }}">
                </div>
                <div class="form-group">
                    <label>Node API Secret</label>
                    <input type="password" name="NODE_API_SECRET" value="{{ config.NODE_API_SECRET }}">
                </div>
                <div class="form-group">
                    <label>Список нод (JSON)</label>
                    <textarea name="NODES">{{ config.NODES | tojson }}</textarea>
                    <div class="hint">Формат: {"node-name": "ip-address", ...}</div>
                </div>
            </div>
            
            <div class="card">
                <h2>🌐 Сервер логов</h2>
                <div class="form-group">
                    <label>Host</label>
                    <input type="text" name="LOG_SERVER_HOST" value="{{ config.LOG_SERVER_HOST }}">
                </div>
                <div class="form-group">
                    <label>Port</label>
                    <input type="number" name="LOG_SERVER_PORT" value="{{ config.LOG_SERVER_PORT }}">
                </div>
            </div>
            
            <button type="submit" class="btn">💾 Сохранить</button>
        </form>
        
        <div class="card" style="margin-top: 20px;">
            <h2>⚡ Действия</h2>
            <form method="POST" action="/restart" style="display: inline;">
                <button type="submit" class="btn" style="width: auto; margin-right: 10px;">🔄 Перезапустить сервис</button>
            </form>
            <form method="POST" action="/clear_db" style="display: inline;">
                <button type="submit" class="btn btn-danger" style="width: auto;">🗑️ Очистить БД</button>
            </form>
        </div>
    </div>
</body>
</html>
"""


def read_config():
    """Read current config values"""
    config = {}
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            content = f.read()
            exec(content, config)
    except Exception as e:
        print(f"Error reading config: {e}")
    
    # Defaults
    defaults = {
        'REMNAWAVE_API_URL': 'http://localhost:3000',
        'REMNAWAVE_API_TOKEN': '',
        'LOG_SERVER_HOST': '0.0.0.0',
        'LOG_SERVER_PORT': 5000,
        'CHECK_INTERVAL_SECONDS': 120,
        'IP_WINDOW_SECONDS': 120,
        'DROP_DURATION_SECONDS': 60,
        'DB_PATH': 'connections.db',
        'TELEGRAM_BOT_TOKEN': '',
        'TELEGRAM_CHAT_ID': '',
        'NODE_API_PORT': 5001,
        'NODE_API_SECRET': 'change_this_secret',
        'NODES': {},
    }
    
    for key, default in defaults.items():
        if key not in config:
            config[key] = default
    
    return config


def write_config(config):
    """Write config to file"""
    content = '''"""Configuration for VPN connection checker"""

# Remnawave API settings
REMNAWAVE_API_URL = {REMNAWAVE_API_URL!r}
REMNAWAVE_API_TOKEN = {REMNAWAVE_API_TOKEN!r}

# Log collection settings
LOG_SERVER_HOST = {LOG_SERVER_HOST!r}
LOG_SERVER_PORT = {LOG_SERVER_PORT}

# Check settings
CHECK_INTERVAL_SECONDS = {CHECK_INTERVAL_SECONDS}
IP_WINDOW_SECONDS = {IP_WINDOW_SECONDS}
DROP_DURATION_SECONDS = {DROP_DURATION_SECONDS}

# Database
DB_PATH = {DB_PATH!r}

# Telegram notifications
TELEGRAM_BOT_TOKEN = {TELEGRAM_BOT_TOKEN!r}
TELEGRAM_CHAT_ID = {TELEGRAM_CHAT_ID!r}

# Node API settings
NODE_API_PORT = {NODE_API_PORT}
NODE_API_SECRET = {NODE_API_SECRET!r}

# Список нод
NODES = {NODES!r}
'''.format(**config)
    
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        f.write(content)


def get_stats():
    """Get current statistics"""
    try:
        from database import get_db_stats, get_all_active_users
        stats = get_db_stats()
        stats['active_users'] = len(get_all_active_users())
        return stats
    except:
        return {'total_connections': 0, 'active_users': 0}


@app.route('/')
def index():
    config = read_config()
    stats = get_stats()
    return render_template_string(ADMIN_HTML, config=config, stats=stats, message=None, success=True)


@app.route('/save', methods=['POST'])
def save():
    try:
        config = read_config()
        
        # Update values
        config['REMNAWAVE_API_URL'] = request.form.get('REMNAWAVE_API_URL', '')
        config['REMNAWAVE_API_TOKEN'] = request.form.get('REMNAWAVE_API_TOKEN', '')
        config['LOG_SERVER_HOST'] = request.form.get('LOG_SERVER_HOST', '0.0.0.0')
        config['LOG_SERVER_PORT'] = int(request.form.get('LOG_SERVER_PORT', 5000))
        config['CHECK_INTERVAL_SECONDS'] = int(request.form.get('CHECK_INTERVAL_SECONDS', 120))
        config['IP_WINDOW_SECONDS'] = int(request.form.get('IP_WINDOW_SECONDS', 120))
        config['DROP_DURATION_SECONDS'] = int(request.form.get('DROP_DURATION_SECONDS', 60))
        config['TELEGRAM_BOT_TOKEN'] = request.form.get('TELEGRAM_BOT_TOKEN', '')
        config['TELEGRAM_CHAT_ID'] = request.form.get('TELEGRAM_CHAT_ID', '')
        config['NODE_API_PORT'] = int(request.form.get('NODE_API_PORT', 5001))
        config['NODE_API_SECRET'] = request.form.get('NODE_API_SECRET', '')
        
        # Parse NODES JSON
        nodes_str = request.form.get('NODES', '{}')
        try:
            config['NODES'] = json.loads(nodes_str)
        except:
            config['NODES'] = {}
        
        write_config(config)
        
        stats = get_stats()
        return render_template_string(ADMIN_HTML, config=config, stats=stats, 
                                     message="✅ Конфигурация сохранена! Перезапустите сервис для применения.", 
                                     success=True)
    except Exception as e:
        config = read_config()
        stats = get_stats()
        return render_template_string(ADMIN_HTML, config=config, stats=stats,
                                     message=f"❌ Ошибка: {e}", success=False)


@app.route('/restart', methods=['POST'])
def restart():
    import subprocess
    try:
        subprocess.run(['systemctl', 'restart', 'connection-limiter'], check=True)
        message = "✅ Сервис перезапущен"
        success = True
    except Exception as e:
        message = f"❌ Ошибка перезапуска: {e}"
        success = False
    
    config = read_config()
    stats = get_stats()
    return render_template_string(ADMIN_HTML, config=config, stats=stats, message=message, success=success)


@app.route('/clear_db', methods=['POST'])
def clear_db():
    try:
        config = read_config()
        db_path = config.get('DB_PATH', 'connections.db')
        if os.path.exists(db_path):
            os.remove(db_path)
        message = "✅ База данных очищена"
        success = True
    except Exception as e:
        message = f"❌ Ошибка: {e}"
        success = False
    
    config = read_config()
    stats = get_stats()
    return render_template_string(ADMIN_HTML, config=config, stats=stats, message=message, success=success)


def run_admin(host='0.0.0.0', port=8080):
    """Run admin panel"""
    print(f"[ADMIN] Starting admin panel on http://{host}:{port}")
    app.run(host=host, port=port, debug=False)


if __name__ == '__main__':
    run_admin()
