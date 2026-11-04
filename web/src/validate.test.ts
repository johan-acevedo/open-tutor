import { describe, expect, it } from 'vitest';
import { validateBoardFocus, validateBoardItem } from './validate';

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
    expect(validateBoardItem({ id: 'h1', kind: 'html', html: '<b>x</b>', height: 'tall' }).ok).toBe(false);
    expect(validateBoardItem({ id: 'h1', kind: 'html', html: '<b>x</b>', height: 420 }).ok).toBe(true);
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
