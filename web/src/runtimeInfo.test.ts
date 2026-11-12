import { describe, expect, it } from 'vitest';
import { buildScreenSection, parseRuntimeInfo } from './runtimeInfo';
import { SCREEN_MODEL_ID, SCREEN_THINKING_LEVEL } from './screen/screenConfig';

describe('parseRuntimeInfo', () => {
  it('accepts a well-formed worker payload', () => {
    const parsed = parseRuntimeInfo({
      version: 1,
      sections: [
        { title: 'Språkmodell', fields: [{ label: 'Modell', value: 'muse-spark-1.3-contributor' }] },
      ],
    });
    expect(parsed?.sections).toHaveLength(1);
    expect(parsed?.sections[0].fields[0]).toEqual({
      label: 'Modell',
      value: 'muse-spark-1.3-contributor',
    });
  });

  it('rejects wrong versions, missing titles and non-string values', () => {
    expect(parseRuntimeInfo({ version: 2, sections: [] })).toBeNull();
    expect(parseRuntimeInfo({ version: 1, sections: [] })).toBeNull();
    expect(parseRuntimeInfo(null)).toBeNull();
    expect(parseRuntimeInfo('tutor.runtime')).toBeNull();
    expect(
      parseRuntimeInfo({ version: 1, sections: [{ fields: [{ label: 'A', value: 'b' }] }] }),
    ).toBeNull();
    expect(
      parseRuntimeInfo({ version: 1, sections: [{ title: 'T', fields: [{ label: 'A', value: 7 }] }] }),
    ).toBeNull();
    expect(
      parseRuntimeInfo({ version: 1, sections: [{ title: 'T', fields: [] }] }),
    ).toBeNull();
  });

  it('rejects oversized payloads instead of rendering them', () => {
    expect(
      parseRuntimeInfo({
        version: 1,
        sections: [{ title: 'T', fields: [{ label: 'A', value: 'x'.repeat(501) }] }],
      }),
    ).toBeNull();
    const many = Array.from({ length: 13 }, (_, i) => ({
      title: `S${i}`,
      fields: [{ label: 'A', value: 'b' }],
    }));
    expect(parseRuntimeInfo({ version: 1, sections: many })).toBeNull();
  });

  it('tolerates malformed JSON at the caller, not here', () => {
    // The hook wraps JSON.parse; the parser only sees already-parsed values.
    expect(parseRuntimeInfo({ version: 1, sections: 'nope' })).toBeNull();
  });
});

describe('buildScreenSection', () => {
  it('reports the centralized Screen model and reasoning level', () => {
    const section = buildScreenSection();
    const byLabel = new Map(section.fields.map((field) => [field.label, field.value]));
    expect(byLabel.get('Modell')).toBe(SCREEN_MODEL_ID);
    expect(byLabel.get('Modell')).toBe('deepseek-v4.1-flash');
    expect(byLabel.get('Resonemang')).toBe(SCREEN_THINKING_LEVEL);
    expect(byLabel.get('SDK')).toMatch(/livekit-client \d+\.\d+/);
    expect(byLabel.get('SDK')).toMatch(/pi-ai \d+\.\d+/);
    expect(byLabel.get('Webbapp')).toBe(window.location.origin);
  });
});
