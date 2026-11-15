# MVS OS — сборка, запись на флешку и запуск

## Что нужно

- Компьютер с Linux (Debian 12 или контейнер Debian 12).
- 12 ГБ свободного места и интернет.
- `live-build`, `squashfs-tools`, `xorriso`.

```sh
sudo apt-get update
sudo apt-get install -y live-build debootstrap fakeroot \
    squashfs-tools xorriso \
    syslinux syslinux-common isolinux syslinux-efi \
    grub-efi-amd64-bin grub-pc-bin mtools dosfstools \
    file rsync wget xz-utils bzip2 cpio apt-utils
```

## Сборка локально

Всё одной командой (сама поставит зависимости и запустит сборку):

```sh
sudo sh tools/build-local.sh
```

Или вручную, если зависимости уже есть:

```sh
cd mvs-os
sh ./check.sh                  # статические проверки, без root
sh tools/check-packages.sh     # все имена пакетов есть в Debian bookworm
sudo sh ./build.sh             # сборка ISO, 20–60 минут
```

`check-packages.sh` скачивает списки `Packages` из архива Debian и сверяет
с ними каждый пакет из `config/package-lists` и наборы MVS Store (кроме
наборов из внешних репозиториев, например VS Code). Это ловит опечатки до
долгой сборки. Нужны `curl` или `wget` и `xz-utils`. `build.sh` запускает
эту проверку сам перед `lb build`.

Результат в корне проекта:

```
MVS-OS-1.0-amd64.iso
MVS-OS-1.0-amd64.iso.sha256
SHA256SUMS
BUILD-INFO-1.0.txt
PACKAGES-1.0.txt
```

`PACKAGES-1.0.txt` — полный список пакетов и версий, вошедших в ISO.

Проверка целостности:

```sh
sha256sum -c SHA256SUMS
```

## Сборка на GitHub

1. Запушьте проект в свой репозиторий (ветка `main`).
2. Actions → **MVS OS — сборка ISO** → **Run workflow**.

Что происходит:

| Шаг | Что делает |
| --- | --- |
| checks | имена пакетов по архиву Debian, `sh check.sh`, синтаксис Python, JSON, YAML Calamares |
| build | собирает ISO в Debian-окружении runner'а, пишет `PACKAGES-1.0.txt` |
| qemu | два дымовых теста: загрузка BIOS и UEFI, снимки экрана не пустые |
| release | по тегу `v*` публикует ISO, SHA256SUMS и список пакетов |

Скачать ISO: Actions → последняя сборка → Artifacts → `mvs-os-iso`.
Либо Release, если сборка шла по тегу:

```sh
git tag v1.0 && git push origin v1.0
```

### Лимит 2 ГБ

GitHub Release принимает файл до 2 ГБ. Если ISO больше, workflow не
публикует релиз, а оставляет ISO в артефактах и пишет предупреждение.
Варианты: оставить в релизе только `SHA256SUMS`, выложить ISO на другой
хостинг или собрать вариант без `firefox-esr`.

## Запись на флешку

Минимум 4 ГБ. **Все данные на флешке будут стёрты.**

Скрипт сам проверит SHA256, откажется писать на системный диск и
попросит ввести `YES`:

```sh
lsblk                                   # найти флешку, например /dev/sdb
sudo sh tools/write-usb.sh /dev/sdb
```

Если флешки нет под рукой, а перезагружать компьютер нельзя —
[запустите MVS OS в виртуальной машине](vm.md).

### Linux / macOS вручную

```sh
lsblk                                  # найти флешку, например /dev/sdb
sudo dd if=MVS-OS-1.0-amd64.iso of=/dev/sdb bs=4M status=progress conv=fsync
sync
```

### Windows

- **Rufus** → выберите ISO → режим «DD» (не ISO-режим).
- или **balenaEtcher** → Flash from file.

## Загрузка

1. Вставьте флешку, включите компьютер.
2. Меню загрузки: обычно `F12`, `F11`, `Esc` или `F9` при включении.
3. Выберите флешку в режиме **UEFI** (рекомендуется) или **Legacy/CSM**.

Через 20–40 секунд появится экран входа. Пользователь `mvs`, пароля нет —
это Live-режим, диск компьютера не изменяется.

## Secure Boot

Загрузчик Live-ISO не подписан ключами Microsoft, поэтому при включённом
Secure Boot флешка может не запуститься. Для Live-режима Secure Boot
нужно отключить в настройках прошивки.

Установленная система ставит подписанный shim + GRUB; на большинстве
машин она загружается и с включённым Secure Boot, но это зависит от
прошивки и не проверялось на всех моделях.

## Если не собирается

| Симптом | Что смотреть |
| --- | --- |
| `lb: command not found` | не установлен `live-build` |
| `Unable to locate package X` | `sh tools/check-packages.sh` покажет точное имя; или `apt-cache policy X` |
| сборка падает на хуке | `build/chroot` и вывод `lb build` |
| ISO есть, но не грузится | проверить SHA256, писать в DD-режиме, попробовать другой USB-порт |
| чёрный экран после GRUB | попробовать `nomodeset` в меню GRUB (клавиша `e`) |

Логи CI сохраняются артефактом `build-log` при ошибке.
