import { describe, expect, it } from 'vitest';
import { validateBoardFocus, validateBoardItem, validateBoardLoading, validateBoardPageOp } from './validate';

describe('validateBoardItem', () => {
  it('accepts a minimal homework item', () => {
    const r = validateBoardItem({ id: 'h1', kind: 'homework', title: 'matte.jpg' });
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.item.kind).toBe('homework');
  });

  it('rejects unknown kinds with an error', () => {
    const r = validateBoardItem({ id: 'a1', kind: 'tictactoe', board: [] });
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.error).toMatch(/unknown board kind/i);
  });

  it('rejects the retired board kinds', () => {
    // 2026-11-18: nothing produces these any more; they are not accepted on the wire either.
    for (const kind of ['text', 'steps', 'mindmap', 'svg', 'html', 'material']) {
      const r = validateBoardItem({ id: 'x1', kind, title: 'x' });
      expect(r.ok).toBe(false);
    }
  });

  it('rejects missing id', () => {
    expect(validateBoardItem({ kind: 'homework', title: 'x' }).ok).toBe(false);
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

  it('accepts pending with its placeholder height', () => {
    expect(validateBoardItem({ id: 'p1', kind: 'pending', title: 'Ritar…' }).ok).toBe(true);
    const sized = validateBoardItem({ id: 'p1', kind: 'pending', title: 'Ritar…', height: 360 });
    expect(sized.ok).toBe(true);
    if (sized.ok) expect(sized.item).toEqual({ id: 'p1', kind: 'pending', title: 'Ritar…', height: 360 });
    expect(validateBoardItem({ id: 'p1', kind: 'pending', title: 'Ritar…', height: 'tall' }).ok).toBe(false);
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

describe('validateBoardLoading', () => {
  it('accepts a topic and an empty topic that clears', () => {
    expect(validateBoardLoading({ id: 'p1', topic: 'historia' })).toEqual({
      ok: true,
      id: 'p1',
      topic: 'historia',
    });
    expect(validateBoardLoading({ id: 'p1', topic: '' }).ok).toBe(true);
  });

  it('rejects bad shapes', () => {
    expect(validateBoardLoading({ id: 'p1' }).ok).toBe(false);
    expect(validateBoardLoading({ id: 'p1', topic: 42 }).ok).toBe(false);
    expect(validateBoardLoading({ id: '', topic: 'historia' }).ok).toBe(false);
    expect(validateBoardLoading({ id: 'p1', topic: 'x'.repeat(121) }).ok).toBe(false);
    expect(validateBoardLoading(null).ok).toBe(false);
  });
});

describe('validateBoardFocus', () => {
  it('accepts an id', () => {
    expect(validateBoardFocus({ id: 'p1' })).toEqual({ ok: true, focus: { id: 'p1' } });
  });

  it('rejects bad shapes', () => {
    expect(validateBoardFocus({}).ok).toBe(false);
    expect(validateBoardFocus({ id: '' }).ok).toBe(false);
    expect(validateBoardFocus(null).ok).toBe(false);
  });
});
