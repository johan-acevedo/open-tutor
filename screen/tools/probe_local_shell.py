"""Run the existing live E2E probe with this checkout's built web assets.

Only this browser receives local index.html and /assets files. API and LiveKit
traffic use the existing dev service; no service or deployment changes.

  npm run build --prefix web
  uv run --project server python screen/tools/probe_local_shell.py --shots-dir /tmp/screen-shell-e2e
Other arguments go to server/scripts/smart_screen_e2e.py unchanged.
"""

from __future__ import annotations

import mimetypes
import pathlib
import runpy
from urllib.parse import urlsplit

from playwright.async_api import Browser

ROOT = pathlib.Path(__file__).resolve().parents[2]
DIST = ROOT / 'web' / 'dist'


def main():
    if not (DIST / 'index.html').exists():
        raise SystemExit('Build web/ first.')
    original = Browser.new_context

    async def local_assets(self, *args, **kwargs):
        context = await original(self, *args, **kwargs)

        async def route_asset(route):
            path = urlsplit(route.request.url).path
            local = DIST / ('index.html' if path == '/' else path.lstrip('/'))
            if (path == '/' or path.startswith('/assets/')) and local.is_file() and DIST in local.resolve().parents:
                await route.fulfill(path=str(local), content_type=mimetypes.guess_type(local)[0] or 'application/octet-stream')
            else:
                await route.continue_()

        await context.route('https://dell5500.tail2e1c4e.ts.net:9444/**', route_asset)
        return context

    Browser.new_context = local_assets
    try:
        runpy.run_path(str(ROOT / 'server' / 'scripts' / 'smart_screen_e2e.py'), run_name='__main__')
    finally:
        Browser.new_context = original


if __name__ == '__main__':
    main()
