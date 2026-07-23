"""Yahtzee rendezvous relay: a dumb WebSocket pairing pipe.

Both the host and the joining player connect OUTBOUND to this relay (so
CGNAT and firewalls do not matter). The host parks spare connections per
room code; every joiner is paired with one, and from then on the relay
forwards frames verbatim in both directions. It stores nothing, knows
nothing about Yahtzee, and keeps no state beyond the in-memory rooms.

Deployed at relay.rustema.app (see docker-compose.yml next to this file).
"""

from __future__ import annotations

import asyncio
import json
import time

from aiohttp import WSMsgType, web

MAX_ROOMS = 500
MAX_WAITING_PER_ROOM = 8
PAIR_TIMEOUT = 3600  # an unpaired host slot may wait this long
MAX_FRAME = 256 * 1024

# room code -> list of (host_ws, future_that_receives_the_joiner)
rooms: dict[str, list[tuple[web.WebSocketResponse, asyncio.Future]]] = {}


async def healthz(_request: web.Request) -> web.Response:
    waiting = sum(len(v) for v in rooms.values())
    return web.json_response({"ok": True, "rooms": len(rooms), "waiting": waiting})


async def ws_handler(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse(heartbeat=30, max_msg_size=MAX_FRAME)
    await ws.prepare(request)
    try:
        first = await ws.receive(timeout=20)
    except asyncio.TimeoutError:
        await ws.close()
        return ws
    if first.type != WSMsgType.TEXT:
        await ws.close()
        return ws
    try:
        hello = json.loads(first.data)
    except ValueError:
        await ws.close()
        return ws
    role = hello.get("role")
    room = str(hello.get("room", "")).strip().upper()[:12]
    if not room or role not in ("host", "join"):
        await ws.close()
        return ws

    if role == "host":
        await _host(ws, room)
    else:
        await _join(ws, room)
    return ws


async def _host(ws: web.WebSocketResponse, room: str) -> None:
    if len(rooms) >= MAX_ROOMS or len(rooms.get(room, [])) >= MAX_WAITING_PER_ROOM:
        await ws.send_json({"error": "busy"})
        await ws.close()
        return
    future: asyncio.Future = asyncio.get_event_loop().create_future()
    slot = (ws, future)
    rooms.setdefault(room, []).append(slot)
    try:
        peer = await asyncio.wait_for(future, timeout=PAIR_TIMEOUT)
    except asyncio.TimeoutError:
        peer = None
    finally:
        if slot in rooms.get(room, []):
            rooms[room].remove(slot)
        if room in rooms and not rooms[room]:
            del rooms[room]
    if peer is None:
        await ws.close()
        return
    await ws.send_json({"paired": True})
    # Pump host -> joiner; the joiner's handler pumps the other direction.
    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                await peer.send_str(msg.data)
            else:
                break
    except (ConnectionError, RuntimeError):
        pass
    finally:
        await _safe_close(peer)


async def _join(ws: web.WebSocketResponse, room: str) -> None:
    waiting = rooms.get(room, [])
    host_ws = None
    while waiting:
        candidate, future = waiting.pop(0)
        if not future.done():
            future.set_result(ws)
            host_ws = candidate
            break
    if host_ws is None:
        await ws.send_json({"error": "no-room"})
        await ws.close()
        return
    await ws.send_json({"paired": True})
    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                await host_ws.send_str(msg.data)
            else:
                break
    except (ConnectionError, RuntimeError):
        pass
    finally:
        await _safe_close(host_ws)


async def _safe_close(ws: web.WebSocketResponse) -> None:
    try:
        await ws.close()
    except Exception:
        pass


def make_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/healthz", healthz)
    app.router.add_get("/ws", ws_handler)
    return app


if __name__ == "__main__":
    web.run_app(make_app(), host="0.0.0.0", port=8080)
