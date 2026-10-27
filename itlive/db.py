"""Single-instance SQLite repository. Every mutation uses a short transaction."""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


STATUSES = (
    "Yangi mijoz", "Bog‘lanishga urinish", "Telefon qilindi", "Qayta aloqa",
    "Uchrashuv belgilandi", "Uchrashuv bo‘lib o‘tdi", "Sotildi", "Sotilmadi",
)
ROLES = ("operator", "admin", "owner")


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=10000")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init(self, owner_id: int = 0):
        with self.connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
            CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS staff(id INTEGER PRIMARY KEY, telegram_id INTEGER NOT NULL UNIQUE, name TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('operator','admin','owner')), active INTEGER NOT NULL DEFAULT 1);
            CREATE TABLE IF NOT EXISTS branches(id INTEGER PRIMARY KEY, name TEXT NOT NULL, address TEXT NOT NULL DEFAULT '', landmark TEXT NOT NULL DEFAULT '', hours TEXT NOT NULL DEFAULT '', phone TEXT NOT NULL DEFAULT '', latitude REAL, longitude REAL, active INTEGER NOT NULL DEFAULT 1, sort_order INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS mentors(id INTEGER PRIMARY KEY, name TEXT NOT NULL, specialty TEXT NOT NULL DEFAULT '', bio TEXT NOT NULL DEFAULT '', photo_file_id TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1, sort_order INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS courses(id INTEGER PRIMARY KEY, name TEXT NOT NULL, short_description TEXT NOT NULL DEFAULT '', description TEXT NOT NULL DEFAULT '', audience TEXT NOT NULL DEFAULT '', duration TEXT NOT NULL DEFAULT '', format TEXT NOT NULL DEFAULT '', syllabus TEXT NOT NULL DEFAULT '', price TEXT NOT NULL DEFAULT '', show_price INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1, sort_order INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS course_mentors(course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE, mentor_id INTEGER NOT NULL REFERENCES mentors(id) ON DELETE CASCADE, PRIMARY KEY(course_id,mentor_id));
            CREATE TABLE IF NOT EXISTS course_branches(course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE, branch_id INTEGER NOT NULL REFERENCES branches(id) ON DELETE CASCADE, PRIMARY KEY(course_id,branch_id));
            CREATE TABLE IF NOT EXISTS faq(id INTEGER PRIMARY KEY, question TEXT NOT NULL, answer TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, sort_order INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS campaigns(code TEXT PRIMARY KEY, title TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1);
            CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS leads(id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id), request_type TEXT NOT NULL CHECK(request_type IN ('course','callback')), name TEXT NOT NULL, phone_e164 TEXT NOT NULL, phone_verified_by_contact INTEGER NOT NULL DEFAULT 0, course_id INTEGER REFERENCES courses(id), course_name_snapshot TEXT, branch_id INTEGER REFERENCES branches(id), branch_name_snapshot TEXT, source TEXT NOT NULL, campaign_code TEXT, status TEXT NOT NULL DEFAULT 'Yangi mijoz', assignee_id INTEGER REFERENCES staff(id), preferred_contact_time TEXT, note TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, first_contact_at TEXT, closed_at TEXT, next_action_at TEXT, meeting_at TEXT, meeting_format TEXT, lost_reason TEXT, confirmation_key TEXT UNIQUE, anonymized_at TEXT, merged_into_id INTEGER REFERENCES leads(id));
            CREATE TABLE IF NOT EXISTS lead_events(id INTEGER PRIMARY KEY, lead_id INTEGER NOT NULL REFERENCES leads(id), actor_staff_id INTEGER REFERENCES staff(id), kind TEXT NOT NULL, old_value TEXT, new_value TEXT, note TEXT, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS reminders(id INTEGER PRIMARY KEY, lead_id INTEGER NOT NULL REFERENCES leads(id), kind TEXT NOT NULL, due_at TEXT NOT NULL, sent_at TEXT, cancelled_at TEXT);
            CREATE TABLE IF NOT EXISTS notification_outbox(id INTEGER PRIMARY KEY, chat_id INTEGER NOT NULL, lead_id INTEGER REFERENCES leads(id), message TEXT NOT NULL, sent_at TEXT, attempts INTEGER NOT NULL DEFAULT 0, next_attempt_at TEXT NOT NULL, last_error TEXT);
            CREATE TABLE IF NOT EXISTS login_tokens(token_hash TEXT PRIMARY KEY, staff_id INTEGER NOT NULL REFERENCES staff(id), expires_at TEXT NOT NULL, used_at TEXT);
            CREATE TABLE IF NOT EXISTS web_sessions(token_hash TEXT PRIMARY KEY, staff_id INTEGER NOT NULL REFERENCES staff(id), csrf_token TEXT NOT NULL, expires_at TEXT NOT NULL, revoked_at TEXT);
            CREATE TABLE IF NOT EXISTS form_drafts(user_id INTEGER PRIMARY KEY, data TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS processed_updates(update_id INTEGER PRIMARY KEY, received_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS admin_audit(id INTEGER PRIMARY KEY, actor_staff_id INTEGER REFERENCES staff(id), action TEXT NOT NULL, detail TEXT, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS login_attempts(ip_hash TEXT PRIMARY KEY, count INTEGER NOT NULL, window_start TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS leads_status ON leads(status);
            CREATE INDEX IF NOT EXISTS leads_assignee ON leads(assignee_id);
            CREATE INDEX IF NOT EXISTS leads_created ON leads(created_at);
            CREATE INDEX IF NOT EXISTS leads_next_action ON leads(next_action_at);
            CREATE INDEX IF NOT EXISTS leads_phone ON leads(phone_e164);
            CREATE INDEX IF NOT EXISTS outbox_due ON notification_outbox(sent_at,next_attempt_at);
            CREATE INDEX IF NOT EXISTS reminders_due ON reminders(sent_at,cancelled_at,due_at);
            """)
            db.execute("INSERT OR IGNORE INTO schema_migrations VALUES(1)")
            columns={row["name"] for row in db.execute("PRAGMA table_info(leads)")}
            if "merged_into_id" not in columns:
                db.execute("ALTER TABLE leads ADD COLUMN merged_into_id INTEGER REFERENCES leads(id)")
            db.execute("INSERT OR IGNORE INTO schema_migrations VALUES(2)")
            if owner_id:
                db.execute("INSERT INTO staff(telegram_id,name,role) VALUES(?,?,?) ON CONFLICT(telegram_id) DO UPDATE SET role='owner',active=1", (owner_id, "Egasi", "owner"))
                now=utc_now()
                previous=db.execute("SELECT id FROM staff WHERE role='owner' AND telegram_id<>? AND active=1",(owner_id,)).fetchall()
                if previous:
                    old_ids=tuple(row["id"] for row in previous)
                    placeholders=",".join("?" for _ in old_ids)
                    db.execute(f"UPDATE staff SET active=0 WHERE id IN ({placeholders})",old_ids)
                    db.execute(f"UPDATE web_sessions SET revoked_at=? WHERE staff_id IN ({placeholders}) AND revoked_at IS NULL",(now,*old_ids))
                    db.execute(f"UPDATE login_tokens SET used_at=? WHERE staff_id IN ({placeholders}) AND used_at IS NULL",(now,*old_ids))

    def one(self, sql, params=()):
        with self.connection() as db:
            return db.execute(sql, params).fetchone()

    def all(self, sql, params=()):
        with self.connection() as db:
            return db.execute(sql, params).fetchall()

    def staff_by_telegram(self, telegram_id):
        return self.one("SELECT * FROM staff WHERE telegram_id=? AND active=1", (telegram_id,))

    def staff_by_id(self, staff_id):
        return self.one("SELECT * FROM staff WHERE id=? AND active=1", (staff_id,))

    def upsert_user(self, user):
        with self.connection() as db:
            db.execute("INSERT INTO users(id,username,first_name,created_at) VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET username=excluded.username,first_name=excluded.first_name", (user.id, user.username, user.first_name, utc_now()))

    def get_draft(self, user_id):
        row = self.one("SELECT data FROM form_drafts WHERE user_id=?", (user_id,))
        return json.loads(row["data"]) if row else None

    def put_draft(self, user_id, data):
        with self.connection() as db:
            db.execute("INSERT INTO form_drafts VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET data=excluded.data,updated_at=excluded.updated_at", (user_id,json.dumps(data,ensure_ascii=False),utc_now()))

    def clear_draft(self, user_id):
        with self.connection() as db:
            db.execute("DELETE FROM form_drafts WHERE user_id=?", (user_id,))

    def create_lead(self, data, key, notify_ids):
        """Atomic, idempotent lead and outbox insert. Returns (id, created)."""
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT id FROM leads WHERE confirmation_key=?", (key,)).fetchone()
            if old:
                return old["id"], False
            if data.get("user_id") and data.get("course_id"):
                old = db.execute("SELECT id FROM leads WHERE user_id=? AND course_id=? AND request_type='course' AND status NOT IN ('Sotildi','Sotilmadi') AND anonymized_at IS NULL AND merged_into_id IS NULL ORDER BY id DESC LIMIT 1", (data["user_id"],data["course_id"])).fetchone()
                if old:
                    return old["id"], False
            course = db.execute("SELECT name FROM courses WHERE id=? AND active=1", (data.get("course_id"),)).fetchone() if data.get("course_id") else None
            if data.get("request_type") == "course" and not course:
                raise ValueError("Kurs endi faol emas")
            branch = db.execute("SELECT name FROM branches WHERE id=? AND active=1", (data.get("branch_id"),)).fetchone() if data.get("branch_id") else None
            if data.get("branch_id") and not branch:
                raise ValueError("Filial endi faol emas")
            now = utc_now()
            cur = db.execute("""INSERT INTO leads(user_id,request_type,name,phone_e164,phone_verified_by_contact,course_id,course_name_snapshot,branch_id,branch_name_snapshot,source,campaign_code,status,preferred_contact_time,note,created_at,updated_at,confirmation_key)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                data.get("user_id"),data["request_type"],data["name"],data["phone_e164"],int(data.get("phone_verified_by_contact",False)),data.get("course_id"),course["name"] if course else None,data.get("branch_id"),branch["name"] if branch else None,data.get("source","telegram_direct"),data.get("campaign_code"),STATUSES[0],data.get("preferred_contact_time"),data.get("note"),now,now,key,
            ))
            lead_id = cur.lastrowid
            db.execute("INSERT INTO lead_events(lead_id,kind,new_value,created_at) VALUES(?,?,?,?)", (lead_id,"created",STATUSES[0],now))
            msg = f"🆕 Ariza #{lead_id}\n{data['name']} · {data['phone_e164']}\n{course['name'] if course else 'Qo‘ng‘iroq so‘rovi'}"
            for chat_id in notify_ids:
                db.execute("INSERT INTO notification_outbox(chat_id,lead_id,message,next_attempt_at) VALUES(?,?,?,?)", (chat_id,lead_id,msg,now))
            return lead_id, True

    def update_lead(self, lead_id, staff_id, changes, event_kind="update", note=None):
        allowed = {"name","phone_e164","course_id","branch_id","status","assignee_id","next_action_at","meeting_at","meeting_format","note","lost_reason"}
        if not changes or set(changes) - allowed:
            raise ValueError("Noto‘g‘ri maydon")
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT * FROM leads WHERE id=? AND anonymized_at IS NULL", (lead_id,)).fetchone()
            if not old:
                raise ValueError("Ariza topilmadi")
            staff = db.execute("SELECT * FROM staff WHERE id=? AND active=1", (staff_id,)).fetchone()
            claim = changes == {"assignee_id": staff_id} and old["assignee_id"] is None
            if not staff or (staff["role"] == "operator" and old["assignee_id"] != staff_id and not claim):
                raise PermissionError("Ruxsat yo‘q")
            if staff["role"] == "operator" and not claim:
                restricted={"name","phone_e164","course_id","branch_id","assignee_id"}
                if any(key in restricted and value != old[key] for key,value in changes.items()):
                    raise PermissionError("Bu ma’lumotni faqat admin tuzatadi")
            status = changes.get("status", old["status"])
            if status not in STATUSES:
                raise ValueError("Noto‘g‘ri status")
            if status == "Qayta aloqa" and not changes.get("next_action_at",old["next_action_at"]):
                raise ValueError("Qayta aloqa vaqti kerak")
            if status == "Uchrashuv belgilandi" and (not changes.get("meeting_at",old["meeting_at"]) or not changes.get("meeting_format",old["meeting_format"])):
                raise ValueError("Uchrashuv vaqti va formati kerak")
            if status in ("Telefon qilindi","Uchrashuv bo‘lib o‘tdi") and status != old["status"] and not (note or changes.get("note")):
                raise ValueError("Natija izohi kerak")
            if status == "Sotildi" and not changes.get("course_id",old["course_id"]):
                raise ValueError("Sotilgan kurs kerak")
            if status == "Sotilmadi" and not changes.get("lost_reason",old["lost_reason"]):
                raise ValueError("Sotilmaganlik sababi kerak")
            if old["status"] in ("Sotildi","Sotilmadi") and status != old["status"] and (not note or note==old["note"]):
                raise ValueError("Qayta ochish sababi kerak")
            if "course_id" in changes:
                row = db.execute("SELECT name FROM courses WHERE id=?", (changes["course_id"],)).fetchone() if changes["course_id"] else None
                changes["course_name_snapshot"] = row["name"] if row else None
            if "branch_id" in changes:
                row = db.execute("SELECT name FROM branches WHERE id=?", (changes["branch_id"],)).fetchone() if changes["branch_id"] else None
                changes["branch_name_snapshot"] = row["name"] if row else None
            now = utc_now()
            if status != old["status"]:
                if status in ("Telefon qilindi","Uchrashuv bo‘lib o‘tdi","Sotildi") and not old["first_contact_at"]:
                    changes["first_contact_at"] = now
                changes["closed_at"] = now if status in ("Sotildi","Sotilmadi") else None
            changes["updated_at"] = now
            sql = ",".join(f"{field}=?" for field in changes)
            db.execute(f"UPDATE leads SET {sql} WHERE id=?", (*changes.values(),lead_id))
            for field,value in changes.items():
                if field != "updated_at" and old[field] != value:
                    db.execute("INSERT INTO lead_events(lead_id,actor_staff_id,kind,old_value,new_value,note,created_at) VALUES(?,?,?,?,?,?,?)", (lead_id,staff_id,event_kind+":"+field,str(old[field]) if old[field] is not None else None,str(value) if value is not None else None,note,now))
            db.execute("UPDATE reminders SET cancelled_at=? WHERE lead_id=? AND sent_at IS NULL AND cancelled_at IS NULL", (now,lead_id))
            due = changes.get("next_action_at") if status == "Qayta aloqa" else changes.get("meeting_at") if status == "Uchrashuv belgilandi" else None
            if due:
                db.execute("INSERT INTO reminders(lead_id,kind,due_at) VALUES(?,?,?)", (lead_id,status,due))

    def visible_lead(self, lead_id, staff):
        row = self.one("SELECT * FROM leads WHERE id=? AND merged_into_id IS NULL", (lead_id,))
        if not row or (staff["role"] == "operator" and row["assignee_id"] != staff["id"]):
            return None
        return row

    def list_leads(self, staff, filters, limit=50, offset=0):
        where, params = ["l.anonymized_at IS NULL","l.merged_into_id IS NULL"], []
        if staff["role"] == "operator":
            where.append("l.assignee_id=?"); params.append(staff["id"])
        for key,col in (("status","l.status"),("course","l.course_id"),("branch","l.branch_id"),("source","l.source"),("assignee","l.assignee_id")):
            if filters.get(key):
                where.append(f"{col}=?"); params.append(filters[key])
        if filters.get("q"):
            q=filters["q"][:80]
            where.append("(l.name LIKE ? OR l.phone_e164 LIKE ? OR CAST(l.id AS TEXT)=? OR u.username LIKE ?)")
            params.extend((f"%{q}%",f"%{q}%",q,f"%{q}%"))
        if filters.get("from"):
            where.append("l.created_at>=?"); params.append(self._date_boundary(filters["from"]))
        if filters.get("to"):
            where.append("l.created_at<?"); params.append(self._date_boundary(filters["to"],next_day=True))
        if filters.get("due") == "overdue":
            where.append("l.next_action_at<? AND l.status='Qayta aloqa'"); params.append(utc_now())
        if filters.get("unanswered"):
            where.append("l.first_contact_at IS NULL")
        clause = " AND ".join(where)
        order = {"old":"l.created_at ASC","unanswered":"l.first_contact_at IS NOT NULL,l.created_at ASC","due":"l.next_action_at IS NULL,l.next_action_at ASC"}.get(filters.get("sort"),"l.created_at DESC")
        base = " FROM leads l LEFT JOIN users u ON u.id=l.user_id WHERE " + clause
        with self.connection() as db:
            count=db.execute("SELECT COUNT(*)"+base,params).fetchone()[0]
            rows=db.execute("SELECT l.*,u.username"+base+f" ORDER BY {order} LIMIT ? OFFSET ?",(*params,limit,offset)).fetchall()
            return rows,count

    @staticmethod
    def _date_boundary(value, next_day=False):
        if len(value)==10:
            day=datetime.fromisoformat(value)
            if next_day: day+=timedelta(days=1)
            return day.replace(tzinfo=ZoneInfo("Asia/Tashkent")).astimezone(timezone.utc).isoformat(timespec="seconds")
        return value

    def mark_update(self, update_id):
        with self.connection() as db:
            cur=db.execute("INSERT OR IGNORE INTO processed_updates VALUES(?,?)",(update_id,utc_now()))
            return cur.rowcount == 1

    def merge_leads(self, target_id, source_id, staff_id):
        if target_id==source_id: raise ValueError("Bir xil arizani birlashtirib bo‘lmaydi")
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            staff=db.execute("SELECT role FROM staff WHERE id=? AND active=1",(staff_id,)).fetchone()
            if not staff or staff["role"] not in ("admin","owner"): raise PermissionError("Ruxsat yo‘q")
            target=db.execute("SELECT * FROM leads WHERE id=? AND anonymized_at IS NULL AND merged_into_id IS NULL",(target_id,)).fetchone()
            source=db.execute("SELECT * FROM leads WHERE id=? AND anonymized_at IS NULL AND merged_into_id IS NULL",(source_id,)).fetchone()
            if not target or not source: raise ValueError("Ariza topilmadi")
            if target["phone_e164"]!=source["phone_e164"]: raise ValueError("Telefonlari mos kelmaydi")
            now=utc_now()
            db.execute("UPDATE leads SET merged_into_id=?,updated_at=? WHERE id=?",(target_id,now,source_id))
            db.execute("UPDATE reminders SET cancelled_at=? WHERE lead_id=? AND sent_at IS NULL AND cancelled_at IS NULL",(now,source_id))
            db.execute("DELETE FROM notification_outbox WHERE lead_id=? AND sent_at IS NULL",(source_id,))
            db.execute("INSERT INTO lead_events(lead_id,actor_staff_id,kind,old_value,new_value,created_at) VALUES(?,?,?,?,?,?)",(target_id,staff_id,"merge",str(source_id),str(target_id),now))
            db.execute("INSERT INTO lead_events(lead_id,actor_staff_id,kind,new_value,created_at) VALUES(?,?,?,?,?)",(source_id,staff_id,"merged_into",str(target_id),now))
