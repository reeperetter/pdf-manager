#!/bin/sh
# Встановлення Tesseract OCR на Debian/Ubuntu-подібних дистрибутивах.
# Запускається з правами root (через pkexec) із tesseract_installer.py.
#
# Мовні пакети ставимо ОКРЕМОЮ командою з "|| true": якщо назва пакета
# не існує в конкретному репозиторії дистрибутива, це не повинно
# зірвати встановлення самого бінарника tesseract.

set -e

# "|| true": якщо в системі є ще якийсь сторонній (навіть непов'язаний
# з tesseract) apt-репозиторій, що зараз недоступний, apt-get update
# поверне ненульовий код незалежно від того, що основні репозиторії
# оновились успішно. Не повинно зривати весь install через це.
apt-get update || true

apt-get install -y tesseract-ocr
apt-get install -y tesseract-ocr-ukr tesseract-ocr-rus || true
