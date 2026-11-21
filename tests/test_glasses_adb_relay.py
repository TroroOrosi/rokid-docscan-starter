"""The PC reaches the glasses' adb through a loopback-only relay on the phone."""

import asyncio
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "glasses_adb_relay", Path(__file__).resolve().parents[1] / "scripts" / "glasses_adb_relay.py")
relay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(relay)


def test_bytes_pass_both_ways_and_only_loopback_listens():
    async def scenario():
        async def glasses(reader, writer):
            writer.write(b"host::" + await reader.readexactly(4))
            await writer.drain()
            writer.close()

        target = await asyncio.start_server(glasses, "127.0.0.1", 0)
        server = await relay.serve("127.0.0.1", target.sockets[0].getsockname()[1], 0)
        host, port = server.sockets[0].getsockname()[:2]
        reader, writer = await asyncio.open_connection(host, port)
        writer.write(b"CNXN")
        await writer.drain()
        reply = await asyncio.wait_for(reader.read(), 5)
        writer.close()
        server.close()
        target.close()
        return host, reply

    host, reply = asyncio.run(scenario())
    assert host == "127.0.0.1" and reply == b"host::CNXN"


def test_absent_glasses_close_the_connection_instead_of_hanging():
    async def scenario():
        closed = await asyncio.start_server(lambda reader, writer: None, "127.0.0.1", 0)
        unused = closed.sockets[0].getsockname()[1]
        closed.close()
        await closed.wait_closed()
        server = await relay.serve("127.0.0.1", unused, 0)
        reader, writer = await asyncio.open_connection(*server.sockets[0].getsockname()[:2])
        data = await asyncio.wait_for(reader.read(), 5)
        writer.close()
        server.close()
        return data

    assert asyncio.run(scenario()) == b""
