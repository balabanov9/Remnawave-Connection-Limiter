#!/bin/bash
# Connection Limiter - Server Installer

set -e
INSTALL_DIR="/opt/connection-limiter"
REPO="https://github.com/balabanov9/Remnawave-Connection-Limiter.git"

echo "========================================"
echo "  Connection Limiter - Server Setup"
echo "========================================"
echo ""

[[ $EUID -ne 0 ]] && echo "Run as root!" && exit 1

# Get settings
read -p "Remnawave API URL: " API_URL
read -p "Remnawave API Token: " API_TOKEN
read -p "Telegram Bot Token (Enter to skip): " TG_TOKEN
read -p "Telegram Chat ID (Enter to skip): " TG_CHAT
read -p "Node API Secret: " NODE_SECRET

echo ""
echo "Enter nodes (name:ip), empty to finish:"
NODES=""
while read -p "Node: " node && [[ -n "$node" ]]; do
    NODES="${NODES:+$NODES,}$node"
done

echo ""
echo "Installing..."

# Install deps
apt-get update -qq && apt-get install -y -qq python3 python3-venv python3-pip git >/dev/null

# Clone/update
if [[ -d "$INSTALL_DIR" ]]; then
    cd "$INSTALL_DIR" && git fetch && git reset --hard origin/main
else
    git clone "$REPO" "$INSTALL_DIR"
fi

# Create venv and install deps
python3 -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install -q aiohttp requests

# Create .env
cat > "$INSTALL_DIR/.env" << EOF
REMNAWAVE_API_URL=$API_URL
REMNAWAVE_API_TOKEN=$API_TOKEN
TELEGRAM_BOT_TOKEN=$TG_TOKEN
TELEGRAM_CHAT_ID=$TG_CHAT
NODE_API_SECRET=$NODE_SECRET
NODES=$NODES
DROP_DURATION_SECONDS=60
IP_WINDOW_SECONDS=60
EOF

# Create service
cat > /etc/systemd/system/connection-limiter.service << EOF
[Unit]
Description=Connection Limiter
After=network.target

[Service]
Type=simple
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/venv/bin/python server.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable connection-limiter
systemctl restart connection-limiter

IP=$(hostname -I | awk '{print $1}')
echo ""
echo "========================================"
echo "  Done!"
echo "========================================"
echo "Admin: http://$IP:8080 (password: admin)"
echo "Logs:  http://$IP:5000"
echo ""
echo "Commands:"
echo "  systemctl status connection-limiter"
echo "  journalctl -u connection-limiter -f"
echo ""
