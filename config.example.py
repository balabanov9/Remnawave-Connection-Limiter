"""Configuration for VPN connection checker"""

# Remnawave API settings
REMNAWAVE_API_URL = "http://localhost:3000"  # URL панели Remnawave (без /api)
REMNAWAVE_API_TOKEN = "your_api_token_here"  # Bearer токен из панели

# Log collection settings
LOG_SERVER_HOST = "0.0.0.0"  # Слушать на всех интерфейсах
LOG_SERVER_PORT = 5000  # Порт для приема логов от нод

# Check settings
CHECK_INTERVAL_SECONDS = 30  # Как часто проверять подключения
IP_WINDOW_SECONDS = 60  # Окно времени для подсчета уникальных IP
BLOCK_DURATION_SECONDS = 120  # На сколько блокировать (2 минуты)

# Database
DB_PATH = "connections.db"  # SQLite база для хранения подключений

# Telegram notifications (optional)
TELEGRAM_BOT_TOKEN = ""  # Токен бота от @BotFather (оставь пустым чтобы отключить)
TELEGRAM_CHAT_ID = ""  # Твой Telegram ID (узнать через @getmyid_bot)
