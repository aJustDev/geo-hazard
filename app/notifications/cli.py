"""CLI de los avisos (ADR-0021). En produccion, dentro del contenedor:

    docker exec geohazard-api python -m app.notifications.cli list

Las credenciales (topic ntfy, clave del webhook) las genera `add` y las
muestra una sola vez; nunca se pasan como argumento.
"""

import argparse
import asyncio
import sys
import uuid
from typing import TextIO

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.channels.driver import ChannelSender
from app.core.channels.guard import describe
from app.core.channels.registry import channel_sender_registry
from app.core.channels.types import ChannelError
from app.core.db import async_session_factory
from app.core.exceptions.exceptions import DomainException
from app.notifications.services.areas import AreaSpec, bbox_area, circle_area, province_area
from app.notifications.services.credentials import mask
from app.notifications.use_cases.manage import (
    DEFAULT_NTFY_SERVER,
    ChannelSpec,
    Created,
    SubscriptionAdmin,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.notifications.cli", description="Avisos por area vigilada"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("provinces", help="codigos INE de provincia")

    add = commands.add_parser("add", help="crea una suscripcion")
    area = add.add_mutually_exclusive_group(required=True)
    area.add_argument("--province", metavar="CODE", help="codigo INE, p. ej. 30")
    area.add_argument("--bbox", metavar="MINLON,MINLAT,MAXLON,MAXLAT")
    area.add_argument("--circle", metavar="LON,LAT,KM", help="centro y radio (1-200 km)")
    add.add_argument("--label", help="nombre del area en los mensajes")
    add.add_argument(
        "--types", required=True, help="weather_warning,earthquake,wildfire (uno o varios)"
    )
    add.add_argument("--severity-min", type=int, choices=range(1, 5), required=True)
    channel = add.add_mutually_exclusive_group(required=True)
    channel.add_argument("--ntfy", action="store_true", help="topic ntfy nuevo")
    channel.add_argument("--webhook", metavar="URL", help="webhook https con clave nueva")
    channel.add_argument(
        "--same-channel-as", metavar="ID", type=uuid.UUID, help="reutiliza el canal de otra"
    )
    add.add_argument("--ntfy-server", default=DEFAULT_NTFY_SERVER)

    commands.add_parser("list", help="suscripciones y su estado")
    for name, help_text in (
        ("pause", "pausa y descarta lo pendiente"),
        ("resume", "reactiva y olvida los fallos"),
        ("remove", "borra la suscripcion (y su area si nadie mas la usa)"),
        ("test", "manda un mensaje de prueba ya"),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("id", type=uuid.UUID)
    stats = commands.add_parser("stats", help="mensajes por semana y suscripcion")
    stats.add_argument("--weeks", type=int, default=8)
    return parser


def _area(args: argparse.Namespace) -> AreaSpec:
    if args.province is not None:
        return province_area(args.province)
    if args.bbox is not None:
        return bbox_area(args.bbox)
    return circle_area(args.circle)


def _channel(args: argparse.Namespace) -> ChannelSpec:
    if args.same_channel_as is not None:
        return ChannelSpec(kind="copy", copy_from=args.same_channel_as)
    if args.webhook is not None:
        return ChannelSpec(kind="webhook", endpoint=args.webhook)
    return ChannelSpec(kind="ntfy", endpoint=args.ntfy_server)


def _print_created(created: Created, out: TextIO) -> None:
    print(f"Suscripcion creada: {created.subscription_id}", file=out)
    print(f"Area: {created.area_label}", file=out)
    if created.new_credential is None:
        print(f"Canal {created.channel} compartido con la suscripcion indicada.", file=out)
        return
    what = "Topic ntfy" if created.channel == "ntfy" else "Clave HMAC del webhook"
    print(f"{what} (no se vuelve a mostrar): {created.new_credential}", file=out)
    print(f"Prueba el canal con: test {created.subscription_id}", file=out)


async def _dispatch(args: argparse.Namespace, admin: SubscriptionAdmin, out: TextIO) -> None:
    match args.command:
        case "provinces":
            for code, name in await admin.provinces():
                print(f"{code}  {name}", file=out)
        case "add":
            created = await admin.add(
                _area(args),
                label=args.label,
                hazard_types=[t.strip() for t in args.types.split(",") if t.strip()],
                severity_min=args.severity_min,
                channel=_channel(args),
            )
            _print_created(created, out)
        case "list":
            for row in await admin.list_all():
                s = row.subscription
                print(
                    f"{s.id}  {s.status}  {s.channel} {describe(s.endpoint)} {mask(s.credential)}",
                    file=out,
                )
                print(
                    f"  area: {row.area_label} | tipos: {','.join(s.hazard_types)} | "
                    f"severidad >= {s.severity_min}",
                    file=out,
                )
                sent = f"{s.last_sent_at:%Y-%m-%d %H:%M} UTC" if s.last_sent_at else "nunca"
                print(
                    f"  pendientes: {row.pending} | ultimo envio: {sent} | "
                    f"fallos seguidos: {s.consecutive_failures}",
                    file=out,
                )
                if s.paused_reason or s.last_error:
                    print(f"  {s.paused_reason or s.last_error}", file=out)
        case "pause":
            await admin.pause(args.id)
            print("Pausada; lo pendiente se descarta.", file=out)
        case "resume":
            await admin.resume(args.id)
            print("Reactivada.", file=out)
        case "remove":
            await admin.remove(args.id)
            print("Borrada.", file=out)
        case "test":
            await admin.test(args.id)
            print("Mensaje de prueba enviado.", file=out)
        case "stats":
            for stat in await admin.stats(weeks=args.weeks):
                print(
                    f"{stat.subscription_id}  {stat.area_label}  semana del {stat.week:%Y-%m-%d}: "
                    f"{stat.messages} mensajes, {stat.deliveries} avisos",
                    file=out,
                )


async def run(
    argv: list[str],
    *,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    sender: ChannelSender | None = None,
    out: TextIO | None = None,
) -> int:
    out = out or sys.stdout
    args = _parser().parse_args(argv)
    admin = SubscriptionAdmin(
        session_factory=session_factory or async_session_factory,
        sender=sender or channel_sender_registry.get(),
    )
    try:
        await _dispatch(args, admin, out)
    except (ValueError, DomainException, ChannelError) as exc:
        print(f"error: {exc}", file=out)
        return 1
    return 0


def main() -> None:
    sys.exit(asyncio.run(run(sys.argv[1:])))


if __name__ == "__main__":
    main()
