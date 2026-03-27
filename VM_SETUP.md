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
sudo mkdir -p /opt/maxrk
sudo chown $USER:$USER /opt/maxrk
```

Copy these files into `/opt/maxrk`:

- `app.py`
- `.env`
- `.env.example`
- `requirements.txt`
- `maxrk-bridge.service`

Recommended `.env` values for this instance:

```env
INSTANCE_NAME=maxrk
STATE_FILE=/opt/maxrk/state.json
```

## 3. Create virtualenv and install deps

```bash
cd /opt/maxrk
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
```

## 4. Quick manual run

```bash
cd /opt/maxrk
./venv/bin/python app.py
```

Expected startup log:

```text
[maxrk] Telegram -> MAX bridge started
```

Stop with `Ctrl+C`.

## 5. Configure systemd

Replace `YOUR_LINUX_USER` in `maxrk-bridge.service` with your actual VM user.

Install service:

```bash
sudo cp /opt/maxrk/maxrk-bridge.service /etc/systemd/system/maxrk-bridge.service
sudo systemctl daemon-reload
sudo systemctl enable maxrk-bridge
sudo systemctl start maxrk-bridge
```

## 6. Check logs

```bash
sudo systemctl status maxrk-bridge
sudo journalctl -u maxrk-bridge -f
```

## 7. Common checks

- Telegram bot must be admin in the source channel.
- MAX bot must have access to the target chat/dialog.
- `TARGET_MAX_CHAT` in `.env` can be a link, username, or numeric `chat_id`.
- Use a unique `STATE_FILE` for each deployed bridge instance.
- VM must allow outbound HTTPS to `api.telegram.org` and `platform-api.max.ru`.
