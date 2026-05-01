"""
service/emailService.py
Kirim email transaksional via SMTP.
Konfigurasi di settings:
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM
"""

import asyncio
import logging
import smtplib
from pathlib import Path
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

from configCredidential import settings


logger = logging.getLogger(__name__)


class EmailService:

    def __init__(self):
        self.smtp_host: str = settings.SMTP_HOST
        self.smtp_port: int = settings.SMTP_PORT
        self.smtp_user: str = settings.SMTP_USER
        self.smtp_password: str = settings.SMTP_PASSWORD
        self.smtp_from: str = settings.SMTP_FROM
        self.logo_path = (
            Path(__file__).resolve().parents[1]
            / "assets"
            / "img"
            / "amani_technology_logo.png"
        )

    def _attach_inline_logo(self, msg: MIMEMultipart) -> None:
        if not self.logo_path.exists():
            return

        with self.logo_path.open("rb") as logo_file:
            logo = MIMEImage(logo_file.read(), _subtype="png")
        logo.add_header("Content-ID", "<amani-logo>")
        logo.add_header("Content-Disposition", "inline",
                        filename=self.logo_path.name)
        msg.attach(logo)

    def _base_template(self, title: str, subtitle: str, body_html: str) -> str:
        logo_block = ""
        if self.logo_path.exists():
            logo_block = (
                "<img "
                "src=\"cid:amani-logo\" "
                "alt=\"Amani Technology\" "
                "style=\"display:block;max-height:42px;max-width:180px;width:auto;height:auto;margin-bottom:18px;\" "
                "/>"
            )

        return f"""
        <div style="margin:0;padding:28px 14px;background:#f3f5f8;">
            <div style="max-width:620px;margin:0 auto;background:#ffffff;border:1px solid #e3e8ef;border-radius:12px;padding:30px 30px 24px;color:#0f172a;font-family:'Segoe UI',Arial,sans-serif;line-height:1.55;">
                {logo_block}
                <h1 style="margin:0 0 6px;font-size:22px;font-weight:700;color:#0f172a;">{title}</h1>
                <p style="margin:0 0 22px;font-size:14px;color:#5b6575;">{subtitle}</p>
                {body_html}
                <hr style="border:none;border-top:1px solid #e7ebf1;margin:24px 0 14px;" />
                <p style="margin:0;font-size:12px;color:#7a8496;">
                    Email ini dikirim otomatis oleh sistem Amani Technology.
                </p>
            </div>
        </div>
        """

    def _build_message(self, to: str, subject: str, html: str) -> MIMEMultipart:
        msg = MIMEMultipart("related")
        msg["Subject"] = subject
        msg["From"] = self.smtp_from
        msg["To"] = to

        alternative = MIMEMultipart("alternative")
        alternative.attach(MIMEText(html, "html", "utf-8"))
        msg.attach(alternative)
        self._attach_inline_logo(msg)

        return msg

    def _send_sync(self, to: str, subject: str, html: str) -> None:
        msg = self._build_message(to, subject, html)
        with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
            server.ehlo()
            server.starttls()
            server.login(self.smtp_user, self.smtp_password)
            server.sendmail(self.smtp_from, to, msg.as_string())

    async def _send(self, to: str, subject: str, html: str) -> None:
        await asyncio.to_thread(self._send_sync, to, subject, html)

    def _run_in_background(self, coro: asyncio.Future, context: str) -> None:
        task = asyncio.create_task(coro)

        def _log_background_error(done_task: asyncio.Task) -> None:
            try:
                done_task.result()
            except Exception as exc:
                logger.warning(
                    "Background email task gagal (%s): %s", context, exc)

        task.add_done_callback(_log_background_error)

    async def send_reset_pin(self, to_email: str, full_name: str, pin: str) -> None:
        """Kirim email berisi PIN 6 digit untuk reset password."""
        subject = "Kode Reset Password Anda"
        body_html = f"""
        <p style="margin:0 0 12px;">Halo <strong>{full_name}</strong>,</p>
        <p style="margin:0 0 18px;">
            Gunakan kode berikut untuk mereset password akun Anda. Kode berlaku selama
            <strong>15 menit</strong>.
        </p>
        <div style="
            margin:0 0 18px;
            border:1px solid #dbe2ec;
            border-radius:10px;
            background:#f8fafc;
            text-align:center;
            padding:18px 16px;
            font-size:34px;
            font-weight:700;
            letter-spacing:10px;
            color:#0f172a;
        ">{pin}</div>
        <p style="margin:0;font-size:13px;color:#5b6575;">
            Jika Anda tidak meminta reset password, abaikan email ini. Jangan bagikan
            kode ini kepada siapa pun.
        </p>
        """
        html = self._base_template(
            title="Reset Password",
            subtitle="Verifikasi keamanan akun",
            body_html=body_html,
        )
        await self._send(to_email, subject, html)

    async def send_credentials_info(
        self,
        to_email: str,
        full_name: str,
        username: str,
        password: str,
        role: Any,
    ) -> None:
        """Kirim email berisi informasi akun saat user baru dibuat."""
        role_value = getattr(role, "value", str(role))
        subject = "Akun Anda Telah Dibuat"
        body_html = f"""
        <p style="margin:0 0 12px;">Halo <strong>{full_name}</strong>,</p>
        <p style="margin:0 0 18px;">
            Akun Anda pada sistem KPI telah dibuat. Gunakan informasi berikut untuk
            login pertama kali.
        </p>
        <div style="margin:0 0 18px;border:1px solid #dbe2ec;border-radius:10px;background:#f8fafc;padding:14px 16px;">
            <table style="width:100%;border-collapse:collapse;font-size:14px;">
                <tr>
                    <td style="padding:7px 0;width:130px;color:#5b6575;">Username</td>
                    <td style="padding:7px 0;font-weight:600;color:#0f172a;">{username}</td>
                </tr>
                <tr>
                    <td style="padding:7px 0;width:130px;color:#5b6575;">Email</td>
                    <td style="padding:7px 0;font-weight:600;color:#0f172a;">{to_email}</td>
                </tr>
                <tr>
                    <td style="padding:7px 0;width:130px;color:#5b6575;">Role</td>
                    <td style="padding:7px 0;font-weight:600;color:#0f172a;">{role_value}</td>
                </tr>
                <tr>
                    <td style="padding:7px 0;width:130px;color:#5b6575;">Password</td>
                    <td style="padding:7px 0;font-weight:700;letter-spacing:0.2px;color:#0f172a;">{password}</td>
                </tr>
            </table>
        </div>
        <p style="margin:0 0 10px;">
            Demi keamanan, segera ganti password setelah berhasil masuk.
        </p>
        <p style="margin:0;font-size:13px;color:#5b6575;">
            Jika Anda tidak merasa meminta pembuatan akun ini, segera hubungi administrator.
        </p>
        """
        html = self._base_template(
            title="Akun Berhasil Dibuat",
            subtitle="Informasi akses awal akun Anda",
            body_html=body_html,
        )
        await self._send(to_email, subject, html)

    def send_reset_pin_background(self, to_email: str, full_name: str, pin: str) -> None:
        self._run_in_background(
            self.send_reset_pin(
                to_email=to_email,
                full_name=full_name,
                pin=pin,
            ),
            context=f"reset-pin:{to_email}",
        )

    def send_credentials_info_background(
        self,
        to_email: str,
        full_name: str,
        username: str,
        password: str,
        role: Any,
    ) -> None:
        self._run_in_background(
            self.send_credentials_info(
                to_email=to_email,
                full_name=full_name,
                username=username,
                password=password,
                role=role,
            ),
            context=f"credentials:{to_email}",
        )
