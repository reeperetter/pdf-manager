#!/bin/sh
# Встановлення Tesseract OCR на openSUSE та похідних (zypper).
# Запускається з правами root (через pkexec) із tesseract_installer.py.

set -e

zypper --non-interactive install tesseract-ocr

zypper --non-interactive install tesseract-ocr-traineddata-ukrainian tesseract-ocr-traineddata-russian || true
