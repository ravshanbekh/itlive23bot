import test from 'node:test';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import { createAIKeyStore, decryptAIKey, encryptAIKey } from './ai-keys.js';

test('provider keys use randomized authenticated encryption', () => {
  const master = crypto.randomBytes(32).toString('hex');
  const value = 'gsk_example-secret-key-12345';
  const first = encryptAIKey(master, 'groq', value);
  const second = encryptAIKey(master, 'groq', value);
  assert.notEqual(first, second);
  assert.equal(decryptAIKey(master, 'groq', first), value);
  assert.throws(() => decryptAIKey(master, 'openai', first));
  assert.throws(() => decryptAIKey(crypto.randomBytes(32).toString('hex'), 'groq', first));
  assert.ok(!first.includes(value));
});

test('key store reports configured providers without returning them in status', async () => {
  const master = crypto.randomBytes(32).toString('hex');
  const rows = new Map();
  const db = { query: async (sql, args = []) => {
    if (sql.startsWith('SELECT')) return { rows: [...rows].map(([provider, ciphertext]) => ({ provider, ciphertext })) };
    if (sql.startsWith('INSERT')) rows.set(args[0], args[1]);
    if (sql.startsWith('DELETE')) rows.delete(args[0]);
    return { rows: [] };
  } };
  const store = createAIKeyStore(db, master);
  await store.save('gemini', 'AIzaExampleSecretKey12345');
  assert.ok(store.names().includes('gemini'));
  assert.equal(store.values().gemini, 'AIzaExampleSecretKey12345');
  const restarted = createAIKeyStore(db, master);
  await restarted.load();
  assert.equal(restarted.values().gemini, 'AIzaExampleSecretKey12345');
  await restarted.remove('gemini');
  assert.ok(!restarted.names().includes('gemini'));
});
