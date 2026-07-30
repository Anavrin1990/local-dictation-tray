# Packaging Local Dictation

Цель: один Windows-установщик, который ставит приложение с локальным распознаванием
без заранее установленного Python, CUDA или скачивания модели на компьютере пользователя.

Системные требования готового приложения: Windows 10/11 x64, обычный x64 CPU и
микрофон. Нужны около 1 ГБ свободного места. CUDA, ffmpeg и Python на целевой
машине не требуются. Распознавание использует CPU `int8`, поэтому является
безопасным fallback для компьютеров без видеокарты.

## Контракт приложения

* Точка входа: `main.py` (либо параметр `-EntryPoint`). Пакет приложения — `dictation_tray`.
* Приложение принимает `--self-check`, выполняет только локальные проверки
  (конфигурация, БД/журнал, доступность файлов модели) и возвращает `0`.
* Для локальной модели приложение читает `LOCAL_DICTATION_MODEL_DIR`. В frozen-сборке
  runtime hook задаёт этот путь на вложенные файлы.
* Движок распознавания: `faster-whisper` / CTranslate2. Модель `Systran/faster-whisper-small`
  скачивается только на машине сборки и добавляется в `assets/models/faster-whisper-small`.
  В целевой системе сеть для работы распознавания не нужна: движок должен вызываться
  с `local_files_only=True`.

## Сборка

Нужны Windows 10/11 x64, Python 3.11/3.12 и Inno Setup 6 только на машине сборки.

```powershell
.\scripts\build-installer.ps1 -Version 1.0.0
```

Скрипт создаёт isolated venv, устанавливает зависимости из `requirements.txt`,
скачивает модель `Systran/faster-whisper-small`, CUDA runtime, собирает PyInstaller one-folder и
затем запускает Inno Setup. Результат: `dist-installer\LocalDictationTray-<версия>-Setup.exe`.

Для воспроизводимой офлайн-пересборки предварительно заполните
`assets/models/faster-whisper-small`; с `-Offline` сборка не обращается к сети.
PyInstaller 6 помещает модель в `LocalDictationTray\_internal\models\faster-whisper-small`;
runtime hook передаёт этот путь приложению автоматически.

## Проверка

```powershell
.\scripts\test-packaging-scripts.ps1
.\scripts\test-package.ps1 -DistDir .\dist\LocalDictationTray
.\scripts\test-installer.ps1 -InstallerPath .\dist-installer\LocalDictationTray-1.0.0-Setup.exe
```

В CI можно добавить `-RunSelfCheck` к `test-package.ps1`. Полную проверку установки
нужно запускать в одноразовой Windows VM/песочнице, чтобы не изменять машину сборки.

## Known build environment issues

## CUDA build contract

The frozen build contains `Systran/faster-whisper-small`, `faster-whisper==1.2.1`, `ctranslate2==4.8.1`, CUDA 12 cuBLAS `12.4.5.8`, and cuDNN 8 `8.9.7.29`. `runtime_local_dictation.py` registers bundled `nvidia/cublas/bin` and `nvidia/cudnn/bin` with both `os.add_dll_directory` and `PATH` before CTranslate2 imports. `test-package.ps1` requires `model.bin`, `cublas64_12.dll`, and `cudnn64_8.dll`; use `-RunGpuSelfCheck` on an NVIDIA build host to require a real CUDA inference.

* `-Offline` does not contact PyPI or Hugging Face. It requires an existing
  `.build\packaging-venv-3.11` or `.build\packaging-venv-3.12` containing all
  dependencies, plus a prepared model directory.
* The build script deliberately rejects Python 3.14 and newer. As of this project,
  the frozen dependency set is supported only on CPython 3.11/3.12; accepting 3.14
  can make pip compile native packages instead of selecting compatible wheels.
* PyInstaller 6 puts bundled data below `_internal`. The package check therefore
  accepts `_internal/models/faster-whisper-small` (and the legacy root layout), while
  the runtime hook resolves the exact frozen location through `sys._MEIPASS`.
