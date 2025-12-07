# Принудительный кик IP (IP Kick)

Опциональная функция для мгновенного разрыва соединений нарушителей через iptables.

## Проблема

Когда юзер блокируется через API Remnawave, его текущие соединения НЕ разрываются — Xray проверяет права только при новом подключении. Юзер продолжает пользоваться VPN пока сам не отключится.

## Решение

При обнаружении нарушения центральный сервер отправляет команду на ноды заблокировать IP нарушителя через iptables. Соединение мгновенно рвётся.

```
┌─────────────────┐                         ┌─────────────────┐
│  Central Server │                         │    VPN Node     │
│                 │                         │                 │
│  checker.py     │── POST /block_ip ──────▶│  node_reporter  │
│                 │   {"ip": "1.2.3.4",     │        │        │
│                 │    "duration": 120,     │        ▼        │
│                 │    "secret": "xxx"}     │   iptables      │
│                 │                         │   -A INPUT      │
│                 │                         │   -s 1.2.3.4    │
│                 │                         │   -j DROP       │
│                 │                         │                 │
│                 │                         │  (через 2 мин)  │
│                 │                         │   iptables      │
│                 │                         │   -D INPUT ...  │
└─────────────────┘                         └─────────────────┘
```

## Настройка

### 1. На центральном сервере (config.py)

```python
# Включить кик
KICK_IPS_ON_VIOLATION = True

# Порт API на нодах
NODE_API_PORT = 5001

# Секретный ключ (придумай свой!)
NODE_API_SECRET = "my_super_secret_key_123"

# Список нод {имя: ip}
# Имя должно совпадать с NODE_NAME на ноде
NODES = {
    "finland-1": "185.123.45.67",
    "poland-1": "91.234.56.78",
    "germany-1": "45.67.89.12",
}
```

### 2. На каждой ноде (node_reporter.py)

```python
# Порт для приема команд (должен совпадать с NODE_API_PORT)
API_PORT = 5001

# Секретный ключ (должен совпадать с NODE_API_SECRET)
API_SECRET = "my_super_secret_key_123"

# Имя ноды (должно совпадать с ключом в NODES)
NODE_NAME = "finland-1"
```

### 3. Открыть порт на нодах

На каждой ноде открой порт 5001 для центрального сервера:

```bash
# Разрешить только с IP центрального сервера
iptables -A INPUT -p tcp --dport 5001 -s IP_ЦЕНТРАЛЬНОГО_СЕРВЕРА -j ACCEPT
iptables -A INPUT -p tcp --dport 5001 -j DROP
```

Или через ufw:
```bash
ufw allow from IP_ЦЕНТРАЛЬНОГО_СЕРВЕРА to any port 5001
```

### 4. Перезапустить сервисы

```bash
# На центральном сервере
systemctl restart connection-limiter

# На каждой ноде
systemctl restart node-reporter
```

## API ноды

Node reporter теперь слушает на порту 5001:

| Метод | Путь | Описание |
|-------|------|----------|
| POST | `/block_ip` | Заблокировать IP |
| POST | `/unblock_ip` | Разблокировать IP |
| GET | `/health` | Health check |

**POST /block_ip:**
```json
{
    "ip": "1.2.3.4",
    "duration": 120,
    "secret": "my_super_secret_key_123"
}
```

## Безопасность

- Используй сложный `NODE_API_SECRET`
- Открой порт 5001 только для IP центрального сервера
- Не открывай порт 5001 для всего интернета!

## Проверка работы

На ноде посмотри логи:
```bash
journalctl -u node-reporter -f
```

При нарушении увидишь:
```
[BLOCKED] IP 178.176.86.81 for 120s
[UNBLOCKED] IP 178.176.86.81
```

Проверить iptables:
```bash
iptables -L INPUT -n | grep DROP
```

## Отключение

Если не нужен кик — просто оставь в config.py:
```python
KICK_IPS_ON_VIOLATION = False
```

Скрипт будет работать как раньше — только блокировка через API Remnawave.
