#!/usr/bin/env bash
# Terminal // Night — крестики-нолики
# Стрелки / WASD — курсор, пробел — ход, цифры 1-9 — сразу, r — заново, q — выход.

[ -n "${BASH_VERSION:-}" ] || { printf 'Нужен bash.\n' >&2; exit 1; }

esc=$'\033'
reset="${esc}[0m"
bold="${esc}[1m"
dim="${esc}[38;5;60m"
accent="${esc}[38;5;111m"
mag="${esc}[38;5;176m"
green="${esc}[38;5;114m"
red="${esc}[38;5;203m"
rev="${esc}[7m"

cleanup() {
    printf '%s[?25h%s\n' "$esc" "$reset"
    if [ -t 0 ]; then stty echo icanon 2>/dev/null; fi
}
trap cleanup EXIT INT TERM

board=(' ' ' ' ' ' ' ' ' ' ' ' ' ' ' ' ' ')
cx=0; cy=0
turn=X
winner=''
moves=0
mode=1

win_lines=(0 1 2 3 4 5 6 7 8 0 3 6 1 4 7 2 5 8 0 4 8 2 4 6)

reset_game() {
    board=(' ' ' ' ' ' ' ' ' ' ' ' ' ' ' ' ' ')
    cx=0; cy=0; turn=X; winner=''; moves=0
}

check_win() {
    local p=$1 i a b c
    for i in 0 3 6 9 12 15 18 21; do
        a=${win_lines[i]}; b=${win_lines[i + 1]}; c=${win_lines[i + 2]}
        if [ "${board[a]}" = "$p" ] && [ "${board[b]}" = "$p" ] && [ "${board[c]}" = "$p" ]; then
            winner=$p
            return 0
        fi
    done
    return 1
}

would_win() {
    local p=$1 idx=$2
    [ "${board[idx]}" = ' ' ] || return 1
    board[idx]=$p
    if check_win "$p"; then
        board[idx]=' '
        winner=''
        return 0
    fi
    board[idx]=' '
    winner=''
    return 1
}

ai_move() {
    local i order
    for i in 0 1 2 3 4 5 6 7 8; do
        would_win O "$i" && { board[i]=O; winner=''; return; }
    done
    for i in 0 1 2 3 4 5 6 7 8; do
        would_win X "$i" && { board[i]=O; winner=''; return; }
    done
    if [ "${board[4]}" = ' ' ]; then board[4]=O; return; fi
    for i in 0 2 6 8; do
        [ "${board[i]}" = ' ' ] && { board[i]=O; return; }
    done
    for i in 1 3 5 7; do
        [ "${board[i]}" = ' ' ] && { board[i]=O; return; }
    done
}

draw_cell() {
    local i=$1 out
    case "${board[i]}" in
        X) out="${bold}${accent}X${reset}" ;;
        O) out="${bold}${mag}O${reset}" ;;
        *) out="${dim}$((i + 1))${reset}" ;;
    esac
    if [ $((cy * 3 + cx)) -eq "$i" ] && [ -z "$winner" ] && [ "$moves" -lt 9 ]; then
        out="${rev}${out}${reset}"
    fi
    printf ' %s ' "$out"
}

draw() {
    printf '%s[H%s[2J' "$esc" "$esc"
    printf '\n  %s%sКРЕСТИКИ-НОЛИКИ%s  %s·%s  ' "$bold" "$accent" "$reset" "$dim" "$reset"
    if [ -n "$winner" ]; then
        printf '%sПобедили %s%s%s\n\n' "$green" "$winner" "$reset"
    elif [ "$moves" -ge 9 ]; then
        printf '%sНичья%s\n\n' "$dim" "$reset"
    else
        printf 'ход %s%s%s\n\n' "$bold" "$turn" "$reset"
    fi
    printf '  %s┌───┬───┬───┐%s\n' "$dim" "$reset"
    local y x i
    for y in 0 1 2; do
        printf '  %s│%s' "$dim" "$reset"
        for x in 0 1 2; do
            i=$((y * 3 + x))
            draw_cell "$i"
            printf '%s│%s' "$dim" "$reset"
        done
        printf '\n'
        if [ "$y" -lt 2 ]; then printf '  %s├───┼───┼───┤%s\n' "$dim" "$reset"; fi
    done
    printf '  %s└───┴───┴───┘%s\n\n' "$dim" "$reset"
    printf '  %sстрелки / WASD%s  %sпробел%s ход  %s1-9%s сразу  %sr%s заново  %sq%s выход\n' \
        "$dim" "$reset" "$dim" "$reset" "$dim" "$reset" "$dim" "$reset" "$dim" "$reset"
    if [ -n "$winner" ] || [ "$moves" -ge 9 ]; then
        printf '\n  %sЕщё: r%s  %sВыход: q%s\n' "$dim" "$reset" "$dim" "$reset"
    fi
}

play_at() {
    local idx=$1
    [ -n "$winner" ] && return
    [ "$moves" -ge 9 ] && return
    [ "${board[idx]}" = ' ' ] || return
    board[idx]=$turn
    moves=$((moves + 1))
    if check_win "$turn"; then
        return
    fi
    if [ "$moves" -ge 9 ]; then
        return
    fi
    if [ "$turn" = X ]; then turn=O; else turn=X; fi
    if [ "$mode" -eq 1 ] && [ "$turn" = O ]; then
        ai_move
        moves=$((moves + 1))
        if check_win O; then
            return
        fi
        if [ "$moves" -lt 9 ]; then turn=X; fi
    fi
}

printf '%s[H%s[2J' "$esc" "$esc"
printf '\n  %s%sКРЕСТИКИ-НОЛИКИ%s\n\n' "$bold" "$accent" "$reset"
printf '  %s1%s — против компьютера\n' "$accent" "$reset"
printf '  %s2%s — вдвоём\n\n' "$accent" "$reset"
printf '  Выбор: '
IFS= read -rsn1 m || m=1
case "$m" in
    2) mode=2 ;;
    *) mode=1 ;;
esac

if [ -t 0 ]; then
    stty -echo -icanon 2>/dev/null
    printf '%s[?25l' "$esc"
fi

while :; do
    draw
    IFS= read -rsn1 key || break
    case "$key" in
        q|Q) break ;;
        r|R) reset_game; continue ;;
        ' ')
            play_at $((cy * 3 + cx))
            ;;
        [1-9]) play_at $((key - 1)) ;;
        h|H|a|A) [ "$cx" -gt 0 ] && cx=$((cx - 1)) ;;
        l|L|d|D) [ "$cx" -lt 2 ] && cx=$((cx + 1)) ;;
        k|K|w|W) [ "$cy" -gt 0 ] && cy=$((cy - 1)) ;;
        j|J|s|S) [ "$cy" -lt 2 ] && cy=$((cy + 1)) ;;
        "$esc")
            IFS= read -rsn1 -t 0.02 k2 || continue
            [ "$k2" = '[' ] || continue
            IFS= read -rsn1 -t 0.02 k3 || continue
            case "$k3" in
                A) [ "$cy" -gt 0 ] && cy=$((cy - 1)) ;;
                B) [ "$cy" -lt 2 ] && cy=$((cy + 1)) ;;
                C) [ "$cx" -lt 2 ] && cx=$((cx + 1)) ;;
                D) [ "$cx" -gt 0 ] && cx=$((cx - 1)) ;;
            esac
            ;;
    esac
done
