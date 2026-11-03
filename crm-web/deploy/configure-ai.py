"""Securely add an AI provider key to the server's CRM environment."""

from getpass import getpass
from pathlib import Path
import os
import re
import subprocess
import tempfile
import time


PROVIDERS = {
    "1": ("Groq", "GROQ_API_KEY", "groq"),
    "2": ("OpenAI", "OPENAI_API_KEY", "openai"),
    "3": ("Gemini", "GEMINI_API_KEY", "gemini"),
}


def save_key(env_path: Path, variable: str, provider: str, key: str) -> None:
    if variable not in {item[1] for item in PROVIDERS.values()} or provider not in {item[2] for item in PROVIDERS.values()}:
        raise ValueError("Noto‘g‘ri provayder")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{10,300}", key):
        raise ValueError("Kalit formati noto‘g‘ri")
    if not env_path.is_file():
        raise FileNotFoundError(f"CRM .env topilmadi: {env_path}")
    lines = env_path.read_text(encoding="utf-8").splitlines()
    updates = {variable: key, "AI_PROVIDER": provider}
    cleaned = [line for line in lines if not any(re.match(rf"^\s*{name}\s*=", line) for name in updates)]
    cleaned.extend(f"{name}={value}" for name, value in updates.items())
    payload = ("\n".join(cleaned) + "\n").encode("utf-8")
    fd, temporary = tempfile.mkstemp(prefix=".env.ai-", dir=env_path.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            if hasattr(os, "fchmod"):
                os.fchmod(output.fileno(), 0o600)
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, env_path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    print("AI provayderni tanlang: 1) Groq  2) OpenAI  3) Gemini")
    choice = input("Raqam: ").strip()
    if choice not in PROVIDERS:
        raise SystemExit("Noto‘g‘ri tanlov")
    label, variable, provider = PROVIDERS[choice]
    key = getpass(f"{label} API kaliti (ekranda ko‘rinmaydi): ").strip()
    save_key(root / ".env", variable, provider, key)
    key = ""
    print(f"{label} kaliti saqlandi. CRM qayta ishga tushirilmoqda...")
    subprocess.run(["docker", "compose", "up", "-d", "--no-deps", "--force-recreate", "crm"], cwd=root, check=True)
    health = ["docker", "compose", "exec", "-T", "crm", "node", "-e",
              "fetch('http://127.0.0.1:8787/crm/health').then(r=>{if(!r.ok)process.exit(1)}).catch(()=>process.exit(1))"]
    for _ in range(30):
        result = subprocess.run(health, cwd=root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        if result.returncode == 0:
            print("CRM sog‘lom. Botdagi “🤖 AI nazorat” tugmasini sinab ko‘ring.")
            return
        time.sleep(2)
    raise SystemExit("CRM health tekshiruvidan o‘tmadi; docker compose logs --tail 50 crm bilan tekshiring.")


if __name__ == "__main__":
    main()
