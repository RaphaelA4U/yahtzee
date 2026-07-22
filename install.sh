#!/usr/bin/env bash
# One-line installer for the Yahtzee TUI:
#   curl -fsSL https://raw.githubusercontent.com/RaphaelA4U/yahtzee/main/install.sh | bash
#
# Installs into ~/.yahtzee, creates a virtualenv, and links the `yahtzee`
# command into ~/.local/bin. Safe to re-run; it then updates in place.
set -euo pipefail

REPO_URL="${YAHTZEE_REPO_URL:-https://github.com/RaphaelA4U/yahtzee.git}"
APP_DIR="${YAHTZEE_HOME:-$HOME/.yahtzee}"
BIN_DIR="$HOME/.local/bin"

say() { printf '\033[1;33m[yahtzee]\033[0m %s\n' "$1"; }

command -v git >/dev/null 2>&1 || { echo "Error: git is required."; exit 1; }

PYTHON="$(command -v python3 || true)"
if [ -z "$PYTHON" ]; then
    echo "Error: python3 (3.10 or newer) is required."
    exit 1
fi
if ! "$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
    echo "Error: python3 3.10+ is required (found: $("$PYTHON" -V))."
    exit 1
fi

if [ -d "$APP_DIR/.git" ]; then
    say "Existing install found in $APP_DIR; updating..."
    git -C "$APP_DIR" pull --ff-only
else
    say "Cloning into $APP_DIR ..."
    git clone --depth 1 "$REPO_URL" "$APP_DIR"
fi

if [ ! -x "$APP_DIR/.venv/bin/python" ]; then
    say "Creating virtualenv..."
    "$PYTHON" -m venv "$APP_DIR/.venv"
fi

say "Installing dependencies (textual, numpy)..."
"$APP_DIR/.venv/bin/pip" install -q --disable-pip-version-check -e "$APP_DIR"

mkdir -p "$BIN_DIR"
chmod +x "$APP_DIR/bin/yahtzee"
ln -sf "$APP_DIR/bin/yahtzee" "$BIN_DIR/yahtzee"

case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *)
        RC="$HOME/.profile"
        case "$(basename "${SHELL:-}")" in
            zsh) RC="$HOME/.zshrc" ;;
            bash) RC="$HOME/.bashrc" ;;
        esac
        if ! grep -qs 'Added by yahtzee installer' "$RC"; then
            printf '\n# Added by yahtzee installer\nexport PATH="$HOME/.local/bin:$PATH"\n' >> "$RC"
            say "Added $BIN_DIR to PATH in $RC"
        fi
        say "Open a new terminal (or run: source $RC) so the command is found."
        ;;
esac

"$APP_DIR/.venv/bin/python" -m yahtzee_app --version
say "Done! Start the game with: yahtzee"
