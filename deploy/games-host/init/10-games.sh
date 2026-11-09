#!/bin/bash
# Eenmalige inrichting van de games-host (draait bij elke containerstart,
# maar is idempotent). Installeert tmux + de spellen voor de ssh-user.
set -e
apk add --no-cache tmux python3 py3-pip py3-numpy git >/dev/null

# tmux zonder prefix of statusbalk: spelers kunnen er niet "uit" naar een
# tmux-commandoprompt; de sessie is puur een volhardende terminal.
cat > /config/.tmux.conf <<'TMUX'
set -g prefix None
set -g prefix2 None
set -g status off
set -g mouse on
TMUX

# De spellen installeren/updaten via hun normale installer (POSIX sh). Als
# root met HOME=/config (de home van de ssh-user), daarna eigendom naar PUID.
for game in yahtzee solitaire sudoku; do
    up=$(echo "$game" | tr a-z A-Z)
    env HOME=/config "${up}_YES=1" sh -c "wget -qO- https://raw.githubusercontent.com/RaphaelA4U/$game/main/install.sh | sh" || true
done
chown -R "${PUID:-1000}:${PGID:-1000}" /config
