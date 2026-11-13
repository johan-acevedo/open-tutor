import asyncio,json,sys
from pathlib import Path
root=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(root/'server'),str(root/'screen/tools')]
from open_tutor.screen import Screen

async def main():
    out=Path(sys.argv[1]) if len(sys.argv)>1 else Path(__file__).parent/'merge-main';out.mkdir(parents=True,exist_ok=True)
    body=('<h1>Etikett och bild</h1><ot-graph id="g" x="-1 1" y="-1 2" axes="off">'
          '<ot-segment id="s" from="0 0" to="0 1">'+('Long label '*20)+'</ot-segment></ot-graph>'
          '<section id="picture"></section>')
    image_url='https://upload.wikimedia.org/wikipedia/commons/test/preview-merge.jpg'
    patch=('<ot-patch target="s"><ot-segment from="0 0" to="0 1">1</ot-segment></ot-patch>'
           '<ot-patch target="picture"><section><ot-image src="'+image_url+'" credit="Bild: Diliff, CC BY-SA 2.5, Wikimedia Commons" alt="Colosseum"></ot-image></section></ot-patch>')
    bitmap=(root/'screen/tests/fixtures/commons-images/colosseum.jpg').read_bytes()
    screen=Screen({},out);results=[]
    try:
        await screen.warmup()
        new_page=screen._browser.new_page
        async def inspected_page(**kwargs):
            page=await new_page(**kwargs)
            async def recorded_image(route):
                await asyncio.sleep(.2)
                await route.fulfill(status=200,content_type='image/jpeg',body=bitmap)
            await page.route(image_url,recorded_image)
            screenshot=page.screenshot
            async def inspected_shot(*args,**kw):
                state=await page.frames[1].evaluate("() => ({issues:ot.issues, image:[...document.querySelectorAll('ot-image img')].map(i=>({complete:i.complete,width:i.naturalWidth}))})")
                assert not state['issues'], state
                assert state['image'] and all(i['complete'] and i['width']>0 for i in state['image']),state
                results.append({'pane':kwargs['viewport'],**state})
                return await screenshot(*args,**kw)
            page.screenshot=inspected_shot
            return page
        screen._browser.new_page=inspected_page
        for w,h in [(370,610),(1000,700)]:
            shot,issues=await screen._default_render_page(body,patch,w,h)
            assert not issues,issues
            (out/f'patch-{w}x{h}.png').write_bytes(shot)
        (out/'results.json').write_text(json.dumps(results,indent=2))
        print(json.dumps(results))
    finally:
        await screen.aclose()
asyncio.run(main())
