import crypto from 'node:crypto';

export const AI_PROVIDERS = ['groq', 'openai', 'gemini'];
const ENV_NAMES = { groq: 'GROQ_API_KEY', openai: 'OPENAI_API_KEY', gemini: 'GEMINI_API_KEY' };

function masterKey(hex) {
  if (!/^[a-f0-9]{64}$/i.test(String(hex || ''))) throw new Error('AI_ENCRYPTION_KEY 32 baytli hex kalit bo‘lishi kerak');
  return Buffer.from(hex, 'hex');
}

export function encryptAIKey(master, provider, value) {
  if (!AI_PROVIDERS.includes(provider)) throw new Error('AI provayder noto‘g‘ri');
  if (!/^[A-Za-z0-9_.-]{10,300}$/.test(String(value || ''))) throw new Error('API kalit formati noto‘g‘ri');
  const iv = crypto.randomBytes(12);
  const cipher = crypto.createCipheriv('aes-256-gcm', masterKey(master), iv);
  cipher.setAAD(Buffer.from(provider));
  const encrypted = Buffer.concat([cipher.update(value, 'utf8'), cipher.final()]);
  return Buffer.concat([iv, cipher.getAuthTag(), encrypted]).toString('base64url');
}

export function decryptAIKey(master, provider, packed) {
  if (!AI_PROVIDERS.includes(provider)) throw new Error('AI provayder noto‘g‘ri');
  const data = Buffer.from(packed, 'base64url');
  if (data.length < 29) throw new Error('Shifrlangan API kalit buzilgan');
  const decipher = crypto.createDecipheriv('aes-256-gcm', masterKey(master), data.subarray(0, 12));
  decipher.setAAD(Buffer.from(provider));
  decipher.setAuthTag(data.subarray(12, 28));
  return Buffer.concat([decipher.update(data.subarray(28)), decipher.final()]).toString('utf8');
}

export function createAIKeyStore(db, master) {
  masterKey(master);
  let stored = {};
  const environment = () => Object.fromEntries(AI_PROVIDERS.map(p => [p, process.env[ENV_NAMES[p]] || '']));
  return {
    async load() {
      const rows = (await db.query('SELECT provider,ciphertext FROM crm_ai_keys')).rows;
      stored = Object.fromEntries(rows.map(row => [row.provider, decryptAIKey(master, row.provider, row.ciphertext)]));
    },
    values() { return { ...environment(), ...stored }; },
    names() { const values = this.values(); return AI_PROVIDERS.filter(p => !!values[p]); },
    async save(provider, value) {
      const encrypted = encryptAIKey(master, provider, value);
      await db.query(`INSERT INTO crm_ai_keys(provider,ciphertext,updated_at) VALUES($1,$2,now())
        ON CONFLICT(provider) DO UPDATE SET ciphertext=EXCLUDED.ciphertext,updated_at=now()`, [provider, encrypted]);
      stored = { ...stored, [provider]: value };
    },
    async remove(provider) {
      if (!AI_PROVIDERS.includes(provider)) throw new Error('AI provayder noto‘g‘ri');
      await db.query('DELETE FROM crm_ai_keys WHERE provider=$1', [provider]);
      const next = { ...stored }; delete next[provider]; stored = next;
    }
  };
}
