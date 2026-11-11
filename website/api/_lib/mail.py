"""Password-reset emails — the ONLY email this site ever sends.

Settings (Vercel ▸ Project ▸ Settings ▸ Environment Variables, never in the repo):
  SMTP_USER   the sending Gmail address
  SMTP_PASS   a Gmail *app password* (Google Account ▸ Security ▸ 2-Step Verification ▸ App passwords)
  SMTP_HOST / SMTP_PORT   optional (default smtp.gmail.com:465)
Without them, "forgot password" says that email reset isn't available yet."""
from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage

sent_for_tests: list[dict] = []          # tests set ANKAR_MAIL_TEST=1 and read this instead of sending


def configured() -> bool:
    return os.environ.get("ANKAR_MAIL_TEST") == "1" or bool(os.environ.get("SMTP_USER") and os.environ.get("SMTP_PASS"))


def send_reset_code(to: str, username: str, code: str, site: str):
    msg = EmailMessage()
    msg["Subject"] = f"AnKar Video Editor: your password reset code {code}"
    msg["From"] = f"AnKar Video Editor <{os.environ.get('SMTP_USER', 'noreply@example.invalid')}>"
    msg["To"] = to
    msg.set_content(
        f"Hi {username},\n\n"
        f"Your code to reset your AnKar Video Editor password is:\n\n    {code}\n\n"
        f"It works once, for 15 minutes, on {site}/forgot\n\n"
        "If you didn't ask for this, ignore this email — your password stays the same.\n\n"
        "This is the only kind of email AnKar Video Editor sends. Your address is used for nothing else.\n")
    if os.environ.get("ANKAR_MAIL_TEST") == "1":
        sent_for_tests.append({"to": to, "code": code, "subject": msg["Subject"]})
        return
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", "465"))
    with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(), timeout=15) as s:
        s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASS"])
        s.send_message(msg)
