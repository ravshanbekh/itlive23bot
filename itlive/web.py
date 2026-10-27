"""Small server-rendered CRM. Every POST checks session, role and CSRF."""
import csv
import hashlib
import hmac
import io
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from aiohttp import web
from jinja2 import Environment, select_autoescape

from .db import Store, STATUSES, utc_now


UZ=ZoneInfo("Asia/Tashkent")
env=Environment(autoescape=select_autoescape(default=True))
BASE=env.from_string("""<!doctype html><html lang='uz'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{{ title }} · ITLIVE CRM</title><style>
:root{font-family:system-ui,sans-serif;color:#18212f;background:#f3f6fa}*{box-sizing:border-box}body{margin:0}header{background:#102747;color:white;padding:1rem;display:flex;gap:1rem;align-items:center;flex-wrap:wrap}header a{color:white}main{max-width:1240px;margin:auto;padding:1rem}nav{display:flex;gap:1rem;flex-wrap:wrap}.card{background:white;border:1px solid #dce3ed;border-radius:12px;padding:1rem;margin:.75rem 0;box-shadow:0 1px 4px #0001}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:.7rem}.kanban{display:flex;overflow:auto;gap:1rem}.kanban>section{min-width:230px;max-width:260px}table{border-collapse:collapse;width:100%;background:white}th,td{border-bottom:1px solid #e1e5ed;padding:.7rem;text-align:left}input,select,textarea,button{font:inherit;padding:.55rem;border:1px solid #aab9cc;border-radius:6px;max-width:100%}input,textarea,select{width:100%}input[type=checkbox]{width:auto}textarea{min-height:5rem}button,.button{background:#1859a8;color:white;border:0;padding:.65rem 1rem;border-radius:6px;cursor:pointer;text-decoration:none;display:inline-block}label{display:block;margin:.55rem 0}small,.muted{color:#59677b}.error{background:#fff0ee;color:#9a2520;padding:.8rem}.ok{background:#e9f8ec;color:#16652a;padding:.8rem}form.inline{display:inline}a{color:#1456a0}.scroll{overflow:auto}@media(max-width:600px){table{font-size:.85rem}th,td{padding:.4rem}header{font-size:.9rem}}
</style></head><body><header><b>ITLIVE CRM</b>{% if staff %}<nav><a href='/admin'>Dashboard</a><a href='/admin/leads'>Lidlar</a>{% if staff.role != 'operator' %}<a href='/admin/content'>Kontent</a><a href='/admin/campaigns'>Kampaniyalar</a><a href='/admin/report'>Hisobot</a>{% endif %}{% if staff.role == 'owner' %}<a href='/admin/staff'>Xodimlar</a><a href='/admin/privacy'>Maxfiylik</a>{% endif %}</nav><form class='inline' method='post' action='/logout'><input type='hidden' name='csrf' value='{{ csrf }}'><button>Chiqish</button></form>{% endif %}</header><main>{% if error %}<p class='error'>{{ error }}</p>{% endif %}{% if notice %}<p class='ok'>{{ notice }}</p>{% endif %}<h1>{{ title }}</h1>{{ body|safe }}</main></body></html>""")


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def local_time(value):
    if not value: return "—"
    try: return datetime.fromisoformat(value).astimezone(UZ).strftime("%d.%m.%Y %H:%M")
    except ValueError: return value


def local_input(value):
    if not value: return ""
    return datetime.fromisoformat(value).astimezone(UZ).strftime("%Y-%m-%dT%H:%M")


def to_utc(value):
    if not value: return None
    return datetime.fromisoformat(value).replace(tzinfo=UZ).astimezone(timezone.utc).isoformat(timespec="seconds")


def page(title,body,staff=None,csrf="",error="",notice=""):
    return web.Response(text=BASE.render(title=title,body=body,staff=staff,csrf=csrf,error=error,notice=notice),content_type="text/html",headers={"Cache-Control":"no-store","X-Content-Type-Options":"nosniff","Content-Security-Policy":"default-src 'self'; style-src 'unsafe-inline'"})


def render(template,**kwargs):
    return env.from_string(template).render(**kwargs)


def get_staff(request):
    token=request.cookies.get("itlive_session","")
    if not token: return None,None
    store=request.app["store"]
    row=store.one("SELECT s.*,w.csrf_token,w.expires_at,w.revoked_at FROM web_sessions w JOIN staff s ON s.id=w.staff_id WHERE w.token_hash=?",(digest(token),))
    if not row or not row["active"] or row["revoked_at"] or row["expires_at"]<=utc_now(): return None,None
    return row,row["csrf_token"]


def require(request,role=None):
    staff,csrf=get_staff(request)
    if not staff: raise web.HTTPFound("/")
    if role and staff["role"] not in role: raise web.HTTPForbidden(text="Ruxsat yo‘q")
    return staff,csrf


async def form_post(request,csrf):
    data=await request.post()
    if not hmac.compare_digest(str(data.get("csrf","")),csrf):
        raise web.HTTPForbidden(text="CSRF tekshiruvi xato")
    return data


def qfilters(request):
    return {k:request.query.get(k,"") for k in ("q","status","course","branch","source","assignee","from","to","due","sort","unanswered")}


def filter_form(store,filters):
    courses=store.all("SELECT id,name FROM courses ORDER BY name")
    branches=store.all("SELECT id,name FROM branches ORDER BY name")
    options=lambda rows,key: "".join(render("<option value='{{ r.id }}' {% if v == r.id|string %}selected{% endif %}>{{ r.name }}</option>",r=r,v=filters[key]) for r in rows)
    return render("""<form class='card grid' method='get' action='/admin/leads'><label>Qidiruv<input name='q' value='{{ f.q }}'></label><label>Status<select name='status'><option value=''>Barchasi</option>{% for s in statuses %}<option {% if f.status == s %}selected{% endif %}>{{ s }}</option>{% endfor %}</select></label><label>Kurs<select name='course'><option value=''>Barchasi</option>{{ course_options|safe }}</select></label><label>Filial<select name='branch'><option value=''>Barchasi</option>{{ branch_options|safe }}</select></label><label>Manba<input name='source' value='{{ f.source }}'></label><label>Mas’ul ID<input name='assignee' value='{{ f.assignee }}'></label><label>Dan<input type='date' name='from' value='{{ f['from'] }}'></label><label>Gacha<input type='date' name='to' value='{{ f.to }}'></label><label>Vazifa<select name='due'><option value=''>Hammasi</option><option value='overdue' {% if f.due == 'overdue' %}selected{% endif %}>Muddati o‘tgan</option></select></label><label>Saralash<select name='sort'><option value=''>Yangi</option><option value='old' {% if f.sort == 'old' %}selected{% endif %}>Eski</option><option value='unanswered' {% if f.sort == 'unanswered' %}selected{% endif %}>Javobsiz</option><option value='due' {% if f.sort == 'due' %}selected{% endif %}>Yaqin qayta aloqa</option></select></label><button>Filtrlash</button></form>""",f=filters,statuses=STATUSES,course_options=options(courses,"course"),branch_options=options(branches,"branch"))


async def root(request):
    staff,_=get_staff(request)
    raise web.HTTPFound("/admin" if staff else "/login")


async def login(request):
    return page("Kirish","<p>Panelga kirish uchun botga <b>/admin</b> yuboring va bir martalik havolani oching.</p>")


async def public_privacy(request):
    body="<div class='card'><p>Ariza yuborsangiz, ismingiz, telefoningiz, tanlagan kurs/filialingiz va ixtiyoriy izohingiz ITLIVE qabul xodimlariga bog‘lanish uchun saqlanadi.</p><p>Arizalaringizni botdagi «Ma’lumotlarim» bo‘limida ko‘rishingiz va o‘chirish so‘rovini yuborishingiz mumkin. So‘rovni ITLIVE egasi panelda ko‘rib chiqadi.</p><p>Saqlash muddati va rasmiy aloqa ma’lumotini ITLIVE tasdiqlashi kerak.</p></div>"
    return page("Maxfiylik haqida",body)


async def login_token(request):
    token=request.match_info["token"]
    store=request.app["store"]
    now=utc_now()
    ip_hash=digest((request.remote or "unknown")+request.app["config"].session_secret)
    attempt=store.one("SELECT count,window_start FROM login_attempts WHERE ip_hash=?",(ip_hash,))
    if attempt and attempt["count"]>=30 and attempt["window_start"]>(datetime.now(timezone.utc)-timedelta(minutes=15)).isoformat():
        raise web.HTTPTooManyRequests(text="Keyinroq qayta urinib ko‘ring")
    valid=store.one("SELECT t.staff_id FROM login_tokens t JOIN staff s ON s.id=t.staff_id WHERE t.token_hash=? AND t.used_at IS NULL AND t.expires_at>? AND s.active=1",(digest(token),now))
    if not valid:
        with store.connection() as db:
            window_start=(datetime.now(timezone.utc)-timedelta(minutes=15)).isoformat()
            db.execute("INSERT INTO login_attempts(ip_hash,count,window_start) VALUES(?,1,?) ON CONFLICT(ip_hash) DO UPDATE SET count=CASE WHEN window_start<? THEN 1 ELSE count+1 END,window_start=CASE WHEN window_start<? THEN excluded.window_start ELSE window_start END",(ip_hash,now,window_start,window_start))
        raise web.HTTPForbidden(text="Havola muddati tugagan yoki ishlatilgan")
    if request.method=="GET":
        next_path=request.query.get("next","/admin")
        return page("Kirishni tasdiqlash",render("<p>Bir martalik havolani ishlatib panelga kiring.</p><form method='post' action='?next={{ next_path|urlencode }}'><button>Panelga kirish</button></form>",next_path=next_path))
    with store.connection() as db:
        db.execute("BEGIN IMMEDIATE")
        row=db.execute("SELECT t.staff_id FROM login_tokens t JOIN staff s ON s.id=t.staff_id WHERE t.token_hash=? AND t.used_at IS NULL AND t.expires_at>? AND s.active=1",(digest(token),now)).fetchone()
        if not row: raise web.HTTPForbidden(text="Havola muddati tugagan yoki ishlatilgan")
        db.execute("UPDATE login_tokens SET used_at=? WHERE token_hash=?",(now,digest(token)))
        session=secrets.token_urlsafe(32); csrf=secrets.token_urlsafe(32)
        expires=(datetime.now(timezone.utc)+timedelta(hours=8)).isoformat()
        db.execute("INSERT INTO web_sessions VALUES(?,?,?,?,NULL)",(digest(session),row["staff_id"],csrf,expires))
    next_path=request.query.get("next","/admin")
    import re
    if next_path!="/admin" and not re.fullmatch(r"/admin/leads/\d+",next_path): next_path="/admin"
    response=web.HTTPFound(next_path)
    response.set_cookie("itlive_session",session,httponly=True,secure=not request.app["config"].dev_mode,samesite="Strict",max_age=8*3600,path="/")
    raise response


async def logout(request):
    staff,csrf=require(request)
    await form_post(request,csrf)
    token=request.cookies.get("itlive_session","")
    with request.app["store"].connection() as db:
        db.execute("UPDATE web_sessions SET revoked_at=? WHERE token_hash=?",(utc_now(),digest(token)))
    response=web.HTTPFound("/login"); response.del_cookie("itlive_session",path="/"); raise response


async def dashboard(request):
    staff,csrf=require(request)
    store=request.app["store"]
    f=qfilters(request)
    today=datetime.now(UZ).date().isoformat()
    base={"from":today,"to":today}
    counts={}
    scope={k:v for k,v in f.items() if k in ("from","to","branch") and v}
    for label,filters in (("Bugun",{**scope,**base}),("Yangi",{"status":"Yangi mijoz"}),("Javobsiz",{"unanswered":"1"}),("Qayta aloqa muddati o‘tgan",{"due":"overdue"}),("Uchrashuv",{"status":"Uchrashuv belgilandi"}),("Sotildi",{"status":"Sotildi"}),("Sotilmadi",{"status":"Sotilmadi"})):
        _,count=store.list_leads(staff,{**scope,**filters},1,0)
        counts[label]=count
    links={"Bugun":urlencode({**scope,**base}),"Yangi":urlencode({**scope,"status":"Yangi mijoz"}),"Javobsiz":urlencode({**scope,"unanswered":"1"}),"Qayta aloqa muddati o‘tgan":urlencode({**scope,"due":"overdue"}),"Uchrashuv":urlencode({**scope,"status":"Uchrashuv belgilandi"}),"Sotildi":urlencode({**scope,"status":"Sotildi"}),"Sotilmadi":urlencode({**scope,"status":"Sotilmadi"})}
    branches=store.all("SELECT id,name FROM branches ORDER BY name")
    body=render("<form class='card grid' method='get'><label>Dan<input type='date' name='from' value='{{ f['from'] }}'></label><label>Gacha<input type='date' name='to' value='{{ f.to }}'></label><label>Filial<select name='branch'><option value=''>Barchasi</option>{% for b in branches %}<option value='{{ b.id }}' {% if f.branch == b.id|string %}selected{% endif %}>{{ b.name }}</option>{% endfor %}</select></label><button>Ko‘rsatish</button></form><div class='grid'>{% for label,n in counts.items() %}<a class='card' href='/admin/leads?{{ links[label] }}'><h2>{{ n }}</h2>{{ label }}</a>{% endfor %}</div><p class='muted'>Vaqt zonasi: Asia/Tashkent. Sotildi ko‘rsatkichi tushum emas.</p>",counts=counts,links=links,f=f,branches=branches)
    return page("Dashboard",body,staff,csrf)


async def leads(request):
    staff,csrf=require(request)
    store=request.app["store"]; f=qfilters(request)
    try: page_no=max(1,int(request.query.get("page","1")))
    except ValueError: page_no=1
    rows,count=store.list_leads(staff,f,50,(page_no-1)*50)
    view=request.query.get("view","table")
    body=filter_form(store,f)+render("<p>{{ count }} ariza · <a href='?{{ query }}&view=table'>Jadval</a> · <a href='?{{ query }}&view=kanban'>Kanban</a>{% if staff.role != 'operator' %} · <a href='/admin/leads/new'>Qo‘lda qo‘shish</a> · <a href='/admin/export?{{ query }}'>CSV</a>{% endif %}</p>",count=count,query=urlencode({k:v for k,v in f.items() if v}),staff=staff)
    if view=="kanban":
        body+=render("<div class='kanban'>{% for status in statuses %}<section><h3>{{ status }}</h3>{% for r in rows if r.status == status %}<div class='card'><a href='/admin/leads/{{ r.id }}'>#{{ r.id }} · {{ r.name }}</a><br><a href='tel:{{ r.phone_e164 }}'>{{ r.phone_e164 }}</a><br>{{ r.course_name_snapshot or 'Maslahat' }}<br>{{ r.branch_name_snapshot or '' }}<br>{{ r.source }}<br>{{ r.created_at|local }}</div>{% endfor %}</section>{% endfor %}</div>",rows=rows,statuses=STATUSES)
    else:
        body+=render("<div class='scroll'><table><tr><th>ID</th><th>Ism</th><th>Telefon</th><th>Kurs</th><th>Filial</th><th>Status</th><th>Manba</th><th>Mas’ul</th><th>So‘nggi aloqa</th><th>Keyingi ish</th></tr>{% for r in rows %}<tr><td><a href='/admin/leads/{{ r.id }}'>#{{ r.id }}</a></td><td>{{ r.name }}</td><td><a href='tel:{{ r.phone_e164 }}'>{{ r.phone_e164 }}</a></td><td>{{ r.course_name_snapshot or '' }}</td><td>{{ r.branch_name_snapshot or '' }}</td><td>{{ r.status }}</td><td>{{ r.source }}</td><td>{{ r.assignee_id or '' }}</td><td>{{ r.first_contact_at|local }}</td><td>{{ r.next_action_at|local }}</td></tr>{% endfor %}</table></div>",rows=rows)
    body+=render("<p>{% if page_no > 1 %}<a href='?{{ query }}&page={{ page_no-1 }}'>◀ Oldingi</a>{% endif %} {% if page_no*50 < count %}<a href='?{{ query }}&page={{ page_no+1 }}'>Keyingi ▶</a>{% endif %}</p>",page_no=page_no,count=count,query=urlencode({**{k:v for k,v in f.items() if v},"view":view}))
    return page("Lidlar",body,staff,csrf)


async def lead_detail(request):
    staff,csrf=require(request); store=request.app["store"]
    lead=store.visible_lead(int(request.match_info["id"]),staff)
    if not lead: raise web.HTTPNotFound()
    events=store.all("SELECT e.*,s.name AS actor FROM lead_events e LEFT JOIN staff s ON s.id=e.actor_staff_id WHERE e.lead_id=? ORDER BY e.id DESC",(lead["id"],))
    staff_rows=store.all("SELECT id,name,role FROM staff WHERE active=1 ORDER BY name") if staff["role"]!="operator" else []
    courses=store.all("SELECT id,name FROM courses ORDER BY name")
    branches=store.all("SELECT id,name FROM branches ORDER BY name")
    body=render("""<div class='card'><p><b>Telefon:</b> <a href='tel:{{ l.phone_e164 }}'>{{ l.phone_e164 }}</a> {% if l.phone_verified_by_contact %}(o‘z kontakti){% else %}(qo‘lda){% endif %}</p><p><b>Kurs:</b> {{ l.course_name_snapshot or 'Maslahat' }} · <b>Filial:</b> {{ l.branch_name_snapshot or 'Farqi yo‘q' }}</p><p><b>Telegram:</b> {% if l.user_id %}<a href='tg://user?id={{ l.user_id }}'>{{ l.user_id }}</a>{% else %}—{% endif %} · <b>Manba:</b> {{ l.source }} {{ l.campaign_code or '' }}</p><p><b>Yaratilgan:</b> {{ l.created_at|local }} · <b>Birinchi aloqa:</b> {{ l.first_contact_at|local }} · <b>Yopilgan:</b> {{ l.closed_at|local }}</p></div>
    <form class='card' method='post'><input type='hidden' name='csrf' value='{{ csrf }}'><div class='grid'><label>Ism<input name='name' value='{{ l.name }}'></label><label>Telefon<input name='phone_e164' value='{{ l.phone_e164 }}'></label><label>Status<select name='status'>{% for s in statuses %}<option {% if l.status == s %}selected{% endif %}>{{ s }}</option>{% endfor %}</select></label>{% if staff.role != 'operator' %}<label>Mas’ul<select name='assignee_id'><option value=''>Tanlanmagan</option>{% for s in staff_rows %}<option value='{{ s.id }}' {% if l.assignee_id == s.id %}selected{% endif %}>{{ s.name }} ({{ s.role }})</option>{% endfor %}</select></label>{% endif %}<label>Kurs<select name='course_id'><option value=''>Yo‘q</option>{% for c in courses %}<option value='{{ c.id }}' {% if l.course_id == c.id %}selected{% endif %}>{{ c.name }}</option>{% endfor %}</select></label><label>Filial<select name='branch_id'><option value=''>Farqi yo‘q</option>{% for b in branches %}<option value='{{ b.id }}' {% if l.branch_id == b.id %}selected{% endif %}>{{ b.name }}</option>{% endfor %}</select></label><label>Qayta aloqa vaqti<input type='datetime-local' name='next_action_at' value='{{ l.next_action_at|localinput }}'></label><label>Uchrashuv vaqti<input type='datetime-local' name='meeting_at' value='{{ l.meeting_at|localinput }}'></label><label>Uchrashuv formati<input name='meeting_format' value='{{ l.meeting_format or '' }}'></label><label>Sotilmadi sababi<select name='lost_reason'><option value=''>Tanlang</option>{% for reason in reasons %}<option {% if l.lost_reason == reason %}selected{% endif %}>{{ reason }}</option>{% endfor %}</select></label></div><label>Izoh / qo‘ng‘iroq natijasi<textarea name='note'>{{ l.note or '' }}</textarea></label><button>Saqlash</button></form>
    {% if staff.role != 'operator' %}<form class='card' method='post' action='/admin/leads/{{ l.id }}/merge'><input type='hidden' name='csrf' value='{{ csrf }}'><label>Birlashtiriladigan dublikat ID<input name='source_id' type='number' required></label><button>Birlashtirish</button><small>Telefon bir xil bo‘lishi kerak. Manba ariza tarixda saqlanadi.</small></form>{% endif %}<h2>Tarix</h2><div class='card'>{% for e in events %}<p><small>{{ e.created_at|local }} · {{ e.actor or 'Bot' }}</small><br><b>{{ e.kind }}</b>: {{ e.old_value or '—' }} → {{ e.new_value or '—' }} {% if e.note %}· {{ e.note }}{% endif %}</p>{% endfor %}</div>""",l=lead,csrf=csrf,statuses=STATUSES,staff=staff,staff_rows=staff_rows,courses=courses,branches=branches,events=events,reasons=("narx","vaqt","qiziqmadi","boshqa","noma’lum"))
    return page(f"Ariza #{lead['id']}",body,staff,csrf,error=request.query.get("error",""),notice=request.query.get("notice",""))


async def lead_save(request):
    staff,csrf=require(request); store=request.app["store"]
    lead_id=int(request.match_info["id"])
    if not store.visible_lead(lead_id,staff): raise web.HTTPNotFound()
    data=await form_post(request,csrf)
    from .bot import phone, clean_name
    try:
        changes={"name":clean_name(str(data.get("name",""))),"phone_e164":phone(str(data.get("phone_e164",""))),"status":str(data.get("status","")),"course_id":int(data["course_id"]) if data.get("course_id") else None,"branch_id":int(data["branch_id"]) if data.get("branch_id") else None,"next_action_at":to_utc(data.get("next_action_at")),"meeting_at":to_utc(data.get("meeting_at")),"meeting_format":str(data.get("meeting_format",""))[:80] or None,"note":str(data.get("note",""))[:1000] or None,"lost_reason":str(data.get("lost_reason","")) or None}
        if staff["role"]!="operator": changes["assignee_id"]=int(data["assignee_id"]) if data.get("assignee_id") else None
        store.update_lead(lead_id,staff["id"],changes,note=changes["note"])
        raise web.HTTPFound(f"/admin/leads/{lead_id}?notice=Saqlangan")
    except (ValueError,PermissionError) as exc:
        raise web.HTTPFound(f"/admin/leads/{lead_id}?"+urlencode({"error":str(exc)}))


async def new_lead(request):
    staff,csrf=require(request,("admin","owner"))
    store=request.app["store"]
    body=render("""<form class='card' method='post'><input type='hidden' name='csrf' value='{{ csrf }}'><label>Ism<input name='name' required></label><label>Telefon<input name='phone' required placeholder='+998901234567'></label><label>Kurs<select name='course_id'><option value=''>Maslahat</option>{% for c in courses %}<option value='{{ c.id }}'>{{ c.name }}</option>{% endfor %}</select></label><label>Filial<select name='branch_id'><option value=''>Farqi yo‘q</option>{% for b in branches %}<option value='{{ b.id }}'>{{ b.name }}</option>{% endfor %}</select></label><label>Izoh<textarea name='note'></textarea></label><button>Ariza qo‘shish</button></form>""",csrf=csrf,courses=store.all("SELECT id,name FROM courses WHERE active=1"),branches=store.all("SELECT id,name FROM branches WHERE active=1"))
    return page("Qo‘lda ariza",body,staff,csrf,error=request.query.get("error",""))


async def merge_leads(request):
    staff,csrf=require(request,("admin","owner")); data=await form_post(request,csrf)
    target_id=int(request.match_info["id"])
    try:
        request.app["store"].merge_leads(target_id,int(data.get("source_id","")),staff["id"])
        raise web.HTTPFound(f"/admin/leads/{target_id}?notice=Birlashtirildi")
    except (ValueError,PermissionError) as exc:
        raise web.HTTPFound(f"/admin/leads/{target_id}?"+urlencode({"error":str(exc)}))


async def new_lead_save(request):
    staff,csrf=require(request,("admin","owner")); data=await form_post(request,csrf)
    from .bot import phone,clean_name
    try:
        course=int(data["course_id"]) if data.get("course_id") else None
        lead={"request_type":"course" if course else "callback","name":clean_name(data.get("name","")),"phone_e164":phone(data.get("phone","")),"course_id":course,"branch_id":int(data["branch_id"]) if data.get("branch_id") else None,"source":"manual","note":str(data.get("note",""))[:500]}
        lead_id,_=request.app["store"].create_lead(lead,secrets.token_urlsafe(20),[])
        raise web.HTTPFound(f"/admin/leads/{lead_id}")
    except ValueError as exc: raise web.HTTPFound("/admin/leads/new?"+urlencode({"error":str(exc)}))


async def export(request):
    staff,csrf=require(request,("admin","owner")); store=request.app["store"]
    rows,_=store.list_leads(staff,qfilters(request),1000000,0)
    buf=io.StringIO(); writer=csv.writer(buf); writer.writerow(("ID","Ism","Telefon","Kurs","Filial","Status","Manba","Mas’ul ID","Yaratilgan UTC"))
    def csv_safe(value):
        text=str(value or "")
        return "'"+text if text.lstrip().startswith(("=","+","-","@","\t","\r")) else text
    for row in rows:
        writer.writerow((row["id"],csv_safe(row["name"]),"\t"+row["phone_e164"],csv_safe(row["course_name_snapshot"]),csv_safe(row["branch_name_snapshot"]),row["status"],csv_safe(row["source"]),row["assignee_id"],row["created_at"]))
    with store.connection() as db:
        db.execute("INSERT INTO admin_audit(actor_staff_id,action,detail,created_at) VALUES(?,?,?,?)",(staff["id"],"export",str(len(rows)),utc_now()))
    return web.Response(body=("\ufeff"+buf.getvalue()).encode("utf-8"),content_type="text/csv",headers={"Content-Disposition":"attachment; filename=itlive-leads.csv","Cache-Control":"no-store"})


async def report(request):
    staff,csrf=require(request,("admin","owner")); store=request.app["store"]
    f=qfilters(request); rows,_=store.list_leads(staff,f,1000000,0)
    group=request.query.get("group","course")
    column={"course":"course_name_snapshot","branch":"branch_name_snapshot","source":"source","operator":"assignee_id"}.get(group,"course_name_snapshot")
    totals={}
    for row in rows:
        key=str(row[column] or "—")
        bucket=totals.setdefault(key,{"ariza":0,"boglanildi":0,"uchrashuv":0,"sotildi":0})
        bucket["ariza"]+=1
        if row["first_contact_at"]: bucket["boglanildi"]+=1
        if row["meeting_at"]: bucket["uchrashuv"]+=1
        if row["status"]=="Sotildi": bucket["sotildi"]+=1
    if request.query.get("format")=="csv":
        buf=io.StringIO(); writer=csv.writer(buf)
        writer.writerow((group,"Ariza","Bog‘lanildi","Uchrashuv","Sotildi"))
        for label,t in totals.items(): writer.writerow((("'"+label) if label.lstrip().startswith(("=","+","-","@","\t","\r")) else label,t["ariza"],t["boglanildi"],t["uchrashuv"],t["sotildi"]))
        with store.connection() as db:
            db.execute("INSERT INTO admin_audit(actor_staff_id,action,detail,created_at) VALUES(?,?,?,?)",(staff["id"],"report_export",group,utc_now()))
        return web.Response(body=("\ufeff"+buf.getvalue()).encode("utf-8"),content_type="text/csv",headers={"Content-Disposition":"attachment; filename=itlive-report.csv","Cache-Control":"no-store"})
    branches=store.all("SELECT id,name FROM branches ORDER BY name")
    body=render("""<form class='card' method='get'><label>Kesim<select name='group'>{% for g in groups %}<option {% if group == g %}selected{% endif %}>{{ g }}</option>{% endfor %}</select></label><label>Filial<select name='branch'><option value=''>Barchasi</option>{% for b in branches %}<option value='{{ b.id }}' {% if f.branch == b.id|string %}selected{% endif %}>{{ b.name }}</option>{% endfor %}</select></label><label>Dan<input type='date' name='from' value='{{ f['from'] }}'></label><label>Gacha<input type='date' name='to' value='{{ f.to }}'></label><button>Ko‘rsatish</button></form><p><a href='?{{ export_query }}'>Hisobot CSV</a></p><table><tr><th>{{ group }}</th><th>Ariza</th><th>Bog‘lanildi</th><th>Uchrashuv</th><th>Sotildi</th></tr>{% for label,t in totals.items() %}<tr><td>{{ label }}</td><td>{{ t.ariza }}</td><td>{{ t.boglanildi }}</td><td>{{ t.uchrashuv }}</td><td>{{ t.sotildi }}</td></tr>{% endfor %}</table><p class='muted'>Sotildi tushumni anglatmaydi.</p>""",groups=("course","branch","source","operator"),group=group,f=f,totals=totals,branches=branches,export_query=urlencode({**{k:v for k,v in f.items() if v},"group":group,"format":"csv"}))
    return page("Hisobot",body,staff,csrf)


CONTENT={
    "courses":("Kurslar",("name","short_description","description","audience","duration","format","syllabus","price","show_price","active","sort_order")),
    "mentors":("Mentorlar",("name","specialty","bio","photo_file_id","active","sort_order")),
    "branches":("Filiallar",("name","address","landmark","hours","phone","latitude","longitude","active","sort_order")),
    "faq":("Savol-javob",("question","answer","active","sort_order")),
}


async def content(request):
    staff,csrf=require(request,("admin","owner")); store=request.app["store"]
    table=request.query.get("table","courses")
    if table not in CONTENT: raise web.HTTPNotFound()
    rows=store.all(f"SELECT * FROM {table} ORDER BY sort_order,id")
    title,fields=CONTENT[table]
    settings=store.all("SELECT key,value FROM settings WHERE key IN ('contact_text','contact_phone','contact_telegram','contact_hours','privacy_url')")
    body=render("""<nav>{% for key,value in content.items() %}<a href='/admin/content?table={{ key }}'>{{ value[0] }}</a>{% endfor %}</nav><form class='card' method='post' action='/admin/settings'><input type='hidden' name='csrf' value='{{ csrf }}'><label>Aloqa matni<textarea name='contact_text'>{{ settings.contact_text or '' }}</textarea></label><label>Telefon<input name='contact_phone' value='{{ settings.contact_phone or '' }}'></label><label>Telegram username<input name='contact_telegram' value='{{ settings.contact_telegram or '' }}'></label><label>Ish vaqti<input name='contact_hours' value='{{ settings.contact_hours or '' }}'></label><label>Rasmiy maxfiylik siyosati HTTPS havolasi<input name='privacy_url' value='{{ settings.privacy_url or '' }}'></label><button>Sozlamalarni saqlash</button></form><p><a class='button' href='/admin/content/{{ table }}/new'>+ Yangi {{ title }}</a></p><table><tr><th>ID</th><th>Nomi/savol</th><th>Faol</th><th></th></tr>{% for r in rows %}<tr><td>{{ r.id }}</td><td>{{ r.name if table != 'faq' else r.question }}</td><td>{{ 'Ha' if r.active else 'Yo‘q' }}</td><td><a href='/admin/content/{{ table }}/{{ r.id }}'>Tahrirlash</a></td></tr>{% endfor %}</table>""",content=CONTENT,settings={r["key"]:r["value"] for r in settings},csrf=csrf,title=title,table=table,rows=rows)
    return page(title,body,staff,csrf,notice=request.query.get("notice",""))


async def content_edit(request):
    staff,csrf=require(request,("admin","owner")); store=request.app["store"]
    table=request.match_info["table"]
    if table not in CONTENT: raise web.HTTPNotFound()
    row=None if request.match_info["id"]=="new" else store.one(f"SELECT * FROM {table} WHERE id=?",(int(request.match_info["id"]),))
    if request.match_info["id"]!="new" and not row: raise web.HTTPNotFound()
    _,fields=CONTENT[table]
    mentors=store.all("SELECT id,name FROM mentors ORDER BY name") if table=="courses" else []
    branches=store.all("SELECT id,name FROM branches ORDER BY name") if table=="courses" else []
    selected_mentors={r["mentor_id"] for r in store.all("SELECT mentor_id FROM course_mentors WHERE course_id=?",(row["id"],))} if table=="courses" and row else set()
    selected_branches={r["branch_id"] for r in store.all("SELECT branch_id FROM course_branches WHERE course_id=?",(row["id"],))} if table=="courses" and row else set()
    body=render("""<form class='card' method='post'><input type='hidden' name='csrf' value='{{ csrf }}'>{% for field in fields %}<label>{{ field }}{% if field in ('active','show_price') %}<select name='{{ field }}'><option value='1' {% if not row or row[field] %}selected{% endif %}>Ha</option><option value='0' {% if row and not row[field] %}selected{% endif %}>Yo‘q</option></select>{% elif field in ('description','bio','answer','syllabus') %}<textarea name='{{ field }}'>{{ row[field] if row else '' }}</textarea>{% else %}<input name='{{ field }}' value='{{ row[field] if row and row[field] is not none else '' }}'>{% endif %}</label>{% endfor %}{% if table == 'courses' %}<fieldset><legend>Mentorlar</legend>{% for m in mentors %}<label><input type='checkbox' name='mentor_ids' value='{{ m.id }}' {% if m.id in selected_mentors %}checked{% endif %}>{{ m.name }}</label>{% endfor %}</fieldset><fieldset><legend>Filiallar</legend>{% for b in branches %}<label><input type='checkbox' name='branch_ids' value='{{ b.id }}' {% if b.id in selected_branches %}checked{% endif %}>{{ b.name }}</label>{% endfor %}</fieldset>{% endif %}<button>Saqlash</button></form>""",fields=fields,row=row,table=table,mentors=mentors,branches=branches,selected_mentors=selected_mentors,selected_branches=selected_branches)
    return page("Kontent tahriri",body,staff,csrf,error=request.query.get("error",""))


async def content_save(request):
    staff,csrf=require(request,("admin","owner")); store=request.app["store"]
    table=request.match_info["table"]
    if table not in CONTENT: raise web.HTTPNotFound()
    data=await form_post(request,csrf)
    _,fields=CONTENT[table]
    values={field:str(data.get(field,"")).strip()[:4000] for field in fields}
    try:
        for field in ("active","show_price","sort_order"):
            if field in values: values[field]=int(values[field] or 0)
        for field in ("latitude","longitude"):
            if field in values: values[field]=float(values[field]) if values[field] else None
        if not (values.get("name") or values.get("question")): raise ValueError("Nom yoki savol kerak")
        with store.connection() as db:
            if request.match_info["id"]=="new":
                cur=db.execute(f"INSERT INTO {table}({','.join(fields)}) VALUES({','.join('?' for _ in fields)})",tuple(values.values()))
                record_id=cur.lastrowid
            else:
                record_id=int(request.match_info["id"])
                db.execute(f"UPDATE {table} SET "+",".join(f"{f}=?" for f in fields)+" WHERE id=?",(*values.values(),record_id))
            if table=="courses":
                for relation,col,key in (("course_mentors","mentor_id","mentor_ids"),("course_branches","branch_id","branch_ids")):
                    db.execute(f"DELETE FROM {relation} WHERE course_id=?",(record_id,))
                    for value in data.getall(key,[]):
                        db.execute(f"INSERT INTO {relation}(course_id,{col}) VALUES(?,?)",(record_id,int(value)))
            db.execute("INSERT INTO admin_audit(actor_staff_id,action,detail,created_at) VALUES(?,?,?,?)",(staff["id"],"content:"+table,str(record_id),utc_now()))
        raise web.HTTPFound("/admin/content?"+urlencode({"table":table,"notice":"Saqlangan"}))
    except ValueError as exc:
        raise web.HTTPFound(f"/admin/content/{table}/{request.match_info['id']}?"+urlencode({"error":str(exc)}))


async def settings_save(request):
    staff,csrf=require(request,("admin","owner")); data=await form_post(request,csrf)
    import re
    from .bot import phone
    privacy=str(data.get("privacy_url","")).strip()
    if privacy and not privacy.startswith("https://"): raise web.HTTPBadRequest(text="Maxfiylik havolasi HTTPS bo‘lsin")
    contact_phone=str(data.get("contact_phone","")).strip()
    if contact_phone:
        try: contact_phone=phone(contact_phone)
        except ValueError as exc: raise web.HTTPBadRequest(text=str(exc))
    contact_telegram=str(data.get("contact_telegram","")).strip().lstrip("@")
    if contact_telegram and not re.fullmatch(r"[A-Za-z0-9_]{5,32}",contact_telegram): raise web.HTTPBadRequest(text="Telegram username xato")
    with request.app["store"].connection() as db:
        values={key:str(data.get(key,""))[:4000] for key in ("contact_text","contact_hours","privacy_url")}
        values.update({"contact_phone":contact_phone,"contact_telegram":contact_telegram})
        for key,value in values.items():
            db.execute("INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(key,value))
        db.execute("INSERT INTO admin_audit(actor_staff_id,action,created_at) VALUES(?,?,?)",(staff["id"],"settings",utc_now()))
    raise web.HTTPFound("/admin/content?notice=Saqlangan")


async def staff_page(request):
    staff,csrf=require(request,("owner",)); rows=request.app["store"].all("SELECT * FROM staff ORDER BY id")
    body=render("""<form class='card' method='post'><input type='hidden' name='csrf' value='{{ csrf }}'><label>Telegram ID<input name='telegram_id' type='number' required></label><label>Ism<input name='name' required></label><label>Rol<select name='role'><option>operator</option><option>admin</option></select></label><button>Qo‘shish / yangilash</button></form><table><tr><th>ID</th><th>Ism</th><th>Telegram ID</th><th>Rol</th><th>Faol</th><th></th></tr>{% for s in rows %}<tr><td>{{ s.id }}</td><td>{{ s.name }}</td><td>{{ s.telegram_id }}</td><td>{{ s.role }}</td><td>{{ s.active }}</td><td>{% if s.role != 'owner' %}<form method='post' action='/admin/staff/{{ s.id }}/toggle'><input type='hidden' name='csrf' value='{{ csrf }}'><button>{{ 'O‘chirish' if s.active else 'Yoqish' }}</button></form>{% endif %}</td></tr>{% endfor %}</table>""",rows=rows,csrf=csrf)
    return page("Xodimlar",body,staff,csrf,error=request.query.get("error",""))


async def campaigns(request):
    staff,csrf=require(request,("admin","owner")); rows=request.app["store"].all("SELECT * FROM campaigns ORDER BY code")
    body=render("""<form class='card' method='post'><input type='hidden' name='csrf' value='{{ csrf }}'><label>Kod (Telegram /start parametri)<input name='code' required pattern='[A-Za-z0-9_-]{1,64}'></label><label>Nomi<input name='title' required></label><button>Qo‘shish / yangilash</button></form><table><tr><th>Kod</th><th>Nomi</th><th>Faol</th><th></th></tr>{% for c in rows %}<tr><td>{{ c.code }}</td><td>{{ c.title }}</td><td>{{ 'Ha' if c.active else 'Yo‘q' }}</td><td><form method='post' action='/admin/campaigns/{{ c.code }}/toggle'><input type='hidden' name='csrf' value='{{ csrf }}'><button>{{ 'O‘chirish' if c.active else 'Yoqish' }}</button></form></td></tr>{% endfor %}</table>""",rows=rows,csrf=csrf)
    return page("Kampaniyalar",body,staff,csrf,error=request.query.get("error",""))


async def campaign_save(request):
    staff,csrf=require(request,("admin","owner")); data=await form_post(request,csrf)
    import re
    code=str(data.get("code","")); title=str(data.get("title","")).strip()[:200]
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}",code) or not title:
        raise web.HTTPFound("/admin/campaigns?error=Kod+yoki+nom+xato")
    with request.app["store"].connection() as db:
        db.execute("INSERT INTO campaigns VALUES(?,?,1) ON CONFLICT(code) DO UPDATE SET title=excluded.title,active=1",(code,title))
        db.execute("INSERT INTO admin_audit(actor_staff_id,action,detail,created_at) VALUES(?,?,?,?)",(staff["id"],"campaign",code,utc_now()))
    raise web.HTTPFound("/admin/campaigns")


async def campaign_toggle(request):
    staff,csrf=require(request,("admin","owner")); await form_post(request,csrf)
    code=request.match_info["code"]
    with request.app["store"].connection() as db:
        db.execute("UPDATE campaigns SET active=1-active WHERE code=?",(code,))
        db.execute("INSERT INTO admin_audit(actor_staff_id,action,detail,created_at) VALUES(?,?,?,?)",(staff["id"],"campaign_toggle",code,utc_now()))
    raise web.HTTPFound("/admin/campaigns")


async def staff_save(request):
    staff,csrf=require(request,("owner",)); data=await form_post(request,csrf)
    try:
        telegram_id=int(data.get("telegram_id","")); name=str(data.get("name","")).strip()[:100]; role=str(data.get("role",""))
        if telegram_id<=0 or not name or role not in ("operator","admin"): raise ValueError("Xodim ma’lumoti xato")
        with request.app["store"].connection() as db:
            existing=db.execute("SELECT role FROM staff WHERE telegram_id=?",(telegram_id,)).fetchone()
            if existing and existing["role"]=="owner": raise ValueError("Egasi roli o‘zgartirilmaydi")
            db.execute("INSERT INTO staff(telegram_id,name,role) VALUES(?,?,?) ON CONFLICT(telegram_id) DO UPDATE SET name=excluded.name,role=excluded.role,active=1",(telegram_id,name,role))
        raise web.HTTPFound("/admin/staff")
    except ValueError as exc: raise web.HTTPFound("/admin/staff?"+urlencode({"error":str(exc)}))


async def staff_toggle(request):
    staff,csrf=require(request,("owner",)); await form_post(request,csrf)
    with request.app["store"].connection() as db:
        db.execute("UPDATE staff SET active=1-active WHERE id=? AND role!='owner'",(int(request.match_info["id"]),))
        db.execute("UPDATE web_sessions SET revoked_at=? WHERE staff_id=? AND revoked_at IS NULL",(utc_now(),int(request.match_info["id"])))
    raise web.HTTPFound("/admin/staff")


async def privacy(request):
    staff,csrf=require(request,("owner",)); store=request.app["store"]
    rows=store.all("SELECT DISTINCT l.id,l.name,l.phone_e164 FROM leads l JOIN lead_events e ON e.lead_id=l.id WHERE e.kind='privacy_request' AND l.anonymized_at IS NULL")
    body=render("<p>So‘rovlar egasi tomonidan ko‘rib chiqiladi. Anonimlashtirish qaytarilmaydi.</p>{% for r in rows %}<form class='card' method='post' action='/admin/privacy/{{ r.id }}'><input type='hidden' name='csrf' value='{{ csrf }}'>#{{ r.id }} · {{ r.name }} · {{ r.phone_e164 }} <button>Anonimlashtirish</button></form>{% endfor %}",rows=rows,csrf=csrf)
    return page("Maxfiylik so‘rovlari",body,staff,csrf)


async def anonymize(request):
    staff,csrf=require(request,("owner",)); await form_post(request,csrf)
    lead_id=int(request.match_info["id"]); now=utc_now()
    with request.app["store"].connection() as db:
        row=db.execute("SELECT id FROM leads WHERE id=? AND anonymized_at IS NULL",(lead_id,)).fetchone()
        if not row: raise web.HTTPNotFound()
        db.execute("UPDATE leads SET name='Anonim',phone_e164='',user_id=NULL,note=NULL,preferred_contact_time=NULL,anonymized_at=?,updated_at=? WHERE id=?",(now,now,lead_id))
        db.execute("UPDATE lead_events SET old_value=NULL,new_value=NULL,note=NULL WHERE lead_id=?",(lead_id,))
        db.execute("INSERT INTO lead_events(lead_id,actor_staff_id,kind,created_at) VALUES(?,?,?,?)",(lead_id,staff["id"],"anonymized",now))
        db.execute("DELETE FROM notification_outbox WHERE lead_id=? AND sent_at IS NULL",(lead_id,))
    raise web.HTTPFound("/admin/privacy")


def routes(app):
    app.router.add_get("/",root)
    app.router.add_get("/privacy",public_privacy)
    app.router.add_get("/login",login)
    app.router.add_get("/login/{token}",login_token)
    app.router.add_post("/login/{token}",login_token)
    app.router.add_post("/logout",logout)
    app.router.add_get("/admin",dashboard)
    app.router.add_get("/admin/leads",leads)
    app.router.add_get("/admin/leads/new",new_lead)
    app.router.add_post("/admin/leads/new",new_lead_save)
    app.router.add_get("/admin/leads/{id}",lead_detail)
    app.router.add_post("/admin/leads/{id}",lead_save)
    app.router.add_post("/admin/leads/{id}/merge",merge_leads)
    app.router.add_get("/admin/export",export)
    app.router.add_get("/admin/report",report)
    app.router.add_get("/admin/content",content)
    app.router.add_get("/admin/content/{table}/{id}",content_edit)
    app.router.add_post("/admin/content/{table}/{id}",content_save)
    app.router.add_post("/admin/settings",settings_save)
    app.router.add_get("/admin/campaigns",campaigns)
    app.router.add_post("/admin/campaigns",campaign_save)
    app.router.add_post("/admin/campaigns/{code}/toggle",campaign_toggle)
    app.router.add_get("/admin/staff",staff_page)
    app.router.add_post("/admin/staff",staff_save)
    app.router.add_post("/admin/staff/{id}/toggle",staff_toggle)
    app.router.add_get("/admin/privacy",privacy)
    app.router.add_post("/admin/privacy/{id}",anonymize)


env.filters["local"]=local_time
env.filters["localinput"]=local_input
