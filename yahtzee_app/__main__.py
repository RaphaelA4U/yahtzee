"""Entry point: `yahtzee` or `python -m yahtzee_app`."""

from __future__ import annotations

import sys


def main() -> None:
    argv = sys.argv[1:]
    if "--version" in argv or "-V" in argv:
        from . import __version__

        print(f"yahtzee v{__version__}")
        return
    if "--build-tables" in argv:
        from .solver.build import main as build_main

        build_main()
        return
    # Preload the default table before the TUI starts, so a missing table
    # builds with visible progress instead of freezing the interface.
    from .solver.tables import load_table

    load_table("official")

    from .ui.app import run

    run(no_update="--no-update" in argv)


if __name__ == "__main__":
    main()
