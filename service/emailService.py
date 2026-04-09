"""
service/emailService.py
Kirim email transaksional via SMTP.
Konfigurasi di settings:
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM
"""

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from config import settings


class EmailService:

    def __init__(self):
        self.smtp_host: str = settings.SMTP_HOST
        self.smtp_port: int = settings.SMTP_PORT
        self.smtp_user: str = settings.SMTP_USER
        self.smtp_password: str = settings.SMTP_PASSWORD
        self.smtp_from: str = settings.SMTP_FROM

    def _build_message(self, to: str, subject: str, html: str) -> MIMEMultipart:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self.smtp_from
        msg["To"] = to
        msg.attach(MIMEText(html, "html", "utf-8"))
        return msg

    def _send(self, to: str, subject: str, html: str) -> None:
        msg = self._build_message(to, subject, html)
        with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
            server.ehlo()
            server.starttls()
            server.login(self.smtp_user, self.smtp_password)
            server.sendmail(self.smtp_from, to, msg.as_string())

    def send_reset_pin(self, to_email: str, full_name: str, pin: str) -> None:
        """Kirim email berisi PIN 6 digit untuk reset password."""
        subject = "Kode Reset Password Anda"
        html = f"""
        <div style="font-family: sans-serif; max-width: 480px; margin: auto;">
            <h2 style="color: #1a1a2e;">Reset Password</h2>
            <p>Halo <strong>{full_name}</strong>,</p>
            <p>Gunakan kode berikut untuk mereset password Anda.
               Kode berlaku selama <strong>15 menit</strong>.</p>
            <div style="
                font-size: 36px;
                font-weight: bold;
                letter-spacing: 12px;
                text-align: center;
                padding: 24px;
                background: #f4f4f8;
                border-radius: 8px;
                margin: 24px 0;
                color: #1a1a2e;
            ">{pin}</div>
            <p style="color: #666; font-size: 13px;">
                Jika Anda tidak meminta reset password, abaikan email ini.
                Jangan bagikan kode ini kepada siapapun.
            </p>
        </div>
        """
        self._send(to_email, subject, html)
