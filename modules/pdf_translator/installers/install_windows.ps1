# Встановлення Tesseract OCR на Windows через winget (вбудований у
# Windows 10/11 "App Installer"). Явного запиту прав адміністратора тут не
# робимо - winget сам показує UAC-запит, якщо він потрібен.
#
# --scope machine: ставимо в ОДНЕ передбачуване місце (Program Files), а не
# у профіль користувача.
winget install --id UB-Mannheim.TesseractOCR -e --silent --scope machine `
    --accept-source-agreements --accept-package-agreements

# ВАЖЛИВО: powershell -File повертає код 0, навіть якщо winget завершився з
# помилкою, - тому без явного "exit" програма вважала б невдале
# встановлення успішним і казала "встановлено, але не знайдено". Передаємо
# справжній код winget назовні. Два коди - не помилки:
#   -1978335189 (0x8A15002B) - немає застосовних оновлень (уже встановлено);
#   -1978335135 (0x8A150061) - пакет уже встановлений.
$code = $LASTEXITCODE
if ($code -eq -1978335189 -or $code -eq -1978335135) { $code = 0 }
exit $code
