#!/bin/bash

# Установка Node Reporter на VPN ноду
# Запускать от root: bash install_node.sh

set -e

echo "=== Installing Node Reporter ==="

# Проверяем что запущено от root
if [ "$EUID" -ne 0 ]; then
    echo "Please run as root"
    exit 1
fi

# Определяем путь
INSTALL_DIR="/opt/node-reporter"
PYTHON_PATH=$(which python3)

echo "Install directory: $INSTALL_DIR"
echo "Python path: $PYTHON_PATH"

# Создаем директорию
mkdir -p "$INSTALL_DIR"

# Копируем скрипт
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cp "$SCRIPT_DIR/node_reporter.py" "$INSTALL_DIR/"

# Устанавливаем requests
echo "Installing dependencies..."
pip3 install requests

# Создаем systemd сервис
echo "Creating systemd service..."
cat > /etc/systemd/system/node-reporter.service << EOF
[Unit]
Description=VPN Node Reporter
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$INSTALL_DIR
ExecStart=$PYTHON_PATH node_reporter.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# Перезагружаем systemd
systemctl daemon-reload

# Включаем сервис (но не запускаем - сначала нужно настроить)
systemctl enable node-reporter

echo ""
echo "=== Installation complete ==="
echo ""
echo "IMPORTANT: Edit settings before starting!"
echo "  nano $INSTALL_DIR/node_reporter.py"
echo ""
echo "Set these values:"
echo "  LOG_SERVER_URL = \"http://your-server:5000/log\""
echo "  NODE_NAME = \"your-node-name\""
echo "  XRAY_LOG_PATH = \"/var/log/xray/access.log\""
echo ""
echo "Then start:"
echo "  systemctl start node-reporter"
echo ""
echo "Commands:"
echo "  systemctl status node-reporter  - check status"
echo "  systemctl restart node-reporter - restart"
echo "  journalctl -u node-reporter -f  - view logs"
