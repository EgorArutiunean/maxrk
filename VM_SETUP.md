# VM setup

Assumption: Ubuntu or Debian VM with outbound HTTPS access.

## 1. Install system packages

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv
```

## 2. Copy project to VM

Create target directory:

```bash
sudo mkdir -p /opt/tg-max-bridge
sudo chown $USER:$USER /opt/tg-max-bridge
```

Copy these files into `/opt/tg-max-bridge`:

- `app.py`
- `.env`
- `requirements.txt`
- `tg-max-bridge.service`

## 3. Create virtualenv and install deps

```bash
cd /opt/tg-max-bridge
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
```

## 4. Quick manual run

```bash
cd /opt/tg-max-bridge
./venv/bin/python app.py
```

Expected startup log:

```text
Мост Telegram -> MAX запущен
```

Stop with `Ctrl+C`.

## 5. Configure systemd

Replace `YOUR_LINUX_USER` in `tg-max-bridge.service` with your actual VM user.

Install service:

```bash
sudo cp /opt/tg-max-bridge/tg-max-bridge.service /etc/systemd/system/tg-max-bridge.service
sudo systemctl daemon-reload
sudo systemctl enable tg-max-bridge
sudo systemctl start tg-max-bridge
```

## 6. Check logs

```bash
sudo systemctl status tg-max-bridge
sudo journalctl -u tg-max-bridge -f
```

## 7. Common checks

- Telegram bot must be admin in the source channel.
- MAX bot must have access to the target chat/dialog.
- `TARGET_MAX_CHAT` in `.env` can be a link, username, or numeric `chat_id`.
- VM must allow outbound HTTPS to `api.telegram.org` and `platform-api.max.ru`.
