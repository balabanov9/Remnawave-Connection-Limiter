"""Web admin panel for configuration with auth and node management"""

import os
import json
import hashlib
import secrets
import aiohttp
import asyncio
from functools import wraps
from flask import Flask, render_template_string, request, redirect, session, jsonify

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)

CONFIG_PATH = "config.py"
ADMIN_PASSWORD_FILE = ".admin_password"

def get_admin_password_hash():
    """Get or create admin password hash"""
    if os.path.exists(ADMIN_PASSWORD_FILE):
        with open(ADMIN_PASSWORD_FILE, 'r') as f:
            return f.read().strip()
    # Default password: admin
    default_hash = hashlib.sha256("admin".encode()).hexdigest()
    with open(ADMIN_PASSWORD_FILE, 'w') as f:
        f.write(default_hash)
    return default_hash

def set_admin_password(password):
    """Set new admin password"""
    password_hash = hashlib.sha256(password.encode()).hexdigest()
    with open(ADMIN_PASSWORD_FILE, 'w') as f:
        f.write(password_hash)

def check_password(password):
    """Check if password is correct"""
    password_hash = hashlib.sha256(password.encode()).hexdigest()
    return password_hash == get_admin_password_hash()

def login_required(f):
    """Decorator for protected routes"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect('/login')
        return f(*args, **kwargs)
    return decorated


# HTML Templates
LOGIN_HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Login - Connection Limiter</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #1a1a2e; color: #eee; min-height: 100vh;
            display: flex; align-items: center; justify-content: center;
        }
        .login-box {
            background: #16213e; padding: 40px; border-radius: 12px;
            width: 100%; max-width: 400px;
        }
        h1 { text-align: center; margin-bottom: 30px; color: #00d4ff; }
        input {
            width: 100%; padding: 12px; margin-bottom: 15px;
            border: 1px solid #333; border-radius: 8px;
            background: #0f0f23; color: #fff; font-size: 16px;
        }
        .btn {
            width: 100%; padding: 12px; background: #00d4ff; color: #000;
            border: none; border-radius: 8px; cursor: pointer; font-size: 16px; font-weight: bold;
        }
        .btn:hover { background: #00b8e6; }
        .error { background: #ff4757; padding: 10px; border-radius: 8px; margin-bottom: 15px; text-align: center; }
    </style>
</head>
<body>
    <div class="login-box">
        <h1>🔒 Connection Limiter</h1>
        {% if error %}<div class="error">{{ error }}</div>{% endif %}
        <form method="POST">
            <input type="password" name="password" placeholder="Пароль" autofocus>
            <button type="submit" class="btn">Войти</button>
        </form>
        <p style="text-align: center; margin-top: 15px; color: #666; font-size: 12px;">
            Пароль по умолчанию: admin
        </p>
    </div>
</body>
</html>
"""


ADMIN_HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Admin - Connection Limiter</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #1a1a2e; color: #eee; min-height: 100vh; padding: 20px;
        }
        .container { max-width: 1200px; margin: 0 auto; }
        .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
        h1 { color: #00d4ff; }
        .logout { color: #ff4757; text-decoration: none; }
        .tabs { display: flex; gap: 10px; margin-bottom: 20px; }
        .tab { padding: 10px 20px; background: #16213e; border-radius: 8px; cursor: pointer; text-decoration: none; color: #aaa; }
        .tab.active { background: #00d4ff; color: #000; }
        .card { background: #16213e; border-radius: 12px; padding: 20px; margin-bottom: 20px; }
        .card h2 { color: #00d4ff; margin-bottom: 15px; font-size: 18px; }
        .form-group { margin-bottom: 15px; }
        label { display: block; margin-bottom: 5px; color: #aaa; font-size: 14px; }
        input, textarea, select { 
            width: 100%; padding: 12px; border: 1px solid #333; border-radius: 8px;
            background: #0f0f23; color: #fff; font-size: 14px;
        }
        input:focus, textarea:focus { outline: none; border-color: #00d4ff; }
        .btn { 
            background: #00d4ff; color: #000; border: none; padding: 12px 20px;
            border-radius: 8px; cursor: pointer; font-size: 14px; font-weight: bold;
        }
        .btn:hover { background: #00b8e6; }
        .btn-danger { background: #ff4757; color: #fff; }
        .btn-sm { padding: 8px 15px; font-size: 12px; }
        .success { background: #2ed573; color: #000; padding: 15px; border-radius: 8px; margin-bottom: 20px; }
        .error { background: #ff4757; color: #fff; padding: 15px; border-radius: 8px; margin-bottom: 20px; }
        .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 15px; margin-bottom: 20px; }
        .stat-box { background: #0f0f23; padding: 15px; border-radius: 8px; text-align: center; }
        .stat-value { font-size: 24px; font-weight: bold; color: #00d4ff; }
        .stat-label { font-size: 12px; color: #666; }
        .status { display: inline-block; padding: 5px 10px; border-radius: 5px; font-size: 12px; }
        .status-ok { background: #2ed573; color: #000; }
        .status-error { background: #ff4757; }
        .status-warn { background: #ffa502; color: #000; }
        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 12px; text-align: left; border-bottom: 1px solid #333; }
        th { color: #aaa; font-weight: normal; }
        .hint { font-size: 12px; color: #666; margin-top: 5px; }
        .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
        @media (max-width: 768px) { .grid-2 { grid-template-columns: 1fr; } }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🔒 Connection Limiter</h1>
            <a href="/logout" class="logout">Выйти</a>
        </div>
        
        {% if message %}
        <div class="{{ 'success' if success else 'error' }}">{{ message }}</div>
        {% endif %}
        
        <div class="tabs">
            <a href="/" class="tab {{ 'active' if tab == 'dashboard' }}">📊 Dashboard</a>
            <a href="/nodes" class="tab {{ 'active' if tab == 'nodes' }}">🖥️ Ноды</a>
            <a href="/settings" class="tab {{ 'active' if tab == 'settings' }}">⚙️ Настройки</a>
        </div>
        
        {{ content | safe }}
    </div>
</body>
</html>
"""


DASHBOARD_CONTENT = """
<div class="stats">
    <div class="stat-box">
        <div class="stat-value">{{ stats.total_connections }}</div>
        <div class="stat-label">Соединений в БД</div>
    </div>
    <div class="stat-box">
        <div class="stat-value">{{ stats.active_users }}</div>
        <div class="stat-label">Активных юзеров</div>
    </div>
    <div class="stat-box">
        <div class="stat-value">{{ nodes | length }}</div>
        <div class="stat-label">Нод</div>
    </div>
    <div class="stat-box">
        <div class="stat-value">{{ config.CHECK_INTERVAL_SECONDS }}s</div>
        <div class="stat-label">Интервал проверки</div>
    </div>
</div>

<div class="grid-2">
    <div class="card">
        <h2>📱 Telegram Bot</h2>
        {% if telegram_status.configured %}
            {% if telegram_status.ok %}
                <p><span class="status status-ok">✓ Подключен</span></p>
                <p style="margin-top: 10px; color: #aaa;">Bot: @{{ telegram_status.username }}</p>
            {% else %}
                <p><span class="status status-error">✗ Ошибка</span></p>
                <p style="margin-top: 10px; color: #ff4757;">{{ telegram_status.error }}</p>
            {% endif %}
        {% else %}
            <p><span class="status status-warn">⚠ Не настроен</span></p>
            <p style="margin-top: 10px; color: #aaa;">Укажите токен и Chat ID в настройках</p>
        {% endif %}
        <form method="POST" action="/test_telegram" style="margin-top: 15px;">
            <button type="submit" class="btn btn-sm" {% if not telegram_status.ok %}disabled{% endif %}>
                📤 Тест сообщения
            </button>
        </form>
    </div>
    
    <div class="card">
        <h2>🔑 Remnawave API</h2>
        {% if api_status.ok %}
            <p><span class="status status-ok">✓ Подключен</span></p>
        {% else %}
            <p><span class="status status-error">✗ Ошибка</span></p>
            <p style="margin-top: 10px; color: #ff4757;">{{ api_status.error }}</p>
        {% endif %}
    </div>
</div>

<div class="card">
    <h2>🖥️ Статус нод</h2>
    {% if nodes %}
    <table>
        <tr><th>Имя</th><th>IP</th><th>Соединений</th><th>Статус</th></tr>
        {% for name, info in nodes.items() %}
        <tr>
            <td>{{ name }}</td>
            <td>{{ info.ip }}</td>
            <td>{{ info.connections }}</td>
            <td>
                {% if info.status == 'online' %}
                    <span class="status status-ok">Online</span>
                {% else %}
                    <span class="status status-error">Offline</span>
                {% endif %}
            </td>
        </tr>
        {% endfor %}
    </table>
    {% else %}
    <p style="color: #666;">Ноды не настроены. <a href="/nodes" style="color: #00d4ff;">Добавить</a></p>
    {% endif %}
</div>

<div class="card">
    <h2>⚡ Быстрые действия</h2>
    <form method="POST" action="/restart" style="display: inline;">
        <button type="submit" class="btn btn-sm">🔄 Перезапустить сервис</button>
    </form>
    <form method="POST" action="/clear_db" style="display: inline; margin-left: 10px;">
        <button type="submit" class="btn btn-sm btn-danger">🗑️ Очистить БД</button>
    </form>
</div>
"""


NODES_CONTENT = """
<div class="card">
    <h2>➕ Добавить ноду</h2>
    <form method="POST" action="/nodes/add">
        <div class="grid-2">
            <div class="form-group">
                <label>Имя ноды</label>
                <input type="text" name="name" placeholder="finland-1" required>
            </div>
            <div class="form-group">
                <label>IP адрес</label>
                <input type="text" name="ip" placeholder="1.2.3.4" required>
            </div>
        </div>
        <button type="submit" class="btn">Добавить</button>
    </form>
</div>

<div class="card">
    <h2>🖥️ Список нод</h2>
    {% if nodes %}
    <table>
        <tr><th>Имя</th><th>IP</th><th>Порт API</th><th>Соединений</th><th>Статус</th><th>Действия</th></tr>
        {% for name, info in nodes.items() %}
        <tr>
            <td>{{ name }}</td>
            <td>{{ info.ip }}</td>
            <td>{{ config.NODE_API_PORT }}</td>
            <td>{{ info.connections }}</td>
            <td>
                {% if info.status == 'online' %}
                    <span class="status status-ok">Online</span>
                {% else %}
                    <span class="status status-error">Offline</span>
                {% endif %}
            </td>
            <td>
                <form method="POST" action="/nodes/delete" style="display: inline;">
                    <input type="hidden" name="name" value="{{ name }}">
                    <button type="submit" class="btn btn-sm btn-danger">Удалить</button>
                </form>
                <form method="POST" action="/nodes/clear_iptables" style="display: inline; margin-left: 5px;">
                    <input type="hidden" name="name" value="{{ name }}">
                    <button type="submit" class="btn btn-sm">Очистить iptables</button>
                </form>
            </td>
        </tr>
        {% endfor %}
    </table>
    {% else %}
    <p style="color: #666;">Нет добавленных нод</p>
    {% endif %}
</div>

<div class="card">
    <h2>🔧 Настройки API нод</h2>
    <form method="POST" action="/nodes/settings">
        <div class="grid-2">
            <div class="form-group">
                <label>Порт API на нодах</label>
                <input type="number" name="NODE_API_PORT" value="{{ config.NODE_API_PORT }}">
            </div>
            <div class="form-group">
                <label>Секретный ключ</label>
                <input type="password" name="NODE_API_SECRET" value="{{ config.NODE_API_SECRET }}">
            </div>
        </div>
        <button type="submit" class="btn">Сохранить</button>
    </form>
</div>
"""


SETTINGS_CONTENT = """
<form method="POST" action="/settings/save">
    <div class="grid-2">
        <div class="card">
            <h2>🔑 Remnawave API</h2>
            <div class="form-group">
                <label>API URL</label>
                <input type="text" name="REMNAWAVE_API_URL" value="{{ config.REMNAWAVE_API_URL }}">
                <div class="hint">URL панели без /api</div>
            </div>
            <div class="form-group">
                <label>API Token</label>
                <input type="password" name="REMNAWAVE_API_TOKEN" value="{{ config.REMNAWAVE_API_TOKEN }}">
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
    </div>
    
    <div class="card">
        <h2>⏱️ Настройки проверки</h2>
        <div class="grid-2">
            <div class="form-group">
                <label>Интервал проверки (секунды)</label>
                <input type="number" name="CHECK_INTERVAL_SECONDS" value="{{ config.CHECK_INTERVAL_SECONDS }}">
            </div>
            <div class="form-group">
                <label>Окно времени для IP (секунды)</label>
                <input type="number" name="IP_WINDOW_SECONDS" value="{{ config.IP_WINDOW_SECONDS }}">
            </div>
            <div class="form-group">
                <label>Длительность дропа (секунды)</label>
                <input type="number" name="DROP_DURATION_SECONDS" value="{{ config.DROP_DURATION_SECONDS }}">
            </div>
            <div class="form-group">
                <label>Порт сервера логов</label>
                <input type="number" name="LOG_SERVER_PORT" value="{{ config.LOG_SERVER_PORT }}">
            </div>
        </div>
    </div>
    
    <div class="card">
        <h2>🔐 Сменить пароль админки</h2>
        <div class="grid-2">
            <div class="form-group">
                <label>Новый пароль</label>
                <input type="password" name="new_password" placeholder="Оставьте пустым чтобы не менять">
            </div>
            <div class="form-group">
                <label>Подтверждение</label>
                <input type="password" name="confirm_password">
            </div>
        </div>
    </div>
    
    <button type="submit" class="btn" style="width: 100%;">💾 Сохранить все настройки</button>
</form>
"""


def read_config():
    """Read current config values"""
    config = {}
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            exec(f.read(), config)
    except Exception as e:
        print(f"Error reading config: {e}")
    
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

# Nodes
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


def get_node_connections():
    """Get connection count per node"""
    try:
        import sqlite3
        config = read_config()
        conn = sqlite3.connect(config.get('DB_PATH', 'connections.db'))
        cursor = conn.cursor()
        cursor.execute('SELECT node_name, COUNT(*) FROM connections GROUP BY node_name')
        result = {row[0]: row[1] for row in cursor.fetchall()}
        conn.close()
        return result
    except:
        return {}


def check_node_status(ip, port):
    """Check if node API is reachable"""
    import socket
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        result = sock.connect_ex((ip, port))
        sock.close()
        return result == 0
    except:
        return False


def get_nodes_with_status():
    """Get nodes with their status and connection count"""
    config = read_config()
    nodes = config.get('NODES', {})
    node_connections = get_node_connections()
    port = config.get('NODE_API_PORT', 5001)
    
    result = {}
    for name, ip in nodes.items():
        result[name] = {
            'ip': ip,
            'connections': node_connections.get(name, 0),
            'status': 'online' if check_node_status(ip, port) else 'offline'
        }
    return result


def check_telegram_status():
    """Check Telegram bot status"""
    config = read_config()
    token = config.get('TELEGRAM_BOT_TOKEN', '')
    chat_id = config.get('TELEGRAM_CHAT_ID', '')
    
    if not token or not chat_id:
        return {'configured': False, 'ok': False}
    
    try:
        import requests
        resp = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            if data.get('ok'):
                return {
                    'configured': True,
                    'ok': True,
                    'username': data['result'].get('username', 'unknown')
                }
        return {'configured': True, 'ok': False, 'error': 'Invalid token'}
    except Exception as e:
        return {'configured': True, 'ok': False, 'error': str(e)}


def check_api_status():
    """Check Remnawave API status"""
    config = read_config()
    url = config.get('REMNAWAVE_API_URL', '')
    token = config.get('REMNAWAVE_API_TOKEN', '')
    
    if not url or not token:
        return {'ok': False, 'error': 'Not configured'}
    
    try:
        import requests
        resp = requests.get(
            f"{url}/api/system/stats",
            headers={"Authorization": f"Bearer {token}"},
            timeout=5
        )
        if resp.status_code == 200:
            return {'ok': True}
        elif resp.status_code == 401:
            return {'ok': False, 'error': 'Invalid token (401)'}
        else:
            return {'ok': False, 'error': f'HTTP {resp.status_code}'}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


# Routes
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        password = request.form.get('password', '')
        if check_password(password):
            session['logged_in'] = True
            return redirect('/')
        return render_template_string(LOGIN_HTML, error="Неверный пароль")
    return render_template_string(LOGIN_HTML, error=None)


@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect('/login')


@app.route('/')
@login_required
def dashboard():
    config = read_config()
    stats = get_stats()
    nodes = get_nodes_with_status()
    telegram_status = check_telegram_status()
    api_status = check_api_status()
    
    from flask import render_template_string as rts
    content = rts(DASHBOARD_CONTENT, 
                  config=config, stats=stats, nodes=nodes,
                  telegram_status=telegram_status, api_status=api_status)
    
    return render_template_string(ADMIN_HTML, content=content, tab='dashboard',
                                  message=request.args.get('message'),
                                  success=request.args.get('success', 'true') == 'true')


@app.route('/nodes')
@login_required
def nodes_page():
    config = read_config()
    nodes = get_nodes_with_status()
    
    from flask import render_template_string as rts
    content = rts(NODES_CONTENT, config=config, nodes=nodes)
    
    return render_template_string(ADMIN_HTML, content=content, tab='nodes',
                                  message=request.args.get('message'),
                                  success=request.args.get('success', 'true') == 'true')


@app.route('/settings')
@login_required
def settings_page():
    config = read_config()
    
    from flask import render_template_string as rts
    content = rts(SETTINGS_CONTENT, config=config)
    
    return render_template_string(ADMIN_HTML, content=content, tab='settings',
                                  message=request.args.get('message'),
                                  success=request.args.get('success', 'true') == 'true')


@app.route('/nodes/add', methods=['POST'])
@login_required
def add_node():
    name = request.form.get('name', '').strip()
    ip = request.form.get('ip', '').strip()
    
    if not name or not ip:
        return redirect('/nodes?message=Укажите имя и IP&success=false')
    
    config = read_config()
    nodes = config.get('NODES', {})
    nodes[name] = ip
    config['NODES'] = nodes
    write_config(config)
    
    return redirect(f'/nodes?message=Нода {name} добавлена&success=true')


@app.route('/nodes/delete', methods=['POST'])
@login_required
def delete_node():
    name = request.form.get('name', '')
    
    config = read_config()
    nodes = config.get('NODES', {})
    if name in nodes:
        del nodes[name]
        config['NODES'] = nodes
        write_config(config)
    
    return redirect(f'/nodes?message=Нода {name} удалена&success=true')


@app.route('/nodes/settings', methods=['POST'])
@login_required
def save_node_settings():
    config = read_config()
    config['NODE_API_PORT'] = int(request.form.get('NODE_API_PORT', 5001))
    config['NODE_API_SECRET'] = request.form.get('NODE_API_SECRET', '')
    write_config(config)
    return redirect('/nodes?message=Настройки сохранены&success=true')


@app.route('/nodes/clear_iptables', methods=['POST'])
@login_required
def clear_node_iptables():
    name = request.form.get('name', '')
    config = read_config()
    nodes = config.get('NODES', {})
    
    if name not in nodes:
        return redirect('/nodes?message=Нода не найдена&success=false')
    
    ip = nodes[name]
    port = config.get('NODE_API_PORT', 5001)
    secret = config.get('NODE_API_SECRET', '')
    
    try:
        import requests
        resp = requests.post(
            f"http://{ip}:{port}/clear_iptables",
            json={"secret": secret},
            timeout=10
        )
        if resp.status_code == 200:
            return redirect(f'/nodes?message=iptables на {name} очищен&success=true')
        else:
            return redirect(f'/nodes?message=Ошибка: HTTP {resp.status_code}&success=false')
    except Exception as e:
        return redirect(f'/nodes?message=Ошибка: {e}&success=false')


@app.route('/settings/save', methods=['POST'])
@login_required
def save_settings():
    config = read_config()
    
    config['REMNAWAVE_API_URL'] = request.form.get('REMNAWAVE_API_URL', '')
    config['REMNAWAVE_API_TOKEN'] = request.form.get('REMNAWAVE_API_TOKEN', '')
    config['TELEGRAM_BOT_TOKEN'] = request.form.get('TELEGRAM_BOT_TOKEN', '')
    config['TELEGRAM_CHAT_ID'] = request.form.get('TELEGRAM_CHAT_ID', '')
    config['CHECK_INTERVAL_SECONDS'] = int(request.form.get('CHECK_INTERVAL_SECONDS', 120))
    config['IP_WINDOW_SECONDS'] = int(request.form.get('IP_WINDOW_SECONDS', 120))
    config['DROP_DURATION_SECONDS'] = int(request.form.get('DROP_DURATION_SECONDS', 60))
    config['LOG_SERVER_PORT'] = int(request.form.get('LOG_SERVER_PORT', 5000))
    
    # Password change
    new_password = request.form.get('new_password', '')
    confirm_password = request.form.get('confirm_password', '')
    
    if new_password:
        if new_password != confirm_password:
            return redirect('/settings?message=Пароли не совпадают&success=false')
        set_admin_password(new_password)
    
    write_config(config)
    return redirect('/settings?message=Настройки сохранены&success=true')


@app.route('/test_telegram', methods=['POST'])
@login_required
def test_telegram():
    config = read_config()
    token = config.get('TELEGRAM_BOT_TOKEN', '')
    chat_id = config.get('TELEGRAM_CHAT_ID', '')
    
    if not token or not chat_id:
        return redirect('/?message=Telegram не настроен&success=false')
    
    try:
        import requests
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": "✅ Тестовое сообщение от Connection Limiter",
                "parse_mode": "HTML"
            },
            timeout=10
        )
        if resp.status_code == 200:
            return redirect('/?message=Сообщение отправлено&success=true')
        else:
            data = resp.json()
            error = data.get('description', f'HTTP {resp.status_code}')
            return redirect(f'/?message=Ошибка: {error}&success=false')
    except Exception as e:
        return redirect(f'/?message=Ошибка: {e}&success=false')


@app.route('/restart', methods=['POST'])
@login_required
def restart():
    import subprocess
    try:
        subprocess.run(['systemctl', 'restart', 'connection-limiter'], check=True)
        return redirect('/?message=Сервис перезапущен&success=true')
    except Exception as e:
        return redirect(f'/?message=Ошибка: {e}&success=false')


@app.route('/clear_db', methods=['POST'])
@login_required
def clear_db():
    config = read_config()
    db_path = config.get('DB_PATH', 'connections.db')
    try:
        if os.path.exists(db_path):
            os.remove(db_path)
        return redirect('/?message=База данных очищена&success=true')
    except Exception as e:
        return redirect(f'/?message=Ошибка: {e}&success=false')


def run_admin(host='0.0.0.0', port=8080):
    """Run admin panel"""
    print(f"[ADMIN] Starting admin panel on http://{host}:{port}")
    app.run(host=host, port=port, debug=False)


if __name__ == '__main__':
    run_admin()
