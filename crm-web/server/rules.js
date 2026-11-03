export const STATUSES = ['Yangi lead','Bog‘lanildi','Bog‘lanib bo‘lmadi','Ma’lumot berildi','Tashrifga keldi','Sotib oldi','Sotib olmadi'];
export const CLOSED = new Set(['Sotib oldi','Sotib olmadi']);
export function mapLegacyStatus(value) {
  return ({'Yangi mijoz':'Yangi lead','Bog‘lanishga urinish':'Bog‘lanib bo‘lmadi','Telefon qilindi':'Bog‘lanildi','Qayta aloqa':'Bog‘lanildi','Uchrashuv belgilandi':'Ma’lumot berildi','Uchrashuv bo‘lib o‘tdi':'Tashrifga keldi','Sotildi':'Sotib oldi','Sotilmadi':'Sotib olmadi'})[value] || 'Yangi lead';
}
export function pickAssignee(staff, leads, cursor = 0) {
  const active = staff.filter(s => s.role === 'operator' && s.active).sort((a,b) => a.id - b.id);
  if (!active.length) return null;
  const counts = new Map(active.map(s => [Number(s.id), 0]));
  for (const lead of leads) if (!CLOSED.has(lead.status) && counts.has(Number(lead.assignee_id))) counts.set(Number(lead.assignee_id), counts.get(Number(lead.assignee_id)) + 1);
  const min = Math.min(...counts.values());
  const ties = active.filter(s => counts.get(Number(s.id)) === min);
  return ties[cursor % ties.length].id;
}
export function validateStage(status, input, prior) {
  if (!STATUSES.includes(status)) throw new Error('Noto‘g‘ri holat');
  if (status === 'Bog‘lanib bo‘lmadi' && !input.note?.trim()) throw new Error('Urinish natijasini yozing');
  if (status === 'Ma’lumot berildi' && !input.note?.trim()) throw new Error('Berilgan ma’lumotni yozing');
  if (status === 'Tashrifga keldi' && !input.note?.trim()) throw new Error('Tashrif natijasini yozing');
  if (status === 'Sotib oldi' && !(input.course_id||prior.course_id)) throw new Error('Sotilgan kursni tanlang');
  if (status === 'Sotib olmadi' && !input.lost_reason?.trim()) throw new Error('Sotib olmaslik sababini tanlang');
  if (CLOSED.has(prior.status) && prior.status !== status && !input.note?.trim()) throw new Error('Qayta ochish sababini yozing');
}
