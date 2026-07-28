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
powershell -ExecutionPolicy Bypass -File .\scripts\test-packaging-scripts.ps1
```
