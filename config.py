"""Configuration for VPN connection checker"""

# Remnawave API settings
REMNAWAVE_API_URL = "http://localhost:3000"  # URL панели Remnawave (без /api)
REMNAWAVE_API_TOKEN = "your_api_token_here"  # Bearer токен из панели

# Log collection settings
LOG_SERVER_HOST = "0.0.0.0"
LOG_SERVER_PORT = 5000

# Check settings
CHECK_INTERVAL_SECONDS = 15  # Как часто проверять подключения (секунды)
IP_WINDOW_SECONDS = 60  # Окно времени для подсчета уникальных IP
BLOCK_DURATION_SECONDS = 120  # На сколько блокировать (2 минуты)
VIOLATION_CONFIRM_COUNT = 2  # Сколько проверок подряд должно быть нарушение (защита от ложных срабатываний)

# Database
DB_PATH = "connections.db"

# Telegram notifications
TELEGRAM_BOT_TOKEN = ""  # Токен бота от @BotFather
TELEGRAM_CHAT_ID = ""  # Твой Telegram ID (узнать через @getmyid_bot)

# IP Kick settings (принудительный разрыв соединений)
KICK_IPS_ON_VIOLATION = False  # Включить кик IP через iptables на нодах
KICK_BY_IP_PORT = True  # True = банить IP:port (точечно), False = банить весь IP
NODE_API_PORT = 5001  # Порт API на нодах для приема команд блокировки
NODE_API_SECRET = "change_this_secret"  # Секретный ключ (должен совпадать на нодах)

# Список нод {имя_ноды: ip_адрес} - заполни если включил KICK_IPS_ON_VIOLATION
NODES = {
    # "finland-1": "1.2.3.4",
    # "poland-1": "5.6.7.8",
}
