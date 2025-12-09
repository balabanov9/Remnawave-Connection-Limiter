# Connection Limiter

Ограничение одновременных VPN подключений на основе HWID лимита из Remnawave.

**Скорость реакции: < 1 секунды**

## Установка

### Сервер (центральный)

```bash
bash <(curl -s https://raw.githubusercontent.com/balabanov9/Remnawave-Connection-Limiter/main/install_server.sh)
```

### Нода (VPN сервер)

```bash
bash <(curl -s https://raw.githubusercontent.com/balabanov9/Remnawave-Connection-Limiter/main/install_node.sh)
```

### Обновление

```bash
bash <(curl -s https://raw.githubusercontent.com/balabanov9/Remnawave-Connection-Limiter/main/update.sh)
```

## Как работает

1. Нода читает логи Xray в реальном времени
2. Каждое подключение мгновенно отправляется на сервер
3. Сервер проверяет лимит через Remnawave API
4. При превышении - команда DROP на все ноды
5. Уведомление в Telegram

## Файлы

- `server.py` - центральный сервер
- `node.py` - репортер для ноды
- `.env` - конфигурация (не в git)

## Команды

```bash
# Сервер
systemctl status connection-limiter
journalctl -u connection-limiter -f

# Нода
systemctl status node-reporter
journalctl -u node-reporter -f
```

## Требования

- Python 3.8+
- Xray с `loglevel: warning`
- Remnawave с настроенным hwidDeviceLimit
