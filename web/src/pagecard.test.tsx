import { describe, expect, it, vi } from 'vitest';
import { cleanup, render } from '@testing-library/react';
import { afterEach } from 'vitest';
import PageCard, { type PageShellMessage } from './components/PageCard';
import type { BoardItem } from './protocol';

afterEach(() => cleanup());

const noop = vi.fn();

function pageItem(id = 'p1'): Extract<BoardItem, { kind: 'page' }> {
  return { id, kind: 'page', title: 'Klockan', body: '<h1>Vad är klockan?</h1>' };
}

function renderPage(id = 'p1') {
  const sends = new Map<string, (msg: PageShellMessage) => void>();
  const onAnswer = vi.fn();
  const utils = render(
    <PageCard
      item={pageItem(id)}
      onMounted={noop}
      registerSend={(pid, send) => {
        if (send) sends.set(pid, send);
        else sends.delete(pid);
      }}
      onAnswer={onAnswer}
    />,
  );
  const frame = utils.container.querySelector('iframe.ot-page-frame') as HTMLIFrameElement;
  return { ...utils, sends, onAnswer, frame };
}

function messageFrom(source: unknown, data: unknown) {
  window.dispatchEvent(new MessageEvent('message', { source: source as WindowProxy, data }));
}

describe('PageCard', () => {
  it('frames the body sandboxed with the shell policy', () => {
    const { frame } = renderPage();
    expect(frame).toBeTruthy();
    expect(frame.getAttribute('sandbox')).toBe('allow-scripts');
    expect(frame.title).toBe('Klockan');
    const doc = new DOMParser().parseFromString(frame.srcdoc, 'text/html');
    const source = doc.querySelector<HTMLTemplateElement>('#ot-source');
    expect(source?.content.textContent).toBe('<h1>Vad är klockan?</h1>');
    expect(doc.querySelector('#page h1')).toBeNull();
    expect(frame.srcdoc).toContain('connect-src https://cdn.jsdelivr.net https://commons.wikimedia.org');
  });

  it('holds patch/reveal/point until the shell reports ready, then delivers', () => {
    const { sends, frame } = renderPage();
    const post = vi.fn();
    Object.defineProperty(frame, 'contentWindow', { value: { postMessage: post }, configurable: true });
    const send = sends.get('p1');
    expect(send).toBeTruthy();
    send!({ ot: 'patch', html: '<ot-patch target=\"a\"/>' });
    send!({ ot: 'reveal', id: 'val' });
    send!({ ot: 'point', id: 'klocka' });
    expect(post).not.toHaveBeenCalled();
    messageFrom(frame.contentWindow, { ot: 'ready', fontPx: 20, issues: [] });
    expect(post).toHaveBeenCalledTimes(3);
    expect(post).toHaveBeenNthCalledWith(1, { ot: 'patch', html: '<ot-patch target=\"a\"/>' }, '*');
    expect(post).toHaveBeenNthCalledWith(2, { ot: 'reveal', id: 'val' }, '*');
    expect(post).toHaveBeenNthCalledWith(3, { ot: 'point', id: 'klocka' }, '*');
    // After ready, messages pass straight through.
    send!({ ot: 'point', id: null });
    expect(post).toHaveBeenCalledTimes(4);
  });

  it('turns a shell answer into a page answer', () => {
    const { onAnswer, frame } = renderPage();
    messageFrom(frame.contentWindow, { ot: 'answer', id: 'val', value: 'kvart i åtta' });
    expect(onAnswer).toHaveBeenCalledTimes(1);
    expect(onAnswer).toHaveBeenCalledWith({
      page: 'p1',
      part: 'val',
      value: 'kvart i åtta',
      kind: 'answer',
    });
  });

  it('ignores messages from a foreign window', () => {
    const { onAnswer, frame } = renderPage();
    messageFrom(window, { ot: 'ready', fontPx: 20, issues: [] });
    messageFrom(window, { ot: 'answer', id: 'val', value: 'x' });
    messageFrom(null, { ot: 'answer', id: 'val', value: 'x' });
    expect(onAnswer).not.toHaveBeenCalled();
    expect(frame.closest('article')?.classList.contains('is-ready')).toBe(false);
  });
});
