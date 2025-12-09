# Обновление v4: Поддержка IP:Port и новый формат логов

## Что нового

### 1. Поддержка нового формата логов Xray

Теперь скрипт корректно парсит логи с коротким email:
```
2025/12/09 16:24:37.137839 from 80.115.201.91:11488 accepted tcp:www.google.com:443 [REALITY_GRPC_INBOUND -> SHADOWSOCKS_OUTBOUND] email: 810
```

А также логи с `tcp:` перед IP:
```
2025/12/09 16:24:38.324777 from tcp:94.25.235.25:64341 accepted udp:213.156.152.244:5055 [REALITY_GRPC_INBOUND -> SHADOWSOCKS_OUTBOUND] email: 4393
```

### 2. Точечный бан по IP:Port

Раньше при нарушении банился весь IP адрес. Теперь можно банить конкретное соединение по IP:port.

**Преимущества:**
- Если несколько пользователей за одним NAT - заблокируется только нарушитель
- Более точный контроль соединений
- Работает если у клиента фиксированный source port

### 3. Новый параметр конфигурации

```python
KICK_BY_IP_PORT = True  # True = банить IP:port (точечно), False = банить весь IP
```

## Обновление

### На центральном сервере:

```bash
cd /root/Remnawave-Connection-Limiter
git pull

# Добавь новый параметр в config.py:
# KICK_BY_IP_PORT = True

# Удали старую базу (добавлена новая колонка port)
rm connections.db

# Перезапусти сервис
sudo systemctl restart connection-limiter
```

### На каждой ноде:

```bash
cd /opt/node-reporter  # или где у тебя лежит
git pull
sudo systemctl restart node-reporter
```

## Как работает бан по IP:Port

1. Нода отправляет на сервер: `{user_email: "810", ip_address: "80.115.201.91", port: "11488"}`
2. При нарушении сервер отправляет на ноды команду блокировки с портом
3. На ноде выполняется: `iptables -A INPUT -s 80.115.201.91 -p tcp --sport 11488 -j DROP`
4. Блокируется только это конкретное соединение

## Требования к Xray

Убедись что в конфиге Xray стоит `loglevel: warning` - только в этом режиме логируются подключения с email.

## Изменённые файлы

- `node_reporter.py` - парсинг порта, бан по IP:port
- `database.py` - хранение порта в БД
- `log_server.py` - приём порта от нод
- `checker.py` - отправка команд бана с портом
- `config.py` - новый параметр KICK_BY_IP_PORT
