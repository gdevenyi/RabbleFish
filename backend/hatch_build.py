"""Hatch build hook: put the built UI into the wheel as `rabblefish/static`.

When the wheel is built from a checkout of the repository (for example with
`uv tool install ./backend`), the hook runs `pnpm install --frozen-lockfile` and
`pnpm -C frontend build` at the repository root, and adds `frontend/dist` to the wheel.
It needs Node.js and pnpm.

- `RABBLEFISH_SKIP_UI_BUILD=1`: do not run pnpm; use the `frontend/dist` that is there (from an
  earlier `pnpm build`).
- An editable install (`uv sync`, `uv run`) does not build the UI: in a checkout the app
  serves `frontend/dist` directly (see `rabblefish.settings.static_dir`).
"""

import os
import shutil
import subprocess
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class UiBuildHook(BuildHookInterface):
    PLUGIN_NAME = "rabblefish-ui"

    def initialize(self, version: str, build_data: dict) -> None:
        if self.target_name != "wheel" or version == "editable":
            return
        repo = Path(self.root).resolve().parent
        frontend = repo / "frontend"
        dist = frontend / "dist"
        if not (frontend / "package.json").is_file():
            raise RuntimeError(
                f"{frontend} not found: build the wheel from a checkout of the whole "
                "repository (the UI is in frontend/), for example `uv tool install ./backend`"
            )
        if not os.environ.get("RABBLEFISH_SKIP_UI_BUILD"):
            pnpm = shutil.which("pnpm")
            if pnpm is None:
                raise RuntimeError(
                    "pnpm not found: the wheel needs the built UI. Install Node.js and pnpm, "
                    "or run `pnpm build` and set RABBLEFISH_SKIP_UI_BUILD=1"
                )
            self.app.display_info("Building the UI: pnpm install && pnpm -C frontend build")
            subprocess.run([pnpm, "install", "--frozen-lockfile"], cwd=repo, check=True)
            subprocess.run([pnpm, "-C", "frontend", "build"], cwd=repo, check=True)
        if not (dist / "index.html").is_file():
            raise RuntimeError(f"{dist}/index.html not found: run `pnpm build` first")
        build_data["force_include"][str(dist)] = "rabblefish/static"
