#!/bin/sh
# MVS OS 1.0 — статические проверки проекта без сборки ISO.
#
# Запуск:  sh check.sh
#
# Что проверяется:
#   * синтаксис sh/bash-скриптов и хуков;
#   * парность тегов XML/SVG;
#   * .desktop: обязательные поля, существование Exec и иконки;
#   * списки пакетов: формат, пустые файлы, дубликаты;
#   * MVS Store: наборы и списки пакетов в presets.json;
#   * Python: синтаксис (если python3 есть в системе);
#   * JSON и YAML: структура (если есть python3 и PyYAML);
#   * Calamares: у каждого модуля из settings.conf есть конфиг;
#   * версия: единственный источник — VERSION; код читает /etc/mvs-version.
#
# Чего проверка не делает: не собирает ISO и не запускает систему.
# Это делает GitHub Actions (сборка + QEMU smoke) и ручная проверка.

set -u
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$ROOT" || exit 1

TMP=$(mktemp -d 2>/dev/null) || TMP="${TMPDIR:-.}/mvs-check.$$"
mkdir -p "$TMP"
trap 'rm -rf "$TMP"' EXIT INT TERM

fails=0
warns=0
ok()   { printf '  ok   %s\n' "$*"; }
warn() { printf '  warn %s\n' "$*"; warns=$((warns + 1)); }
bad()  { printf '  FAIL %s\n' "$*"; fails=$((fails + 1)); }
skip() { printf '  skip %s\n' "$*"; }

printf '\n▸ Синтаксис sh\n'
for f in build.sh check.sh \
         config/hooks/live/*.hook.chroot \
         config/includes.chroot/usr/local/bin/* \
         config/includes.chroot/usr/local/sbin/* \
         config/includes.chroot/etc/grub.d/40_mvs_snapshots \
         config/includes.chroot/usr/local/share/mvs-os/games/*.sh \
         tools/*.sh; do
    [ -f "$f" ] || continue
    case "$f" in
        *.py) continue ;;
    esac
    # Игры используют массивы bash. На Debian проверять их через dash
    # нельзя: sh -n падает на «Syntax error: "(" unexpected». Берём
    # интерпретатор из shebang, а на Android (bash нет) остаётся mksh.
    if head -n 1 "$f" 2>/dev/null | grep -q 'bash' && command -v bash >/dev/null 2>&1; then
        bash -n "$f" 2>"$TMP/err"
    else
        sh -n "$f" 2>"$TMP/err"
    fi
    if [ $? -eq 0 ]; then ok "$f"; else bad "$f"; sed 's/^/         /' "$TMP/err"; fi
done

printf '\n▸ XML и SVG\n'
cat > "$TMP/xml.awk" <<'AWK'
{
  line = $0
  while (match(line, /<[^>]*>/)) {
    tag = substr(line, RSTART, RLENGTH)
    line = substr(line, RSTART + RLENGTH)
    if (tag ~ /^<\?/ || tag ~ /^<!/) continue
    if (tag ~ /\/>$/) continue
    if (tag ~ /^<\//) {
      name = tag
      sub(/^<\//, "", name)
      sub(/>$/, "", name)
      if (top == 0 || stack[top] != name) bad = 1
      else top--
    } else {
      name = tag
      sub(/^</, "", name)
      sub(/[ \t>].*$/, "", name)
      top++
      stack[top] = name
    }
  }
}
END { if (top != 0) bad = 1; exit bad }
AWK

for f in $(find config/includes.chroot -name '*.xml' -o -name '*.svg' | sort); do
    tr '\n' ' ' < "$f" > "$TMP/one.xml"
    if awk -f "$TMP/xml.awk" "$TMP/one.xml"; then ok "$f"; else bad "$f"; fi
done

printf '\n▸ Ярлыки .desktop\n'
for f in $(find config/includes.chroot -name '*.desktop' | sort); do
    if ! awk -F= '
        /^\[Desktop Entry\]/ { entry = 1 }
        /^Type=/            { type = $2 }
        /^Name=/            { name = $2 }
        /^Exec=/            { exec = $2 }
        END { exit !(entry && type == "Application" && name != "" && exec != "") }
    ' "$f"; then
        bad "$f: нет Type/Name/Exec"
        continue
    fi

    exec_line=$(awk -F= '/^Exec=/{print $2; exit}' "$f")
    cmd=${exec_line%% *}
    case "$cmd" in
        /*)
            if [ -x "config/includes.chroot$cmd" ] || [ -f "config/includes.chroot$cmd" ]; then
                ok "$f"
            else
                bad "$f: Exec указывает на несуществующий $cmd"
            fi
            ;;
        mvs-*)
            if [ -f "config/includes.chroot/usr/local/bin/$cmd" ]; then
                ok "$f"
            else
                bad "$f: нет обёртки usr/local/bin/$cmd"
            fi
            ;;
        *)
            # Системная команда (thunar, firefox-esr, xfce4-*): наличие
            # проверяется в собранной системе, здесь только формат.
            ok "$f"
            ;;
    esac
done

printf '\n▸ Иконки приложений MVS\n'
for f in $(find config/includes.chroot -name '*.desktop' | sort); do
    icon=$(awk -F= '/^Icon=/{print $2; exit}' "$f")
    case "$icon" in
        mvs-*)
            if [ -f "config/includes.chroot/usr/share/icons/MVS/apps/scalable/$icon.svg" ]; then
                ok "$f → $icon"
            else
                bad "$f: нет иконки $icon.svg"
            fi
            ;;
        /*)
            if [ -f "config/includes.chroot$icon" ]; then
                ok "$f → $icon"
            else
                bad "$f: нет файла иконки $icon"
            fi
            ;;
        *)
            ok "$f → $icon (системная)"
            ;;
    esac
done

printf '\n▸ Обёртки приложений MVS\n'
for f in config/includes.chroot/usr/local/bin/mvs-*; do
    [ -f "$f" ] || continue
    target=$(sed -n 's|.*/usr/lib/mvs/apps/\(mvs_[a-z_]*\.py\).*|\1|p' "$f" | head -n 1)
    if [ -n "$target" ]; then
        if [ -f "config/includes.chroot/usr/lib/mvs/apps/$target" ]; then
            ok "$(basename "$f") → $target"
        else
            bad "$(basename "$f"): нет config/includes.chroot/usr/lib/mvs/apps/$target"
        fi
    else
        ok "$(basename "$f")"
    fi
done

printf '\n▸ Списки пакетов\n'
seen="$TMP/packages.seen"
: > "$seen"
for f in config/package-lists/*.list.chroot; do
    [ -f "$f" ] || { bad "нет списков пакетов"; continue; }
    if ! grep -qE '^[a-z0-9]' "$f"; then
        bad "$f: пустой список"
        continue
    fi
    ok "$f ($(grep -cE '^[a-z0-9]' "$f") пакетов)"

    # Читаем файл через перенаправление, а не через конвейер: иначе while
    # выполняется в подоболочке и bad() не увеличит общий счётчик ошибок.
    while IFS= read -r pkg; do
        # CR мог остаться от редактирования в Windows, пробелы по краям
        # live-build игнорирует — убираем и их, чтобы не ругаться зря.
        pkg=$(printf '%s' "$pkg" | tr -d '\r' | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')
        [ -n "$pkg" ] || continue
        case "$pkg" in
            '#'*) continue ;;
        esac
        case "$pkg" in
            *[!a-z0-9+.:-]*)
                bad "$f: странное имя пакета «$pkg»"
                ;;
        esac
    done < "$f"

    grep -E '^[a-z0-9]' "$f" | sort >> "$seen"
done

dups=$(sort "$seen" | uniq -d)
if [ -n "$dups" ]; then
    bad "пакеты перечислены дважды: $(printf '%s' "$dups" | tr '\n' ' ')"
else
    ok "дубликатов пакетов нет"
fi

printf '\n▸ Вход в Live\n'
if grep -qx 'user-setup' config/package-lists/01-live.list.chroot; then
    ok "user-setup в списке Live (live-config создаст пользователя mvs)"
else
    bad "в 01-live.list.chroot нет user-setup: live-config не создаст mvs, вход невозможен"
fi
if grep -q '^autologin-user=mvs$' \
        config/includes.chroot/etc/lightdm/lightdm.conf.d/50-mvs-autologin.conf 2>/dev/null; then
    ok "автовход Live настроен на mvs"
else
    bad "нет автовхода mvs в lightdm.conf.d/50-mvs-autologin.conf"
fi
if grep -q 'keyboard-layouts=us,ru' build.sh; then
    ok "раскладка Live: английская первой"
else
    warn "в build.sh раскладка не us,ru: пароль live на экране входа может не набраться"
fi
if grep -q '^XKBLAYOUT="us,ru"' config/includes.chroot/etc/default/keyboard 2>/dev/null; then
    ok "раскладка установленной системы: английская первой"
else
    warn "XKBLAYOUT не us,ru: на экране входа можно случайно набрать пароль по-русски"
fi

printf '\n▸ MVS Store\n'
presets=config/includes.chroot/usr/share/mvs/store/presets.json
if [ -f "$presets" ]; then
    sets=$(grep -c '"id":' "$presets" 2>/dev/null || true)
    if [ "${sets:-0}" -ge 1 ]; then
        ok "presets.json: $sets наборов"
    else
        bad "presets.json: нет наборов"
    fi
    if grep -q '"packages"[[:space:]]*:' "$presets"; then
        ok "presets.json: списки пакетов на месте"
    else
        bad "presets.json: нет списков пакетов"
    fi
else
    bad "нет $presets"
fi

printf '\n▸ Версия\n'
file_version=$(tr -d ' \n' < VERSION 2>/dev/null || echo "")
if [ -n "$file_version" ]; then
    ok "VERSION=$file_version"
else
    bad "пустой или отсутствует VERSION"
fi

# Версия должна читаться из одного файла, а не быть вписанной в код.
if grep -q 'VERSION=$(tr' build.sh 2>/dev/null; then
    ok "build.sh берёт версию из VERSION"
else
    bad "build.sh не читает файл VERSION"
fi

for reader in \
    config/includes.chroot/usr/lib/mvs/mvsui.py \
    config/includes.chroot/usr/local/sbin/mvs-identity; do
    if grep -q '/etc/mvs-version' "$reader" 2>/dev/null; then
        ok "$(basename "$reader"): версия из /etc/mvs-version"
    else
        bad "$(basename "$reader"): не читает /etc/mvs-version"
    fi
done

# Статический os-release — это была бы вторая версия в исходниках.
if [ -e config/includes.chroot/etc/os-release ]; then
    bad "config/includes.chroot/etc/os-release дублирует версию (его генерирует сборка)"
else
    ok "статического os-release нет"
fi

printf '\n▸ Calamares\n'
settings=config/includes.chroot/etc/calamares/settings.conf
modules=config/includes.chroot/etc/calamares/modules
if [ -f "$settings" ]; then
    ok "settings.conf на месте"
    for module in welcome locale keyboard partition mount unpackfs machineid fstab users networkcfg hwclock localecfg bootloader umount finished summary; do
        if [ -f "$modules/$module.conf" ]; then
            ok "конфиг модуля $module"
        else
            bad "нет modules/$module.conf"
        fi
    done
    if [ -f "$modules/live-admin.conf" ]; then
        ok "конфиг экземпляра live-admin"
    else
        bad "нет modules/live-admin.conf"
    fi

    # Calamares ищет конфиги только в /etc/calamares/modules. Файл рядом
    # с settings.conf был бы молча проигнорирован — это уже случалось.
    stray=$(find config/includes.chroot/etc/calamares -maxdepth 1 -name '*.conf' ! -name settings.conf)
    if [ -n "$stray" ]; then
        bad "конфиги модулей вне modules/: $(printf '%s' "$stray" | tr '\n' ' ')"
    else
        ok "конфиги модулей только в modules/"
    fi

    # Экземпляр должен вызываться по полному ключу module@id и указывать
    # свой конфиг, иначе Calamares возьмёт shellprocess.conf.
    if grep -q 'config: live-admin.conf' "$settings" && grep -q 'shellprocess@live-admin' "$settings"; then
        ok "экземпляр shellprocess@live-admin настроен"
    else
        bad "в settings.conf нет config: live-admin.conf или shellprocess@live-admin"
    fi
    if [ -f config/includes.chroot/usr/local/bin/mvs-install ]; then
        ok "запускалка установщика mvs-install"
    else
        bad "нет mvs-install"
    fi
else
    bad "нет etc/calamares/settings.conf"
fi

printf '\n▸ Python, JSON, YAML\n'
if command -v python3 >/dev/null 2>&1; then
    if python3 - "$TMP" <<'PY'
import pathlib
import sys

bad = 0
for path in sorted(pathlib.Path(".").rglob("*.py")):
    if "build/" in str(path):
        continue
    try:
        compile(path.read_text(encoding="utf-8"), str(path), "exec")
    except SyntaxError as exc:
        print("         %s:%s: %s" % (path, exc.lineno, exc.msg))
        bad += 1
sys.exit(1 if bad else 0)
PY
    then ok "Python: синтаксис"; else bad "Python: синтаксис"; fi

    if python3 - <<'PY'
import json
import pathlib
import sys

bad = 0
for path in sorted(pathlib.Path("config").rglob("*.json")):
    try:
        json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        print("         %s: %s" % (path, exc))
        bad += 1
sys.exit(1 if bad else 0)
PY
    then ok "JSON: структура"; else bad "JSON: структура"; fi

    if python3 -c 'import yaml' 2>/dev/null; then
        if python3 - <<'PY'
import pathlib
import sys
import yaml

bad = 0
roots = [
    pathlib.Path("config/includes.chroot/etc/calamares"),
    pathlib.Path("config/includes.chroot/usr/share/calamares/branding"),
]
for root in roots:
    for path in sorted(root.rglob("*")):
        if path.suffix not in (".conf", ".desc"):
            continue
        try:
            yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            print("         %s: %s" % (path, exc))
            bad += 1
sys.exit(1 if bad else 0)
PY
        then ok "YAML: структура"; else bad "YAML: структура"; fi
    else
        skip "YAML: нет PyYAML (проверяется в CI)"
    fi
else
    skip "Python: нет python3 (синтаксис проверяется в CI)"
    skip "JSON: нет python3"
    skip "YAML: нет PyYAML"
fi

printf '\n▸ Ключевые файлы\n'
for f in \
    config/includes.chroot/usr/lib/mvs/mvsui.py \
    config/includes.chroot/usr/lib/mvs/apps/mvs_control.py \
    config/includes.chroot/usr/lib/mvs/apps/mvs_store.py \
    config/includes.chroot/usr/lib/mvs/apps/mvs_doctor.py \
    config/includes.chroot/usr/lib/mvs/apps/mvs_welcome.py \
    config/includes.chroot/usr/share/mvs/store/presets.json \
    config/includes.chroot/usr/share/applications/mvs-doctor.desktop \
    config/includes.chroot/usr/local/bin/mvs-doctor \
    config/includes.chroot/usr/share/themes/MVS-Dark/gtk-3.0/gtk.css \
    config/includes.chroot/usr/share/themes/MVS-Light/gtk-3.0/gtk.css \
    config/includes.chroot/usr/share/plymouth/themes/mvs/mvs.plymouth \
    config/includes.chroot/etc/xdg/autostart/mvs-welcome.desktop \
    config/package-lists/05-extra.list.chroot \
    tools/build-local.sh \
    tools/check-packages.sh \
    tools/make-vm.sh \
    tools/write-usb.sh \
    tests/qemu_smoke.py \
    .github/workflows/build.yml \
    docs/building.md \
    docs/vm.md; do
    if [ -f "$f" ]; then ok "$f"; else bad "нет $f"; fi
done

printf '\n'
if [ "$fails" -eq 0 ]; then
    printf 'Всё чисто: %d предупреждений.\n' "$warns"
    printf 'Сборка: sudo sh ./build.sh   (в CI — Actions → Run workflow)\n\n'
    exit 0
fi
printf 'Ошибок: %s, предупреждений: %s\n\n' "$fails" "$warns"
exit 1
