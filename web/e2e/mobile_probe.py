"""Exercise the real React app with a build-time, test-only LiveKit transport.

Run from the repo: uv run --with playwright python web/e2e/mobile_probe.py
No providers, production endpoints, family rooms, microphone or camera hardware are used.
"""
import base64, contextlib, functools, http.server, json, pathlib, subprocess, threading
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = ROOT / '.review-checks/mobile'
OUT.mkdir(parents=True, exist_ok=True)
subprocess.run(['npm', 'exec', '--', 'vite', 'build', '--config', 'e2e/vite.config.mjs'], cwd=ROOT/'web', check=True, stdout=subprocess.DEVNULL)
class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_): pass
server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Handler, directory=str(ROOT/'.review-checks/mobile-site')))
threading.Thread(target=server.serve_forever, daemon=True).start()
url = 'http://127.0.0.1:' + str(server.server_port)
results = []
def check(name, value):
    results.append({'check': name, 'pass': bool(value)})
    assert value, name

STEPS = {'id':'equation','kind':'steps','title':'Ekvationer · ett steg i taget','steps':[{'tex':'3x + 5 = 20'},{'tex':'3x = 15','op':'-5'},{'tex':'x = 5','op':'\\div 3'}]}
PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a/tkAAAAASUVORK5CYII=')

try:
  with sync_playwright() as p:
    executables = sorted(pathlib.Path.home().glob('.cache/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell'))
    browser = p.chromium.launch(executable_path=str(executables[-1]) if executables else None)
    errors=[]
    for w,h in [(360,800),(390,844),(430,932),(844,390),(820,900),(900,700),(1366,768)]:
      phone = w<=600 or (w==844 and h==390)
      context=browser.new_context(viewport={'width':w,'height':h},is_mobile=phone,has_touch=phone)
      page=context.new_page(); page.on('pageerror',lambda err:errors.append(str(err)))
      def session_route(route):
        page.evaluate("mobileProbe.events.push(['session-request'])")
        route.fulfill(json={'url':'ws://fictional.invalid','token':'fictional','room':'fictional-room'})
      page.route('**/api/session',session_route)
      page.goto(url)
      page.get_by_label('Förnamn',exact=True).fill('Leo')
      if w==390: page.screenshot(path=str(OUT/'01-picker.png'))
      page.get_by_role('button',name='Starta',exact=True).click()
      page.locator('.ot-bottombar').wait_for()
      check(f'{w}: audio unlock precedes request',page.evaluate("mobileProbe.events.findIndex(e=>e[0]==='startAudio') < mobileProbe.events.findIndex(e=>e[0]==='session-request')"))
      check(f'{w}: mobile classification',page.locator('.ot-root').evaluate('(el)=>el.classList.contains("ot-phone")')==phone)
      if w==390: page.screenshot(path=str(OUT/'02-greeting.png'))
      def rpc(method,payload):
        return page.evaluate('async ([method,payload])=>await mobileProbe.rooms.at(-1).rpc.get(method)({payload:JSON.stringify(payload)})',[method,payload])
      _show_ack = json.loads(rpc('board.show',STEPS))
      check(f'{w}: board rendered acknowledgement',_show_ack.get('ok') is True and _show_ack.get('board',{}).get('w',0) >= 1)
      rpc('board.focus',{'id':'equation','step':1})
      rpc('board.show',{'id':'other','kind':'text','title':'Annat ämne','markdown':'En kort förklaring.'})
      rpc('board.update',{**STEPS,'title':'Ekvationer'})
      rpc('board.focus',{'id':'equation','step':1})
      page.evaluate("mobileProbe.rooms.at(-1).emit('ParticipantAttributesChanged',{'lk.agent.state':'speaking'})")
      page.evaluate("async()=>await mobileProbe.rooms.at(-1).streams.get('lk.transcription')({async *[Symbol.asyncIterator](){yield 'Precis. Vi tar bort fem på båda sidor.'}},{identity:'fictional-tutor'})")
      page.wait_for_timeout(80)
      if phone:
        check(f'{w}: older focused card visible',page.locator('[data-board-id=equation]').is_visible() and not page.locator('[data-board-id=other]').is_visible())
        check(f'{w}: future answer unrevealed',not page.locator('[data-step="2"]').is_visible())
        check(f'{w}: readable step above companion',page.evaluate('''() => {
          const a=document.querySelector('.ot-step-eq.focused').getBoundingClientRect();
          const b=document.querySelector('.ot-avatar-col').getBoundingClientRect();
          const c=document.querySelector('.ot-board-scroll').getBoundingClientRect();
          const overlap=a.left<b.right&&a.right>b.left&&a.top<b.bottom&&a.bottom>b.top;
          return !overlap && a.top>=c.top-1 && a.bottom<=c.bottom+1;
        }'''))
        page.get_by_role('button',name='Hela tavlan',exact=False).click()
        check(f'{w}: full board accessible',page.locator('[data-board-id=other]').is_visible() and page.locator('[data-step="2"]').is_visible())
        page.get_by_role('button',name='Hela tavlan',exact=False).click()
        page.get_by_role('button',name='Gör tutorn mindre',exact=True).click()
        check(f'{w}: explicit small mode',page.locator('.ot-root').evaluate('(el)=>el.classList.contains("ot-small-companion")'))
        page.get_by_role('button',name='Gör tutorn större',exact=True).click()
      check(f'{w}: no page overflow',page.evaluate('document.documentElement.scrollWidth <= innerWidth && document.querySelector(".ot-root").getBoundingClientRect().bottom <= innerHeight+1'))
      if w in (390,844,1366): page.screenshot(path=str(OUT/f'03-active-{w}.png'))
      if w==390:
        # Canvas/photo decoding and bytes flow are real; OS picker is replaced by a synthetic file.
        page.locator('input[capture]').set_input_files({'name':'matte.png','mimeType':'image/png','buffer':PNG})
        page.get_by_role('button',name='Avbryt',exact=True).click()
        check('cancel photo sends nothing',page.evaluate("!mobileProbe.events.some(e=>e[0]==='bytes')"))
        page.locator('input[capture]').set_input_files({'name':'matte.png','mimeType':'image/png','buffer':PNG})
        check('photo not sent before confirmation',page.evaluate("!mobileProbe.events.some(e=>e[0]==='bytes')"))
        page.screenshot(path=str(OUT/'04-homework-preview.png'))
        page.evaluate('mobileProbe.failBytes=true')
        page.get_by_role('button',name='Skicka till tutorn',exact=True).click()
        page.get_by_role('button',name='Skicka till tutorn',exact=True).wait_for(state='visible')
        check('failed photo stays available to retry',page.locator('.ot-homework-tray').is_visible())
        page.evaluate('mobileProbe.failBytes=false')
        page.get_by_role('button',name='Skicka till tutorn',exact=True).click()
        page.locator('.ot-homework-tray').wait_for(state='hidden')
        check('photo bytes sent after confirmation',page.evaluate("mobileProbe.events.some(e=>e[0]==='bytes'&&e[1]>0)"))
        # A resource stays the same DOM player while switching history and focus.
        rpc('board.show',{'id':'video','kind':'resource','title':'Film','url':url+'/not-a-real-video','embedUrl':url+'/not-a-real-video'})
        page.locator('.ot-resource-frame').evaluate("el=>el.dataset.samePlayer='yes'")
        rpc('board.focus',{'id':'equation','step':1})
        page.get_by_role('button',name='Hela tavlan',exact=False).click()
        check('resource player retained across views',page.locator('.ot-resource-frame').get_attribute('data-same-player')=='yes')
        page.get_by_role('button',name='Klar – prata vidare',exact=True).click()
        check('resource callback sent',page.evaluate("mobileProbe.events.some(e=>e[0]==='text'&&e[1].includes('resource-closed'))"))
        page.get_by_role('button',name='Hela tavlan',exact=False).click()
        rpc('board.focus',{'id':'equation','step':1})
        # Deliberately simulated visual viewport, not a claim about the iOS keyboard.
        page.locator('.ot-chat-input').focus()
        page.evaluate("Object.defineProperty(visualViewport,'height',{configurable:true,value:450});visualViewport.dispatchEvent(new Event('resize'))")
        page.locator('.ot-keyboard').wait_for()
        page.screenshot(path=str(OUT/'05-keyboard-simulated.png'))
        check('keyboard dock within visual viewport',page.locator('.ot-bottombar').evaluate('(el)=>el.getBoundingClientRect().bottom<=451'))
        page.locator('.ot-chat-input').fill('Jag förstår inte steg två')
        page.get_by_role('button',name='Skicka',exact=True).click()
        check('send retains input focus',page.locator('.ot-chat-input').evaluate('(el)=>document.activeElement===el&&el.value===""'))
        page.evaluate("delete visualViewport.height;document.activeElement.blur();visualViewport.dispatchEvent(new Event('resize'))")
        page.locator('.ot-keyboard').wait_for(state='hidden')
        # Playback-blocked recovery reuses the same call.
        page.evaluate("mobileProbe.blockAudio=true;mobileProbe.rooms.at(-1).emit('AudioPlaybackStatusChanged',false)")
        page.get_by_role('button',name='Tryck för att höra mig',exact=True).click()
        page.evaluate('mobileProbe.blockAudio=false')
        page.get_by_role('button',name='Tryck för att höra mig',exact=True).click()
        page.get_by_role('button',name='Tryck för att höra mig',exact=True).wait_for(state='hidden')
        check('audio retry keeps one room',page.evaluate('mobileProbe.rooms.length===1'))
        page.get_by_role('button',name='Avsluta',exact=True).click()
        check('end requires confirmation',page.get_by_role('button',name='Ja, avsluta',exact=True).is_visible())
        page.get_by_role('button',name='Fortsätt',exact=True).click()
      context.close()
    check('no browser errors',not errors)
    browser.close()
finally:
  server.shutdown();server.server_close()
  (OUT/'report.json').write_text(json.dumps({'checks':results,'browser_errors':errors if 'errors' in locals() else [],'scope':'Real app components and browser; test-only SDK transport. No real calls, audio or OS camera/keyboard.'},indent=2))
print(str(len(results))+' browser checks passed')
