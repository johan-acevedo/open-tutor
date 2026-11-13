import { describe, expect, it } from 'vitest';
import { validateBoardFocus, validateBoardItem, validateBoardPageOp } from './validate';

describe('validateBoardItem', () => {
  it('accepts a minimal text item', () => {
    const r = validateBoardItem({ id: 'a1', kind: 'text', markdown: 'Hej **Leo**' });
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.item.kind).toBe('text');
  });

  it('rejects unknown kinds with an error', () => {
    const r = validateBoardItem({ id: 'a1', kind: 'tictactoe', board: [] });
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.error).toMatch(/unknown board kind/i);
  });

  it('rejects missing id', () => {
    expect(validateBoardItem({ kind: 'text', markdown: 'x' }).ok).toBe(false);
  });

  it('validates steps rows', () => {
    const good = validateBoardItem({
      id: 's1',
      kind: 'steps',
      steps: [
        { tex: '3x + 5 = 20', op: '−5' },
        { tex: '3x = 15', note: 'Vi tar bort 5 på båda sidor.' },
      ],
    });
    expect(good.ok).toBe(true);
    const bad = validateBoardItem({ id: 's1', kind: 'steps', steps: [{ note: 'saknar tex' }] });
    expect(bad.ok).toBe(false);
    const empty = validateBoardItem({ id: 's1', kind: 'steps', steps: [] });
    expect(empty.ok).toBe(false);
  });

  it('validates mindmap ideas', () => {
    expect(
      validateBoardItem({ id: 'm1', kind: 'mindmap', center: 'Boken', ideas: ['a', 'b'] }).ok,
    ).toBe(true);
    expect(validateBoardItem({ id: 'm1', kind: 'mindmap', center: 'Boken', ideas: [1, 2] }).ok).toBe(
      false,
    );
  });

  it('validates resource and image items', () => {
    expect(
      validateBoardItem({ id: 'r1', kind: 'resource', title: 'Video', url: 'https://x', embedUrl: 5 }).ok,
    ).toBe(false);
    expect(
      validateBoardItem({ id: 'r1', kind: 'resource', title: 'Video', url: 'https://x' }).ok,
    ).toBe(true);
    expect(validateBoardItem({ id: 'i1', kind: 'image', url: 'https://x/y.png' }).ok).toBe(false);
  });

  it('validates homework items', () => {
    expect(
      validateBoardItem({ id: 'h1', kind: 'homework', title: 'matte.jpg', images: ['data:image/jpeg;base64,x'] })
        .ok,
    ).toBe(true);
    expect(validateBoardItem({ id: 'h1', kind: 'homework', title: 42 }).ok).toBe(false);
  });

  it('accepts pending and html/sizes', () => {
    expect(validateBoardItem({ id: 'p1', kind: 'pending', title: 'Ritar…' }).ok).toBe(true);
    const sized = validateBoardItem({ id: 'p1', kind: 'pending', title: 'Ritar…', height: 360 });
    expect(sized.ok).toBe(true);
    if (sized.ok) expect(sized.item).toEqual({ id: 'p1', kind: 'pending', title: 'Ritar…', height: 360 });
    expect(validateBoardItem({ id: 'p1', kind: 'pending', title: 'Ritar…', height: 'tall' }).ok).toBe(false);
    expect(validateBoardItem({ id: 'h1', kind: 'html', html: '<b>x</b>', height: 'tall' }).ok).toBe(false);
    expect(validateBoardItem({ id: 'h1', kind: 'html', html: '<b>x</b>', height: 420 }).ok).toBe(true);
    expect(validateBoardItem({ id: 'h1', kind: 'html', html: '<b>x</b>', width: 'wide' }).ok).toBe(false);
    const sizedHtml = validateBoardItem({ id: 'h1', kind: 'html', html: '<b>x</b>', height: 420, width: 640 });
    expect(sizedHtml.ok).toBe(true);
    if (sizedHtml.ok) expect(sizedHtml.item).toEqual({ id: 'h1', kind: 'html', html: '<b>x</b>', height: 420, width: 640 });
    // Legacy boards without width still validate (fluid-width fit).
    expect(validateBoardItem({ id: 'h1', kind: 'html', html: '<b>x</b>' }).ok).toBe(true);
  });

  it('validates material section references', () => {
    const good = validateBoardItem({
      id: 'm1',
      kind: 'material',
      title: 'A simple circuit',
      section_id: 'sec-ecd16baf9e4fee44',
    });
    expect(good.ok).toBe(true);
    if (good.ok) {
      expect(good.item).toEqual({
        id: 'm1',
        kind: 'material',
        title: 'A simple circuit',
        section_id: 'sec-ecd16baf9e4fee44',
      });
    }
    // Not a catalogue ID: rejected, never turned into a URL.
    expect(
      validateBoardItem({ id: 'm1', kind: 'material', title: 'X', section_id: 'sec-xyz' }).ok,
    ).toBe(false);
    expect(
      validateBoardItem({
        id: 'm1',
        kind: 'material',
        title: 'X',
        section_id: 'https://evil.example/page.html',
      }).ok,
    ).toBe(false);
    // An agent-supplied URL is dropped: the item carries no URL at all.
    const withUrl = validateBoardItem({
      id: 'm1',
      kind: 'material',
      title: 'X',
      section_id: 'sec-ecd16baf9e4fee44',
      url: 'https://evil.example/page.html',
    });
    expect(withUrl.ok).toBe(true);
    if (withUrl.ok) expect('url' in withUrl.item).toBe(false);
    expect(validateBoardItem({ id: 'm1', kind: 'material', section_id: 'sec-ecd16baf9e4fee44' }).ok).toBe(
      false,
    );
  });
});

describe('validateBoardItem page kind', () => {
  it('accepts a page item with title and body', () => {
    const r = validateBoardItem({ id: 'p1', kind: 'page', title: 'Klockan', body: '<h1>Hej</h1>' });
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.item).toEqual({ id: 'p1', kind: 'page', title: 'Klockan', body: '<h1>Hej</h1>' });
  });

  it('rejects pages without title, without body or with too long a body', () => {
    expect(validateBoardItem({ id: 'p1', kind: 'page', body: 'x' }).ok).toBe(false);
    expect(validateBoardItem({ id: 'p1', kind: 'page', title: 'T', body: 42 }).ok).toBe(false);
    expect(validateBoardItem({ id: 'p1', kind: 'page', title: 'T', body: 'x'.repeat(20001) }).ok).toBe(
      false,
    );
    expect(validateBoardItem({ id: 'p1', kind: 'page', title: 'T', body: 'x'.repeat(20000) }).ok).toBe(
      true,
    );
  });
});

describe('validateBoardPageOp', () => {
  it('accepts patch and part payloads', () => {
    expect(validateBoardPageOp({ id: 'p1', patch: '<ot-patch/>' }, 'patch')).toEqual({
      ok: true,
      id: 'p1',
      arg: '<ot-patch/>',
    });
    expect(validateBoardPageOp({ id: 'p1', part: 'val' }, 'part')).toEqual({
      ok: true,
      id: 'p1',
      arg: 'val',
    });
  });

  it('rejects bad shapes', () => {
    expect(validateBoardPageOp({ id: 'p1' }, 'patch').ok).toBe(false);
    expect(validateBoardPageOp({ id: 'p1', part: 42 }, 'part').ok).toBe(false);
    expect(validateBoardPageOp({ id: '', patch: 'x' }, 'patch').ok).toBe(false);
    expect(validateBoardPageOp(null, 'patch').ok).toBe(false);
  });
});

describe('validateBoardFocus', () => {
  it('accepts id with optional step', () => {
    expect(validateBoardFocus({ id: 's1', step: 2 }).ok).toBe(true);
    expect(validateBoardFocus({ id: 's1' }).ok).toBe(true);
  });

  it('rejects bad shapes', () => {
    expect(validateBoardFocus({ step: 1 }).ok).toBe(false);
    expect(validateBoardFocus({ id: 's1', step: -1 }).ok).toBe(false);
    expect(validateBoardFocus({ id: 's1', step: 1.5 }).ok).toBe(false);
    expect(validateBoardFocus(null).ok).toBe(false);
  });
});
