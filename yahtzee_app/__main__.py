"""Entry point: `yahtzee` or `python -m yahtzee_app`."""

from __future__ import annotations

import argparse
import os
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="yahtzee",
        description="Yahtzee in your terminal. Run without arguments for the menu.",
    )
    parser.add_argument("-V", "--version", action="store_true", help="show the version")
    parser.add_argument(
        "--profile",
        metavar="NAME",
        help="use a separate profile (own settings, stats, identity); handy "
        "for a second instance on the same machine",
    )
    parser.add_argument(
        "--new", action="store_true", help="skip the menu and start a match with your saved settings"
    )
    parser.add_argument("--no-update", action="store_true", help="skip the update check")
    parser.add_argument(
        "--resume", action="store_true", help="reopen the saved game right away"
    )
    parser.add_argument(
        "--build-tables", action="store_true", help="rebuild the solver tables"
    )
    parser.add_argument(
        "--bots", type=int, metavar="N", help="start a game with N bots (1-4)"
    )
    parser.add_argument(
        "--level",
        metavar="L",
        help="bot difficulty: easy|medium|hard|optimal, or a comma list per bot",
    )
    parser.add_argument(
        "--rules", metavar="R", help="rule variant: official|free_joker|simple"
    )
    parser.add_argument(
        "--games", type=int, metavar="G", help="games per match (1-6, a column each)"
    )
    parser.add_argument("--seed", type=int, metavar="S", help="seed for the dice")
    parser.add_argument(
        "--name", metavar="NAME",
        help="set your player name (saved in the active profile)",
    )
    parser.add_argument(
        "--color", metavar="#RRGGBB",
        help="set your fixed player color (used as-is by everyone online, "
        "instead of the everyone-sees-themselves-purple scheme)",
    )
    parser.add_argument(
        "--host", metavar="CODE",
        help="host an online game with this fixed room code (6 letters); an "
        "unfinished match with the same code resumes automatically",
    )
    parser.add_argument(
        "--join", metavar="CODE",
        help="join an online game with this room code right away",
    )
    args = parser.parse_args()

    if args.profile:
        os.environ["YAHTZEE_PROFILE"] = args.profile

    if args.version:
        from . import __version__

        print(f"yahtzee v{__version__}")
        return
    if args.build_tables:
        try:
            from .solver.build import main as build_main
        except Exception as exc:  # noqa: BLE001
            print(f"Cannot build tables: the solver needs numpy ({exc}).")
            raise SystemExit(2)

        build_main()
        return

    # Claude-style eager update: pull before the UI starts, then re-exec so
    # you are always ON the latest version, not merely notified about it.
    if not args.no_update:
        from .update import quick_sync_update

        if quick_sync_update():
            os.execv(
                sys.executable,
                [sys.executable, "-m", "yahtzee_app", *sys.argv[1:], "--no-update"],
            )

    initial = None
    if (
        args.new
        or args.bots is not None
        or args.level
        or args.rules
        or args.seed is not None
        or args.games is not None
    ):
        from .bots import DIFFICULTIES
        from .config import load_settings
        from .game import RULESETS

        settings = load_settings()
        levels = [
            lv.strip().lower() for lv in (args.level or "").split(",") if lv.strip()
        ] or [str(settings.get("difficulty", "medium"))]
        bad = next((lv for lv in levels if lv not in DIFFICULTIES), None)
        if bad:
            parser.error(f"unknown level: {bad} (choose from {', '.join(DIFFICULTIES)})")
        n = args.bots if args.bots is not None else max(len(levels), 1)
        n = max(1, min(4, n))
        if len(levels) == 1:
            levels = levels * n
        rules = (args.rules or settings.get("ruleset", "official")).lower()
        if rules not in RULESETS:
            parser.error(f"unknown rules: {rules} (choose from {', '.join(RULESETS)})")
        n_games = max(1, min(6, args.games or int(settings.get("n_games", 1))))
        initial = {
            "difficulties": levels[:n],
            "rules": rules,
            "seed": args.seed,
            "n_games": n_games,
        }

    # Preload the default table before the TUI starts, so a missing table
    # builds with visible progress instead of freezing the interface.
    # Without a working numpy (iSH) the game starts in lite mode instead.
    try:
        from .solver.tables import load_table

        load_table((initial or {}).get("rules", "official"))
    except Exception:  # noqa: BLE001
        print(
            "Solver unavailable (numpy missing or unusable); starting in lite "
            "mode: online play and easy/medium bots work, hints/coach/auto are off."
        )

    from .ui.app import run

    online = None
    if args.host or args.join:
        from . import net

        role = "host" if args.host else "join"
        code = (args.host or args.join).strip().upper()
        if not net.looks_like_code(code):
            print(f"Not a valid room code: {code} (6 letters/digits, e.g. ABC234)")
            raise SystemExit(2)
        online = (role, code)
        initial = None

    if args.name or args.color:
        import re as _re

        from . import config

        settings = config.load_settings()
        if args.name:
            settings["player_name"] = args.name.strip()[:16]
        if args.color:
            color = args.color.strip()
            if not _re.fullmatch(r"#[0-9a-fA-F]{6}", color):
                print(f"Not a valid color: {color} (expected #RRGGBB)")
                raise SystemExit(2)
            settings["player_color"] = color
        config.save_settings(settings)

    run(no_update=args.no_update, initial=initial, resume=args.resume, online=online)


if __name__ == "__main__":
    main()
