#!/usr/bin/env bash
# Terminal // Night — тетрис
# ← → ↓, ↑ — поворот, пробел — сброс, p — пауза, q — выход.

[ -n "${BASH_VERSION:-}" ] || { printf 'Нужен bash.\n' >&2; exit 1; }

esc=$'\033'
reset="${esc}[0m"
bold="${esc}[1m"
dim="${esc}[38;5;60m"
accent="${esc}[38;5;111m"
green="${esc}[38;5;114m"

cleanup() {
    printf '%s[?25h%s\n' "$esc" "$reset"
    if [ -t 0 ]; then stty echo icanon 2>/dev/null; fi
}
trap cleanup EXIT INT TERM

W=10
H=20
TOTAL=$((W * H))

board=()
i=0
while [ "$i" -lt "$TOTAL" ]; do
    board[i]=0
    i=$((i + 1))
done

piece=()
px=3
py=0
ptype=1
score=0
lines=0
level=1
delay=0.45
game_over=0

set_piece() {
    local t=$1 k
    piece=()
    k=0
    while [ "$k" -lt 16 ]; do piece[k]=0; k=$((k + 1)); done
    case "$t" in
        1) # I
            piece[4]=1; piece[5]=1; piece[6]=1; piece[7]=1 ;;
        2) # O
            piece[0]=1; piece[1]=1; piece[4]=1; piece[5]=1 ;;
        3) # T
            piece[1]=1; piece[4]=1; piece[5]=1; piece[6]=1 ;;
        4) # S
            piece[1]=1; piece[2]=1; piece[4]=1; piece[5]=1 ;;
        5) # Z
            piece[0]=1; piece[1]=1; piece[5]=1; piece[6]=1 ;;
        6) # J
            piece[0]=1; piece[4]=1; piece[5]=1; piece[6]=1 ;;
        7) # L
            piece[2]=1; piece[4]=1; piece[5]=1; piece[6]=1 ;;
    esac
    ptype=$t
    px=3
    py=0
}

collides() {
    local r c x y idx
    for r in 0 1 2 3; do
        for c in 0 1 2 3; do
            [ "${piece[r * 4 + c]}" -eq 0 ] && continue
            x=$((px + c))
            y=$((py + r))
            [ "$x" -lt 0 ] || [ "$x" -ge "$W" ] && return 0
            [ "$y" -ge "$H" ] && return 0
            [ "$y" -ge 0 ] || continue
            idx=$((y * W + x))
            [ "${board[idx]}" -ne 0 ] && return 0
        done
    done
    return 1
}

spawn() {
    set_piece $((RANDOM % 7 + 1))
    if collides; then
        game_over=1
        return 1
    fi
    return 0
}

lock_piece() {
    local r c x y idx top=0
    for r in 0 1 2 3; do
        for c in 0 1 2 3; do
            [ "${piece[r * 4 + c]}" -eq 0 ] && continue
            x=$((px + c))
            y=$((py + r))
            [ "$y" -lt 0 ] && { top=1; continue; }
            idx=$((y * W + x))
            board[idx]=$ptype
        done
    done
    [ "$top" -eq 1 ] && game_over=1
}

clear_lines() {
    local y x idx full removed=0
    y=$((H - 1))
    while [ "$y" -ge 0 ]; do
        full=1
        for x in 0 1 2 3 4 5 6 7 8 9; do
            idx=$((y * W + x))
            [ "${board[idx]}" -eq 0 ] && { full=0; break; }
        done
        if [ "$full" -eq 1 ]; then
            local yy=$y
            while [ "$yy" -gt 0 ]; do
                for x in 0 1 2 3 4 5 6 7 8 9; do
                    board[$((yy * W + x))]=${board[$(((yy - 1) * W + x))]}
                done
                yy=$((yy - 1))
            done
            for x in 0 1 2 3 4 5 6 7 8 9; do board[x]=0; done
            removed=$((removed + 1))
            continue
        fi
        y=$((y - 1))
    done
    if [ "$removed" -gt 0 ]; then
        lines=$((lines + removed))
        case "$removed" in
            1) score=$((score + 100)) ;;
            2) score=$((score + 300)) ;;
            3) score=$((score + 500)) ;;
            *) score=$((score + 800)) ;;
        esac
        level=$((lines / 5 + 1))
        delay=$(awk -v l="$level" 'BEGIN{d=0.45-(l-1)*0.035; if(d<0.09)d=0.09; printf "%.3f", d}')
    fi
}

draw() {
    local view x y r c idx gx gy line v
    view=()
    y=0
    while [ "$y" -lt "$H" ]; do
        x=0
        while [ "$x" -lt "$W" ]; do
            idx=$((y * W + x))
            view[idx]=${board[idx]}
            x=$((x + 1))
        done
        y=$((y + 1))
    done
    for r in 0 1 2 3; do
        for c in 0 1 2 3; do
            [ "${piece[r * 4 + c]}" -eq 0 ] && continue
            gx=$((px + c))
            gy=$((py + r))
            [ "$gy" -lt 0 ] || [ "$gy" -ge "$H" ] && continue
            [ "$gx" -lt 0 ] || [ "$gx" -ge "$W" ] && continue
            view[$((gy * W + gx))]=$ptype
        done
    done

    printf '%s[H%s[2J' "$esc" "$esc"
    printf '\n  %s%sТЕТРИС%s  %s·%s  счёт %s%s%s  %s·%s  линий %s%s%s  %s·%s  уровень %s%s%s\n' \
        "$bold" "$accent" "$reset" "$dim" "$reset" "$bold" "$score" "$reset" \
        "$dim" "$reset" "$bold" "$lines" "$reset" "$dim" "$reset" "$bold" "$level" "$reset"
    y=0
    while [ "$y" -lt "$H" ]; do
        line="  ${dim}│${reset}"
        x=0
        while [ "$x" -lt "$W" ]; do
            idx=$((y * W + x))
            case "${view[idx]}" in
                1) line="${line}${esc}[48;5;117m  ${reset}" ;;
                2) line="${line}${esc}[48;5;179m  ${reset}" ;;
                3) line="${line}${esc}[48;5;176m  ${reset}" ;;
                4) line="${line}${esc}[48;5;114m  ${reset}" ;;
                5) line="${line}${esc}[48;5;203m  ${reset}" ;;
                6) line="${line}${esc}[48;5;111m  ${reset}" ;;
                7) line="${line}${esc}[48;5;215m  ${reset}" ;;
                *) line="${line}  " ;;
            esac
            x=$((x + 1))
        done
        line="${line}${dim}│${reset}"
        printf '%s\n' "$line"
        y=$((y + 1))
    done
    printf '  %s← → ↓  ↑ поворот  пробел сброс  p пауза  q выход%s\n' "$dim" "$reset"
    if [ "$game_over" -eq 1 ]; then
        printf '\n  %sИгра окончена.%s Счёт: %s%s%s\n' "$dim" "$reset" "$bold" "$score" "$reset"
        IFS= read -rsn1 _ || true
    fi
}

if [ -t 0 ]; then
    stty -echo -icanon 2>/dev/null
    printf '%s[?25l' "$esc"
fi

spawn

while [ "$game_over" -eq 0 ]; do
    draw
    key=''
    IFS= read -rsn1 -t "$delay" key
    if [ -n "$key" ]; then
        case "$key" in
            q|Q) break ;;
            p|P)
                printf '\n  %sПауза.%s Нажми любую клавишу.\n' "$dim" "$reset"
                IFS= read -rsn1 _ || true
                continue
                ;;
            h|H|a|A)
                px=$((px - 1))
                if collides; then px=$((px + 1)); fi
                continue
                ;;
            l|L|d|D)
                px=$((px + 1))
                if collides; then px=$((px - 1)); fi
                continue
                ;;
            j|J|s|S)
                py=$((py + 1))
                if collides; then py=$((py - 1)); else continue; fi
                ;;
            k|K|w|W) ;;
            ' ')
                while :; do
                    py=$((py + 1))
                    if collides; then
                        py=$((py - 1))
                        break
                    fi
                done
                ;;
            "$esc")
                IFS= read -rsn1 -t 0.02 k2 || { continue; }
                [ "$k2" = '[' ] || continue
                IFS= read -rsn1 -t 0.02 k3 || continue
                case "$k3" in
                    A)
                        old=()
                        rr=0
                        while [ "$rr" -lt 16 ]; do old[rr]=${piece[rr]}; rr=$((rr + 1)); done
                        rr=0
                        while [ "$rr" -lt 4 ]; do
                            cc=0
                            while [ "$cc" -lt 4 ]; do
                                piece[$((rr * 4 + cc))]=${old[$(((3 - cc) * 4 + rr))]}
                                cc=$((cc + 1))
                            done
                            rr=$((rr + 1))
                        done
                        if [ "$ptype" -eq 2 ] || collides; then
                            rr=0
                            while [ "$rr" -lt 16 ]; do piece[rr]=${old[rr]}; rr=$((rr + 1)); done
                        fi
                        continue
                        ;;
                    B)
                        py=$((py + 1))
                        if collides; then py=$((py - 1)); else continue; fi
                        ;;
                    C)
                        px=$((px + 1))
                        if collides; then px=$((px - 1)); fi
                        continue
                        ;;
                    D)
                        px=$((px - 1))
                        if collides; then px=$((px + 1)); fi
                        continue
                        ;;
                    *) continue ;;
                esac
                ;;
            *) continue ;;
        esac
    fi

    py=$((py + 1))
    if collides; then
        py=$((py - 1))
        lock_piece
        clear_lines
        [ "$game_over" -eq 0 ] && spawn
    fi
done

draw
