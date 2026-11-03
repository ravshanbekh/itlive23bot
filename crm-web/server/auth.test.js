import test from 'node:test';
import assert from 'node:assert/strict';
import {passwordHash,verifyPassword} from './auth.js';
test('seller password is salted and verified',()=>{
  const one=passwordHash('long secret 123');const two=passwordHash('long secret 123');
  assert.notEqual(one,two);
  assert.equal(verifyPassword('long secret 123',one),true);
  assert.equal(verifyPassword('wrong password',one),false);
  assert.throws(()=>passwordHash('short'),/12/);
});
