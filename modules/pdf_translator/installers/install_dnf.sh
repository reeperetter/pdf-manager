#!/bin/sh
# Встановлення Tesseract OCR на Fedora/RHEL-подібних дистрибутивах.
# Запускається з правами root (через pkexec) із tesseract_installer.py.

set -e

dnf install -y tesseract

dnf install -y tesseract-langpack-ukr tesseract-langpack-rus || true
