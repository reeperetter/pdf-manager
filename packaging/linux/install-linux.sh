#!/usr/bin/env bash
# Інтеграція PDF Manager у Linux-середовище: створює ярлик у меню
# застосунків ("PDF Manager") з правильною іконкою.
#
# Чому це потрібно: у Linux бінарний файл не може мати вбудованої іконки
# (на відміну від .exe у Windows), тому файловий менеджер показує для
# нього стандартну "шестерню". Іконку отримує лише ЯРЛИК (.desktop-файл),
# який і створює цей скрипт. Запускайте його з теки, де лежить PDFManager.
#
#   ./install-linux.sh            - встановити ярлик
#   ./install-linux.sh --remove   - прибрати ярлик
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APPS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
DESKTOP_FILE="$APPS_DIR/pdfmanager.desktop"

if [[ "${1:-}" == "--remove" ]]; then
    rm -f "$DESKTOP_FILE"
    command -v update-desktop-database >/dev/null && update-desktop-database "$APPS_DIR" || true
    echo "Ярлик прибрано."
    exit 0
fi

if [[ ! -f "$HERE/PDFManager" ]]; then
    echo "Не знайдено файл PDFManager поруч зі скриптом ($HERE)." >&2
    exit 1
fi
if [[ ! -f "$HERE/PDFManager.png" ]]; then
    echo "Не знайдено PDFManager.png поруч зі скриптом ($HERE)." >&2
    exit 1
fi

# Артефакти GitHub Actions не зберігають права на виконання -
# повертаємо їх.
chmod +x "$HERE/PDFManager"

mkdir -p "$APPS_DIR"
cat > "$DESKTOP_FILE" <<DESKTOP
[Desktop Entry]
Type=Application
Name=PDF Manager
Comment=Інструменти для роботи з PDF
Exec="$HERE/PDFManager"
Path=$HERE
Icon=$HERE/PDFManager.png
Terminal=false
Categories=Office;Utility;
StartupWMClass=PDFManager
DESKTOP
chmod +x "$DESKTOP_FILE"

command -v update-desktop-database >/dev/null && update-desktop-database "$APPS_DIR" || true

echo "Готово: ярлик створено ($DESKTOP_FILE)."
echo "PDF Manager з'явився у меню застосунків із власною іконкою."
echo "Не переміщуйте теку після встановлення (або запустіть скрипт знову)."
