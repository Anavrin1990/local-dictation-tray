# Known issues and workarounds

## SQLite connection locks on Windows

`sqlite3.Connection` does not close when used only as a context manager: it commits or rolls back but leaves the file handle open. On Windows this can lock `history.sqlite3` and prevent backup/removal. All repository operations therefore wrap connections in `contextlib.closing(...)`.

## Windows log handle during a short self-check

`RotatingFileHandler` intentionally keeps `app.log` open for the lifetime of the tray process. A short-lived self-check must not create one without closing it, because test/package cleanup can then fail with `WinError 32`. The self-check verifies log writability with a scoped `open(..., "a")` instead.

## Git reports dubious ownership in this workspace

When the workspace is mounted under a different Windows SID, Git can reject status/diff commands. This does not affect the application or its tests. Configure the workspace as a safe directory in the developer environment only when needed: `git config --global --add safe.directory 'D:/AI Tasks'`.

## PowerShell blocks local QA scripts

On machines whose execution policy blocks local `.ps1` files, invoke the checks without changing the global policy:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\test-package.ps1 -RunSelfCheck -RunGpuSelfCheck
powershell -ExecutionPolicy Bypass -File .\scripts\test-installer.ps1 -InstallerPath .\dist-installer\LocalDictationTray-0.3.0-Setup.exe
```

## Packaged self-check returns code 2 in a restricted sandbox

The packaged `--self-check` writes only to the normal per-user application data
directory. A restricted build sandbox may deny that profile path and return code
2 even when the package is valid. Re-run `scripts\test-package.ps1 -RunSelfCheck`
with access to the real user `%APPDATA%`; do not weaken the application data path
or disable the check.

## Pytest cannot write `.pytest_cache`

Some managed workspace sessions deny writes to the existing `.pytest_cache`
directory. Pytest still executes the suite normally; the warning only means its
optional cache was not updated. Use `pytest -p no:cacheprovider` when a clean
warning-free diagnostic run is needed.

# GPU/runtime notes

- `--self-check` deliberately does not open `app.log`: an already-running Windows tray
  process may hold that file with exclusive sharing.  Check the log directory instead.
- Some Codex/sandbox Windows sessions expose duplicate `Path`/`PATH` environment keys.
  `Start-Process` then fails before creating a child. Run long local builds directly (or
  normalize the environment in a normal PowerShell session).
