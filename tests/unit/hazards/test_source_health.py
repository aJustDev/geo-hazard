from datetime import UTC, datetime, timedelta

from app.hazards.models import SourceSyncStateORM
from app.hazards.services.source_health import assess_sources, sync_intervals

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)


def _state(source: str, *, success_ago: timedelta | None, failures: int = 0) -> SourceSyncStateORM:
    last_success = NOW - success_ago if success_ago is not None else None
    return SourceSyncStateORM(
        source=source,
        last_run_at=NOW,
        last_success_at=last_success,
        consecutive_failures=failures,
        last_error="boom" if failures else None,
    )


def _assess(states: list[SourceSyncStateORM], intervals: dict[str, int]):
    return assess_sources(states, intervals, now=NOW, staleness_factor=3, max_failures=3)


def test_sync_intervals_solo_jobs_de_fuente() -> None:
    jobs = [("ign_sync", 900), ("aemet_sync", 1800), ("notifications_deliver", 60)]
    assert sync_intervals(jobs) == {"ign": 900, "aemet": 1800}


def test_fresca_segun_su_propia_cadencia() -> None:
    # 2 h sin exito es fresco para EFFIS (cada 4 h) y stale para IGN (cada 15 min).
    report = _assess(
        [
            _state("effis", success_ago=timedelta(hours=2)),
            _state("ign", success_ago=timedelta(hours=2)),
        ],
        {"effis": 14400, "ign": 900},
    )
    by_source = {s.source: s for s in report.sources}
    assert by_source["effis"].healthy
    assert by_source["ign"].stale
    assert not by_source["ign"].healthy
    assert report.status == "degraded"


def test_justo_en_el_umbral_no_es_stale() -> None:
    report = _assess([_state("ign", success_ago=timedelta(seconds=3 * 900))], {"ign": 900})
    assert not report.sources[0].stale


def test_programada_sin_estado_aparece_degradada() -> None:
    report = _assess([], {"aemet": 1800})
    assert report.sources[0].source == "aemet"
    assert report.sources[0].stale
    assert report.sources[0].seconds_since_success is None
    assert report.status == "degraded"


def test_fallos_consecutivos_degradan_aunque_sea_fresca() -> None:
    report = _assess(
        [_state("aemet", success_ago=timedelta(minutes=5), failures=3)], {"aemet": 1800}
    )
    assert not report.sources[0].stale
    assert report.sources[0].has_error
    assert not report.sources[0].healthy


def test_con_estado_sin_programar_no_es_stale() -> None:
    report = _assess([_state("ign", success_ago=None)], {})
    assert report.sources[0].interval_seconds is None
    assert not report.sources[0].stale
    assert report.status == "ok"


def test_atribucion_por_fuente() -> None:
    report = _assess([_state("ign", success_ago=timedelta(minutes=1))], {"ign": 900})
    assert report.sources[0].attribution is not None
    assert report.sources[0].attribution.source == "ign"
