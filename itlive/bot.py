import html
import re
import secrets
from datetime import datetime, timedelta, timezone
from hashlib import sha256

from aiogram import Bot, Router, F
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, Message, ReplyKeyboardMarkup, ReplyKeyboardRemove

from .db import Store, utc_now


MENU = ["📚 Kurslar", "👨‍🏫 Mentorlar", "📍 Manzil/filiallar", "📝 Kursga yozilish", "📞 Raqam qoldirish", "❓ Savol-javob", "☎️ Aloqa", "🔒 Ma’lumotlarim"]


def esc(value):
    return html.escape(str(value or ""))


def kb(*items):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=label,callback_data=data)] for label,data in items])


def navigation(back="home"):
    return [InlineKeyboardButton(text="◀️ Ortga",callback_data=back),InlineKeyboardButton(text="🏠 Bosh menyu",callback_data="home")]


def phone(value):
    raw=re.sub(r"[\s()\-]", "", value.strip())
    if raw.startswith("00"):
        raw="+"+raw[2:]
    if raw.startswith("998"):
        raw="+"+raw
    if len(raw)==9 and raw.isdigit():
        raw="+998"+raw
    if not re.fullmatch(r"\+998\d{9}",raw):
        raise ValueError("Telefonni +998901234567 shaklida yuboring.")
    return raw


def clean_name(value):
    result=" ".join(value.split())
    if not 2 <= len(result) <= 100 or len(re.findall(r"[^\W\d_]",result,re.UNICODE)) < 2:
        raise ValueError("Ismni 2–100 harf bilan kiriting.")
    return result


def issue_login_link(store, staff, base_url, next_path="/admin"):
    token=secrets.token_urlsafe(32)
    expires=(datetime.now(timezone.utc)+timedelta(minutes=10)).isoformat()
    with store.connection() as db:
        db.execute("INSERT INTO login_tokens VALUES(?,?,?,NULL)",(sha256(token.encode()).hexdigest(),staff["id"],expires))
    from urllib.parse import quote
    return f"{base_url}/login/{token}?next={quote(next_path,safe='/')}"


def create_router(store: Store, base_url: str):
    router=Router()

    async def send(target, text, markup=None, reply_markup=None):
        if isinstance(target,CallbackQuery):
            await target.answer()
            await target.message.answer(text,parse_mode="HTML",reply_markup=markup or reply_markup)
        else:
            await target.answer(text,parse_mode="HTML",reply_markup=markup or reply_markup)

    async def home(target):
        markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=MENU[i],callback_data=key) for i,key in pair]
            for pair in [((0,"courses"),(1,"mentors")),((2,"branches"),(3,"apply")),((4,"callback"),(5,"faq")),((6,"contact"),(7,"mine"))]
        ])
        await send(target,"Assalomu alaykum! ITLIVE qabul botiga xush kelibsiz. Kerakli bo‘limni tanlang.",markup)

    async def content_list(target, table, title, prefix):
        extra={"courses":"AND TRIM(COALESCE(NULLIF(description,''),short_description))<>''","mentors":"AND TRIM(bio)<>''","branches":"AND TRIM(address)<>''"}[table]
        rows=store.all(f"SELECT id,name FROM {table} WHERE active=1 AND TRIM(name)<>'' {extra} ORDER BY sort_order,id")
        if not rows:
            await send(target,f"{title} hozircha e’lon qilinmagan.",kb(("📞 Maslahat so‘rash","callback"),("🏠 Bosh menyu","home")))
            return
        await send(target,title,InlineKeyboardMarkup(inline_keyboard=[*[ [InlineKeyboardButton(text=row["name"],callback_data=f"{prefix}:{row['id']}")] for row in rows],navigation()]))

    async def show_course(target, course_id):
        row=store.one("SELECT * FROM courses WHERE id=? AND active=1",(course_id,))
        if not row or not row["name"].strip() or not (row["short_description"] or row["description"]).strip():
            await send(target,"Bu kurs hozir mavjud emas.",kb(("📚 Kurslar","courses"),("🏠 Bosh menyu","home")))
            return
        fields=[f"<b>{esc(row['name'][:120])}</b>",esc((row["description"] or row["short_description"])[:1000])]
        for label,key in (("Kimlar uchun","audience"),("Davomiylik","duration"),("Format","format"),("Dastur","syllabus")):
            if row[key]: fields.append(f"<b>{label}:</b> {esc(row[key][:1200] if key=='syllabus' else row[key][:200])}")
        fields.append(f"<b>Narx:</b> {esc(row['price'][:100]) if row['show_price'] and row['price'] else 'Narxni menejerdan so‘rang'}")
        mentors=store.all("SELECT m.id,m.name FROM mentors m JOIN course_mentors cm ON cm.mentor_id=m.id WHERE cm.course_id=? AND m.active=1",(course_id,))
        if mentors: fields.append("<b>Mentorlar:</b> "+", ".join(esc(m["name"]) for m in mentors))
        await send(target,"\n\n".join(fields),InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📝 Shu kursga yozilish",callback_data=f"apply:{course_id}")],*[ [InlineKeyboardButton(text="👨‍🏫 "+m["name"],callback_data=f"mentor:{m['id']}")] for m in mentors],navigation("courses")]))

    async def show_mentor(target, mentor_id):
        row=store.one("SELECT * FROM mentors WHERE id=? AND active=1",(mentor_id,))
        if not row or not row["name"].strip() or not row["bio"].strip():
            await send(target,"Mentor kartasi hozir mavjud emas.",kb(("👨‍🏫 Mentorlar","mentors"),("🏠 Bosh menyu","home")))
            return
        courses=store.all("SELECT c.id,c.name FROM courses c JOIN course_mentors cm ON cm.course_id=c.id WHERE cm.mentor_id=? AND c.active=1",(mentor_id,))
        text=f"<b>{esc(row['name'][:120])}</b>\n{esc(row['specialty'][:160])}\n\n{esc(row['bio'][:3000])}"
        markup=InlineKeyboardMarkup(inline_keyboard=[*[ [InlineKeyboardButton(text="📚 "+c["name"],callback_data=f"course:{c['id']}")] for c in courses],navigation("mentors")])
        if row["photo_file_id"]:
            try:
                if isinstance(target,CallbackQuery): await target.answer()
                await target.bot.send_photo(target.from_user.id,row["photo_file_id"],caption=text,parse_mode="HTML",reply_markup=markup)
                return
            except Exception:
                pass
        await send(target,text,markup)

    async def show_branch(target, branch_id):
        row=store.one("SELECT * FROM branches WHERE id=? AND active=1",(branch_id,))
        if not row or not row["name"].strip() or not row["address"].strip():
            await send(target,"Filial ma’lumoti hozir mavjud emas.",kb(("📍 Filiallar","branches"),("🏠 Bosh menyu","home")))
            return
        text="\n".join(x for x in [f"<b>{esc(row['name'][:120])}</b>",esc(row["address"][:1000]),esc(row["landmark"][:300]),esc(row["hours"][:300]),f"Telefon: <a href='tel:{esc(row['phone'])}'>{esc(row['phone'])}</a>" if row["phone"] else ""] if x)
        if isinstance(target,CallbackQuery): await target.answer()
        await target.bot.send_message(target.from_user.id,text,parse_mode="HTML",reply_markup=kb(("◀️ Filiallar","branches"),("🏠 Bosh menyu","home")))
        if row["latitude"] is not None and row["longitude"] is not None:
            await target.bot.send_location(target.from_user.id,row["latitude"],row["longitude"])

    async def next_step(target,draft):
        step=draft["step"]
        if step=="course":
            await content_list(target,"courses","Kursni tanlang:","choosecourse")
        elif step=="branch":
            linked=store.one("SELECT COUNT(*) AS n FROM course_branches WHERE course_id=?",(draft.get("course_id"),))
            if linked and linked["n"]:
                rows=store.all("SELECT b.id,b.name FROM branches b JOIN course_branches cb ON cb.branch_id=b.id WHERE cb.course_id=? AND b.active=1 AND TRIM(b.name)<>'' AND TRIM(b.address)<>'' ORDER BY b.sort_order,b.id",(draft["course_id"],))
            else:
                rows=store.all("SELECT id,name FROM branches WHERE active=1 AND TRIM(name)<>'' AND TRIM(address)<>'' ORDER BY sort_order,id")
            if len(rows)==1:
                draft["branch_id"]=rows[0]["id"]; draft["step"]="name"; store.put_draft(draft["user_id"],draft); await next_step(target,draft); return
            if not rows:
                draft["step"]="name"; store.put_draft(draft["user_id"],draft); await next_step(target,draft); return
            await send(target,"Filialni tanlang:",InlineKeyboardMarkup(inline_keyboard=[*[ [InlineKeyboardButton(text=r["name"],callback_data=f"choosebranch:{r['id']}")] for r in rows],[InlineKeyboardButton(text="Menga farqi yo‘q",callback_data="choosebranch:0")],[InlineKeyboardButton(text="Bekor qilish",callback_data="cancel")]]))
        elif step=="name":
            await send(target,"Ism va familiyangizni yozing:",kb(("Bekor qilish","cancel")))
        elif step=="phone":
            await send(target,"Telefon raqamingizni +998901234567 shaklida yozing yoki o‘z kontaktingizni ulashing:",reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📱 Raqamni ulashish",request_contact=True)],[KeyboardButton(text="Bekor qilish")]],resize_keyboard=True,one_time_keyboard=True))
        elif step=="preferred":
            await send(target,"Qachon qo‘ng‘iroq qilish qulay? Qisqa yozing yoki o‘tkazib yuboring.",kb(("O‘tkazib yuborish","skip"),("Bekor qilish","cancel")))
        elif step=="note":
            await send(target,"Savolingiz yoki izohingiz bormi?",kb(("O‘tkazib yuborish","skip"),("Bekor qilish","cancel")))
        elif step=="confirm":
            course=store.one("SELECT name FROM courses WHERE id=?",(draft.get("course_id"),)) if draft.get("course_id") else None
            branch=store.one("SELECT name FROM branches WHERE id=?",(draft.get("branch_id"),)) if draft.get("branch_id") else None
            policy=store.one("SELECT value FROM settings WHERE key='privacy_url'")
            summary=f"<b>Arizani tasdiqlang</b>\nKurs: {esc(course['name'] if course else 'Maslahat')}\nFilial: {esc(branch['name'] if branch else 'Farqi yo‘q')}\nIsm: {esc(draft['name'])}\nTelefon: {esc(draft['phone_e164'])}\n\nMa’lumotlaringiz qabul xodimlari tomonidan bog‘lanish uchun saqlanadi."
            policy_url=policy["value"] if policy and policy["value"].startswith("https://") else base_url+"/privacy"
            if policy_url.startswith("https://"):
                summary+=f"\n<a href='{esc(policy_url)}'>Maxfiylik haqida</a>"
            await send(target,summary,kb(("✅ Tasdiqlash","confirm"),("✏️ Tahrirlash","edit"),("Bekor qilish","cancel")))

    async def begin(target,kind,course_id=None):
        user=target.from_user
        store.upsert_user(user)
        prior=store.get_draft(user.id) or {}
        campaign=prior.get("campaign_code")
        draft={"user_id":user.id,"request_type":kind,"source":"campaign" if campaign else "telegram_direct","campaign_code":campaign,"course_id":course_id,"step":"branch" if course_id else "course" if kind=="course" else "name","key":secrets.token_urlsafe(20)}
        if kind=="callback": draft["step"]="name"
        store.put_draft(user.id,draft)
        await next_step(target,draft)

    @router.message(CommandStart())
    async def start(message:Message):
        store.upsert_user(message.from_user)
        store.clear_draft(message.from_user.id)
        payload=(message.text or "").partition(" ")[2].strip()
        if payload and re.fullmatch(r"[A-Za-z0-9_-]{1,64}",payload):
            campaign=store.one("SELECT code FROM campaigns WHERE code=? AND active=1",(payload,))
            if campaign:
                store.put_draft(message.from_user.id,{"user_id":message.from_user.id,"campaign_code":payload,"source":"campaign","step":"idle"})
        await home(message)

    @router.message(Command("admin"))
    async def admin(message:Message):
        staff=store.staff_by_telegram(message.from_user.id)
        if not staff:
            await message.answer("Admin kirishiga ruxsatingiz yo‘q."); return
        await message.answer(f"Panelga bir martalik kirish havolasi (10 daqiqa):\n{issue_login_link(store,staff,base_url)}",link_preview_options={"is_disabled":True})

    @router.callback_query()
    async def callbacks(call:CallbackQuery):
        data=call.data or ""
        if data=="home": await home(call); return
        if data=="courses": await content_list(call,"courses","Faol kurslar:","course"); return
        if data=="mentors": await content_list(call,"mentors","Mentorlar:","mentor"); return
        if data=="branches": await content_list(call,"branches","Filiallar:","branch"); return
        if data=="faq":
            rows=store.all("SELECT question,answer FROM faq WHERE active=1 AND TRIM(question)<>'' AND TRIM(answer)<>'' ORDER BY sort_order,id")
            parts=[]
            for r in rows:
                part=f"<b>{esc(r['question'][:180])}</b>\n{esc(r['answer'][:800])}"
                if sum(len(x) for x in parts)+len(part)>3600: break
                parts.append(part)
            await send(call,"\n\n".join(parts) or "Savol-javob hozircha e’lon qilinmagan.",kb(("📞 Menejer bilan bog‘lanish","callback"),("🏠 Bosh menyu","home"))); return
        if data=="contact":
            settings={r["key"]:r["value"] for r in store.all("SELECT key,value FROM settings WHERE key IN ('contact_text','contact_phone','contact_telegram','contact_hours')")}
            lines=[esc(settings.get("contact_text",""))]
            if settings.get("contact_phone"):
                p=esc(settings["contact_phone"]); lines.append(f"☎️ <a href='tel:{p}'>{p}</a>")
            if settings.get("contact_telegram"):
                handle=settings["contact_telegram"].lstrip("@")
                if re.fullmatch(r"[A-Za-z0-9_]{5,32}",handle): lines.append(f"Telegram: <a href='https://t.me/{handle}'>@{handle}</a>")
            if settings.get("contact_hours"): lines.append("Ish vaqti: "+esc(settings["contact_hours"]))
            await send(call,"\n".join(x for x in lines if x) or "Aloqa ma’lumoti hozircha kiritilmagan.",kb(("📞 Raqam qoldirish","callback"),("🏠 Bosh menyu","home"))); return
        if data=="mine":
            rows=store.all("SELECT id,request_type,course_name_snapshot,status,created_at FROM leads WHERE user_id=? AND anonymized_at IS NULL AND merged_into_id IS NULL ORDER BY id DESC LIMIT 20",(call.from_user.id,))
            body="\n".join(f"#{r['id']} · {esc(r['course_name_snapshot'] or 'Maslahat')} · {esc(r['status'])}" for r in rows) or "Sizda ariza yo‘q."
            await send(call,body,kb(("🗑 O‘chirish so‘rovi","delete_request"),("🏠 Bosh menyu","home"))); return
        if data=="delete_request":
            with store.connection() as db:
                ids=db.execute("SELECT id FROM leads WHERE user_id=? AND anonymized_at IS NULL",(call.from_user.id,)).fetchall()
                for row in ids:
                    prior=db.execute("SELECT 1 FROM lead_events WHERE lead_id=? AND kind='privacy_request'",(row["id"],)).fetchone()
                    if not prior: db.execute("INSERT INTO lead_events(lead_id,kind,new_value,created_at) VALUES(?,?,?,?)",(row["id"],"privacy_request","pending",utc_now()))
            await send(call,"Ma’lumotlarni o‘chirish so‘rovingiz qabul qilindi. Egasi uni ko‘rib chiqadi.",kb(("🏠 Bosh menyu","home"))); return
        if data.startswith("course:"): await show_course(call,int(data.split(":")[1])); return
        if data.startswith("mentor:"): await show_mentor(call,int(data.split(":")[1])); return
        if data.startswith("branch:"): await show_branch(call,int(data.split(":")[1])); return
        if data.startswith("apply"):
            course_id=int(data.split(":")[1]) if ":" in data else None
            if course_id and not store.one("SELECT id FROM courses WHERE id=? AND active=1",(course_id,)):
                await send(call,"Kurs endi faol emas.",kb(("📚 Kurslar","courses"))); return
            await begin(call,"course",course_id); return
        if data=="callback": await begin(call,"callback"); return
        if data=="cancel":
            store.clear_draft(call.from_user.id); await home(call); return
        if data.startswith("choosecourse:") or data.startswith("choosebranch:"):
            draft=store.get_draft(call.from_user.id)
            prefix,value=data.split(":")
            needed="course" if prefix=="choosecourse" else "branch"
            if not draft or draft.get("step")!=needed:
                await send(call,"Shakl muddati tugagan. Qaytadan boshlang.",kb(("🏠 Bosh menyu","home"))); return
            choice=int(value)
            if needed=="course":
                if not store.one("SELECT id FROM courses WHERE id=? AND active=1",(choice,)):
                    await send(call,"Kurs endi faol emas.",kb(("📚 Kurslar","courses"))); return
                draft["course_id"]=choice; draft["step"]="branch"
            else:
                if choice and not store.one("SELECT id FROM branches WHERE id=? AND active=1",(choice,)):
                    await send(call,"Filial endi faol emas.",kb(("📍 Filiallar","branches"))); return
                draft["branch_id"]=choice or None; draft["step"]="name"
            store.put_draft(call.from_user.id,draft); await next_step(call,draft); return
        if data in ("skip","edit","confirm"):
            draft=store.get_draft(call.from_user.id)
            if not draft:
                await send(call,"Shakl muddati tugagan. Qaytadan boshlang.",kb(("🏠 Bosh menyu","home"))); return
            if data=="confirm" and draft.get("step")=="done":
                await send(call,f"Arizangiz qabul qilingan: <b>#{draft['lead_id']}</b>.",kb(("🏠 Bosh menyu","home"))); return
            if data=="skip" and draft["step"] in ("preferred","note"):
                draft["step"]="note" if draft["step"]=="preferred" and draft["request_type"]=="course" else "confirm"
                store.put_draft(call.from_user.id,draft); await next_step(call,draft); return
            if data=="edit" and draft["step"]=="confirm":
                draft["step"]="name"; store.put_draft(call.from_user.id,draft); await next_step(call,draft); return
            if data=="confirm" and draft["step"]=="confirm":
                try:
                    notify=[r["telegram_id"] for r in store.all("SELECT telegram_id FROM staff WHERE active=1")]
                    lead_id,created=store.create_lead(draft,draft["key"],notify)
                except ValueError as exc:
                    await send(call,esc(exc),kb(("🏠 Bosh menyu","home"))); return
                store.put_draft(call.from_user.id,{"step":"done","lead_id":lead_id,"user_id":call.from_user.id,"campaign_code":draft.get("campaign_code")})
                await send(call,f"Arizangiz qabul qilindi: <b>#{lead_id}</b>. Menejer siz bilan bog‘lanadi." if created else f"Sizda shu kurs bo‘yicha ochiq ariza bor: <b>#{lead_id}</b>.",kb(("🏠 Bosh menyu","home")))
                return
        if data.startswith("claim:"):
            staff=store.staff_by_telegram(call.from_user.id)
            lead_id=int(data.split(":")[1])
            lead=store.one("SELECT * FROM leads WHERE id=?",(lead_id,))
            if not staff or not lead or (lead["assignee_id"] and lead["assignee_id"]!=staff["id"] and staff["role"]=="operator"):
                await call.answer("Ruxsat yo‘q",show_alert=True); return
            try: store.update_lead(lead_id,staff["id"],{"assignee_id":staff["id"]})
            except (ValueError,PermissionError): await call.answer("Biriktirish mumkin emas",show_alert=True); return
            await call.answer("Sizga biriktirildi",show_alert=True); return
        if data.startswith(("open:","call:","followup:")):
            action,raw_id=data.split(":",1)
            if not raw_id.isdigit():
                await call.answer("Tugma eskirgan",show_alert=True); return
            lead_id=int(raw_id)
            staff=store.staff_by_telegram(call.from_user.id)
            if not staff or not store.visible_lead(lead_id,staff):
                await call.answer("Ruxsat yo‘q",show_alert=True); return
            link=issue_login_link(store,staff,base_url,f"/admin/leads/{lead_id}")
            hint={"open":"Lid kartasi","call":"Qo‘ng‘iroq natijasini va izohni kartada yozing","followup":"Qayta aloqa vaqtini kartada belgilang"}[action]
            await send(call,f"{hint}:\n{esc(link)}"); return
        await send(call,"Bu tugma eskirgan. Bosh menyudan davom eting.",kb(("🏠 Bosh menyu","home")))

    @router.message()
    async def messages(message:Message):
        if message.text=="Bekor qilish":
            store.clear_draft(message.from_user.id); await home(message); return
        draft=store.get_draft(message.from_user.id)
        if not draft or draft.get("step") not in ("name","phone","preferred","note"):
            await home(message); return
        step=draft["step"]
        try:
            if step=="name": draft["name"]=clean_name(message.text or ""); draft["step"]="phone"
            elif step=="phone":
                if message.contact:
                    if message.contact.user_id != message.from_user.id:
                        raise ValueError("Faqat o‘z kontaktingizni ulashing yoki raqamni yozing.")
                    draft["phone_verified_by_contact"]=True
                    raw=message.contact.phone_number
                else:
                    raw=message.text or ""
                    draft["phone_verified_by_contact"]=False
                draft["phone_e164"]=phone(raw)
                draft["step"]="preferred" if draft["request_type"]=="course" else "note"
            elif step=="preferred":
                draft["preferred_contact_time"]=(message.text or "").strip()[:160]; draft["step"]="note"
            elif step=="note":
                draft["note"]=(message.text or "").strip()[:500]; draft["step"]="confirm"
        except ValueError as exc:
            await message.answer(str(exc)); return
        store.put_draft(message.from_user.id,draft)
        if step=="phone": await message.answer("Raqam olindi.",reply_markup=ReplyKeyboardRemove())
        await next_step(message,draft)

    return router
