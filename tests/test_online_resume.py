"""Viewer-relative colors, client roll animation, and online resume."""

import asyncio

import pytest

import yahtzee_app.config as cfg
import yahtzee_app.net as net


def _client_state(me: str) -> dict:
    return {
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


@pytest.mark.asyncio
async def test_client_viewer_relative_colors():
    from yahtzee_app.ui.app import (
        ACCENT,
        PLAYER_COLOR_POOL,
        OnlineClientScreen,
        YahtzeeApp,
    )

    me = net.device_id()
    client = net.GameClient("127.0.0.1:59999", "Me")  # never connected
    app = YahtzeeApp(no_update=True)
    async with app.run_test(size=(170, 45)) as pilot:
        await pilot.pause()
        app.push_screen(OnlineClientScreen(client, _client_state(me)))
        await pilot.pause(0.2)
        screen = app.screen
        # You are always purple on your own screen; the host gets a pool color.
        assert screen.human.color == ACCENT
        assert screen.players[0].color == PLAYER_COLOR_POOL[0]
        # Host-perspective colors in shared log lines are rewritten, both ways
        # at once (the host's purple and my pool color swap places).
        line = f"[{ACCENT}]Hosty[/{ACCENT}] scores; [#ff6e9c]Me[/#ff6e9c] is next"
        local = screen._localize(line)
        assert f"[{PLAYER_COLOR_POOL[0]}]Hosty[/{PLAYER_COLOR_POOL[0]}]" in local
        assert f"[{ACCENT}]Me[/{ACCENT}]" in local
        client.close()


@pytest.mark.asyncio
async def test_client_animates_incoming_roll():
    from yahtzee_app.ui.app import OnlineClientScreen, YahtzeeApp

    me = net.device_id()
    client = net.GameClient("127.0.0.1:59999", "Me")
    app = YahtzeeApp(no_update=True)
    async with app.run_test(size=(170, 45)) as pilot:
        await pilot.pause()
        app.push_screen(OnlineClientScreen(client, _client_state(me)))
        await pilot.pause(0.2)
        screen = app.screen
        state2 = dict(_client_state(me))
        state2["turn"] = {"dice": [6, 6, 6, 6, 6], "held": [False] * 5, "rolls_used": 1}
        await client.events.put(("msg", {"t": "state", "state": state2, "events": []}))
        await pilot.pause(0.1)
        assert screen._rolling  # the roll animation is running
        await pilot.pause(0.5)
        assert not screen._rolling
        assert screen.game.turn.dice == [6, 6, 6, 6, 6]
        client.close()


@pytest.mark.asyncio
async def test_host_resume_from_snapshot_serves_state():
    """Host quits mid-match; Resume hosting reopens it, and a rejoining
    client with the reserved uuid immediately receives the saved state."""
    from yahtzee_app.ui.app import GameConfig, OnlineHostScreen, YahtzeeApp

    guest_uuid = "guest-uuid-1234"
    snap = {
        "version": "x",
        "config": {"difficulties": ["easy"], "mode": "normal", "rules": "official"},
        "n_games": 1,
        "game_no": 1,
        "finished": False,
        "round": 4,
        "current_idx": 1,
        "turn": {"dice": [2, 2, 3, 4, 5], "held": [False] * 5, "rolls_used": 1},
        "players": [
            {"name": "Hosty", "bot": False, "difficulty": None, "color": "#875fff",
             "boxes": [12] + [None] * 12, "ybonus": 0, "history": []},
            {"name": "Guesty", "bot": False, "difficulty": None, "color": "#ff6e9c",
             "boxes": [None] * 13, "ybonus": 0, "history": []},
            {"name": "Bo (BOT)", "bot": True, "difficulty": "easy", "color": "#35c9b0",
             "boxes": [None] * 13, "ybonus": 0, "history": []},
        ],
        "uuids": ["host", guest_uuid, ""],
        "online_host": {"room": "ABCDEF", "host_name": "Hosty"},
    }
    config = GameConfig(
        difficulties=["easy"], mode="normal", rules="official", n_games=1
    )
    server = net.HostServer("Hosty")
    server.started = True
    server.seats.append(net.Seat(uuid=guest_uuid, name="Guesty"))
    server._last_state = {k: v for k, v in snap.items() if k != "online_host"}
    port = await server.start()

    app = YahtzeeApp(no_update=True)
    async with app.run_test(size=(170, 45)) as pilot:
        await pilot.pause()
        app.push_screen(OnlineHostScreen(config, server, snapshot=snap))
        await pilot.pause(0.3)
        screen = app.screen
        assert isinstance(screen, OnlineHostScreen)
        assert screen.game.round == 4
        assert screen.game.current_idx == 1
        assert screen._uuid_by_player == {1: guest_uuid}
        assert screen.players[2].is_bot
        # The resumed match keeps persisting for the next resume.
        assert cfg.load_online_snapshot() is not None

        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        await net.send_msg(
            writer,
            {
                "t": "hello",
                "v": net.PROTOCOL_VERSION,
                "uuid": guest_uuid,
                "name": "Guesty",
                "stats": {},
            },
        )
        welcome = await net.read_msg(reader)
        assert welcome["t"] == "welcome"
        assert welcome["name"] == "Guesty"
        msg = await net.read_msg(reader)
        assert msg["t"] == "state"
        assert msg["state"]["round"] == 4
        writer.close()
        await pilot.pause(0.2)
    await server.stop()


def test_online_snapshot_roundtrip():
    cfg.save_online_snapshot({"round": 7})
    assert cfg.load_online_snapshot() == {"round": 7}
    cfg.clear_online_snapshot()
    assert cfg.load_online_snapshot() is None
