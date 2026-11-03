import test from 'node:test';
import assert from 'node:assert/strict';
import { availableProviders, createAgent, dueReportSlot, formatReport, parseDirectTask, parseTask, resolveSeller, taskDeadline, tashkentTime, transcribeVoice } from './agent.js';

test('daily slots use Tashkent time', () => {
  assert.equal(dueReportSlot(new Date('2026-11-03T06:59:00Z')), null);
  assert.equal(dueReportSlot(new Date('2026-11-03T07:00:00Z')), '2026-11-03:12');
  assert.equal(dueReportSlot(new Date('2026-11-03T12:00:00Z')), '2026-11-03:17');
  assert.equal(tashkentTime(new Date('2026-11-03T20:00:00Z')).day, '2026-11-04');
});

test('explicit seller task extracts lead and tomorrow deadline', () => {
  const task = parseDirectTask('ali | Ertaga 15:00 lead #12 ga qo‘ng‘iroq qiling', [{id: 42, name: 'Ali Valiyev', login_name: 'ali'}]);
  assert.equal(task.seller_id, 42);
  assert.equal(task.lead_id, 12);
  assert.ok(new Date(task.due_at).getTime() > Date.now());
  assert.equal(parseDirectTask('Ali vazifa', [{id: 42, name: 'Ali', login_name: 'ali'}]), null);
});

test('natural Uzbek task resolves unique seller and dotted deadline', async () => {
  const sellers=[{id:42,name:'Bobur Karimov',login_name:'bobur1'},{id:43,name:'Ali Valiyev',login_name:'ali1'}];
  const text='bobur barcha leadlarga ertaga soat 20.00 gacha telefon qilsin';
  assert.equal(resolveSeller(text,sellers).id,42);
  assert.equal(resolveSeller('Bobur va Ali birga ishlasin',sellers),null);
  assert.equal(taskDeadline(text,new Date('2026-11-03T13:00:00Z')),'2026-11-04T15:00:00.000Z');
  const task=await parseTask(text,sellers,{});
  assert.equal(task.seller_id,42);
  assert.match(task.details,/barcha leadlarga/i);
  assert.equal(task.title,'Barcha leadlarga qo‘ng‘iroq qilish');
  const byLead=await parseTask('Lead #12 ga qo‘ng‘iroq qiling',sellers,{});
  assert.equal(byLead.seller_id,null);
  assert.equal(byLead.lead_id,12);
});

test('natural task is assigned to the named seller, not an unknown name', async () => {
  const seller={id:42,name:'Bobur Karimov',login_name:'bobur1'};
  const writes=[];
  const client={query:async(sql,args=[])=>{writes.push({sql,args});return {rows:sql.includes('RETURNING id')?[{id:7}]:[]};},release:()=>{}};
  const db={query:async()=>({rows:[seller]}),connect:async()=>client};
  const bot={prepare:()=>({run:()=>({changes:1})}),transaction:fn=>fn};
  const agent=createAgent({db,bot,keyStore:{values:()=>({})}});
  const result=await agent.createTask({id:1},'Bobur barcha leadlarga ertaga soat 20.00 gacha telefon qilsin',{id:1});
  assert.match(result,/Bobur Karimovga biriktirildi/);
  const insert=writes.find(x=>x.sql.includes('INSERT INTO crm_tasks'));
  assert.equal(insert.args[2],42);
  assert.equal(insert.args[3],1);
  assert.equal(insert.args[6],1);
  assert.match(await agent.createTask({id:2},'Ali barcha leadlarga telefon qilsin',{id:1}),/Qaysi sotuvchiga/);
  assert.equal(writes.filter(x=>x.sql.includes('INSERT INTO crm_tasks')).length,1);
});

test('voice is sent as audio to provider and transcript returned', async () => {
  const previous=globalThis.fetch;
  globalThis.fetch=async(url,options)=>{
    assert.match(url,/groq.com.*audio\/transcriptions/);
    assert.equal(options.body.get('model'),'whisper-large-v3-turbo');
    assert.equal(options.body.get('file').type,'audio/ogg');
    return {ok:true,json:async()=>({text:'Bobur barcha leadlarga qo‘ng‘iroq qilsin'})};
  };
  try { assert.match(await transcribeVoice(Buffer.from('ogg'),'audio/ogg',{groq:'test-key'}),/Bobur/); }
  finally { globalThis.fetch=previous; }
});

test('OpenAI and Gemini voice transcription use configured provider', async () => {
  const previous=globalThis.fetch;
  try {
    globalThis.fetch=async(url,options)=>{
      assert.match(url,/openai.com.*audio\/transcriptions/);
      assert.equal(options.body.get('model'),'gpt-transcribe');
      return {ok:true,json:async()=>({text:'Ali yangi leadlarni tekshirsin'})};
    };
    assert.match(await transcribeVoice(Buffer.from('ogg'),'audio/ogg',{openai:'test-key'}),/Ali/);
    globalThis.fetch=async(url,options)=>{
      assert.match(url,/generativelanguage.googleapis.com.*interactions/);
      const body=JSON.parse(options.body);
      assert.equal(body.input[1].mime_type,'audio/ogg');
      assert.equal(body.store,false);
      return {ok:true,json:async()=>({steps:[{type:'thought',content:[{type:'text',text:'internal'}]},{type:'model_output',content:[{type:'text',text:'Bobur leadlarga telefon qilsin'}]}]})};
    };
    assert.match(await transcribeVoice(Buffer.from('ogg'),'audio/ogg',{gemini:'test-key'}),/Bobur/);
  } finally { globalThis.fetch=previous; }
});

test('report contains verifiable counts and seller load', () => {
  const text = formatReport({
    summary: {today: 2, open: 3, won: 1, lost: 0, unassigned: 1, stale_new: 1, overdue: 2, overdue_tasks: 1, open_tasks: 3, done_today: 1},
    stages: [{status: 'Yangi lead', count: 2}], sellers: [{name: 'Ali', open_leads: 2, open_tasks: 1, won: 1}]
  }, 'test');
  assert.match(text, /Bugun yangi lead: 2/);
  assert.match(text, /Ali: 2 ochiq lead/);
});

test('AI parser accepts structured output without sending private leads', async () => {
  const priorKey = process.env.OPENAI_API_KEY;
  const priorProvider = process.env.AI_PROVIDER;
  const priorFetch = globalThis.fetch;
  process.env.OPENAI_API_KEY = 'test-key';
  process.env.AI_PROVIDER = 'openai';
  let request;
  globalThis.fetch = async (_url, options) => {
    request = JSON.parse(options.body);
    return { ok: true, json: async () => ({ output: [{ content: [{ type: 'output_text', text: JSON.stringify({ seller_id: 42, title: 'Qo‘ng‘iroq', details: 'Ali lead #12 ga qo‘ng‘iroq qilsin', lead_id: 12, due_at: null }) }] }] }) };
  };
  try {
    const parsed = await parseTask('Ali lead #12 ga qo‘ng‘iroq qilsin', [{ id: 42, name: 'Ali Valiyev', login_name: 'ali' }]);
    assert.equal(parsed.seller_id, 42);
    assert.equal(request.text.format.type, 'json_schema');
    assert.equal(request.store, false);
  } finally {
    globalThis.fetch = priorFetch;
    if (priorKey === undefined) delete process.env.OPENAI_API_KEY;
    else process.env.OPENAI_API_KEY = priorKey;
    if (priorProvider === undefined) delete process.env.AI_PROVIDER;
    else process.env.AI_PROVIDER = priorProvider;
  }
});

test('Groq falls back to OpenAI when its API fails', async () => {
  const original = { groq: process.env.GROQ_API_KEY, openai: process.env.OPENAI_API_KEY, gemini: process.env.GEMINI_API_KEY, provider: process.env.AI_PROVIDER, fetch: globalThis.fetch };
  process.env.GROQ_API_KEY = 'groq-test'; process.env.OPENAI_API_KEY = 'openai-test';
  delete process.env.GEMINI_API_KEY; process.env.AI_PROVIDER = 'groq';
  const urls = [];
  globalThis.fetch = async (url) => {
    urls.push(url);
    if (urls.length === 1) return { ok: false, status: 503 };
    return { ok: true, json: async () => ({ output: [{ content: [{ type: 'output_text', text: JSON.stringify({ seller_id: 42, title: 'Qo‘ng‘iroq', details: 'Ali qo‘ng‘iroq qilsin', lead_id: null, due_at: null }) }] }] }) };
  };
  try {
    assert.deepEqual(availableProviders(), ['groq', 'openai']);
    const result = await parseTask('Ali qo‘ng‘iroq qilsin', [{ id: 42, name: 'Ali', login_name: 'ali' }]);
    assert.equal(result.seller_id, 42);
    assert.match(urls[0], /groq/); assert.match(urls[1], /openai/);
  } finally {
    globalThis.fetch = original.fetch;
    for (const [key, value] of [['GROQ_API_KEY', original.groq], ['OPENAI_API_KEY', original.openai], ['GEMINI_API_KEY', original.gemini], ['AI_PROVIDER', original.provider]]) {
      if (value === undefined) delete process.env[key]; else process.env[key] = value;
    }
  }
});

test('Gemini structured JSON response is parsed', async () => {
  const original = { groq: process.env.GROQ_API_KEY, openai: process.env.OPENAI_API_KEY, gemini: process.env.GEMINI_API_KEY, provider: process.env.AI_PROVIDER, fetch: globalThis.fetch };
  delete process.env.GROQ_API_KEY; delete process.env.OPENAI_API_KEY;
  process.env.GEMINI_API_KEY = 'gemini-test'; process.env.AI_PROVIDER = 'gemini';
  globalThis.fetch = async (url, options) => {
    assert.match(url, /generativelanguage\.googleapis\.com/);
    assert.equal(JSON.parse(options.body).generationConfig.responseMimeType, 'application/json');
    return { ok: true, json: async () => ({ candidates: [{ content: { parts: [{ text: JSON.stringify({ seller_id: 42, title: 'Qo‘ng‘iroq', details: 'Ali qo‘ng‘iroq qilsin', lead_id: null, due_at: null }) }] } }] }) };
  };
  try {
    const result = await parseTask('Ali qo‘ng‘iroq qilsin', [{ id: 42, name: 'Ali', login_name: 'ali' }]);
    assert.equal(result.seller_id, 42);
  } finally {
    globalThis.fetch = original.fetch;
    for (const [key, value] of [['GROQ_API_KEY', original.groq], ['OPENAI_API_KEY', original.openai], ['GEMINI_API_KEY', original.gemini], ['AI_PROVIDER', original.provider]]) {
      if (value === undefined) delete process.env[key]; else process.env[key] = value;
    }
  }
});
