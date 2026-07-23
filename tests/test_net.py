"""Protocol tests for online multiplayer (host + client over localhost)."""

import asyncio

import pytest

from yahtzee_app import net


def test_parse_address():
    assert net.GameClient.parse_address("1.2.3.4:6000") == ("1.2.3.4", 6000)
    assert net.GameClient.parse_address("myhost") == ("myhost", net.DEFAULT_PORT)
    assert net.GameClient.parse_address(" host.tail:5333 ") == ("host.tail", 5333)


def test_device_id_is_stable():
    a = net.device_id()
    b = net.device_id()
    assert a == b and len(a) == 36


@pytest.mark.asyncio
async def test_host_client_roundtrip():
    server = net.HostServer("Hosty")
    port = await server.start()

    client = net.GameClient(f"127.0.0.1:{port}", "Guest")
    task = asyncio.create_task(client.run())
    try:
        kind, payload = await asyncio.wait_for(client.events.get(), timeout=5)
        assert (kind, payload) == ("net", "up")
        kind, msg = await asyncio.wait_for(client.events.get(), timeout=5)
        assert msg["t"] == "welcome"

        # Server sees the join
        ev = await asyncio.wait_for(server.events.get(), timeout=5)
        assert ev[0] == "join"
        assert server.seats[0].name == "Guest"

        # Client action reaches the host
        await client.send_action({"kind": "roll"})
        ev = await asyncio.wait_for(server.events.get(), timeout=5)
        assert ev[0] == "action" and ev[2]["kind"] == "roll"

        # Broadcast reaches the client
        await server.broadcast({"t": "state", "state": {"round": 1}, "events": ["x"]})
        kind, msg = await asyncio.wait_for(client.events.get(), timeout=5)
        assert msg["t"] == "state" and msg["state"]["round"] == 1
    finally:
        client.close()
        await server.stop()
        task.cancel()


@pytest.mark.asyncio
async def test_full_table_refused():
    server = net.HostServer("Hosty", max_remote=0)
    port = await server.start()
    client = net.GameClient(f"127.0.0.1:{port}", "Guest")
    task = asyncio.create_task(client.run())
    try:
        kind, payload = await asyncio.wait_for(client.events.get(), timeout=5)
        assert (kind, payload) == ("net", "refused:full")
    finally:
        client.close()
        await server.stop()
        task.cancel()


@pytest.mark.asyncio
async def test_online_host_end_to_end():
    """Host app + raw network guest play a full round over localhost."""
    import yahtzee_app.config as cfg
    from yahtzee_app.ui.app import HostLobbyScreen, OnlineHostScreen, YahtzeeApp

    settings = cfg.load_settings()
    settings.update({"n_bots": 1, "n_games": 1, "speed": "instant"})
    cfg.save_settings(settings)

    app = YahtzeeApp(no_update=True)
    async with app.run_test(size=(170, 45)) as pilot:
        await pilot.pause()
        app.push_screen(HostLobbyScreen())
        await pilot.pause(0.2)
        lobby = app.screen
        for _ in range(50):
            if lobby.server.port:
                break
            await pilot.pause(0.1)
        client = net.GameClient(f"127.0.0.1:{lobby.server.port}", "Guest")
        task = asyncio.create_task(client.run())
        for _ in range(50):
            if lobby.server.seats:
                break
            await pilot.pause(0.1)
        assert lobby.server.seats and lobby.server.seats[0].name == "Guest"

        lobby.action_start()
        await pilot.pause(0.3)
        screen = app.screen
        assert isinstance(screen, OnlineHostScreen)
        screen.settings["speed"] = "instant"
        assert [p.name for p in screen.players][:2] == ["Host", "Guest"]

        # Host plays their turn: roll once, then score Chance.
        await pilot.press("r")
        await pilot.pause(0.4)
        option = screen.human.card.score_option(12, screen.game.turn.counts())
        screen._score(screen.human, option)
        await pilot.pause(0.3)
        assert screen.game.current.name == "Guest"

        # Guest rolls and scores over the wire.
        await client.send_action({"kind": "roll"})
        for _ in range(50):
            await pilot.pause(0.1)
            if screen.game.turn.rolls_used == 1:
                break
        assert screen.game.turn.rolls_used == 1
        await client.send_action({"kind": "score", "category": 12})
        for _ in range(50):
            await pilot.pause(0.1)
            if screen.players[1].card.boxes[12] is not None:
                break
        assert screen.players[1].card.boxes[12] is not None

        # The guest received streamed states.
        states = 0
        while not client.events.empty():
            kind, payload = client.events.get_nowait()
            if kind == "msg" and payload.get("t") == "state":
                states += 1
        assert states >= 2
        client.close()
        await lobby.server.stop()
        task.cancel()


@pytest.mark.asyncio
async def test_online_client_screen_applies_states():
    from yahtzee_app.ui.app import OnlineClientScreen, YahtzeeApp

    me = net.device_id()
    state = {
        "version": "x",
        "config": {"difficulties": [], "mode": "normal", "rules": "official"},
        "n_games": 1,
        "game_no": 1,
        "finished": False,
        "round": 1,
        "current_idx": 1,
        "turn": {"dice": [1, 2, 3, 4, 5], "held": [False] * 5, "rolls_used": 0},
        "players": [
            {"name": "Hosty", "bot": False, "difficulty": None, "color": "#875fff",
             "boxes": [None] * 13, "ybonus": 0, "history": []},
            {"name": "Me", "bot": False, "difficulty": None, "color": "#ff6e9c",
             "boxes": [None] * 13, "ybonus": 0, "history": []},
        ],
        "uuids": ["host", me],
    }
    client = net.GameClient("127.0.0.1:59999", "Me")  # never connected
    app = YahtzeeApp(no_update=True)
    async with app.run_test(size=(170, 45)) as pilot:
        await pilot.pause()
        app.push_screen(OnlineClientScreen(client, state))
        await pilot.pause(0.2)
        screen = app.screen
        assert isinstance(screen, OnlineClientScreen)
        assert screen.local_idx == 1
        assert screen.human.name == "Me"
        assert screen.is_human_turn()

        # A new state from the host lands in the UI.
        state2 = dict(state)
        state2["turn"] = {"dice": [6, 6, 6, 6, 6], "held": [False] * 5, "rolls_used": 1}
        await client.events.put(("msg", {"t": "state", "state": state2, "events": ["hi"]}))
        await pilot.pause(0.3)
        assert screen.game.turn.dice == [6, 6, 6, 6, 6]
        assert screen.game.turn.rolls_used == 1
        client.close()


@pytest.mark.asyncio
async def test_relay_pairing_roundtrip():
    """Host and client meet through the relay: full protocol roundtrip."""
    import sys

    sys.path.insert(0, "relay")
    from aiohttp.test_utils import TestServer
    from relay import make_app

    relay_server = TestServer(make_app())
    await relay_server.start_server()
    relay_url = f"ws://127.0.0.1:{relay_server.port}/ws"

    server = net.HostServer("Hosty")
    room = net.make_room_code()
    server.relay = net.RelaySlots(server, room, relay=relay_url)
    slots_task = asyncio.create_task(server.relay.run())

    client = net.GameClient(room, "Guest", relay=relay_url)
    client_task = asyncio.create_task(client.run())
    try:
        kind, payload = await asyncio.wait_for(client.events.get(), timeout=8)
        assert (kind, payload) == ("net", "up")
        kind, msg = await asyncio.wait_for(client.events.get(), timeout=8)
        assert msg["t"] == "welcome"

        ev = await asyncio.wait_for(server.events.get(), timeout=8)
        assert ev[0] == "join"
        assert server.seats[0].name == "Guest"

        await client.send_action({"kind": "roll"})
        ev = await asyncio.wait_for(server.events.get(), timeout=8)
        assert ev[0] == "action" and ev[2]["kind"] == "roll"

        await server.broadcast({"t": "state", "state": {"round": 7}, "events": []})
        kind, msg = await asyncio.wait_for(client.events.get(), timeout=8)
        assert msg["t"] == "state" and msg["state"]["round"] == 7
    finally:
        client.close()
        await server.stop()
        slots_task.cancel()
        client_task.cancel()
        await relay_server.close()


def test_room_codes():
    code = net.make_room_code()
    assert len(code) == 6 and net.looks_like_code(code)
    assert not net.looks_like_code("1.2.3.4:5333")
    assert not net.looks_like_code("myhost:5333")


@pytest.mark.asyncio
async def test_lobby_screens_actually_render():
    """Regression: the lobby bodies must have real size on screen."""
    from textual.widgets import Input, Static

    from yahtzee_app.ui.app import HostLobbyScreen, JoinLobbyScreen, YahtzeeApp

    app = YahtzeeApp(no_update=True)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        app.push_screen(JoinLobbyScreen())
        await pilot.pause(0.3)
        name = app.screen.query_one("#join-name", Input)
        addr = app.screen.query_one("#join-address", Input)
        assert name.region.width > 10 and name.region.height >= 1
        assert addr.region.width > 10
        await pilot.press("escape")
        await pilot.pause(0.2)

        app.push_screen(HostLobbyScreen())
        await pilot.pause(0.5)
        host_name = app.screen.query_one("#lobby-name", Input)
        addresses = app.screen.query_one("#lobby-addresses", Static)
        assert host_name.region.width > 10 and host_name.region.height >= 1
        assert addresses.region.width > 10
        await pilot.press("escape")
        await pilot.pause(0.2)
