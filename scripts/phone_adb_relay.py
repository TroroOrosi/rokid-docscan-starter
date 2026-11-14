"""Runs on the phone (Termux). Carries one TCP port on the phone's home-network address to the glasses' adb port on its hotspot.

The glasses reach nothing but the phone's hotspot, and at the venue there is no cable: this lets the development PC
drive and read the glasses through the phone, as the phone's own watcher does, while they are worn.
Started and stopped from the PC by scripts/glasses_over_phone.py; not part of the venue's services.

    python phone_adb_relay.py <listen address> <listen port> <glasses address> [glasses port=5555]
"""
import asyncio
import sys


async def carry(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    except OSError:
        pass
    finally:
        writer.close()


async def main() -> None:
    listen, port, glasses = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    target = int(sys.argv[4]) if len(sys.argv) > 4 else 5555

    async def connection(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            far_reader, far_writer = await asyncio.open_connection(glasses, target)
        except OSError:
            writer.close()
            return
        await asyncio.gather(carry(reader, far_writer), carry(far_reader, writer))

    async with await asyncio.start_server(connection, listen, port) as server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
