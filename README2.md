# Дополнительная информация

## Скрипты автозагрузки

Если скрипты уже настроены и работают, но нужно только добавить в автозагрузку systemd:

### autostart_server.sh

Запускать на центральном сервере из папки с проектом:
```bash
cd /root/Remnawave-Connection-Limiter
bash autostart_server.sh
```

Создаёт сервис `connection-limiter`, добавляет в автозагрузку и запускает.

### autostart_node.sh

Запускать на VPN ноде из папки где лежит `node_reporter.py`:
```bash
cd /opt/node-reporter
bash autostart_node.sh
```

Создаёт сервис `node-reporter`, добавляет в автозагрузку и запускает.

---

## Разница между скриптами

| Скрипт | Что делает |
|--------|-----------|
| `install_server.sh` | Полная установка: зависимости + systemd + автозагрузка + запуск |
| `install_node.sh` | Полная установка: копирует файлы + зависимости + systemd |
| `autostart_server.sh` | Только systemd сервис + автозагрузка + запуск |
| `autostart_node.sh` | Только systemd сервис + автозагрузка + запуск |

---

## Команды управления

### Центральный сервер
```bash
systemctl status connection-limiter   # статус
systemctl restart connection-limiter  # перезапуск
systemctl stop connection-limiter     # остановка
systemctl start connection-limiter    # запуск
journalctl -u connection-limiter -f   # логи
```

### VPN нода
```bash
systemctl status node-reporter   # статус
systemctl restart node-reporter  # перезапуск
systemctl stop node-reporter     # остановка
systemctl start node-reporter    # запуск
journalctl -u node-reporter -f   # логи
```

---

## Обновление с GitHub

На сервере/ноде:
```bash
cd /root/Remnawave-Connection-Limiter
git pull
systemctl restart connection-limiter  # или node-reporter
```
