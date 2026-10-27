import asyncio
import secrets
from datetime import datetime,timedelta,timezone
from hashlib import sha256

import pytest
from aiohttp.test_utils import TestClient, TestServer

from itlive.bot import clean_name, phone
from itlive.config import Config
from itlive.db import Store
from itlive.__main__ import make_app
from itlive.backup import backup,verify


@pytest.fixture
def store(tmp_path):
    db=Store(tmp_path/"test.sqlite3")
    db.init(111)
    with db.connection() as conn:
        conn.execute("INSERT INTO staff(telegram_id,name,role) VALUES(222,'Operator','operator')")
        conn.execute("INSERT INTO courses(name,short_description) VALUES('Python','Boshlang‘ich kurs')")
        conn.execute("INSERT INTO branches(name,address) VALUES('Markaz','Toshkent')")
        conn.execute("INSERT INTO users VALUES(333,'user','Ali',?)",(datetime.now(timezone.utc).isoformat(),))
    return db


def payload():
    return {"user_id":333,"request_type":"course","name":"Ali Vali","phone_e164":"+998901234567","course_id":1,"branch_id":1,"source":"telegram_direct"}


def test_phone_and_name_validation():
    assert phone("90 123 45 67")=="+998901234567"
    assert phone("998901234567")=="+998901234567"
    with pytest.raises(ValueError): phone("123")
    with pytest.raises(ValueError): clean_name(" A ")
    assert clean_name(" Ali   Vali ")=="Ali Vali"


def test_lead_idempotence_duplicate_and_atomic_outbox(store):
    lead,created=store.create_lead(payload(),"same-key",[111,222])
    assert created
    assert store.create_lead(payload(),"same-key",[111,222])==(lead,False)
    assert store.create_lead(payload(),"another-key",[111,222])==(lead,False)
    assert store.one("SELECT COUNT(*) AS n FROM leads")["n"]==1
    assert store.one("SELECT COUNT(*) AS n FROM notification_outbox")["n"]==2
    row=store.one("SELECT course_name_snapshot,branch_name_snapshot FROM leads WHERE id=?",(lead,))
    assert (row["course_name_snapshot"],row["branch_name_snapshot"])==("Python","Markaz")


def test_status_requirements_audit_and_operator_scope(store):
    lead,_=store.create_lead(payload(),"key",[])
    owner=store.staff_by_telegram(111); operator=store.staff_by_telegram(222)
    assert store.visible_lead(lead,operator) is None
    with pytest.raises(PermissionError): store.update_lead(lead,operator["id"],{"status":"Telefon qilindi"},note="Gaplashildi")
    store.update_lead(lead,owner["id"],{"assignee_id":operator["id"]})
    assert store.visible_lead(lead,operator) is not None
    with pytest.raises(ValueError): store.update_lead(lead,operator["id"],{"status":"Qayta aloqa"})
    due=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()
    store.update_lead(lead,operator["id"],{"status":"Qayta aloqa","next_action_at":due})
    assert store.one("SELECT COUNT(*) AS n FROM reminders WHERE lead_id=? AND cancelled_at IS NULL",(lead,))["n"]==1
    assert store.one("SELECT old_value,new_value FROM lead_events WHERE lead_id=? AND kind='update:status'",(lead,))["new_value"]=="Qayta aloqa"


def test_merge_duplicate_is_audited_and_hidden(store):
    first,_=store.create_lead(payload(),"first",[])
    second_payload={**payload(),"user_id":None,"request_type":"callback","course_id":None}
    second,_=store.create_lead(second_payload,"second",[])
    owner=store.staff_by_telegram(111)
    store.merge_leads(first,second,owner["id"])
    rows,count=store.list_leads(owner,{},50,0)
    assert count==1 and rows[0]["id"]==first
    assert store.one("SELECT merged_into_id FROM leads WHERE id=?",(second,))["merged_into_id"]==first
    assert store.one("SELECT kind FROM lead_events WHERE lead_id=? AND kind='merge'",(first,))


def test_online_backup_and_restore_survives_restart(store,tmp_path):
    lead,_=store.create_lead(payload(),"backup",[])
    target=tmp_path/"backup.sqlite3"
    backup(store.path,target)
    verify(target)
    restored=Store(target)
    assert restored.one("SELECT id FROM leads WHERE id=?",(lead,))["id"]==lead


def test_owner_change_revokes_previous_access(store):
    old=store.staff_by_telegram(111)
    now=datetime.now(timezone.utc)
    with store.connection() as db:
        db.execute("INSERT INTO web_sessions VALUES(?,?,?,?,NULL)",("old-session",old["id"],"csrf",(now+timedelta(hours=1)).isoformat()))
        db.execute("INSERT INTO login_tokens VALUES(?,?,?,NULL)",("old-login",old["id"],(now+timedelta(minutes=10)).isoformat()))
    store.init(8735614176)
    assert store.staff_by_telegram(111) is None
    assert store.staff_by_telegram(8735614176)["role"]=="owner"
    assert store.one("SELECT revoked_at FROM web_sessions WHERE token_hash='old-session'")["revoked_at"]
    assert store.one("SELECT used_at FROM login_tokens WHERE token_hash='old-login'")["used_at"]


@pytest.mark.asyncio
async def test_web_login_single_use_csrf_and_role(tmp_path):
    config=Config("","","","",111,tmp_path/"web.sqlite3",dev_mode=True)
    app=await make_app(config)
    async with TestServer(app) as server:
        async with TestClient(server) as client:
            assert (await client.get("/health")).status==200
            assert (await client.get("/admin",allow_redirects=False)).status==302
            store=app["store"]
            raw=secrets.token_urlsafe(24)
            expires=(datetime.now(timezone.utc)+timedelta(minutes=10)).isoformat()
            owner=store.staff_by_telegram(111)
            with store.connection() as db:
                db.execute("INSERT INTO login_tokens VALUES(?,?,?,NULL)",(sha256(raw.encode()).hexdigest(),owner["id"],expires))
            assert (await client.get("/login/"+raw,allow_redirects=False)).status==200
            response=await client.post("/login/"+raw,allow_redirects=False)
            assert response.status==302
            assert (await client.get("/login/"+raw,allow_redirects=False)).status==403
            assert (await client.get("/admin")).status==200
            assert (await client.post("/admin/staff",data={"telegram_id":"222","name":"Op","role":"operator"},allow_redirects=False)).status==403
            cookie=client.session.cookie_jar.filter_cookies(server.make_url("/"))["itlive_session"].value
            csrf=store.one("SELECT csrf_token FROM web_sessions WHERE token_hash=?",(sha256(cookie.encode()).hexdigest(),))["csrf_token"]
            assert (await client.post("/admin/staff",data={"csrf":csrf,"telegram_id":"222","name":"Op","role":"operator"},allow_redirects=False)).status==302
            assert store.staff_by_telegram(222)["role"]=="operator"
            with store.connection() as db:
                db.execute("INSERT INTO mentors(name,bio) VALUES('Mentor','Tasdiqlangan bio')")
                db.execute("INSERT INTO branches(name,address) VALUES('Markaz','Toshkent')")
            edit=await client.get("/admin/content/courses/new")
            assert edit.status==200
            assert "Mentor" in await edit.text()
            save=await client.post("/admin/content/courses/new",data={"csrf":csrf,"name":"Python","short_description":"Boshlang‘ich kurs","active":"1","sort_order":"0","show_price":"0","mentor_ids":"1","branch_ids":"1"},allow_redirects=False)
            assert save.status==302
            assert store.one("SELECT COUNT(*) AS n FROM course_mentors")["n"]==1
            assert store.one("SELECT COUNT(*) AS n FROM course_branches")["n"]==1
            lead,_=store.create_lead({"request_type":"course","name":"Ali Vali","phone_e164":"+998901234567","course_id":1,"branch_id":1,"source":"manual"},"new",[])
            assert (await client.get(f"/admin/leads/{lead}")).status==200
            report=await client.get("/admin/report?group=course&format=csv")
            assert report.status==200
            assert "Python" in (await report.text())
