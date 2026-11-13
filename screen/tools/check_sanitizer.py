"""Exercise model page and patch sanitization in a real sandboxed browser.

  uv run --project server python screen/tools/check_sanitizer.py
"""

from __future__ import annotations

import pathlib

from playwright.sync_api import sync_playwright

import screenkit

ATTACKS = '''</template><script>window.modelRan = true</script>
<h1>Säker klocka</h1>
<img src="data:image/png;base64,broken" onerror="window.modelRan = true">
<video poster="https://example.org/unchecked.jpg"><source src="https://example.org/unchecked.mp4"></video>
<input type="image" src="https://example.org/unchecked.jpg">
<svg><image href="https://example.org/unchecked.jpg"></image></svg>
<svg onload="window.modelRan = true"><circle r="2"></circle></svg>
<button id="attack-button" onclick="window.modelRan = true">Tryck</button>
<a id="link" href="javascript:window.modelRan = true">Länk</a>
<ot-clock id="clock" time="7:30" onclick="window.modelRan = true"></ot-clock>
<ot-fraction value="1/2" color='red\"><image href=\"data:image/png;base64,broken\" onerror=\"window.modelRan=true\"></image><rect fill=\"red'></ot-fraction>
<ot-hidden id="facit">$7 + 3 = 10$</ot-hidden>
<ot-choice id="choice"><button correct>A</button><button>B</button></ot-choice>
<ot-gap id="gap" answer="went"></ot-gap>
<p id="later" later>Senare</p>
<style>body { display: none }</style>'''


def run(browser, fallback: bool, blocked: bool = False):
    context = browser.new_context(viewport={"width": 370, "height": 610})
    if fallback:
        # Run the actual library fallback, including its real CDN download.
        context.add_init_script('delete Element.prototype.setHTML')
    if blocked:
        context.route('**/dompurify@*/**', lambda route: route.abort())
    page = context.new_page()
    try:
        page.set_content(screenkit.host_page(screenkit.compose(ATTACKS)))
        page.wait_for_function('() => frames.length === 1')
        frame = page.frames[1]
        frame.wait_for_function("() => document.documentElement.dataset.otReady === '1'")
        if blocked:
            assert frame.evaluate("() => document.getElementById('page').children.length") == 0
            assert frame.evaluate("() => ot.issues.some(i => i.kind === 'boot')")
        else:
            assert frame.evaluate("() => document.getElementById('clock').getAttribute('time')") == '7:30'
            assert frame.evaluate("() => document.querySelector('#choice button').hasAttribute('correct')")
            assert frame.evaluate("() => document.getElementById('gap').getAttribute('answer')") == 'went'
            assert frame.evaluate("() => document.getElementById('later').hasAttribute('later')")
            frame.evaluate("() => document.getElementById('attack-button').click()")
            assert frame.evaluate("() => !document.getElementById('link').hasAttribute('href')")
            assert not frame.evaluate("() => !!window.modelRan")
            assert frame.evaluate("() => !document.querySelector('#page img, #page image, #page video, #page input[type=image]')")
            assert frame.evaluate("() => !document.querySelector('#page script, #page style, #page [onclick], #page [onerror], #page [onload]')")
            frame.evaluate('''() => ot.patch(`<ot-patch target="clock"><ot-clock time="9:15" onmouseover="window.modelRan=true"><img src="data:image/png;base64,broken" onerror="window.modelRan=true"><script>window.modelRan=true</script></ot-clock></ot-patch>`)''')
            assert frame.evaluate("() => document.getElementById('clock').getAttribute('time')") == '9:15'
            frame.evaluate("() => document.getElementById('clock').dispatchEvent(new Event('mouseover'))")
            assert not frame.evaluate("() => !!window.modelRan")
            assert frame.evaluate("() => !document.querySelector('#page img, #page image, #page video, #page input[type=image]')")
            assert frame.evaluate("() => !document.querySelector('#page script, #page [onmouseover], #page [onerror]')")
            frame.evaluate("() => ot.reveal('facit')")
            assert frame.evaluate("() => document.getElementById('facit').hasAttribute('data-revealed')")
        print('sanitizer passed:', 'library' if fallback else 'native', 'blocked' if blocked else 'page + patch + reveal')
    finally:
        context.close()


def main():
    from open_tutor.board import PageItem
    from open_tutor.screen import page_title

    examples = pathlib.Path(__file__).resolve().parents[1] / 'examples'
    sizes = []
    for path in examples.glob('*.html'):
        if path.name.endswith('.patch.html'):
            continue
        body = path.read_text()
        item = PageItem(id='p123', title=page_title(body, path.stem), body=body)
        size = len(item.model_dump_json().encode('utf-8'))
        assert size < 15000, (path.name, size)
        sizes.append((size, path.name))
    print('Largest page RPC payload:', max(sizes), 'bytes. Body escaping happens after RPC.')
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            run(browser, False)
            run(browser, True)
            run(browser, True, True)
        finally:
            browser.close()


if __name__ == '__main__':
    main()
