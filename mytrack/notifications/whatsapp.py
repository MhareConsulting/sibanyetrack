import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


def _wa() -> dict:
    return getattr(settings, "WHATSAPP", {})


def _is_configured() -> bool:
    wa = _wa()
    return bool(wa.get("PHONE_NUMBER_ID") and wa.get("ACCESS_TOKEN"))


def send_whatsapp_template(phone_e164: str, template_name: str, lang: str, body_params: list[str]) -> bool:
    """
    Send a WhatsApp template message via Meta Cloud API.
    Returns True on success, False on failure (never raises).
    """
    wa = _wa()
    token = wa.get("ACCESS_TOKEN")
    phone_id = wa.get("PHONE_NUMBER_ID")
    graph_ver = (wa.get("GRAPH_API_VERSION") or "v25.0").strip().lstrip("/")

    if not token or not phone_id or not phone_e164:
        return False

    payload = {
        "messaging_product": "whatsapp",
        "to": phone_e164.lstrip("+"),
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": lang},
            "components": [
                {
                    "type": "body",
                    "parameters": [{"type": "text", "text": p or " "} for p in body_params],
                }
            ],
        },
    }
    try:
        resp = requests.post(
            f"https://graph.facebook.com/{graph_ver}/{phone_id}/messages",
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
            timeout=10,
        )
        if resp.status_code >= 400:
            logger.warning(
                "WhatsApp Graph error sending %r: HTTP %s %s",
                template_name,
                resp.status_code,
                (resp.text or "")[:800],
            )
            return False
        logger.info("WhatsApp template %r sent to %s", template_name, phone_e164)
        return True
    except Exception as exc:
        logger.warning("WhatsApp send failed to %s: %s", phone_e164, exc)
        return False


def _resolve_driver_phone(driver_name: str, organisation, vehicle=None) -> str | None:
    """
    Look up a driver's E.164 phone within an organisation.
    If driver_name is blank (Traccar rarely sends it), fall back to whichever
    active driver has the vehicle set as their default_vehicle.
    """
    from mytrack.drivers.models import Driver
    if driver_name:
        driver = (
            Driver.objects.filter(organisation=organisation, full_name__iexact=driver_name, is_active=True)
            .only("phone_e164")
            .first()
        )
    elif vehicle is not None:
        driver = (
            Driver.objects.filter(organisation=organisation, default_vehicle=vehicle, is_active=True)
            .only("phone_e164")
            .first()
        )
    else:
        return None
    return driver.phone_e164 if driver and driver.phone_e164 else None


def notify_driver(driver_name: str, organisation, event_label: str, vehicle_reg: str, detail: str, vehicle=None) -> bool:
    """
    Send a WhatsApp alert to a driver if the org has it enabled and the driver has a phone number.

    Uses the template at settings.WHATSAPP["TEMPLATE_DRIVER_ALERT"] (default: driver_fleet_alert).
    The template must have three body parameters: {{1}} event, {{2}} vehicle reg, {{3}} detail.
    Pass vehicle= so we can fall back to default_vehicle lookup when driver_name is blank.
    """
    if not _is_configured():
        return False
    if not getattr(organisation, "whatsapp_driver_notify_enabled", False):
        return False
    phone = _resolve_driver_phone(driver_name, organisation, vehicle=vehicle)
    if not phone:
        return False
    template = (_wa().get("TEMPLATE_DRIVER_ALERT") or "driver_fleet_alert").strip()
    return send_whatsapp_template(phone, template, "en", [event_label, vehicle_reg, detail])
