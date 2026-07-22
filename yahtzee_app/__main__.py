"""Entry point: `yahtzee` or `python -m yahtzee_app`."""

from __future__ import annotations

import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="yahtzee",
        description="Yahtzee in your terminal. Run without arguments for the menu.",
    )
    parser.add_argument("-V", "--version", action="store_true", help="show the version")
    parser.add_argument("--no-update", action="store_true", help="skip the update check")
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
    parser.add_argument("--seed", type=int, metavar="S", help="seed for the dice")
    args = parser.parse_args()

    if args.version:
        from . import __version__

        print(f"yahtzee v{__version__}")
        return
    if args.build_tables:
        from .solver.build import main as build_main

        build_main()
        return

    initial = None
    if args.bots is not None or args.level or args.rules or args.seed is not None:
        from .bots import DIFFICULTIES
        from .game import RULESETS
        from .config import load_settings

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
        initial = {"difficulties": levels[:n], "rules": rules, "seed": args.seed}

    # Preload the default table before the TUI starts, so a missing table
    # builds with visible progress instead of freezing the interface.
    from .solver.tables import load_table

    load_table((initial or {}).get("rules", "official"))

    from .ui.app import run

    run(no_update=args.no_update, initial=initial)


if __name__ == "__main__":
    main()
