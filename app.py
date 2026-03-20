import json
import logging
import mimetypes
import os
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv

load_dotenv()

# =========================
# CONFIG
# =========================
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
MAX_BOT_TOKEN = os.environ["MAX_BOT_TOKEN"]

SOURCE_TG_CHAT_ID = int(os.environ["SOURCE_TG_CHAT_ID"])
TARGET_MAX_CHAT = os.environ.get("TARGET_MAX_CHAT") or os.environ["TARGET_MAX_CHAT_ID"]

POLL_TIMEOUT = int(os.getenv("POLL_TIMEOUT", "30"))
STATE_FILE = Path(os.getenv("STATE_FILE", "state.json"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# Какие типы обновлений слушаем
# Для первого стабильного варианта: только новые посты канала
TG_ALLOWED_UPDATES = ["channel_post"]

TG_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
TG_FILE_API = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}"
MAX_API = "https://platform-api.max.ru"

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger("tg_to_max_bridge")

tg = requests.Session()
mx = requests.Session()
mx.headers.update({"Authorization": MAX_BOT_TOKEN})
_target_max_recipient: dict[str, int] | None = None


# =========================
# STATE
# =========================
def load_state() -> dict[str, Any]:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            log.warning("Не удалось прочитать state.json, начну с пустого состояния")
    return {"tg_offset": None}


def save_state(state: dict[str, Any]) -> None:
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# =========================
# TELEGRAM
# =========================
def tg_get_updates(offset: int | None) -> list[dict[str, Any]]:
    params = {
        "timeout": POLL_TIMEOUT,
        "allowed_updates": json.dumps(TG_ALLOWED_UPDATES),
    }
    if offset is not None:
        params["offset"] = offset

    resp = tg.get(
        f"{TG_API}/getUpdates",
        params=params,
        timeout=POLL_TIMEOUT + 10,
    )
    resp.raise_for_status()
    data = resp.json()

    if not data.get("ok"):
        raise RuntimeError(f"Telegram getUpdates failed: {data}")

    return data["result"]


def tg_get_file_info(file_id: str) -> dict[str, Any]:
    resp = tg.get(
        f"{TG_API}/getFile",
        params={"file_id": file_id},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()

    if not data.get("ok"):
        raise RuntimeError(f"Telegram getFile failed: {data}")

    return data["result"]


def tg_download_file(file_id: str) -> tuple[bytes, str, str | None]:
    info = tg_get_file_info(file_id)
    file_path = info["file_path"]
    filename = file_path.split("/")[-1]
    mime_type, _ = mimetypes.guess_type(filename)

    resp = tg.get(f"{TG_FILE_API}/{file_path}", timeout=180)
    resp.raise_for_status()

    return resp.content, filename, mime_type


# =========================
# MAX
# =========================
def max_iter_chats() -> list[dict[str, Any]]:
    chats: list[dict[str, Any]] = []
    marker: int | None = None

    while True:
        params: dict[str, Any] = {"count": 100}
        if marker is not None:
            params["marker"] = marker

        resp = mx.get(
            f"{MAX_API}/chats",
            params=params,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        chats.extend(data.get("chats", []))
        marker = data.get("marker")
        if marker is None:
            return chats


def normalize_max_target(value: str) -> str:
    raw = value.strip()
    if not raw:
        raise RuntimeError("TARGET_MAX_CHAT пустой")

    if raw.lstrip("-").isdigit():
        return raw

    if raw.startswith("@"):
        return raw[1:].lower()

    if raw.startswith("http://") or raw.startswith("https://"):
        parsed = urlparse(raw)
        path = parsed.path.strip("/")
        if not path:
            raise RuntimeError(f"Некорректная ссылка MAX: {raw}")
        return path.lower()

    return raw.strip("/").lower()


def max_resolve_recipient(target: str) -> dict[str, int]:
    normalized_target = normalize_max_target(target)

    if normalized_target.lstrip("-").isdigit():
        return {"chat_id": int(normalized_target)}

    for chat in max_iter_chats():
        link = (chat.get("link") or "").strip()
        title = (chat.get("title") or "").strip().lower()
        dialog_user = chat.get("dialog_with_user") or {}
        dialog_username = (dialog_user.get("username") or "").strip().lower()

        candidates = {
            title,
            dialog_username,
            normalize_max_target(link) if link else "",
        }

        if normalized_target in candidates:
            return {"chat_id": int(chat["chat_id"])}

    raise RuntimeError(
        "Не удалось определить chat_id для TARGET_MAX_CHAT. "
        "Укажи числовой chat_id или сначала открой диалог/добавь бота в нужный чат."
    )


def get_target_max_recipient() -> dict[str, int]:
    global _target_max_recipient

    if _target_max_recipient is None:
        _target_max_recipient = max_resolve_recipient(TARGET_MAX_CHAT)
        log.info("MAX получатель определён: %s", _target_max_recipient)

    return _target_max_recipient


def max_get_upload_slot(kind: str) -> dict[str, Any]:
    """
    kind: image | file | video | audio
    """
    resp = mx.post(
        f"{MAX_API}/uploads",
        params={"type": kind},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()

    if "url" not in data:
        raise RuntimeError(f"MAX /uploads did not return url: {data}")

    return data


def max_upload_file(
    kind: str,
    filename: str,
    blob: bytes,
    mime_type: str | None,
) -> dict[str, Any]:
    """
    Возвращает attachment вида:
    {
      "type": "image" | "file" | "video" | "audio",
      "payload": {...}
    }
    """
    slot = max_get_upload_slot(kind)
    upload_url = slot["url"]

    files = {
        "data": (filename, blob, mime_type or "application/octet-stream")
    }

    # По документации upload можно делать multipart/form-data
    # На всякий случай пробуем сначала с Authorization.
    resp = requests.post(
        upload_url,
        headers={"Authorization": MAX_BOT_TOKEN},
        files=files,
        timeout=300,
    )

    # Если CDN/endpoint не принимает Authorization, пробуем без него
    if resp.status_code in (400, 401, 403):
        resp = requests.post(
            upload_url,
            files=files,
            timeout=300,
        )

    resp.raise_for_status()

    # Для image/file token обычно приходит после загрузки.
    # Для video/audio токен может прийти либо из /uploads, либо из ответа загрузки.
    upload_result = resp.json()

    payload = None

    if "token" in upload_result:
        payload = upload_result
    elif "token" in slot:
        payload = {"token": slot["token"]}
    else:
        # Иногда API может вернуть уже готовый payload-объект
        payload = upload_result

    return {
        "type": kind,
        "payload": payload,
    }


def max_send_message(
    text: str | None,
    attachments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    recipient = get_target_max_recipient()
    body: dict[str, Any] = {}

    if text:
        body["text"] = text[:4000]

    if attachments:
        body["attachments"] = attachments

    if not body:
        body["text"] = "[Пустой пост]"

    # У Max после загрузки медиа может быть короткая задержка готовности вложения
    for attempt in range(6):
        resp = mx.post(
            f"{MAX_API}/messages",
            params=recipient,
            json=body,
            timeout=60,
        )

        if resp.ok:
            return resp.json()

        err_text = resp.text
        try:
            err_json = resp.json()
        except Exception:
            err_json = {"raw": err_text}

        err_code = err_json.get("code")

        if err_code == "attachment.not.ready":
            sleep_s = 1.5 * (attempt + 1)
            log.warning("Вложение MAX ещё не готово, повтор через %.1fс", sleep_s)
            time.sleep(sleep_s)
            continue

        raise RuntimeError(
            f"MAX send failed: status={resp.status_code}, body={err_json}"
        )

    raise RuntimeError("MAX attachment.not.ready after retries")


# =========================
# CONTENT EXTRACTION
# =========================
def get_post_text(post: dict[str, Any]) -> str:
    return (post.get("text") or post.get("caption") or "").strip()


def extract_attachments_from_post(post: dict[str, Any]) -> list[dict[str, Any]]:
    attachments: list[dict[str, Any]] = []

    # Фото
    if post.get("photo"):
        photo = post["photo"][-1]  # самое большое фото
        blob, filename, mime_type = tg_download_file(photo["file_id"])
        attachments.append(
            max_upload_file("image", filename or "photo.jpg", blob, mime_type)
        )

    # Документ
    if post.get("document"):
        doc = post["document"]
        blob, filename, mime_type = tg_download_file(doc["file_id"])
        attachments.append(
            max_upload_file(
                "file",
                doc.get("file_name") or filename or "document.bin",
                blob,
                doc.get("mime_type") or mime_type,
            )
        )

    # Видео
    if post.get("video"):
        video = post["video"]
        blob, filename, mime_type = tg_download_file(video["file_id"])
        attachments.append(
            max_upload_file(
                "video",
                filename or "video.mp4",
                blob,
                video.get("mime_type") or mime_type,
            )
        )

    # Аудио
    if post.get("audio"):
        audio = post["audio"]
        blob, filename, mime_type = tg_download_file(audio["file_id"])
        attachments.append(
            max_upload_file(
                "audio",
                audio.get("file_name") or filename or "audio.mp3",
                blob,
                audio.get("mime_type") or mime_type,
            )
        )

    # Голосовое
    if post.get("voice"):
        voice = post["voice"]
        blob, filename, mime_type = tg_download_file(voice["file_id"])
        attachments.append(
            max_upload_file(
                "audio",
                filename or "voice.ogg",
                blob,
                voice.get("mime_type") or mime_type,
            )
        )

    # Анимация/GIF как video
    if post.get("animation"):
        animation = post["animation"]
        blob, filename, mime_type = tg_download_file(animation["file_id"])
        attachments.append(
            max_upload_file(
                "video",
                filename or "animation.mp4",
                blob,
                animation.get("mime_type") or mime_type,
            )
        )

    return attachments


def handle_channel_post(post: dict[str, Any]) -> None:
    chat = post["chat"]
    chat_id = int(chat["id"])

    if chat_id != SOURCE_TG_CHAT_ID:
        return

    text = get_post_text(post)
    attachments = extract_attachments_from_post(post)

    if not text and not attachments:
        text = "[Пост без поддерживаемого контента]"

    result = max_send_message(text=text, attachments=attachments)

    max_message = result.get("message", {})
    log.info(
        "Репост выполнен: tg_chat=%s tg_msg=%s -> max_chat=%s max_mid=%s",
        chat_id,
        post.get("message_id"),
        get_target_max_recipient().get("chat_id"),
        max_message.get("mid"),
    )


# =========================
# MAIN LOOP
# =========================
def main() -> None:
    state = load_state()
    log.info("Мост Telegram -> MAX запущен")

    while True:
        try:
            updates = tg_get_updates(state.get("tg_offset"))

            for update in updates:
                state["tg_offset"] = update["update_id"] + 1

                if "channel_post" in update:
                    handle_channel_post(update["channel_post"])

                save_state(state)

        except requests.RequestException as exc:
            log.exception("Сетевая ошибка: %s", exc)
            time.sleep(5)
        except KeyboardInterrupt:
            log.info("Остановка по Ctrl+C")
            break
        except Exception as exc:
            log.exception("Необработанная ошибка: %s", exc)
            time.sleep(5)


if __name__ == "__main__":
    main()
