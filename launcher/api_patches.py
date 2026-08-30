"""补丁相关 API mixin，减轻 app.py 体积。"""

from __future__ import annotations


class PatchesApiMixin:
    def workbench_diagnostic(self) -> dict:
        from launcher.workbench.diagnostic import run_full_diagnostic

        try:
            return run_full_diagnostic()
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def restore_workbench_unified(self, target: str = "auto") -> dict:
        from launcher.workbench.diagnostic import restore_workbench_layer

        try:
            return self._with_cursor_closed(
                lambda _layout: restore_workbench_layer(target=target)
            )
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def patch_autofix_plan(self) -> dict:
        from launcher.workbench.autofix import plan_autofix

        try:
            return plan_autofix()
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def patch_autofix(self, close_ide: bool = False) -> dict:
        from launcher.workbench.autofix import run_autofix

        try:
            return run_autofix(close_ide=bool(close_ide))
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def check_launcher_update(self) -> dict:
        from launcher.versioning import check_launcher_update

        try:
            return check_launcher_update()
        except Exception as exc:
            return {"ok": False, "error": str(exc), "newer": False}

    def migrate_workbench_backups(self) -> dict:
        from launcher.workbench import backup as wb_backup

        try:
            return wb_backup.migrate_legacy_into_unified()
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
