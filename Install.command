#!/bin/zsh
cd "$(dirname "$0")" || exit 1
for candidate in python3.13 python3.12 python3.11 python3; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
    "$candidate" install.py
    result=$?
    echo
    echo 'Нажмите Enter, чтобы закрыть окно.'
    read -r
    exit "$result"
  fi
done
echo 'Нужен Python 3.11 или новее. Установите Python с python.org и запустите этот файл снова.'
read -r
exit 1
