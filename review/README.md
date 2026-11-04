# First build review

Open the [presentation](board-meeting.html) and use the arrow buttons, arrow keys, or slide selector. Each slide has optional presenter notes. The [PDF](board-meeting.pdf) is a standalone copy for reading or sharing. The HTML uses images stored in this repository, so keep the project files together when moving it.

The meeting covers the agreed product and visual foundation, the recommended technical approach, and the questions the next integration experiment must answer. Technical choices are proposals for review. No tutor application has been implemented or deployed.

- [Technical plan](../BUILD-PLAN.md)
- [Meeting notes](MEETING-NOTES.md)
- [Sources and checks](../docs/technical-evidence.md)
- [Review PR](https://github.com/johan-acevedo/open-tutor/pull/1)

Rebuild the HTML and notes with Python:

```sh
python3 review/build.py
```

To also rebuild the PDF, use Playwright with Chromium installed:

```sh
uv run --no-project --with playwright python review/build.py --pdf
```

The renderer uses an existing standard Playwright Chromium installation when available. If Chromium is absent, install it with Playwright before exporting. This tooling builds the presentation only; it does not run the tutor or call AI providers.

Check local links and the package contents:

```sh
python3 review/check.py
```

Verify every slide in Chromium, keyboard navigation, responsive widths, print overflow and PDF page count:

```sh
uv run --no-project --with playwright --with pypdf python review/verify_render.py
```

This writes `verification.json` and local screenshots under `.review-checks/`. It needs an installed Playwright Chromium browser.
