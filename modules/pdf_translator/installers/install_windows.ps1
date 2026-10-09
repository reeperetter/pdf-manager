# Встановлення Tesseract OCR на Windows через winget (вбудований у
# Windows 10/11 "App Installer"). На відміну від Linux-скриптів,
# явного запиту прав адміністратора тут не робимо - winget сам показує
# UAC-запит, якщо він потрібен для конкретного пакета.
#
# --scope machine: без цього winget сам вирішує, куди ставити пакет, і
# при --silent-встановленні без явного підвищення прав часто обирає
# профіль користувача (%LocalAppData%\...), а не Program Files. Код у
# ocr.py find_tesseract_cmd() тепер уміє шукати й там теж, але краще
# одразу ставити в ОДНЕ передбачуване місце - так наступні запуски
# програми однозначно знаходять щойно встановлений tesseract, замість
# "встановлення пройшло, але досі не знайдено" при неспівпадінні шляхів.
winget install --id UB-Mannheim.TesseractOCR -e --silent --scope machine `
    --accept-source-agreements --accept-package-agreements
