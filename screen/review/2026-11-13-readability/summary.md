# smalltest summary

| model | case | page first (s) | page total (s) | page chars | patch first (s) | patch total (s) | patch chars | errors |
|---|---|---|---|---|---|---|---|---|
| deepseek | brak | 6.74 | 9.02 | 675 | 6.13 | 7.64 | 516 | - |
| deepseek | linje | 3.69 | 6.33 | 730 | 2.85 | 4.12 | 320 | - |

## usage

### deepseek (deepseek-v4.1-flash)

- brak page: `{"total_tokens": 7391}` patch: `{"total_tokens": 7458}`
- linje page: `{"total_tokens": 7058}` patch: `{"total_tokens": 7192}`

## render lint (screenkit issues)

### deepseek

- brak 370x610: ready_ms=404 fontPx=17.5 issues=[] patch_issues=[{"kind": "dense", "msg": "text is only 12.75px on this screen (minimum 16px). Keep one teaching step and one main visual; cut text or split the page."}]
- brak 370x558: ready_ms=370 fontPx=16.75 issues=[] patch_issues=[{"kind": "dense", "msg": "text is only 11.5px on this screen (minimum 16px). Keep one teaching step and one main visual; cut text or split the page."}]
- brak 1000x700: ready_ms=304 fontPx=30.25 issues=[] patch_issues=[]
- linje 370x610: ready_ms=573 fontPx=14.75 issues=[{"kind": "dense", "msg": "text is only 14.75px on this screen (minimum 16px). Keep one teaching step and one main visual; cut text or split the page."}] patch_issues=[{"kind": "dense", "msg": "text is only 12.75px on this screen (minimum 16px). Keep one teaching step and one main visual; cut text or split the page."}]
- linje 370x558: ready_ms=552 fontPx=13.75 issues=[{"kind": "dense", "msg": "text is only 13.75px on this screen (minimum 16px). Keep one teaching step and one main visual; cut text or split the page."}] patch_issues=[{"kind": "dense", "msg": "text is only 11.5px on this screen (minimum 16px). Keep one teaching step and one main visual; cut text or split the page."}]
- linje 1000x700: ready_ms=615 fontPx=20.5 issues=[] patch_issues=[]

