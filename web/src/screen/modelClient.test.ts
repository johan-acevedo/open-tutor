import { describe, expect, it, vi } from 'vitest';
import { postScreenChat, SCREEN_CHAT_PATH } from './modelClient';

describe('postScreenChat', () => {
  it('posts to the same-origin gateway with the model pinned', async () => {
    const fetchFn = vi.fn(async () => new Response('{}', { status: 200 }));
    await postScreenChat({
      room: 'tutor-abc123',
      accessCode: 'kod',
      body: { messages: [{ role: 'user', content: 'hej' }] },
      fetchFn: fetchFn as unknown as typeof fetch,
    });
    expect(fetchFn).toHaveBeenCalledTimes(1);
    const [url, init] = fetchFn.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe(SCREEN_CHAT_PATH('tutor-abc123'));
    expect(init.method).toBe('POST');
    expect((init.headers as Record<string, string>)['x-tutor-code']).toBe('kod');
    expect(JSON.parse(init.body as string).model).toBe('deepseek-v4.1-flash');
  });

  it('works with an empty access code in public Swedish mode (same-origin, no credential)', async () => {
    const fetchFn = vi.fn(async () => new Response('{}', { status: 200 }));
    await postScreenChat({
      room: 'tutor-abc123',
      accessCode: '',
      body: { messages: [{ role: 'user', content: 'hej' }] },
      fetchFn: fetchFn as unknown as typeof fetch,
    });
    const [, init] = fetchFn.mock.calls[0] as unknown as [string, RequestInit];
    expect((init.headers as Record<string, string>)['x-tutor-code']).toBe('');
  });
});
