#!/bin/sh
# MVS OS — генератор фирменных иконок приложений MVS.
#
# Иконки — обычные SVG: один и тот же файл кладётся в apps/scalable и apps/64,
# чтобы GTK находил их независимо от того, как тема ищет размер.
#
# Запуск:  sh tools/gen-icons.sh
# Повторный запуск безопасен: файлы перезаписываются.
#
# Стиль: тёмная карточка MVS + голубой глиф. Это единственная «рамка»,
# которую рисует тема; содержимое задаёт сам глиф.

set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
OUT="$ROOT/config/includes.chroot/usr/share/icons/MVS"
mkdir -p "$OUT/apps/scalable" "$OUT/apps/64"

glyph() {
    case "$1" in
    hub)
        printf '%s' '<rect x="15" y="15" width="14" height="14" rx="4"/><rect x="35" y="15" width="14" height="14" rx="4"/><rect x="15" y="35" width="14" height="14" rx="4"/><rect x="35" y="35" width="14" height="14" rx="4"/>'
        ;;
    control)
        printf '%s' '<path d="M14 22h36M14 32h36M14 42h36"/><circle cx="24" cy="22" r="3.4" fill="#16161e"/><circle cx="40" cy="32" r="3.4" fill="#16161e"/><circle cx="28" cy="42" r="3.4" fill="#16161e"/>'
        ;;
    store)
        printf '%s' '<path d="M17 25h30l-3.2 23H20.2z"/><path d="M25 25v-3.5a7 7 0 0 1 14 0V25"/>'
        ;;
    update)
        printf '%s' '<path d="M46 32a14 14 0 1 1-4.4-10.1"/><path d="M46 16v8h-8"/>'
        ;;
    monitor)
        printf '%s' '<rect x="11" y="15" width="42" height="30" rx="4"/><path d="M16 39l8-10 6 6 8-12 10 8"/>'
        ;;
    doctor)
        printf '%s' '<path d="M32 13l17 6.5V30c0 10.5-7.5 17.5-17 21-9.5-3.5-17-10.5-17-21V19.5z"/><path d="M24 32l6 6 12-12"/>'
        ;;
    cleaner)
        printf '%s' '<path d="M30 14l4.4 8.8 8.6 4.4-8.6 4.4L30 40l-4.4-8.4-8.6-4.4 8.6-4.4z"/><path d="M43 36l2.4 4.6 4.6 2.4-4.6 2.4L43 50l-2.4-4.6L36 43l4.6-2.4z"/>'
        ;;
    backup)
        printf '%s' '<path d="M21 38a8 8 0 0 1 .8-15.9 10.5 10.5 0 0 1 20 3.4A7.2 7.2 0 0 1 45 38"/><path d="M32 32v14"/><path d="M26 40l6 6 6-6"/>'
        ;;
    games)
        printf '%s' '<rect x="12" y="24" width="40" height="21" rx="9"/><path d="M23 34h7M26.5 30.5v7"/><circle cx="39" cy="32" r="1.8" fill="#7aa2f7" stroke="none"/><circle cx="43" cy="36.5" r="1.8" fill="#7aa2f7" stroke="none"/>'
        ;;
    about)
        printf '%s' '<circle cx="32" cy="32" r="17"/><path d="M32 30v11"/><circle cx="32" cy="23" r="2" fill="#7aa2f7" stroke="none"/>'
        ;;
    welcome)
        printf '%s' '<path d="M32 47S17 38 17 28.5A8.5 8.5 0 0 1 32 23a8.5 8.5 0 0 1 15 5.5C47 38 32 47 32 47z"/>'
        ;;
    quick)
        printf '%s' '<circle cx="32" cy="32" r="14"/><path d="M32 18a14 14 0 0 1 0 28z" fill="#7aa2f7" stroke="none"/>'
        ;;
    theme)
        printf '%s' '<path d="M32 15c7.5 8.6 12 14 12 20.2A12 12 0 0 1 20 35.2C20 29 24.5 23.6 32 15z"/><path d="M25 38a7 7 0 0 0 7 6"/>'
        ;;
    files)
        printf '%s' '<path d="M13 24h12l4 4h22v22H13z"/><path d="M13 24v-4h11l4 4"/>'
        ;;
    terminal)
        printf '%s' '<rect x="12" y="15" width="40" height="34" rx="4"/><path d="M20 28l5 4-5 4"/><path d="M31 37h11"/>'
        ;;
    settings)
        printf '%s' '<circle cx="32" cy="32" r="8"/><path d="M32 14v6M32 44v6M14 32h6M44 32h6M19.3 19.3l4.2 4.2M40.5 40.5l4.2 4.2M44.7 19.3l-4.2 4.2M23.5 40.5l-4.2 4.2"/>'
        ;;
    install)
        printf '%s' '<rect x="14" y="14" width="36" height="36" rx="7"/><path d="M32 22v14"/><path d="M25 30l7 7 7-7"/>'
        ;;
    *)
        printf '%s' '<circle cx="32" cy="32" r="14"/>'
        ;;
    esac
}

for name in hub control store update monitor doctor cleaner backup games about welcome quick theme files terminal settings install; do
    body=$(glyph "$name")
    for size in scalable 64; do
        cat > "$OUT/apps/$size/mvs-$name.svg" <<SVG
<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64">
  <title>MVS $name</title>
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#242942"/>
      <stop offset="1" stop-color="#14151f"/>
    </linearGradient>
  </defs>
  <rect x="2" y="2" width="60" height="60" rx="15" fill="url(#bg)" stroke="#3b4261" stroke-width="1.5"/>
  <g fill="none" stroke="#7aa2f7" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
    $body
  </g>
</svg>
SVG
    done
done

count=$(find "$OUT/apps" -name 'mvs-*.svg' | wc -l | tr -d ' ')
printf 'MVS: иконок создано — %s (%s)\n' "$count" "$OUT"
