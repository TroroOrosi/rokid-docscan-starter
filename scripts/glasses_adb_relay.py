"""Reach the glasses' wireless adb from the PC through the phone.

The glasses join the phone's hotspot (10.x) and already listen on adb TCP 5555
(``persist.adb.tcp.port``). The PC sits on another network and cannot route to
them. This relay runs in Termux on the phone and forwards one loopback port to
the glasses; the PC then uses ``adb forward`` to that port and ``adb connect``.

    phone (Termux):  python scripts/glasses_adb_relay.py 10.129.169.167
    PC:              adb -s <phone> forward tcp:5556 tcp:5556
                     adb connect 127.0.0.1:5556

It listens on 127.0.0.1 only: the glasses' debug port is never offered to the
hotspot or the home network. Development only; the venue needs no PC.
"""

from __future__ import annotations

import asyncio
import sys


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    except (ConnectionError, OSError):
        pass
    finally:
        writer.close()


async def serve(target_host: str, target_port: int = 5555, listen_port: int = 5556,
                listen_host: str = "127.0.0.1") -> asyncio.AbstractServer:
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            upstream_reader, upstream_writer = await asyncio.open_connection(target_host, target_port)
        except OSError:
            writer.close()  # The glasses are away: the PC sees a closed connection, not a hang.
            return
        await asyncio.gather(_pipe(reader, upstream_writer), _pipe(upstream_reader, writer))

    return await asyncio.start_server(handle, listen_host, listen_port)


async def _main(arguments: list[str]) -> None:
    server = await serve(arguments[0], *(int(value) for value in arguments[1:3]))
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("usage: glasses_adb_relay.py GLASSES_IP [GLASSES_PORT [LISTEN_PORT]]")
    asyncio.run(_main(sys.argv[1:]))
