#!/bin/bash

# Добавляет node_reporter в автозагрузку
# Запускать от root из папки где лежит node_reporter.py

set -e

if [ "$EUID" -ne 0 ]; then
    echo "Run as root"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON_PATH=$(which python3)

cat > /etc/systemd/system/node-reporter.service << EOF
[Unit]
Description=VPN Node Reporter
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$SCRIPT_DIR
ExecStart=$PYTHON_PATH node_reporter.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable node-reporter
systemctl start node-reporter

echo "Done! Service: node-reporter"
echo "  systemctl status node-reporter"
echo "  journalctl -u node-reporter -f"
