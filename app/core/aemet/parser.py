"""Parser de un CAP v1.2 de AEMET (un XML por aviso y zona, docs/sources.md).

Cada fichero duplica el bloque <info> en es-ES y en-GB; se toma el castellano
como canonico. Los campos propios de Meteoalerta (nivel, fenomeno, zona)
viajan dentro de los contenedores genericos de CAP: parameter, eventCode y
geocode, todos con la forma valueName/value.
"""

from datetime import datetime
from xml.etree.ElementTree import Element

from defusedxml import ElementTree

from app.core.aemet.exceptions import AemetProtocolError
from app.core.aemet.types import AemetWarning

_CAP_NS = "{urn:oasis:names:tc:emergency:cap:1.2}"


def parse_cap(payload: bytes) -> AemetWarning:
    try:
        root = ElementTree.fromstring(payload)
    except Exception as exc:
        raise AemetProtocolError(f"unparseable CAP XML: {exc}") from exc

    identifier = root.findtext(f"{_CAP_NS}identifier")
    msg_type = root.findtext(f"{_CAP_NS}msgType")
    sent_text = root.findtext(f"{_CAP_NS}sent")
    if not (identifier and msg_type and sent_text):
        raise AemetProtocolError("CAP alert missing identifier/msgType/sent")

    # references: triples "sender,identifier,sent" separados por espacios;
    # solo interesa el identifier del mensaje supersedido.
    references = tuple(
        chunk.split(",")[1]
        for chunk in (root.findtext(f"{_CAP_NS}references") or "").split()
        if chunk.count(",") >= 2
    )

    base = AemetWarning(
        external_id=identifier,
        msg_type=msg_type,
        sent=_parse_moment(sent_text),
        references=references,
    )

    info = _spanish_info(root)
    if info is None:
        # Tipicamente un Cancel: sin contenido, solo referencias que cerrar.
        return base

    parameters = _named_values(info, "parameter")
    area = info.find(f"{_CAP_NS}area")
    onset = info.findtext(f"{_CAP_NS}onset")
    expires = info.findtext(f"{_CAP_NS}expires")

    attrs = {
        "headline": info.findtext(f"{_CAP_NS}headline"),
        "description": info.findtext(f"{_CAP_NS}description"),
        "cap_severity": info.findtext(f"{_CAP_NS}severity"),
        "probability": parameters.get("AEMET-Meteoalerta probabilidad"),
        "parameter": parameters.get("AEMET-Meteoalerta parametro"),
    }

    return AemetWarning(
        external_id=base.external_id,
        msg_type=base.msg_type,
        sent=base.sent,
        references=base.references,
        event=info.findtext(f"{_CAP_NS}event"),
        phenomenon=_named_values(info, "eventCode").get("AEMET-Meteoalerta fenomeno"),
        level=parameters.get("AEMET-Meteoalerta nivel"),
        onset=_parse_moment(onset) if onset else None,
        expires=_parse_moment(expires) if expires else None,
        polygon=area.findtext(f"{_CAP_NS}polygon") if area is not None else None,
        zone=_named_values(area, "geocode").get("AEMET-Meteoalerta zona")
        if area is not None
        else None,
        area_desc=area.findtext(f"{_CAP_NS}areaDesc") if area is not None else None,
        attrs={key: value for key, value in attrs.items() if value is not None},
    )


def _parse_moment(text: str) -> datetime:
    # CAP usa ISO 8601 con offset explicito ("2026-07-02T16:28:03-00:00").
    try:
        return datetime.fromisoformat(text)
    except ValueError as exc:
        raise AemetProtocolError(f"unparseable CAP timestamp: {text!r}") from exc


def _spanish_info(root: Element) -> Element | None:
    infos = root.findall(f"{_CAP_NS}info")
    for info in infos:
        language = info.findtext(f"{_CAP_NS}language") or ""
        if language.lower().startswith("es"):
            return info
    return infos[0] if infos else None


def _named_values(parent: Element, tag: str) -> dict[str, str]:
    """Contenedores CAP valueName/value (parameter, eventCode, geocode) -> dict."""
    values: dict[str, str] = {}
    for element in parent.findall(f"{_CAP_NS}{tag}"):
        name = element.findtext(f"{_CAP_NS}valueName")
        value = element.findtext(f"{_CAP_NS}value")
        if name and value:
            values[name] = value
    return values


__all__ = ["parse_cap"]
