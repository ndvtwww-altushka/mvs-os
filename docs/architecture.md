# Архитектура проекта

## Идея

MVS OS — это Debian 12 + XFCE, поверх которого лежит собственная оболочка:
тема, набор приложений, установщик и правила Live-режима. Ядро, драйверы
и репозитории остаются Debian: это осознанный выбор в пользу стабильности
и совместимости.

## Дерево

```
mvs-os/
├── build.sh                    сборка ISO (live-build)
├── check.sh                    статические проверки
├── VERSION                     версия 1.0
├── config/
│   ├── package-lists/          пакеты по слоям
│   │   ├── 01-live.list.chroot         ядро, live, прошивки, защита
│   │   ├── 02-desktop.list.chroot      XFCE, сеть, звук, печать
│   │   ├── 03-apps.list.chroot         Python/GTK, Firefox, игры
│   │   ├── 04-installer.list.chroot    Calamares, grub, shim
│   │   └── 05-extra.list.chroot        офис, почта, мультимедиа, утилиты
│   ├── hooks/live/
│   │   ├── 0100-mvs-branding.hook.chroot     права, темы, службы
│   │   ├── 0200-mvs-live-policy.hook.chroot  sudo/polkit Live
│   │   └── 0900-mvs-cleanup.hook.chroot      чистка перед squashfs
│   └── includes.chroot/        файлы будущей системы (1:1)
│       ├── etc/                брендинг, Calamares, sysctl, apt, sudoers
│       ├── usr/lib/mvs/        mvsui.py + apps/*.py
│       ├── usr/local/bin/      обёртки mvs-*
│       ├── usr/share/mvs/      CSS темы приложений, наборы Store
│       ├── usr/share/icons/MVS/ фирменные иконки
│       ├── usr/share/themes/   MVS-Dark, MVS-Light
│       ├── usr/share/backgrounds/ обои
│       └── usr/share/plymouth/ экран загрузки
├── .github/workflows/build.yml CI: проверки → ISO → QEMU → релиз
├── docs/                       эта документация
├── tests/qemu_smoke.py         дымовой тест загрузки
├── tools/
│   ├── build-local.sh          зависимости + сборка
│   ├── check-packages.sh       сверка имён пакетов с архивом Debian
│   ├── make-vm.sh              VM без перезагрузки
│   ├── write-usb.sh            запись ISO с проверками
│   └── gen-icons.sh            генератор иконок
```

## Слои системы

1. **Debian** — ядро, systemd, apt, драйверы, Xorg.
2. **XFCE** — сессия, панель, Thunar, настройки.
3. **Оболочка MVS** — темы, иконки, обои, Plymouth, приветствие.
4. **Приложения MVS** — Python 3 + GTK 3, общий модуль `mvsui.py`.
5. **Прикладной слой** — LibreOffice, Thunderbird, VLC, диски, диагностика.
6. **Установщик** — Calamares с собственной последовательностью.
7. **Сборка** — live-build + GitHub Actions.

## Приложения MVS

Все приложения используют `/usr/lib/mvs/mvsui.py`:

- единая палитра и размеры (CSS `/usr/share/mvs/theme/`);
- `ui.run()` / `ui.out()` — запуск команд без исключений;
- `ui.priv_prefix()` — `sudo -n` в Live, `pkexec` в установленной системе;
- `MvsWindow` — окно с боковым меню и страницами;
- `LogView` + `stream()` — честный журнал вывода apt и системных команд.

Обёртки `/usr/local/bin/mvs-*` — тонкие: они только запускают нужный
Python-файл. Это позволяет вызывать приложения из меню, панели и скриптов
одинаково.

### Почему Python + GTK

- GTK 3 уже есть в XFCE — не тянем второй тулкит.
- Python 3 входит в Debian, код читается и правится без сборки.
- Нет своих демонов: приложение запускается по требованию и завершается.

## Темы

- `MVS-Dark` / `MVS-Light` — GTK-темы: `@import` Arc/Arc-Dark + палитра MVS.
  Импорт, а не форк: обновление Arc не ломает MVS.
- Оконные рамки — Arc-Dark/Arc (проверенная основа), цвета заголовков
  заданы в `xfwm4.xml`.
- Иконки — `MVS`, наследует Papirus-Dark; содержит только иконки
  приложений MVS.
- Приложения MVS дополнительно подключают свой CSS, поэтому выглядят
  одинаково даже при смене системной темы.

## Поток загрузки

```
UEFI/BIOS → GRUB (syslinux на BIOS ISO) → ядро + initramfs
        → Plymouth (градиент MVS) → live-boot
        → systemd → LightDM (автологин mvs) → XFCE
```

После установки: GRUB → Plymouth → LightDM (пароль) → XFCE.

## Почему не «с нуля»

Свой kernel/драйверы/репозиторий — годы работы и отсутствие совместимости.
Задача MVS OS — узнаваемая и цельная система на проверенной базе, а не
ещё один Debian-ремикс с обоями. Поэтому собственное — это оболочка,
приложения, установщик, политика безопасности и сборка.
