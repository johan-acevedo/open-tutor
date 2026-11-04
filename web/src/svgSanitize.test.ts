import { describe, expect, it } from 'vitest';
import { sanitiseSvg } from './svgSanitize';

describe('sanitiseSvg', () => {
  it('removes script elements', () => {
    const out = sanitiseSvg('<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script><circle r="5"/></svg>');
    expect(out).not.toContain('<script');
    expect(out).toContain('<circle');
  });

  it('removes foreignObject and event handler attributes', () => {
    const out = sanitiseSvg(
      '<svg xmlns="http://www.w3.org/2000/svg"><g onload="alert(1)" onclick="x"><foreignObject><div>hi</div></foreignObject><rect onmouseover="y" width="10"/></g></svg>',
    );
    expect(out.toLowerCase()).not.toContain('foreignobject');
    expect(out).not.toContain('onload');
    expect(out).not.toContain('onclick');
    expect(out).not.toContain('onmouseover');
  });

  it('drops javascript: hrefs', () => {
    const out = sanitiseSvg(
      '<svg xmlns="http://www.w3.org/2000/svg"><a href="javascript:alert(1)"><text>x</text></a></svg>',
    );
    expect(out).not.toContain('javascript:');
  });

  it('rejects non-svg input', () => {
    expect(sanitiseSvg('<div>hej</div>')).toBe('');
    expect(sanitiseSvg('not xml at all <')).toBe('');
  });
});
