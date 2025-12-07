#!/bin/bash

# Установка Connection Limiter на центральный сервер
# Запускать от root: bash install_server.sh

set -e

echo "=== Installing Remnawave Connection Limiter ==="

# Проверяем что запущено от root
if [ "$EUID" -ne 0 ]; then
    echo "Please run as root"
    exit 1
fi

# Определяем путь к скрипту
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON_PATH=$(which python3)

echo "Script directory: $SCRIPT_DIR"
echo "Python path: $PYTHON_PATH"

# Устанавливаем зависимости
echo "Installing dependencies..."
pip3 install -r "$SCRIPT_DIR/requirements.txt"

# Создаем systemd сервис
echo "Creating systemd service..."
cat > /etc/systemd/system/connection-limiter.service << EOF
[Unit]
Description=Remnawave Connection Limiter
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$SCRIPT_DIR
ExecStart=$PYTHON_PATH main.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# Перезагружаем systemd
systemctl daemon-reload

# Включаем и запускаем сервис
systemctl enable connection-limiter
systemctl start connection-limiter

echo ""
echo "=== Installation complete ==="
echo ""
echo "Commands:"
echo "  systemctl status connection-limiter  - check status"
echo "  systemctl restart connection-limiter - restart"
echo "  journalctl -u connection-limiter -f  - view logs"
echo ""
echo "Don't forget to edit config.py with your settings!"
