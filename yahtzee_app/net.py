"""Online multiplayer: host-authoritative, JSON lines over TCP.

Transport ladder (no central server, no database):
1. Direct TCP: LAN, Tailscale, ZeroTier, or a manually forwarded port.
2. UPnP: the host asks its router to forward the port (best effort).
3. (Planned) a tiny public relay for CGNAT cases.

The host runs the rules engine; clients only send actions (roll, hold,
score) and render the state snapshots the host broadcasts. Every device
has a persistent random UUID; a lost connection keeps the seat reserved
and reconnecting with the same UUID resumes it.
"""

from __future__ import annotations

import asyncio
import json
import socket
import subprocess
import urllib.request
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional
from xml.etree import ElementTree

from .config import load_settings, load_stats, save_settings

PROTOCOL_VERSION = 1
DEFAULT_PORT = 5333
PORT_RANGE = range(DEFAULT_PORT, DEFAULT_PORT + 8)
MAX_LINE = 512 * 1024


# ---------------------------------------------------------------------------
# Identity and discovery
# ---------------------------------------------------------------------------


def device_id() -> str:
    """Stable random identity for this device (standard approach: uuid4,
    generated once and stored)."""
    settings = load_settings()
    dev = settings.get("device_id")
    if not dev:
        dev = str(uuid.uuid4())
        settings["device_id"] = dev
        save_settings(settings)
    return dev


def player_name() -> str:
    settings = load_settings()
    return str(settings.get("player_name") or "")


def save_player_name(name: str) -> None:
    settings = load_settings()
    settings["player_name"] = name
    save_settings(settings)


def my_stats_summary() -> dict:
    """Small local stats summary, shared peer-to-peer in the lobby."""
    games = load_stats().get("games_v2", [])
    if not games:
        return {"games": 0, "won": 0, "avg": 0}
    scores = [g.get("your_score", 0) for g in games]
    return {
        "games": len(games),
        "won": sum(1 for g in games if g.get("won")),
        "avg": round(sum(scores) / len(scores), 1),
    }


def _probe_ip(target: str) -> Optional[str]:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect((target, 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return None


def local_addresses() -> list[tuple[str, str]]:
    """(label, ip) pairs a friend could connect to."""
    out: list[tuple[str, str]] = []
    lan = _probe_ip("8.8.8.8")
    if lan:
        out.append(("lan", lan))
    ts = _probe_ip("100.100.100.100")
    if ts and ts.startswith("100.") and all(ts != ip for _, ip in out):
        out.append(("tailscale", ts))
    try:
        result = subprocess.run(
            ["tailscale", "ip", "-4"], capture_output=True, text=True, timeout=2
        )
        for line in result.stdout.split():
            if line and all(line != ip for _, ip in out):
                out.append(("tailscale", line.strip()))
    except (OSError, subprocess.TimeoutExpired):
        pass
    return out


# ---------------------------------------------------------------------------
# Best-effort UPnP port mapping (no dependencies)
# ---------------------------------------------------------------------------


def try_upnp_map(port: int) -> Optional[str]:
    """Ask the router to forward `port`; returns the public IP on success."""
    try:
        location = _ssdp_discover()
        if not location:
            return None
        control_url, service = _igd_control_url(location)
        if not control_url:
            return None
        lan = _probe_ip("8.8.8.8")
        if not lan:
            return None
        _soap(
            control_url,
            service,
            "AddPortMapping",
            {
                "NewRemoteHost": "",
                "NewExternalPort": str(port),
                "NewProtocol": "TCP",
                "NewInternalPort": str(port),
                "NewInternalClient": lan,
                "NewEnabled": "1",
                "NewPortMappingDescription": "yahtzee",
                "NewLeaseDuration": "7200",
            },
        )
        body = _soap(control_url, service, "GetExternalIPAddress", {})
        match = body.find(".//NewExternalIPAddress")
        if match is not None and match.text and not match.text.startswith(
            ("10.", "192.168.", "172.", "100.")
        ):
            return match.text
    except Exception:
        pass
    return None


def _ssdp_discover() -> Optional[str]:
    msg = (
        "M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\n"
        'MAN: "ssdp:discover"\r\nMX: 2\r\n'
        "ST: urn:schemas-upnp-org:device:InternetGatewayDevice:1\r\n\r\n"
    ).encode()
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(2.5)
    try:
        s.sendto(msg, ("239.255.255.250", 1900))
        while True:
            data, _ = s.recvfrom(4096)
            for line in data.decode(errors="ignore").splitlines():
                if line.lower().startswith("location:"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        return None
    finally:
        s.close()


def _igd_control_url(location: str) -> tuple[Optional[str], str]:
    with urllib.request.urlopen(location, timeout=3) as resp:
        tree = ElementTree.fromstring(resp.read())
    ns = {"d": "urn:schemas-upnp-org:device-1-0"}
    base = location.split("/", 3)
    base_url = f"{base[0]}//{base[2]}"
    for svc_type in ("WANIPConnection:1", "WANPPPConnection:1"):
        for svc in tree.iter("{urn:schemas-upnp-org:device-1-0}service"):
            stype = svc.findtext("d:serviceType", "", ns)
            if svc_type in stype:
                url = svc.findtext("d:controlURL", "", ns)
                if url:
                    if not url.startswith("http"):
                        url = base_url + url
                    return url, stype
    return None, ""


def _soap(control_url: str, service: str, action: str, args: dict) -> ElementTree.Element:
    body_args = "".join(f"<{k}>{v}</{k}>" for k, v in args.items())
    envelope = (
        '<?xml version="1.0"?>'
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
        's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
        f'<s:Body><u:{action} xmlns:u="{service}">{body_args}</u:{action}></s:Body>'
        "</s:Envelope>"
    ).encode()
    req = urllib.request.Request(
        control_url,
        data=envelope,
        headers={
            "Content-Type": 'text/xml; charset="utf-8"',
            "SOAPAction": f'"{service}#{action}"',
        },
    )
    with urllib.request.urlopen(req, timeout=3) as resp:
        text = resp.read().decode(errors="ignore")
    for a, b in (("<s:", "<"), ("</s:", "</"), ("<u:", "<"), ("</u:", "</")):
        text = text.replace(a, b)
    return ElementTree.fromstring(text)


# ---------------------------------------------------------------------------
# Wire helpers
# ---------------------------------------------------------------------------


async def send_msg(writer: asyncio.StreamWriter, msg: dict) -> None:
    writer.write(json.dumps(msg, separators=(",", ":")).encode() + b"\n")
    await writer.drain()


async def read_msg(reader: asyncio.StreamReader) -> Optional[dict]:
    line = await reader.readline()
    if not line or len(line) > MAX_LINE:
        return None
    try:
        msg = json.loads(line)
        return msg if isinstance(msg, dict) else None
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Host
# ---------------------------------------------------------------------------


@dataclass
class Seat:
    uuid: str
    name: str
    stats: dict = field(default_factory=dict)
    writer: Optional[asyncio.StreamWriter] = None

    @property
    def connected(self) -> bool:
        return self.writer is not None and not self.writer.is_closing()


class HostServer:
    """Accepts players, forwards their actions, broadcasts state.

    Events for the UI arrive on `events` as tuples:
      ("join", seat_uuid) ("leave", seat_uuid) ("action", seat_uuid, dict)
    """

    def __init__(self, host_name: str, max_remote: int = 5) -> None:
        self.host_name = host_name
        self.max_remote = max_remote
        self.seats: list[Seat] = []
        self.events: asyncio.Queue = asyncio.Queue()
        self.started = False
        self._server: Optional[asyncio.base_events.Server] = None
        self.port: Optional[int] = None
        self._last_state: Optional[dict] = None

    async def start(self) -> int:
        last_error: Exception = OSError("no port available")
        for port in PORT_RANGE:
            try:
                self._server = await asyncio.start_server(
                    self.handle_stream, host="0.0.0.0", port=port
                )
                self.port = port
                return port
            except OSError as exc:
                last_error = exc
        raise last_error

    async def stop(self) -> None:
        if getattr(self, "relay", None) is not None:
            self.relay.stop()
        for seat in self.seats:
            if seat.writer:
                seat.writer.close()
        if self._server:
            self._server.close()

    def seat_by_uuid(self, dev: str) -> Optional[Seat]:
        return next((s for s in self.seats if s.uuid == dev), None)

    async def handle_stream(self, reader, writer) -> None:
        hello = await read_msg(reader)
        if not hello or hello.get("t") != "hello":
            writer.close()
            return
        if int(hello.get("v", 0)) != PROTOCOL_VERSION:
            await send_msg(writer, {"t": "error", "reason": "version"})
            writer.close()
            return
        dev = str(hello.get("uuid", ""))[:64]
        name = str(hello.get("name", "Player"))[:16] or "Player"
        seat = self.seat_by_uuid(dev)
        if seat is None:
            if self.started or len(self.seats) >= self.max_remote:
                await send_msg(
                    writer,
                    {"t": "error", "reason": "started" if self.started else "full"},
                )
                writer.close()
                return
            seat = Seat(uuid=dev, name=name, stats=dict(hello.get("stats") or {}))
            self.seats.append(seat)
        seat.writer = writer
        await send_msg(writer, {"t": "welcome", "name": seat.name})
        if self.started and self._last_state is not None:
            await send_msg(writer, {"t": "state", "state": self._last_state, "events": []})
        await self.events.put(("join", seat.uuid))
        try:
            while True:
                msg = await read_msg(reader)
                if msg is None:
                    break
                if msg.get("t") == "ping":
                    await send_msg(writer, {"t": "pong"})
                elif msg.get("t") == "action":
                    await self.events.put(("action", seat.uuid, msg))
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            if seat.writer is writer:
                seat.writer = None
                await self.events.put(("leave", seat.uuid))
            writer.close()

    async def broadcast(self, msg: dict) -> None:
        if msg.get("t") == "state":
            self._last_state = msg.get("state")
        for seat in self.seats:
            if seat.connected:
                try:
                    await send_msg(seat.writer, msg)
                except (ConnectionError, OSError):
                    seat.writer = None
                    await self.events.put(("leave", seat.uuid))

    def lobby_payload(self) -> dict:
        return {
            "t": "lobby",
            "host": {"name": self.host_name, "stats": my_stats_summary()},
            "players": [
                {"name": s.name, "stats": s.stats, "connected": s.connected}
                for s in self.seats
            ],
        }


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class GameClient:
    """Connects to a host; auto-reconnects with the same device UUID.

    UI events on `events`:
      ("net", "up"|"down"|"gone") ("msg", dict)
    """

    def __init__(self, address: str, name: str, relay: str | None = None) -> None:
        self.address = address
        self.name = name
        self.relay = relay
        self.events: asyncio.Queue = asyncio.Queue()
        self._writer: Optional[asyncio.StreamWriter] = None
        self._closed = False
        self.connected = False

    @staticmethod
    def parse_address(text: str) -> tuple[str, int]:
        text = text.strip()
        if ":" in text:
            host, _, port = text.rpartition(":")
            return host.strip() or "127.0.0.1", int(port)
        return text, DEFAULT_PORT

    async def _open(self):
        """One transport attempt: relay code or direct TCP."""
        if looks_like_code(self.address):
            ws = await connect_relay("join", self.address.strip().upper(), self.relay)
            if not await _await_paired(ws):
                raise ConnectionError("relay pairing failed")
            return _WSReader(ws), _WSWriter(ws)
        host, port = self.parse_address(self.address)
        return await asyncio.wait_for(asyncio.open_connection(host, port), timeout=6)

    async def run(self) -> None:
        """Connect + reconnect loop; ends when close() is called or the
        host refuses us permanently."""
        backoff = 1.0
        while not self._closed:
            try:
                reader, writer = await self._open()
                self._writer = writer
                await send_msg(
                    writer,
                    {
                        "t": "hello",
                        "v": PROTOCOL_VERSION,
                        "uuid": device_id(),
                        "name": self.name,
                        "stats": my_stats_summary(),
                    },
                )
                first = await asyncio.wait_for(read_msg(reader), timeout=6)
                if not first or first.get("t") == "error":
                    reason = (first or {}).get("reason", "no response")
                    await self.events.put(("net", f"refused:{reason}"))
                    return
                self.connected = True
                backoff = 1.0
                await self.events.put(("net", "up"))
                await self.events.put(("msg", first))
                while True:
                    msg = await read_msg(reader)
                    if msg is None:
                        break
                    await self.events.put(("msg", msg))
            except (OSError, asyncio.TimeoutError, ConnectionError):
                pass
            self.connected = False
            self._writer = None
            if self._closed:
                return
            await self.events.put(("net", "down"))
            await asyncio.sleep(backoff)
            backoff = min(backoff * 1.7, 10.0)

    async def send_action(self, action: dict) -> None:
        if self._writer and not self._writer.is_closing():
            try:
                await send_msg(self._writer, {"t": "action", **action})
            except (ConnectionError, OSError):
                pass

    def close(self) -> None:
        self._closed = True
        if self._writer:
            self._writer.close()


# ---------------------------------------------------------------------------
# Relay transport (rung 3): both sides connect OUT to a dumb pairing relay,
# so CGNAT and firewalls stop mattering. See relay/relay.py in this repo.
# ---------------------------------------------------------------------------

RELAY_HOST = "relay.rustema.app"
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def make_room_code() -> str:
    import random as _random

    return "".join(_random.choice(_CODE_ALPHABET) for _ in range(6))


def looks_like_code(text: str) -> bool:
    text = text.strip().upper()
    return (
        3 <= len(text) <= 12
        and "." not in text
        and ":" not in text
        and all(c in _CODE_ALPHABET for c in text)
    )


def relay_urls(relay: str | None = None) -> list[str]:
    if relay and relay.startswith(("ws://", "wss://")):
        return [relay]
    host = relay or RELAY_HOST
    return [f"wss://{host}/ws", f"ws://{host}:5711/ws"]


async def connect_relay(role: str, room: str, relay: str | None = None):
    """Open a relay websocket and register; returns it once ready."""
    import websockets

    last: Exception = OSError("relay unreachable")
    for url in relay_urls(relay):
        try:
            ws = await websockets.connect(
                url, open_timeout=6, close_timeout=3, max_size=MAX_LINE
            )
            await ws.send(json.dumps({"role": role, "room": room}))
            return ws
        except Exception as exc:  # noqa: BLE001
            last = exc
    raise last


class _WSReader:
    """Adapter: read relay frames through the JSON-lines interface."""

    def __init__(self, ws) -> None:
        self.ws = ws

    async def readline(self) -> bytes:
        try:
            frame = await self.ws.recv()
        except Exception:  # noqa: BLE001
            return b""
        if isinstance(frame, str):
            frame = frame.encode()
        return frame + b"\n"


class _WSWriter:
    """Adapter: write JSON lines as relay frames."""

    def __init__(self, ws) -> None:
        self.ws = ws
        self._buffer = b""
        self._closed = False

    def write(self, data: bytes) -> None:
        self._buffer += data

    async def drain(self) -> None:
        data, self._buffer = self._buffer, b""
        for line in data.split(b"\n"):
            if line:
                try:
                    await self.ws.send(line.decode())
                except Exception:  # noqa: BLE001
                    self._closed = True
                    raise ConnectionError("relay send failed")

    def is_closing(self) -> bool:
        return self._closed

    def close(self) -> None:
        self._closed = True
        try:
            asyncio.get_event_loop().create_task(self.ws.close())
        except RuntimeError:
            pass


async def _await_paired(ws) -> bool:
    try:
        frame = await ws.recv()
        msg = json.loads(frame)
        return bool(msg.get("paired"))
    except Exception:  # noqa: BLE001
        return False


class RelaySlots:
    """Host side: keeps a spare relay connection parked per room code;
    every pairing becomes a normal client stream on the HostServer."""

    def __init__(self, server: HostServer, room: str, relay: str | None = None) -> None:
        self.server = server
        self.room = room
        self.relay = relay
        self.ok: bool | None = None  # None = still trying
        self._stopped = False

    async def run(self) -> None:
        while not self._stopped:
            try:
                ws = await connect_relay("host", self.room, self.relay)
                self.ok = True
                if not await _await_paired(ws):
                    await asyncio.sleep(2)
                    continue
                asyncio.get_event_loop().create_task(
                    self.server.handle_stream(_WSReader(ws), _WSWriter(ws))
                )
            except Exception:  # noqa: BLE001
                if self.ok is None:
                    self.ok = False
                if self._stopped:
                    return
                await asyncio.sleep(5)

    def stop(self) -> None:
        self._stopped = True
