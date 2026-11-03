import test from 'node:test';
import assert from 'node:assert/strict';
import { mapLegacyStatus, pickAssignee, validateStage } from './rules.js';

test('legacy bot states map into seven CRM stages', () => {
  assert.equal(mapLegacyStatus('Uchrashuv bo‘lib o‘tdi'), 'Tashrifga keldi');
  assert.equal(mapLegacyStatus('Sotildi'), 'Sotib oldi');
});
test('assignment balances active sellers and ignores closed leads', () => {
  const staff = [{id:1,role:'operator',active:true},{id:2,role:'operator',active:true},{id:3,role:'operator',active:false}];
  const leads = [{assignee_id:1,status:'Yangi lead'},{assignee_id:2,status:'Sotib oldi'}];
  assert.equal(pickAssignee(staff,leads), 2);
  assert.equal(pickAssignee(staff,[],1), 2);
});
test('stage changes require outcome details', () => {
  assert.throws(() => validateStage('Sotib olmadi',{},{}), /sababini/);
  assert.throws(() => validateStage('Yangi lead',{}, {status:'Sotib oldi'}), /Qayta ochish/);
  assert.doesNotThrow(() => validateStage('Sotib olmadi',{lost_reason:'narx'},{status:'Yangi lead'}));
});
