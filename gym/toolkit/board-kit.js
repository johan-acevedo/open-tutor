/* BoardKit 0.1.0 — dependency-free teaching-board drawing library.
 * Draws into SVG. Does geometry and counting itself so models never place
 * individual pieces by hand. ES5 syntax (runs everywhere). Exposes
 * window.BoardKit. Board space is 1920x1080 CSS pixels.
 * Palette: bg #181B22, ink #F3F5F8, cyan #22D3EE, violet #A78BFA.
 * All text defaults to >= 24px. Errors throw, never silently misdraw.
 */
(function (global) {
  'use strict';
  var SVGNS = 'http://www.w3.org/2000/svg';
  var BOARD_W = 1920;
  var BOARD_H = 1080;
  var SAFE_MARGIN = 60;

  var PALETTE = {
    bg: '#181B22',
    panel: '#20242E',
    piece: '#232A36',
    ink: '#F3F5F8',
    muted: '#9AA3B2',
    line: '#3A4354',
    cyan: '#22D3EE',
    violet: '#A78BFA',
    danger: '#F87171'
  };

  function err(msg) { throw new Error('[BoardKit] ' + msg); }

  function isNum(v) { return typeof v === 'number' && isFinite(v); }

  function assertBox(box, name) {
    if (!box || !isNum(box.x) || !isNum(box.y) || !isNum(box.w) || !isNum(box.h))
      err((name || 'box') + ' must be {x,y,w,h} numbers');
    if (box.w <= 0 || box.h <= 0)
      err((name || 'box') + ' must have positive w/h (got ' + box.w + 'x' + box.h + ')');
    if (box.x < 0 || box.y < 0 || box.x + box.w > BOARD_W || box.y + box.h > BOARD_H)
      err((name || 'box') + ' (' + box.x + ',' + box.y + ' ' + box.w + 'x' + box.h +
        ') exceeds the 1920x1080 board');
  }

  function assertInt(v, name) {
    if (typeof v !== 'number' || !isFinite(v) || Math.floor(v) !== v)
      err(name + ' must be an integer (got ' + v + ')');
  }

  function assertPoint(x, y, name) {
    if (!isNum(x) || !isNum(y)) err(name + ' must be numbers');
    if (x < 0 || x > BOARD_W || y < 0 || y > BOARD_H)
      err(name + ' (' + x + ',' + y + ') is outside the 1920x1080 board');
  }

  function node(tag, attrs, parent) {
    var el = document.createElementNS(SVGNS, tag);
    if (attrs) {
      for (var k in attrs) {
        if (Object.prototype.hasOwnProperty.call(attrs, k))
          el.setAttribute(k, attrs[k]);
      }
    }
    if (parent) parent.appendChild(el);
    return el;
  }

  var FONT = "system-ui, -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif";

  function text(parent, x, y, str, opts) {
    if (typeof str !== 'string') err('text() str must be a string');
    opts = opts || {};
    var size = opts.size == null ? 28 : opts.size;
    if (!isNum(size) || size < 24)
      err('text size must be >= 24px (got ' + size + '). Board text must stay readable for children.');
    var el = node('text', {
      x: x, y: y,
      'font-size': size,
      'font-family': FONT,
      'font-weight': opts.weight || 'normal',
      fill: opts.fill || PALETTE.ink,
      'text-anchor': opts.anchor || 'start'
    }, parent);
    if (opts.valign === 'middle') el.setAttribute('dominant-baseline', 'central');
    el.textContent = str;
    return el;
  }

  /* Swedish number formatting with decimal comma. fmtSV(13.5, 2) -> "13,50".
   * Thousands are grouped with a space: fmtSV(1000) -> "1 000". */
  function fmtSV(n, decimals) {
    if (typeof n !== 'number' || !isFinite(n))
      err('fmtSV() needs a finite number (got ' + n + ')');
    var s;
    if (decimals == null) {
      s = String(n);
      // Avoid exponential output for typical board numbers.
      if (s.indexOf('e') !== -1) err('fmtSV() cannot format exponential ' + s + '; pass decimals');
    } else {
      assertInt(decimals, 'fmtSV() decimals');
      if (decimals < 0 || decimals > 10) err('fmtSV() decimals must be 0..10');
      s = n.toFixed(decimals);
    }
    var neg = s.charAt(0) === '-' ? '-' : '';
    if (neg) s = s.slice(1);
    var parts = s.split('.');
    parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
    return neg + (parts.length > 1 ? parts[0] + ',' + parts[1] : parts[0]);
  }

  /* Safe board box with comfortable margins. If an <svg> element is passed,
   * it is sized to 1920x1080 and given the dark background. */
  function board(svg, opts) {
    opts = opts || {};
    var m = opts.margin == null ? SAFE_MARGIN : opts.margin;
    if (!isNum(m) || m < 0 || m * 2 >= Math.min(BOARD_W, BOARD_H))
      err('board() margin must be 0..539 (got ' + m + ')');
    if (svg) {
      if (!svg.tagName || svg.tagName.toLowerCase() !== 'svg')
        err('board() first argument must be an <svg> element or omitted');
      svg.setAttribute('width', BOARD_W);
      svg.setAttribute('height', BOARD_H);
      svg.setAttribute('viewBox', '0 0 ' + BOARD_W + ' ' + BOARD_H);
      node('rect', { x: 0, y: 0, width: BOARD_W, height: BOARD_H, fill: PALETTE.bg }, svg);
    }
    return { x: m, y: m, w: BOARD_W - m * 2, h: BOARD_H - m * 2 };
  }

  function splitBox(box, ratios, gap, horizontal) {
    assertBox(box, 'parent box');
    if (!ratios || ratios.length < 1) err('need at least one ratio');
    var i, sum = 0;
    for (i = 0; i < ratios.length; i++) {
      if (!isNum(ratios[i]) || ratios[i] <= 0) err('ratios must be positive numbers');
      sum += ratios[i];
    }
    if (!isNum(gap)) gap = 24;
    if (gap < 0) err('gap must be >= 0');
    var n = ratios.length;
    var avail = (horizontal ? box.w : box.h) - gap * (n - 1);
    if (avail <= 0) err('box too small for ' + n + ' regions with gap ' + gap);
    var out = [], cur = horizontal ? box.x : box.y;
    for (i = 0; i < n; i++) {
      var len = (i === n - 1)
        ? ((horizontal ? box.x + box.w : box.y + box.h) - cur) // last takes remainder: never overflows
        : avail * ratios[i] / sum;
      out.push(horizontal
        ? { x: cur, y: box.y, w: len, h: box.h }
        : { x: box.x, y: cur, w: box.w, h: len });
      cur += len + gap;
    }
    return out;
  }

  function rows(box, ratios, gap) { return splitBox(box, ratios, gap, false); }
  function cols(box, ratios, gap) { return splitBox(box, ratios, gap, true); }

  /* stack(box, count, gap, dir): count equal regions, vertical ('v') or
   * horizontal ('h'). Convenience wrapper so models never compute splits. */
  function stack(box, count, gap, dir) {
    assertInt(count, 'stack() count');
    if (count < 1) err('stack() count must be >= 1');
    var ratios = [], i;
    for (i = 0; i < count; i++) ratios.push(1);
    return splitBox(box, ratios, gap, dir === 'h');
  }

  /* Analog clock. opts: {hour (0-23), minute (0-59), numerals=true,
   * highlightNumbers=[...], hourColor, minuteColor, caption}. Hour hand
   * position is exact: hourAngle = (hour%12)*30 + minute*0.5. */
  function clock(parent, box, opts) {
    assertBox(box, 'clock box');
    opts = opts || {};
    assertInt(opts.hour, 'clock() hour');
    assertInt(opts.minute, 'clock() minute');
    if (opts.hour < 0 || opts.hour > 23) err('clock() hour must be 0..23 (got ' + opts.hour + ')');
    if (opts.minute < 0 || opts.minute > 59) err('clock() minute must be 0..59 (got ' + opts.minute + ')');
    var showNum = opts.numerals == null ? true : !!opts.numerals;
    var hiNums = opts.highlightNumbers || [];
    var cx = box.x + box.w / 2;
    var cy = box.y + box.h / 2 - (opts.caption ? 18 : 0);
    var pad = opts.caption ? 44 : 12;
    var R = Math.min(box.w, box.h) / 2 - pad;
    if (R < 60) err('clock() box too small (needs min 160px height/width with caption)');
    if (showNum && R < 76)
      err('clock() box too small for readable numerals (clock radius ' +
        Math.round(R) + 'px, needs 76px+ so 24px numerals do not touch)');
    var g = node('g', null, parent);
    node('circle', { cx: cx, cy: cy, r: R, fill: PALETTE.panel, stroke: PALETTE.line, 'stroke-width': 5 }, g);
    var i, a, x1, y1, x2, y2, major;
    for (i = 0; i < 60; i++) {
      a = i * 6 * Math.PI / 180;
      major = i % 5 === 0;
      x1 = cx + Math.sin(a) * (R - (major ? R * 0.13 : R * 0.07));
      y1 = cy - Math.cos(a) * (R - (major ? R * 0.13 : R * 0.07));
      x2 = cx + Math.sin(a) * (R - 6);
      y2 = cy - Math.cos(a) * (R - 6);
      node('line', {
        x1: x1, y1: y1, x2: x2, y2: y2,
        stroke: major ? PALETTE.ink : PALETTE.muted,
        'stroke-width': major ? 5 : 2, 'stroke-linecap': 'round'
      }, g);
    }
    var hourAngle = (opts.hour % 12) * 30 + opts.minute * 0.5;
    var minAngle = opts.minute * 6;
    function hand(angleDeg, len, width, color) {
      var r = angleDeg * Math.PI / 180;
      node('line', {
        x1: cx, y1: cy,
        x2: cx + Math.sin(r) * len, y2: cy - Math.cos(r) * len,
        stroke: color, 'stroke-width': width, 'stroke-linecap': 'round'
      }, g);
    }
    var fs = Math.max(24, Math.round(R * 0.17));
    // Numerals sit inside the major ticks with room for two-digit width;
    // hands stop short of the numerals so none is ever covered.
    var numR = R * 0.87 - fs * 0.95;
    var minLen = showNum ? numR - fs * 0.62 : R * 0.76;
    var hourLen = minLen * 0.66;
    if (showNum && numR < fs * 3.1)
      err('clock() box too small: numerals would overlap. Give it a box at least ' +
        Math.ceil(2 * ((fs * 3.1 + fs * 0.95) / 0.87 + pad)) + 'px on its shorter side');
    if (showNum) {
      for (i = 1; i <= 12; i++) {
        a = i * 30 * Math.PI / 180;
        var nx = cx + Math.sin(a) * numR;
        var ny = cy - Math.cos(a) * numR;
        var t = text(g, nx, ny, String(i), {
          size: fs, anchor: 'middle', valign: 'middle',
          weight: hiNums.indexOf(i) !== -1 ? 'bold' : 'normal',
          fill: hiNums.indexOf(i) !== -1 ? PALETTE.cyan : PALETTE.ink
        });
        void t;
      }
    }
    hand(hourAngle, hourLen, Math.max(9, R * 0.055), opts.hourColor || PALETTE.ink);
    hand(minAngle, minLen, Math.max(6, R * 0.038), opts.minuteColor || PALETTE.cyan);
    node('circle', { cx: cx, cy: cy, r: 11, fill: PALETTE.cyan }, g);
    node('circle', { cx: cx, cy: cy, r: 4.5, fill: PALETTE.bg }, g);
    if (opts.caption)
      text(g, cx, box.y + box.h - 14, opts.caption, { size: 28, anchor: 'middle' });
    return { cx: cx, cy: cy, r: R, hourAngle: hourAngle, minuteAngle: minAngle };
  }

  /* Unit blocks: n identical pieces in groups of perGroup, with a bracket
   * and label per full group plus a bracket/label for the remainder.
   * opts: {n, perGroup, pieceLabel (header), groupLabel, remainderLabel,
   * evenGroups}. groupLabel/remainderLabel are strings or fn(count)->string.
   * Set evenGroups:true to throw when n % perGroup !== 0. */
  function blocks(parent, box, opts) {
    assertBox(box, 'blocks box');
    opts = opts || {};
    assertInt(opts.n, 'blocks() n');
    assertInt(opts.perGroup, 'blocks() perGroup');
    if (opts.n < 1) err('blocks() n must be >= 1 (got ' + opts.n + ')');
    if (opts.perGroup < 1) err('blocks() perGroup must be >= 1 (got ' + opts.perGroup + ')');
    if (opts.evenGroups && opts.n % opts.perGroup !== 0)
      err('blocks() n=' + opts.n + ' does not divide into even groups of ' +
        opts.perGroup + ' (remainder ' + (opts.n % opts.perGroup) + ')');
    function lab(fn, c) {
      if (typeof fn === 'function') return fn(c);
      if (typeof fn === 'string') return fn;
      return c + ' st';
    }
    var full = Math.floor(opts.n / opts.perGroup);
    var rem = opts.n % opts.perGroup;
    var nGroups = full + (rem > 0 ? 1 : 0);
    var g = node('g', null, parent);
    var headerH = opts.pieceLabel ? 40 : 8;
    if (opts.pieceLabel)
      text(g, box.x + box.w / 2, box.y + 30, opts.pieceLabel, { size: 26, anchor: 'middle', fill: PALETTE.muted });
    var labelH = 66;
    var gridY = box.y + headerH;
    var gridH = box.h - headerH - labelH;
    var gap = 18;
    var gw = (box.w - gap * (nGroups - 1)) / nGroups;
    if (gw < 30 || gridH < 60) err('blocks() box too small for ' + nGroups + ' groups');
    var gi, pi, count, isRem, colsN, rowsN, gx;
    // One piece size for every group so all pieces are identical.
    var colsFull = opts.perGroup <= 4 ? opts.perGroup : 5;
    var rowsFull = Math.ceil(opts.perGroup / colsFull);
    var piece = Math.min((gw - 8) / colsFull, gridH / rowsFull, 58);
    if (piece < 14) err('blocks() box too small: pieces would be under 14px');
    var oy = gridY + (gridH - rowsFull * piece) / 2;
    var by = oy + rowsFull * piece + 14;
    for (gi = 0; gi < nGroups; gi++) {
      isRem = rem > 0 && gi === nGroups - 1;
      count = isRem ? rem : opts.perGroup;
      gx = box.x + gi * (gw + gap);
      colsN = count <= 4 ? count : 5;
      rowsN = Math.ceil(count / colsN);
      var ox = gx + (gw - colsN * piece) / 2;
      for (pi = 0; pi < count; pi++) {
        var c = pi % colsN, r = Math.floor(pi / colsN);
        node('rect', {
          x: ox + c * piece + 2, y: oy + r * piece + 2,
          width: piece - 4, height: piece - 4, rx: 7,
          fill: isRem ? '#2C2540' : PALETTE.piece,
          stroke: isRem ? PALETTE.violet : PALETTE.cyan, 'stroke-width': 3
        }, g);
      }
      // Bracket + label under the group.
      var bx0 = ox, bx1 = ox + colsN * piece;
      var col = isRem ? PALETTE.violet : PALETTE.cyan;
      node('path', {
        d: 'M ' + bx0 + ' ' + by + ' L ' + bx0 + ' ' + (by + 10) +
           ' L ' + bx1 + ' ' + (by + 10) + ' L ' + bx1 + ' ' + by,
        fill: 'none', stroke: col, 'stroke-width': 4, 'stroke-linecap': 'round'
      }, g);
      text(g, gx + gw / 2, by + 44, lab(isRem ? opts.remainderLabel : opts.groupLabel, count),
        { size: 26, anchor: 'middle', fill: col, weight: 'bold' });
    }
    return { groups: full, remainder: rem };
  }

  /* Portions: count equal containers in a row, some highlighted.
   * opts: {count, filled (number or array of indices), labels?, caption?,
   * title?}. filled as a number highlights the first k. */
  function portions(parent, box, opts) {
    assertBox(box, 'portions box');
    opts = opts || {};
    assertInt(opts.count, 'portions() count');
    if (opts.count < 1) err('portions() count must be >= 1');
    var set = {};
    if (opts.filled == null) { /* none */ }
    else if (typeof opts.filled === 'number') {
      assertInt(opts.filled, 'portions() filled');
      if (opts.filled < 0 || opts.filled > opts.count)
        err('portions() filled=' + opts.filled + ' out of range 0..' + opts.count);
      for (var k = 0; k < opts.filled; k++) set[k] = true;
    } else if (Object.prototype.toString.call(opts.filled) === '[object Array]') {
      for (var j = 0; j < opts.filled.length; j++) {
        var idx = opts.filled[j];
        assertInt(idx, 'portions() filled index');
        if (idx < 0 || idx >= opts.count)
          err('portions() filled index ' + idx + ' out of range 0..' + (opts.count - 1));
        set[idx] = true;
      }
    } else err('portions() filled must be a number or an array of indices');
    if (opts.labels != null) {
      if (Object.prototype.toString.call(opts.labels) !== '[object Array]' ||
          opts.labels.length !== opts.count)
        err('portions() labels must be an array of length ' + opts.count);
    }
    var g = node('g', null, parent);
    var titleH = opts.title ? 42 : 6;
    if (opts.title)
      text(g, box.x + box.w / 2, box.y + 32, opts.title, { size: 27, anchor: 'middle', weight: 'bold' });
    var gap = 12;
    var pw = (box.w - 20 - gap * (opts.count - 1)) / opts.count;
    var labH2 = opts.labels ? 78 : (opts.caption ? 70 : 10);
    var ph = box.h - titleH - labH2;
    if (pw < 24 || ph < 50) err('portions() box too small for ' + opts.count + ' portions');
    var y0 = box.y + titleH;
    var i, on;
    for (i = 0; i < opts.count; i++) {
      on = !!set[i];
      node('rect', {
        x: box.x + 10 + i * (pw + gap), y: y0, width: pw, height: ph, rx: 12,
        fill: on ? 'rgba(34,211,238,0.20)' : PALETTE.piece,
        stroke: on ? PALETTE.cyan : PALETTE.line, 'stroke-width': on ? 4 : 3
      }, g);
      if (opts.labels)
        text(g, box.x + 10 + i * (pw + gap) + pw / 2, y0 + ph + 34,
          String(opts.labels[i]), {
            size: 24, anchor: 'middle', fill: on ? PALETTE.cyan : PALETTE.muted,
            weight: on ? 'bold' : 'normal'
          });
    }
    if (opts.caption && !opts.labels)
      text(g, box.x + box.w / 2, y0 + ph + 40, opts.caption, { size: 26, anchor: 'middle' });
    if (opts.caption && opts.labels)
      text(g, box.x + box.w / 2, y0 + ph + 68, opts.caption, { size: 24, anchor: 'middle', fill: PALETTE.muted });
    return { highlighted: Object.keys(set).length };
  }

  /* Number line. opts: {min, max, step, mark?, markLabel?, unit?}.
   * Throws when step does not divide the range evenly. */
  function numberLine(parent, box, opts) {
    assertBox(box, 'numberLine box');
    opts = opts || {};
    if (!isNum(opts.min) || !isNum(opts.max) || !isNum(opts.step))
      err('numberLine() needs numeric min/max/step');
    if (opts.max <= opts.min) err('numberLine() max must exceed min');
    if (opts.step <= 0) err('numberLine() step must be > 0');
    var q = (opts.max - opts.min) / opts.step;
    if (Math.abs(q - Math.round(q)) > 1e-9)
      err('numberLine() step ' + opts.step + ' does not divide range ' +
        opts.min + '..' + opts.max + ' evenly (' + q.toFixed(2) + ' steps)');
    var nTicks = Math.round(q) + 1;
    if (nTicks > 21) err('numberLine() would draw ' + nTicks + ' ticks (max 21); widen step');
    if (opts.mark != null) {
      if (!isNum(opts.mark)) err('numberLine() mark must be a number');
      if (opts.mark < opts.min || opts.mark > opts.max)
        err('numberLine() mark ' + opts.mark + ' outside ' + opts.min + '..' + opts.max);
    }
    var g = node('g', null, parent);
    var padX = 56;
    var x0 = box.x + padX, x1 = box.x + box.w - padX;
    var lineY = box.y + box.h * 0.52;
    node('line', {
      x1: x0, y1: lineY, x2: x1, y2: lineY,
      stroke: PALETTE.ink, 'stroke-width': 5, 'stroke-linecap': 'round'
    }, g);
    var i, v, x;
    for (i = 0; i < nTicks; i++) {
      v = opts.min + i * opts.step;
      x = x0 + (x1 - x0) * i / (nTicks - 1);
      node('line', {
        x1: x, y1: lineY - 13, x2: x, y2: lineY + 13,
        stroke: PALETTE.ink, 'stroke-width': 4, 'stroke-linecap': 'round'
      }, g);
      text(g, x, lineY + 48, fmtSV(Math.round(v * 1e9) / 1e9) + (opts.unit ? ' ' + opts.unit : ''),
        { size: 25, anchor: 'middle', fill: PALETTE.muted });
    }
    if (opts.mark != null) {
      var mx = x0 + (x1 - x0) * (opts.mark - opts.min) / (opts.max - opts.min);
      node('circle', { cx: mx, cy: lineY, r: 14, fill: PALETTE.cyan, stroke: PALETTE.bg, 'stroke-width': 4 }, g);
      text(g, mx, lineY - 34,
        opts.markLabel != null ? String(opts.markLabel) : fmtSV(opts.mark),
        { size: 29, anchor: 'middle', fill: PALETTE.cyan, weight: 'bold' });
    }
    return { ticks: nTicks };
  }

  /* Fraction bar: num of den equal parts filled.
   * opts: {num, den, label?}. */
  function fractionBar(parent, box, opts) {
    assertBox(box, 'fractionBar box');
    opts = opts || {};
    assertInt(opts.num, 'fractionBar() num');
    assertInt(opts.den, 'fractionBar() den');
    if (opts.den < 1) err('fractionBar() den must be >= 1');
    if (opts.num < 0 || opts.num > opts.den)
      err('fractionBar() num=' + opts.num + ' outside 0..' + opts.den);
    if (opts.den > 12) err('fractionBar() den max 12 (got ' + opts.den + ')');
    var g = node('g', null, parent);
    var bw = box.w - 20, bh = Math.min(100, box.h * 0.42);
    var bx = box.x + 10, by = box.y + Math.max(8, (box.h - 70 - bh) / 2);
    var gap = 5, sw = (bw - gap * (opts.den - 1)) / opts.den;
    if (sw < 18) err('fractionBar() box too small for ' + opts.den + ' parts');
    var i;
    for (i = 0; i < opts.den; i++) {
      var on = i < opts.num;
      node('rect', {
        x: bx + i * (sw + gap), y: by, width: sw, height: bh, rx: 8,
        fill: on ? PALETTE.cyan : PALETTE.piece,
        'fill-opacity': on ? 0.85 : 1,
        stroke: on ? PALETTE.cyan : PALETTE.line, 'stroke-width': 3
      }, g);
    }
    text(g, box.x + box.w / 2, by + bh + 44,
      opts.label != null ? String(opts.label) : opts.num + ' av ' + opts.den,
      { size: 29, anchor: 'middle', weight: 'bold' });
    return { filled: opts.num, total: opts.den };
  }

  /* Singapore-style bar model: one horizontal bar split proportionally.
   * parts: [number] or [{value, label, highlight}]. opts: {total?, caption?}.
   * Throws when values are not positive or parts do not sum to total. */
  function barModel(parent, box, opts) {
    assertBox(box, 'barModel box');
    opts = opts || {};
    if (Object.prototype.toString.call(opts.parts) !== '[object Array]' || !opts.parts.length)
      err('barModel() parts must be a non-empty array');
    var parts = opts.parts.map(function (p, i) {
      if (typeof p === 'number') return { value: p, label: '', highlight: false };
      if (!p || !isNum(p.value)) err('barModel() part ' + i + ' needs a numeric value');
      return { value: p.value, label: p.label == null ? '' : String(p.label), highlight: !!p.highlight };
    });
    var i, sum = 0;
    for (i = 0; i < parts.length; i++) {
      if (parts[i].value <= 0) err('barModel() part ' + i + ' value must be > 0');
      sum += parts[i].value;
    }
    if (opts.total != null) {
      if (!isNum(opts.total)) err('barModel() total must be a number');
      if (Math.abs(sum - opts.total) > 1e-9 * Math.max(1, Math.abs(opts.total)))
        err('barModel() parts sum to ' + sum + ' but total is ' + opts.total);
    }
    if (parts.length > 10) err('barModel() max 10 parts (got ' + parts.length + ')');
    var g = node('g', null, parent);
    var bw = box.w - 20, bh = Math.min(108, box.h * 0.4);
    var bx = box.x + 10, by = box.y + Math.max(8, (box.h - 76 - bh) / 2);
    var gap = parts.length > 1 ? 5 : 0;
    var x = bx;
    for (i = 0; i < parts.length; i++) {
      var w = (bw - gap * (parts.length - 1)) * parts[i].value / sum;
      if (w < 4) err('barModel() box too small: part ' + i + ' would be under 4px');
      node('rect', {
        x: x, y: by, width: w, height: bh, rx: 10,
        fill: parts[i].highlight ? PALETTE.cyan : '#2C3444',
        'fill-opacity': parts[i].highlight ? 0.9 : 1,
        stroke: parts[i].highlight ? PALETTE.cyan : PALETTE.line, 'stroke-width': 3
      }, g);
      if (w >= 96 && parts[i].label)
        text(g, x + w / 2, by + bh / 2, parts[i].label,
          { size: 24, anchor: 'middle', valign: 'middle', weight: 'bold', fill: parts[i].highlight ? '#0B1220' : PALETTE.ink });
      else if (parts[i].label)
        text(g, x + w / 2, by + bh + 34, parts[i].label,
          { size: 24, anchor: 'middle', fill: parts[i].highlight ? PALETTE.cyan : PALETTE.muted });
      x += w + gap;
    }
    if (opts.caption)
      text(g, box.x + box.w / 2, by + bh + (parts.some(function (p) { return p.label && true; }) ? 62 : 40),
        String(opts.caption), { size: 26, anchor: 'middle' });
    return { sum: sum };
  }

  /* Simple balance scale. opts: {left:{label,sub?}, right:{label,sub?},
   * tilt:'left'|'right'|'balance'}. Tilt names the heavier side. */
  function scale(parent, box, opts) {
    assertBox(box, 'scale box');
    opts = opts || {};
    if (!opts.left || typeof opts.left.label !== 'string' || !opts.left.label)
      err('scale() needs left.label (non-empty string)');
    if (!opts.right || typeof opts.right.label !== 'string' || !opts.right.label)
      err('scale() needs right.label (non-empty string)');
    if (opts.tilt !== 'left' && opts.tilt !== 'right' && opts.tilt !== 'balance')
      err("scale() tilt must be 'left', 'right' or 'balance' (got '" + opts.tilt + "')");
    var g = node('g', null, parent);
    var cx = box.x + box.w / 2;
    var baseY = box.y + box.h - 26;
    var topY = box.y + Math.min(78, Math.round(box.h * 0.30));
    var L = Math.min(box.w * 0.36, 300);
    if (L < 120) err('scale() box too narrow (needs 260px+)');
    if (box.h < 130) err('scale() box too short (needs 130px+ height)');
    var ang = opts.tilt === 'left' ? -8 : opts.tilt === 'right' ? 8 : 0;
    var rad = ang * Math.PI / 180;
    function end(side) { // side -1 left, +1 right
      return { x: cx + side * L * Math.cos(rad), y: topY + side * L * Math.sin(rad) };
    }
    var le = end(-1), re = end(1);
    // Stand + base.
    node('line', { x1: cx, y1: topY, x2: cx, y2: baseY, stroke: PALETTE.muted, 'stroke-width': 10, 'stroke-linecap': 'round' }, g);
    node('line', { x1: cx - 90, y1: baseY, x2: cx + 90, y2: baseY, stroke: PALETTE.muted, 'stroke-width': 10, 'stroke-linecap': 'round' }, g);
    node('polygon', {
      points: cx + ',' + (topY - 2) + ' ' + (cx - 16) + ',' + (topY + 26) + ' ' + (cx + 16) + ',' + (topY + 26),
      fill: PALETTE.muted
    }, g);
    // Beam.
    node('line', { x1: le.x, y1: le.y, x2: re.x, y2: re.y, stroke: PALETTE.ink, 'stroke-width': 9, 'stroke-linecap': 'round' }, g);
    node('circle', { cx: cx, cy: topY, r: 10, fill: PALETTE.cyan }, g);
    // Pans.
    function pan(e, side, info, color) {
      var hang = Math.min(64, Math.round(box.h * 0.28));
      node('line', { x1: e.x, y1: e.y, x2: e.x, y2: e.y + hang, stroke: PALETTE.muted, 'stroke-width': 4 }, g);
      node('ellipse', {
        cx: e.x, cy: e.y + hang + 14, rx: 78, ry: 20,
        fill: '#232A36', stroke: color, 'stroke-width': 4
      }, g);
      var vt = text(g, e.x, e.y + hang - 22, info.label,
        { size: 30, anchor: 'middle', weight: 'bold', fill: color });
      try {
        var vbb = vt.getBBox();
        node('rect', {
          x: vbb.x - 10, y: vbb.y - 6, width: vbb.width + 20, height: vbb.height + 12, rx: 9,
          fill: PALETTE.bg, 'fill-opacity': 0.9
        }, g).parentNode.insertBefore(g.lastChild, vt);
      } catch (e2) { /* backing optional */ }
      if (info.sub)
        text(g, e.x, e.y + hang + 52, String(info.sub), { size: 24, anchor: 'middle', fill: PALETTE.muted });
    }
    var hl = opts.tilt === 'left' ? PALETTE.cyan : opts.tilt === 'balance' ? PALETTE.cyan : PALETTE.muted;
    var hr = opts.tilt === 'right' ? PALETTE.cyan : opts.tilt === 'balance' ? PALETTE.cyan : PALETTE.muted;
    pan(le, -1, opts.left, hl);
    pan(re, 1, opts.right, hr);
    return { tilt: opts.tilt };
  }

  /* Arrow between two board points, with optional label offset
   * perpendicular to the shaft. */
  function arrow(parent, opts) {
    opts = opts || {};
    if (!isNum(opts.x1) || !isNum(opts.y1) || !isNum(opts.x2) || !isNum(opts.y2))
      err('arrow() needs numeric x1,y1,x2,y2');
    assertPoint(opts.x1, opts.y1, 'arrow() start');
    assertPoint(opts.x2, opts.y2, 'arrow() end');
    var dx = opts.x2 - opts.x1, dy = opts.y2 - opts.y1;
    var len = Math.sqrt(dx * dx + dy * dy);
    if (len < 30) err('arrow() endpoints too close (' + Math.round(len) + 'px, min 30)');
    var color = opts.color || PALETTE.cyan;
    var w = opts.width || 6;
    var g = node('g', null, parent);
    node('line', {
      x1: opts.x1, y1: opts.y1, x2: opts.x2, y2: opts.y2,
      stroke: color, 'stroke-width': w, 'stroke-linecap': 'round'
    }, g);
    var ux = dx / len, uy = dy / len;
    var hs = 26; // head size
    var bx = opts.x2 - ux * hs, by = opts.y2 - uy * hs;
    var px = -uy, py = ux;
    node('polygon', {
      points: opts.x2 + ',' + opts.y2 + ' ' + (bx + px * 11) + ',' + (by + py * 11) +
        ' ' + (bx - px * 11) + ',' + (by - py * 11),
      fill: color
    }, g);
    if (opts.label != null) {
      var mx = (opts.x1 + opts.x2) / 2 - uy * 34;
      var my = (opts.y1 + opts.y2) / 2 + ux * 34;
      var t = text(g, mx, my, String(opts.label), { size: 26, anchor: 'middle', valign: 'middle', weight: 'bold', fill: color });
      try {
        var bb = t.getBBox();
        node('rect', {
          x: bb.x - 12, y: bb.y - 8, width: bb.width + 24, height: bb.height + 16, rx: 10,
          fill: PALETTE.bg, 'fill-opacity': 0.88
        }, g).parentNode.insertBefore(g.lastChild, t);
      } catch (e) { /* getBBox unavailable pre-render; label stays readable without backing */ }
    }
    return { length: Math.round(len) };
  }

  /* Label with a leader line pointing at a target. The label box is pushed
   * away until it no longer covers the target and stays inside the board.
   * opts: {tx, ty, text, dx?, dy?, side?}. */
  function leader(parent, opts) {
    opts = opts || {};
    if (!isNum(opts.tx) || !isNum(opts.ty)) err('leader() needs numeric tx,ty');
    assertPoint(opts.tx, opts.ty, 'leader() target');
    if (typeof opts.text !== 'string' || !opts.text) err('leader() needs non-empty text');
    var dx = opts.dx, dy = opts.dy;
    if (dx == null || dy == null) {
      var side = opts.side || 'auto';
      if (side === 'left') { dx = -170; dy = -40; }
      else if (side === 'right') { dx = 170; dy = -40; }
      else if (side === 'top') { dx = 40; dy = -120; }
      else if (side === 'bottom') { dx = 40; dy = 120; }
      else { // auto: point away from the nearest board edge
        dx = opts.tx < BOARD_W / 2 ? 170 : -170;
        dy = opts.ty < BOARD_H / 2 ? -110 : 110;
        if (opts.tx < BOARD_W / 2 && opts.ty > BOARD_H * 0.7) dy = -110;
      }
    }
    var g = node('g', null, parent);
    var lx = opts.tx + dx, ly = opts.ty + dy;
    var t = text(g, lx, ly, opts.text, { size: 27, anchor: 'middle', valign: 'middle', weight: 'bold' });
    var bb;
    try { bb = t.getBBox(); } catch (e) { bb = null; }
    if (bb) {
      var padBox = 14, i;
      for (i = 0; i < 6; i++) {
        var covers = opts.tx > bb.x - 24 && opts.tx < bb.x + bb.width + 24 &&
                     opts.ty > bb.y - 24 && opts.ty < bb.y + bb.height + 24;
        var outL = bb.x - padBox < SAFE_MARGIN, outR = bb.x + bb.width + padBox > BOARD_W - SAFE_MARGIN;
        var outT = bb.y - padBox < SAFE_MARGIN, outB = bb.y + bb.height + padBox > BOARD_H - SAFE_MARGIN;
        if (!covers && !outL && !outR && !outT && !outB) break;
        if (covers) { lx += dx * 0.25; ly += dy * 0.25; }
        if (outL) lx += 40; if (outR) lx -= 40;
        if (outT) ly += 40; if (outB) ly -= 40;
        t.setAttribute('x', lx); t.setAttribute('y', ly);
        try { bb = t.getBBox(); } catch (e2) { break; }
      }
      node('rect', {
        x: bb.x - 16, y: bb.y - 10, width: bb.width + 32, height: bb.height + 20, rx: 12,
        fill: PALETTE.panel, stroke: PALETTE.line, 'stroke-width': 2
      }, g).parentNode.insertBefore(g.lastChild, t);
      // Leader line from label edge to target.
      var ex = Math.max(bb.x - 16, Math.min(bb.x + bb.width + 16, opts.tx));
      var ey = Math.max(bb.y - 10, Math.min(bb.y + bb.height + 10, opts.ty));
      node('line', { x1: ex, y1: ey, x2: opts.tx, y2: opts.ty, stroke: PALETTE.muted, 'stroke-width': 3 }, g)
        .parentNode.insertBefore(g.lastChild, t);
    } else {
      node('line', { x1: lx, y1: ly, x2: opts.tx, y2: opts.ty, stroke: PALETTE.muted, 'stroke-width': 3 }, g)
        .parentNode.insertBefore(g.lastChild, t);
    }
    node('circle', { cx: opts.tx, cy: opts.ty, r: 8, fill: PALETTE.cyan, stroke: PALETTE.bg, 'stroke-width': 3 }, g);
    return { x: lx, y: ly };
  }

  /* Equation row: steps aligned at '='. rows: ["a = b", ...].
   * opts: {highlight (index or array), size?}. */
  function equations(parent, box, opts) {
    assertBox(box, 'equations box');
    opts = opts || {};
    if (Object.prototype.toString.call(opts.rows) !== '[object Array]' || !opts.rows.length)
      err('equations() rows must be a non-empty array of strings');
    var size = opts.size == null ? 33 : opts.size;
    if (!isNum(size) || size < 24)
      err('equations() size must be >= 24px (got ' + size + ')');
    var hi = opts.highlight == null ? [] :
      (Object.prototype.toString.call(opts.highlight) === '[object Array]' ? opts.highlight : [opts.highlight]);
    var g = node('g', null, parent);
    var lineH = Math.min((box.h - 16) / opts.rows.length, 92);
    if (lineH < 40) err('equations() box too short for ' + opts.rows.length + ' rows');
    var cx = box.x + box.w / 2;
    var i, parts, left, right;
    for (i = 0; i < opts.rows.length; i++) {
      if (typeof opts.rows[i] !== 'string' || !opts.rows[i])
        err('equations() row ' + i + ' must be a non-empty string');
      var y = box.y + 8 + lineH * (i + 0.64);
      var hot = hi.indexOf(i) !== -1;
      var fill = hot ? PALETTE.cyan : PALETTE.ink;
      var wt = hot ? 'bold' : 'normal';
      var eq = opts.rows[i].indexOf('=');
      if (eq === -1) {
        text(g, cx, y, opts.rows[i], { size: size, anchor: 'middle', fill: fill, weight: wt });
      } else {
        left = opts.rows[i].slice(0, eq).replace(/\s+$/, '');
        right = opts.rows[i].slice(eq + 1).replace(/^\s+/, '');
        text(g, cx - 30, y, left, { size: size, anchor: 'end', fill: fill, weight: wt });
        text(g, cx, y, '=', { size: size, anchor: 'middle', fill: fill, weight: wt });
        text(g, cx + 30, y, right, { size: size, anchor: 'start', fill: fill, weight: wt });
      }
    }
    return { rows: opts.rows.length };
  }

  var BoardKit = {
    version: '0.1.0',
    palette: PALETTE,
    boardSize: { w: BOARD_W, h: BOARD_H },
    fmtSV: fmtSV,
    board: board,
    rows: rows,
    cols: cols,
    stack: stack,
    text: text,
    node: node,
    clock: clock,
    blocks: blocks,
    portions: portions,
    numberLine: numberLine,
    fractionBar: fractionBar,
    barModel: barModel,
    scale: scale,
    arrow: arrow,
    leader: leader,
    equations: equations
  };

  global.BoardKit = BoardKit;
})(window);
