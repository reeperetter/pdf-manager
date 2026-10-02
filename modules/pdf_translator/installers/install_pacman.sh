#!/bin/sh
# Встановлення Tesseract OCR на Arch Linux та похідних (pacman).
# Запускається з правами root (через pkexec) із tesseract_installer.py.

set -e

pacman -Sy --noconfirm --needed tesseract

pacman -S --noconfirm --needed tesseract-data-ukr tesseract-data-rus tesseract-data-eng || true
