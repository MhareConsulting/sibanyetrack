from django.conf import settings
from azure.communication.email import EmailClient


def send_email(to_addresses: list[str], subject: str, html_body: str) -> None:
    """Send an email via Azure Communication Services."""
    if not to_addresses:
        return

    client = EmailClient.from_connection_string(settings.ACS_CONNECTION_STRING)
    poller = client.begin_send({
        "senderAddress": settings.ACS_SENDER_EMAIL,
        "recipients": {"to": [{"address": addr} for addr in to_addresses]},
        "content": {"subject": subject, "html": html_body},
    })
    poller.result()
