from __future__ import annotations

import argparse
import asyncio
import os

import asyncpg

from notifelect.models import MessageExchange
from notifelect.queries import Queries, SQLBuilder


def parse_args() -> argparse.Namespace:
    common = argparse.ArgumentParser(
        add_help=False,
        prog="notifelect",
    )

    common.add_argument(
        "--prefix",
        default="",
        help=(
            "All notifelect sequences will start with this prefix. "
            "(If set, additional configuration is required.)"
        ),
    )

    common.add_argument(
        "--pg-dsn",
        help=(
            "Connection string in the libpq URI format, including host, port, user, "
            "database, password, passfile, and SSL options. Must be properly quoted; "
            "IPv6 addresses must be in brackets. "
            "Example: postgres://user:pass@host:port/database. Defaults to PGDSN "
            "environment variable if set."
        ),
        default=os.environ.get("PGDSN"),
    )

    common.add_argument(
        "--pg-host",
        help=(
            "Database host address, which can be an IP or domain name. "
            "Defaults to PGHOST environment variable if set."
        ),
        default=os.environ.get("PGHOST"),
    )

    common.add_argument(
        "--pg-port",
        help=(
            "Port number for the server host. "
            "Defaults to PGPORT environment variable or 5432 if not set."
        ),
        default=os.environ.get("PGPORT", "5432"),
    )

    common.add_argument(
        "--pg-user",
        help=("Database role for authentication. Defaults to PGUSER environment variable if set."),
        default=os.environ.get("PGUSER"),
    )

    common.add_argument(
        "--pg-database",
        help=(
            "Name of the database to connect to. "
            "Defaults to PGDATABASE environment variable if set."
        ),
        default=os.environ.get("PGDATABASE"),
    )

    common.add_argument(
        "--pg-password",
        help=("Password for authentication. Defaults to PGPASSWORD environment variable if set."),
        default=os.environ.get("PGPASSWORD"),
    )

    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        prog="notifelect",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "install",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        parents=[common],
    ).add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Print the SQL statements that would be executed without "
            "applying any changes to the database."
        ),
    )

    subparsers.add_parser(
        "uninstall",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        parents=[common],
    ).add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Print the SQL statements that would be executed without "
            "applying any changes to the database."
        ),
    )

    listen_parser = subparsers.add_parser(
        "listen",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        parents=[common],
    )
    listen_parser.add_argument(
        "--channel",
        help="PostgreSQL NOTIFY channel to listen on for debug purposes.",
        default=SQLBuilder().channel,
    )

    return parser.parse_args()


async def connect(parsed: argparse.Namespace) -> asyncpg.Connection:
    return await asyncpg.connect(
        dsn=parsed.pg_dsn or None,
        host=parsed.pg_host or None,
        port=parsed.pg_port or None,
        user=parsed.pg_user or None,
        password=parsed.pg_password or None,
    )


async def main() -> None:
    parsed = parse_args()

    if (
        "NOTIFELECT_PREFIX" not in os.environ
        and isinstance(prefix := parsed.prefix, str)
        and prefix
    ):
        os.environ["NOTIFELECT_PREFIX"] = prefix

    sql = SQLBuilder()

    match parsed.command:
        case "install":
            print(sql.install_sql())
            if not parsed.dry_run:
                await Queries(await connect(parsed)).install()
        case "uninstall":
            print(sql.uninstall_sql())
            if not parsed.dry_run:
                await Queries(await connect(parsed)).uninstall()
        case "listen":
            conn = await connect(parsed)
            await conn.add_listener(
                sql.channel,
                lambda *x: print(repr(MessageExchange.model_validate_json(x[-1]))),
            )
            await asyncio.Future()
