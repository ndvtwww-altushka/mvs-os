# MVS OS 1.0 «Aurora»

[![Сборка ISO](https://github.com/ndvtwww-altushka/mvs-os/actions/workflows/build.yml/badge.svg?branch=main)](https://github.com/ndvtwww-altushka/mvs-os/actions/workflows/build.yml)
[![Последний релиз](https://img.shields.io/github/v/release/ndvtwww-altushka/mvs-os?display_name=tag)](https://github.com/ndvtwww-altushka/mvs-os/releases)

Собственная операционная система на базе Debian 12: свой рабочий стол,
свои приложения, свой установщик и своя политика безопасности.
Не «Debian с обоями» — но и не ядро, написанное с нуля: база Debian
выбрана осознанно, ради драйверов и стабильности.

**Статус:** исходники 1.0 готовы. ISO собирается в
[GitHub Actions](https://github.com/ndvtwww-altushka/mvs-os/actions/workflows/build.yml).
Локальная сборка и запуск на железе в этом окружении не выполнялись —
подробности в [docs/testing.md](docs/testing.md).

## Что внутри

**Оболочка**

- тёмная и светлая темы `MVS-Dark` / `MVS-Light`;
- набор иконок `MVS` (16 фирменных иконок + Papirus для остального);
- три обоины и фирменный экран загрузки Plymouth;
- нижняя панель: «Пуск», задачи, трей, уведомления, звук, питание,
  быстрые настройки, часы;
- экран входа LightDM с фирменным фоном.

**Приложения** (Python 3 + GTK 3, общий модуль `mvsui.py`)

| Приложение | Что делает по-настоящему |
| --- | --- |
| MVS Hub | запуск всех программ, поиск |
| MVS Control Center | 14 разделов: экран, звук, сеть, Bluetooth, питание, пользователи, безопасность, обновления |
| MVS Store | наборы, поиск и журнал: установка через `apt`, внешние репозитории — с пояснением |
| MVS Update | `apt-get update` + `dist-upgrade`, честный код выхода |
| MVS Monitor | графики CPU/RAM/сети, таблица процессов, kill |
| MVS Doctor | диск, память, службы, ufw, AppArmor, обновления, сеть, отчёт |
| MVS Cleaner | кэш apt, журналы, кэш пользователя, корзина |
| MVS Backup | tar.gz и восстановление |
| MVS Welcome | мастер первого запуска |
| MVS Quick | быстрые настройки по `Super+S` |
| MVS Games | 2048, змейка, сапёр, крестики-нолики, тетрис |
| MVS Files / Terminal / Settings | Thunar, XFCE Terminal, настройки XFCE с профилем MVS |
| MVS About | система, железо, лицензии |

**Система**

- установщик Calamares: диск, пользователь, локаль, загрузчик, UEFI + BIOS;
- Live: автологин `mvs`, sudo без пароля — **только в Live**;
- установленная система: пароль, sudo через группу `sudo`, polkit;
- ufw (входящие запрещены), AppArmor, sysctl-защита, `unattended-upgrades`
  только для security-обновлений;
- zram-swap для машин с малым объёмом RAM;
- из коробки: Firefox ESR, LibreOffice (тексты, таблицы, презентации),
  Thunderbird, VLC, PDF, архиватор, калькулятор, скриншоты;
- поиск файлов Catfish, связка ключей GNOME, сетевые папки (`smb://`);
- печать и сканирование по сети: CUPS, Avahi, `sane-airscan`;
- диск и железо: GParted, GNOME Disks, SMART, NVMe, `fwupd`, микрокод CPU;
- терминал: `htop`, `ncdu`, `rsync`, `git`, `curl`, `wget`, `vim`, `mc`,
  `jq`, `inxi`, `lshw`, `remmina`;
- Steam, GIMP, VS Code, NVIDIA — устанавливаются из Store.

## Структура

```
mvs-os/
├── build.sh                 сборка ISO
├── check.sh                 проверки без сборки
├── config/                  пакеты, хуки, файлы системы
├── docs/                    сборка, установщик, безопасность, тесты
├── tests/qemu_smoke.py      дымовой тест загрузки
├── tools/build-local.sh     установка зависимостей + сборка
├── tools/check-packages.sh  сверка пакетов с архивом Debian
├── tools/make-vm.sh         MVS OS в QEMU без перезагрузки
├── tools/write-usb.sh       запись ISO на флешку с проверками
├── tools/gen-icons.sh       генератор иконок
└── .github/workflows/       CI: пакеты → ISO → QEMU BIOS/UEFI → релиз
```

Подробнее: [docs/architecture.md](docs/architecture.md).

## Быстрый старт

```sh
sh ./check.sh                  # проверки
sh tools/check-packages.sh     # пакеты есть в Debian bookworm
sudo sh tools/build-local.sh   # зависимости + ISO на Debian 12
```

Или через GitHub: Actions → **MVS OS — сборка ISO** → Run workflow.
Записать ISO на флешку: `sudo sh tools/write-usb.sh /dev/sdX`.
Запустить без перезагрузки: `sh tools/make-vm.sh --install`.
Инструкции: [сборка и USB](docs/building.md), [виртуальная машина](docs/vm.md).

## Сборка и релизы в GitHub

- Push в `main` запускает статические проверки и сборку ISO.
- На pull request выполняются только статические проверки — полная сборка
  не тратит час на каждое изменение.
- Готовый ISO, `SHA256SUMS`, `BUILD-INFO` и список пакетов лежат в артефакте
  `mvs-os-iso` (14 дней).
- Чтобы опубликовать **GitHub Release**, запустите workflow вручную и
  включите `publish_release`. Тег по умолчанию — `v1.0`, его можно задать
  в поле `release_tag`.

Если ISO больше 2 ГБ, GitHub Release не принимает файл: сборка честно
предупреждает об этом и оставляет ISO в артефакте Actions.

## Документация

- [Сборка и запись на USB](docs/building.md)
- [Запуск в виртуальной машине](docs/vm.md)
- [Установщик](docs/installer.md)
- [Безопасность](docs/security.md)
- [Архитектура](docs/architecture.md)
- [Тестирование и ограничения](docs/testing.md)
- [Изменения](CHANGELOG.md)

## Ограничения

- Установка на реальном железе не прогонялась в рамках разработки.
- Secure Boot для Live-флешки нужно отключать.
- Шифрование диска не включено в шаги установщика.
- NVIDIA — только через установку драйвера из Store (non-free).
- ISO может превысить 2 ГБ — тогда релиз не публикуется, ISO остаётся
  артефактом Actions, а предупреждение видно в журнале.

## Лицензия

Собственный код MVS OS — MIT (см. [LICENSE](LICENSE)).
Пакеты Debian сохраняют свои лицензии.
