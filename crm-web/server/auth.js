import crypto from 'node:crypto';
export function passwordHash(password, salt=crypto.randomBytes(16).toString('hex')){
  if(typeof password!=='string'||password.length<12||password.length>128)throw new Error('Parol kamida 12 belgidan iborat bo‘lsin');
  return `${salt}:${crypto.scryptSync(password,salt,64).toString('hex')}`;
}
export function verifyPassword(password,stored){
  if(!stored||typeof password!=='string')return false;
  const [salt,hash]=stored.split(':');if(!salt||!hash||hash.length!==128)return false;
  const actual=crypto.scryptSync(password,salt,64);return crypto.timingSafeEqual(actual,Buffer.from(hash,'hex'));
}
