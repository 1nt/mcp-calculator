import os
import json
import uuid
import re
import sys
import asyncio
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from apscheduler.schedulers.asyncio import AsyncIOScheduler

TIMERS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "timers.json")
DEFAULT_TZ = os.getenv("TIMEZONE", "Europe/Moscow")
MQTT_BROKER = os.getenv("MQTT_BROKER", "api.tenclass.net")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
BASE_AUDIO_URL = os.getenv("AUDIO_URL", "https://actions.google.com/sounds/v1/alarms/alarm_clock.ogg")
DEVICE_ID = os.getenv("DEVICE_ID", "default_device")
HA_WEBHOOK_URL = os.getenv("HA_WEBHOOK_URL", "")

scheduler = None
active_timers = {}


def get_tz():
    tz_name = os.getenv("TIMEZONE", DEFAULT_TZ)
    try:
        return ZoneInfo(tz_name)
    except Exception:
        return timezone.utc


def load_timers():
    global active_timers
    if os.path.exists(TIMERS_FILE):
        try:
            with open(TIMERS_FILE, "r", encoding="utf-8") as f:
                active_timers = json.load(f)
        except Exception as e:
            sys.stderr.write(f"[ALARM] Error loading timers: {e}\n")
            sys.stderr.flush()
            active_timers = {}
    else:
        active_timers = {}
    return active_timers


def save_timers():
    try:
        with open(TIMERS_FILE, "w", encoding="utf-8") as f:
            json.dump(active_timers, f, ensure_ascii=False, indent=2)
    except Exception as e:
        sys.stderr.write(f"[ALARM] Error saving timers: {e}\n")
        sys.stderr.flush()


def restore_scheduled_jobs():
    load_timers()
    tz = get_tz()
    now = datetime.now(tz)
    expired = []
    sched = get_scheduler()
    for timer_id, data in list(active_timers.items()):
        try:
            run_at = datetime.fromisoformat(data["run_at"])
            if run_at.tzinfo is None:
                run_at = run_at.replace(tzinfo=tz)
            if run_at > now:
                sched.add_job(
                    fire_alarm,
                    trigger="date",
                    run_date=run_at,
                    args=[timer_id, data["title"], data.get("device_id", DEVICE_ID)],
                    id=timer_id,
                    replace_existing=True,
                )
                sys.stderr.write(f"[ALARM] Restored timer '{data['title']}' for {run_at}\n")
            else:
                expired.append(timer_id)
        except Exception as e:
            sys.stderr.write(f"[ALARM] Failed to restore timer {timer_id}: {e}\n")
            expired.append(timer_id)
    for tid in expired:
        active_timers.pop(tid, None)
    if expired:
        save_timers()
    sys.stderr.flush()


def get_scheduler():
    global scheduler
    if scheduler is None:
        scheduler = AsyncIOScheduler()
        scheduler.start()
        restore_scheduled_jobs()
    elif not scheduler.running:
        scheduler.start()
    return scheduler


async def fire_alarm(timer_id: str, title: str, device_id: str = None):
    dev_id = device_id or os.getenv("DEVICE_ID", DEVICE_ID)
    sys.stderr.write(f"[ALARM TRIGGERED] '{title}' (id: {timer_id}) for device: {dev_id}\n")
    sys.stderr.flush()

    load_timers()
    if timer_id in active_timers:
        del active_timers[timer_id]
        save_timers()

    audio_url = os.getenv("AUDIO_URL", BASE_AUDIO_URL)
    payload = {
        "type": "notify",
        "audio_url": audio_url,
        "subtitles": [
            {"start_ms": 0, "text": f"Будильник: {title}"}
        ],
    }

    # 1. Отправка в MQTT брокер (если настроен)
    broker = os.getenv("MQTT_BROKER", MQTT_BROKER)
    port = int(os.getenv("MQTT_PORT", str(MQTT_PORT)))
    if broker:
        try:
            import aiomqtt
            async with aiomqtt.Client(broker, port, timeout=4) as client:
                topic = f"devices/{dev_id}/command"
                await client.publish(topic, json.dumps(payload))
                sys.stderr.write(f"[ALARM MQTT] Published to {topic}: {payload}\n")
                sys.stderr.flush()
        except Exception as e:
            sys.stderr.write(f"[ALARM MQTT ERROR] Failed to send push via MQTT: {e}\n")
            sys.stderr.flush()

    # 2. Отправка в Home Assistant Webhook (если настроен)
    ha_url = os.getenv("HA_WEBHOOK_URL", HA_WEBHOOK_URL)
    if ha_url:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=5) as http_client:
                await http_client.post(
                    ha_url,
                    json={"title": title, "device_id": dev_id, "type": "alarm", "payload": payload},
                )
                sys.stderr.write(f"[ALARM HA] Triggered webhook {ha_url}\n")
                sys.stderr.flush()
        except Exception as e:
            sys.stderr.write(f"[ALARM HA ERROR] Failed to call HA webhook: {e}\n")
            sys.stderr.flush()


async def set_timer_impl(title: str, seconds: int = None, target_time: str = None, device_id: str = None) -> str:
    """Установить будильник или таймер."""
    tz = get_tz()
    now = datetime.now(tz)

    if seconds is not None and int(seconds) > 0:
        run_at = now + timedelta(seconds=int(seconds))
    elif target_time:
        m = re.match(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$", target_time.strip())
        if m:
            h, mn = int(m.group(1)), int(m.group(2))
            s = int(m.group(3)) if m.group(3) else 0
            if h < 0 or h > 23 or mn < 0 or mn > 59 or s < 0 or s > 59:
                return "Ошибка: некорректное время. Часы должны быть от 0 до 23, минуты от 0 до 59."
            run_at = now.replace(hour=h, minute=mn, second=s, microsecond=0)
            if run_at <= now:
                run_at += timedelta(days=1)
        else:
            try:
                run_at = datetime.fromisoformat(target_time.strip())
                if run_at.tzinfo is None:
                    run_at = run_at.replace(tzinfo=tz)
                if run_at <= now:
                    return f"Ошибка: указанное время {target_time} уже прошло."
            except Exception:
                return f"Ошибка: не удалось распознать время '{target_time}'. Укажите время в формате 'HH:MM' (например '07:30')."
    else:
        return "Ошибка: укажите количество секунд (seconds) или точное время (target_time)."

    timer_id = str(uuid.uuid4())[:8]
    dev_id = device_id or os.getenv("DEVICE_ID", DEVICE_ID)

    load_timers()
    active_timers[timer_id] = {
        "id": timer_id,
        "title": title,
        "run_at": run_at.isoformat(),
        "device_id": dev_id,
    }
    save_timers()

    sched = get_scheduler()
    sched.add_job(
        fire_alarm,
        trigger="date",
        run_date=run_at,
        args=[timer_id, title, dev_id],
        id=timer_id,
        replace_existing=True,
    )

    remaining_sec = max(1, int((run_at - now).total_seconds()))
    hours, rem = divmod(remaining_sec, 3600)
    mins, secs = divmod(rem, 60)

    time_str = run_at.strftime("%H:%M")
    diff_parts = []
    if hours > 0:
        diff_parts.append(f"{hours} ч")
    if mins > 0 or hours > 0:
        diff_parts.append(f"{mins} мин")
    diff_parts.append(f"{secs} сек")
    diff_str = " ".join(diff_parts)

    return f"Будильник '{title}' установлен на {time_str} (сработает через {diff_str})."


async def get_active_timers_impl() -> str:
    """Возвращает список всех активных таймеров и будильников."""
    load_timers()
    if not active_timers:
        return "Активных таймеров и будильников сейчас нет."

    tz = get_tz()
    now = datetime.now(tz)
    lines = ["Активные таймеры и будильники:"]
    expired = []

    for t_id, data in list(active_timers.items()):
        try:
            run_at = datetime.fromisoformat(data["run_at"])
            if run_at.tzinfo is None:
                run_at = run_at.replace(tzinfo=tz)
            left = int((run_at - now).total_seconds())
            if left > 0:
                h, rem = divmod(left, 3600)
                m, s = divmod(rem, 60)
                left_str = f"{h}ч {m}м {s}с" if h > 0 else f"{m}м {s}с"
                lines.append(f"- '{data['title']}' на {run_at.strftime('%H:%M')} (осталось {left_str})")
            else:
                expired.append(t_id)
        except Exception:
            expired.append(t_id)

    for tid in expired:
        active_timers.pop(tid, None)
    if expired:
        save_timers()

    if len(lines) == 1:
        return "Активных таймеров и будильников сейчас нет."
    return "\n".join(lines)


async def cancel_timer_impl(title: str) -> str:
    """Отменить таймер или будильник по названию или ID."""
    load_timers()
    title_lower = title.strip().lower()
    matched_id = None
    matched_title = None

    for t_id, data in list(active_timers.items()):
        if t_id.lower() == title_lower or title_lower in data["title"].lower():
            matched_id = t_id
            matched_title = data["title"]
            break

    if matched_id:
        sched = get_scheduler()
        try:
            sched.remove_job(matched_id)
        except Exception:
            pass
        del active_timers[matched_id]
        save_timers()
        return f"Таймер/будильник '{matched_title}' успешно отменен."

    return f"Таймер или будильник с названием или ID '{title}' не найден."
