"""Real built app + local LiveKit + synthetic audio. No cloud/providers/hardware.
Run after npm run build, passing a local LiveKit server executable:
uv run --project server --with playwright python web/e2e/livekit_probe.py --server PATH
"""
import argparse, asyncio, array, contextlib, functools, http.server, json, math, pathlib, subprocess, threading, time, urllib.request
from livekit import api, rtc
from playwright.sync_api import sync_playwright

ROOT=pathlib.Path(__file__).resolve().parents[2]
OUT=ROOT/'.review-checks/mobile-livekit';OUT.mkdir(parents=True,exist_ok=True)
args=argparse.ArgumentParser();args.add_argument('--server',required=True);opts=args.parse_args()
KEY='devkey';SECRET='secret';ROOM='mobile-local-probe';URL='ws://127.0.0.1:18810'
def token(identity):
    return api.AccessToken(KEY,SECRET).with_identity(identity).with_grants(api.VideoGrants(room_join=True,room=ROOM)).to_jwt()
class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self,*_):pass
    def do_POST(self):
        self.rfile.read(int(self.headers.get('content-length','0')))
        body=json.dumps({'url':URL,'token':token('fictional-browser'),'room':ROOM}).encode()
        self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(body)

loop=asyncio.new_event_loop()
threading.Thread(target=loop.run_forever,daemon=True).start()
def run(coro):return asyncio.run_coroutine_threadsafe(coro,loop).result(timeout=20)
remote=rtc.Room(loop=loop)
async def connect():await remote.connect(URL,token('fictional-tutor'))
async def end_room():
    client=api.LiveKitAPI('http://127.0.0.1:18810',KEY,SECRET)
    try:await client.room.delete_room(api.DeleteRoomRequest(room=ROOM))
    finally:await client.aclose()
async def board(method,payload):
    return await remote.local_participant.perform_rpc(destination_identity='fictional-browser',method=method,payload=json.dumps(payload),response_timeout=10)
async def audio():
    source=rtc.AudioSource(48000,1)
    track=rtc.LocalAudioTrack.create_audio_track('synthetic-tone',source)
    publication=await remote.local_participant.publish_track(track,rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE))
    await remote.local_participant.set_attributes({'lk.agent.state':'speaking'})
    await remote.local_participant.send_text('Precis. Vi tar bort fem på båda sidor.',topic='lk.transcription')
    for frame_index in range(100):
        frame=rtc.AudioFrame.create(48000,1,960)
        samples=array.array('h',(int(1500*math.sin((frame_index*960+i)*2*math.pi*440/48000)) for i in range(960)))
        frame.data[:]=samples
        await source.capture_frame(frame)
    await source.wait_for_playout()
    await remote.local_participant.unpublish_track(publication.sid)
    await source.aclose()

report={}
log=(OUT/'server.log').open('wb')
server=subprocess.Popen([opts.server,'--dev','--bind','127.0.0.1','--port','18810'],stdout=log,stderr=subprocess.STDOUT)
http=http.server.ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Handler,directory=str(ROOT/'web/dist')))
threading.Thread(target=http.serve_forever,daemon=True).start()
try:
    # Bounded readiness check for the process just started (not repository/CI polling).
    for _ in range(50):
        try:urllib.request.urlopen('http://127.0.0.1:18810',timeout=.2);break
        except Exception:time.sleep(.1)
    run(connect())
    with sync_playwright() as p:
        cached=sorted(pathlib.Path.home().glob('.cache/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell'))
        browser=p.chromium.launch(executable_path=str(cached[-1]) if cached else None,args=['--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream'])
        context=browser.new_context(viewport={'width':390,'height':844},is_mobile=True,has_touch=True,permissions=['microphone'])
        page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        page.add_init_script('''window.probeContexts=[];window.probePeers=[];
          const AC=window.AudioContext;window.AudioContext=class extends AC{constructor(...args){super(...args);window.probeContexts.push(this)}};
          const PC=window.RTCPeerConnection;window.RTCPeerConnection=class extends PC{constructor(...args){super(...args);window.probePeers.push(this)}};''')
        page.goto('http://127.0.0.1:'+str(http.server_port))
        page.get_by_label('Förnamn',exact=True).fill('Leo')
        page.get_by_role('button',name='Starta',exact=True).click()
        page.locator('.ot-mic-btn.live').wait_for(timeout=15000)
        report['board_ack']=run(board('board.show',{'id':'live-equation','kind':'steps','title':'Ekvationer','steps':[{'tex':'3x+5=20'},{'tex':'3x=15','op':'-5'}]}))
        report['focus_ack']=run(board('board.focus',{'id':'live-equation','step':1}))
        future=asyncio.run_coroutine_threadsafe(audio(),loop)
        page.wait_for_function("probeContexts.some(c=>c.state==='running') && document.querySelector('audio').srcObject?.getAudioTracks().length>0",timeout=15000)
        page.wait_for_timeout(900)
        report['audio']=page.evaluate('''async()=>{
          let inbound=0;for(const pc of probePeers){const stats=await pc.getStats();stats.forEach(s=>{if(s.type==='inbound-rtp'&&s.kind==='audio')inbound+=s.bytesReceived||0})}
          const mic=probePeers.flatMap(pc=>pc.getSenders()).find(s=>s.track?.kind==='audio')?.track?.getSettings();
          return {contexts:probeContexts.map(c=>c.state),inboundAudioBytes:inbound,mic};
        }''')
        future.result(timeout=15)
        page.screenshot(path=str(OUT/'actual-sdk-call.png'))
        page.get_by_role('button',name='Stäng av mikrofonen',exact=True).click()
        # Real visibility lifecycle event, with deliberately muted microphone.
        page.evaluate("Object.defineProperty(document,'hidden',{configurable:true,value:true});document.dispatchEvent(new Event('visibilitychange'));Object.defineProperty(document,'hidden',{configurable:true,value:false});document.dispatchEvent(new Event('visibilitychange'))")
        page.get_by_role('button',name='Fortsätt samtalet',exact=True).click()
        report['muted_on_return']=page.get_by_role('button',name='Mikrofon av — sätt på mikrofonen',exact=True).is_visible()
        page.get_by_role('button',name='Avsluta',exact=True).click()
        page.get_by_role('button',name='Ja, avsluta',exact=True).click()
        run(remote.disconnect())
        run(end_room())
        page.get_by_text('Bra jobbat idag, Leo!',exact=True).wait_for(timeout=10000)
        report['contexts_after_end']=page.evaluate('probeContexts.map(c=>c.state)')
        report['browser_errors']=errors
        _board_ack=json.loads(report['board_ack'])
        assert _board_ack.get('ok') is True and _board_ack.get('board',{}).get('w',0)>=1 and report['focus_ack']=='{"ok":true}'
        assert report['audio']['inboundAudioBytes']>0 and report['muted_on_return']
        assert all(x=='closed' for x in report['contexts_after_end']) and not errors
        browser.close()
finally:
    with contextlib.suppress(Exception):
        if remote.isconnected():run(remote.disconnect())
    server.terminate()
    try:server.wait(timeout=5)
    except subprocess.TimeoutExpired:server.kill();server.wait(timeout=5)
    log.close();http.shutdown();http.server_close();loop.call_soon_threadsafe(loop.stop)
    (OUT/'report.json').write_text(json.dumps(report,indent=2))
print('Real local LiveKit probe passed: board, focus, incoming audio, muted resume, cleanup')
