import asyncio
import logging
import os

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from .bot import create_router
from .config import Config
from .db import Store, utc_now
from .web import routes


log=logging.getLogger("itlive")


async def health(request):
    try:
        request.app["store"].one("SELECT 1")
    except Exception:
        raise web.HTTPServiceUnavailable(text="database unavailable")
    return web.json_response({"status":"ok","bot_configured":bool(request.app["config"].bot_token)})


async def worker(app):
    store=app["store"]
    bot=app.get("bot")
    while True:
        try:
            if bot:
                now=utc_now()
                # Durable reminders are turned into outbox entries before Telegram delivery.
                with store.connection() as db:
                    db.execute("BEGIN IMMEDIATE")
                    due=db.execute("SELECT r.id,r.lead_id,r.kind,l.assignee_id,s.telegram_id FROM reminders r JOIN leads l ON l.id=r.lead_id LEFT JOIN staff s ON s.id=l.assignee_id AND s.active=1 WHERE r.sent_at IS NULL AND r.cancelled_at IS NULL AND r.due_at<=? AND l.anonymized_at IS NULL LIMIT 50",(now,)).fetchall()
                    for reminder in due:
                        if reminder["telegram_id"]:
                            db.execute("INSERT INTO notification_outbox(chat_id,lead_id,message,next_attempt_at) VALUES(?,?,?,?)",(reminder["telegram_id"],reminder["lead_id"],f"⏰ {reminder['kind']}: ariza #{reminder['lead_id']}",now))
                        db.execute("UPDATE reminders SET sent_at=? WHERE id=?",(now,reminder["id"]))
                rows=store.all("SELECT o.* FROM notification_outbox o LEFT JOIN leads l ON l.id=o.lead_id WHERE o.sent_at IS NULL AND o.next_attempt_at<=? AND (l.anonymized_at IS NULL OR o.lead_id IS NULL) ORDER BY o.id LIMIT 30",(now,))
                for row in rows:
                    staff=store.staff_by_telegram(row["chat_id"])
                    if not staff:
                        with store.connection() as db: db.execute("UPDATE notification_outbox SET sent_at=?,last_error='recipient inactive' WHERE id=?",(utc_now(),row["id"]))
                        continue
                    markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="📂 Ochish",callback_data=f"open:{row['lead_id']}"),InlineKeyboardButton(text="🙋 Menga biriktirish",callback_data=f"claim:{row['lead_id']}")],
                        [InlineKeyboardButton(text="☎️ Telefon qilindi",callback_data=f"call:{row['lead_id']}"),InlineKeyboardButton(text="⏰ Qayta aloqa",callback_data=f"followup:{row['lead_id']}")],
                    ]) if row["lead_id"] else None
                    try:
                        await bot.send_message(row["chat_id"],row["message"],reply_markup=markup)
                        with store.connection() as db: db.execute("UPDATE notification_outbox SET sent_at=?,last_error=NULL WHERE id=?",(utc_now(),row["id"]))
                    except Exception as exc:
                        # Do not log phone numbers, tokens or Telegram's full response.
                        delay=min(3600,2**min(row["attempts"],10))
                        from datetime import datetime,timedelta,timezone
                        next_at=(datetime.now(timezone.utc)+timedelta(seconds=delay)).isoformat(timespec="seconds")
                        with store.connection() as db: db.execute("UPDATE notification_outbox SET attempts=attempts+1,next_attempt_at=?,last_error=? WHERE id=?",(next_at,type(exc).__name__,row["id"]))
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Background worker error")
            await asyncio.sleep(5)


async def make_app(config=None):
    config=config or Config.from_env()
    store=Store(config.sqlite_path); store.init(config.owner_telegram_id)
    app=web.Application(client_max_size=1024*1024)
    app["config"]=config; app["store"]=store
    app.router.add_get("/health",health)
    routes(app)
    if config.bot_token:
        bot=Bot(config.bot_token)
        dp=Dispatcher()
        dp.include_router(create_router(store,config.public_base_url))
        app["bot"]=bot
        if config.bot_mode=="webhook":
            SimpleRequestHandler(dp,bot,secret_token=config.webhook_secret,handle_in_background=False).register(app,path="/telegram/webhook")
            setup_application(app,dp,bot=bot)

            async def set_webhook(application):
                await bot.set_webhook(config.public_base_url+"/telegram/webhook",secret_token=config.webhook_secret)
            app.on_startup.append(set_webhook)
        else:
            async def start_polling(application):
                await bot.delete_webhook(drop_pending_updates=False)
                application["polling_task"]=asyncio.create_task(dp.start_polling(bot,handle_signals=False))

            async def stop_polling(application):
                application["polling_task"].cancel()
                try: await application["polling_task"]
                except asyncio.CancelledError: pass
                await bot.session.close()

            app.on_startup.append(start_polling)
            app.on_cleanup.append(stop_polling)

    async def start_worker(application):
        application["worker_task"]=asyncio.create_task(worker(application))

    async def stop_worker(application):
        application["worker_task"].cancel()
        try: await application["worker_task"]
        except asyncio.CancelledError: pass

    app.on_startup.append(start_worker)
    app.on_cleanup.append(stop_worker)
    return app


def main():
    logging.basicConfig(level=logging.INFO,format="%(levelname)s %(name)s: %(message)s")
    config=Config.from_env()
    host=os.getenv("BIND_HOST") or ("127.0.0.1" if config.bot_mode=="polling" else "0.0.0.0")
    if host not in ("127.0.0.1","0.0.0.0"):
        raise ValueError("BIND_HOST 127.0.0.1 yoki 0.0.0.0 bo‘lishi kerak")
    web.run_app(make_app(config),host=host,port=config.port,access_log=None)


if __name__=="__main__": main()
