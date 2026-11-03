#!/usr/bin/env python3
"""Verify the actual review deck and PDF, without running a web server."""

import json
from pathlib import Path
from playwright.sync_api import sync_playwright
from pypdf import PdfReader

root = Path(__file__).resolve().parents[1]
output = root / '.review-checks'
output.mkdir(exist_ok=True)
errors = []
results = []
with sync_playwright() as p:
    candidates = sorted((Path.home() / '.cache/ms-playwright').glob('chromium-*/chrome-linux64/chrome'))
    options = {'executable_path': str(candidates[-1])} if candidates else {}
    browser = p.chromium.launch(**options)
    page = browser.new_page(viewport={'width': 1280, 'height': 950})
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto((root / 'review/board-meeting.html').as_uri(), wait_until='load')
    for n in range(12):
        page.select_option('#picker', str(n))
        page.wait_for_function('(n) => document.querySelector("#counter").textContent === `${n + 1} / 12`', arg=n)
        assert page.locator('.slide:visible').count() == 1
        assert page.locator('.slide:visible h1').inner_text()
        if n in (0, 2, 4, 7, 11):
            page.locator('.slide:visible').screenshot(path=str(output / f'slide-{n + 1:02}.png'))
        results.append({'slide': n + 1, 'title': page.locator('.slide:visible h1').inner_text()})
    page.select_option('#picker', '0')
    page.keyboard.press('ArrowRight')
    assert page.locator('#counter').inner_text() == '2 / 12'
    page.keyboard.press('Home')
    assert page.locator('#counter').inner_text() == '1 / 12'
    page.locator('#notes summary').click()
    assert page.locator('#notes').get_attribute('open') is not None
    assert 'two requested steps' in page.locator('#notes-text').inner_text()
    assert page.evaluate('Array.from(document.images).every(i => i.complete && i.naturalWidth > 0)')
    page.set_viewport_size({'width': 728, 'height': 1000})
    page.screenshot(path=str(output / 'inline-width.png'), full_page=True)
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
    page.set_viewport_size({'width': 390, 'height': 900})
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
    page.set_viewport_size({'width': 1280, 'height': 800})
    page.emulate_media(media='print')
    overflow = page.evaluate('''() => [...document.querySelectorAll('.slide')].flatMap((s,n) => {
      const r=s.getBoundingClientRect();
      const bad=[...s.querySelectorAll('h1,h3,p,figure,.takeaway,.slide-footer,article')].filter(e => {
        const b=e.getBoundingClientRect(); return b.width>0 && b.height>0 && (b.bottom>r.bottom+1 || b.right>r.right+1 || b.left<r.left-1);
      });
      return bad.length ? [{slide:n+1,elements:bad.map(e=>e.tagName+': '+e.textContent.slice(0,60))}] : [];
    })''')
    assert not overflow, overflow
    assert not errors, errors
    browser.close()
pdf = PdfReader(root / 'review/board-meeting.pdf')
assert len(pdf.pages) == 12, len(pdf.pages)
for expected, pdf_page in zip(results, pdf.pages):
    text = ' '.join(pdf_page.extract_text().split())
    assert expected['title'] in text, expected['title']
(root / 'review/verification.json').write_text(json.dumps({'slides': results, 'pdfPages': 12, 'checks': ['all slides visible through navigation', 'keyboard and presenter notes', 'all mockup images loaded', '728px and 390px no horizontal overflow', 'print layout has no clipped content', 'PDF has twelve readable pages', 'no browser page errors'], 'scope': 'Presentation and documentation only; no tutor application tested'}, indent=2)+'\n')
print('PASS: all slides, navigation, notes, images, responsive widths, print layout and 12-page PDF.')
