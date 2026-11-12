"""Every finished game is kept turn by turn in games.jsonl."""

import json

import pytest

import yahtzee_app.config as cfg
import yahtzee_app.net as net
from yahtzee_app.game import (
    CATEGORY_NAMES,
    Game,
    Player,
    Scorecard,
    counts_of,
    replay,
)


def _play_engine_game(seed: int, n_players: int = 2) -> Game:
    """A whole game on the bare engine: hold the most common face, reroll the
    rest, then take the highest-scoring box."""
    players = [Player(f"P{i}", card=Scorecard("official")) for i in range(n_players)]
    game = Game(players, seed=seed)
    while not game.finished:
        turn = game.turn
        turn.roll()
        while turn.rolls_left > 0:
            counts = turn.counts()
            face = max(range(6), key=lambda f: (counts[f], f))
            turn.held = [d == face + 1 for d in turn.dice]
            if all(turn.held):
                break
            turn.roll()
        card = game.current.card
        option = max(card.options(turn.counts()), key=lambda o: (o.points, -o.category))
        card.apply(option, turn.counts())
        game.record_turn(option)
        game.advance()
    return game


def test_engine_log_replays_to_the_same_cards():
    game = _play_engine_game(seed=11)
    assert len(game.log) == 13 * 2
    for t in game.log:
        assert 1 <= len(t["rolls"]) <= 3
        assert len(t["held"]) == len(t["rolls"]) - 1
        assert t["category"] == CATEGORY_NAMES[t["cat"]]
    cards = replay(game.log, 2, "official")
    for card, player in zip(cards, game.players):
        assert card.boxes == player.card.boxes
        assert card.total() == player.card.total()
    # Same seed, same dice: the log is reproducible.
    assert _play_engine_game(seed=11).log == game.log


def test_replay_refuses_a_log_that_does_not_add_up():
    game = _play_engine_game(seed=5)
    bad_points = json.loads(json.dumps(game.log))
    bad_points[0]["points"] += 1
    with pytest.raises(ValueError):
        replay(bad_points, 2)
    # A held die that changes value on the reroll.
    turns = json.loads(json.dumps(game.log))
    t = next(t for t in turns if t["held"] and any(t["held"][0]))
    i = t["held"][0].index(True)
    t["rolls"][1][i] = t["rolls"][0][i] % 6 + 1
    with pytest.raises(ValueError):
        replay(turns, 2)


def test_turn_rolls_and_holds_are_recorded():
    game = Game([Player("A", card=Scorecard())], seed=3)
    turn = game.turn
    turn.roll()
    first = list(turn.dice)
    turn.held = [True, False, True, False, False]
    turn.roll()
    assert turn.rolls[0] == first
    assert turn.holds == [[True, False, True, False, False]]
    assert turn.rolls[1][0] == first[0] and turn.rolls[1][2] == first[2]


def test_record_game_result_appends_a_line():
    cfg.record_game_result({"your_score": 200, "won": True})  # no game: stats only
    assert cfg.load_game_logs() == []
    cfg.record_game_result({"your_score": 250, "won": False}, game={"turns": [], "game_no": 1})
    logs = cfg.load_game_logs()
    assert len(logs) == 1 and logs[0]["your_score"] == 250 and logs[0]["turns"] == []
    stats = cfg.load_stats()
    assert [g["your_score"] for g in stats["games_v2"]] == [200, 250]
    assert logs[0]["date"] == stats["games_v2"][1]["date"]


def test_snapshot_keeps_the_turn_log():
    """Continue from the menu: the game so far and the turn in progress
    come back, so the finished game still lands whole in games.jsonl."""
    from yahtzee_app.ui.app import GameConfig, GameScreen

    config = GameConfig(difficulties=["easy"], mode="normal", seed=9)
    s1 = GameScreen(config)
    s1.game.turn.roll()
    opt = s1.human.card.score_option(12, s1.game.turn.counts())
    s1.human.card.apply(opt, s1.game.turn.counts())
    s1.game.record_turn(opt)
    s1.game.advance()
    s1.game.turn.roll()
    s1.game.turn.held = [True] * 4 + [False]
    s1.game.turn.roll()
    snap = json.loads(json.dumps(s1._snapshot()))
    s2 = GameScreen(config, snapshot=snap)
    assert s2.game.log == s1.game.log and len(s2.game.log) == 1
    assert s2.game.turn.rolls == s1.game.turn.rolls
    assert s2.game.turn.holds == s1.game.turn.holds
    assert s2.game.seed == 9


@pytest.mark.asyncio
async def test_finished_match_logs_every_game_with_all_turns():
    from yahtzee_app.ui.app import GameConfig, GameScreen, YahtzeeApp

    cfg.save_settings(dict(cfg.load_settings(), win_animation=False))
    app = YahtzeeApp(no_update=True)
    async with app.run_test(size=(160, 45)) as pilot:
        app.start_game(GameConfig(difficulties=["easy"], mode="auto", n_games=2, seed=4))
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, GameScreen)
        screen.settings["speed"] = "instant"
        for _ in range(1600):
            await pilot.pause(0.05)
            if screen._recorded:
                break
        assert screen._recorded
    logs = cfg.load_game_logs()
    assert [g["game_no"] for g in logs] == [1, 2]
    assert logs[0]["seed"] == 4 and logs[1]["seed"] == 4  # the whole match plays the seed
    stats = cfg.load_stats()["games_v2"]
    for line, entry in zip(logs, stats):
        # The stats entry, plus the game itself.
        assert {k: line[k] for k in entry} == entry
        assert line["rules"] == "official" and line["n_games"] == 2
        assert len(line["turns"]) == 13 * 2
        cards = replay(line["turns"], 2, line["rules"])
        assert [c.total() for c in cards] == [p["score"] for p in line["players"]]
        assert cards[0].boxes == line["boxes"]
        for t in line["turns"]:
            assert len(t["held"]) == len(t["rolls"]) - 1


@pytest.mark.asyncio
async def test_host_keeps_the_log_out_of_the_protocol():
    from yahtzee_app.ui.app import GameConfig, OnlineHostScreen, YahtzeeApp

    cfg.clear_online_snapshot()
    config = GameConfig(difficulties=[], mode="normal", rules="official", n_games=1)
    server = net.HostServer("Hosty")
    server.seats.append(net.Seat(uuid="dev-1", name="Guesty"))
    await server.start()
    app = YahtzeeApp(no_update=True)
    try:
        async with app.run_test(size=(170, 45)) as pilot:
            await pilot.pause()
            app.push_screen(OnlineHostScreen(config, server))
            await pilot.pause(0.2)
            screen = app.screen
            screen.settings["speed"] = "instant"
            await pilot.press("r")
            await pilot.pause(0.4)
            option = screen.human.card.score_option(12, screen.game.turn.counts())
            screen._score(screen.human, option)
            await pilot.pause(0.3)
            assert "turn_log" not in screen._net_state()
            saved = cfg.load_online_snapshot()
            assert saved["turn_log"]["turns"][0]["category"] == "Chance"
    finally:
        await server.stop()
        cfg.clear_online_snapshot()


def _state(me: str, seq: int, current: int, round_no: int, rolls_used: int,
           dice=(1, 1, 1, 1, 1), held=(False,) * 5, boxes=None, finished=False,
           history=None) -> dict:
    boxes = boxes or [[None] * 13, [None] * 13]
    history = history or [[], []]
    return {
        "version": "x",
        "config": {"difficulties": [], "mode": "normal", "rules": "official"},
        "n_games": 1,
        "game_no": 1,
        "finished": finished,
        "round": round_no,
        "current_idx": current,
        "turn": {"dice": list(dice), "held": list(held), "rolls_used": rolls_used},
        "players": [
            {"name": "Hosty", "bot": False, "difficulty": None, "color": "#875fff",
             "boxes": boxes[0], "ybonus": 0, "history": history[0]},
            {"name": "Me", "bot": False, "difficulty": None, "color": "#ff6e9c",
             "boxes": boxes[1], "ybonus": 0, "history": history[1]},
        ],
        "uuids": ["host", me],
        "seq": seq,
    }


@pytest.mark.asyncio
async def test_joined_player_logs_turns_seen_in_broadcasts():
    """A joiner does not roll the dice itself; it rebuilds the turns from the
    host's states (no protocol change) and logs its finished game too."""
    from yahtzee_app.ui.app import OnlineClientScreen, YahtzeeApp

    cfg.save_settings(dict(cfg.load_settings(), win_animation=False))
    me = net.device_id()
    client = net.GameClient("127.0.0.1:59999", "Me")
    app = YahtzeeApp(no_update=True)
    async with app.run_test(size=(170, 45)) as pilot:
        await pilot.pause()
        app.push_screen(OnlineClientScreen(client, _state(me, 0, 0, 1, 0)))
        await pilot.pause(0.2)
        screen = app.screen
        b0 = [None] * 13
        b0[9] = 30
        b1 = [None] * 13
        b1[11] = 50
        states = [
            _state(me, 1, 0, 1, 1, dice=(1, 2, 3, 4, 5)),
            _state(me, 2, 0, 1, 2, dice=(1, 2, 3, 4, 6), held=(True, True, True, True, False)),
            _state(me, 3, 1, 1, 0, boxes=[b0, [None] * 13]),
            _state(me, 4, 1, 1, 1, dice=(6, 6, 6, 6, 6), boxes=[b0, [None] * 13]),
            _state(me, 5, 0, 2, 0, boxes=[b0, b1]),
        ]
        for st in states:
            screen._apply_state(st, [])
            await pilot.pause(0.05)
        turns = screen._obs_turns
        assert [(t["player"], t["category"], t["points"]) for t in turns] == [
            (0, "Small Straight", 30), (1, "Yahtzee", 50)]
        assert turns[0]["rolls"] == [[1, 2, 3, 4, 5], [1, 2, 3, 4, 6]]
        assert turns[0]["held"] == [[True, True, True, True, False]]
        assert turns[1]["rolls"] == [[6, 6, 6, 6, 6]] and turns[1]["held"] == []
        assert counts_of(turns[1]["rolls"][-1])[5] == 5

        full0 = [1] * 13
        full0[9] = 30
        full1 = [5] * 13
        full1[11] = 50
        done = _state(me, 6, 0, 14, 0, finished=True,
                      history=[[{"boxes": full0, "ybonus": 0}], [{"boxes": full1, "ybonus": 0}]])
        screen._apply_state(done, [])
        await pilot.pause(0.1)
        client.close()
    logs = cfg.load_game_logs()
    assert len(logs) == 1
    line = logs[0]
    assert line["online"] and line["observed"] and line["game_no"] == 1
    assert [t["category"] for t in line["turns"]] == ["Small Straight", "Yahtzee"]
    assert "game" not in line["turns"][0]


def test_a_seed_gives_everyone_the_same_dice():
    # Fair races and challenges: with a seed every roll of a round is fixed, whatever
    # was held before and whoever rolls it.
    game = Game([Player("A", card=Scorecard()), Player("B", card=Scorecard())], seed=42)
    game.turn.roll()
    first_a = list(game.turn.dice)
    game.turn.toggle_hold(0)
    game.turn.roll()
    second_a = list(game.turn.dice)
    other = Game([Player("C", card=Scorecard())], seed=42)
    other.turn.roll()
    assert other.turn.dice == first_a
    other.turn.toggle_hold(3)
    other.turn.roll()
    # Rerolled dice get the same values as in A's second roll; held dice keep theirs.
    assert [other.turn.dice[i] for i in (1, 2, 4)] == [second_a[i] for i in (1, 2, 4)]
    assert other.turn.dice[3] == first_a[3]
    # Another seed, other dice; another game of the match, other dice.
    assert Game([Player("D", card=Scorecard())], seed=43).turn.key != game.turn.key
    assert Game([Player("E", card=Scorecard())], seed=42, game_no=2).dice_key() != "42:1:1"
