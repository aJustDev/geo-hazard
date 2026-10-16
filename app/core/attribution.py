"""Atribucion que exige cada fuente al redistribuir su dato (F1, NOTICE).

geo-hazard no sirve el dato tal cual: normaliza severidad, geometria y ciclo
de vida. Por eso se usan las formulas de dato modificado / obra derivada de
cada licencia. Vive en core porque la citan los dos planos (hazards y
analytics), que no pueden importarse entre si (ADR-0012).
"""

from collections.abc import Iterable

from app.core.schema import BaseSchema


class SourceAttribution(BaseSchema):
    source: str
    text: str
    # Terminos de reutilizacion de la fuente.
    url: str


ATTRIBUTIONS: dict[str, SourceAttribution] = {
    a.source: a
    for a in (
        # Nota legal de AEMET: dato elaborado -> "Fuente: AEMET". La fecha de
        # ultima actualizacion que tambien pide esta en /v1/sources/status.
        SourceAttribution(
            source="aemet",
            text="Fuente: AEMET",
            url="https://www.aemet.es/es/nota_legal",
        ),
        # Contenido de la UE en EFFIS bajo CC BY 4.0; formula de los terminos
        # del Copernicus Emergency Management Service para dato modificado.
        SourceAttribution(
            source="effis",
            text=(
                "Contains modified Copernicus Emergency Management Service information "
                "(EFFIS). (c) European Union, CC BY 4.0"
            ),
            url="https://forest-fire.emergency.copernicus.eu/about-effis/data-license",
        ),
        # IGN, CC BY 4.0: formula de obra derivada de sus condiciones de uso.
        SourceAttribution(
            source="ign",
            text="Obra derivada del catalogo de terremotos del IGN, CC-BY 4.0 ign.es",
            url="https://www.ign.es/resources/licencia/Condiciones_licenciaUso_IGN.pdf",
        ),
        # Limites provinciales de la referencia commiteada (ADR-0013).
        SourceAttribution(
            source="cnig",
            text="Obra derivada de las lineas limite del CNIG, CC-BY 4.0 ign.es",
            url="https://www.ign.es/resources/licencia/Condiciones_licenciaUso_IGN.pdf",
        ),
    )
}


def attributions_for(sources: Iterable[str]) -> list[SourceAttribution]:
    """Atribuciones de las fuentes dadas, ordenadas y sin repetir. Una fuente
    sin entrada (p.ej. programada pero aun sin implementar) se omite."""
    return [ATTRIBUTIONS[s] for s in sorted(set(sources)) if s in ATTRIBUTIONS]


__all__ = ["ATTRIBUTIONS", "SourceAttribution", "attributions_for"]
