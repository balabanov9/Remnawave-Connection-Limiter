#!/bin/bash
# Connection Limiter - Update Script

set -e

if [[ -d "/opt/connection-limiter" ]]; then
    DIR="/opt/connection-limiter"
    SVC="connection-limiter"
elif [[ -d "/opt/node-reporter" ]]; then
    DIR="/opt/node-reporter"
    SVC="node-reporter"
else
    echo "No installation found!"
    exit 1
fi

echo "Updating $SVC..."

cd "$DIR"
cp .env .env.bak 2>/dev/null || true
git fetch && git reset --hard origin/main
mv .env.bak .env 2>/dev/null || true

systemctl restart $SVC
echo "Done! Check: systemctl status $SVC"
