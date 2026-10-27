from unittest.mock import AsyncMock

import pytest
from aiogram import Bot, Dispatcher
from aiogram.types import Update

from itlive.bot import create_router
from itlive.db import Store


def update_message(update_id, text=None, contact=None):
    message={"message_id":update_id,"date":1,"chat":{"id":333,"type":"private"},"from":{"id":333,"is_bot":False,"first_name":"Ali"}}
    if text is not None: message["text"]=text
    if contact is not None: message["contact"]=contact
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
