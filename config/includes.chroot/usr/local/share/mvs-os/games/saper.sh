#!/usr/bin/env bash
# Terminal // Night — сапёр
# Стрелки / WASD — курсор, пробел — открыть, f — флаг, q — выход.

[ -n "${BASH_VERSION:-}" ] || { printf 'Нужен bash.\n' >&2; exit 1; }

esc=$'\033'
reset="${esc}[0m"
bold="${esc}[1m"
dim="${esc}[38;5;60m"
accent="${esc}[38;5;111m"
red="${esc}[38;5;203m"
yellow="${esc}[38;5;179m"
green="${esc}[38;5;114m"
cyan="${esc}[38;5;117m"
mag="${esc}[38;5;176m"
rev="${esc}[7m"

cleanup() {
    printf '%s[?25h%s\n' "$esc" "$reset"
    if [ -t 0 ]; then stty echo icanon 2>/dev/null; fi
}
trap cleanup EXIT INT TERM

N=9
MINES=10
TOTAL=$((N * N))

reset_board() {
    local i
    mine=(); open=(); flag=(); num=()
    i=0
    while [ "$i" -lt "$TOTAL" ]; do
        mine[i]=0; open[i]=0; flag[i]=0; num[i]=0
        i=$((i + 1))
    done
    cx=0; cy=0
    flags=0; opened=0; placed=0; dead=0; win=0
    start=$SECONDS
}

place_mines() {
    local sx=$1 sy=$2 placed_count=0 idx x y dx dy
    while [ "$placed_count" -lt "$MINES" ]; do
        idx=$((RANDOM % TOTAL))
        x=$((idx % N))
        y=$((idx / N))
        dx=$((x - sx)); [ "$dx" -lt 0 ] && dx=$((-dx))
        dy=$((y - sy)); [ "$dy" -lt 0 ] && dy=$((-dy))
        [ "$dx" -le 1 ] && [ "$dy" -le 1 ] && continue
        [ "${mine[idx]}" -eq 1 ] && continue
        mine[idx]=1
        placed_count=$((placed_count + 1))
    done
    placed=1
    local yy xx c ny nx
    for yy in $(seq 0 $((N - 1))); do
        for xx in $(seq 0 $((N - 1))); do
            c=0
            for dy in -1 0 1; do
                for dx in -1 0 1; do
                    [ "$dy" -eq 0 ] && [ "$dx" -eq 0 ] && continue
                    ny=$((yy + dy)); nx=$((xx + dx))
                    [ "$ny" -lt 0 ] || [ "$ny" -ge "$N" ] && continue
                    [ "$nx" -lt 0 ] || [ "$nx" -ge "$N" ] && continue
                    [ "${mine[$((ny * N + nx))]}" -eq 1 ] && c=$((c + 1))
                done
            done
            num[$((yy * N + xx))]=$c
        done
    done
}

reveal() {
    local x=$1 y=$2
    local stx sty
    local last idx
    stx=("$x"); sty=("$y")
    while [ "${#stx[@]}" -gt 0 ]; do
        last=$((${#stx[@]} - 1))
        x=${stx[last]}; y=${sty[last]}
        unset "stx[$last]" "sty[$last]"
        idx=$((y * N + x))
        [ "${flag[idx]}" -eq 1 ] && continue
        [ "${open[idx]}" -eq 1 ] && continue
        open[idx]=1
        if [ "${mine[idx]}" -eq 1 ]; then
            dead=1
            return
        fi
        opened=$((opened + 1))
        if [ "${num[idx]}" -eq 0 ]; then
            local dx dy nx ny
            for dy in -1 0 1; do
                for dx in -1 0 1; do
                    [ "$dy" -eq 0 ] && [ "$dx" -eq 0 ] && continue
                    ny=$((y + dy)); nx=$((x + dx))
                    [ "$ny" -lt 0 ] || [ "$ny" -ge "$N" ] && continue
                    [ "$nx" -lt 0 ] || [ "$nx" -ge "$N" ] && continue
                    [ "${open[$((ny * N + nx))]}" -eq 1 ] && continue
                    stx+=("$nx"); sty+=("$ny")
                done
            done
        fi
    done
}

cell_text() {
    local x=$1 y=$2 idx=$((y * N + x)) out
    if [ "${mine[idx]}" -eq 1 ] && { [ "${open[idx]}" -eq 1 ] || [ "$dead" -eq 1 ]; }; then
        out="${red}*${reset}"
    elif [ "${open[idx]}" -eq 1 ]; then
        if [ "${num[idx]}" -eq 0 ]; then
            out=' '
        else
            case "${num[idx]}" in
                1) out="${cyan}1${reset}" ;;
                2) out="${green}2${reset}" ;;
                3) out="${red}3${reset}" ;;
                4) out="${mag}4${reset}" ;;
                5) out="${yellow}5${reset}" ;;
                6) out="${cyan}6${reset}" ;;
                7) out="${bold}7${reset}" ;;
                *) out="${red}8${reset}" ;;
            esac
        fi
    elif [ "${flag[idx]}" -eq 1 ]; then
        out="${yellow}F${reset}"
    else
        out="${dim}.${reset}"
    fi
    if [ "$x" -eq "$cx" ] && [ "$y" -eq "$cy" ]; then
        out="${rev}${out}${reset}"
    fi
    printf '%s ' "$out"
}

draw() {
    local x y line
    printf '%s[H%s[2J' "$esc" "$esc"
    printf '\n  %s%sСАПЁР%s  %s·%s  мин %s%s%s  %s·%s  флагов %s%s%s  %s·%s  %s%ss%s\n\n' \
        "$bold" "$accent" "$reset" "$dim" "$reset" "$bold" "$MINES" "$reset" \
        "$dim" "$reset" "$bold" "$flags" "$reset" "$dim" "$reset" "$bold" "$((SECONDS - start))" "$reset"
    printf '   '
    for x in $(seq 0 $((N - 1))); do printf '%s%s%s ' "$dim" "$((x + 1))" "$reset"; done
    printf '\n'
    for y in $(seq 0 $((N - 1))); do
        printf '  %s%2d%s ' "$dim" "$((y + 1))" "$reset"
        for x in $(seq 0 $((N - 1))); do
            cell_text "$x" "$y"
        done
        printf '\n'
    done
    printf '\n  %sстрелки / WASD%s  %sпробел%s открыть  %sf%s флаг  %sr%s заново  %sq%s выход\n' \
        "$dim" "$reset" "$dim" "$reset" "$dim" "$reset" "$dim" "$reset" "$dim" "$reset"
    if [ "$dead" -eq 1 ]; then
        printf '\n  %sМины.%s Нажми любую клавишу.\n' "$red" "$reset"
    elif [ "$win" -eq 1 ]; then
        printf '\n  %sПоле очищено!%s Время: %s%sс%s.\n' "$green" "$reset" "$bold" "$((SECONDS - start))" "$reset"
    fi
}

reset_board

if [ -t 0 ]; then
    stty -echo -icanon 2>/dev/null
    printf '%s[?25l' "$esc"
fi

while [ "$dead" -eq 0 ] && [ "$win" -eq 0 ]; do
    draw
    IFS= read -rsn1 key || break
    case "$key" in
        q|Q) break ;;
        r|R) reset_board; continue ;;
        ' ')
            idx=$((cy * N + cx))
            if [ "${open[idx]}" -eq 0 ] && [ "${flag[idx]}" -eq 0 ]; then
                if [ "$placed" -eq 0 ]; then place_mines "$cx" "$cy"; fi
                reveal "$cx" "$cy"
                if [ "$dead" -eq 0 ] && [ "$opened" -eq $((TOTAL - MINES)) ]; then
                    win=1
                fi
            fi
            ;;
        f|F)
            idx=$((cy * N + cx))
            if [ "${open[idx]}" -eq 0 ]; then
                if [ "${flag[idx]}" -eq 1 ]; then
                    flag[idx]=0; flags=$((flags - 1))
                else
                    flag[idx]=1; flags=$((flags + 1))
                fi
            fi
            ;;
        h|H|a|A) [ "$cx" -gt 0 ] && cx=$((cx - 1)) ;;
        l|L|d|D) [ "$cx" -lt $((N - 1)) ] && cx=$((cx + 1)) ;;
        k|K|w|W) [ "$cy" -gt 0 ] && cy=$((cy - 1)) ;;
        j|J|s|S) [ "$cy" -lt $((N - 1)) ] && cy=$((cy + 1)) ;;
        "$esc")
            IFS= read -rsn1 -t 0.02 k2 || continue
            [ "$k2" = '[' ] || continue
            IFS= read -rsn1 -t 0.02 k3 || continue
            case "$k3" in
                A) [ "$cy" -gt 0 ] && cy=$((cy - 1)) ;;
                B) [ "$cy" -lt $((N - 1)) ] && cy=$((cy + 1)) ;;
                C) [ "$cx" -lt $((N - 1)) ] && cx=$((cx + 1)) ;;
                D) [ "$cx" -gt 0 ] && cx=$((cx - 1)) ;;
            esac
            ;;
    esac
done

draw
if [ "$dead" -eq 1 ] || [ "$win" -eq 1 ]; then
    IFS= read -rsn1 _ || true
fi
