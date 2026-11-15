#!/usr/bin/env bash
# Terminal // Night — 2048
# Стрелки или h/j/k/l, q — выход.

[ -n "${BASH_VERSION:-}" ] || { printf 'Нужен bash.\n' >&2; exit 1; }

esc=$'\033'
reset="${esc}[0m"
bold="${esc}[1m"
dim="${esc}[38;5;60m"
accent="${esc}[38;5;111m"
mag="${esc}[38;5;176m"

cleanup() {
    printf '%s[?25h%s\n' "$esc" "$reset"
    if [ -t 0 ]; then stty echo icanon 2>/dev/null; fi
}
trap cleanup EXIT INT TERM

board=(0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0)
score=0
won=0
over=0

tile_color() {
    case "$1" in
        2)    printf '%s[38;5;189;48;5;237m' "$esc" ;;
        4)    printf '%s[38;5;189;48;5;238m' "$esc" ;;
        8)    printf '%s[38;5;234;48;5;111m' "$esc" ;;
        16)   printf '%s[38;5;234;48;5;117m' "$esc" ;;
        32)   printf '%s[38;5;234;48;5;114m' "$esc" ;;
        64)   printf '%s[38;5;234;48;5;179m' "$esc" ;;
        128)  printf '%s[38;5;234;48;5;215m' "$esc" ;;
        256)  printf '%s[38;5;234;48;5;203m' "$esc" ;;
        512)  printf '%s[38;5;234;48;5;141m' "$esc" ;;
        *)    printf '%s[1;38;5;234;48;5;111m' "$esc" ;;
    esac
}

draw_tile() {
    local v=$1
    if [ "$v" -eq 0 ]; then
        printf '       '
    else
        printf '%s' "$(tile_color "$v")"
        printf '%6s ' "$v"
        printf '%s' "$reset"
    fi
}

draw() {
    printf '%s[H%s[2J' "$esc" "$esc"
    printf '\n  %s%s2048%s  %s·%s  счёт %s%s%s' \
        "$bold" "$accent" "$reset" "$dim" "$reset" "$bold" "$score" "$reset"
    [ "$won" -eq 1 ] && printf '  %s· 2048!%s' "$accent" "$reset"
    printf '\n\n'
    printf '  %s┌───────┬───────┬───────┬───────┐%s\n' "$dim" "$reset"
    local r c i v
    for r in 0 1 2 3; do
        printf '  %s│%s' "$dim" "$reset"
        for c in 0 1 2 3; do
            i=$((r * 4 + c))
            draw_tile "${board[i]}"
            printf '%s│%s' "$dim" "$reset"
        done
        printf '\n'
        if [ "$r" -lt 3 ]; then
            printf '  %s├───────┼───────┼───────┼───────┤%s\n' "$dim" "$reset"
        fi
    done
    printf '  %s└───────┴───────┴───────┴───────┘%s\n\n' "$dim" "$reset"
    printf '  %sстрелки / hjkl%s   %sq%s — выход   %sr%s — заново\n' \
        "$dim" "$reset" "$dim" "$reset" "$dim" "$reset"
}

spawn() {
    local empty
    empty=()
    local i v
    for i in 0 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
        [ "${board[i]}" -eq 0 ] && empty+=("$i")
    done
    [ "${#empty[@]}" -eq 0 ] && return 1
    i=${empty[RANDOM % ${#empty[@]}]}
    if [ $((RANDOM % 10)) -eq 0 ]; then v=4; else v=2; fi
    board[i]=$v
}

merge_line() {
    local tmp
    tmp=()
    local v i n
    for v in "$@"; do
        [ "$v" -ne 0 ] && tmp+=("$v")
    done
    out=()
    n=${#tmp[@]}
    i=0
    while [ "$i" -lt "$n" ]; do
        if [ $((i + 1)) -lt "$n" ] && [ "${tmp[i]}" -eq "${tmp[i + 1]}" ]; then
            v=$((tmp[i] * 2))
            score=$((score + v))
            out+=("$v")
            i=$((i + 2))
        else
            out+=("${tmp[i]}")
            i=$((i + 1))
        fi
    done
    while [ "${#out[@]}" -lt 4 ]; do out+=(0); done
}

move_left() {
    local r c idx moved=0
    for r in 0 1 2 3; do
        merge_line "${board[r * 4]}" "${board[r * 4 + 1]}" "${board[r * 4 + 2]}" "${board[r * 4 + 3]}"
        for c in 0 1 2 3; do
            idx=$((r * 4 + c))
            [ "${board[idx]}" -ne "${out[c]}" ] && moved=1
            board[idx]=${out[c]}
        done
    done
    return $((1 - moved))
}

move_right() {
    local r c idx moved=0
    for r in 0 1 2 3; do
        merge_line "${board[r * 4 + 3]}" "${board[r * 4 + 2]}" "${board[r * 4 + 1]}" "${board[r * 4]}"
        for c in 0 1 2 3; do
            idx=$((r * 4 + 3 - c))
            [ "${board[idx]}" -ne "${out[c]}" ] && moved=1
            board[idx]=${out[c]}
        done
    done
    return $((1 - moved))
}

move_up() {
    local r c idx moved=0
    for c in 0 1 2 3; do
        merge_line "${board[c]}" "${board[4 + c]}" "${board[8 + c]}" "${board[12 + c]}"
        for r in 0 1 2 3; do
            idx=$((r * 4 + c))
            [ "${board[idx]}" -ne "${out[r]}" ] && moved=1
            board[idx]=${out[r]}
        done
    done
    return $((1 - moved))
}

move_down() {
    local r c idx moved=0
    for c in 0 1 2 3; do
        merge_line "${board[12 + c]}" "${board[8 + c]}" "${board[4 + c]}" "${board[c]}"
        for r in 0 1 2 3; do
            idx=$(((3 - r) * 4 + c))
            [ "${board[idx]}" -ne "${out[r]}" ] && moved=1
            board[idx]=${out[r]}
        done
    done
    return $((1 - moved))
}

can_move() {
    local i
    for i in 0 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
        [ "${board[i]}" -eq 0 ] && return 0
    done
    local r c
    for r in 0 1 2 3; do
        for c in 0 1 2; do
            [ "${board[r * 4 + c]}" -eq "${board[r * 4 + c + 1]}" ] && return 0
        done
    done
    for r in 0 1 2; do
        for c in 0 1 2 3; do
            [ "${board[r * 4 + c]}" -eq "${board[(r + 1) * 4 + c]}" ] && return 0
        done
    done
    return 1
}

check_state() {
    local v
    for v in "${board[@]}"; do
        if [ "$v" -ge 2048 ] && [ "$won" -eq 0 ]; then
            won=1
        fi
    done
    if ! can_move; then
        over=1
    fi
}

if [ -t 0 ]; then
    stty -echo -icanon 2>/dev/null
    printf '%s[?25l' "$esc"
fi

spawn
spawn

while [ "$over" -eq 0 ]; do
    draw
    IFS= read -rsn1 key || break
    before="${board[*]}"
    case "$key" in
        q|Q) break ;;
        r|R)
            board=(0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0)
            score=0; won=0; over=0
            spawn; spawn
            continue
            ;;
        h|a) move_left ;;
        l|d) move_right ;;
        k|w) move_up ;;
        j|s) move_down ;;
        "$esc")
            IFS= read -rsn1 -t 0.02 k2 || continue
            [ "$k2" = '[' ] || continue
            IFS= read -rsn1 -t 0.02 k3 || continue
            case "$k3" in
                A) move_up ;;
                B) move_down ;;
                C) move_right ;;
                D) move_left ;;
                *) continue ;;
            esac
            ;;
        *) continue ;;
    esac
    if [ "$before" != "${board[*]}" ]; then
        spawn
        check_state
    fi
done

draw
if [ "$over" -eq 1 ]; then
    printf '\n  %sИгра окончена.%s Счёт: %s%s%s\n\n' "$dim" "$reset" "$bold" "$score" "$reset"
    IFS= read -rsn1 _ || true
else
    printf '\n  %sСчёт: %s%s%s\n\n' "$dim" "$bold" "$score" "$reset"
fi
