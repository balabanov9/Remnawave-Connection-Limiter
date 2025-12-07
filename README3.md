# Принудительный кик IP (IP Kick)

Опциональная функция для мгновенного разрыва соединений нарушителей через iptables.

## Проблема

Когда юзер блокируется через API Remnawave, его текущие соединения НЕ разрываются — Xray проверяет права только при новом подключении. Юзер продолжает пользоваться VPN пока сам не отключится.

## Решение

При обнаружении нарушения центральный сервер отправляет команду на **ВСЕ ноды** заблокировать IP нарушителя через iptables. Соединение мгновенно рвётся, и нарушитель не может переключиться на другую ноду.

```
                                            ┌─────────────────┐
                                       ┌───▶│  Node Finland   │
                                       │    │  iptables DROP  │
┌─────────────────┐                    │    └─────────────────┘
│  Central Server │                    │
│                 │── POST /block_ip ──┼───▶┌─────────────────┐
│  Нарушение!     │   на ВСЕ ноды      │    │  Node Poland    │
│  IPs: 1.2.3.4   │                    │    │  iptables DROP  │
│        5.6.7.8  │                    │    └─────────────────┘
└─────────────────┘                    │
                                       └───▶┌─────────────────┐
                                            │  Node Germany   │
                                            │  iptables DROP  │
                                            └─────────────────┘
```

**Логика:**
1. Юзер подключен с 2+ IP (нарушение лимита)
2. Центральный сервер отправляет команду блокировки на ВСЕ ноды
3. Все ноды добавляют правило iptables для этих IP
4. Соединения мгновенно рвутся на всех нодах
5. Через 2 минуты ноды автоматически удаляют правила

## Настройка

### 1. На центральном сервере (config.py)

```python
# Включить кик IP на нодах
KICK_IPS_ON_VIOLATION = True

# Порт API на нодах для приема команд
NODE_API_PORT = 5001

# Секретный ключ (придумай сложный!)
NODE_API_SECRET = "mySuperSecret123!@#"

# Список ВСЕХ нод
# Ключ = имя ноды (NODE_NAME на ноде)
# Значение = IP адрес ноды
NODES = {
    "Finland_XHTTP-yandex-xhttp-ads": "185.100.50.25",
    "Poland_XHTTP-yandex-xhttp-ads": "91.200.100.75",
    "Germany_XHTTP-yandex-xhttp-ads": "45.67.89.12",
}
```

### 2. На каждой ноде (node_reporter.py)

```python
# URL центрального сервера
LOG_SERVER_URL = "http://10.0.0.1:5000/log"

# Имя ноды (должно совпадать с ключом в NODES на сервере)
NODE_NAME = "Finland_XHTTP-yandex-xhttp-ads"

# Путь к логам Xray
XRAY_LOG_PATH = "/var/log/xray/access.log"

# Порт для приема команд блокировки
API_PORT = 5001

# Секретный ключ (должен совпадать с NODE_API_SECRET на сервере!)
API_SECRET = "mySuperSecret123!@#"
```

### 3. Открыть порт на нодах

На каждой ноде открой порт 5001 **только** для центрального сервера:

```bash
# Через iptables (замени IP_СЕРВЕРА на реальный IP)
iptables -A INPUT -p tcp --dport 5001 -s IP_СЕРВЕРА -j ACCEPT
iptables -A INPUT -p tcp --dport 5001 -j DROP

# Сохранить правила
iptables-save > /etc/iptables/rules.v4
```

Или через ufw:
```bash
ufw allow from IP_СЕРВЕРА to any port 5001
```

### 4. Перезапустить сервисы

```bash
# На центральном сервере
systemctl restart connection-limiter

# На каждой ноде
systemctl restart node-reporter
```

## Откуда взять имя ноды?

Из логов Xray. Пример лога:
```
2025/12/07 15:02:32 from 178.176.86.81:16708 accepted tcp:www.google.com:443 [Poland_XHTTP-yandex-xhttp-ads -> gateway] email: user_848055128
```

Имя ноды: `Poland_XHTTP-yandex-xhttp-ads` (в квадратных скобках, до `->`)

## Проверка работы

### 1. Проверить что API ноды работает

С центрального сервера:
```bash
curl http://IP_НОДЫ:5001/health
```
Ответ: `{"status": "ok"}`

### 2. Тестовая блокировка

```bash
curl -X POST http://IP_НОДЫ:5001/block_ip \
  -H "Content-Type: application/json" \
  -d '{"ip": "1.2.3.4", "duration": 60, "secret": "твой_секрет"}'
```

### 3. Проверить iptables на ноде

```bash
iptables -L INPUT -n | grep DROP
```

Увидишь:
```
DROP       all  --  1.2.3.4              0.0.0.0/0
```

### 4. Логи node_reporter

```bash
journalctl -u node-reporter -f
```

При блокировке:
```
[BLOCKED] IP 1.2.3.4 for 60s
```

Через 60 сек:
```
[UNBLOCKED] IP 1.2.3.4
```

### 5. Разблокировать вручную

```bash
# Через API
curl -X POST http://IP_НОДЫ:5001/unblock_ip \
  -H "Content-Type: application/json" \
  -d '{"ip": "1.2.3.4", "secret": "твой_секрет"}'

# Или напрямую на ноде
iptables -D INPUT -s 1.2.3.4 -j DROP
```

## Безопасность

⚠️ **Важно:**
- Используй сложный `NODE_API_SECRET`
- Открой порт 5001 **только** для IP центрального сервера
- Никогда не открывай порт 5001 для всего интернета!

## Отключение

Если не нужен кик — в `config.py`:
```python
KICK_IPS_ON_VIOLATION = False
```

Скрипт будет работать как раньше — только блокировка через API Remnawave без разрыва соединений.
