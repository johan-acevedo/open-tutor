import { describe, expect, it } from 'vitest';
import type { DiagramItem } from './protocol';
import { buildScene, diagramText, sceneBounds, toSkeletons, wrapLabel, linkElementId, nodeElementId } from './diagramModel';

// Ten pixels per character: wide enough to wrap, simple enough to compute by hand.
const measure = (text: string, px: number) => text.length * (px / 2);

const item = (patch: Partial<DiagramItem> = {}): DiagramItem => ({
  id: 'b1',
  kind: 'diagram',
  title: 'Klimat',
  rev: 1,
  layout: 'radial',
  nodes: [
    { id: 'k', text: 'Klimat', role: 'center', x: 0, y: 0 },
    { id: 'a', text: 'Växthusgaser', role: 'idea', x: 400, y: 0 },
    { id: 'b', text: 'Smältande is och stigande hav', role: 'idea', x: -400, y: 0 },
  ],
  links: [
    { id: 'l1', source: 'k', target: 'a', label: 'orsakas av' },
    { id: 'l2', source: 'k', target: 'b' },
  ],
  focus: [],
  ...patch,
});

describe('wrapLabel', () => {
  it('wraps at word boundaries and keeps every word', () => {
    const lines = wrapLabel('Smältande is och stigande hav', 210, 20, measure);
    expect(lines.length).toBeGreaterThan(1);
    expect(lines.join(' ')).toBe('Smältande is och stigande hav');
    expect(Math.max(...lines.map((l) => measure(l, 20)))).toBeLessThanOrEqual(210);
  });
  it('splits a single word that is wider than the box', () => {
    const lines = wrapLabel('Fotosyntesprocessen', 100, 20, measure);
    expect(lines.length).toBeGreaterThan(1);
    expect(lines.join('')).toBe('Fotosyntesprocessen');
  });
});

describe('buildScene', () => {
  it('centres every box on its node and keeps Swedish text intact', () => {
    const scene = buildScene(item(), measure);
    for (const n of item().nodes) {
      const box = scene.nodes.find((b) => b.id === n.id)!;
      expect(box.x + box.w / 2).toBeCloseTo(n.x, 0);
      expect(box.y + box.h / 2).toBeCloseTo(n.y, 0);
      expect(box.lines.join(' ')).toBe(n.text);
    }
  });

  it('cuts each arrow at the box edges, with a small gap, pointing from source to target', () => {
    const scene = buildScene(item(), measure);
    const k = scene.nodes.find((n) => n.id === 'k')!;
    const a = scene.nodes.find((n) => n.id === 'a')!;
    const arrow = scene.arrows.find((r) => r.id === 'l1')!;
    const start = arrow.x;
    const end = arrow.x + arrow.points[1][0];
    expect(start).toBe(k.x + k.w + 6); // leaves the right edge of k
    expect(end).toBe(a.x - 6); // stops before the left edge of a
    expect(arrow.points[1][1]).toBe(0); // horizontal: same y
    expect(arrow.headed).toBe(false); // mind-map connectors have no head
  });

  it('draws flow arrows with a head', () => {
    expect(buildScene(item({ layout: 'flow' }), measure).arrows.every((a) => a.headed)).toBe(true);
  });

  it('rebuilds from the model: an edit changes the box and arrow, a removal leaves nothing behind', () => {
    const before = buildScene(item(), measure);
    const edited = item();
    edited.nodes[1] = { ...edited.nodes[1], text: 'Växthusgaser från trafik och industri' };
    const after = buildScene(edited, measure);
    const boxBefore = before.nodes.find((n) => n.id === 'a')!;
    const boxAfter = after.nodes.find((n) => n.id === 'a')!;
    expect(boxAfter.h).toBeGreaterThan(boxBefore.h);
    const arrowBefore = before.arrows.find((r) => r.id === 'l1')!;
    const arrowAfter = after.arrows.find((r) => r.id === 'l1')!;
    expect(arrowAfter.x + arrowAfter.points[1][0]).toBeLessThan(arrowBefore.x + arrowBefore.points[1][0]); // box grew leftwards

    const removed = buildScene(
      item({ nodes: item().nodes.filter((n) => n.id !== 'a'), links: item().links.filter((l) => l.id !== 'l1') }),
      measure,
    );
    expect(removed.nodes.map((n) => n.id)).toEqual(['k', 'b']);
    expect(removed.arrows.map((a) => a.id)).toEqual(['l2']);
  });

  it('skips an arrow whose boxes touch instead of drawing a backwards one', () => {
    const touching = item({ nodes: [item().nodes[0], { ...item().nodes[1], x: 60, y: 0 }], links: [item().links[0]] });
    expect(buildScene(touching, measure).arrows).toEqual([]);
  });

  it('marks focused nodes and dims the rest; an arrow between two focused nodes is focused', () => {
    const scene = buildScene(item({ focus: ['k', 'a'] }), measure);
    expect(Object.fromEntries(scene.nodes.map((n) => [n.id, n.state]))).toEqual({ k: 'focus', a: 'focus', b: 'dim' });
    expect(Object.fromEntries(scene.arrows.map((a) => [a.id, a.state]))).toEqual({ l1: 'focus', l2: 'dim' });
    expect(buildScene(item({ focus: ['l2'] }), measure).arrows.map((a) => a.state)).toEqual(['dim', 'focus']);
    expect(buildScene(item(), measure).nodes.every((n) => n.state === 'normal')).toBe(true);
  });

  it('reports bounds that contain every box', () => {
    const scene = buildScene(item(), measure);
    const bounds = sceneBounds(scene);
    for (const n of scene.nodes) {
      expect(n.x).toBeGreaterThanOrEqual(bounds.x);
      expect(n.x + n.w).toBeLessThanOrEqual(bounds.x + bounds.w);
    }
  });
});

describe('toSkeletons', () => {
  it('gives every element a stable id from the model id, explicit geometry and the palette', () => {
    const skeletons = toSkeletons(buildScene(item({ focus: ['a'] }), measure)) as Array<Record<string, any>>;
    const ids = skeletons.map((s) => s.id);
    expect(ids).toEqual([nodeElementId('k'), nodeElementId('a'), nodeElementId('b'), linkElementId('l1'), linkElementId('l2')]);
    const focused = skeletons.find((s) => s.id === nodeElementId('a'))!;
    expect(focused.strokeColor).toBe('#22D3EE');
    expect(focused.strokeWidth).toBe(4);
    const dimmed = skeletons.find((s) => s.id === nodeElementId('b'))!;
    expect(dimmed.opacity).toBe(45);
    expect(dimmed.roughness).toBe(0);
    const arrow = skeletons.find((s) => s.id === linkElementId('l1'))!;
    expect(arrow.points).toHaveLength(2);
    expect(arrow.label.text).toBe('orsakas av');
    expect(arrow.start).toBeUndefined(); // no bindings: the geometry is ours
    expect(skeletons.find((s) => s.id === linkElementId('l2'))!.label).toBeUndefined();
  });
});

describe('diagramText', () => {
  it('lists every connection, unconnected nodes and the current highlight, in Swedish', () => {
    const text = diagramText(
      item({ nodes: [...item().nodes, { id: 'c', text: 'Ensam', role: 'note', x: 0, y: 300 }], focus: ['a'] }),
    );
    expect(text.summary).toBe('Tankekarta om Klimat: 4 rutor och 2 pilar.');
    expect(text.lines).toEqual([
      'Klimat → Växthusgaser (orsakas av)',
      'Klimat → Smältande is och stigande hav',
      'Ensam (inte kopplad)',
      'Markerat just nu: Växthusgaser',
    ]);
  });
  it('names a flow and pluralises one box', () => {
    const text = diagramText(item({ layout: 'flow', title: undefined, nodes: [item().nodes[0]], links: [] }));
    expect(text.summary).toBe('Flödesschema: 1 ruta och 0 pilar.');
  });
});
