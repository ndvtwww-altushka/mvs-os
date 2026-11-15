#!/usr/bin/env bash
# Terminal // Night — змейка
# Стрелки или WASD, p — пауза, q — выход.

[ -n "${BASH_VERSION:-}" ] || { printf 'Нужен bash.\n' >&2; exit 1; }

esc=$'\033'
reset="${esc}[0m"
bold="${esc}[1m"
dim="${esc}[38;5;60m"
accent="${esc}[38;5;111m"
red="${esc}[38;5;203m"
green="${esc}[38;5;114m"
body="${esc}[38;5;68m"

cleanup() {
    printf '%s[?25h%s\n' "$esc" "$reset"
    if [ -t 0 ]; then stty echo icanon 2>/dev/null; fi
}
trap cleanup EXIT INT TERM

if [ -t 0 ]; then
    stty -echo -icanon 2>/dev/null
    printf '%s[?25l' "$esc"
    sz=$(stty size 2>/dev/null)
    rows=${sz% *}
    cols=${sz#* }
else
    rows=24
    cols=80
fi
case "$rows" in ''|*[!0-9]*) rows=24 ;; esac
case "$cols" in ''|*[!0-9]*) cols=80 ;; esac

W=$((cols - 6))
[ "$W" -gt 52 ] && W=52
[ "$W" -lt 20 ] && W=20
H=$((rows - 8))
[ "$H" -gt 20 ] && H=20
[ "$H" -lt 10 ] && H=10

bestfile="${XDG_CACHE_HOME:-$HOME/.cache}/terminal-visual/snake.best"
best=0
[ -r "$bestfile" ] && best=$(cat "$bestfile" 2>/dev/null)
case "$best" in ''|*[!0-9]*) best=0 ;; esac

grid=()
i=0
while [ "$i" -lt $((W * H)) ]; do
    grid[i]=0
    i=$((i + 1))
done

cx=$((W / 2))
cy=$((H / 2))
sx=("$cx" "$((cx - 1))" "$((cx - 2))")
sy=("$cy" "$cy" "$cy")
len=3
for i in 0 1 2; do
    grid[$((sy[i] * W + sx[i]))]=1
done

dir=right
next=right
score=0
delay=0.14
food_x=0
food_y=0
food_ok=0

spawn_food() {
    local tries=0 fx fy idx
    while [ "$tries" -lt 300 ]; do
        fx=$((RANDOM % W))
        fy=$((RANDOM % H))
        idx=$((fy * W + fx))
        if [ "${grid[idx]}" -eq 0 ]; then
            food_x=$fx
            food_y=$fy
            grid[idx]=2
            food_ok=1
            return 0
        fi
        tries=$((tries + 1))
    done
    food_ok=0
    return 1
}

draw() {
    local y x idx v line
    printf '%s[H' "$esc"
    printf '\n  %s%sЗМЕЙКА%s  %s·%s  счёт %s%s%s  %s·%s  рекорд %s%s%s\n' \
        "$bold" "$green" "$reset" "$dim" "$reset" "$bold" "$score" "$reset" \
        "$dim" "$reset" "$bold" "$best" "$reset"
    printf '  %s┌' "$dim"
    x=0
    while [ "$x" -lt "$W" ]; do printf '─'; x=$((x + 1)); done
    printf '┐%s\n' "$reset"
    y=0
    while [ "$y" -lt "$H" ]; do
        line="  ${dim}│${reset}"
        x=0
        while [ "$x" -lt "$W" ]; do
            idx=$((y * W + x))
            v=${grid[idx]}
            case "$v" in
                2) line="${line}${red}*${reset}" ;;
                1)
                    if [ "$x" -eq "${sx[0]}" ] && [ "$y" -eq "${sy[0]}" ]; then
                        line="${line}${accent}@${reset}"
                    else
                        line="${line}${body}o${reset}"
                    fi
                    ;;
                *) line="${line} " ;;
            esac
            x=$((x + 1))
        done
        line="${line}${dim}│${reset}"
        printf '%s\n' "$line"
        y=$((y + 1))
    done
    printf '  %s└' "$dim"
    x=0
    while [ "$x" -lt "$W" ]; do printf '─'; x=$((x + 1)); done
    printf '┘%s\n\n' "$reset"
    printf '  %sстрелки / WASD%s  %sp%s пауза  %sq%s выход\n' \
        "$dim" "$reset" "$dim" "$reset" "$dim" "$reset"
}

set_dir() {
    case "$1" in
        up)    [ "$next" = down ]  && return ;;
        down)  [ "$next" = up ]    && return ;;
        left)  [ "$next" = right ] && return ;;
        right) [ "$next" = left ]  && return ;;
    esac
    next=$1
}

pause_game() {
    printf '\n  %sПауза.%s Нажми любую клавишу.\n' "$dim" "$reset"
    IFS= read -rsn1 _ || true
}

spawn_food

while :; do
    draw
    key=''
    IFS= read -rsn1 -t "$delay" key
    if [ -n "$key" ]; then
        case "$key" in
            q|Q) break ;;
            p|P) pause_game ;;
            w|W|k|K) set_dir up ;;
            s|S|j|J) set_dir down ;;
            a|A|h|H) set_dir left ;;
            d|D|l|L) set_dir right ;;
            "$esc")
                IFS= read -rsn1 -t 0.02 k2 || true
                if [ "$k2" = '[' ]; then
                    IFS= read -rsn1 -t 0.02 k3 || true
                    case "$k3" in
                        A) set_dir up ;;
                        B) set_dir down ;;
                        C) set_dir right ;;
                        D) set_dir left ;;
                    esac
                fi
                ;;
        esac
    fi

    dir=$next
    hx=${sx[0]}
    hy=${sy[0]}
    case "$dir" in
        up)    hy=$((hy - 1)) ;;
        down)  hy=$((hy + 1)) ;;
        left)  hx=$((hx - 1)) ;;
        right) hx=$((hx + 1)) ;;
    esac

    if [ "$hx" -lt 0 ] || [ "$hx" -ge "$W" ] || [ "$hy" -lt 0 ] || [ "$hy" -ge "$H" ]; then
        break
    fi
    hidx=$((hy * W + hx))
    if [ "${grid[hidx]}" -eq 1 ]; then
        break
    fi

    eat=0
    [ "${grid[hidx]}" -eq 2 ] && eat=1

    if [ "$eat" -eq 0 ]; then
        last=$((len - 1))
        tx=${sx[last]}
        ty=${sy[last]}
        grid[$((ty * W + tx))]=0
        unset "sx[$last]" "sy[$last]"
        len=$((len - 1))
    fi

    sx=("$hx" "${sx[@]}")
    sy=("$hy" "${sy[@]}")
    len=$((len + 1))
    grid[hidx]=1

    if [ "$eat" -eq 1 ]; then
        score=$((score + 1))
        if [ "$score" -gt "$best" ]; then
            best=$score
            mkdir -p "$(dirname "$bestfile")" 2>/dev/null
            printf '%s\n' "$best" > "$bestfile" 2>/dev/null
        fi
        if awk -v d="$delay" 'BEGIN{exit !(d > 0.06)}'; then
            delay=$(awk -v d="$delay" 'BEGIN{printf "%.3f", d-0.002}')
        fi
        if ! spawn_food; then
            draw
            printf '\n  %sПоле заполнено. Победа!%s Счёт: %s%s%s\n\n' \
                "$green" "$reset" "$bold" "$score" "$reset"
            IFS= read -rsn1 _ || true
            break
        fi
    fi
done

draw
printf '\n  %sИгра окончена.%s Счёт: %s%s%s  %s·%s  рекорд %s%s%s\n\n' \
    "$dim" "$reset" "$bold" "$score" "$reset" "$dim" "$reset" "$bold" "$best" "$reset"
IFS= read -rsn1 _ || true
