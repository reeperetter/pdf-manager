#!/bin/sh
# Встановлення Tesseract OCR на macOS через Homebrew.
# На відміну від Linux-скриптів, root тут не потрібен - brew сам працює
# від імені звичайного користувача.

set -e

brew install tesseract
brew install tesseract-lang || true
