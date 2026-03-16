from flask_mail import Message
from threading import Thread
from extensions import mail
from flask import current_app

def send_async_email(app, msg):
    with app.app_context():
        try:
            mail.send(msg)
        except Exception as e:
            print(f"Error sending async email: {e}")

def send_email(subject, recipients, body=None, html=None, attachments=None):
    """
    Send email asynchronously.
    attachments: list of dicts with keys: filename, content_type, data, disposition (optional), headers (optional)
    """
    app = current_app._get_current_object()
    msg = Message(subject=subject, recipients=recipients, sender=app.config['MAIL_USERNAME'])
    if body:
        msg.body = body
    if html:
        msg.html = html
        
    if attachments:
        for att in attachments:
            msg.attach(
                att['filename'],
                att['content_type'],
                att['data'],
                att.get('disposition', 'attachment'),
                headers=att.get('headers')
            )

    Thread(target=send_async_email, args=(app, msg)).start()
