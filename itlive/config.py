from dataclasses import dataclass
import os
from pathlib import Path
from urllib.parse import urlparse


@dataclass(frozen=True)
class Config:
    bot_token: str
    public_base_url: str
    webhook_secret: str
    session_secret: str
    owner_telegram_id: int
    sqlite_path: Path
    port: int = 8080
    dev_mode: bool = False
    bot_mode: str = "webhook"

    @classmethod
    def from_env(cls) -> "Config":
        dev = os.getenv("DEV_MODE") == "1"
        mode=os.getenv("BOT_MODE","webhook")
        if mode not in ("webhook","polling"):
            raise ValueError("BOT_MODE webhook yoki polling bo‘lishi kerak")
        required = ("BOT_TOKEN", "OWNER_TELEGRAM_ID") if mode=="polling" else ("BOT_TOKEN", "PUBLIC_BASE_URL", "WEBHOOK_SECRET", "SESSION_SECRET", "OWNER_TELEGRAM_ID")
        missing = [key for key in required if not os.getenv(key)]
        if missing and not dev:
            raise ValueError("Majburiy muhit sozlamalari yo‘q: " + ", ".join(missing))
        if dev and os.getenv("BOT_TOKEN") and missing:
            raise ValueError("Botni ulash uchun barcha majburiy sozlamalarni kiriting")
        url = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
        parsed=urlparse(url)
        local_polling=mode=="polling" and parsed.scheme=="http" and parsed.hostname in ("localhost","127.0.0.1")
        if url and (not parsed.netloc or (parsed.scheme != "https" and not local_polling)):
            raise ValueError("PUBLIC_BASE_URL ommaviy HTTPS manzil bo‘lishi kerak")
        secret = os.getenv("WEBHOOK_SECRET", "")
        if secret and not all(ch.isalnum() or ch in "_-" for ch in secret):
            raise ValueError("WEBHOOK_SECRET faqat A-Z, 0-9, _ va - belgilaridan iborat bo‘lsin")
        if secret and len(secret)<16:
            raise ValueError("WEBHOOK_SECRET kamida 16 belgi bo‘lsin")
        session = os.getenv("SESSION_SECRET", "")
        if session and len(session) < 32:
            raise ValueError("SESSION_SECRET kamida 32 belgi bo‘lsin")
        return cls(
            os.getenv("BOT_TOKEN", ""), url, secret, session,
            int(os.getenv("OWNER_TELEGRAM_ID", "0")),
            Path(os.getenv("SQLITE_PATH", "./itlive.sqlite3")),
            int(os.getenv("PORT", "8080")), dev, mode,
        )
