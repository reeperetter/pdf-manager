# Встановлення Tesseract OCR на Windows через winget (вбудований у
# Windows 10/11 "App Installer"). На відміну від Linux-скриптів,
# явного запиту прав адміністратора тут не робимо - winget сам показує
# UAC-запит, якщо він потрібен для конкретного пакета.

winget install --id UB-Mannheim.TesseractOCR -e --silent `
    --accept-source-agreements --accept-package-agreements
