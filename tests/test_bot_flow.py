from unittest.mock import AsyncMock
from io import BytesIO

import pytest
from aiogram import Bot, Dispatcher
from aiogram.types import Update

from itlive.bot import create_router
from itlive.db import Store


def update_message(update_id, text=None, contact=None, voice=None):
    message={"message_id":update_id,"date":1,"chat":{"id":333,"type":"private"},"from":{"id":333,"is_bot":False,"first_name":"Ali"}}
    if text is not None: message["text"]=text
    if contact is not None: message["contact"]=contact
    if voice is not None: message["voice"]=voice
    return Update.model_validate({"update_id":update_id,"message":message})


def update_callback(update_id, data):
    return Update.model_validate({"update_id":update_id,"callback_query":{"id":str(update_id),"from":{"id":333,"is_bot":False,"first_name":"Ali"},"chat_instance":"x","data":data,"message":{"message_id":update_id,"date":1,"chat":{"id":333,"type":"private"},"text":"old"}}})


@pytest.mark.asyncio
async def test_callback_form_and_repeat_confirm(tmp_path,monkeypatch):
    store=Store(tmp_path/"flow.sqlite3"); store.init(111)
    bot=Bot("123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi")
    api=AsyncMock()
    monkeypatch.setattr(Bot,"__call__",api)
    dp=Dispatcher(); dp.include_router(create_router(store,"https://example.org"))
    await dp.feed_update(bot,update_message(1,"/start"))
    await dp.feed_update(bot,update_callback(2,"callback"))
    await dp.feed_update(bot,update_message(3,"Ali Vali"))
    await dp.feed_update(bot,update_message(4,"+998901234567"))
    await dp.feed_update(bot,update_callback(5,"skip"))
    await dp.feed_update(bot,update_callback(6,"confirm"))
    await dp.feed_update(bot,update_callback(7,"confirm"))
    assert store.one("SELECT COUNT(*) AS n FROM leads")["n"]==1
    assert store.one("SELECT request_type,course_id FROM leads")["request_type"]=="callback"
    assert "#1" in api.await_args.args[0].text
    await bot.session.close()


@pytest.mark.asyncio
async def test_foreign_contact_rejected(tmp_path,monkeypatch):
    store=Store(tmp_path/"contact.sqlite3"); store.init(111)
    bot=Bot("123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi")
    api=AsyncMock()
    monkeypatch.setattr(Bot,"__call__",api)
    dp=Dispatcher(); dp.include_router(create_router(store,"https://example.org"))
    await dp.feed_update(bot,update_message(1,"/start"))
    await dp.feed_update(bot,update_callback(2,"callback"))
    await dp.feed_update(bot,update_message(3,"Ali Vali"))
    await dp.feed_update(bot,update_message(4,contact={"phone_number":"+998901234567","first_name":"Other","user_id":999}))
    assert store.get_draft(333)["step"]=="phone"
    assert "Faqat o‘z kontaktingizni" in api.await_args.args[0].text
    await bot.session.close()


@pytest.mark.asyncio
async def test_owner_agent_report_and_task_queue(tmp_path,monkeypatch):
    store=Store(tmp_path/"agent.sqlite3"); store.init(333)
    bot=Bot("123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi")
    api=AsyncMock()
    monkeypatch.setattr(Bot,"__call__",api)
    dp=Dispatcher(); dp.include_router(create_router(store,"https://example.org"))
    await dp.feed_update(bot,update_callback(1,"agent:report"))
    await dp.feed_update(bot,update_callback(2,"agent:task"))
    await dp.feed_update(bot,update_message(3,"ali | Lead #12 ga qo‘ng‘iroq qiling"))
    rows=store.all("SELECT telegram_id,kind,payload FROM agent_requests ORDER BY id")
    assert [(r["telegram_id"],r["kind"]) for r in rows]==[(333,"report"),(333,"task")]
    assert "Lead #12" in rows[1]["payload"]
    assert store.one("SELECT 1 FROM agent_modes WHERE user_id=333") is None
    await bot.session.close()


@pytest.mark.asyncio
async def test_owner_can_send_natural_text_and_voice_without_button(tmp_path,monkeypatch):
    store=Store(tmp_path/"voice.sqlite3"); store.init(333)
    bot=Bot("123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi")
    monkeypatch.setattr(Bot,"__call__",AsyncMock())
    monkeypatch.setattr(Bot,"download",AsyncMock(return_value=BytesIO(b"ogg-audio")))
    dp=Dispatcher(); dp.include_router(create_router(store,"https://example.org"))
    await dp.feed_update(bot,update_message(1,"bobur barcha leadlarga bugun soat 20.00 gacha telefon qilsin"))
    await dp.feed_update(bot,update_message(2,voice={"file_id":"test-voice","file_unique_id":"unique","duration":4,"file_size":9}))
    rows=store.all("SELECT id,kind,payload FROM agent_requests ORDER BY id")
    assert [r["kind"] for r in rows]==["task","task"]
    assert rows[0]["payload"].startswith("bobur barcha")
    assert store.one("SELECT audio FROM agent_voice_files WHERE request_id=?",(rows[1]["id"],))["audio"]==b"ogg-audio"
    await bot.session.close()


@pytest.mark.asyncio
async def test_non_owner_cannot_queue_agent_request(tmp_path,monkeypatch):
    store=Store(tmp_path/"agent-denied.sqlite3"); store.init(111)
    bot=Bot("123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi")
    monkeypatch.setattr(Bot,"__call__",AsyncMock())
    dp=Dispatcher(); dp.include_router(create_router(store,"https://example.org"))
    await dp.feed_update(bot,update_callback(1,"agent:report"))
    await dp.feed_update(bot,update_message(2,"/task ali | Xabar"))
    assert store.one("SELECT 1 FROM agent_requests") is None
    await bot.session.close()
