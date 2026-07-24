import smtplib
from email.mime.text import MIMEText


def send_mail(sender, app_password, receiver, subject, body):
    """Gmailでメール送信"""

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = receiver

    with smtplib.SMTP("smtp.gmail.com", 587) as smtp:
        smtp.starttls()
        smtp.login(sender, app_password)
        smtp.send_message(msg)

    print("メール送信完了")
