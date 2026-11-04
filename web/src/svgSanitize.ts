// Sanitise tutor-provided SVG before inline rendering:
// drop script/foreignObject, on* attributes and javascript: hrefs.

const FORBIDDEN_TAGS = new Set(['script', 'foreignobject']);

function isDangerousHref(value: string): boolean {
  const v = value.trim().toLowerCase();
  return v.startsWith('javascript:') || v.startsWith('data:text/html');
}

function cleanElement(el: Element): void {
  // Remove event-handler attributes and dangerous links.
  for (const attr of [...el.attributes]) {
    const name = attr.name.toLowerCase();
    if (name.startsWith('on')) {
      el.removeAttribute(attr.name);
      continue;
    }
    if ((name === 'href' || name === 'xlink:href' || name.endsWith(':href')) && isDangerousHref(attr.value)) {
      el.removeAttribute(attr.name);
      continue;
    }
    if (name === 'style' && /javascript:|expression\s*\(/i.test(attr.value)) {
      el.removeAttribute(attr.name);
    }
  }
  for (const child of [...el.children]) {
    if (FORBIDDEN_TAGS.has(child.tagName.toLowerCase())) {
      child.remove();
    } else {
      cleanElement(child);
    }
  }
}

/** Return sanitised SVG markup, or '' if the input is not parseable SVG. */
export function sanitiseSvg(svg: string): string {
  let doc: Document;
  try {
    doc = new DOMParser().parseFromString(svg, 'image/svg+xml');
  } catch {
    return '';
  }
  if (doc.getElementsByTagName('parsererror').length > 0) return '';
  const root = doc.documentElement;
  if (!root || root.tagName.toLowerCase() !== 'svg') return '';
  cleanElement(root);
  try {
    return new XMLSerializer().serializeToString(root);
  } catch {
    return '';
  }
}
