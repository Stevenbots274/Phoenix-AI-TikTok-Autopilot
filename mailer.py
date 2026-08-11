"""Branded transactional email delivery for Phoenix Autopilot."""

from __future__ import annotations

import html
import os
import smtplib
import ssl
from email.message import EmailMessage


class MailDeliveryError(RuntimeError):
    pass


class Mailer:
    def __init__(self):
        self.host = os.getenv("SMTP_HOST", "smtp.zoho.com")
        self.port = int(os.getenv("SMTP_PORT", "465"))
        self.username = os.getenv("SMTP_USERNAME", "")
        self.password = os.getenv("SMTP_PASSWORD", "")
        self.from_email = os.getenv("SMTP_FROM_EMAIL", "no-reply-tiktok@senseiphoenix.name.ng")
        self.from_name = os.getenv("SMTP_FROM_NAME", "Phoenix Autopilot")

    @property
    def configured(self) -> bool:
        return bool(self.host and self.username and self.password and self.from_email)

    def send_template(
        self,
        template: str,
        recipients: list[str],
        context: dict,
        reply_to: str | None = None,
    ) -> None:
        if not self.configured:
            raise MailDeliveryError("Transactional email is not configured.")
        subject, text, markup = render_template(template, context)
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = f"{self.from_name} <{self.from_email}>"
        message["To"] = ", ".join(recipients)
        if reply_to:
            message["Reply-To"] = reply_to
        message.set_content(text)
        message.add_alternative(markup, subtype="html")
        try:
            if self.port == 465:
                with smtplib.SMTP_SSL(self.host, self.port, context=ssl.create_default_context(), timeout=20) as smtp:
                    smtp.login(self.username, self.password)
                    smtp.send_message(message)
            else:
                with smtplib.SMTP(self.host, self.port, timeout=20) as smtp:
                    smtp.ehlo()
                    smtp.starttls(context=ssl.create_default_context())
                    smtp.ehlo()
                    smtp.login(self.username, self.password)
                    smtp.send_message(message)
        except (OSError, smtplib.SMTPException) as error:
            raise MailDeliveryError(f"Email delivery failed: {error}") from error


def render_template(template: str, context: dict) -> tuple[str, str, str]:
    name = html.escape(str(context.get("name") or "Creator"))
    topic = html.escape(str(context.get("topic") or "your Phoenix post"))
    link = html.escape(str(context.get("link") or "https://tiktok.senseiphoenix.name.ng/app"), quote=True)
    tiktok_url = html.escape(str(context.get("tiktok_url") or ""), quote=True)
    error = html.escape(str(context.get("error") or "TikTok could not complete the request."))
    scheduled_at = html.escape(str(context.get("scheduled_at") or "your selected time"))
    username = html.escape(str(context.get("username") or "your TikTok account"))
    support = html.escape(os.getenv("SUPPORT_EMAIL", "support.tiktok@senseiphoenix.name.ng"))

    if template == "verification":
        subject = "Verify your Phoenix email"
        title = "Verify your email"
        text = f"Hi {name},\n\nVerify your Phoenix account here:\n{link}\n\nThis link expires in 24 hours. If you did not create this account, you can ignore this email.\n\nPhoenix Autopilot"
        body = f"<p>Hi {name},</p><p>One click confirms this email and unlocks your Phoenix workspace.</p>{_button(link, 'Verify email')}<p class=\"muted\">This link expires in 24 hours. If you did not create this account, you can ignore this email.</p>"
    elif template == "email_verified":
        subject = "Your Phoenix email is verified"
        title = "You are verified"
        text = f"Hi {name},\n\nYour Phoenix email is verified. Open your workspace:\n{link}\n\nPhoenix Autopilot"
        body = f"<p>Hi {name},</p><p>Your email is verified and your workspace is ready.</p>{_button(link, 'Open workspace')}"
    elif template == "content_ready":
        subject = f"New Phoenix post ready: {topic}"
        title = "New content is ready"
        text = f"Hi {name},\n\nPhoenix created: {topic}\nOpen your workspace: {link}\n\nPhoenix Autopilot"
        body = f"<p>Hi {name},</p><p>Phoenix created a new post:</p><h2>{topic}</h2>{_button(link, 'Open post')}"
    elif template == "post_scheduled":
        subject = f"TikTok post scheduled: {topic}"
        title = "Post scheduled"
        text = f"Hi {name},\n\n{topic} is scheduled for {scheduled_at}.\nOpen Phoenix: {link}\n\nPhoenix Autopilot"
        body = f"<p>Hi {name},</p><p><strong>{topic}</strong> is scheduled for {scheduled_at}.</p>{_button(link, 'View publishing queue')}"
    elif template == "post_published":
        subject = f"Your TikTok post is live: {topic}"
        title = "Your post is live"
        text = f"Hi {name},\n\nPhoenix published {topic} to {username}.\nOpen it on TikTok: {tiktok_url}\n\nPhoenix Autopilot"
        body = f"<p>Hi {name},</p><p>Phoenix published <strong>{topic}</strong> to {username}.</p>{_button(tiktok_url, 'Open on TikTok')}"
    elif template == "post_failed":
        subject = f"TikTok publishing needs attention: {topic}"
        title = "Publishing needs attention"
        text = f"Hi {name},\n\nPhoenix could not publish {topic}.\nReason: {error}\nOpen Phoenix: {link}\nSupport: {support}\n\nPhoenix Autopilot"
        body = f"<p>Hi {name},</p><p>Phoenix could not publish <strong>{topic}</strong>.</p><p class=\"error\">{error}</p>{_button(link, 'Open workspace')}<p class=\"muted\">Need help? Email {support}.</p>"
    elif template == "tiktok_connected":
        subject = "TikTok account connected to Phoenix"
        title = "TikTok connected"
        text = f"Hi {name},\n\n{username} is now connected to Phoenix.\nOpen Phoenix: {link}\n\nPhoenix Autopilot"
        body = f"<p>Hi {name},</p><p><strong>{username}</strong> is now connected to Phoenix.</p>{_button(link, 'Open workspace')}"
    elif template == "tiktok_disconnected":
        subject = "TikTok account disconnected from Phoenix"
        title = "TikTok disconnected"
        text = f"Hi {name},\n\nYour TikTok connection was disconnected. Phoenix will not publish until you connect it again.\nOpen Phoenix: {link}\n\nPhoenix Autopilot"
        body = f"<p>Hi {name},</p><p>Your TikTok connection was disconnected. Phoenix will not publish until you connect it again.</p>{_button(link, 'Manage connection')}"
    elif template == "automation":
        active = bool(context.get("active"))
        subject = f"Phoenix Autopilot {'enabled' if active else 'paused'}"
        title = "Autopilot enabled" if active else "Autopilot paused"
        text = f"Hi {name},\n\nPhoenix Autopilot is {'now active' if active else 'paused'}.\nOpen Phoenix: {link}\n\nPhoenix Autopilot"
        body = f"<p>Hi {name},</p><p>Phoenix Autopilot is <strong>{'now active' if active else 'paused'}</strong>.</p>{_button(link, 'Open settings')}"
    else:
        raise MailDeliveryError(f"Unknown email template: {template}")
    return subject, text, _layout(title, body)


def _button(url: str, label: str) -> str:
    return f'<p><a class="button" href="{url}">{label}</a></p>'


def _layout(title: str, body: str) -> str:
    return f"""<!doctype html><html><body style=\"margin:0;background:#f5f4ef;color:#171a21;font-family:Arial,sans-serif\"><div style=\"max-width:620px;margin:32px auto;padding:0 18px\"><div style=\"background:#191d27;color:#fff;padding:22px 26px;border-radius:18px 18px 0 0\"><strong style=\"font-size:18px\">Phoenix</strong><span style=\"display:block;margin-top:4px;color:#ff9072;font-size:10px;letter-spacing:2px;text-transform:uppercase\">Autopilot</span></div><main style=\"background:#fff;padding:34px 26px;border:1px solid #e4e3df;border-top:0;border-radius:0 0 18px 18px\"><p style=\"margin:0 0 12px;color:#eb6a4c;font-size:11px;letter-spacing:1.6px;text-transform:uppercase\">Phoenix update</p><h1 style=\"margin:0 0 22px;font-size:28px\">{title}</h1>{body}<p style=\"margin-top:30px;color:#858b98;font-size:12px;line-height:1.6\">Phoenix Autopilot<br/>Support: {html.escape(os.getenv('SUPPORT_EMAIL', 'support.tiktok@senseiphoenix.name.ng'))}</p></main></div></body></html>"""
