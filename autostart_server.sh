#!/bin/bash

# Добавляет центральный сервер в автозагрузку
# Запускать от root из папки с проектом

set -e

if [ "$EUID" -ne 0 ]; then
    echo "Run as root"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON_PATH=$(which python3)

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

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable connection-limiter
systemctl start connection-limiter

echo "Done! Service: connection-limiter"
echo "  systemctl status connection-limiter"
echo "  journalctl -u connection-limiter -f"
