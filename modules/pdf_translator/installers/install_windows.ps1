# Встановлення Tesseract OCR на Windows через winget (вбудований у
# Windows 10/11 "App Installer"). Явного запиту прав адміністратора тут не
# робимо - winget сам показує UAC-запит, якщо він потрібен.
#
# '--source winget' - ставимо ТІЛЬКИ з основного репозиторію winget. Без
# цього winget перебирає всі джерела, зокрема "msstore" (Microsoft Store),
# яке вимагає прийняти окрему угоду й код регіону, а при проблемах із
# мережею/регіоном падає з помилкою 0x8a15000f ("Отсутствуют данные,
# требуемые источником") - і все встановлення зривається, хоча Tesseract
# є лише в основному джерелі.
$common = @('--id', 'UB-Mannheim.TesseractOCR', '-e', '--silent',
            '--source', 'winget',
            '--accept-source-agreements', '--accept-package-agreements')

# Оновити індекс джерела (помилку ігноруємо - це лише спроба).
winget source update --name winget 2>&1 | Out-Null

# Спроби по черзі: без scope (winget обирає сам), потім явні варіанти.
# -1978335216 (0x8A150010) = "применимый установщик не найден" для заданих
# параметрів - тоді пробуємо наступний варіант.
$attempts = @(
    @(),
    @('--scope', 'machine'),
    @('--scope', 'user'),
    @('--architecture', 'x64'),
    @('--architecture', 'x86')
)

$noInstaller = -1978335216
$sourceBroken = -1978335217   # 0x8A15000F: джерело не віддає дані

function Try-Install {
    $c = 1
    foreach ($extra in $attempts) {
        winget install @common @extra
        $c = $LASTEXITCODE
        # Не помилки: -1978335189 (немає оновлень), -1978335135 (уже встановлено).
        if ($c -eq -1978335189 -or $c -eq -1978335135) { $c = 0 }
        if ($c -ne $noInstaller) { break }
    }
    return $c
}

$code = Try-Install

# Джерело зіпсоване: скидаємо його (потрібні права адміністратора - якщо їх
# немає, команда просто завершиться помилкою, і ми повідомимо про це).
if ($code -eq $sourceBroken) {
    winget source reset --force winget 2>&1 | Out-Null
    winget source update --name winget 2>&1 | Out-Null
    $code = Try-Install
}

# powershell -File повертає 0, навіть якщо winget впав, - тому передаємо
# справжній код назовні явно.
exit $code
