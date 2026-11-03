import express from 'express';
import Database from 'better-sqlite3';
import pg from 'pg';
import cookie from 'cookie';
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { STATUSES, CLOSED, mapLegacyStatus, pickAssignee, validateStage } from './rules.js';
import { passwordHash, verifyPassword } from './auth.js';

const here = path.dirname(fileURLToPath(import.meta.url));
const db = new pg.Pool({ connectionString: process.env.DATABASE_URL, max: 10 });
const bot = new Database(process.env.BOT_SQLITE_PATH || '/bot-data/itlive.sqlite3', { fileMustExist: true });
bot.pragma('busy_timeout = 10000');
bot.pragma('journal_mode = WAL');
const app = express();
app.disable('x-powered-by');
app.set('trust proxy',1);
app.use(express.json({ limit: '128kb' }));
app.use((req, res, next) => { res.set('Cache-Control','no-store'); res.set('X-Content-Type-Options','nosniff'); next(); });
const q = (text, args=[]) => db.query(text,args);
const str = v => String(v ?? '').trim();
const id = v => { const n=Number(v); if (!Number.isSafeInteger(n) || n<1) throw new Error('Noto‘g‘ri ID'); return n; };
const stamp = v => v ? new Date(v) : null;
const sqlNow = () => new Date().toISOString();
const roleAdmin = user => user.role==='admin'||user.role==='owner';
const csrfHash = value => crypto.createHash('sha256').update(value).digest('hex');

async function getUser(req) {
  const cookies=cookie.parse(req.headers.cookie||'');
  if(cookies.crm_session){
    const r=await q(`SELECT s.id,s.name,s.role,s.active,w.csrf_token,w.expires_at FROM crm_login_sessions w JOIN crm_staff s ON s.id=w.staff_id
      WHERE w.token_hash=$1 AND w.expires_at>now() AND s.active`,[csrfHash(cookies.crm_session)]);
    if(r.rows[0])return r.rows[0];
  }
  const token = cookies.itlive_session;
  if (!token) return null;
  const row = bot.prepare(`SELECT s.id,s.telegram_id,s.name,s.role,s.active,w.csrf_token,w.expires_at,w.revoked_at
    FROM web_sessions w JOIN staff s ON s.id=w.staff_id WHERE w.token_hash=?`).get(csrfHash(token));
  if (!row || !row.active || row.revoked_at || Date.parse(row.expires_at)<=Date.now()) return null;
  return row;
}
function auth(req,res,next) {getUser(req).then(user=>{if(!user)return res.status(401).json({error:'Kirish talab qilinadi'});req.user=user;next();}).catch(next);}
function admin(req,res,next){ if(!roleAdmin(req.user)) return res.status(403).json({error:'Ruxsat yo‘q'}); next(); }
function owner(req,res,next){ if(req.user.role!=='owner') return res.status(403).json({error:'Ruxsat yo‘q'}); next(); }
function mutation(req,res,next){ if(req.get('X-CSRF-Token')!==req.user.csrf_token) return res.status(403).json({error:'CSRF tekshiruvi xato'}); next(); }
function safe(fn){return (req,res,next)=>Promise.resolve().then(()=>fn(req,res)).catch(next);}
function visible(user,lead){return !!lead && !lead.anonymized && !lead.merged_into_id && (roleAdmin(user)||Number(lead.assignee_id)===Number(user.id));}
async function leadFor(req){const r=await q('SELECT * FROM crm_leads WHERE id=$1',[id(req.params.id)]);const lead=r.rows[0];if(!visible(req.user,lead)) {const e=new Error('Lead topilmadi');e.status=404;throw e;}return lead;}
function record(client,leadId,actor,kind,oldValue,newValue,note=''){
  return client.query('INSERT INTO crm_events(lead_id,actor_id,kind,old_value,new_value,note) VALUES($1,$2,$3,$4,$5,$6)',[leadId,actor,kind,oldValue,newValue,note]);
}

async function syncBot() {
  const staff=bot.prepare('SELECT id,telegram_id,name,role,active FROM staff').all();
  const leads=bot.prepare(`SELECT l.*,u.username FROM leads l LEFT JOIN users u ON u.id=l.user_id ORDER BY l.id`).all();
  const client=await db.connect();
  try {
    await client.query('BEGIN');
    await client.query('SELECT pg_advisory_xact_lock(923417)');
    for(const s of staff) await client.query(`INSERT INTO crm_staff(id,telegram_id,name,role,active) VALUES($1,$2,$3,$4,$5)
      ON CONFLICT(id) DO UPDATE SET telegram_id=EXCLUDED.telegram_id,name=EXCLUDED.name,role=EXCLUDED.role,active=EXCLUDED.active`,[s.id,s.telegram_id,s.name,s.role,!!s.active]);
    const allStaff=(await client.query('SELECT id,role,active FROM crm_staff')).rows;
    const current=(await client.query('SELECT id,status,assignee_id,bot_updated_at,anonymized,merged_into_id FROM crm_leads ORDER BY id')).rows;
    const known=new Map(current.map(r=>[Number(r.id),r]));
    let cursor=Number((await client.query("SELECT value FROM crm_meta WHERE key='assignment_cursor'")).rows[0]?.value||0);
    for(const l of leads){
      const prior=known.get(l.id);
      const privateGone=!!l.anonymized_at;
      if(!prior){
        const status=mapLegacyStatus(l.status);
        const eligible=!privateGone && !l.merged_into_id && !CLOSED.has(status);
        const assignment=!eligible ? null : l.assignee_id && allStaff.some(s=>Number(s.id)===l.assignee_id && s.active && s.role==='operator')
          ? l.assignee_id : pickAssignee(allStaff,current,cursor++);
        await client.query(`INSERT INTO crm_leads(id,telegram_user_id,username,request_type,name,phone,course_id,course_name,branch_id,branch_name,source,campaign_code,status,assignee_id,preferred_contact_time,note,next_action_at,meeting_at,meeting_format,lost_reason,first_contact_at,closed_at,created_at,updated_at,bot_updated_at,anonymized,merged_into_id)
          VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22,$23,$24,$25,$26,$27)`,
          [l.id,l.user_id,l.username,l.request_type,privateGone?'Anonim':l.name,privateGone?'':l.phone_e164,l.course_id,l.course_name_snapshot,l.branch_id,l.branch_name_snapshot,l.source,l.campaign_code,status,assignment,l.preferred_contact_time,l.note,stamp(l.next_action_at),stamp(l.meeting_at),l.meeting_format,l.lost_reason,stamp(l.first_contact_at),stamp(l.closed_at),stamp(l.created_at),stamp(l.updated_at),stamp(l.updated_at),privateGone,l.merged_into_id]);
        current.push({id:l.id,status,assignee_id:assignment,anonymized:privateGone,merged_into_id:l.merged_into_id});
        known.set(l.id,{id:l.id,status,assignee_id:assignment,bot_updated_at:l.updated_at});
        await record(client,l.id,null,'created',null,status,'Telegram botdan sinxronlandi');
        if(assignment) await record(client,l.id,null,'assigned',null,String(assignment),'Avtomatik teng taqsimlash');
      } else if(Date.parse(l.updated_at)>Date.parse(prior.bot_updated_at) || (privateGone&&!prior.anonymized)){
        await client.query(`UPDATE crm_leads SET name=$2,phone=$3,username=$4,course_id=$5,course_name=$6,branch_id=$7,branch_name=$8,
          anonymized=$9,merged_into_id=$10,bot_updated_at=$11 WHERE id=$1`,
          [l.id,privateGone?'Anonim':l.name,privateGone?'':l.phone_e164,l.username,l.course_id,l.course_name_snapshot,l.branch_id,l.branch_name_snapshot,privateGone,l.merged_into_id,stamp(l.updated_at)]);
        prior.anonymized=privateGone;
        prior.merged_into_id=l.merged_into_id;
      }
    }
    for(const lead of current.filter(x=>!x.assignee_id && !x.anonymized && !x.merged_into_id && !CLOSED.has(x.status))){
      const assignment=pickAssignee(allStaff,current,cursor++);
      if(!assignment)break;
      await client.query('UPDATE crm_leads SET assignee_id=$2,updated_at=now() WHERE id=$1',[lead.id,assignment]);
      await record(client,lead.id,null,'assigned',null,String(assignment),'Biriktirilmagan lead avtomatik taqsimlandi');
      lead.assignee_id=assignment;
    }
    await client.query("INSERT INTO crm_meta(key,value) VALUES('assignment_cursor',$1) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value",[String(cursor)]);
    await client.query('COMMIT');
  } catch(e){await client.query('ROLLBACK');throw e;} finally{client.release();}
}

app.get('/crm/health',safe(async(req,res)=>{await q('SELECT 1');bot.prepare('SELECT 1').get();res.json({status:'ok',bot_sync:true});}));
const loginAttempts=new Map();
app.post('/crm/api/seller/login',safe(async(req,res)=>{
  const origin=req.get('Origin');
  if(origin && new URL(origin).host!==req.get('host')){const e=new Error('Noto‘g‘ri kirish manzili');e.status=403;throw e;}
  const key=req.ip||'unknown',now=Date.now(),attempt=loginAttempts.get(key)||{count:0,until:now+900000};
  if(attempt.until<now){attempt.count=0;attempt.until=now+900000;}
  if(attempt.count>=10){const e=new Error('Kirish urinishlari ko‘p. Keyinroq urinib ko‘ring');e.status=429;throw e;}
  const login=str(req.body.login_name).toLowerCase().slice(0,80),password=req.body.password;
  const row=(await q("SELECT id,password_hash FROM crm_staff WHERE login_name=$1 AND role='operator' AND active",[login])).rows[0];
  if(!row||!verifyPassword(password,row.password_hash)){attempt.count++;loginAttempts.set(key,attempt);const e=new Error('Login yoki parol noto‘g‘ri');e.status=401;throw e;}
  loginAttempts.delete(key);
  const token=crypto.randomBytes(32).toString('base64url'),csrf=crypto.randomBytes(32).toString('base64url');
  await q('INSERT INTO crm_login_sessions(token_hash,staff_id,csrf_token,expires_at) VALUES($1,$2,$3,now()+interval \'8 hours\')',[csrfHash(token),row.id,csrf]);
  res.cookie('crm_session',token,{httpOnly:true,secure:true,sameSite:'lax',path:'/crm',maxAge:8*3600*1000});
  res.json({ok:true});
}));
app.post('/crm/api/logout',auth,mutation,safe(async(req,res)=>{
  const token=cookie.parse(req.headers.cookie||'').crm_session;
  if(token)await q('DELETE FROM crm_login_sessions WHERE token_hash=$1',[csrfHash(token)]);
  const botToken=cookie.parse(req.headers.cookie||'').itlive_session;
  if(botToken)bot.prepare('UPDATE web_sessions SET revoked_at=? WHERE token_hash=? AND revoked_at IS NULL').run(sqlNow(),csrfHash(botToken));
  res.clearCookie('crm_session',{path:'/crm'});
  res.clearCookie('itlive_session',{path:'/'});
  res.json({ok:true});
}));
app.get('/crm/api/me',auth,safe(async(req,res)=>res.json({id:req.user.id,name:req.user.name,role:req.user.role,csrf:req.user.csrf_token,loginUrl:'/login'})));
app.get('/crm/api/dashboard',auth,safe(async(req,res)=>{
  const scope=roleAdmin(req.user)?'':`AND assignee_id=${Number(req.user.id)}`;
  const {rows}=await q(`SELECT count(*) FILTER (WHERE created_at >= (now() AT TIME ZONE 'Asia/Tashkent')::date AT TIME ZONE 'Asia/Tashkent')::int AS today,
    count(*) FILTER (WHERE status='Yangi lead')::int AS fresh,
    count(*) FILTER (WHERE next_action_at<now() AND status NOT IN ('Sotib oldi','Sotib olmadi'))::int AS overdue,
    count(*) FILTER (WHERE meeting_at::date=(now() AT TIME ZONE 'Asia/Tashkent')::date)::int AS visits,
    count(*) FILTER (WHERE status='Sotib oldi')::int AS won,
    count(*) FILTER (WHERE status='Sotib olmadi')::int AS lost,
    count(*)::int AS total FROM crm_leads WHERE NOT anonymized AND merged_into_id IS NULL ${scope}`);
  res.json(rows[0]);
}));
app.get('/crm/api/leads',auth,safe(async(req,res)=>{
  const where=['NOT l.anonymized','l.merged_into_id IS NULL'];const args=[];
  if(!roleAdmin(req.user)){args.push(req.user.id);where.push(`l.assignee_id=$${args.length}`);}
  for(const [key,col] of [['status','l.status'],['course','l.course_id'],['branch','l.branch_id'],['source','l.source'],['assignee','l.assignee_id']]){
    if(req.query[key]){args.push(req.query[key]);where.push(`${col}=$${args.length}`);}
  }
  if(req.query.q){args.push(`%${str(req.query.q).slice(0,80)}%`);where.push(`(l.name ILIKE $${args.length} OR l.phone ILIKE $${args.length} OR l.username ILIKE $${args.length} OR l.id::text ILIKE $${args.length})`);}
  if(req.query.from){args.push(req.query.from);where.push(`l.created_at >= $${args.length}::date AT TIME ZONE 'Asia/Tashkent'`);}
  if(req.query.to){args.push(req.query.to);where.push(`l.created_at < ($${args.length}::date + interval '1 day') AT TIME ZONE 'Asia/Tashkent'`);}
  if(req.query.due==='overdue')where.push("l.next_action_at<now() AND l.status NOT IN ('Sotib oldi','Sotib olmadi')");
  const result=await q(`SELECT l.*,s.name AS assignee_name FROM crm_leads l LEFT JOIN crm_staff s ON s.id=l.assignee_id WHERE ${where.join(' AND ')} ORDER BY l.created_at DESC LIMIT 5000`,args);
  res.json({items:result.rows,statuses:STATUSES});
}));
app.get('/crm/api/leads/:id',auth,safe(async(req,res)=>{
  const lead=await leadFor(req);
  const events=(await q('SELECT e.*,s.name AS actor_name FROM crm_events e LEFT JOIN crm_staff s ON s.id=e.actor_id WHERE e.lead_id=$1 ORDER BY e.id DESC LIMIT 100',[lead.id])).rows;
  res.json({lead,events});
}));
app.patch('/crm/api/leads/:id',auth,admin,mutation,safe(async(req,res)=>{
  const lead=await leadFor(req),name=str(req.body.name).slice(0,100),phone=str(req.body.phone).replace(/\s/g,''),courseId=req.body.course_id?id(req.body.course_id):null,branchId=req.body.branch_id?id(req.body.branch_id):null;
  if(name.length<2||!/^\+998\d{9}$/.test(phone))throw new Error('Ism yoki telefon raqami noto‘g‘ri');
  const course=courseId?bot.prepare('SELECT name FROM courses WHERE id=?').get(courseId):null;
  const branch=branchId?bot.prepare('SELECT name FROM branches WHERE id=?').get(branchId):null;
  if(courseId&&!course||branchId&&!branch)throw new Error('Kurs yoki filial topilmadi');
  const original=bot.prepare('SELECT * FROM leads WHERE id=? AND anonymized_at IS NULL AND merged_into_id IS NULL').get(lead.id);
  if(!original)throw new Error('Bot arizasi topilmadi');
  const fields={name,phone_e164:phone,course_id:courseId,course_name_snapshot:course?.name||null,branch_id:branchId,branch_name_snapshot:branch?.name||null};
  bot.transaction(()=>{
    const now=sqlNow();
    bot.prepare('UPDATE leads SET name=?,phone_e164=?,course_id=?,course_name_snapshot=?,branch_id=?,branch_name_snapshot=?,updated_at=? WHERE id=?').run(name,phone,courseId,course?.name||null,branchId,branch?.name||null,now,lead.id);
    const event=bot.prepare('INSERT INTO lead_events(lead_id,actor_staff_id,kind,old_value,new_value,created_at) VALUES(?,?,?,?,?,?)');
    for(const [field,value] of Object.entries(fields))if(original[field]!==value)event.run(lead.id,req.user.id,`crm_update:${field}`,String(original[field]??''),String(value??''),now);
  })();
  await syncBot();res.json({ok:true});
}));
app.post('/crm/api/leads/:id/stage',auth,mutation,safe(async(req,res)=>{
  const lead=await leadFor(req),status=str(req.body.status),note=str(req.body.note).slice(0,1000),lost=str(req.body.lost_reason).slice(0,80);
  const courseId=req.body.course_id?id(req.body.course_id):lead.course_id;
  const course=req.body.course_id?bot.prepare('SELECT id,name FROM courses WHERE id=? AND active=1').get(courseId):courseId?{id:courseId,name:lead.course_name}:null;
  if(req.body.course_id&&!course)throw new Error('Faol kurs topilmadi');
  validateStage(status,{note,lost_reason:lost,course_id:courseId},lead);
  const next=req.body.next_action_at?stamp(req.body.next_action_at):null;
  const meeting=req.body.meeting_at?stamp(req.body.meeting_at):null;
  if((next && Number.isNaN(next.getTime()))||(meeting && Number.isNaN(meeting.getTime()))) throw new Error('Sana noto‘g‘ri');
  const client=await db.connect();try{await client.query('BEGIN');await client.query(`UPDATE crm_leads SET status=$2,note=CASE WHEN $3='' THEN note ELSE $3 END,
    lost_reason=$4,next_action_at=$5,meeting_at=$6,meeting_format=$7,first_contact_at=CASE WHEN $2<>'Yangi lead' AND first_contact_at IS NULL THEN now() ELSE first_contact_at END,
    closed_at=CASE WHEN $2 IN ('Sotib oldi','Sotib olmadi') THEN now() ELSE NULL END,course_id=$8,course_name=$9,updated_at=now() WHERE id=$1`,[lead.id,status,note,lost||null,next,meeting,str(req.body.meeting_format)||null,courseId,course?.name||null]);
    await record(client,lead.id,req.user.id,'status',lead.status,status,note);await client.query('COMMIT');res.json({ok:true});}catch(e){await client.query('ROLLBACK');throw e;}finally{client.release();}
}));
app.post('/crm/api/leads/:id/note',auth,mutation,safe(async(req,res)=>{
  const lead=await leadFor(req),note=str(req.body.note).slice(0,1000);if(!note)throw new Error('Izoh kiriting');
  await q('INSERT INTO crm_events(lead_id,actor_id,kind,note) VALUES($1,$2,$3,$4)',[lead.id,req.user.id,'note',note]);res.json({ok:true});
}));
app.post('/crm/api/leads/:id/assign',auth,admin,mutation,safe(async(req,res)=>{
  const lead=await leadFor(req),assignee=req.body.assignee_id? id(req.body.assignee_id):null;
  if(assignee){const s=(await q("SELECT * FROM crm_staff WHERE id=$1 AND role='operator' AND active",[assignee])).rows[0];if(!s)throw new Error('Faol sotuvchi topilmadi');}
  const client=await db.connect();try{await client.query('BEGIN');await client.query('UPDATE crm_leads SET assignee_id=$2,updated_at=now() WHERE id=$1',[lead.id,assignee]);await record(client,lead.id,req.user.id,'assigned',String(lead.assignee_id||''),String(assignee||''));await client.query('COMMIT');res.json({ok:true});}catch(e){await client.query('ROLLBACK');throw e;}finally{client.release();}
}));
app.post('/crm/api/leads',auth,admin,mutation,safe(async(req,res)=>{
  const name=str(req.body.name).slice(0,120),phone=str(req.body.phone).replace(/\s/g,''),course=req.body.course_id?id(req.body.course_id):null,branch=req.body.branch_id?id(req.body.branch_id):null;
  if(name.length<2||!/^\+998\d{9}$/.test(phone))throw new Error('Ism yoki +998 telefon raqami noto‘g‘ri');
  const courseRow=course?bot.prepare('SELECT name FROM courses WHERE id=? AND active=1').get(course):null;
  const branchRow=branch?bot.prepare('SELECT name FROM branches WHERE id=? AND active=1').get(branch):null;
  if(course&&!courseRow)throw new Error('Kurs topilmadi');if(branch&&!branchRow)throw new Error('Filial topilmadi');
  const now=sqlNow();const result=bot.prepare(`INSERT INTO leads(request_type,name,phone_e164,course_id,course_name_snapshot,branch_id,branch_name_snapshot,source,status,note,created_at,updated_at,confirmation_key)
    VALUES(?,?,?,?,? ,?,?,'manual','Yangi mijoz',?,?,?,?)`).run(course?'course':'callback',name,phone,course,courseRow?.name||null,branch,branchRow?.name||null,str(req.body.note).slice(0,500)||null,now,now,crypto.randomBytes(20).toString('hex'));
  await syncBot();res.json({id:Number(result.lastInsertRowid)});
}));
app.get('/crm/api/team',auth,safe(async(req,res)=>{
  const rows=(await q(`SELECT s.id,s.telegram_id,s.login_name,s.name,s.role,s.active,count(l.id) FILTER (WHERE l.status NOT IN ('Sotib oldi','Sotib olmadi') AND NOT l.anonymized)::int AS open_leads,
  count(l.id) FILTER (WHERE l.status='Sotib oldi')::int AS won FROM crm_staff s LEFT JOIN crm_leads l ON l.assignee_id=s.id ${roleAdmin(req.user)?'':'WHERE s.id=$1'} GROUP BY s.id ORDER BY s.role,s.id`,roleAdmin(req.user)?[]:[req.user.id])).rows;res.json(rows);
}));
app.post('/crm/api/team',auth,admin,mutation,safe(async(req,res)=>{
  const name=str(req.body.name).slice(0,100),role=str(req.body.role);
  if(name.length<2||!['operator','admin'].includes(role))throw new Error('Xodim ma’lumoti noto‘g‘ri');
  if(role==='operator'){
    const login=str(req.body.login_name).toLowerCase();
    if(!/^[a-z0-9_.-]{3,40}$/.test(login))throw new Error('Login 3–40 belgili lotin harflari va raqamlardan iborat bo‘lsin');
    await q(`INSERT INTO crm_staff(id,telegram_id,login_name,password_hash,name,role,active)
      VALUES(nextval('crm_seller_seq'),NULL,$1,$2,$3,'operator',true)`,[login,passwordHash(req.body.password),name]);
    await syncBot();
  }else{
    if(req.user.role!=='owner'){const e=new Error('Faqat egasi admin qo‘sha oladi');e.status=403;throw e;}
    const telegram=id(req.body.telegram_id);
    bot.prepare(`INSERT INTO staff(telegram_id,name,role,active) VALUES(?,?,?,1) ON CONFLICT(telegram_id) DO UPDATE SET name=excluded.name,role=excluded.role,active=1`).run(telegram,name,role);
    await syncBot();
  }
  res.json({ok:true});
}));
app.patch('/crm/api/team/:id',auth,admin,mutation,safe(async(req,res)=>{
  const target=id(req.params.id),row=(await q('SELECT id,role,telegram_id FROM crm_staff WHERE id=$1',[target])).rows[0];
  if(!row||row.role==='owner')throw new Error('Egasi hisobini o‘zgartirib bo‘lmaydi');
  if(row.role==='admin'&&req.user.role!=='owner'){const e=new Error('Faqat egasi adminni boshqaradi');e.status=403;throw e;}
  const active=!!req.body.active;
  if(row.telegram_id){bot.transaction(()=>{bot.prepare('UPDATE staff SET active=? WHERE id=?').run(Number(active),target);if(!active){bot.prepare('UPDATE web_sessions SET revoked_at=? WHERE staff_id=? AND revoked_at IS NULL').run(sqlNow(),target);bot.prepare('UPDATE login_tokens SET used_at=? WHERE staff_id=? AND used_at IS NULL').run(sqlNow(),target);}})();await syncBot();}
  else{await q('UPDATE crm_staff SET active=$2 WHERE id=$1',[target,active]);if(!active)await q('DELETE FROM crm_login_sessions WHERE staff_id=$1',[target]);}
  res.json({ok:true});
}));
app.post('/crm/api/team/:id/password',auth,admin,mutation,safe(async(req,res)=>{
  const target=id(req.params.id),row=(await q("SELECT id FROM crm_staff WHERE id=$1 AND role='operator' AND telegram_id IS NULL",[target])).rows[0];
  if(!row)throw new Error('Sotuvchi topilmadi');
  await q('UPDATE crm_staff SET password_hash=$2 WHERE id=$1',[target,passwordHash(req.body.password)]);
  await q('DELETE FROM crm_login_sessions WHERE staff_id=$1',[target]);
  res.json({ok:true});
}));
app.post('/crm/api/my-password',auth,mutation,safe(async(req,res)=>{
  const row=(await q('SELECT password_hash FROM crm_staff WHERE id=$1 AND role=\'operator\'',[req.user.id])).rows[0];
  if(!row||!verifyPassword(req.body.current_password,row.password_hash)){const e=new Error('Joriy parol noto‘g‘ri');e.status=403;throw e;}
  await q('UPDATE crm_staff SET password_hash=$2 WHERE id=$1',[req.user.id,passwordHash(req.body.new_password)]);
  res.json({ok:true});
}));

const ENTITIES={
  courses:['name','short_description','description','audience','duration','format','syllabus','price','show_price','active','sort_order'],
  mentors:['name','specialty','bio','photo_file_id','active','sort_order'],
  branches:['name','address','landmark','hours','phone','latitude','longitude','active','sort_order'],
  faq:['question','answer','active','sort_order']
};
function entity(req){const e=req.params.entity;if(!ENTITIES[e]){const x=new Error('Bo‘lim topilmadi');x.status=404;throw x;}return e;}
app.get('/crm/api/content/courses/:id/links',auth,admin,safe(async(req,res)=>{
  const courseId=id(req.params.id);
  res.json({
    mentor_ids:bot.prepare('SELECT mentor_id FROM course_mentors WHERE course_id=?').all(courseId).map(x=>x.mentor_id),
    branch_ids:bot.prepare('SELECT branch_id FROM course_branches WHERE course_id=?').all(courseId).map(x=>x.branch_id)
  });
}));
app.put('/crm/api/content/courses/:id/links',auth,admin,mutation,safe(async(req,res)=>{
  const courseId=id(req.params.id);
  if(!bot.prepare('SELECT 1 FROM courses WHERE id=?').get(courseId))throw new Error('Kurs topilmadi');
  const mentors=[...new Set((req.body.mentor_ids||[]).map(id))],branches=[...new Set((req.body.branch_ids||[]).map(id))];
  if(mentors.length>100||branches.length>100)throw new Error('Juda ko‘p bog‘lanish');
  bot.transaction(()=>{
    bot.prepare('DELETE FROM course_mentors WHERE course_id=?').run(courseId);
    bot.prepare('DELETE FROM course_branches WHERE course_id=?').run(courseId);
    const addMentor=bot.prepare('INSERT INTO course_mentors(course_id,mentor_id) VALUES(?,?)');
    const addBranch=bot.prepare('INSERT INTO course_branches(course_id,branch_id) VALUES(?,?)');
    for(const mentor of mentors)addMentor.run(courseId,mentor);
    for(const branch of branches)addBranch.run(courseId,branch);
  })();res.json({ok:true});
}));
app.get('/crm/api/content/:entity',auth,safe(async(req,res)=>{
  const e=entity(req);res.json(bot.prepare(`SELECT * FROM ${e} ORDER BY sort_order,id`).all());
}));
app.post('/crm/api/content/:entity',auth,admin,mutation,safe(async(req,res)=>{
  const e=entity(req),cols=ENTITIES[e].filter(k=>Object.hasOwn(req.body,k));
  if(!cols.length)throw new Error('Ma’lumot kiriting');
  const values=cols.map(k=>['active','show_price'].includes(k)?Number(!!req.body[k]):req.body[k]);
  const result=bot.prepare(`INSERT INTO ${e}(${cols.join(',')}) VALUES(${cols.map(()=>'?').join(',')})`).run(...values);res.json({id:Number(result.lastInsertRowid)});
}));
app.patch('/crm/api/content/:entity/:id',auth,admin,mutation,safe(async(req,res)=>{
  const e=entity(req),cols=ENTITIES[e].filter(k=>Object.hasOwn(req.body,k));if(!cols.length)throw new Error('Ma’lumot kiriting');
  const values=cols.map(k=>['active','show_price'].includes(k)?Number(!!req.body[k]):req.body[k]);
  bot.prepare(`UPDATE ${e} SET ${cols.map(k=>`${k}=?`).join(',')} WHERE id=?`).run(...values,id(req.params.id));res.json({ok:true});
}));
app.get('/crm/api/settings',auth,admin,safe(async(req,res)=>res.json(Object.fromEntries(bot.prepare('SELECT key,value FROM settings').all().map(r=>[r.key,r.value])))));
app.patch('/crm/api/settings',auth,admin,mutation,safe(async(req,res)=>{
  const allowed=['contact_text','contact_phone','contact_telegram','contact_hours','privacy_url'];
  const update=bot.prepare('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value');
  bot.transaction(()=>{for(const key of allowed)if(Object.hasOwn(req.body,key))update.run(key,str(req.body[key]).slice(0,2000));})();res.json({ok:true});
}));
app.get('/crm/api/campaigns',auth,admin,safe(async(req,res)=>res.json(bot.prepare('SELECT * FROM campaigns ORDER BY code').all())));
app.post('/crm/api/campaigns',auth,admin,mutation,safe(async(req,res)=>{
  const code=str(req.body.code).slice(0,64),title=str(req.body.title).slice(0,150);
  if(!/^[A-Za-z0-9_-]{2,64}$/.test(code)||!title)throw new Error('Kampaniya kodi yoki nomi noto‘g‘ri');
  bot.prepare('INSERT INTO campaigns(code,title,active) VALUES(?,?,1) ON CONFLICT(code) DO UPDATE SET title=excluded.title,active=1').run(code,title);res.json({ok:true});
}));
app.patch('/crm/api/campaigns/:code',auth,admin,mutation,safe(async(req,res)=>{bot.prepare('UPDATE campaigns SET active=? WHERE code=?').run(Number(!!req.body.active),req.params.code);res.json({ok:true});}));
app.get('/crm/api/report',auth,admin,safe(async(req,res)=>{
  const where=["NOT l.anonymized","l.merged_into_id IS NULL"],args=[];
  if(req.query.from){args.push(req.query.from);where.push(`l.created_at >= $${args.length}::date AT TIME ZONE 'Asia/Tashkent'`);}
  if(req.query.to){args.push(req.query.to);where.push(`l.created_at < ($${args.length}::date + interval '1 day') AT TIME ZONE 'Asia/Tashkent'`);}
  const rows=(await q(`SELECT s.name AS seller,l.course_name AS course,l.branch_name AS branch,l.source,l.status,count(*)::int AS count FROM crm_leads l LEFT JOIN crm_staff s ON s.id=l.assignee_id WHERE ${where.join(' AND ')} GROUP BY s.name,l.course_name,l.branch_name,l.source,l.status ORDER BY count DESC`,args)).rows;
  res.json(rows);
}));
app.get('/crm/api/export',auth,admin,safe(async(req,res)=>{
  const rows=(await q('SELECT id,name,phone,course_name,branch_name,source,status,assignee_id,created_at FROM crm_leads WHERE NOT anonymized AND merged_into_id IS NULL ORDER BY created_at DESC')).rows;
  const quote=v=>'"'+String(v??'').replaceAll('"','""').replace(/^[=+@-]/,'\t$&')+'"';
  const cols=['id','name','phone','course_name','branch_name','source','status','assignee_id','created_at'];
  const csv='\ufeff'+[cols.join(','),...rows.map(r=>cols.map(c=>quote(r[c])).join(','))].join('\r\n');
  res.set('Content-Type','text/csv; charset=utf-8');res.set('Content-Disposition','attachment; filename="itlive-crm-leads.csv"');res.send(csv);
}));

const assets=path.resolve(here,'../client/dist');
app.use('/crm',express.static(assets,{index:false,maxAge:'1h'}));
app.get(/^\/crm(?:\/.*)?$/, (req,res)=>res.sendFile(path.join(assets,'index.html')));
app.use((err,req,res,next)=>{console.error('CRM error:',err.message);res.status(err.status||400).json({error:err.message||'Xatolik yuz berdi'});});

await q(fs.readFileSync(path.join(here,'schema.sql'),'utf8'));
await syncBot();
setInterval(()=>syncBot().catch(e=>console.error('Bot sync failed:',e.message)),10000).unref();
app.listen(Number(process.env.PORT||8787),'0.0.0.0',()=>console.log('ITLIVE CRM listening'));
