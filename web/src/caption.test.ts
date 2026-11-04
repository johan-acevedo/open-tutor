import { describe, expect, it } from 'vitest';
import { captionTail } from './useSession';

describe('captionTail', () => {
  it('keeps short captions whole and strips markup', () => {
    expect(captionTail('Vi har **$3x + 5 = 20$**.')).toBe('Vi har 3x + 5 = 20.');
  });
  it('shows the latest sentences of a long reply', () => {
    const long = 'Första meningen är ganska lång och handlar om något annat helt och hållet. '.repeat(3) + 'Nu tar vi bort fem på båda sidor.';
    const tail = captionTail(long);
    expect(tail.endsWith('Nu tar vi bort fem på båda sidor.')).toBe(true);
    expect(tail.length).toBeLessThanOrEqual(140);
  });
});
