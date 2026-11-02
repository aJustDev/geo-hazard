import re

from app.notifications.services.credentials import mask, new_ntfy_topic, new_webhook_key


def test_topic_ntfy_valido_e_inadivinable() -> None:
    topic = new_ntfy_topic()
    # ntfy acepta [-_A-Za-z0-9]{1,64} como topic.
    assert re.fullmatch(r"[-_A-Za-z0-9]{1,64}", topic)
    assert topic.startswith("geohazard-")
    assert len(topic) >= 40
    assert new_ntfy_topic() != topic


def test_clave_webhook_de_256_bits() -> None:
    key = new_webhook_key()
    assert re.fullmatch(r"[0-9a-f]{64}", key)
    assert new_webhook_key() != key


def test_mascara_solo_deja_el_final() -> None:
    assert mask("geohazard-abcdefghij") == "...ghij"
