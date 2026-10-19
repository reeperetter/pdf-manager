# Встановлення Tesseract OCR на Windows через winget (вбудований у
# Windows 10/11 "App Installer"). Явного запиту прав адміністратора тут не
# робимо - winget сам показує UAC-запит, якщо він потрібен.
#
# Спробуємо кілька варіантів по черзі. Код -1978335216 (0x8A150010,
# "Применимый установщик не найден" / "No applicable installer found")
# winget повертає, коли маніфест пакета не має інсталятора під задані
# параметри - зокрема під примусовий "--scope machine", який раніше був
# єдиним варіантом і саме тому ламав встановлення. Тому першою йде спроба
# БЕЗ вказівки scope (winget сам вибирає підходящий), далі - варіанти з
# явним scope та архітектурою.
$common = @('--id', 'UB-Mannheim.TesseractOCR', '-e', '--silent',
            '--accept-source-agreements', '--accept-package-agreements')

$attempts = @(
    @(),
    @('--scope', 'machine'),
    @('--scope', 'user'),
    @('--architecture', 'x64'),
    @('--architecture', 'x86')
)

# Коди, що НЕ є помилкою:
#   -1978335189 (0x8A15002B) - немає застосовних оновлень (уже встановлено);
#   -1978335135 (0x8A150061) - пакет уже встановлений.
$noInstaller = -1978335216
$code = 1
foreach ($extra in $attempts) {
    winget install @common @extra
    $code = $LASTEXITCODE
    if ($code -eq -1978335189 -or $code -eq -1978335135) { $code = 0 }
    if ($code -ne $noInstaller) { break }
}

# powershell -File повертає 0, навіть якщо winget впав, - тому передаємо
# справжній код назовні явно.
exit $code
