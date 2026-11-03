const ZONE = 'Asia/Tashkent';
const OPEN = "status NOT IN ('Sotib oldi','Sotib olmadi')";

export function tashkentTime(now = new Date()) {
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en-GB', {
    timeZone: ZONE, year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hourCycle: 'h23'
  }).formatToParts(now).filter(x => x.type !== 'literal').map(x => [x.type, x.value]));
  return { day: `${parts.year}-${parts.month}-${parts.day}`, hour: Number(parts.hour), minute: Number(parts.minute) };
}

export function dueReportSlot(now = new Date()) {
  const { day, hour } = tashkentTime(now);
  return hour >= 17 ? `${day}:17` : hour >= 12 ? `${day}:12` : null;
}

const normalized = value => String(value || '').toLocaleLowerCase('uz-UZ').replace(/[‘’`ʻʼ]/g, "'").replace(/\s+/g, ' ').trim();
const escaped = value => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
const mentions = (text, value) => value && new RegExp(`(^|[^\\p{L}\\p{N}])${escaped(normalized(value))}(?=$|[^\\p{L}\\p{N}])`, 'u').test(normalized(text));

export function resolveSeller(text, sellers) {
  const full = sellers.filter(s => mentions(text, s.name) || mentions(text, s.login_name));
  if (full.length === 1) return full[0];
  if (full.length > 1) return null;
  const first = sellers.filter(s => mentions(text, String(s.name || '').split(/\s+/)[0]));
  return first.length === 1 ? first[0] : null;
}

export function taskDeadline(text, now = new Date()) {
  const match = normalized(text).match(/\b(bugun|ertaga)\s+(?:soat\s+)?(\d{1,2})[.:](\d{2})(?:\s*gacha)?\b/);
  if (!match || Number(match[2]) > 23 || Number(match[3]) > 59) return null;
  const { day } = tashkentTime(now);
  const start = new Date(`${day}T00:00:00+05:00`);
  const offset = match[1] === 'ertaga' ? 86400000 : 0;
  const due = new Date(start.getTime() + offset + (Number(match[2]) * 60 + Number(match[3])) * 60000);
  return due > now ? due.toISOString() : null;
}

function fallbackTask(text, seller) {
  let body = String(text).trim();
  for (const alias of [seller?.name, seller?.login_name, String(seller?.name || '').split(/\s+/)[0]].filter(Boolean).sort((a,b)=>b.length-a.length)) {
    body = body.replace(new RegExp(`^${escaped(alias)}(?:[,:\\s]+|$)`, 'iu'), '').trim();
  }
  let details = (body || text).replace(/\s+/g, ' ').trim();
  details = details.replace(/telefon qilsin/iu, 'telefon qiling').replace(/qo['‘’`ʻʼ]ng['‘’`ʻʼ]?iroq qilsin/iu, 'qo‘ng‘iroq qiling');
  details = details.charAt(0).toLocaleUpperCase('uz-UZ') + details.slice(1);
  if (!/[.!?]$/.test(details)) details += '.';
  const title = /barcha leadlarga/i.test(details) && /telefon|qo['‘’`ʻʼ]ng/i.test(details) ? 'Barcha leadlarga qo‘ng‘iroq qilish' : details.slice(0, 180);
  const lead = text.match(/(?:lead|lid|ariza)\s*#?(\d+)/i);
  return { seller_id: seller ? Number(seller.id) : null, title, details: details.slice(0, 800), lead_id: lead ? Number(lead[1]) : null, due_at: taskDeadline(text), direct: !!seller };
}

export function parseDirectTask(text, sellers) {
  const match = String(text || '').trim().match(/^([^|:]{2,80})\s*[|:]\s*(.{3,800})$/s);
  if (!match) return null;
  const target = match[1].trim().toLocaleLowerCase('uz-UZ');
  const seller = sellers.find(s => [String(s.id), s.login_name?.toLocaleLowerCase('uz-UZ'), s.name.toLocaleLowerCase('uz-UZ')].includes(target));
  if (!seller) return null;
  const body = match[2].trim();
  const lead = body.match(/(?:lead|lid|ariza)\s*#?(\d+)/i);
  const due_at = taskDeadline(body);
  return { seller_id: Number(seller.id), title: body.slice(0, 180), details: body, lead_id: lead ? Number(lead[1]) : null, due_at, direct: true };
}

function interactionText(json) {
  return (json.steps || []).filter(step => step.type === 'model_output')
    .flatMap(step => step.content || []).filter(part => part.type === 'text')
    .map(part => part.text || '').join('').trim();
}

export async function transcribeVoice(audio, mimeType = 'audio/ogg', keys = {}) {
  if (!Buffer.isBuffer(audio) || !audio.length || audio.length > 10_000_000) throw new Error('Ovozli xabar hajmi noto‘g‘ri');
  for (const provider of availableProviders(keys)) {
    try {
      let response, result;
      if (provider === 'gemini') {
        response = await fetch('https://generativelanguage.googleapis.com/v1beta/interactions', {
          method: 'POST', signal: AbortSignal.timeout(45000),
          headers: { 'x-goog-api-key': keys.gemini, 'Content-Type': 'application/json' },
          body: JSON.stringify({ model: process.env.GEMINI_MODEL || 'gemini-3.6-flash', store: false, generation_config: { thinking_level: 'low', max_output_tokens: 1000 }, input: [
            { type: 'text', text: 'Ushbu ovozli xabarni o‘zbek tilida aynan aytilganidek matnga ko‘chiring. Faqat transkriptni qaytaring.' },
            { type: 'audio', data: audio.toString('base64'), mime_type: mimeType }
          ] })
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        result = interactionText(await response.json());
      } else {
        const form = new FormData();
        form.set('model', provider === 'groq' ? 'whisper-large-v3-turbo' : 'gpt-transcribe');
        form.set('file', new Blob([audio], { type: mimeType }), 'telegram-voice.ogg');
        form.set('prompt', 'O‘zbek tilidagi ITLIVE savdo vazifasi. Lead, sotuvchi ismlari va vaqtlarni aniq yozing.');
        response = await fetch(provider === 'groq' ? 'https://api.groq.com/openai/v1/audio/transcriptions' : 'https://api.openai.com/v1/audio/transcriptions', {
          method: 'POST', signal: AbortSignal.timeout(30000),
          headers: { Authorization: `Bearer ${keys[provider]}` }, body: form
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        result = (await response.json()).text;
      }
      if (String(result || '').trim().length >= 3) return String(result).trim().slice(0, 800);
      throw new Error('bo‘sh transkript');
    } catch (error) { console.error(`${provider} voice transcription failed:`, error.message); }
  }
  return null;
}

function responseText(json) {
  return (json.output || []).flatMap(item => item.content || []).filter(x => x.type === 'output_text').map(x => x.text).join('').trim();
}

export function availableProviders(saved = {}) {
  const keys = { groq: saved.groq || process.env.GROQ_API_KEY, openai: saved.openai || process.env.OPENAI_API_KEY, gemini: saved.gemini || process.env.GEMINI_API_KEY };
  const preferred = String(process.env.AI_PROVIDER || 'auto').toLowerCase();
  const order = Object.hasOwn(keys, preferred) ? [preferred, ...Object.keys(keys).filter(x => x !== preferred)] : Object.keys(keys);
  return order.filter(x => !!keys[x]);
}

async function callAI(input, schema, instructions, maxOutput = 350, saved = {}) {
  const keys = { groq: saved.groq || process.env.GROQ_API_KEY, openai: saved.openai || process.env.OPENAI_API_KEY, gemini: saved.gemini || process.env.GEMINI_API_KEY };
  for (const provider of availableProviders(saved)) {
    try {
      let response, result;
      if (provider === 'groq') {
        response = await fetch('https://api.groq.com/openai/v1/chat/completions', {
          method: 'POST', signal: AbortSignal.timeout(15000),
          headers: { Authorization: `Bearer ${keys.groq}`, 'Content-Type': 'application/json' },
          body: JSON.stringify({
            model: process.env.GROQ_MODEL || 'openai/gpt-oss-20b',
            messages: [{ role: 'system', content: instructions }, { role: 'user', content: input }],
            max_completion_tokens: Math.max(maxOutput, 600),
            response_format: schema ? { type: 'json_schema', json_schema: { name: 'itlive_agent', strict: true, schema } } : undefined
          })
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        result = (await response.json()).choices?.[0]?.message?.content?.trim();
      } else if (provider === 'openai') {
        response = await fetch('https://api.openai.com/v1/responses', {
          method: 'POST', signal: AbortSignal.timeout(15000),
          headers: { Authorization: `Bearer ${keys.openai}`, 'Content-Type': 'application/json' },
          body: JSON.stringify({
            model: process.env.OPENAI_MODEL || 'gpt-4.1-mini', store: false,
            instructions, input, max_output_tokens: maxOutput,
            text: schema ? { format: { type: 'json_schema', name: 'itlive_agent', strict: true, schema } } : undefined
          })
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        result = responseText(await response.json());
      } else {
        const model = encodeURIComponent(process.env.GEMINI_MODEL || 'gemini-3.6-flash');
        response = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent`, {
          method: 'POST', signal: AbortSignal.timeout(30000),
          headers: { 'x-goog-api-key': keys.gemini, 'Content-Type': 'application/json' },
          body: JSON.stringify({
            systemInstruction: { parts: [{ text: instructions + (schema ? `\nFaqat quyidagi maydonli JSON obyekt qaytaring: ${JSON.stringify(schema)}` : '') }] },
            contents: [{ role: 'user', parts: [{ text: input }] }],
            generationConfig: { maxOutputTokens: Math.max(maxOutput, 600), thinkingConfig: { thinkingLevel: 'low' }, ...(schema ? { responseMimeType: 'application/json' } : {}) }
          })
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        result = (await response.json()).candidates?.[0]?.content?.parts?.map(x => x.text || '').join('').trim();
      }
      if (!result) throw new Error('bo‘sh javob');
      if (schema) JSON.parse(result);
      return result;
    } catch (error) { console.error(`${provider} agent request failed:`, error.message); }
  }
  return null;
}

const TASK_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    seller_id: { type: ['integer', 'null'] },
    title: { type: 'string' },
    details: { type: 'string' },
    lead_id: { type: ['integer', 'null'] },
    due_at: { type: ['string', 'null'] }
  },
  required: ['seller_id', 'title', 'details', 'lead_id', 'due_at']
};

export async function parseTask(text, sellers, keys = {}) {
  const direct = parseDirectTask(text, sellers);
  if (direct) return direct;
  const matched = resolveSeller(text, sellers);
  const fallback = fallbackTask(text, matched);
  if (!availableProviders(keys).length) return fallback;
  const roster = sellers.map(s => ({ id: Number(s.id), name: s.name, login: s.login_name }));
  const instructions = `Siz ITLIVE CRM rahbari topshirig‘ini sotuvchiga tushunarli va muloyim shaklga keltirasiz. title qisqa harakat nomi, details esa sotuvchiga bevosita murojaat qilingan ravon o‘zbekcha ko‘rsatma bo‘lsin. Mazmun, lead doirasi, muddat va sonlarni o‘zgartirmang; yangi buyruq o‘ylab topmang. Sotuvchi aniq tilga olinmasa seller_id=null. Faqat ro‘yxatdagi IDlardan foydalaning. Lead ID faqat matnda aniq ko‘rsatilsa yozilsin. due_at faqat aniq vaqt aytilsa ISO 8601 +05:00 formatida; aks holda null. Hozir: ${new Date().toISOString()}. Vaqt zonasi: Asia/Tashkent. Sotuvchilar: ${JSON.stringify(roster)}.`;
  try {
    const output = await callAI(text.slice(0, 800), TASK_SCHEMA, instructions, 450, keys);
    if (!output) return fallback;
    const parsed = JSON.parse(output);
    const lead = text.match(/(?:lead|lid|ariza)\s*#?(\d+)/i);
    return { ...parsed, seller_id: matched ? Number(matched.id) : parsed.seller_id, lead_id: lead ? Number(lead[1]) : null, due_at: taskDeadline(text) };
  } catch (error) { console.error('AI task parsing failed:', error.message); return fallback; }
}

export function formatReport(snapshot, label, insight = '') {
  const { summary: s, stages, sellers } = snapshot;
  const lines = [
    `📊 ITLIVE CRM — ${label}`,
    `Bugun yangi lead: ${s.today}; jami faol lead: ${s.open}; sotib oldi: ${s.won}; sotib olmadi: ${s.lost}.`,
    `Nazorat: ${s.unassigned} biriktirilmagan, ${s.stale_new} ta 1 soatdan ortiq yangi, ${s.overdue} qayta aloqa muddati o‘tgan, ${s.overdue_tasks} muddati o‘tgan vazifa.`,
    `Vazifalar: ${s.open_tasks} ochiq, bugun ${s.done_today} bajarilgan.`,
    `Bosqichlar: ${stages.map(x => `${x.status} ${x.count}`).join(' · ') || 'lead yo‘q'}.`
  ];
  if (sellers.length) lines.push('Sotuvchilar:\n' + sellers.map(x => `• ${x.name}: ${x.open_leads} ochiq lead, ${x.open_tasks} vazifa, ${x.won} sotuv`).join('\n'));
  if (insight) lines.push(`AI kuzatuv: ${insight.slice(0, 500)}`);
  return lines.join('\n\n').slice(0, 3900);
}

export function createAgent({ db, bot, keyStore }) {
  const query = (sql, args = []) => db.query(sql, args);
  const owner = () => bot.prepare("SELECT id,telegram_id FROM staff WHERE role='owner' AND active=1 ORDER BY id LIMIT 1").get();
  const outbox = bot.prepare('INSERT INTO notification_outbox(chat_id,lead_id,message,next_attempt_at) VALUES(?,NULL,?,?)');
  const nowIso = () => new Date().toISOString().replace(/\.\d{3}Z$/, '+00:00');
  const reply = bot.transaction((request, text) => {
    const stamp = nowIso();
    if (bot.prepare('INSERT OR IGNORE INTO agent_replies(request_id,queued_at) VALUES(?,?)').run(request.id, stamp).changes) outbox.run(request.telegram_id, text, stamp);
    bot.prepare('UPDATE agent_requests SET processed_at=? WHERE id=?').run(stamp, request.id);
  });

  async function snapshot() {
    const summary = (await query(`SELECT
      count(*) FILTER (WHERE created_at >= date_trunc('day',now() AT TIME ZONE '${ZONE}') AT TIME ZONE '${ZONE}')::int AS today,
      count(*) FILTER (WHERE ${OPEN})::int AS open,
      count(*) FILTER (WHERE status='Sotib oldi')::int AS won,
      count(*) FILTER (WHERE status='Sotib olmadi')::int AS lost,
      count(*) FILTER (WHERE ${OPEN} AND assignee_id IS NULL)::int AS unassigned,
      count(*) FILTER (WHERE status='Yangi lead' AND created_at < now()-interval '1 hour')::int AS stale_new,
      count(*) FILTER (WHERE ${OPEN} AND next_action_at < now())::int AS overdue
      FROM crm_leads WHERE NOT anonymized AND merged_into_id IS NULL`)).rows[0];
    const taskCounts = (await query(`SELECT
      count(*) FILTER (WHERE status='open')::int AS open_tasks,
      count(*) FILTER (WHERE status='open' AND due_at<now())::int AS overdue_tasks,
      count(*) FILTER (WHERE status='done' AND completed_at >= date_trunc('day',now() AT TIME ZONE '${ZONE}') AT TIME ZONE '${ZONE}')::int AS done_today
      FROM crm_tasks`)).rows[0];
    const stages = (await query('SELECT status,count(*)::int AS count FROM crm_leads WHERE NOT anonymized AND merged_into_id IS NULL GROUP BY status ORDER BY status')).rows;
    const sellers = (await query(`SELECT s.name,
      (SELECT count(*)::int FROM crm_leads l WHERE l.assignee_id=s.id AND NOT l.anonymized AND l.merged_into_id IS NULL AND ${OPEN}) AS open_leads,
      (SELECT count(*)::int FROM crm_leads l WHERE l.assignee_id=s.id AND l.status='Sotib oldi' AND NOT l.anonymized AND l.merged_into_id IS NULL) AS won,
      (SELECT count(*)::int FROM crm_tasks t WHERE t.assignee_id=s.id AND t.status='open') AS open_tasks
      FROM crm_staff s WHERE s.role='operator' AND s.active ORDER BY s.name`)).rows;
    return { summary: { ...summary, ...taskCounts }, stages, sellers };
  }

  async function report(label) {
    const data = await snapshot();
    let insight = '';
    const keys = keyStore?.values() || {};
    if (availableProviders(keys).length) {
      try {
        insight = await callAI(JSON.stringify(data), null,
          'ITLIVE rahbariga o‘zbek tilida eng muhim 1-2 nazorat xulosasini 300 belgigacha yozing. Faqat berilgan sonlarga tayaning; taxminiy pul yoki sabab o‘ylab topmang. Agar muammo bo‘lmasa shuni ayting.', 300, keys) || '';
      } catch (error) { console.error('AI report insight failed:', error.message); }
    }
    return formatReport(data, label, insight);
  }

  async function createTask(request, text, actor) {
    const sellers = (await query("SELECT id,name,login_name FROM crm_staff WHERE role='operator' AND active ORDER BY name")).rows;
    if (!sellers.length) return 'Faol sotuvchi yo‘q. Avval CRM saytida sotuvchi hisobini yarating.';
    const parsed = await parseTask(text, sellers, keyStore?.values() || {});
    let seller = resolveSeller(text, sellers);
    if (!seller && parsed?.direct) seller = sellers.find(x => Number(x.id) === Number(parsed.seller_id));
    if (!seller && parsed?.lead_id) {
      const assigned = (await query('SELECT assignee_id FROM crm_leads WHERE id=$1 AND NOT anonymized AND merged_into_id IS NULL', [parsed.lead_id])).rows[0]?.assignee_id;
      seller = sellers.find(x => Number(x.id) === Number(assigned));
    }
    if (!seller && sellers.length === 1) seller = sellers[0];
    if (!seller) return `Qaysi sotuvchiga yuboray? Ismini yozing yoki lead raqamini ayting. Faol sotuvchilar: ${sellers.map(x => `${x.name} (${x.login_name || x.id})`).join(', ').slice(0, 800)}.`;
    if (!parsed?.title?.trim()) return 'Vazifani tushunmadim. Iltimos, nima qilish kerakligini qayta yozing yoki ovoz yuboring.';
    const title = String(parsed.title).trim().slice(0, 180);
    const details = String(parsed.details || title).trim().slice(0, 800);
    let due = null;
    if (parsed.due_at) {
      const value = new Date(parsed.due_at);
      if (!Number.isNaN(value.getTime()) && value.getTime() > Date.now() && value.getTime() < Date.now() + 366 * 86400000) due = value;
    }
    const leadId = Number.isSafeInteger(Number(parsed.lead_id)) && Number(parsed.lead_id) > 0 ? Number(parsed.lead_id) : null;
    const client = await db.connect();
    try {
      await client.query('BEGIN');
      if (leadId) {
        const lead = (await client.query('SELECT id,assignee_id,anonymized,merged_into_id FROM crm_leads WHERE id=$1 FOR UPDATE', [leadId])).rows[0];
        if (!lead || lead.anonymized || lead.merged_into_id) { await client.query('ROLLBACK'); return `Lead #${leadId} topilmadi yoki yopilgan.`; }
        if (lead.assignee_id && Number(lead.assignee_id) !== Number(seller.id)) { await client.query('ROLLBACK'); return `Lead #${leadId} boshqa sotuvchiga biriktirilgan. Avval CRMda mas’ulni o‘zgartiring.`; }
        if (!lead.assignee_id) {
          await client.query('UPDATE crm_leads SET assignee_id=$2,updated_at=now() WHERE id=$1', [leadId, seller.id]);
          await client.query("INSERT INTO crm_events(lead_id,actor_id,kind,new_value,note) VALUES($1,$2,'assigned',$3,'AI agent orqali vazifa')", [leadId, actor.id, String(seller.id)]);
        }
      }
      const existing = (await client.query('SELECT id FROM crm_tasks WHERE source_request_id=$1', [request.id])).rows[0];
      const task = existing || (await client.query(`INSERT INTO crm_tasks(title,details,assignee_id,created_by,lead_id,due_at,source,source_request_id)
        VALUES($1,$2,$3,$4,$5,$6,'telegram_agent',$7) RETURNING id`, [title, details, seller.id, actor.id, leadId, due, request.id])).rows[0];
      if (!existing) await client.query("INSERT INTO crm_task_events(task_id,actor_id,kind,note) VALUES($1,$2,'created','Telegram orqali')", [task.id, actor.id]);
      await client.query('COMMIT');
      return `✅ Vazifa #${task.id} ${seller.name}ga biriktirildi. Sotuvchi uni CRM → Vazifalar bo‘limida ko‘radi.${leadId ? ` Lead #${leadId}.` : ''}${due ? ` Muddat: ${new Intl.DateTimeFormat('uz-UZ', { timeZone: ZONE, dateStyle: 'medium', timeStyle: 'short' }).format(due)}.` : ''}\n\n📝 ${title}${details !== title ? `\n${details}` : ''}`;
    } catch (error) { await client.query('ROLLBACK'); throw error; }
    finally { client.release(); }
  }

  async function processRequests() {
    const activeOwner = owner();
    if (!activeOwner) return;
    const requests = bot.prepare('SELECT * FROM agent_requests WHERE processed_at IS NULL ORDER BY id LIMIT 10').all();
    for (const request of requests) {
      if (Number(request.telegram_id) !== Number(activeOwner.telegram_id)) {
        bot.prepare('UPDATE agent_requests SET processed_at=? WHERE id=?').run(nowIso(), request.id);
        continue;
      }
      const voice = bot.prepare('SELECT audio,mime_type FROM agent_voice_files WHERE request_id=?').get(request.id);
      let message;
      if (request.kind === 'report') message = await report('Hozirgi holat');
      else if (voice) {
        const transcript = await transcribeVoice(voice.audio, voice.mime_type, keyStore?.values() || {});
        message = transcript ? `🎙 Eshitildi: ${transcript.slice(0, 500)}\n\n${await createTask(request, transcript, activeOwner)}` : 'Ovozli vazifani matnga aylantira olmadim. AI nazorat sahifasida Groq, OpenAI yoki Gemini kalitini saqlang va ovozni qayta yuboring.';
      } else message = await createTask(request, request.payload, activeOwner);
      reply(request, message);
      if (voice) bot.prepare('DELETE FROM agent_voice_files WHERE request_id=?').run(request.id);
    }
  }

  async function scheduledReport(now = new Date()) {
    const activeOwner = owner(), slot = dueReportSlot(now);
    if (!activeOwner || !slot || bot.prepare('SELECT 1 FROM agent_report_slots WHERE slot=?').get(slot)) return;
    const message = await report(`${slot.slice(0, 10)} ${slot.slice(11)}:00 (Toshkent)`);
    bot.transaction(() => {
      const stamp = nowIso();
      if (bot.prepare('INSERT OR IGNORE INTO agent_report_slots(slot,queued_at) VALUES(?,?)').run(slot, stamp).changes) outbox.run(activeOwner.telegram_id, message, stamp);
    })();
  }

  async function monitor(now = new Date()) {
    const activeOwner = owner();
    if (!activeOwner) return;
    const { day } = tashkentTime(now);
    const s = (await snapshot()).summary;
    const warnings = [
      ['unassigned', s.unassigned, 'biriktirilmagan lead'],
      ['stale', s.stale_new, '1 soatdan ortiq yangi holatda qolgan lead'],
      ['followup', s.overdue, 'muddati o‘tgan qayta aloqa'],
      ['task', s.overdue_tasks, 'muddati o‘tgan vazifa']
    ];
    for (const [key, count, label] of warnings) {
      if (!count) continue;
      bot.transaction(() => {
        const stamp = nowIso();
        if (bot.prepare('INSERT OR IGNORE INTO agent_alerts(alert_key,queued_at) VALUES(?,?)').run(`${day}:${key}`, stamp).changes)
          outbox.run(activeOwner.telegram_id, `⚠️ ITLIVE nazorat: ${count} ta ${label} bor. Batafsil holat uchun botdagi “📊 Hozirgi holat” tugmasini bosing.`, stamp);
      })();
    }
  }

  let busy = false, lastMonitor = 0;
  async function tick(now = new Date()) {
    if (busy) return;
    busy = true;
    try {
      await processRequests();
      await scheduledReport(now);
      if (now.getTime() - lastMonitor >= 5 * 60000) { await monitor(now); lastMonitor = now.getTime(); }
    } finally { busy = false; }
  }
  return { tick, snapshot, report, createTask };
}
