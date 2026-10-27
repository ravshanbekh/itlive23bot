# ITLIVE qabul boti va CRM

Manba TZ: [[02-Loyihalar/ITLIVE — Telegram qabul boti va admin paneli — TZ]]. Python 3.12+, aiogram 3, aiohttp, Jinja2, SQLite. Bir Railway servisida webhook va panel ishlaydi.

## Mahalliy ishga tushirish

```powershell
cd 'E:\Second-Brain\02-Loyihalar\itlive-qabul'
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
Copy-Item .env.example .env
# .env qiymatlarini muhit o‘zgaruvchisi sifatida yuklang; Python .env ni avtomatik o‘qimaydi.
python -m itlive
```

`BOT_TOKEN`, `PUBLIC_BASE_URL`, `WEBHOOK_SECRET`, `SESSION_SECRET` (kamida 32 belgi), `OWNER_TELEGRAM_ID`, `SQLITE_PATH` va `TZ=Asia/Tashkent` sozlang. `PUBLIC_BASE_URL` haqiqiy HTTPS bo‘lishi kerak. Mahalliy test uchun `DEV_MODE=1`, `SQLITE_PATH=./itlive.sqlite3` va `PORT=8080` yetadi; bunda bot ulanmaydi, `/health` ishlaydi. Ishlab chiqarishda `DEV_MODE=0`.

Haqiqiy botni domensiz mahalliy sinash uchun `BOT_MODE=polling`, `BOT_TOKEN`, `OWNER_TELEGRAM_ID`, `PUBLIC_BASE_URL=http://127.0.0.1:8080` va `SQLITE_PATH=./itlive.sqlite3` kiriting. Bot ishlaydi, panel havolasi faqat shu kompyuterda ochiladi. Bu rejimda webhook o‘chiriladi; Railway’ga o‘tganda `BOT_MODE=webhook` qiling.

## Contabo / Docker Compose

Domensiz server uchun bot `polling` rejimida ishlaydi. Panelning 8765 porti faqat serverning `127.0.0.1` manzilida ochiladi. `.env` faylini Gitga qo‘shmang.

```bash
git clone https://github.com/ravshanbekh/itlive23bot.git /opt/itlive23bot
cd /opt/itlive23bot
mkdir -p data
chown 10001:10001 data
chmod 700 data
umask 077
cat > .env <<'EOF'
BOT_MODE=polling
DEV_MODE=1
BOT_TOKEN=BOTFATHER_TOKENINI_SHU_YERGA_KIRITING
OWNER_TELEGRAM_ID=TELEGRAM_ID
PUBLIC_BASE_URL=http://127.0.0.1:8765
SESSION_SECRET=KAMIDA_32_BELGILI_TASODIFIY_QIYMAT
EOF
chmod 600 .env
docker compose up -d --build
docker compose ps
curl -fsS http://127.0.0.1:8765/health
```

Panelga kirish uchun kompyuteringizda `ssh -L 8765:127.0.0.1:8765 root@SERVER_IP` tunnelini oching. So‘ng botga `/admin` yuboring va kelgan lokal havolani shu kompyuterda oching. Serverning 8765 portini Internetga ochmang. Botga `restarting` holati tushsa `docker compose logs --tail 100 app` bilan tekshiring. Serverdagi `data/` papkasi SQLite bazasini saqlaydi; zaxira uchun `python -m itlive.backup` yoki hostdagi SQLite online backup usulidan foydalaning.

Kundalik lokal zaxirani yoqish:

```bash
install -m 0644 deploy/itlive-backup.service /etc/systemd/system/
install -m 0644 deploy/itlive-backup.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now itlive-backup.timer
systemctl start itlive-backup.service
systemctl status itlive-backup.service --no-pager
systemctl list-timers itlive-backup.timer
```

Timer 21:30 UTC atrofida ishlaydi (Toshkentda ertasi kuni 02:30). `backups/` serverning o‘z diskida qoladi; ofsayt nusxa uchun alohida manzil va kirish ma’lumoti kerak. Yangilash: `git pull --ff-only`, `docker compose up -d --build`, so‘ng `/health` va loglarni tekshiring. Bir token bilan ikki joyda polling ishlatmang.

## Railway

1. Ushbu papkani alohida Git repo sifatida yoki loyiha root sifatida Railway’ga ulang.
2. Persistent Volume’ni `/data` ga ulang; `SQLITE_PATH=/data/itlive.sqlite3`.
3. HTTPS domain oling va `PUBLIC_BASE_URL`ga yozing; qolgan majburiy sirlarni Railway Variables’da kiriting.
4. Bir replika ishlating. Start komandasi `python -m itlive`. `/health` readiness manzili.
5. BotFather tokeni bilan egasi botga `/start`, so‘ng `/admin` yuboradi. Bir martalik havola orqali panel ochiladi.
6. Panelda kontent va operatorlarni kiriting. Faol kursning tavsifi, faol filialning manzili, mentorning biosi bo‘lmasa bot kartani ko‘rsatmaydi.
7. Test ariza qoldiring, admin xabari va panel status tarixini tekshiring. Railway Volume backup va tiklashni alohida sinang.

Ommaviy botni ishga tushirish uchun haqiqiy token, domen, egasi IDsi, tasdiqlangan kontent va maxfiylik siyosati kerak. Sirlarni Gitga yozmang.

## Xavfsizlik va ma’lumot

Webhook maxfiy headerni tekshiradi. `/admin` Telegram ID ruxsati asosida 10 daqiqalik bir martalik link beradi. Panelda 8 soatlik HttpOnly/SameSite sessiya va POST amallarida CSRF token bor. Operator faqat o‘ziga biriktirilgan lidni ko‘radi. CSV faqat admin/egasiga ochiq. Telefon va shaxsiy ma’lumotni logga yozmang. O‘chirish so‘rovi egasi panelida ko‘rinadi.

SQLite faylini xizmat ishlayotganda oddiy `Copy-Item` bilan zaxiralash o‘rniga Railway Volume backup yoki SQLite online backup API’dan foydalaning. Tiklashni alohida muhitda tekshiring.

```powershell
python -m itlive.backup create /data/itlive.sqlite3 /data/backups/itlive-2026-10-20.sqlite3
python -m itlive.backup verify /data/backups/itlive-2026-10-20.sqlite3
```

Tiklashda servisni to‘xtating, tekshirilgan backupni yangi volume yoki alohida servisga joylang va `/health`, arizalar hamda eslatmalarni tekshiring. Railway Volume backupini ham muntazam yoqing.

## Test

```powershell
python -m pytest -q
```
