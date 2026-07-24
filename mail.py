import smtplib
from email.mime.text import MIMEText


def send_mail(sender, app_password, receiver, subject, body):
    """Gmailでメール送信。未設定・認証失敗でも本処理は止めない。"""

    if not sender or not app_password:
        print("メール設定が未完了のため、通知をスキップしました。")
        return False

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = receiver

    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as smtp:
            smtp.starttls()
            smtp.login(sender, app_password)
            smtp.send_message(msg)
    except (smtplib.SMTPException, OSError) as exc:
        print(f"メール送信に失敗しましたが、処理結果は保存済みです: {exc}")
        return False

    print("メール送信完了")
    return True
