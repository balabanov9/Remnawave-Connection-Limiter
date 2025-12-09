#!/bin/bash
# Connection Limiter - Node Installer

set -e
INSTALL_DIR="/opt/node-reporter"
REPO="https://github.com/balabanov9/Remnawave-Connection-Limiter.git"

echo "========================================"
echo "  Connection Limiter - Node Setup"
echo "========================================"
echo ""

[[ $EUID -ne 0 ]] && echo "Run as root!" && exit 1

# Get settings
read -p "Central Server IP: " SERVER_IP
read -p "Node Name: " NODE_NAME
read -p "API Secret (same as server): " API_SECRET
read -p "Xray Log Path [/var/log/xray/access.log]: " LOG_PATH
LOG_PATH=${LOG_PATH:-/var/log/xray/access.log}

echo ""
echo "Installing..."

# Install deps
apt-get update -qq && apt-get install -y -qq python3 python3-pip git iptables >/dev/null

# Clone/update
if [[ -d "$INSTALL_DIR" ]]; then
    cd "$INSTALL_DIR" && git fetch && git reset --hard origin/main
else
    git clone "$REPO" "$INSTALL_DIR"
fi

# Install Python deps
pip3 install -q requests

# Create .env
cat > "$INSTALL_DIR/.env" << EOF
SERVER_URL=http://$SERVER_IP:5000/log
NODE_NAME=$NODE_NAME
LOG_PATH=$LOG_PATH
API_PORT=5001
API_SECRET=$API_SECRET
EOF

# Create service
cat > /etc/systemd/system/node-reporter.service << EOF
[Unit]
Description=Node Reporter
After=network.target

[Service]
Type=simple
WorkingDirectory=$INSTALL_DIR
ExecStart=/usr/bin/python3 node.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable node-reporter
systemctl restart node-reporter

echo ""
echo "========================================"
echo "  Done!"
echo "========================================"
echo "Node: $NODE_NAME"
echo "Server: http://$SERVER_IP:5000"
echo ""
echo "Commands:"
echo "  systemctl status node-reporter"
echo "  journalctl -u node-reporter -f"
echo ""
