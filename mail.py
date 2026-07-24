import smtplib
from email.mime.text import MIMEText


def send_mail(sender, app_password, receiver, subject, body):
    """Gmailでメール送信。設定不足やSMTP失敗時は安全にスキップする。"""

    if not sender or not receiver or not app_password:
        print("メール設定が不足しているため、メール送信をスキップしました。")
        return False

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = receiver

    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=10) as smtp:
            smtp.starttls()
            smtp.login(sender, app_password)
            smtp.send_message(msg)
    except (OSError, smtplib.SMTPException) as exc:
        print(f"メール送信に失敗しました: {exc}")
        return False

    print("メール送信完了")
    return True
