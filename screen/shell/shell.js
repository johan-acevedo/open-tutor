/* Open Tutor screen shell.
 *
 * The screen model writes only a page body. This script turns that body into a
 * finished page: it loads the libraries the page needs, renders maths, builds the
 * ot-* components, picks the largest root font size at which the page fits the
 * pane without scrolling, draws the visuals at their final size and only then
 * shows the page. Afterwards it applies patches, reveals and pointing sent by the
 * parent window, and reports answers back.
 *
 * Parent -> frame (postMessage):  {ot:'patch', html}  {ot:'point', id|null}
 *                                  {ot:'reveal', id}   {ot:'restore', state}
 *                                  {ot:'hello'}         (the frame posts its ready message again:
 *                                    at once when it is already ready, otherwise when it becomes ready)
 * Frame -> parent:                 {ot:'ready', fontPx, issues, w, h}
 *                                  {ot:'patched', issues}   (only issues new since the previous
 *                                    ready/patched report; also posted at once when point/reveal
 *                                    name an id that does not exist)
 *                                  {ot:'answer', id, value}   (child pressed Skicka / chose)
 *                                  {ot:'input', id, value}    (draft text, for keeping state)
 * The same calls exist as window.ot.patch / point / reveal / restore.
 */
(function () {
  'use strict';

  var CDN = 'https://cdn.jsdelivr.net/';
  var LIBS = {
    katex: { css: [CDN + 'npm/katex@0.19.1/dist/katex.min.css'],
             js: [CDN + 'npm/katex@0.19.1/dist/katex.min.js', CDN + 'npm/katex@0.19.1/dist/contrib/auto-render.min.js'] },
    jsxgraph: { css: [CDN + 'npm/jsxgraph@1.14.1/distrib/jsxgraph.css'], js: [CDN + 'npm/jsxgraph@1.14.1/distrib/jsxgraphcore.js'] },
    chart: { js: [CDN + 'npm/chart.js@4.6.1/dist/chart.umd.min.js'] },
    d3: { js: [CDN + 'npm/d3@7.9.0/dist/d3.min.js'] },
    purify: { js: [CDN + 'npm/dompurify@3.4.17/dist/purify.min.js'] }
  };
  var DATA = {
    countries: CDN + 'gh/nvkelso/natural-earth-vector@ca96624a56bd078437bca8184e78163e5039ad19/geojson/ne_50m_admin_0_countries.geojson',
    history: CDN + 'gh/aourednik/historical-basemaps@4b5039e50d8d2464b065bd76ad6086cd4597108d/geojson/'
  };
  var HISTORY_YEARS = [-123000, -10000, -8000, -5000, -4000, -3000, -2000, -1500, -1000, -700, -500, -400, -323, -300, -200, -100, -1,
    100, 200, 300, 400, 500, 600, 700, 800, 900, 1000, 1100, 1200, 1279, 1300, 1400, 1492, 1500, 1530, 1600, 1650, 1700, 1715,
    1783, 1800, 1815, 1878, 1880, 1900, 1914, 1920, 1930, 1938, 1945, 1960, 1994, 2000, 2010];

  var ot = window.ot = { issues: [], ready: null, fontPx: 0 };
  var booted = false;
  var page = null;
  var MIN_FONT = 11, SMALL_FONT = 14;

  // ---------------------------------------------------------------- helpers
  function $$(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }
  function css(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function describe(el) {
    if (!el || !el.tagName) return '';
    return '<' + el.tagName.toLowerCase() + (el.id ? ' id="' + el.id + '"' : '') + '>';
  }
  function issue(kind, msg, el) {
    var item = { kind: kind, msg: msg };
    if (el) item.where = describe(el);
    // the same problem is only reported once, however often it re-triggers
    var dup = ot.issues.some(function (i) { return i.kind === item.kind && i.msg === item.msg && i.where === item.where; });
    if (!dup) ot.issues.push(item);
    return item;
  }
  // Issues since the previous ready/patched report; posts them as {ot:'patched', issues}.
  // force makes sure one issue is included even when it was already reported before.
  var reported = 0;
  function flushPatched(force) {
    var fresh = ot.issues.slice(reported);
    reported = ot.issues.length;
    if (force && !fresh.length) fresh = [force];
    var msg = { ot: 'patched', issues: fresh };
    post(msg);
    return fresh;
  }
  function post(msg) {
    try { if (window.parent && window.parent !== window) window.parent.postMessage(msg, '*'); } catch (e) { /* detached */ }
  }
  function fontPx() { return parseFloat(getComputedStyle(document.documentElement).fontSize) || 16; }
  function reducedMotion() { return window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches; }
  function timeout(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }
  function withTimeout(p, ms) { return Promise.race([p, timeout(ms)]); }

  var COLORS = { cyan: '--cyan', violet: '--violet', green: '--green', amber: '--amber', pink: '--pink', red: '--red',
                 white: '--text', text: '--text', muted: '--muted', gray: '--muted', grey: '--muted' };
  var SERIES = ['cyan', 'violet', 'amber', 'green', 'pink'];
  function color(name, fallback) {
    name = (name || '').trim();
    if (!name) return css(COLORS[fallback || 'cyan']);
    if (COLORS[name]) return css(COLORS[name]);
    // This value also enters SVG attributes. Do not let a colour become markup.
    return /^[#a-z0-9(),.% /+-]+$/i.test(name) && CSS.supports('color', name) ? name : css(COLORS[fallback || 'cyan']);
  }
  function alpha(hex, a) {
    var m = /^#([0-9a-f]{6})$/i.exec(hex);
    if (!m) return hex;
    var n = parseInt(m[1], 16);
    return 'rgba(' + (n >> 16) + ',' + ((n >> 8) & 255) + ',' + (n & 255) + ',' + a + ')';
  }

  // Swedish numbers: decimal comma, true minus, space between thousands from 10 000.
  function num(s) {
    if (s == null) return NaN;
    if (typeof s === 'number') return s;
    s = String(s).trim().replace(/−/g, '-').replace(/\s/g, '');
    var f = /^(-?\d+)\/(\d+)$/.exec(s);
    if (f) return Number(f[1]) / Number(f[2]);
    return Number(s.replace(',', '.'));
  }
  function nums(s) {
    if (!s) return [];
    var out = String(s).replace(/[()]/g, ' ').replace(/−/g, '-').split(/[\s;]+|,\s+|,(?=-?\d+,)/);
    return out.filter(function (t) { return t !== ''; }).map(num).filter(function (n) { return !isNaN(n); });
  }
  function points(s) { var a = nums(s), out = []; for (var i = 0; i + 1 < a.length; i += 2) out.push([a[i], a[i + 1]]); return out; }
  function fmt(n, maxDec) {
    if (!isFinite(n)) return '';
    n = Math.round(n * 1e9) / 1e9;
    var s = new Intl.NumberFormat('sv-SE', { maximumFractionDigits: maxDec == null ? 6 : maxDec, useGrouping: Math.abs(n) >= 10000 }).format(n);
    return s.replace(/-/g, '−');
  }
  function frac(s) {
    var m = /^\s*(-?\d+)\s*\/\s*(\d+)\s*$/.exec(s || '');
    return m ? { n: Number(m[1]), d: Number(m[2]) } : null;
  }

  // ---------------------------------------------------------------- loading
  var loaded = {};
  function loadScript(url) {
    return new Promise(function (resolve, reject) {
      var s = document.createElement('script');
      s.src = url; s.async = false; s.crossOrigin = 'anonymous';
      s.onload = resolve; s.onerror = function () { reject(new Error('could not load ' + url)); };
      document.head.appendChild(s);
    });
  }
  function loadCss(url) {
    return new Promise(function (resolve) {
      var l = document.createElement('link');
      l.rel = 'stylesheet'; l.href = url; l.crossOrigin = 'anonymous';
      l.onload = resolve; l.onerror = function () { issue('load', 'could not load ' + url); resolve(); };
      document.head.appendChild(l);
    });
  }
  function lib(name) {
    if (loaded[name]) return loaded[name];
    var spec = LIBS[name];
    var styles = (spec.css || []).map(loadCss);
    var chain = (spec.js || []).reduce(function (p, url) { return p.then(function () { return loadScript(url); }); }, Promise.resolve());
    loaded[name] = Promise.all([chain].concat(styles)).catch(function (e) { issue('load', e.message); });
    return loaded[name];
  }
  var dataCache = {}, dataValue = {};
  function fetchJson(url) {
    if (!dataCache[url]) {
      dataCache[url] = fetch(url).then(function (r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      }).then(function (v) { dataValue[url] = v; return v; }).catch(function (e) { issue('load', 'could not load ' + url + ': ' + e.message); return null; });
    }
    return dataCache[url];
  }
  function needs(root) {
    var want = { katex: true };
    if (root.querySelector('ot-graph')) want.jsxgraph = true;
    if (root.querySelector('ot-chart')) want.chart = true;
    if (root.querySelector('ot-map')) want.d3 = true;
    return Object.keys(want);
  }

  // Parse model markup before connecting any of it to the live document.
  var UNSAFE_TAGS = ['script', 'style', 'link', 'meta', 'base', 'iframe', 'object', 'embed',
                     'template', 'foreignObject', 'animate', 'animateMotion', 'animateTransform', 'set', 'use'];
  function sanitizedFragment(html) {
    var fragment;
    if ('setHTML' in Element.prototype) {
      var host = document.createElement('div');
      host.setHTML(String(html || ''), { sanitizer: {
        removeElements: UNSAFE_TAGS,
        removeAttributes: ['style', 'is', 'srcdoc']
      } });
      fragment = document.createDocumentFragment();
      fragment.append.apply(fragment, Array.prototype.slice.call(host.childNodes));
    } else {
      if (!window.DOMPurify || !DOMPurify.isSupported) throw new Error('HTML sanitizer unavailable');
      fragment = DOMPurify.sanitize(String(html || ''), {
        RETURN_DOM_FRAGMENT: true,
        ADD_ATTR: ['correct', 'later'],
        FORBID_TAGS: UNSAFE_TAGS.map(function (tag) { return tag.toLowerCase(); }),
        FORBID_ATTR: ['style', 'is', 'srcdoc'],
        CUSTOM_ELEMENT_HANDLING: {
          tagNameCheck: /^ot-[a-z][a-z0-9-]*$/,
          attributeNameCheck: /^(?!on)[a-z][a-z0-9-]*$/i,
          allowCustomizedBuiltInElements: false
        }
      });
    }
    $$('*', fragment).forEach(function (el) {
      Array.prototype.slice.call(el.attributes).forEach(function (attribute) {
        var name = attribute.name.toLowerCase();
        if (name.indexOf('on') === 0) el.removeAttribute(attribute.name);
        if (['href', 'src', 'xlink:href', 'action', 'formaction'].indexOf(name) >= 0) {
          var value = attribute.value.replace(/[\u0000-\u0020]/g, '');
          if (!/^(https?:|data:image\/(png|jpeg|gif|webp|avif);|#|\/)/i.test(value)) el.removeAttribute(attribute.name);
        }
      });
    });
    return fragment;
  }

  // ---------------------------------------------------------------- maths
  // Decimal comma: "9,5" is one number; "(1, 3)" keeps its space.
  function fixTex(t) { return String(t).replace(/(\d),(?=\d)/g, '$1{,}').replace(/−/g, '-'); }
  function tex(t, display) {
    if (!window.katex) return esc(t);
    try {
      return katex.renderToString(fixTex(t), { displayMode: !!display, throwOnError: true, output: 'html', strict: false });
    } catch (e) {
      issue('math', 'KaTeX could not read: ' + t + ' (' + (e.message || e) + ')');
      return '<span class="ot-math-err">' + esc(t) + '</span>';
    }
  }
  // Text that may contain $...$: rendered as HTML with maths.
  function rich(s) {
    s = String(s || '');
    if (s.indexOf('$') < 0) return esc(s);
    var out = '', parts = s.split('$');
    for (var i = 0; i < parts.length; i++) out += (i % 2) ? tex(parts[i]) : esc(parts[i]);
    return out;
  }
  var MATH_SKIP = ['script', 'noscript', 'style', 'textarea', 'pre', 'code', 'option', 'input',
                   'ot-steps', 'ot-graph', 'ot-numberline', 'ot-map', 'ot-chart', 'ot-balance', 'ot-fraction', 'ot-written', 'ot-clock', 'ot-patch'];
  function renderMath(root) {
    if (!window.renderMathInElement || !root) return;
    renderMathInElement(root, {
      delimiters: [
        { left: '$$', right: '$$', display: true },
        { left: '\\[', right: '\\]', display: true },
        { left: '$', right: '$', display: false },
        { left: '\\(', right: '\\)', display: false }
      ],
      ignoredTags: MATH_SKIP,
      throwOnError: false,
      strict: false,
      output: 'html',
      preProcess: fixTex,
      errorCallback: function (msg, err) { issue('math', String(msg) + ' ' + (err && err.message || '')); }
    });
  }

  // ---------------------------------------------------------------- base element
  var REGISTRY = {};
  function define(tag, cls) { REGISTRY[tag] = cls; }

  function makeBase() {
    return class OtElement extends HTMLElement {
      connectedCallback() {
        if (!this._built) { this._built = true; if (this.build) this.build(); }
      }
    };
  }

  // A visual draws into a positioned layer once its box has its final size.
  function makeVisual(Base) {
    return class OtVisual extends Base {
      layer() {
        if (!this._layer || this._layer.parentNode !== this) {
          this._layer = document.createElement('div');
          this._layer.className = 'ot-vis';
          this.appendChild(this._layer);
        }
        return this._layer;
      }
      redraw() {
        var w = this.clientWidth, h = this.clientHeight;
        if (w < 2 || h < 2) return true;
        try { var r = this.draw(w, h, fontPx()); keepInside(this); return r; }
        catch (e) { issue('draw', (e && e.message) || String(e), this); return true; }
      }
    };
  }

  // Labels near the edge of a visual are moved back inside it instead of spilling over its neighbours.
  function keepInside(host) {
    var lay = host._layer;
    if (!lay) return;
    // A map with a key in flow keeps its labels inside the drawing box, not over the key.
    var box = (lay.querySelector(':scope > .ot-map-canvas') || lay).getBoundingClientRect();
    $$('.ot-lbl, .ot-place-label, .ot-map-label', lay).forEach(function (l) {
      if (l.classList.contains('ot-side-lbl')) return; // the graph pass already kept these clear without pushing them back across their edge
      var r = l.getBoundingClientRect();
      var dx = r.left < box.left ? box.left - r.left : r.right > box.right ? box.right - r.right : 0;
      var dy = r.top < box.top ? box.top - r.top : r.bottom > box.bottom ? box.bottom - r.bottom : 0;
      if (dx || dy) { l.style.left = (parseFloat(l.style.left) || 0) + dx + 'px'; l.style.top = (parseFloat(l.style.top) || 0) + dy + 'px'; }
    });
  }

  // SVG helpers
  function svg(w, h, inner) {
    return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ' + w + ' ' + h + '" width="' + w + '" height="' + h + '">' + inner + '</svg>';
  }
  function line(x1, y1, x2, y2, stroke, width, extra) {
    return '<line x1="' + x1 + '" y1="' + y1 + '" x2="' + x2 + '" y2="' + y2 + '" stroke="' + stroke + '" stroke-width="' + width + '" stroke-linecap="round" ' + (extra || '') + '/>';
  }
  function label(layer, x, y, html, cls, style) {
    var d = document.createElement('div');
    d.className = 'ot-lbl' + (cls ? ' ' + cls : '');
    d.style.left = x + 'px'; d.style.top = y + 'px';
    if (style) d.setAttribute('style', d.getAttribute('style') + ';' + style);
    d.innerHTML = html;
    layer.appendChild(d);
    return d;
  }

  // ---------------------------------------------------------------- components
  function defineAll() {
    var Base = makeBase();
    var Visual = makeVisual(Base);

    // Data tags: they only carry attributes and text for their parent component.
    ['ot-fn', 'ot-point', 'ot-segment', 'ot-polygon', 'ot-text', 'ot-mark', 'ot-jump', 'ot-item', 'ot-node',
     'ot-country', 'ot-region', 'ot-area', 'ot-place', 'ot-label', 'ot-patch'].forEach(function (t) {
      define(t, class extends Base {});
    });

    // ---- ot-hidden: an answer the tutor reveals. Space is reserved, so revealing moves nothing.
    define('ot-hidden', class extends Base {
      build() {
        var body = document.createElement('span');
        body.className = 'ot-hidden-body';
        while (this.firstChild) body.appendChild(this.firstChild);
        if (body.querySelector('div, p, ot-steps, ul, ol, table, .card, h2')) this.classList.add('block');
        var cover = document.createElement('span');
        cover.className = 'ot-cover';
        cover.textContent = this.getAttribute('label') || '?';
        this.append(body, cover);
      }
      reveal() { this.setAttribute('data-revealed', ''); return this.querySelector('.ot-hidden-body'); }
    });

    // ---- ot-answer: input + Skicka. What the child sends reaches the tutor.
    define('ot-answer', class extends Base {
      build() {
        var id = this.id || (this.id = autoId('svar'));
        var lab = this.getAttribute('label');
        var unit = this.getAttribute('unit');
        var input = document.createElement('input');
        input.className = 'ot-input' + (this.hasAttribute('wide') || this.getAttribute('kind') === 'text' ? ' wide' : '');
        input.id = id + '-input';
        input.type = 'text';
        input.autocomplete = 'off';
        input.spellcheck = false;
        if (this.getAttribute('kind') !== 'text') input.inputMode = 'decimal';
        input.placeholder = this.getAttribute('placeholder') || '';
        input.setAttribute('aria-label', lab || 'Ditt svar');
        var btn = document.createElement('button');
        btn.type = 'button'; btn.className = 'ot-send'; btn.textContent = 'Skicka';
        var self = this;
        function send() {
          var v = input.value.trim();
          if (!v) { input.focus(); return; }
          btn.textContent = 'Skickat ✓'; btn.setAttribute('data-sent', '');
          post({ ot: 'answer', id: id, value: v });
        }
        btn.addEventListener('click', send);
        input.addEventListener('keydown', function (e) { if (e.key === 'Enter') send(); });
        input.addEventListener('input', function () {
          btn.textContent = 'Skicka'; btn.removeAttribute('data-sent');
          draft(id, input.value);
        });
        this.textContent = '';
        if (lab) { var l = document.createElement('label'); l.htmlFor = input.id; l.innerHTML = rich(lab); this.appendChild(l); }
        this.appendChild(input);
        if (unit) { var u = document.createElement('span'); u.className = 'ot-unit'; u.textContent = unit; this.appendChild(u); }
        this.appendChild(btn);
        this._input = input;
        self._restore = function (v) { input.value = v; };
      }
    });

    // ---- ot-choice: buttons; a choice is sent to the tutor. reveal marks the button with `correct`.
    define('ot-choice', class extends Base {
      build() {
        var id = this.id || (this.id = autoId('val'));
        var self = this;
        $$(':scope > *', this).forEach(function (el, i) {
          var b = el;
          if (el.tagName !== 'BUTTON') {
            b = document.createElement('button');
            while (el.firstChild) b.appendChild(el.firstChild);
            Array.prototype.slice.call(el.attributes).forEach(function (a) { b.setAttribute(a.name, a.value); });
            el.replaceWith(b);
          }
          b.type = 'button';
          b.setAttribute('aria-pressed', 'false');
          b.dataset.value = b.getAttribute('value') || b.textContent.trim();
          b.addEventListener('click', function () {
            $$(':scope > button', self).forEach(function (o) { o.setAttribute('aria-pressed', String(o === b)); });
            post({ ot: 'answer', id: id, value: b.dataset.value, index: i });
            draft(id, String(i));
          });
        });
        this._restore = function (v) {
          $$(':scope > button', self).forEach(function (o, j) { o.setAttribute('aria-pressed', String(String(j) === String(v))); });
        };
      }
      reveal() { this.setAttribute('data-revealed', ''); return this.querySelector('button[correct]') || this; }
    });

    // ---- ot-gap: a gap in a sentence. reveal writes the answer in.
    define('ot-gap', class extends Base {
      build() {
        var id = this.id || (this.id = autoId('lucka'));
        var ans = this.getAttribute('answer') || '';
        var input = document.createElement('input');
        input.type = 'text'; input.autocomplete = 'off'; input.spellcheck = false;
        input.setAttribute('autocapitalize', 'off');
        input.setAttribute('aria-label', this.getAttribute('label') || 'Lucka');
        input.size = Math.max(3, Math.min(18, (this.getAttribute('size') | 0) || ans.length + 1 || 5));
        input.style.width = (input.size + 0.5) + 'ch';
        input.addEventListener('change', function () { if (input.value.trim()) post({ ot: 'answer', id: id, value: input.value.trim() }); });
        input.addEventListener('keydown', function (e) { if (e.key === 'Enter') input.blur(); });
        input.addEventListener('input', function () { draft(id, input.value); });
        this.textContent = '';
        this.appendChild(input);
        this._restore = function (v) { input.value = v; };
      }
      reveal() {
        var input = this.querySelector('input');
        if (input) { input.value = this.getAttribute('answer') || input.value; input.readOnly = true; }
        this.setAttribute('data-revealed', '');
        return this;
      }
    });

    // ---- ot-steps / ot-step: worked steps, equals signs aligned, a cyan note for the operation.
    define('ot-steps', class extends Base {
      build() { this.refresh(); }
      refresh() {
        var base = this.id;
        $$(':scope > ot-step', this).forEach(function (s, i) { if (!s.id && base) s.id = base + '-' + (i + 1); });
      }
    });
    define('ot-step', class extends Base {
      build() {
        var src = this._src = this.innerHTML.trim();
        var note = this.getAttribute('note');
        var m = /^\$([^$]+)\$$/.exec(src);
        var html = '';
        if (m) {
          var parts = splitRelation(m[1]);
          if (parts) {
            html = '<span class="ot-s ot-s-l">' + tex(parts[0]) + '</span><span class="ot-s ot-s-eq">' + tex(parts[1]) +
                   '</span><span class="ot-s ot-s-r">' + tex(parts[2]) + '</span>';
          } else {
            html = '<span class="ot-s ot-s-full">' + tex(m[1]) + '</span>';
          }
        } else if (src.indexOf('$') >= 0) {
          html = '<span class="ot-s ot-s-full">' + src + '</span>';
        } else {
          this.innerHTML = '<span class="ot-s-text">' + src + '</span>';
          return;
        }
        html += '<span class="ot-s-note">' + (note ? rich(note) : '') + '</span>';
        this.innerHTML = html;
        // Mixed text and maths in a full-width cell.
        if (!m) renderMathNow(this);
      }
    });

    // ---- ot-written: uppställning computed by the shell (addition, subtraktion, multiplikation, liggande stolen).
    define('ot-written', class extends Base {
      build() { this.refresh(); }
      refresh() {
        try { this.innerHTML = written(this); }
        catch (e) { issue('written', e.message, this); this.textContent = (this.getAttribute('a') || '') + ' ' + (this.getAttribute('op') || '') + ' ' + (this.getAttribute('b') || ''); }
      }
      static get observedAttributes() { return ['a', 'b', 'op', 'steps', 'result']; }
      attributeChangedCallback() { if (this._built) this.refresh(); }
      reveal() { this.setAttribute('result', 'shown'); return this; }
    });

    // ---- ot-timeline / ot-event
    define('ot-timeline', class extends Base {
      build() { this.refresh(); }
      refresh() {
        var evs = $$(':scope > ot-event', this);
        // keep events in time order, wherever a patch put them
        var sorted = evs.slice().sort(function (a, b) { return num(a.getAttribute('year')) - num(b.getAttribute('year')); });
        if (sorted.some(function (e, i) { return e !== evs[i]; })) { var self = this; sorted.forEach(function (e) { self.appendChild(e); }); evs = sorted; }
        var bce = evs.some(function (e) { return num(e.getAttribute('year')) < 0; });
        evs.forEach(function (e) {
          var y = num(e.getAttribute('year'));
          var text = e.getAttribute('label') || (isNaN(y) ? '' : y < 0 ? fmtYear(-y) + ' f.Kr.' : fmtYear(y) + (bce ? ' e.Kr.' : ''));
          var span = e.querySelector(':scope > .ot-ev-year');
          if (span) span.textContent = text;
        });
      }
    });
    define('ot-event', class extends Base {
      build() {
        var y = document.createElement('span'); y.className = 'ot-ev-year';
        var d = document.createElement('span'); d.className = 'ot-ev-dot';
        var t = document.createElement('span'); t.className = 'ot-ev-text';
        while (this.firstChild) t.appendChild(this.firstChild);
        this.append(y, d, t);
        var tl = this.closest('ot-timeline');
        if (tl && tl.refresh) tl.refresh();
      }
    });

    // ---- ot-clock
    define('ot-clock', class extends Visual {
      static get observedAttributes() { return ['time']; }
      attributeChangedCallback() { if (this._built) this.redraw(); }
      draw(w, h, f) {
        var t = /(\d{1,2})\s*[:.]\s*(\d{2})/.exec(this.getAttribute('time') || '12:00') || [0, 12, 0];
        var hh = Number(t[1]), mm = Number(t[2]);
        var digital = this.hasAttribute('digital');
        var minutes = this.hasAttribute('minutes');
        var avail = Math.min(w, h - (digital ? 2.4 * f : 0));
        var outer = minutes ? 1.2 : 1.0;
        var r = avail / 2 / outer - 2;
        var cx = w / 2, cy = (minutes ? r * outer : r) + 2;
        if (!digital) cy = h / 2;
        var c = { text: css('--text'), muted: css('--muted'), surface: css('--surface'), border: css('--border-2'), cyan: css('--cyan'), bg: css('--bg') };
        var s = '<circle cx="' + cx + '" cy="' + cy + '" r="' + r + '" fill="' + c.surface + '" stroke="' + c.border + '" stroke-width="' + Math.max(2, r * 0.03) + '"/>';
        for (var i = 0; i < 60; i++) {
          var a = i * Math.PI / 30, big = i % 5 === 0;
          var r1 = r * (big ? 0.86 : 0.92), r2 = r * 0.965;
          s += line(cx + r1 * Math.sin(a), cy - r1 * Math.cos(a), cx + r2 * Math.sin(a), cy - r2 * Math.cos(a), big ? c.text : c.muted, big ? Math.max(2, r * 0.025) : Math.max(1, r * 0.01));
        }
        var lay = this.layer();
        var fs = Math.max(f * 0.95, r * 0.15);
        var html = '';
        if (!this.hasAttribute('no-numbers')) {
          for (var n = 1; n <= 12; n++) {
            var an = n * Math.PI / 6, rr = r * 0.72;
            html += '<div class="ot-lbl" style="left:' + (cx + rr * Math.sin(an)) + 'px;top:' + (cy - rr * Math.cos(an)) + 'px;font-size:' + fs + 'px;font-weight:700">' + n + '</div>';
          }
        }
        if (minutes) {
          for (var k = 1; k <= 12; k++) {
            var am = k * Math.PI / 6, rm = r * 1.1;
            html += '<div class="ot-lbl" style="left:' + (cx + rm * Math.sin(am)) + 'px;top:' + (cy - rm * Math.cos(am)) + 'px;font-size:' + Math.max(f * 0.72, r * 0.085) + 'px;color:' + c.muted + '">' + (k * 5 === 60 ? 0 : k * 5) + '</div>';
          }
        }
        var ha = ((hh % 12) + mm / 60) * Math.PI / 6, ma = mm * Math.PI / 30;
        s += line(cx, cy, cx + r * 0.5 * Math.sin(ha), cy - r * 0.5 * Math.cos(ha), c.text, Math.max(4, r * 0.075));
        s += line(cx, cy, cx + r * 0.8 * Math.sin(ma), cy - r * 0.8 * Math.cos(ma), c.cyan, Math.max(3, r * 0.045));
        s += '<circle cx="' + cx + '" cy="' + cy + '" r="' + Math.max(4, r * 0.05) + '" fill="' + c.text + '"/>';
        lay.innerHTML = svg(w, h, s) + html;
        if (digital) {
          var dv = (hh < 10 ? '0' : '') + hh + ':' + (mm < 10 ? '0' : '') + mm;
          label(lay, cx, cy + r * outer + 1.3 * f, '<span style="font-size:1.3em;font-weight:750;letter-spacing:0.04em;background:' + c.bg + ';border:1px solid ' + c.border + ';border-radius:0.4em;padding:0.05em 0.5em">' + dv + '</span>');
        }
      }
    });

    // ---- ot-numberline with ot-mark and ot-jump children
    define('ot-numberline', class extends Visual {
      draw(w, h, f) {
        var lay = this.layer();
        var fr = frac(this.getAttribute('step'));
        var from = num(this.getAttribute('from') || 0), to = num(this.getAttribute('to') || 10);
        var step = fr ? fr.n / fr.d : num(this.getAttribute('step') || 1);
        if (!(to > from) || !(step > 0)) { issue('attr', 'numberline needs from < to and step > 0', this); return; }
        var n = Math.round((to - from) / step);
        if (n > 200) { issue('attr', 'numberline has too many ticks', this); n = 200; }
        var marks = $$(':scope > ot-mark', this), jumps = $$(':scope > ot-jump', this);
        var pad = 1.4 * f;
        var x = function (v) { return pad + (v - from) / (to - from) * (w - 2 * pad); };
        var tickPx = (w - 2 * pad) / n;
        var c = { text: css('--text'), muted: css('--muted'), border: css('--border-2'), bg: css('--bg') };
        var maxJump = 0;
        jumps.forEach(function (j) { maxJump = Math.max(maxJump, Math.abs(x(num(j.getAttribute('to'))) - x(num(j.getAttribute('from'))))); });
        var arcH = jumps.length ? Math.max(1.4 * f, Math.min(maxJump / 2, 2.6 * f)) : 0;
        // with jumps above the line, mark labels go below the numbers
        var marksBelow = jumps.length > 0;
        var top = (marks.length && !marksBelow ? 4.3 * f : 0.6 * f) + (jumps.length ? arcH + 1.6 * f : 0);
        var y = Math.min(h - (marks.length && marksBelow ? 5.2 * f : 2.4 * f), Math.max(top, h / 2));
        var s = line(pad - 0.6 * f, y, w - pad + 0.6 * f, y, c.text, Math.max(2, f * 0.12));
        // arrow head on the right
        s += '<path d="M' + (w - pad + 0.9 * f) + ' ' + y + ' l' + (-0.6 * f) + ' ' + (-0.35 * f) + ' v' + (0.7 * f) + ' z" fill="' + c.text + '"/>';
        var labelEvery = 1;
        var lw = f * 0.62 * Math.max(fmt(from).length, fmt(to).length, fr ? 1.6 : 1) + 0.7 * f;
        [1, 2, 5, 10, 20, 50].some(function (k) { labelEvery = k; return tickPx * k >= lw; });
        var spec = this.getAttribute('labels');
        var html = '';
        for (var i = 0; i <= n; i++) {
          var v = from + i * step, X = x(v);
          var whole = Math.abs(v - Math.round(v)) < 1e-9;
          var major = fr ? whole : (i % labelEvery === 0);
          s += line(X, y - (major ? 0.55 : 0.32) * f, X, y + (major ? 0.55 : 0.32) * f, major ? c.text : c.muted, Math.max(1.5, f * (major ? 0.1 : 0.06)));
          var show = spec === 'none' ? false : spec === 'ends' ? (i === 0 || i === n) : fr ? (tickPx > 1.6 * f || whole) : i % labelEvery === 0;
          if (show) {
            var txt = fr && !whole ? tex('\\tfrac{' + Math.round(v * fr.d) + '}{' + fr.d + '}') : fmt(v);
            html += '<div class="ot-lbl" style="left:' + X + 'px;top:' + (y + 1.35 * f) + 'px;color:' + (major ? c.text : c.muted) + '">' + txt + '</div>';
          }
        }
        jumps.forEach(function (j, k) {
          var a = x(num(j.getAttribute('from'))), b = x(num(j.getAttribute('to')));
          var col = color(j.getAttribute('color'), 'violet');
          var mid = (a + b) / 2, yy = y - 0.5 * f, hh = Math.min(arcH, Math.max(Math.abs(b - a) / 2, 1.3 * f));
          s += '<path d="M' + a + ' ' + yy + ' Q' + mid + ' ' + (yy - hh * 2) + ' ' + b + ' ' + yy + '" fill="none" stroke="' + col + '" stroke-width="' + Math.max(2, f * 0.12) + '"/>';
          var dir = b > a ? 1 : -1;
          s += '<path d="M' + b + ' ' + yy + ' l' + (-dir * 0.55 * f) + ' ' + (-0.5 * f) + ' l' + (dir * 0.05 * f) + ' ' + (0.62 * f) + ' z" fill="' + col + '"/>';
          html += '<div class="ot-lbl" style="left:' + mid + 'px;top:' + (yy - hh - 0.8 * f) + 'px;color:' + col + ';font-weight:750">' + rich(j.textContent.trim()) + '</div>';
          j._px = { x: mid, y: yy - hh };
        });
        // labels of marks that sit close together go on two levels
        var lastX = -1e9, lastLevel = 1;
        marks.slice().sort(function (a, b) { return num(a.getAttribute('at')) - num(b.getAttribute('at')); }).forEach(function (m) {
          var X = x(num(m.getAttribute('at')));
          m._level = (X - lastX < 2.4 * f && lastLevel === 0) ? 1 : 0;
          lastX = X; lastLevel = m._level;
        });
        marks.forEach(function (m) {
          var v = num(m.getAttribute('at')), X = x(v);
          var col = color(m.getAttribute('color'), 'cyan');
          s += '<circle cx="' + X + '" cy="' + y + '" r="' + (0.38 * f) + '" fill="' + col + '" stroke="' + c.bg + '" stroke-width="' + (0.12 * f) + '"/>';
          var t = m.textContent.trim();
          var ly = marksBelow ? y + 2.8 * f + (m._level ? 1.9 * f : 0) : y - 1.45 * f - (m._level ? 2.1 * f : 0);
          if (t) html += '<div class="ot-lbl" style="left:' + X + 'px;top:' + ly + 'px;color:' + col + ';font-weight:750">' + rich(t) + '</div>';
          if (t && m._level && !marksBelow) s += line(X, y - 0.5 * f, X, y - 2.6 * f, col, 1.5);
          m._px = { x: X, y: y };
        });
        lay.innerHTML = svg(w, h, s) + html;
        this._y = y;
        // ask for more height when jumps or marks do not fit above and below the line
        var need = top + (marks.length && marksBelow ? 5.2 * f : 2.4 * f);
        if (need > h + 1) return { ok: false, needEm: need / f + 0.2, msg: 'numberline needs more room' };
      }
      pointAt(child) { return ringAt(this, child._px); }
    });

    // ---- ot-fraction: bar or circle
    define('ot-fraction', class extends Visual {
      static get observedAttributes() { return ['value', 'shape']; }
      attributeChangedCallback() { if (this._built) this.redraw(); }
      draw(w, h, f) {
        var v = frac(this.getAttribute('value') || '1/2');
        if (!v || v.d < 1 || v.d > 60) { issue('attr', 'fraction value must look like 3/4', this); return; }
        var col = color(this.getAttribute('color'), 'cyan');
        var c = { text: css('--text'), border: css('--border-2'), surface: css('--surface'), bg: css('--bg') };
        var lab = this.getAttribute('label');
        var labHtml = lab === 'none' ? '' : lab ? rich(lab) : tex('\\frac{' + v.n + '}{' + v.d + '}');
        var lay = this.layer();
        var s = '', html = '';
        var wholes = Math.max(1, Math.ceil(v.n / v.d));
        if (this.getAttribute('shape') === 'circle') {
          var lw = labHtml ? 3.2 * f : 0;
          var r = Math.min((w - lw) / wholes / 2 - 0.4 * f, h / 2 - 2);
          for (var k = 0; k < wholes; k++) {
            var cx = lw + r + 0.2 * f + k * (2 * r + 0.8 * f), cy = h / 2;
            s += '<circle cx="' + cx + '" cy="' + cy + '" r="' + r + '" fill="' + c.surface + '"/>';
            for (var i = 0; i < v.d; i++) {
              var filled = k * v.d + i < v.n;
              var a0 = i / v.d * 2 * Math.PI, a1 = (i + 1) / v.d * 2 * Math.PI;
              var p = 'M' + cx + ' ' + cy + ' L' + (cx + r * Math.sin(a0)) + ' ' + (cy - r * Math.cos(a0)) +
                      ' A' + r + ' ' + r + ' 0 ' + (a1 - a0 > Math.PI ? 1 : 0) + ' 1 ' + (cx + r * Math.sin(a1)) + ' ' + (cy - r * Math.cos(a1)) + ' Z';
              if (v.d === 1) p = 'M' + (cx - r) + ' ' + cy + ' a' + r + ' ' + r + ' 0 1 0 ' + 2 * r + ' 0 a' + r + ' ' + r + ' 0 1 0 ' + (-2 * r) + ' 0';
              s += '<path d="' + p + '" fill="' + (filled ? alpha(col, 0.85) : 'none') + '" stroke="' + c.bg + '" stroke-width="' + Math.max(2, f * 0.12) + '"/>';
            }
            s += '<circle cx="' + cx + '" cy="' + cy + '" r="' + r + '" fill="none" stroke="' + c.text + '" stroke-width="' + Math.max(1.5, f * 0.08) + '"/>';
          }
          if (labHtml) html = '<div class="ot-lbl" style="left:' + (lw / 2) + 'px;top:' + (h / 2) + 'px;font-size:1.25em">' + labHtml + '</div>';
        } else {
          var lw2 = labHtml ? 3.2 * f : 0;
          var bh = Math.min(h - 4, 2.6 * f);
          var bw = (w - lw2 - (wholes - 1) * 0.8 * f) / wholes;
          var y0 = (h - bh) / 2;
          for (var k2 = 0; k2 < wholes; k2++) {
            var x0 = lw2 + k2 * (bw + 0.8 * f);
            for (var j = 0; j < v.d; j++) {
              var on = k2 * v.d + j < v.n;
              s += '<rect x="' + (x0 + j * bw / v.d) + '" y="' + y0 + '" width="' + bw / v.d + '" height="' + bh + '" fill="' + (on ? alpha(col, 0.85) : c.surface) + '" stroke="' + c.bg + '" stroke-width="' + Math.max(2, f * 0.1) + '"/>';
            }
            s += '<rect x="' + x0 + '" y="' + y0 + '" width="' + bw + '" height="' + bh + '" rx="' + 0.15 * f + '" fill="none" stroke="' + c.text + '" stroke-width="' + Math.max(1.5, f * 0.08) + '"/>';
          }
          if (labHtml) html = '<div class="ot-lbl" style="left:' + (lw2 / 2) + 'px;top:' + (h / 2) + 'px;font-size:1.25em">' + labHtml + '</div>';
        }
        lay.innerHTML = svg(w, h, s) + html;
      }
    });

    // ---- ot-balance: a balance scale for equations
    define('ot-balance', class extends Visual {
      static get observedAttributes() { return ['left', 'right', 'tilt']; }
      attributeChangedCallback() { if (this._built) this.redraw(); }
      draw(w, h, f) {
        var c = { text: css('--text'), muted: css('--muted'), border: css('--border-2'), surface: css('--surface'), violet: css('--violet'), bg: css('--bg') };
        var tilt = this.getAttribute('tilt');
        var ang = tilt === 'left' ? -7 : tilt === 'right' ? 7 : 0;
        var bw = Math.min(w * 0.92, h * 2.6);
        var cx = w / 2, py = 0.9 * f;
        var panW = Math.min(bw * 0.38, 9 * f);
        var half = Math.min(bw / 2, (w - panW) / 2 - 0.5 * f);
        var rad = ang * Math.PI / 180;
        var L = { x: cx - half * Math.cos(rad), y: py - half * Math.sin(rad) };
        var R = { x: cx + half * Math.cos(rad), y: py + half * Math.sin(rad) };
        var drop = h - 2.4 * f - py;
        var s = '';
        // stand
        s += '<path d="M' + (cx - 2.2 * f) + ' ' + (h - 0.2 * f) + ' L' + cx + ' ' + (h - 1.6 * f) + ' L' + (cx + 2.2 * f) + ' ' + (h - 0.2 * f) + ' Z" fill="' + c.surface + '" stroke="' + c.border + '" stroke-width="2"/>';
        s += line(cx, py, cx, h - 1.6 * f, c.border, Math.max(3, f * 0.22));
        s += line(L.x, L.y, R.x, R.y, c.text, Math.max(3, f * 0.2));
        s += '<circle cx="' + cx + '" cy="' + py + '" r="' + 0.32 * f + '" fill="' + c.violet + '"/>';
        var html = '';
        var self = this;
        [[L, this.getAttribute('left')], [R, this.getAttribute('right')]].forEach(function (pair) {
          var P = pair[0], panY = P.y + drop;
          s += line(P.x, P.y, P.x - panW / 2, panY, c.muted, 1.5) + line(P.x, P.y, P.x + panW / 2, panY, c.muted, 1.5);
          s += '<path d="M' + (P.x - panW / 2 - 0.3 * f) + ' ' + panY + ' Q' + P.x + ' ' + (panY + 1.3 * f) + ' ' + (P.x + panW / 2 + 0.3 * f) + ' ' + panY + ' Z" fill="' + c.surface + '" stroke="' + c.text + '" stroke-width="2"/>';
          html += '<div class="ot-lbl" style="left:' + P.x + 'px;top:' + (panY - 1.15 * f) + 'px;font-size:1.35em;background:' + c.bg + ';padding:0.05em 0.35em;border-radius:0.3em">' + tex(pair[1] || '') + '</div>';
        });
        this.layer().innerHTML = svg(w, h, s) + html;
        void self;
      }
    });

    // ---- ot-graph: coordinate system with JSXGraph
    define('ot-graph', class extends Visual {
      draw(w, h, f) { drawGraph(this, w, h, f); }
      disconnectedCallback() {
        if (this._board) { try { JXG.JSXGraph.freeBoard(this._board); } catch (e) { /* gone */ } this._board = null; }
      }
      pointAt(child) { return graphPoint(this, child); }
      flashChild(child) { return graphFlash(this, child); }
    });

    // ---- ot-chart: Chart.js from a plain <table>
    define('ot-chart', class extends Visual {
      draw(w, h, f) { drawChart(this, w, h, f); }
      disconnectedCallback() {
        if (this._chart) { try { this._chart.destroy(); } catch (e) { /* gone */ } this._chart = null; }
      }
    });

    // ---- ot-map: vector map (d3-geo + Natural Earth / historical-basemaps)
    define('ot-map', class extends Visual {
      build() { this._data = mapData(this); }
      draw(w, h, f) { drawMap(this, w, h, f); }
      pointAt(child) { return pointRegion(this, child); }
    });

    // ---- ot-image: photo or illustration with credit; ot-label children make labelled parts
    define('ot-image', class extends Visual {
      build() {
        var wrap = document.createElement('div'); wrap.className = 'ot-img-wrap';
        var img = document.createElement('img');
        img.alt = this.getAttribute('alt') || '';
        img.decoding = 'async';
        img.referrerPolicy = 'no-referrer';
        var credit = document.createElement('div'); credit.className = 'ot-credit';
        wrap.appendChild(img);
        this.append(wrap, credit);
        this._img = img; this._credit = credit;
        var self = this;
        this._loaded = resolveImage(this).then(function (info) {
          if (!info || !info.src) { issue('image', 'no image found', self); return; }
          credit.textContent = info.credit || '';
          if (!info.credit) issue('image', 'image has no credit (källa)', self);
          return new Promise(function (resolve) {
            img.onload = function () { resolve(); self.redraw(); };
            img.onerror = function () { issue('image', 'image failed to load: ' + info.src, self); resolve(); };
            img.src = info.src;
          });
        });
      }
      draw(w, h, f) { drawImageLabels(this, w, h, f); }
    });

    // ---- ot-cycle and ot-mindmap: boxes on an ellipse, arrows or branches
    define('ot-cycle', class extends Visual {
      draw(w, h, f) { return drawRing(this, w, h, f, 'cycle'); }
    });
    define('ot-mindmap', class extends Visual {
      draw(w, h, f) { return drawRing(this, w, h, f, 'mindmap'); }
    });

    Object.keys(REGISTRY).forEach(function (tag) {
      if (!customElements.get(tag)) customElements.define(tag, REGISTRY[tag]);
    });
  }

  var autoCount = 0;
  function autoId(prefix) {
    var id;
    do { id = prefix + '-' + (++autoCount); } while (document.getElementById(id));
    return id;
  }
  function renderMathNow(el) { renderMath(el); }
  function fmtYear(y) { return String(Math.round(y)); }

  // Split "3x + 5 = 20" at the first top-level relation.
  function splitRelation(t) {
    var depth = 0;
    var rels = ['\\approx', '\\neq', '\\leq', '\\geq', '\\le', '\\ge', '=', '<', '>', '≈'];
    for (var i = 0; i < t.length; i++) {
      var ch = t[i];
      if (ch === '{') depth++;
      else if (ch === '}') depth--;
      else if (depth === 0) {
        for (var k = 0; k < rels.length; k++) {
          var r = rels[k];
          if (t.substr(i, r.length) === r && !(r[0] === '\\' && /[a-z]/i.test(t[i + r.length] || '') )) {
            if ((r === '<' || r === '>') && /\\(left|right)$/.test(t.slice(0, i))) continue;
            return [t.slice(0, i), r, t.slice(i + r.length)];
          }
        }
        if (ch === '\\') { var m = /^\\[a-zA-Z]+/.exec(t.slice(i)); if (m) i += m[0].length - 1; }
      }
    }
    return null;
  }

  // ---------------------------------------------------------------- written methods
  function parseDec(s) {
    s = String(s || '').trim().replace(/\s/g, '').replace('.', ',');
    if (!/^\d+(,\d+)?$/.test(s)) throw new Error('written needs plain positive numbers, got "' + s + '"');
    var p = s.split(',');
    return { int: p[0].replace(/^0+(?=\d)/, ''), frac: p[1] || '' };
  }
  function cells(spec) {
    // spec: array of {t, cls, w:'d'|'c'}; returns grid row html
    return spec.map(function (c) {
      return '<span class="' + (c.w === 'c' ? 'ot-w-c' : 'ot-w-d') + (c.cls ? ' ' + c.cls : '') + '">' + (c.t == null ? '' : esc(c.t)) + (c.comma ? '<span class="ot-w-comma">,</span>' : '') + '</span>';
    }).join('');
  }
  function written(el) {
    var op = (el.getAttribute('op') || '+').trim();
    op = { '-': '−', '−': '−', '*': '×', 'x': '×', '·': '×', '×': '×', '/': '÷', ':': '÷', '÷': '÷' }[op] || '+';
    var hideResult = el.getAttribute('result') === 'hidden';
    if (op === '÷') return writtenDivision(el, hideResult);
    if (op === '×') return writtenMultiplication(el, hideResult);
    return writtenAddSub(el, op, hideResult);
  }
  function writtenAddSub(el, op, hide) {
    var a = parseDec(el.getAttribute('a')), b = parseDec(el.getAttribute('b'));
    var fl = Math.max(a.frac.length, b.frac.length);
    var A = (a.int + a.frac.padEnd(fl, '0')), B = (b.int + b.frac.padEnd(fl, '0'));
    var il = Math.max(a.int.length, b.int.length) + (op === '+' ? 1 : 0);
    var n = il + fl;
    A = A.padStart(n, ' '); B = B.padStart(n, ' ');
    var da = A.split('').map(function (c) { return c === ' ' ? null : Number(c); });
    var db = B.split('').map(function (c) { return c === ' ' ? null : Number(c); });
    var res = new Array(n), above = new Array(n).fill(null), crossed = new Array(n).fill(false);
    if (op === '+') {
      var carry = 0;
      for (var i = n - 1; i >= 0; i--) {
        var s = (da[i] || 0) + (db[i] || 0) + carry;
        res[i] = s % 10; carry = Math.floor(s / 10);
        if (carry && i > 0) above[i - 1] = '1';
      }
      if (carry) res[0] = carry;
    } else {
      if (Number(a.int + '.' + (a.frac || 0)) < Number(b.int + '.' + (b.frac || 0))) throw new Error('subtraction: a must be at least b');
      var cur = da.map(function (d) { return d || 0; });
      for (var j = n - 1; j >= 0; j--) {
        var sub = db[j] || 0;
        if (cur[j] < sub) {
          var k = j - 1;
          while (k >= 0 && cur[k] === 0) k--;
          cur[k] -= 1; above[k] = String(cur[k]); crossed[k] = true;
          for (var m = k + 1; m < j; m++) { cur[m] = 9; above[m] = '9'; crossed[m] = true; }
          cur[j] += 10; above[j] = String(cur[j]); crossed[j] = true;
        }
        res[j] = cur[j] - sub;
      }
    }
    // trim leading zeros of result (keep the digit before the comma)
    var first = 0;
    while (first < il - 1 && !res[first]) { res[first] = null; first++; }
    var cols = [];
    var commaAt = il; // index where comma column goes (before digit index il)
    function row(digits, opts) {
      opts = opts || {};
      var out = [{ t: opts.sign || '', cls: 'ot-w-op' + (opts.lineCls ? ' ' + opts.lineCls : '') }];
      for (var i = 0; i < n; i++) {
        if (i === commaAt && fl) out.push({ t: opts.comma ? ',' : '', w: 'c', cls: opts.lineCls || '' });
        var d = digits[i];
        var cls = (opts.cls || '') + (opts.crossed && opts.crossed[i] ? ' ot-w-cross' : '') + (opts.lineCls ? ' ' + opts.lineCls : '');
        out.push({ t: d == null ? '' : String(d), cls: cls });
      }
      return cells(out);
    }
    var showA = da.map(function (d) { return d; });
    var html = row(above, { cls: 'ot-w-carry' }) +
      row(showA, { comma: true, crossed: crossed }) +
      row(db, { comma: true, sign: op }) +
      row(hide ? res.map(function () { return null; }) : res, { comma: !hide, cls: 'ot-w-result', lineCls: 'ot-w-line' });
    var ncols = 1 + n + (fl ? 1 : 0);
    return '<div class="ot-w-grid" style="grid-template-columns:' + colTemplate(ncols, fl ? 1 + commaAt : -1) + '">' + html + '</div>';
  }
  function colTemplate(n, commaIdx) {
    var t = [];
    for (var i = 0; i < n; i++) t.push(i === commaIdx ? '0.32em' : '0.72em');
    return t.join(' ');
  }
  function writtenMultiplication(el, hide) {
    var a = parseDec(el.getAttribute('a')), b = parseDec(el.getAttribute('b'));
    var A = a.int + a.frac, B = b.int + b.frac;
    A = A.replace(/^0+(?=\d)/, ''); B = B.replace(/^0+(?=\d)/, '');
    var decs = a.frac.length + b.frac.length;
    var prod = (BigInt(A) * BigInt(B)).toString();
    while (prod.length <= decs) prod = '0' + prod;
    var partials = [];
    if (B.length > 1) {
      for (var i = B.length - 1; i >= 0; i--) {
        partials.push((BigInt(A) * BigInt(B[i])).toString() + '0'.repeat(B.length - 1 - i));
      }
    }
    var n = Math.max(A.length, B.length + 1, prod.length, partials.reduce(function (m, p) { return Math.max(m, p.length); }, 0)) + 0;
    // carries only for a one-digit second factor
    var carries = new Array(n).fill(null);
    if (B.length === 1) {
      var c = 0, bd = Number(B);
      for (var j = A.length - 1; j >= 0; j--) {
        var s = Number(A[j]) * bd + c; c = Math.floor(s / 10);
        if (c && j > 0) carries[n - A.length + j - 1] = String(c);
      }
    }
    function digitsRight(str, commaFromRight) {
      var arr = new Array(n).fill(null);
      var off = n - str.length;
      for (var k = 0; k < str.length; k++) arr[off + k] = str[k];
      return { arr: arr, comma: commaFromRight ? n - commaFromRight : -1 };
    }
    function row(d, opts) {
      opts = opts || {};
      var out = [{ t: opts.sign || '', cls: 'ot-w-op' + (opts.lineCls ? ' ' + opts.lineCls : '') }];
      for (var k = 0; k < n; k++) {
        var t = d.arr[k];
        var withComma = d.comma === k + 1 && t != null;
        out.push({ t: t, comma: withComma, cls: (opts.cls || '') + (opts.lineCls ? ' ' + opts.lineCls : '') });
      }
      return cells(out);
    }
    // Commas sit after the digit; we render "d," in one cell, so widen nothing.
    var html = '';
    html = cells([{ t: '' }].concat(carries.map(function (c2) { return { t: c2, cls: 'ot-w-carry' }; })));
    html += row(digitsRight(A, a.frac.length), {});
    html += row(digitsRight(B, b.frac.length), { sign: '×' });
    if (partials.length) {
      partials.forEach(function (p, k) { html += row(digitsRight(p, 0), { cls: 'ot-w-sub', lineCls: k === 0 ? 'ot-w-line' : '', sign: k === partials.length - 1 ? '+' : '' }); });
    }
    var resD = digitsRight(prod, decs);
    if (hide) resD.arr = resD.arr.map(function () { return null; });
    html += row(resD, { cls: 'ot-w-result', lineCls: 'ot-w-line' });
    return '<div class="ot-w-grid ot-w-mul" style="grid-template-columns:' + colTemplate(n + 1, -1).replace(/0\.72em/g, '0.8em') + '">' + html + '</div>';
  }
  function writtenDivision(el, hide) {
    var a = parseDec(el.getAttribute('a')), b = parseDec(el.getAttribute('b'));
    if (b.frac && Number(b.frac) !== 0) {
      issue('written', 'divisor ' + el.getAttribute('b') + ' is not a whole number: multiply both by 10 first', el);
    }
    var divisor = Number(b.int + (b.frac && Number(b.frac) !== 0 ? b.frac : ''));
    if (b.frac && Number(b.frac) !== 0) {
      var shift = b.frac.length;
      var f2 = a.frac.padEnd(shift, '0');
      a = { int: (a.int + f2.slice(0, shift)).replace(/^0+(?=\d)/, ''), frac: f2.slice(shift) };
    }
    if (!(divisor > 0)) throw new Error('division by zero');
    var maxExtra = Math.min(4, Math.max(0, (el.getAttribute('decimals') | 0) || 3));
    var D = (a.int + a.frac).split('').map(Number);
    var intLen = a.int.length;
    var steps = [];
    var quotient = new Array(D.length).fill(null);
    var partial = 0, started = false, extra = 0, j = 0;
    while (true) {
      if (j >= D.length) {
        if (partial === 0 || extra >= maxExtra || D.length - intLen >= a.frac.length + maxExtra) break;
        D.push(0); quotient.push(null); extra++;
      }
      partial = partial * 10 + D[j];
      if (!started && partial < divisor && j < intLen - 1) { j++; continue; }
      var q = Math.floor(partial / divisor);
      quotient[j] = q;
      if (q > 0 || !started) steps.push({ end: j, partial: partial, prod: q * divisor, rem: partial - q * divisor, q: q });
      started = true;
      partial = partial - q * divisor;
      if (q === 0 && steps.length) { steps[steps.length - 1].skipTo = j; }
      j++;
    }
    var fracLen = D.length - intLen;
    var limit = el.hasAttribute('steps') ? Math.max(0, el.getAttribute('steps') | 0) : Infinity;
    // columns: [sign] D digits (comma column after intLen if fracLen) [bar] divisor digits
    var dvs = String(divisor);
    var nD = D.length;
    var commaCol = fracLen ? intLen : -1;
    function rowCells(arr, opts) {
      opts = opts || {};
      var out = [{ t: opts.sign || '', cls: 'ot-w-op' }];
      for (var i = 0; i < nD; i++) {
        if (i === commaCol) out.push({ t: opts.comma ? ',' : '', w: 'c', cls: (opts.lineCls || '') + ' ' + (opts.cls || '') });
        out.push({ t: arr[i] == null ? '' : String(arr[i]), cls: (opts.cls || '') + (opts.lineCls && arr[i] != null ? ' ' + opts.lineCls : '') + (opts.lineAll ? ' ' + opts.lineAll : '') });
      }
      out.push({ t: '', cls: opts.bar ? 'ot-w-bar' : '' });
      for (var k = 0; k < dvs.length; k++) out.push({ t: opts.divisor ? dvs[k] : '', cls: '' });
      return cells(out);
    }
    function placeRight(value, end) {
      var arr = new Array(nD).fill(null), s = String(value);
      for (var k = 0; k < s.length; k++) arr[end - s.length + 1 + k] = s[k];
      return arr;
    }
    var shownSteps = Math.min(limit, steps.length);
    var qShown = quotient.map(function (q, i) {
      if (q == null) return null;
      var stepIdx = -1;
      for (var k = 0; k < steps.length; k++) if (steps[k].end <= i) stepIdx = k;
      return (hide || stepIdx >= shownSteps) ? null : q;
    });
    var lastQ = -1; qShown.forEach(function (q, i) { if (q != null) lastQ = i; });
    var html = rowCells(qShown, { cls: 'ot-w-result', comma: fracLen && lastQ >= intLen && !hide });
    html += rowCells(D.map(function (d, i) { return i < intLen + a.frac.length || i <= lastStepEnd() ? d : null; }), { comma: !!fracLen, bar: true, divisor: true, lineAll: 'ot-w-line' });
    function lastStepEnd() { return shownSteps ? steps[shownSteps - 1].end + 1 : 0; }
    for (var s = 0; s < shownSteps; s++) {
      var st = steps[s];
      if (st.q === 0 && s > 0) continue;
      var prodArr = placeRight(st.prod, st.end);
      var firstDigit = prodArr.indexOf(prodArr.filter(function (x) { return x != null; })[0]);
      var signRow = rowCells(prodArr, { cls: 'ot-w-sub' });
      // put the minus sign just left of the product
      if (firstDigit > 0) {
        var tmp = prodArr.slice(); tmp[firstDigit - 1] = '−';
        signRow = rowCells(tmp, { cls: 'ot-w-sub' });
      } else {
        signRow = rowCells(prodArr, { cls: 'ot-w-sub', sign: '−' });
      }
      html += signRow;
      var next = steps[s + 1];
      var remEnd, remVal;
      if (next && s + 1 < shownSteps + 1 && s + 1 <= steps.length - 1) {
        remEnd = next.end; remVal = next.partial;
      } else { remEnd = st.end; remVal = st.rem; }
      var remArr = placeRight(remVal, remEnd);
      // the line spans the product's columns and the brought-down column
      var lineArr = remArr.map(function (x, i) { return i <= st.end && i >= st.end - String(st.prod).length + 1 ? 'L' : null; });
      html += rowCells(remArr.map(function (x, i) { return x; }), { lineCls: '', cls: '' }).replace(/<span class="ot-w-d"><\/span>/g, '<span class="ot-w-d"></span>');
      html = markLine(html, lineArr, nD, commaCol, dvs.length);
      if (!(next && s + 1 < shownSteps)) break;
    }
    var ncols = 1 + nD + (fracLen ? 1 : 0) + 1 + dvs.length;
    var tpl = [];
    for (var i = 0; i < ncols; i++) tpl.push('0.72em');
    if (fracLen) tpl[1 + intLen] = '0.32em';
    tpl[1 + nD + (fracLen ? 1 : 0)] = '0.5em';
    return '<div class="ot-w-grid ot-w-div" style="grid-template-columns:' + tpl.join(' ') + '">' + html + '</div>';
  }
  // Add the top rule to the last row's cells over the given columns.
  function markLine(html, lineArr, nD, commaCol, dl) {
    var parts = html.split('<span ');
    var rowLen = 1 + nD + (commaCol >= 0 ? 1 : 0) + 1 + dl;
    var start = parts.length - rowLen;
    var idx = start + 1; // skip sign cell
    for (var i = 0; i < nD; i++) {
      if (i === commaCol) {
        if (lineArr[i - 1] && lineArr[i]) parts[idx] = parts[idx].replace('class="', 'class="ot-w-line ');
        idx++;
      }
      if (lineArr[i]) parts[idx] = parts[idx].replace('class="', 'class="ot-w-line ');
      idx++;
    }
    return parts.join('<span ');
  }

  // ---------------------------------------------------------------- graph
  function parseFn(src) {
    var s = String(src || '').trim();
    s = s.replace(/^\s*(y|f\s*\(\s*x\s*\)|g\s*\(\s*x\s*\)|h\s*\(\s*x\s*\))\s*=\s*/i, '');
    s = s.replace(/\$/g, '').replace(/−/g, '-').replace(/[·×]/g, '*').replace(/÷/g, '/').replace(/(\d),(\d)/g, '$1.$2');
    s = s.replace(/\\cdot/g, '*').replace(/\\frac\{([^{}]+)\}\{([^{}]+)\}/g, '(($1)/($2))').replace(/\\sqrt\{([^{}]+)\}/g, 'sqrt($1)').replace(/[{}]/g, function (c) { return c === '{' ? '(' : ')'; }).replace(/\\/g, '');
    s = s.replace(/\bln\b/g, 'log').replace(/π/g, 'PI').replace(/\bpi\b/g, 'PI');
    s = s.replace(/(\d)\s*(x|\(|[a-z])/gi, '$1*$2').replace(/\)\s*(\(|x|\d)/g, ')*$1').replace(/x\s*(\(|\d)/g, 'x*$1');
    s = s.replace(/\^/g, '**');
    if (!/^[\dx+\-*/().\s*a-zA-Z]*$/.test(s)) throw new Error('cannot read function "' + src + '"');
    var words = s.match(/[a-zA-Z]+/g) || [];
    var ok = ['x', 'sin', 'cos', 'tan', 'sqrt', 'abs', 'log', 'exp', 'PI', 'E', 'min', 'max', 'pow', 'log10', 'log2'];
    words.forEach(function (wd) { if (ok.indexOf(wd) < 0) throw new Error('unknown word "' + wd + '" in function "' + src + '"'); });
    s = s.replace(/\b(sin|cos|tan|sqrt|abs|log10|log2|log|exp|PI|E|min|max|pow)\b/g, 'Math.$1');
    /* jshint evil:true */
    var fn = new Function('x', 'return ' + s + ';');
    fn(1);
    return fn;
  }
  function graphRanges(el, w, h) {
    var xr = nums(el.getAttribute('x')), yr = nums(el.getAttribute('y'));
    var pts = [];
    $$(':scope > ot-point', el).forEach(function (p) { pts.push([num(p.getAttribute('x')), num(p.getAttribute('y'))]); });
    $$(':scope > ot-polygon, :scope > ot-segment', el).forEach(function (p) {
      pts = pts.concat(points(p.getAttribute('points') || ((p.getAttribute('from') || '') + ' ' + (p.getAttribute('to') || ''))));
    });
    if (xr.length < 2 || yr.length < 2) {
      var xs = pts.map(function (p) { return p[0]; }), ys = pts.map(function (p) { return p[1]; });
      if (!xs.length) { xs = [-5, 5]; ys = [-5, 5]; }
      var mx = Math.max.apply(null, xs) - Math.min.apply(null, xs), my = Math.max.apply(null, ys) - Math.min.apply(null, ys);
      var padd = Math.max(mx, my, 1) * 0.22;
      if (xr.length < 2) xr = [Math.min.apply(null, xs) - padd, Math.max.apply(null, xs) + padd];
      if (yr.length < 2) yr = [Math.min.apply(null, ys) - padd, Math.max.apply(null, ys) + padd];
    }
    // equal units on both axes: widen the narrower range around its centre
    var ux = (xr[1] - xr[0]) / w, uy = (yr[1] - yr[0]) / h;
    if (!el.hasAttribute('free')) {
      if (ux > uy) { var cy = (yr[0] + yr[1]) / 2, hy = ux * h / 2; yr = [cy - hy, cy + hy]; }
      else { var cx = (xr[0] + xr[1]) / 2, hx = uy * w / 2; xr = [cx - hx, cx + hx]; }
    }
    return { x: xr, y: yr };
  }
  function niceStep(range, px, f) {
    var target = range / Math.max(2, px / (2.6 * f));
    var p = Math.pow(10, Math.floor(Math.log10(target)));
    var m = target / p;
    return (m <= 1 ? 1 : m <= 2 ? 2 : m <= 5 ? 5 : 10) * p;
  }
  function drawGraph(el, w, h, f) {
    if (!window.JXG) { issue('load', 'JSXGraph missing', el); return; }
    var lay = el.layer();
    if (el._board) { try { JXG.JSXGraph.freeBoard(el._board); } catch (e) { /* gone */ } el._board = null; }
    lay.innerHTML = '';
    var box = document.createElement('div');
    box.id = el._boxId || (el._boxId = autoId('jxg'));
    box.className = 'jxgbox';
    box.style.width = w + 'px'; box.style.height = h + 'px';
    lay.appendChild(box);
    var axes = el.getAttribute('axes') !== 'off';
    var grid = el.hasAttribute('grid') ? el.getAttribute('grid') !== 'off' : axes;
    var r = graphRanges(el, w, h);
    // Room for side labels. Ranges from points alone leave labels hanging past
    // the pane edge, where no clamp can keep them without pushing them back
    // across their stroke. Widen auto axes by the longest label's half-width.
    // Axes the author set explicitly are respected; leftovers become honest lint.
    var lblLen = 0;
    $$(':scope > *', el).forEach(function (ch) {
      var tg = ch.tagName.toLowerCase();
      if (tg === 'ot-segment' && ch.textContent.trim()) lblLen = Math.max(lblLen, ch.textContent.trim().length);
      else if (tg === 'ot-polygon') (ch.getAttribute('sides') || '').split('|').forEach(function (s) { lblLen = Math.max(lblLen, s.trim().length); });
    });
    if (lblLen) {
      var xAuto = nums(el.getAttribute('x')).length < 2, yAuto = nums(el.getAttribute('y')).length < 2;
      if (xAuto || yAuto) {
        var upu = Math.min((r.x[1] - r.x[0]) / w, (r.y[1] - r.y[0]) / h);
        var padU = (lblLen * 0.32 + 0.9) * f * upu;
        if (xAuto) r.x = [r.x[0] - padU, r.x[1] + padU];
        if (yAuto) r.y = [r.y[0] - padU, r.y[1] + padU];
        if (!el.hasAttribute('free')) {
          var ux2 = (r.x[1] - r.x[0]) / w, uy2 = (r.y[1] - r.y[0]) / h;
          if (ux2 > uy2) { var cy2 = (r.y[0] + r.y[1]) / 2, hy2 = ux2 * h / 2; r.y = [cy2 - hy2, cy2 + hy2]; }
          else { var cx2 = (r.x[0] + r.x[1]) / 2, hx2 = uy2 * w / 2; r.x = [cx2 - hx2, cx2 + hx2]; }
        }
      }
    }
    var c = { text: css('--text'), muted: css('--muted'), border: css('--border-2'), bg: css('--bg') };
    var sx = niceStep(r.x[1] - r.x[0], w, f), sy = niceStep(r.y[1] - r.y[0], h, f);
    if (!el.hasAttribute('free')) { sx = sy = Math.max(sx, sy); }
    var board = JXG.JSXGraph.initBoard(box.id, {
      boundingbox: [r.x[0], r.y[1], r.x[1], r.y[0]], axis: false, grid: false, keepAspectRatio: false,
      showCopyright: false, showNavigation: false, pan: { enabled: false }, zoom: { enabled: false },
      showFullscreen: false, showScreenshot: false, registerEvents: false, renderer: 'svg', resize: { enabled: false }
    });
    el._board = board;
    board.suspendUpdate();
    var sw = Math.max(1.5, f * 0.11);
    if (grid) {
      for (var gx = Math.ceil(r.x[0] / sx) * sx; gx <= r.x[1]; gx += sx) board.create('segment', [[gx, r.y[0]], [gx, r.y[1]]], { strokeColor: '#ffffff', strokeOpacity: 0.07, strokeWidth: 1, fixed: true, highlight: false });
      for (var gy = Math.ceil(r.y[0] / sy) * sy; gy <= r.y[1]; gy += sy) board.create('segment', [[r.x[0], gy], [r.x[1], gy]], { strokeColor: '#ffffff', strokeOpacity: 0.07, strokeWidth: 1, fixed: true, highlight: false });
    }
    var html = '';
    function px(x, y) { var cc = new JXG.Coords(JXG.COORDS_BY_USER, [x, y], board).scrCoords; return { x: cc[1], y: cc[2] }; }
    if (axes) {
      var arrow = { type: 2, size: Math.round(f * 0.35) };
      var yAx = Math.min(Math.max(0, r.x[0]), r.x[1]), xAx = Math.min(Math.max(0, r.y[0]), r.y[1]);
      board.create('arrow', [[r.x[0], xAx], [r.x[1], xAx]], { strokeColor: c.muted, strokeWidth: sw * 0.8, lastArrow: arrow, fixed: true, highlight: false });
      board.create('arrow', [[yAx, r.y[0]], [yAx, r.y[1]]], { strokeColor: c.muted, strokeWidth: sw * 0.8, lastArrow: arrow, fixed: true, highlight: false });
      var tick = 0.22 * f;
      var lblEvery = 1;
      for (var tx = Math.ceil(r.x[0] / sx) * sx; tx < r.x[1] - sx * 0.3; tx += sx) {
        if (Math.abs(tx) < 1e-9) continue;
        var p = px(tx, xAx);
        html += '<div class="ot-lbl" style="left:' + p.x + 'px;top:' + (p.y + 0.8 * f) + 'px;color:' + c.muted + ';font-size:0.85em">' + fmt(tx) + '</div>';
        board.create('segment', [[tx, xAx], [tx, xAx]], { visible: false });
        html += '<div style="position:absolute;left:' + (p.x - 0.5) + 'px;top:' + (p.y - tick) + 'px;width:1px;height:' + 2 * tick + 'px;background:' + c.muted + '"></div>';
      }
      for (var ty = Math.ceil(r.y[0] / sy) * sy; ty < r.y[1] - sy * 0.3; ty += sy) {
        if (Math.abs(ty) < 1e-9) continue;
        var q = px(yAx, ty);
        html += '<div class="ot-lbl" style="left:' + (q.x - 0.55 * f) + 'px;top:' + q.y + 'px;transform:translate(-100%,-50%);color:' + c.muted + ';font-size:0.85em">' + fmt(ty) + '</div>';
        html += '<div style="position:absolute;left:' + (q.x - tick) + 'px;top:' + (q.y - 0.5) + 'px;width:' + 2 * tick + 'px;height:1px;background:' + c.muted + '"></div>';
      }
      void lblEvery;
      var o = px(yAx, xAx);
      if (yAx === 0 && xAx === 0) html += '<div class="ot-lbl" style="left:' + (o.x - 0.55 * f) + 'px;top:' + (o.y + 0.8 * f) + 'px;transform:translate(-100%,-50%);color:' + c.muted + ';font-size:0.85em">0</div>';
      var xe = px(r.x[1], xAx), ye = px(yAx, r.y[1]);
      html += '<div class="ot-lbl" style="left:' + (xe.x - 0.7 * f) + 'px;top:' + (xe.y - 0.9 * f) + 'px;font-style:italic;color:' + c.muted + '">' + esc(el.getAttribute('x-label') || 'x') + '</div>';
      html += '<div class="ot-lbl" style="left:' + (ye.x + 0.8 * f) + 'px;top:' + (ye.y + 0.6 * f) + 'px;font-style:italic;color:' + c.muted + ';transform:translate(0,-50%)">' + esc(el.getAttribute('y-label') || 'y') + '</div>';
    }
    var idx = 0;
    var children = $$(':scope > *', el).filter(function (ch) { return ch.tagName.indexOf('OT-') === 0; });
    // points and corners that function labels should keep clear of
    var taken = [];
    children.forEach(function (ch) {
      if (ch.tagName === 'OT-POINT') taken.push(px(num(ch.getAttribute('x')), num(ch.getAttribute('y'))));
      if (ch.tagName === 'OT-POLYGON' || ch.tagName === 'OT-SEGMENT') points(ch.getAttribute('points') || ((ch.getAttribute('from') || '') + ', ' + (ch.getAttribute('to') || ''))).forEach(function (p) { taken.push(px(p[0], p[1])); });
    });
    // Side/segment labels in creation order, each tied to its actual source edge.
    var sideMeta = el._sideMeta = [];
    var strokeEdges = [];
    children.forEach(function (ch) {
      var tag = ch.tagName.toLowerCase();
      var col = color(ch.getAttribute('color'), SERIES[idx % SERIES.length]);
      var dash = ch.hasAttribute('dashed') ? 2 : 0;
      ch._jxg = [];
      if (ch.hasAttribute('later') || ch.hasAttribute('hidden')) return;
      try {
        if (tag === 'ot-fn') {
          idx++;
          var fn = parseFn(ch.getAttribute('y') || ch.textContent);
          var dom = nums(ch.getAttribute('domain'));
          var g = board.create('functiongraph', [fn].concat(dom.length === 2 ? dom : []), { strokeColor: col, strokeWidth: sw * 1.6, dash: dash, highlight: false, fixed: true });
          ch._jxg.push(g);
          var lab = ch.getAttribute('label');
          if (lab) {
            var spot = fnLabelSpot(fn, r, dom, px, taken, axes ? px(yAx, xAx) : null, f);
            if (spot) {
              var pp = px(spot[0], spot[1]);
              ch._px = pp;
              taken.push(spot[3]);
              html += '<div class="ot-lbl ot-halo" data-for="' + esc(ch.id || '') + '" style="left:' + (pp.x + 0.7 * f) + 'px;top:' + pp.y + 'px;transform:translate(0,' + (spot[2] ? '15%' : '-115%') + ');color:' + col + ';font-weight:700;text-shadow:0 0 0.3em ' + c.bg + ',0 0 0.3em ' + c.bg + '">' + rich(lab) + '</div>';
            }
          }
        } else if (tag === 'ot-point') {
          var x = num(ch.getAttribute('x')), y = num(ch.getAttribute('y'));
          if (isNaN(x) || isNaN(y)) throw new Error('point needs x and y');
          var pcol = color(ch.getAttribute('color'), 'text');
          if (ch.hasAttribute('guides')) {
            var yA = Math.min(Math.max(0, r.x[0]), r.x[1]), xA = Math.min(Math.max(0, r.y[0]), r.y[1]);
            ch._jxg.push(board.create('segment', [[x, y], [x, xA]], { strokeColor: pcol, strokeOpacity: 0.6, dash: 2, strokeWidth: sw, fixed: true, highlight: false }));
            ch._jxg.push(board.create('segment', [[x, y], [yA, y]], { strokeColor: pcol, strokeOpacity: 0.6, dash: 2, strokeWidth: sw, fixed: true, highlight: false }));
          }
          ch._jxg.push(board.create('point', [x, y], { name: '', fixed: true, size: Math.max(3, f * 0.24), fillColor: pcol, strokeColor: c.bg, strokeWidth: Math.max(1.5, f * 0.08), highlight: false, showInfobox: false }));
          var pt = px(x, y); ch._px = pt;
          var t = ch.textContent.trim();
          var pos = (ch.getAttribute('label-pos') || 'ne');
          var tr = { ne: 'translate(18%,-125%)', nw: 'translate(-118%,-125%)', se: 'translate(18%,25%)', sw: 'translate(-118%,25%)', n: 'translate(-50%,-140%)', s: 'translate(-50%,40%)', e: 'translate(30%,-50%)', w: 'translate(-130%,-50%)' }[pos] || 'translate(18%,-125%)';
          if (t) html += '<div class="ot-lbl" style="left:' + pt.x + 'px;top:' + pt.y + 'px;transform:' + tr + ';color:' + pcol + ';font-weight:700;text-shadow:0 0 0.3em ' + c.bg + ',0 0 0.3em ' + c.bg + '">' + rich(t) + '</div>';
        } else if (tag === 'ot-segment' || tag === 'ot-polygon') {
          var pts = tag === 'ot-segment' ? points((ch.getAttribute('from') || '') + ', ' + (ch.getAttribute('to') || '')) : points(ch.getAttribute('points'));
          if (pts.length < 2) throw new Error(tag + ' needs points');
          var edgePoints = pts.map(function (p) { return px(p[0], p[1]); });
          for (var edge = 0; edge < (tag === 'ot-polygon' ? edgePoints.length : 1); edge++) {
            var edgeA = edgePoints[edge], edgeB = edgePoints[(edge + 1) % edgePoints.length];
            strokeEdges.push({ ax: edgeA.x, ay: edgeA.y, bx: edgeB.x, by: edgeB.y });
          }
          var scol = color(ch.getAttribute('color'), tag === 'ot-polygon' ? 'cyan' : 'violet');
          if (tag === 'ot-segment') {
            ch._jxg.push(board.create('segment', pts, { strokeColor: scol, strokeWidth: sw * 1.5, dash: dash, fixed: true, highlight: false }));
            var t2 = ch.textContent.trim();
            if (t2) {
              var pa = px(pts[0][0], pts[0][1]), pb = px(pts[1][0], pts[1][1]);
              // Above the line by default; the fix-up pass may flip a segment label
              // to the clearer side. Metadata ties the label to this edge.
              var ex2 = pb.x - pa.x, ey2 = pb.y - pa.y, el2 = Math.hypot(ex2, ey2) || 1;
              var sx = -ey2 / el2, sy = ex2 / el2;
              if (sy > 0) { sx = -sx; sy = -sy; }
              sideMeta.push({ for: ch.id || '', kind: 'seg', edge: 0, ax: pa.x, ay: pa.y, bx: pb.x, by: pb.y,
                mx: (pa.x + pb.x) / 2, my: (pa.y + pb.y) / 2, nx: sx, ny: sy, poly: null });
              html += sideLabel(pa, pb, sideMeta[sideMeta.length - 1], rich(t2), scol, f, c.bg);
            }
          } else {
            var fill = ch.getAttribute('fill');
            ch._jxg.push(board.create('polygon', pts, {
              fillColor: fill ? color(fill) : scol, fillOpacity: fill === 'none' ? 0 : 0.14, highlight: false, fixed: true,
              vertices: { visible: false }, borders: { strokeColor: scol, strokeWidth: sw * 1.5, highlight: false, fixed: true }
            }));
            var sides = (ch.getAttribute('sides') || '').split('|').map(function (s2) { return s2.trim(); });
            var names = (ch.getAttribute('vertices') || '').split(/\s+/).filter(Boolean);
            var spx = pts.map(function (p2) { return px(p2[0], p2[1]); });
            var cen = spx.reduce(function (a2, p2) { return { x: a2.x + p2.x / spx.length, y: a2.y + p2.y / spx.length }; }, { x: 0, y: 0 });
            // Local outward per edge from the polygon's winding: the vertex mean sits
            // in the notch of a concave shape, so it cannot decide the side. The sign
            // rule holds for both vertex orders; spx is screen pixels either way.
            var area2 = 0;
            spx.forEach(function (p2, k) { var q2 = spx[(k + 1) % spx.length]; area2 += p2.x * q2.y - q2.x * p2.y; });
            var wind = area2 < 0 ? 1 : -1;
            spx.forEach(function (p2, k) {
              var nx = spx[(k + 1) % spx.length];
              if (sides[k]) {
                var ex = nx.x - p2.x, ey = nx.y - p2.y, elen = Math.hypot(ex, ey) || 1;
                sideMeta.push({ for: ch.id || '', kind: 'side', edge: k, ax: p2.x, ay: p2.y, bx: nx.x, by: nx.y,
                  mx: (p2.x + nx.x) / 2, my: (p2.y + nx.y) / 2,
                  nx: -ey / elen * wind, ny: ex / elen * wind, poly: spx.map(function (q2) { return { x: q2.x, y: q2.y }; }) });
                var m = sideMeta[sideMeta.length - 1];
                html += sideLabel(p2, nx, m, rich(sides[k]), c.text, f, c.bg);
              }
              if (names[k]) {
                var dx = p2.x - cen.x, dy = p2.y - cen.y, dl = Math.hypot(dx, dy) || 1;
                html += '<div class="ot-lbl" style="left:' + (p2.x + dx / dl * 1.0 * f) + 'px;top:' + (p2.y + dy / dl * 1.0 * f) + 'px;font-weight:750;font-style:italic">' + esc(names[k]) + '</div>';
              }
              // mark right angles
              if (ch.getAttribute('angles') !== 'off') {
                var pv = spx[(k + spx.length - 1) % spx.length];
                var v1 = { x: pv.x - p2.x, y: pv.y - p2.y }, v2 = { x: nx.x - p2.x, y: nx.y - p2.y };
                var l1 = Math.hypot(v1.x, v1.y), l2 = Math.hypot(v2.x, v2.y);
                if (l1 && l2 && Math.abs((v1.x * v2.x + v1.y * v2.y) / (l1 * l2)) < 0.01) {
                  var q2 = Math.min(0.9 * f, l1 / 3, l2 / 3);
                  var a1 = { x: p2.x + v1.x / l1 * q2, y: p2.y + v1.y / l1 * q2 }, b1 = { x: p2.x + v2.x / l2 * q2, y: p2.y + v2.y / l2 * q2 };
                  html += '<svg style="position:absolute;inset:0;overflow:visible;pointer-events:none" width="' + w + '" height="' + h + '"><path d="M' + a1.x + ' ' + a1.y + ' L' + (a1.x + b1.x - p2.x) + ' ' + (a1.y + b1.y - p2.y) + ' L' + b1.x + ' ' + b1.y + '" fill="none" stroke="' + scol + '" stroke-width="' + Math.max(1.5, sw) + '"/></svg>';
                }
              }
            });
          }
        } else if (tag === 'ot-text') {
          var tp = px(num(ch.getAttribute('x')), num(ch.getAttribute('y')));
          ch._px = tp;
          html += '<div class="ot-lbl" style="left:' + tp.x + 'px;top:' + tp.y + 'px;color:' + color(ch.getAttribute('color'), 'text') + ';text-shadow:0 0 0.3em ' + c.bg + '">' + rich(ch.textContent.trim()) + '</div>';
        }
      } catch (e) {
        issue('graph', (e && e.message) || String(e), ch);
      }
    });
    board.unsuspendUpdate();
    var over = document.createElement('div');
    over.className = 'ot-graph-labels';
    over.style.cssText = 'position:absolute;inset:0;pointer-events:none';
    over.innerHTML = html;
    lay.appendChild(over);
    settleSideLabels(el, over, w, h, f, sw, strokeEdges);
    el._px = px;
  }
  function sideLabel(a, b, out, html, col, f, bg) {
    // `out` is the unit outward normal decided by the caller (winding for polygons,
    // above-the-line default for segments). The first pass centres the label a fixed
    // distance out; settleSideLabels measures the real box and pushes it clear.
    var mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
    var nx = out.nx, ny = out.ny;
    var d = 1.05 * f;
    return '<div class="ot-lbl ot-side-lbl" data-for="' + esc(out.for || '') + '" data-edge="' + out.edge + '"' +
      ' data-kind="' + out.kind + '" style="left:' + (mx + nx * d) + 'px;top:' + (my + ny * d) + 'px;color:' + col + ';font-weight:700;text-shadow:0 0 0.3em ' + bg + ',0 0 0.3em ' + bg + '">' + html + '</div>';
  }
  function inPoly(x, y, poly) {
    var inside = false;
    for (var i = 0, j = poly.length - 1; i < poly.length; j = i++) {
      var xi = poly[i].x, yi = poly[i].y, xj = poly[j].x, yj = poly[j].y;
      if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) inside = !inside;
    }
    return inside;
  }
  // Reach-aware side-label placement from the real boxes. Runs once per graph draw
  // at its final size: offset each label along its outward normal by the half-extent
  // of its own box along that normal (|nx|*w + |ny|*h)/2 plus a line/margin gap,
  // resolve neighbour collisions where cheap, keep labels inside the pane without
  // pushing them back across their own edge, and record what is still crowded in
  // el._graphCrowding for lint. Never shrinks text.
  function settleSideLabels(el, over, w, h, f, sw, strokeEdges) {
    var metas = el._sideMeta || [];
    el._graphCrowding = [];
    if (!metas.length || over.offsetWidth < 2) return;
    var nodes = $$('.ot-side-lbl', over);
    function box(i) {
      var nd = nodes[i];
      var cx = parseFloat(nd.style.left) || 0, cy = parseFloat(nd.style.top) || 0;
      var bw = nd.offsetWidth || 0, bh = nd.offsetHeight || 0;
      return { cx: cx, cy: cy, w: bw, h: bh, l: cx - bw / 2, t: cy - bh / 2, r: cx + bw / 2, b: cy + bh / 2 };
    }
    function place(i, cx, cy) { nodes[i].style.left = cx + 'px'; nodes[i].style.top = cy + 'px'; }
    var gap = 0.25 * f + 1.5 * sw;
    function reach(m, b) { return (Math.abs(m.nx) * b.w + Math.abs(m.ny) * b.h) / 2 + gap; }
    function ownOverlap(m, b) {
      return reach(m, b) - ((b.cx - m.ax) * m.nx + (b.cy - m.ay) * m.ny);
    }
    function hitsStroke(b) {
      var pad = 0.75 * sw;
      return strokeEdges.some(function (e) {
        var dx = e.bx - e.ax, dy = e.by - e.ay, lo = 0, hi = 1;
        var clips = [[-dx, e.ax - b.l + pad], [dx, b.r - e.ax + pad],
                     [-dy, e.ay - b.t + pad], [dy, b.b - e.ay + pad]];
        for (var k = 0; k < clips.length; k++) {
          var p = clips[k][0], q = clips[k][1];
          if (Math.abs(p) < 1e-9) { if (q < 0) return false; }
          else if (p < 0) lo = Math.max(lo, q / p);
          else hi = Math.min(hi, q / p);
          if (lo > hi) return false;
        }
        return true;
      });
    }
    function rectOverlap(b1, b2, pad) {
      var ox = Math.min(b1.r, b2.r) - Math.max(b1.l, b2.l) + pad;
      var oy = Math.min(b1.b, b2.b) - Math.max(b1.t, b2.t) + pad;
      return (ox > 0 && oy > 0) ? Math.min(ox, oy) : 0;
    }
    function clearOfOthers(i, b) {
      for (var k = 0; k < metas.length; k++) {
        if (k === i || !nodes[k]) continue;
        if (rectOverlap(b, box(k), 1) > 0) return false;
      }
      return true;
    }
    // 1) clear each label's own stroke
    metas.forEach(function (m, i) {
      if (!nodes[i]) return;
      var b = box(i);
      if (!b.w || !b.h) return;
      var push = ownOverlap(m, b);
      if (push > 0) place(i, b.cx + m.nx * push, b.cy + m.ny * push);
    });
    // 2) neighbours: nudge along the edge tangent, or flip a segment label
    for (var pass = 0; pass < 2; pass++) {
      var moved = false;
      for (var i = 0; i < metas.length; i++) {
        for (var j = i + 1; j < metas.length; j++) {
          if (!nodes[i] || !nodes[j]) continue;
          var bi = box(i), bj = box(j);
          if (!bj.w || !bj.h) continue;
          if (!rectOverlap(bi, bj, 1)) {
            if (hitsStroke(bj) && tryNudge(j, bi, bj)) moved = true;
            if (hitsStroke(bi) && tryNudge(i, box(j), bi)) moved = true;
            continue;
          }
          if (tryNudge(j, bi, bj) || (metas[j].kind === 'seg' && tryFlip(j, bi)) || (metas[i].kind === 'seg' && tryNudge(i, bj, bi))) { moved = true; }
        }
      }
      if (!moved) break;
    }
    function tryNudge(j, other, bj) {
      var m = metas[j];
      var tx = -m.ny, ty = m.nx;
      var away = ((bj.cx - other.cx) * tx + (bj.cy - other.cy) * ty) >= 0 ? 1 : -1;
      var dirs = [[tx * away, ty * away], [-tx * away, -ty * away], [m.nx, m.ny]];
      for (var dd = 0; dd < dirs.length; dd++) {
        for (var step = 0.5 * f; step <= 1.5 * f + 0.01; step += 0.5 * f) {
          var cand = { cx: bj.cx + dirs[dd][0] * step, cy: bj.cy + dirs[dd][1] * step, w: bj.w, h: bj.h };
          cand.l = cand.cx - cand.w / 2; cand.t = cand.cy - cand.h / 2;
          cand.r = cand.cx + cand.w / 2; cand.b = cand.cy + cand.h / 2;
          // a nudge that lands inside the outlined shape trades one defect for another
          if (m.poly && inPoly(cand.cx, cand.cy, m.poly)) continue;
          if (ownOverlap(m, cand) <= 0 && !hitsStroke(cand) && !rectOverlap(other, cand, 1) && clearOfOthers(j, cand)) {
            place(j, cand.cx, cand.cy);
            return true;
          }
        }
      }
      return false;
    }
    function tryFlip(j, other) {
      var m = metas[j];
      var bj = box(j);
      // mirror the centre across the edge line onto the other side
      var dx = m.bx - m.ax, dy = m.by - m.ay;
      var len2 = dx * dx + dy * dy || 1;
      var t = Math.max(0, Math.min(1, ((bj.cx - m.ax) * dx + (bj.cy - m.ay) * dy) / len2));
      var qx = m.ax + t * dx, qy = m.ay + t * dy;
      var cand = { cx: 2 * qx - bj.cx, cy: 2 * qy - bj.cy, w: bj.w, h: bj.h };
      cand.l = cand.cx - cand.w / 2; cand.t = cand.cy - cand.h / 2;
      cand.r = cand.cx + cand.w / 2; cand.b = cand.cy + cand.h / 2;
      var fm = { nx: -m.nx, ny: -m.ny, bx: m.bx, by: m.by, ax: m.ax, ay: m.ay };
      if (ownOverlap(fm, cand) <= 0 && !hitsStroke(cand) && !rectOverlap(other, cand, 1) && clearOfOthers(j, cand)) {
        m.nx = -m.nx; m.ny = -m.ny;
        place(j, cand.cx, cand.cy);
        return true;
      }
      return false;
    }
    // 3) inside the pane, but never back across the label's own edge
    metas.forEach(function (m, i) {
      if (!nodes[i]) return;
      var b = box(i);
      var dx = b.l < 0 ? -b.l : b.r > w ? w - b.r : 0;
      var dy = b.t < 0 ? -b.t : b.b > h ? h - b.b : 0;
      if (!dx && !dy) return;
      var inw = dx * m.nx + dy * m.ny;
      if (inw < 0) { dx -= inw * m.nx; dy -= inw * m.ny; }
      if (dx || dy) place(i, b.cx + dx, b.cy + dy);
    });
    // 4) what is still crowded becomes lint; placement never pretends to be clean
    var HELP = '; keep given measures; shorten labels, use separate graphs or give the graph more room';
    function nm(i) { return (nodes[i].textContent || '').trim().slice(0, 24) || ('edge ' + (metas[i].edge + 1)); }
    metas.forEach(function (m, i) {
      if (!nodes[i]) return;
      var b = box(i);
      if (!b.w || !b.h) return;
      var ov = ownOverlap(m, b);
      if (ov > 1) el._graphCrowding.push('label \'' + nm(i) + '\' crosses its own line by ' + Math.round(ov) + ' px' + HELP);
      else if (hitsStroke(b)) el._graphCrowding.push('label \'' + nm(i) + '\' crosses an outline' + HELP);
      else if (m.poly && inPoly(b.cx, b.cy, m.poly)) el._graphCrowding.push('label \'' + nm(i) + '\' is inside the outlined shape' + HELP);
      if (b.l < -0.5 || b.t < -0.5 || b.r > w + 0.5 || b.b > h + 0.5)
        el._graphCrowding.push('label \'' + nm(i) + '\' does not fit inside the pane' + HELP);
    });
    for (var a = 0; a < metas.length; a++) {
      for (var c = a + 1; c < metas.length; c++) {
        if (!nodes[a] || !nodes[c]) continue;
        var ov2 = rectOverlap(box(a), box(c), 1);
        if (ov2 > 0) el._graphCrowding.push('labels \'' + nm(a) + '\' and \'' + nm(c) + '\' overlap by ' + Math.round(ov2) + ' px' + HELP);
      }
    }
  }
  // Where to put a function's label: on the curve, inside the view, as far as possible
  // from the axes, the points and the labels already placed. Returns [x, y, rising].
  function fnLabelSpot(fn, r, dom, px, taken, axisPx, f) {
    var x0 = dom.length === 2 ? Math.max(r.x[0], dom[0]) : r.x[0], x1 = dom.length === 2 ? Math.min(r.x[1], dom[1]) : r.x[1];
    var yPad = (r.y[1] - r.y[0]) * 0.1, xPad = (x1 - x0) * 0.08;
    var best = null, bestScore = -Infinity;
    for (var i = 0; i <= 60; i++) {
      var x = x0 + xPad + (x1 - x0 - 2 * xPad) * i / 60;
      var y = fn(x);
      if (!isFinite(y) || y > r.y[1] - yPad || y < r.y[0] + yPad) continue;
      var rising = fn(x + 1e-3) > fn(x - 1e-3);
      var p = px(x, y);
      // the label's own centre sits beside the curve
      var c = { x: p.x + 2.4 * f, y: p.y + (rising ? 1.0 : -1.0) * f };
      var d = Infinity;
      if (axisPx) { d = Math.min(d, Math.abs(c.y - axisPx.y) * 1.4, Math.abs(c.x - axisPx.x)); }
      taken.forEach(function (t) { d = Math.min(d, Math.hypot(c.x - t.x, c.y - t.y)); });
      var score = Math.min(d, 6 * f) + i / 60 * f; // prefer the right-hand side when it is just as clear
      if (score > bestScore) { bestScore = score; best = [x, y, rising, c]; }
    }
    return best;
  }

  function graphPoint(el, child) {
    if (child._jxg) child._jxg.forEach(function (o) {
      try {
        if (o.elType === 'point') o.setAttribute({ size: o.visProp.size * 1.6, strokeColor: css('--cyan'), strokeWidth: 4 });
        else o.setAttribute({ strokeWidth: (o.visProp.strokewidth || 3) * 1.8 });
      } catch (e) { /* ignore */ }
    });
    var undo = function () { el.redraw(); };
    if (child._px && child.tagName === 'OT-POINT') { var ring = ringAt(el, child._px); return function () { ring(); undo(); }; }
    return undo;
  }
  function graphFlash(el, child) {
    (child._jxg || []).forEach(function (o) {
      var n = o.rendNode;
      if (n && n.animate && !reducedMotion()) n.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 700, easing: 'ease-out' });
    });
    if (child._px) flashAt(el, child._px);
  }
  // A cyan ring around a point inside a visual (pointing). Returns an undo.
  function ringAt(host, p) {
    if (!p) { host.classList.add('ot-pointed'); return function () { host.classList.remove('ot-pointed'); }; }
    var f = fontPx();
    var d = document.createElement('div');
    d.style.cssText = 'position:absolute;left:' + (p.x - 1.1 * f) + 'px;top:' + (p.y - 1.1 * f) + 'px;width:' + 2.2 * f + 'px;height:' + 2.2 * f + 'px;border-radius:50%;border:0.16em solid ' + css('--cyan') + ';box-shadow:0 0 0 0.4em rgba(34,211,238,.15);pointer-events:none';
    host.layer().appendChild(d);
    return function () { d.remove(); };
  }
  function flashAt(host, p) {
    var f = fontPx();
    var d = document.createElement('div');
    d.style.cssText = 'position:absolute;left:' + (p.x - 1.4 * f) + 'px;top:' + (p.y - 1.4 * f) + 'px;width:' + 2.8 * f + 'px;height:' + 2.8 * f + 'px;border-radius:50%;background:rgba(167,139,250,.35);pointer-events:none';
    host.layer().appendChild(d);
    animEnd(d.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 1600, easing: 'ease-out' }), 1600, function () { d.remove(); });
  }

  // ---------------------------------------------------------------- chart
  function drawChart(el, w, h, f) {
    if (!window.Chart) { issue('load', 'Chart.js missing', el); return; }
    var table = el.querySelector('table');
    if (!table) { issue('chart', 'ot-chart needs a <table> with the data', el); return; }
    var rows = $$('tr', table).map(function (tr) { return $$('th,td', tr).map(function (c) { return c.textContent.trim(); }); });
    var head = rows.length && $$('th', rows.length ? table.querySelector('tr') : table).length ? rows.shift() : null;
    var labels = rows.map(function (r) { return r[0]; });
    var ncol = Math.max.apply(null, rows.map(function (r) { return r.length; }));
    var type = (el.getAttribute('type') || 'bar').toLowerCase();
    var horizontal = type === 'hbar';
    var c = { text: css('--text'), muted: css('--muted'), grid: 'rgba(255,255,255,0.08)', bg: css('--bg') };
    var datasets = [];
    for (var k = 1; k < ncol; k++) {
      var col = color(SERIES[(k - 1) % SERIES.length]);
      datasets.push({
        label: head ? head[k] : '',
        data: rows.map(function (r) { return num(r[k]); }),
        backgroundColor: type === 'pie' || type === 'doughnut' ? rows.map(function (r, i) { return color(SERIES[i % SERIES.length]); }) : (type === 'line' ? col : alpha(col, 0.85)),
        borderColor: type === 'pie' || type === 'doughnut' ? c.bg : col,
        borderWidth: type === 'line' ? Math.max(2, f * 0.15) : (type === 'pie' || type === 'doughnut' ? 2 : 0),
        pointRadius: type === 'line' ? Math.max(3, f * 0.2) : 0,
        borderRadius: type === 'bar' || horizontal ? 4 : 0,
        tension: 0
      });
    }
    var lay = el.layer();
    if (el._chart) { el._chart.destroy(); el._chart = null; }
    lay.innerHTML = '';
    var canvas = document.createElement('canvas');
    canvas.style.width = w + 'px'; canvas.style.height = h + 'px';
    canvas.width = Math.round(w * (window.devicePixelRatio || 1)); canvas.height = Math.round(h * (window.devicePixelRatio || 1));
    lay.appendChild(canvas);
    Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
    Chart.defaults.font.size = Math.round(f * 0.85);
    Chart.defaults.color = c.muted;
    var unit = el.getAttribute('unit') || '';
    var round = type === 'pie' || type === 'doughnut';
    var multi = datasets.length > 1;
    var valuePlugin = {
      id: 'otValues',
      afterDatasetsDraw: function (chart) {
        if (el.getAttribute('values') === 'off' || type === 'line') return;
        var ctx = chart.ctx;
        ctx.save();
        ctx.font = '700 ' + Math.round(f * 0.85) + 'px ' + Chart.defaults.font.family;
        chart.data.datasets.forEach(function (ds, di) {
          chart.getDatasetMeta(di).data.forEach(function (bar, i) {
            var v = ds.data[i];
            if (!isFinite(v)) return;
            var txt = fmt(v) + (round && unit ? ' ' + unit : '');
            if (round) {
              var pos = bar.tooltipPosition();
              ctx.fillStyle = c.bg; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
              ctx.fillText(txt, pos.x, pos.y);
            } else if (horizontal) {
              ctx.fillStyle = c.text; ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
              ctx.fillText(txt, bar.x + 0.35 * f, bar.y);
            } else {
              ctx.fillStyle = c.text; ctx.textAlign = 'center'; ctx.textBaseline = 'bottom';
              ctx.fillText(txt, bar.x, bar.y - 0.2 * f);
            }
          });
        });
        ctx.restore();
      }
    };
    var scales = round ? {} : {
      x: { grid: { color: horizontal ? c.grid : 'transparent' }, ticks: { color: horizontal ? c.muted : c.text, font: { size: Math.round(f * (horizontal ? 0.8 : 0.9)) } }, beginAtZero: horizontal, border: { color: c.grid } },
      y: { grid: { color: horizontal ? 'transparent' : c.grid }, ticks: { maxTicksLimit: 6, color: horizontal ? c.text : c.muted, callback: function (v) { return horizontal ? this.getLabelForValue(v) : fmt(v); } }, beginAtZero: el.getAttribute('zero') !== 'off', border: { color: c.grid },
           title: { display: !!unit && !horizontal, text: unit, color: c.muted } }
    };
    if (horizontal) scales.x.ticks.callback = function (v) { return fmt(v); };
    el._chart = new Chart(canvas, {
      type: horizontal ? 'bar' : type,
      data: { labels: labels, datasets: datasets },
      options: {
        indexAxis: horizontal ? 'y' : 'x', responsive: false, animation: false, maintainAspectRatio: false,
        devicePixelRatio: window.devicePixelRatio || 1, locale: 'sv-SE',
        layout: { padding: { top: round ? 4 : 1.4 * f, right: horizontal ? 3 * f : 4, left: 4, bottom: 4 } },
        events: [],
        plugins: {
          legend: { display: multi || round, position: round ? 'right' : 'top', labels: { color: c.text, boxWidth: f, boxHeight: f, padding: f * 0.8, font: { size: Math.round(f * 0.9) } } },
          tooltip: { enabled: false }, title: { display: false }
        },
        scales: scales
      },
      plugins: [valuePlugin]
    });
  }

  // ---------------------------------------------------------------- map
  var VIEWS = {
    world: [-168, -56, 180, 78], varlden: [-168, -56, 180, 78], 'världen': [-168, -56, 180, 78],
    europe: [-11, 35, 34, 70], europa: [-11, 35, 34, 70],
    nordic: [-24, 54.5, 32, 71], norden: [-24, 54.5, 32, 71], scandinavia: [4, 54.5, 32, 71], skandinavien: [4, 54.5, 32, 71],
    sweden: [10.5, 55.2, 24.2, 69.1], sverige: [10.5, 55.2, 24.2, 69.1],
    mediterranean: [-9, 29, 37, 47], medelhavet: [-9, 29, 37, 47],
    africa: [-18, -35, 52, 37], afrika: [-18, -35, 52, 37],
    asia: [26, -10, 150, 60], asien: [26, -10, 150, 60],
    'north-america': [-168, 8, -52, 72], nordamerika: [-168, 8, -52, 72],
    'south-america': [-82, -56, -34, 13], sydamerika: [-82, -56, -34, 13],
    'middle-east': [25, 12, 63, 42], 'mellanöstern': [25, 12, 63, 42]
  };
  function nearestHistory(y) {
    var best = HISTORY_YEARS[0];
    HISTORY_YEARS.forEach(function (h) { if (Math.abs(h - y) < Math.abs(best - y)) best = h; });
    return best;
  }
  function historyUrl(y) { return DATA.history + 'world_' + (y < 0 ? 'bc' + (-y) : y) + '.geojson'; }

  // ---- Sweden's 21 län (regions). The shapes travel with the shell, not with the page:
  // screen/shell/data/lan-sverige.json is inlined by compose(), so a region map needs no
  // request and no bytes in the page body (LiveKit RPC is about 15 kB).
  var REGION_WORDS = ['län', 'lan', 'länen', 'lanen', 'regioner', 'counties', 'all'];
  var lanValue;
  function lanData() {
    if (lanValue !== undefined) return lanValue;
    lanValue = null;
    var node = document.getElementById('ot-map-data');
    if (!node) { issue('map', 'the shell has no region data'); return null; }
    try { lanValue = JSON.parse(node.textContent); }
    catch (e) { issue('load', 'could not read the region data: ' + ((e && e.message) || e)); }
    return lanValue;
  }
  function showsRegions(el) {
    var v = (el.getAttribute('regions') || '').trim().toLowerCase();
    if (!v) return false;
    if (REGION_WORDS.indexOf(v) >= 0) return true;
    issue('map', 'unknown regions="' + v + '" (use regions="län")', el);
    return false;
  }
  // "Skåne", "Skåne län", "Region Skåne", "Skånes län", "M", "SE-M" all name the same region.
  function regionKey(s) {
    return String(s || '').trim().toLowerCase()
      .replace(/^region\s+/, '')
      .replace(/\s+län$/, '')
      .replace(/[åä]/g, 'a').replace(/ö/g, 'o')
      .replace(/[^a-z0-9]/g, '');
  }
  function regionIndex(data) {
    var index = {};
    data.regions.forEach(function (r) {
      var k = regionKey(r.name), code = r.code.toLowerCase();
      [k, k + 's', 'lan' + code, 'se' + code, code].forEach(function (key) { index[key] = r; });
    });
    return index;
  }
  function findRegion(index, el) {
    var k = regionKey(el.getAttribute('name') || el.getAttribute('code') || el.textContent);
    if (!k) return null;
    return index[k] || (k.slice(-1) === 's' ? index[k.slice(0, -1)] : null) || null;
  }
  function regionFeature(data, r) {
    var polys = r.parts.map(function (part) {
      var ring = [];
      for (var i = 0; i + 1 < part.length; i += 2) ring.push([part[i] / data.scale, part[i + 1] / data.scale]);
      return [ring];
    });
    return { type: 'Feature', properties: {}, geometry: { type: 'MultiPolygon', coordinates: polys } };
  }
  function regionLabelled(r, data) { return [r.label[0] / data.scale, r.label[1] / data.scale]; }
  // Rounded to whole pixels: neighbours share their border vertices, so identical rounding
  // keeps shared borders identical and the lines clean.
  function regionPath(proj, part, scale) {
    var d = '';
    for (var i = 0; i + 1 < part.length; i += 2) {
      var p = proj([part[i] / scale, part[i + 1] / scale]);
      if (!p || isNaN(p[0]) || isNaN(p[1])) return '';
      d += (i ? 'L' : 'M') + Math.round(p[0]) + ' ' + Math.round(p[1]);
    }
    return d ? d + 'Z' : '';
  }
  function regionShape(r, data, proj, cls, fill, stroke, width) {
    var d = r.parts.map(function (part) { return regionPath(proj, part, data.scale); }).join('');
    if (!d) return '';
    return '<path class="' + cls + '" data-code="' + r.code + '" d="' + d + '" fill="' + fill +
      '" stroke="' + stroke + '" stroke-width="' + width + '" stroke-linejoin="round"/>';
  }
  // Pointing at a region outlines the whole region; anything else keeps the ring.
  function pointRegion(host, child) {
    var code = child && child._region && child._region.code;
    if (code) {
      var shapes = $$('.ot-region-shape[data-code="' + code + '"]', host.layer());
      if (shapes.length) {
        var shape = shapes[shapes.length - 1];
        shape.classList.add('ot-pointed');
        return function () { shape.classList.remove('ot-pointed'); };
      }
    }
    return ringAt(host, child && child._px);
  }
  // Every region of a full map can be pointed at by id `lan-<bokstav>` (lan-M is Skåne).
  function ensureRegionTargets(el) {
    if (el._regionTargets) return el._regionTargets;
    var data = lanData();
    if (!data) return null;
    el._regionTargets = {};
    data.regions.forEach(function (r) {
      var id = 'lan-' + r.code;
      var existing = document.getElementById(id);  // the page may name one itself
      if (existing) { el._regionTargets[r.code] = existing; return; }
      var kid = document.createElement('ot-region');
      kid.id = id;
      kid.setAttribute('name', r.name);
      kid._auto = true;
      kid._region = r;
      el.appendChild(kid);
      el._regionTargets[r.code] = kid;
    });
    return el._regionTargets;
  }
  function regionLabelMode(el, all) {
    var v = (el.getAttribute('labels') || '').trim().toLowerCase();
    if (v) {
      if (['namn', 'names', 'name'].indexOf(v) >= 0) return 'namn';
      if (['kort', 'koder', 'codes', 'nummer'].indexOf(v) >= 0) return 'kort';
      if (['ingen', 'off', 'inga'].indexOf(v) >= 0) return 'ingen';
      issue('map', 'unknown labels="' + v + '" (use labels="namn", "kort" or "ingen")', el);
    }
    // 21 names never fit: the letter codes on the map plus the key below it read at any size.
    return all ? 'kort' : 'namn';
  }
  function regionLegend(data, el) {
    var marked = {};
    $$(':scope > ot-region', el).forEach(function (ch) { if (ch._region && !ch._auto) marked[ch._region.code] = true; });
    return data.regions.slice()
      .sort(function (a, b) { return a.name.localeCompare(b.name, 'sv'); })
      .map(function (r) {
        return '<span class="ot-region-key' + (marked[r.code] ? ' ot-region-key-on' : '') + '" data-code="' +
          r.code + '"><b>' + esc(r.code) + '</b>' + esc(r.name) + '</span>';
      }).join('');
  }
  function mapData(el) {
    var urls = [DATA.countries];
    var year = el.getAttribute('year');
    if (year) urls.push(historyUrl(nearestHistory(num(year))));
    // data already loaded for an earlier map (a patch replacing a map): attach it now, so the
    // new map draws in the same task as the patch
    if (urls.every(function (u) { return u in dataValue; })) {
      el._countries = dataValue[urls[0]]; el._history = urls[1] ? dataValue[urls[1]] : null;
      return Promise.resolve();
    }
    return Promise.all(urls.map(fetchJson)).then(function (r) {
      el._countries = r[0]; el._history = r[1] || null;
      if (booted && el.isConnected) el.redraw();
    });
  }
  function rewind(feature) {
    // d3 wants clockwise rings; GeoJSON files are often the other way round.
    var g = feature.geometry;
    if (!g) return feature;
    var polys = g.type === 'Polygon' ? [g.coordinates] : g.type === 'MultiPolygon' ? g.coordinates : [];
    polys.forEach(function (poly) {
      if (d3.geoArea({ type: 'Polygon', coordinates: poly }) > 2 * Math.PI) poly.forEach(function (ring) { ring.reverse(); });
    });
    return feature;
  }
  function biggestPart(feature) {
    var g = feature.geometry;
    if (!g || g.type !== 'MultiPolygon') return feature;
    var best = null, area = -1;
    g.coordinates.forEach(function (poly) {
      var a = d3.geoArea({ type: 'Polygon', coordinates: poly });
      if (a > area) { area = a; best = poly; }
    });
    return { type: 'Feature', properties: feature.properties, geometry: { type: 'Polygon', coordinates: best } };
  }
  function matchCountry(features, key) {
    key = String(key || '').trim().toLowerCase();
    if (!key) return null;
    var fields = ['ISO_A2_EH', 'ISO_A2', 'ISO_A3_EH', 'ISO_A3', 'ADM0_A3', 'NAME', 'NAME_EN', 'NAME_SV', 'NAME_LONG', 'ADMIN', 'SOVEREIGNT'];
    // field by field, so "Denmark" finds Denmark before Greenland (whose sovereign is Denmark)
    for (var k = 0; k < fields.length; k++) {
      for (var i = 0; i < features.length; i++) {
        var p = features[i].properties || {};
        if (String(p[fields[k]] || '').toLowerCase() === key) return features[i];
      }
    }
    return null;
  }
  function matchArea(features, key) {
    key = String(key || '').trim().toLowerCase();
    var hits = features.filter(function (f2) {
      var p = f2.properties || {};
      return ['NAME', 'ABBREVN', 'SUBJECTO', 'PARTOF'].some(function (k) { return String(p[k] || '').toLowerCase() === key; });
    });
    if (!hits.length) return null;
    var polys = [];
    hits.forEach(function (h) {
      var g = h.geometry;
      if (!g) return;
      if (g.type === 'Polygon') polys.push(g.coordinates); else if (g.type === 'MultiPolygon') polys = polys.concat(g.coordinates);
    });
    return { type: 'Feature', properties: hits[0].properties, geometry: { type: 'MultiPolygon', coordinates: polys } };
  }
  function bboxFeature(b) {
    var pts = [];
    for (var i = 0; i <= 10; i++) {
      var t = i / 10;
      pts.push([b[0] + (b[2] - b[0]) * t, b[1]], [b[0] + (b[2] - b[0]) * t, b[3]], [b[0], b[1] + (b[3] - b[1]) * t], [b[2], b[1] + (b[3] - b[1]) * t]);
    }
    return { type: 'Feature', geometry: { type: 'MultiPoint', coordinates: pts } };
  }
  function drawMap(el, w, h, f) {
    if (!window.d3) { issue('load', 'd3 missing', el); return; }
    if (!el._countries) { issue('map', 'map data not loaded', el); return; }
    var world = el._countries.features.map(rewind);
    var hist = el._history ? el._history.features.filter(function (x) { return x.geometry; }).map(rewind) : null;
    var c = { text: css('--text'), muted: css('--muted'), bg: css('--bg') };
    var ocean = '#16202d', land = '#2b3242', border = '#454f63';
    var focus = [];
    var countries = $$(':scope > ot-country', el), areas = $$(':scope > ot-area', el), places = $$(':scope > ot-place', el);
    countries.forEach(function (ch) {
      var ft = matchCountry(world, ch.getAttribute('name') || ch.textContent);
      if (!ft) { issue('map', 'unknown country "' + (ch.getAttribute('name') || ch.textContent.trim()) + '"', ch); return; }
      ch._ft = ft; focus.push(biggestPart(ft));
    });
    // Swedish län: all 21 with regions="län", or the ones ot-region marks.
    var data = lanData();
    var index = data ? regionIndex(data) : {};
    var allRegions = showsRegions(el) && !!data;
    var targets = allRegions ? ensureRegionTargets(el) : null;
    var marked = [];
    $$(':scope > ot-region', el).forEach(function (ch) {
      if (ch._auto) return;
      var r = data && findRegion(index, ch);
      if (!r) { issue('map', 'unknown region "' + (ch.getAttribute('name') || ch.textContent.trim()) + '" (svenska län)', ch); return; }
      ch._region = r; marked.push(ch);
      focus.push(rewind(regionFeature(data, r)));
    });
    areas.forEach(function (ch) {
      if (!hist) { issue('map', 'ot-area needs year="..." on ot-map', ch); return; }
      var ft = matchArea(hist, ch.getAttribute('name'));
      if (!ft) { issue('map', 'no area named "' + ch.getAttribute('name') + '" in year ' + nearestHistory(num(el.getAttribute('year'))), ch); return; }
      ch._ft = ft; focus.push(ft);
    });
    places.forEach(function (ch) {
      var lat = num(ch.getAttribute('lat')), lon = num(ch.getAttribute('lon') || ch.getAttribute('lng'));
      if (isNaN(lat) || isNaN(lon)) { issue('map', 'place needs lat and lon', ch); return; }
      ch._ll = [lon, lat]; focus.push({ type: 'Feature', geometry: { type: 'Point', coordinates: [lon, lat] } });
    });
    var viewKey = (el.getAttribute('view') || '').trim().toLowerCase();
    var view = VIEWS[viewKey] || (nums(viewKey).length === 4 ? nums(viewKey) : null);
    // d3 reads a ring wound the other way as the rest of the globe, so the fit needs rewind()
    var regions = allRegions ? data.regions.map(function (r) { return rewind(regionFeature(data, r)); }) : null;
    // A full län map is fitted to the 21 real region polygons, not to the `sverige` view box:
    // that box keeps Norway, Finland and the Baltic as context, which left Sweden a small shape
    // in a mostly empty frame. The neighbours are still drawn, as context at the edge of the box.
    var mode = regionLabelMode(el, allRegions);
    var lay = el.layer();
    lay.innerHTML = '';
    lay.classList.remove('ot-map-split', 'ot-map-key-side');
    var credit = hist ? 'Gränser: historical-basemaps · Natural Earth' : 'Natural Earth';
    // The key gets its own normal-flow box, never an overlay over sea or country: a strip under
    // the drawing box on a phone, an upright column beside it on a wide pane. The map is drawn
    // into what is left, so Sweden fills its box instead of sharing it with the key.
    var legend = null, keys = null, draw = lay;
    if (allRegions && mode === 'kort') {
      lay.classList.add('ot-map-split');
      draw = document.createElement('div');
      draw.className = 'ot-map-canvas';
      lay.appendChild(draw);
      legend = document.createElement('div');
      legend.className = 'ot-map-legend';
      legend.innerHTML = '<div class="ot-map-keys">' + regionLegend(data, el) + '</div>' +
        '<span class="ot-map-legend-src">' + esc(credit) + '</span>';
      keys = legend.firstChild;
      lay.appendChild(legend);
    }
    var target;
    if (regions) target = { type: 'FeatureCollection', features: regions };
    else if (view) target = bboxFeature(view);
    else if (focus.length) target = { type: 'FeatureCollection', features: focus };
    else target = bboxFeature(VIEWS.europe);
    var b = d3.geoBounds(target);
    var lon0 = (b[0][0] + b[1][0]) / 2, lat0 = (b[0][1] + b[1][1]) / 2;
    var wide = !regions && (b[1][0] - b[0][0]) > 150;
    function mapProj(areaW, areaH) {
      var p = wide ? d3.geoEqualEarth() : d3.geoAzimuthalEqualArea().rotate([-lon0, -lat0]);
      // A region map is padded by a few percent of its box, so edge codes keep a little air;
      // the country still fills the box.
      var pad = regions ? Math.min(areaW, areaH) * 0.045 : (view ? 0.4 * f : Math.min(areaW, areaH) * 0.08);
      p.fitExtent([[pad, pad], [areaW - pad, areaH - pad]], target);
      return p;
    }
    function boxOf(node) { var r = node.getBoundingClientRect(); return { w: r.width, h: r.height }; }
    var area = boxOf(draw), proj = mapProj(area.w, area.h), side = false;
    if (legend) {
      var count = data.regions.length, layBox = boxOf(lay);
      var sideFont = 0, sideRows = 0;
      // Three key sizes, never below 10 px. Each is measured in the side layout and kept only if
      // it draws the country bigger than the strip under the map does. A pane that is not clearly
      // landscape keeps the key under the map: beside a 333 px map the key would be a third of
      // the width and the drawing box a narrow, unusable column.
      var sizes = [0.68 * f, 0.6 * f, 0.52 * f].filter(function (px) { return px >= 10; });
      var canSide = layBox.w >= 480 && layBox.w > layBox.h * 1.3;
      for (var ti = 0; ti < sizes.length && canSide; ti++) {
        legend.style.fontSize = sizes[ti].toFixed(1) + 'px';
        var rowsFit = Math.max(1, Math.floor((layBox.h * 0.92) / (sizes[ti] * 1.35)));
        // As many columns as the height needs, with the rows shared out evenly between them.
        var rows = Math.ceil(count / Math.ceil(count / rowsFit));
        lay.classList.add('ot-map-key-side');
        keys.style.gridTemplateRows = 'repeat(' + rows + ', auto)';
        var keyBox = boxOf(legend), drawBox = boxOf(draw);
        // The key may take at most 40 % of the width and must fit the height of the box.
        if (keyBox.h <= layBox.h + 0.5 && keyBox.w <= layBox.w * 0.4 && drawBox.w > layBox.w * 0.5) {
          var p2 = mapProj(drawBox.w, drawBox.h);
          if (p2.scale() > proj.scale() * 1.02) {
            proj = p2; area = drawBox; side = true;
            sideFont = sizes[ti]; sideRows = rows;
            break;
          }
        }
        lay.classList.remove('ot-map-key-side');
        keys.style.gridTemplateRows = '';
        legend.style.fontSize = '';
      }
      lay.classList.toggle('ot-map-key-side', side);
      if (side) {
        legend.style.fontSize = sideFont.toFixed(1) + 'px';
        keys.style.gridTemplateRows = 'repeat(' + sideRows + ', auto)';
      }
      // Measure the layout that won, so the projection matches the box it is drawn into.
      area = boxOf(draw);
      proj = mapProj(area.w, area.h);
    }
    var mapH = area.h, mapW = area.w;
    var path = d3.geoPath(proj);
    var s = '<rect width="' + mapW + '" height="' + mapH + '" fill="' + ocean + '" rx="' + 0.6 * f + '"/>';
    s += '<path d="' + path(d3.geoGraticule10()) + '" fill="none" stroke="#ffffff" stroke-opacity="0.05"/>';
    var bordersOn = hist ? el.hasAttribute('borders') : el.getAttribute('borders') !== 'off';
    var neighbourFill = allRegions ? '#242b39' : land;
    world.forEach(function (ft) {
      var d = path(ft);
      if (d) s += '<path d="' + d + '" fill="' + neighbourFill + '" stroke="' + (bordersOn ? border : neighbourFill) + '" stroke-width="' + (bordersOn ? 0.8 : 0.5) + '" stroke-linejoin="round"/>';
    });
    var html = '';
    function labelAt(ft, ch, col) {
      var t = ch.textContent.trim();
      if (!t) return;
      var p = path.centroid(biggestPart(ft));
      if (ch.hasAttribute('label-at')) {
        var ll = nums(ch.getAttribute('label-at'));
        if (ll.length === 2) p = proj([ll[1], ll[0]]);
      }
      if (!p || isNaN(p[0])) return;
      ch._px = { x: p[0], y: p[1] };
      html += '<div class="ot-map-label" style="left:' + p[0] + 'px;top:' + p[1] + 'px;color:' + col + '">' + rich(t) + '</div>';
    }
    areas.forEach(function (ch) {
      if (!ch._ft) return;
      var col = color(ch.getAttribute('color'), 'amber');
      s += '<path d="' + path(ch._ft) + '" fill="' + alpha(col, 0.32) + '" stroke="' + col + '" stroke-width="' + Math.max(1.5, f * 0.1) + '" stroke-linejoin="round"/>';
    });
    countries.forEach(function (ch) {
      if (!ch._ft) return;
      var col = color(ch.getAttribute('color'), 'cyan');
      s += '<path d="' + path(ch._ft) + '" fill="' + alpha(col, 0.35) + '" stroke="' + col + '" stroke-width="' + Math.max(1.5, f * 0.1) + '" stroke-linejoin="round"/>';
    });
    var geoByCode = {};
    if (allRegions) {
      var regionFill = alpha('#9fb2d4', 0.1);
      data.regions.forEach(function (r) {
        s += regionShape(r, data, proj, 'ot-region-shape', regionFill, '#8494b3', Math.max(1, f * 0.05));
        geoByCode[r.code] = r.parts.map(function (part) {
          var ring = [];
          for (var i = 0; i + 1 < part.length; i += 2) {
            var q = proj([part[i] / data.scale, part[i + 1] / data.scale]);
            if (q) ring.push([q[0], q[1]]);
          }
          return ring;
        });
      });
    }
    var markedCodes = {};
    marked.forEach(function (ch) {
      if (!ch._region) return;
      var col = color(ch.getAttribute('color'), 'cyan');
      markedCodes[ch._region.code] = true;
      s += regionShape(ch._region, data, proj, 'ot-region-shape', alpha(col, 0.38), col, Math.max(1.6, f * 0.1));
    });
    if (allRegions && mode !== 'ingen') {
      data.regions.forEach(function (r) {
        var p = proj(regionLabelled(r, data));
        if (!p || isNaN(p[0])) return;
        var kid = targets && targets[r.code];
        if (kid) kid._px = { x: p[0], y: p[1] };
        if (markedCodes[r.code]) return;
        var short = mode === 'kort';
        // Letter codes are sized by the map, not by the page: a tall page font over a small map
        // would put 21 letters the size of Skåne on it.
        var size = short ? ';font-size:' + Math.min(0.7 * f, Math.max(7, mapH / 26)).toFixed(1) + 'px' : '';
        html += '<div class="ot-map-label ot-region-label' + (short ? ' ot-region-code' : '') + '" data-code="' + r.code +
          '" style="left:' + p[0] + 'px;top:' + p[1] + 'px;color:' + (short ? c.text : c.muted) + size + '">' +
          esc(short ? r.code : r.name) + '</div>';
      });
    }
    marked.forEach(function (ch) {
      if (!ch._region) return;
      var p = proj(regionLabelled(ch._region, data));
      if (!p || isNaN(p[0])) return;
      ch._px = { x: p[0], y: p[1] };
      var t = ch.textContent.trim();
      if (t) html += '<div class="ot-map-label ot-region-label" style="left:' + p[0] + 'px;top:' + p[1] + 'px;color:' + color(ch.getAttribute('color'), 'cyan') + '">' + rich(t) + '</div>';
    });
    areas.forEach(function (ch) { if (ch._ft) labelAt(ch._ft, ch, color(ch.getAttribute('color'), 'amber')); });
    countries.forEach(function (ch) { if (ch._ft) labelAt(ch._ft, ch, c.text); });
    places.forEach(function (ch) {
      if (!ch._ll) return;
      var p = proj(ch._ll);
      if (!p || p[0] < 0 || p[1] < 0 || p[0] > mapW || p[1] > mapH) { issue('map', 'place outside the map: ' + ch.textContent.trim(), ch); return; }
      ch._px = { x: p[0], y: p[1] };
      var col = color(ch.getAttribute('color'), 'text');
      var left = ch.getAttribute('side') === 'left' || (ch.getAttribute('side') !== 'right' && p[0] > mapW * 0.82);
      html += '<div class="ot-place-dot" style="left:' + p[0] + 'px;top:' + p[1] + 'px;background:' + col + '"></div>';
      html += '<div class="ot-place-label' + (left ? ' left' : '') + '" style="left:' + p[0] + 'px;top:' + p[1] + 'px;color:' + col + '">' + rich(ch.textContent.trim()) + '</div>';
    });
    if (legend) {
      draw.innerHTML = svg(mapW, mapH, s);
      draw.insertAdjacentHTML('beforeend', html);
    } else {
      lay.innerHTML = svg(w, h, s) + html + '<div class="ot-map-credit">' + credit + '</div>';
    }
    declutter(lay, f, geoByCode, el, area);
  }

  // Map labels: places keep their spot (a place label may flip to the other side of its dot);
  // country and realm labels move up, down or sideways to a free spot, greedily.
  function declutter(lay, f, geoByCode, host, area) {
    var placed = [];
    function box(e) { var r = e.getBoundingClientRect(); return { l: r.left - 2, t: r.top - 1, r: r.right + 2, b: r.bottom + 1 }; }
    function hits(b) { return placed.some(function (p) { return b.l < p.r && b.r > p.l && b.t < p.b && b.b > p.t; }); }
    $$('.ot-place-dot', lay).forEach(function (d) { placed.push(box(d)); });
    $$('.ot-place-label', lay).forEach(function (l) {
      var top0 = parseFloat(l.style.top);
      var tries = [[false, 0], [true, 0], [false, -0.8], [true, -0.8], [false, 0.8], [true, 0.8]];
      var flipped0 = l.classList.contains('left');
      for (var i = 0; i < tries.length; i++) {
        l.classList.toggle('left', tries[i][0] !== flipped0);
        l.style.top = (top0 + tries[i][1] * f) + 'px';
        if (!hits(box(l))) break;
      }
      placed.push(box(l));
    });
    // A map label stays as close to its own spot as it can: the least crowded free spot wins.
    // Region codes are two letters in a crowded country, so they search a fine spiral around
    // their own spot (measured, not re-laid out) and take the quietest place within reach.
    var layer0 = (lay.querySelector(':scope > .ot-map-canvas') || lay).getBoundingClientRect();
    function overlap(a, b) {
      var w = Math.min(a.r, b.r) - Math.max(a.l, b.l);
      var h = Math.min(a.b, b.b) - Math.max(a.t, b.t);
      return w > 0 && h > 0 ? w * h : 0;
    }
    $$('.ot-map-label', lay).forEach(function (l) {
      if (l.classList.contains('ot-region-code')) return;
      var x0 = parseFloat(l.style.left), y0 = parseFloat(l.style.top);
      var tries = [[0, 0], [0, -1.1], [0, 1.1], [-2.5, 0], [2.5, 0], [0, -2.2], [0, 2.2], [-2.5, -1.1], [2.5, 1.1]];
      var bestAt = [x0, y0], bestCost = Infinity;
      for (var i = 0; i < tries.length; i++) {
        l.style.left = (x0 + tries[i][0] * f) + 'px';
        l.style.top = (y0 + tries[i][1] * f) + 'px';
        var bx = box(l), cost = 0;
        for (var k = 0; k < placed.length; k++) cost += overlap(bx, placed[k]);
        if (cost < bestCost) { bestCost = cost; bestAt = [x0 + tries[i][0] * f, y0 + tries[i][1] * f]; if (!cost) break; }
      }
      l.style.left = bestAt[0] + 'px'; l.style.top = bestAt[1] + 'px';
      placed.push(box(l));
    });
    function inside(rings, x, y) {
      if (!rings) return true;
      var hit = false;
      for (var i = 0; i < rings.length; i++) {
        var ring = rings[i];
        for (var a = 0, k = ring.length - 1; a < ring.length; k = a++) {
          var xi = ring[a][0], yi = ring[a][1], xk = ring[k][0], yk = ring[k][1];
          if ((yi > y) !== (yk > y) && x < (xk - xi) * (y - yi) / (yk - yi) + xi) hit = !hit;
        }
      }
      return hit;
    }
    // 2.5 px of air around each code: labels this close read as one word.
    var PX = 2.5, PY = 2, OUTSIDE = 260;  // OUTSIDE: what it costs to leave the region
    var skipped = 0, codeCount = 0, crowded = 0;
    $$('.ot-region-code', lay).forEach(function (l) {
      codeCount++;
      var w = l.offsetWidth, h = l.offsetHeight;
      var x0 = parseFloat(l.style.left), y0 = parseFloat(l.style.top);
      var rings = geoByCode && geoByCode[l.getAttribute('data-code')];
      function at(dx, dy) {
        return { l: layer0.left + x0 + dx - w / 2 - PX, t: layer0.top + y0 + dy - h / 2 - PY,
                 r: layer0.left + x0 + dx + w / 2 + PX, b: layer0.top + y0 + dy + h / 2 + PY };
      }
      // A code prefers its own region, then a clean window: a spot outside the region costs
      // extra, and a spot that overlaps another label costs the overlap. Least total wins,
      // so a narrow region is labelled just beside itself with a leader, not on top of a neighbour.
      var best = null, bestScore = Infinity, bestInside = false;
      for (var r = 0; r <= 3.2 * f; r += 0.3 * f) {
        var n = r ? 16 : 1;
        for (var a = 0; a < n; a++) {
          var ang = (a / n) * Math.PI * 2;
          var dx0 = r * Math.cos(ang), dy0 = r * Math.sin(ang);
          // A code stays on the map, never in the key beside it.
          if (area && (x0 + dx0 - w / 2 < 0.02 * area.w || x0 + dx0 + w / 2 > area.w - 0.02 * area.w ||
              y0 + dy0 - h / 2 < 0 || y0 + dy0 + h / 2 > area.h)) continue;
          var bx = at(dx0, dy0), cost = 0, ins = inside(rings, x0 + dx0, y0 + dy0);
          for (var k = 0; k < placed.length; k++) cost += overlap(bx, placed[k]);
          var score = cost + 0.3 * (dx0 * dx0 + dy0 * dy0) + (ins ? 0 : OUTSIDE);
          if (score < bestScore) { bestScore = score; best = bx; bestInside = ins; }
        }
      }
      if (!best) {
        l.hidden = true; skipped++;
        var nokey = lay.querySelector('.ot-region-key[data-code="' + l.getAttribute('data-code') + '"]');
        if (nokey) nokey.classList.add('ot-region-key-off');
        return;
      }
      var bestCost = 0;
      for (var k3 = 0; k3 < placed.length; k3++) bestCost += overlap(best, placed[k3]);
      if (bestCost > 0.35 * w * h) {
        l.hidden = true; skipped++;
        var key = lay.querySelector('.ot-region-key[data-code="' + l.getAttribute('data-code') + '"]');
        if (key) key.classList.add('ot-region-key-off');
        return;
      }
      for (var c3 = 0; c3 < placed.length; c3++) {
        var ow = Math.min(best.r, placed[c3].r) - Math.max(best.l, placed[c3].l) - 2 * PX;
        var oh = Math.min(best.b, placed[c3].b) - Math.max(best.t, placed[c3].t) - 2 * PY;
        if (ow > 1 && oh > 1) { crowded++; break; }
      }
      var dx = (best.l + best.r) / 2 - layer0.left - x0, dy = (best.t + best.b) / 2 - layer0.top - y0;
      l.style.left = (x0 + dx) + 'px';
      l.style.top = (y0 + dy) + 'px';
      placed.push(best);
      // a code that had to move gets a thin leader so it still points at its own region
      if (!bestInside || Math.sqrt(dx * dx + dy * dy) > 0.8 * f) {
        var lead = document.createElement('div');
        lead.className = 'ot-region-leader';
        lead.style.left = x0 + 'px';
        lead.style.top = y0 + 'px';
        lead.style.width = Math.sqrt(dx * dx + dy * dy) + 'px';
        lead.style.transform = 'rotate(' + Math.atan2(dy, dx) + 'rad)';
        lay.appendChild(lead);
      }
    });
    // A map too small for 21 codes reads better as borders plus the key, than as a pile of
    // letters. Say so, so the screen model can give the map more room or show fewer regions.
    if (skipped) {
      issue('crowded', skipped + ' of ' + codeCount + ' regions have no letter on the map at this size ' +
        "(their rows in the key are dimmed): give the map more height or show fewer regions", host);
    }
    if (codeCount && (skipped + crowded) > 0.5 * codeCount) {
      $$('.ot-region-code', lay).forEach(function (l) { l.hidden = true; });
      $$('.ot-region-leader', lay).forEach(function (l) { l.remove(); });
      issue('crowded', 'the regions are too small for letter codes on this map (' + (skipped + crowded) + ' of ' +
        codeCount + ' did not fit): the key names them. Give the map more height or show fewer regions', host);
    }
  }

  // ---------------------------------------------------------------- images
  function resolveImage(el) {
    var src = el.getAttribute('src');
    if (src) return Promise.resolve({ src: src, credit: el.getAttribute('credit') || '' });
    var q = el.getAttribute('query');
    if (!q) return Promise.resolve(null);
    var api = 'https://commons.wikimedia.org/w/api.php?action=query&format=json&origin=*&generator=search&gsrnamespace=6&gsrlimit=6' +
      '&gsrsearch=' + encodeURIComponent('filetype:bitmap ' + q) + '&prop=imageinfo&iiprop=url|extmetadata|size&iiurlwidth=1280';
    return fetch(api).then(function (r) { return r.json(); }).then(function (data) {
      var pages = data && data.query && data.query.pages ? Object.keys(data.query.pages).map(function (k) { return data.query.pages[k]; }) : [];
      pages.sort(function (a, b) { return (a.index || 0) - (b.index || 0); });
      var pick = pages.find(function (p) { var ii = p.imageinfo && p.imageinfo[0]; return ii && ii.width >= 600; }) || pages[0];
      if (!pick) return null;
      var ii = pick.imageinfo[0], md = ii.extmetadata || {};
      var artist = md.Artist ? String(md.Artist.value).replace(/<[^>]*>/g, '').trim() : '';
      var lic = md.LicenseShortName ? md.LicenseShortName.value : '';
      return { src: ii.thumburl || ii.url, credit: 'Bild: ' + [artist, lic, 'Wikimedia Commons'].filter(Boolean).join(', ') };
    }).catch(function (e) { issue('image', 'image search failed: ' + e.message, el); return null; });
  }
  function drawImageLabels(el, w, h, f) {
    var lay = el.layer();
    lay.innerHTML = '';
    var labels = $$(':scope > ot-label', el);
    var img = el._img;
    if (!labels.length || !img || !img.naturalWidth) return;
    var wrap = img.parentNode;
    var bw = wrap.clientWidth, bh = wrap.clientHeight;
    var sc = Math.min(bw / img.naturalWidth, bh / img.naturalHeight);
    var iw = img.naturalWidth * sc, ih = img.naturalHeight * sc, ix = (bw - iw) / 2, iy = (bh - ih) / 2;
    var items = labels.map(function (lb) {
      var at = nums(lb.getAttribute('at'));
      var p = { x: ix + (at[0] || 0) / 100 * iw, y: iy + (at[1] || 0) / 100 * ih };
      return { el: lb, p: p, left: (at[0] || 0) < 50 };
    });
    var s = '', html = '';
    ['left', 'right'].forEach(function (side) {
      var group = items.filter(function (it) { return (side === 'left') === it.left; }).sort(function (a, b) { return a.p.y - b.p.y; });
      var minGap = 2.0 * f, lastY = -Infinity;
      group.forEach(function (it) { it.ly = Math.max(it.p.y, lastY + minGap); lastY = it.ly; });
      var over = lastY - (bh - f);
      if (over > 0) group.forEach(function (it) { it.ly -= over; });
      group.forEach(function (it) {
        var room = side === 'left' ? ix : bw - ix - iw;
        var lx = side === 'left' ? Math.max(0.3 * f, ix - Math.min(room, 0.5 * f) - 0.5 * f) : Math.min(bw - 0.3 * f, ix + iw + Math.min(room, 0.5 * f) + 0.5 * f);
        var tx = side === 'left' ? Math.min(lx, it.p.x - 2 * f) : Math.max(lx, it.p.x + 2 * f);
        s += line(it.p.x, it.p.y, tx, it.ly, css('--cyan'), Math.max(1.5, f * 0.09));
        html += '<div class="ot-pin" style="left:' + it.p.x + 'px;top:' + it.p.y + 'px"></div>';
        html += '<div class="ot-pin-label" id="' + esc(it.el.id ? it.el.id + '-view' : '') + '" style="top:' + it.ly + 'px;' + (side === 'left' ? 'right:' + (bw - tx) + 'px' : 'left:' + tx + 'px') + '">' + rich(it.el.textContent.trim()) + '</div>';
        it.el._px = { x: it.p.x, y: it.p.y };
      });
    });
    lay.style.bottom = '1.4em';
    lay.innerHTML = svg(bw, bh, s) + html;
    // a label that would leave the picture's box is pulled back to its edge
    var lb = lay.getBoundingClientRect();
    $$('.ot-pin-label', lay).forEach(function (l) {
      var r = l.getBoundingClientRect();
      if (r.right > lb.right) { l.style.left = ''; l.style.right = 0.2 * f + 'px'; }
      if (r.left < lb.left) { l.style.right = ''; l.style.left = 0.2 * f + 'px'; }
    });
    labels.forEach(function (lb) { if (lb.id) lb._view = lay.querySelector('#' + CSS.escape(lb.id + '-view')); });
  }

  // ---------------------------------------------------------------- cycle / mind map
  function drawRing(el, w, h, f, kind) {
    var lay = el.layer();
    var items = $$(kind === 'cycle' ? ':scope > ot-item' : ':scope > ot-node', el);
    var center = el.getAttribute('center');
    lay.innerHTML = '';
    var c = { violet: css('--violet'), muted: css('--muted'), border: css('--border-2') };
    var n = items.length;
    if (!n) return;
    // Narrow boxes (portrait) read better as a column than as a squeezed ring.
    var column = window.innerWidth < window.innerHeight;
    var maxW = column ? w - (kind === 'cycle' ? 3.2 * f : 3.4 * f) : Math.min(12 * f, Math.max(7 * f, w * 0.31));
    var boxes = items.map(function (it) {
      var d = document.createElement('div');
      d.className = 'ot-node-box';
      d.style.maxWidth = maxW + 'px';
      d.style.width = column ? maxW + 'px' : 'max-content';
      if (column) d.style.fontSize = '1em';
      var col = it.getAttribute('color');
      if (col) d.style.borderColor = color(col);
      d.innerHTML = it.innerHTML;
      lay.appendChild(d);
      it._view = d;
      return d;
    });
    renderMath(lay);
    var cbox = null;
    if (center) {
      cbox = document.createElement('div');
      cbox.className = 'ot-node-box ot-node-center';
      cbox.style.maxWidth = (column ? maxW : Math.min(10 * f, w * 0.26)) + 'px';
      cbox.style.width = 'max-content';
      cbox.innerHTML = rich(center);
      lay.appendChild(cbox);
    }
    var sizes = boxes.map(function (b) { return { w: b.offsetWidth, h: b.offsetHeight }; });
    var cs = cbox ? { w: cbox.offsetWidth, h: cbox.offsetHeight } : { w: 0, h: 0 };
    var s = '', sw = Math.max(2, f * 0.12);
    var arrowDef = '<defs><marker id="ot-arr-' + kind + '" viewBox="0 0 10 10" refX="7" refY="5" markerWidth="4" markerHeight="4" orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10 z" fill="' + c.violet + '"/></marker></defs>';
    var pos = [], res = true;
    if (column) {
      // stacked: centre (if any) on top, items below; spread over the box height
      var total = sizes.reduce(function (a, z) { return a + z.h; }, 0) + (cbox ? cs.h : 0);
      var free = Math.max(0, h - total - 0.4 * f);
      var step = Math.max(0.9 * f, Math.min(2.2 * f, free / Math.max(1, n - 1 + (cbox ? 1 : 0))));
      var y = 0.2 * f;
      var x0 = kind === 'cycle' ? 0.4 * f : 2.6 * f;
      if (cbox) {
        cbox.style.transform = 'none';
        cbox.style.left = (kind === 'cycle' ? x0 : 0.2 * f) + 'px'; cbox.style.top = y + 'px';
        y += cs.h + step;
      }
      boxes.forEach(function (b, i) {
        b.style.transform = 'none';
        b.style.left = x0 + 'px'; b.style.top = y + 'px';
        pos.push({ x: x0 + sizes[i].w / 2, y: y + sizes[i].h / 2, top: y, bottom: y + sizes[i].h });
        y += sizes[i].h + step;
      });
      if (y - step > h + 1) res = { ok: false, needEm: (y - step) / f + 0.4, msg: kind + ' does not fit: shorten the texts or use fewer items' };
      if (kind === 'cycle') {
        s += arrowDef;
        for (var k = 0; k + 1 < n; k++) {
          var xm = x0 + maxW * 0.5;
          s += '<path d="M' + xm + ' ' + (pos[k].bottom + 0.15 * f) + ' L' + xm + ' ' + (pos[k + 1].top - 0.25 * f) + '" stroke="' + c.violet + '" stroke-width="' + sw + '" marker-end="url(#ot-arr-cycle)"/>';
        }
        // the way back: along the right edge from the last box to the first
        var xr = x0 + maxW + 0.3 * f, xe = x0 + maxW + 1.6 * f;
        s += '<path d="M' + xr + ' ' + pos[n - 1].y + ' L' + xe + ' ' + pos[n - 1].y + ' L' + xe + ' ' + pos[0].y + ' L' + (xr + 0.25 * f) + ' ' + pos[0].y + '" fill="none" stroke="' + c.violet + '" stroke-width="' + sw + '" stroke-linejoin="round" marker-end="url(#ot-arr-cycle)"/>';
      } else {
        var tx = 1.2 * f, ty = cbox ? 0.2 * f + cs.h : 0;
        if (cbox) s += '<path d="M' + tx + ' ' + ty + ' L' + tx + ' ' + pos[n - 1].y + '" fill="none" stroke="' + c.violet + '" stroke-width="' + sw + '"/>';
        pos.forEach(function (p, k2) {
          var col = items[k2].getAttribute('color') ? color(items[k2].getAttribute('color')) : c.violet;
          s += '<path d="M' + tx + ' ' + p.y + ' L' + (x0 - 0.15 * f) + ' ' + p.y + '" stroke="' + col + '" stroke-width="' + sw + '"/>';
        });
      }
    } else {
      var mw = Math.max.apply(null, sizes.map(function (z) { return z.w; })), mh = Math.max.apply(null, sizes.map(function (z) { return z.h; }));
      var rx = Math.max(0, (w - mw) / 2 - 0.2 * f), ry = Math.max(0, (h - mh) / 2 - 0.2 * f);
      var cx = w / 2, cy = h / 2;
      boxes.forEach(function (b, i) {
        var a = -Math.PI / 2 + i * 2 * Math.PI / n;
        var p = { x: cx + rx * Math.cos(a), y: cy + ry * Math.sin(a), a: a };
        b.style.left = p.x + 'px'; b.style.top = p.y + 'px';
        pos.push(p);
      });
      if (cbox) { cbox.style.left = cx + 'px'; cbox.style.top = cy + 'px'; }
      var rects = pos.map(function (p, i) { return { x: p.x, y: p.y, w: sizes[i].w, h: sizes[i].h }; });
      if (cbox) rects.push({ x: cx, y: cy, w: cs.w, h: cs.h });
      outer: for (var i = 0; i < rects.length; i++) for (var j = i + 1; j < rects.length; j++) {
        if (Math.abs(rects[i].x - rects[j].x) < (rects[i].w + rects[j].w) / 2 + 0.2 * f && Math.abs(rects[i].y - rects[j].y) < (rects[i].h + rects[j].h) / 2 + 0.2 * f) {
          res = { ok: false, msg: kind + ' boxes overlap: shorten the texts or use fewer items' };
          break outer;
        }
      }
      var inside = function (p, k3, m) { return Math.abs(p.x - pos[k3].x) < sizes[k3].w / 2 + m && Math.abs(p.y - pos[k3].y) < sizes[k3].h / 2 + m; };
      if (kind === 'cycle') {
        s += arrowDef;
        for (var k4 = 0; k4 < n; k4++) {
          var a0 = pos[k4].a, a1 = k4 + 1 < n ? pos[k4 + 1].a : pos[0].a + 2 * Math.PI;
          var pts = [];
          for (var t = 0; t <= 90; t++) {
            var aa = a0 + (a1 - a0) * t / 90;
            var q = { x: cx + rx * Math.cos(aa), y: cy + ry * Math.sin(aa) };
            if (inside(q, k4, 0.4 * f) || inside(q, (k4 + 1) % n, 0.4 * f)) continue;
            pts.push(q);
          }
          if (pts.length > 1) s += '<path d="M' + pts.map(function (q2) { return q2.x.toFixed(1) + ' ' + q2.y.toFixed(1); }).join(' L') + '" fill="none" stroke="' + c.violet + '" stroke-width="' + sw + '" marker-end="url(#ot-arr-cycle)"/>';
        }
      } else {
        pos.forEach(function (p, k5) {
          var col = items[k5].getAttribute('color') ? color(items[k5].getAttribute('color')) : c.violet;
          var dx = p.x - cx, dy = p.y - cy;
          var tc = Math.min(Math.abs((cs.w / 2 + 0.2 * f) / (dx || 1e-9)), Math.abs((cs.h / 2 + 0.2 * f) / (dy || 1e-9)));
          var tn = Math.min(Math.abs((sizes[k5].w / 2 + 0.2 * f) / (dx || 1e-9)), Math.abs((sizes[k5].h / 2 + 0.2 * f) / (dy || 1e-9)));
          var x1 = cx + dx * tc, y1 = cy + dy * tc, x2 = p.x - dx * tn, y2 = p.y - dy * tn;
          s += '<path d="M' + x1 + ' ' + y1 + ' C' + (x1 + (x2 - x1) * 0.5) + ' ' + y1 + ' ' + (x1 + (x2 - x1) * 0.5) + ' ' + y2 + ' ' + x2 + ' ' + y2 + '" fill="none" stroke="' + col + '" stroke-opacity="0.85" stroke-width="' + sw + '"/>';
        });
      }
    }
    var svgEl = document.createElement('div');
    svgEl.style.cssText = 'position:absolute;inset:0;pointer-events:none';
    svgEl.innerHTML = svg(w, h, s);
    lay.insertBefore(svgEl, lay.firstChild);
    return res;
  }

  // ---------------------------------------------------------------- fit
  var GROWABLE = 'ot-graph, ot-map, ot-chart, ot-image, ot-clock, ot-balance, ot-cycle, ot-mindmap, .grow';
  function markGrowth() {
    $$('.ot-grows').forEach(function (e) { e.classList.remove('ot-grows'); });
    $$(GROWABLE, page).forEach(function (v) {
      for (var p = v.parentElement; p && p !== page; p = p.parentElement) p.classList.add('ot-grows');
    });
  }
  function overflows() {
    var H = window.innerHeight, W = window.innerWidth;
    return page.scrollHeight > H + 0.5 || page.scrollWidth > page.clientWidth + 0.5 || document.documentElement.scrollWidth > W + 0.5;
  }
  function measureAt(px) {
    document.documentElement.style.fontSize = px + 'px';
    return !overflows();
  }
  function fit(maxPx) {
    var root = document.documentElement;
    root.classList.add('ot-measure');
    root.classList.remove('ot-settled');
    page.style.transform = ''; page.style.width = '';
    var W = window.innerWidth, H = window.innerHeight;
    var hi = Math.min(W / 21, H / 23, 34);
    if (maxPx) hi = Math.min(hi, maxPx);
    var lo = MIN_FONT, best = lo;
    if (measureAt(hi)) best = hi;
    else {
      for (var i = 0; i < 9; i++) {
        var mid = (lo + hi) / 2;
        if (measureAt(mid)) { best = mid; lo = mid; } else hi = mid;
      }
    }
    best = Math.floor(best * 4) / 4;
    var fits = measureAt(best);
    if (!fits) {
      var scale = Math.min(H / page.scrollHeight, W / page.scrollWidth);
      issue('overflow', 'page does not fit even at ' + best + 'px text; it was shrunk to ' + Math.round(scale * 100) + '%. Cut content or split the page.');
      page.style.transformOrigin = 'top left';
      page.style.width = (W / scale) + 'px';
      page.style.transform = 'scale(' + scale + ')';
    }
    root.classList.remove('ot-measure');
    root.classList.add('ot-settled');
    ot.fontPx = best;
    return best;
  }
  var VISUALS = 'ot-graph, ot-map, ot-chart, ot-image, ot-clock, ot-balance, ot-cycle, ot-mindmap, ot-numberline, ot-fraction';
  // Draw every visual at its final size. Returns the ones that said they do not fit.
  function drawVisuals(root) {
    var bad = [];
    $$(VISUALS, root || page).forEach(function (v) {
      if (!v.redraw) return;
      var r = v.redraw();
      if (r && r.ok === false) bad.push({ el: v, r: r });
    });
    return bad;
  }
  function settle(keepFont) {
    markGrowth();
    var px;
    if (keepFont) {
      document.documentElement.classList.add('ot-measure');
      var ok = measureAt(ot.fontPx);
      document.documentElement.classList.remove('ot-measure');
      px = ok ? ot.fontPx : fit(ot.fontPx);
    } else px = fit();
    // A crowded visual asks for more height or for smaller text; refit until it fits.
    var bad = drawVisuals(), cap = px;
    for (var attempt = 0; bad.length && attempt < 6; attempt++) {
      bad.forEach(function (b) {
        if (b.r.needEm && b.r.needEm > (parseFloat(b.el.style.minHeight) || 0) + 0.05) b.el.style.minHeight = b.r.needEm.toFixed(2) + 'em';
        else cap = Math.min(cap, px * 0.9);
      });
      px = fit(cap);
      bad = drawVisuals();
    }
    bad.forEach(function (b) { issue('crowded', b.r.msg || 'does not fit', b.el); });
    lintGraphs();
    var scale = page.offsetWidth ? page.getBoundingClientRect().width / page.offsetWidth : 1;
    var readable = window.innerWidth <= 600 ? 16 : SMALL_FONT;
    var textPx = Math.floor(px * scale * 100) / 100;
    if (textPx < readable) issue('dense', 'text is only ' + textPx + 'px on this screen (minimum ' + readable + 'px). Keep one teaching step and one main visual; cut text or split the page.');
    $$('h1', page).forEach(function (heading) {
      var line = parseFloat(getComputedStyle(heading).lineHeight);
      if (heading.offsetHeight > line * 2.25) issue('heading', 'title takes more than two lines. Use a short title of two to four words; put the question below it.', heading);
    });
    return px;
  }

  // Graph label overlap, measured from the delivered placement: last round's
  // findings go first so lint describes what is on screen now, never a stale
  // or intermediate fit pass. drawGraph records per-graph findings; the crowded
  // kind already earns the existing bounded retry, whose wording names the fix.
  function lintGraphs() {
    var removedReported = 0;
    ot.issues = ot.issues.filter(function (i, index) {
      var remove = i.kind === 'crowded' && i.where && i.where.indexOf('<ot-graph') === 0 && /^labels? /.test(i.msg);
      if (remove && index < reported) removedReported++;
      return !remove;
    });
    reported = Math.max(0, reported - removedReported);
    $$('ot-graph', page).forEach(function (el) {
      // Boot temporarily hides the entire body. Only semantic hiding suppresses
      // findings here; these labels become visible as soon as boot finishes.
      if (!el.getClientRects().length || el.closest('[later], [hidden], ot-hidden:not([data-revealed]) .ot-hidden-body')) return;
      (el._graphCrowding || []).forEach(function (msg) { issue('crowded', msg, el); });
    });
  }
  // ---------------------------------------------------------------- lint
  function lint() {
    var seen = {};
    $$('[id]', page).forEach(function (el) {
      if (seen[el.id]) issue('id', 'duplicate id "' + el.id + '"', el);
      seen[el.id] = true;
    });
    $$('*', page).forEach(function (el) {
      var t = el.tagName.toLowerCase();
      if (t.indexOf('ot-') === 0 && !REGISTRY[t]) issue('tag', 'unknown tag <' + t + '>', el);
      if (t === 'ot-patch') issue('tag', '<ot-patch> belongs in a patch, not in the page body', el);
    });
    $$('.katex-error', page).forEach(function (el) { issue('math', 'KaTeX error: ' + (el.getAttribute('title') || el.textContent), el); });
  }

  // ---------------------------------------------------------------- change effects
  function rectOf(el) {
    var r = el.getBoundingClientRect();
    if (r.width || r.height) return r;
    var kids = Array.prototype.slice.call(el.children).map(function (k) { return k.getBoundingClientRect(); }).filter(function (k) { return k.width || k.height; });
    if (!kids.length) return null;
    var x0 = Math.min.apply(null, kids.map(function (k) { return k.left; })), y0 = Math.min.apply(null, kids.map(function (k) { return k.top; }));
    var x1 = Math.max.apply(null, kids.map(function (k) { return k.right; })), y1 = Math.max.apply(null, kids.map(function (k) { return k.bottom; }));
    return { left: x0, top: y0, width: x1 - x0, height: y1 - y0 };
  }
  // A soft violet glow over what changed, fading out. Never a redraw of the page.
  // Web Animations never finish in a hidden pane (or a throttled background tab):
  // the timer makes sure the end state is always reached.
  function animEnd(anim, ms, fn) {
    var done = false;
    function fin() { if (done) return; done = true; try { fn(); } catch (e) { /* ignore */ } }
    if (anim) { try { anim.onfinish = fin; } catch (e) { /* no WAAPI */ } }
    setTimeout(fin, (ms || 500) + 800);
  }
  function flash(el) {
    if (!el) return;
    var target = el._view || el;
    var r = rectOf(target);
    if (!r) {
      var host = el.parentElement && el.parentElement.closest('ot-graph, ot-map, ot-numberline, ot-image, ot-cycle, ot-mindmap, ot-chart');
      if (host && host.flashChild) return host.flashChild(el);
      if (el._px && host) return flashAt(host, el._px);
      if (host) return flash(host);
      return;
    }
    var f = fontPx();
    var d = document.createElement('div');
    d.style.cssText = 'position:fixed;pointer-events:none;border-radius:' + 0.45 * f + 'px;background:rgba(167,139,250,0.15);box-shadow:0 0 0 ' + 0.2 * f + 'px rgba(167,139,250,0.3);z-index:10;' +
      'left:' + (r.left - 0.25 * f) + 'px;top:' + (r.top - 0.15 * f) + 'px;width:' + (r.width + 0.5 * f) + 'px;height:' + (r.height + 0.3 * f) + 'px';
    document.body.appendChild(d);
    var dur = reducedMotion() ? 1400 : 2000;
    animEnd(d.animate([{ opacity: 1 }, { opacity: 1, offset: 0.25 }, { opacity: 0 }], { duration: dur, easing: 'ease-out' }), dur, function () { d.remove(); });
  }
  function fadeIn(el, from) {
    if (reducedMotion() || !el.animate) return;
    var target = el._view || el;
    if (getComputedStyle(target).display === 'contents') {
      Array.prototype.slice.call(target.children).forEach(function (k) { k.animate([{ opacity: from }, { opacity: 1 }], { duration: 450, easing: 'ease-out' }); });
    } else target.animate([{ opacity: from }, { opacity: 1 }], { duration: 450, easing: 'ease-out' });
  }

  // ---------------------------------------------------------------- public api
  var drafts = {};
  var draftTimer = null;
  function draft(id, value) {
    drafts[id] = value;
    clearTimeout(draftTimer);
    draftTimer = setTimeout(function () { post({ ot: 'input', id: id, value: value }); }, 300);
  }
  ot.state = function () { return Object.assign({}, drafts); };
  ot.restore = function (state) {
    Object.keys(state || {}).forEach(function (id) {
      var el = document.getElementById(id);
      if (el && el._restore) { el._restore(state[id]); drafts[id] = state[id]; }
    });
  };

  var unpoint = null;
  ot.point = function (id) {
    if (unpoint) { unpoint(); unpoint = null; }
    if (!id) return true;
    var el = document.getElementById(id);
    if (!el) { flushPatched(issue('point', 'nothing has id "' + id + '"')); return false; }
    var host = el.parentElement && el.parentElement.closest('ot-graph, ot-map, ot-numberline, ot-image');
    if (host && host.pointAt && getComputedStyle(el).display === 'none') { unpoint = host.pointAt(el); return true; }
    var target = el._view || el;
    target.classList.add('ot-pointed');
    unpoint = function () { target.classList.remove('ot-pointed'); };
    return true;
  };

  ot.reveal = function (id) {
    var el = document.getElementById(id);
    if (!el) { flushPatched(issue('reveal', 'nothing has id "' + id + '"')); return false; }
    var shown = el;
    if (el.hasAttribute('later')) { el.removeAttribute('later'); fadeIn(el, 0); }
    else if (el.reveal) { shown = el.reveal() || el; fadeIn(shown, 0); }
    else if ($$('[later]', el).length) $$('[later]', el).forEach(function (k) { k.removeAttribute('later'); fadeIn(k, 0); });
    else issue('reveal', '"' + id + '" has nothing hidden to reveal', el);
    var graph = el.closest('ot-graph');
    if (graph && graph.redraw) graph.redraw();
    flash(shown);
    lintGraphs();
    return true;
  };

  ot.patch = async function (html) {
    try {
      var fragment = sanitizedFragment(html);
      var ops = $$('ot-patch', fragment).filter(function (p) { return !p.parentElement || !p.parentElement.closest('ot-patch'); });
      if (!ops.length) issue('patch', 'no <ot-patch> found');
      var changed = [], replaced = [], removed = [], reveals = [];
      ops.forEach(function (op) {
        var id = op.getAttribute('target');
        var action = (op.getAttribute('do') || 'replace').toLowerCase();
        var target = id && document.getElementById(id);
        if (!target) { issue('patch', 'no element with id "' + id + '"'); return; }
        var nodes = Array.prototype.slice.call(op.childNodes);
        var els = nodes.filter(function (n) { return n.nodeType === 1; });
        if (action === 'reveal') { reveals.push(id); return; }
        if (action === 'remove') { removed.push(target); return; }
        if (action === 'replace') {
          // the replacement keeps the target's id, whatever id it arrived with,
          // so later patches, points and reveals still find the element
          if (els.length === 1) els[0].id = id;
          if (!els.length) {
            // text-only replacement keeps the element and swaps its content
            target.textContent = '';
            nodes.forEach(function (n) { target.appendChild(n); });
            replaced.push(target);
          } else {
            target.replaceWith.apply(target, nodes);
            replaced = replaced.concat(els);
          }
        } else if (action === 'append' || action === 'prepend' || action === 'before' || action === 'after') {
          target[action].apply(target, nodes);
          changed = changed.concat(els.length ? els : [target]);
        } else if (action === 'text') {
          target.textContent = op.textContent; replaced.push(target);
        } else issue('patch', 'unknown do="' + action + '"');
      });
      // typed answers survive a patch that replaced their element:
      // drafts go back onto every input that still exists by id
      Object.keys(drafts).forEach(function (id) {
        var el = document.getElementById(id);
        if (el && el._restore) { try { el._restore(drafts[id]); } catch (e) { /* keep the text in drafts */ } }
      });
      // a map added by this patch draws from its own data before anything is reported or shown
      var freshMaps = $$('ot-map', page).filter(function (m) { return m._data && !m._countries; });
      if (freshMaps.length) {
        await withTimeout(Promise.all(freshMaps.map(function (m) { return m._data; })), 10000);
        freshMaps.forEach(function (m) { if (m.isConnected) m.redraw(); });
      }
      var touched = changed.concat(replaced);
      // maths in new content, except inside components that read their own raw text
      var own = MATH_SKIP.filter(function (t) { return t.indexOf('ot-') === 0; }).join(',');
      touched.forEach(function (el) { if (el.isConnected && !el.closest(own)) renderMath(el); });
      // components whose data children changed rebuild their view
      touched.forEach(function (el) {
        var host = el.parentElement && el.parentElement.closest('ot-steps, ot-timeline');
        if (host && host.refresh) host.refresh();
      });
      lint();
      settle(true);
      touched.forEach(function (el) {
        if (!el.isConnected) return;
        fadeIn(el, replaced.indexOf(el) >= 0 ? 0.35 : 0);
        flash(el);
      });
      reveals.forEach(function (id) { ot.reveal(id); });
      removed.forEach(function (el) {
        if (reducedMotion() || !el.animate) { el.remove(); settle(true); return; }
        animEnd(el.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 350, easing: 'ease-in', fill: 'forwards' }), 350, function () { el.remove(); settle(true); });
      });
      return flushPatched();
    } catch (e) {
      issue('patch', 'patch failed: ' + (e && e.message || String(e)));
      return flushPatched();
    }
  };

  // ---------------------------------------------------------------- boot
  var readyInfo = null; // the last ready message, re-sent on {ot:'hello'}
  function sendReady() { if (readyInfo) post(readyInfo); }
  function onMessage(e) {
    if (e.source !== window.parent) return;
    var m = e.data;
    if (!m || typeof m !== 'object' || typeof m.ot !== 'string') return;
    if (m.ot === 'hello') { ot.ready.then(sendReady); return; }
    ot.ready.then(function () {
      if (m.ot === 'patch') ot.patch(m.html);
      else if (m.ot === 'point') ot.point(m.id || null);
      else if (m.ot === 'reveal') { ot.reveal(m.id); flushPatched(); }
      else if (m.ot === 'restore') ot.restore(m.state);
    });
  }
  window.addEventListener('message', onMessage);

  var BOOT_BUDGET = 10000; // one overall deadline: the page is always shown after 10 s
  async function boot() {
    page = document.getElementById('page') || document.body;
    var started = performance.now();
    var slow = [];
    // Wait for a stage only while budget is left; past the deadline the page is
    // shown with whatever arrived, and the issue names what was still loading.
    async function stage(label, p) {
      var left = BOOT_BUDGET - (performance.now() - started);
      if (left <= 0) { slow.push(label); return; }
      var WAITING = {};
      var r = await Promise.race([p, timeout(left).then(function () { return WAITING; })]);
      if (r === WAITING) slow.push(label);
    }
    if (!('setHTML' in Element.prototype)) await stage('HTML sanitizer', lib('purify'));
    var source = document.getElementById('ot-source');
    page.appendChild(sanitizedFragment(source.content.textContent));
    source.remove();
    await stage('libraries', Promise.all(needs(page).map(lib)));
    defineAll();
    renderMath(page);
    var waits = [];
    $$('ot-map', page).forEach(function (m) { if (m._data) waits.push(m._data); });
    if (document.fonts && document.fonts.ready) waits.push(document.fonts.ready);
    await stage('map data and fonts', Promise.all(waits));
    lint();
    settle(false);
    var imgs = $$('ot-image', page).map(function (i) { return i._loaded; }).concat($$('img', page).filter(function (i) { return !i.closest('ot-image') && !i.complete; }).map(function (i) {
      return new Promise(function (r) { i.onload = i.onerror = r; });
    }));
    await stage('images', Promise.all(imgs));
    drawVisuals();
    if (slow.length) issue('slow', 'still loading after 10 s: ' + slow.join(', '));
    booted = true;
    document.documentElement.classList.remove('ot-boot');
    document.documentElement.setAttribute('data-ot-ready', '1');
    readyInfo = { ot: 'ready', fontPx: ot.fontPx, issues: ot.issues.slice(), w: innerWidth, h: innerHeight, ms: Math.round(performance.now() - started) };
    reported = ot.issues.length;
    post(readyInfo);
    return readyInfo;
  }
  var resizeTimer = null;
  window.addEventListener('resize', function () {
    if (!booted) return;
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () { settle(false); }, 120);
  });

  ot.ready = new Promise(function (resolve) {
    function go() {
      boot().then(resolve, function (e) {
        // a failed boot still shows the page and still reports ready, with the failure as an issue
        issue('boot', String(e && e.stack || e));
        try { if (page) settle(false); } catch (e2) { /* show what we have */ }
        try { drawVisuals(); } catch (e3) { /* show what we have */ }
        document.documentElement.classList.remove('ot-boot');
        document.documentElement.setAttribute('data-ot-ready', '1');
        readyInfo = { ot: 'ready', fontPx: ot.fontPx, issues: ot.issues.slice(), w: innerWidth, h: innerHeight, ms: -1 };
        reported = ot.issues.length;
        post(readyInfo);
        resolve(readyInfo);
      });
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', go); else go();
  });
})();
