// misaki-lite (runtime agent, prototype): misaki 0.9's American-English G2P (misaki/en.py) without spaCy, so it runs in a browser.
// Ported: misaki's us_gold + us_silver lexicon (grown as misaki does), special cases, -s / -ed / -ing stemming, stress rules,
// right-to-left future-vowel context, sub-token groups (longest suffix match, prespace, stress demotion), numbers (num2words
// cardinal / year / ordinal / decimal, currency) and punctuation. Replaced: spaCy's tokenizer by a small prefix / suffix /
// abbreviation splitter, and spaCy's POS tags by "no tag" (dictionary DEFAULTs) plus three guesses: 'a' before a word is a
// determiner, 'I' a pronoun, an all-caps word whose noun reading is spelled out (US) a proper noun. Words it cannot resolve fall
// back to eSpeak NG + misaki.js, as misaki falls back to eSpeak. DEV mismatch vs real misaki: tools/phon_mismatch.mjs --frontend lite.
import { textToPhonemes as espeakChain } from "./espeak_chain.mjs";

const STRESSES = "ˌˈ", PRIMARY = "ˈ", SECONDARY = "ˌ";
const VOWELS = new Set("AIOQWYaiuæɑɒɔəɛɜɪʊʌᵻ"), CONSONANTS = new Set("bdfhjklmnpstvwzðŋɡɹɾʃʒʤʧθ"), US_TAUS = new Set("AIOWYiuæɑəɛɪɹʊʌ");
const PUNCTS = new Set(';:,.!?—…"“”'), NON_QUOTE_PUNCTS = new Set(";:,.!?—…"), DIPHTHONGS = new Set("AIOQWYʤʧ");
const SUBTOKEN_JUNKS = new Set("',-._‘’/");
const SYMBOLS = { "%": "percent", "&": "and", "+": "plus", "@": "at" };
const CURRENCIES = { $: ["dollar", "cent"], "£": ["pound", "pence"], "€": ["euro", "cent"] };
const ORDINALS = ["st", "nd", "rd", "th"];
const SUBTOKEN = /^['‘’]+|\p{Lu}(?=\p{Lu}\p{Ll})|(?:^-)?(?:\d?[,.]?\d)+|[-_]+|['‘’]{2,}|\p{L}*?(?:['‘’]\p{L})*?\p{Ll}(?=\p{Lu})|\p{L}+(?:['‘’]\p{L})*|[^-_\p{L}'‘’\d]|['‘’]+$/gu;
// spaCy tokenizer exceptions that keep their final period (plus every single letter)
const ABBREVS = new Set(("Adm Ala Apr Ariz Ark Aug Bros Calif Capt Cmdr Co Col Colo Conn Corp Dec Del Dr Feb Fla Ft Ga Gen Gov Ill Inc Ind " +
  "Jan Jr Jul Jun Kan Kans Ky La Lt Ltd Mar Mass Md Messrs Mfg Mich Minn Miss Mo Mont Mr Mrs Ms Mt Neb Nebr Nev Nov Oct Okla Ore Pa " +
  "Ph Prof Rep Rev Sen Sep Sept Sgt Sr St Tenn Va Wash Wis co vs etc").split(" "));
let gold = null, silver = null;

// A lexicon is misaki's dictionary as two sorted arrays (keys, values) searched by bisection: decoding the packed file is ~5x
// cheaper than building a Map. misaki's grow_dictionary (Capitalised / lower-case twins of every entry, real entries winning)
// is applied at lookup time instead of materialising 90k more keys.
class Lex {
  constructor(keys, vals) { this.k = keys; this.v = vals; }
  raw(w) {
    const K = this.k; let lo = 0, hi = K.length - 1;
    while (lo <= hi) {
      const m = (lo + hi) >> 1, x = K[m];
      if (x === w) { let v = this.v[m]; if (typeof v === "string" && v.charCodeAt(0) === 123) v = this.v[m] = JSON.parse(v); return v; }
      if (x < w) lo = m + 1; else hi = m - 1;
    }
    return undefined;
  }
  get(w) {
    const v = this.raw(w); if (v !== undefined || w.length < 2) return v;
    const lo = w.toLowerCase(), cap = w[0].toUpperCase() + w.slice(1).toLowerCase();
    if (w === cap && w !== lo) return this.raw(lo);     // twin of a lower-case entry
    if (w === lo && w !== cap) return this.raw(cap);    // twin of a Capitalised entry
    return undefined;
  }
  has(w) { return this.get(w) !== undefined; }
}
export function parseLexicon(text) {   // tools/lexicon_pack.mjs format (sorted, front-coded)
  const L = text.split("\n"), K = new Array(L.length), V = new Array(L.length); let prev = "";
  for (let i = 0; i < L.length; i++) {
    const line = L[i], t = line.indexOf("\t"), p = line.charCodeAt(0) - 48, k = (p ? prev.slice(0, p) : "") + line.slice(1, t);
    K[i] = k; V[i] = line.slice(t + 1); prev = k;
  }
  return new Lex(K, V);
}
const fromObject = (o) => { const K = Object.keys(o).sort(); return new Lex(K, K.map((k) => o[k])); };
// sources: a URL of a packed lexicon, or a plain object (misaki's JSON). Silver may arrive later (setSilver); until then gold only.
const getLex = async (s) => (s instanceof Lex ? s : typeof s === "string" ? parseLexicon(await (await fetch(s)).text()) : fromObject(s));
export async function loadLexicon(goldSrc, silverSrc) { gold = await getLex(goldSrc); silver = silverSrc ? await getLex(silverSrc) : new Lex([], []); }
export async function setSilver(silverSrc) { silver = await getLex(silverSrc); }

// ---- sharded lexicon (browser start-up): tools/lexicon_shard.mjs splits gold / silver into shards by lower-case key range, so a
// page fetches only the shards the words of a sentence can touch (a few kB each) instead of the whole lexicon on its critical path.
// A lookup that falls in a shard not loaded yet is recorded and the sentence is phonemised again once those shards are in, so the
// result is always exactly the full lexicon's. useFullLexicon() switches to the complete files when they arrive in the background.
const missing = new Set();
class ShardLex extends Lex {
  constructor(tag, first, always, fetchShard) { super([], []); Object.assign(this, { tag, first, always, fetchShard, shards: new Array(first.length) }); }
  sid(w) { const lo = w.toLowerCase(), F = this.first; let a = 0, b = F.length - 1; while (a < b) { const m = (a + b + 1) >> 1; if (F[m] <= lo) a = m; else b = m - 1; } return a; }
  raw(w) {
    const v = this.always.raw(w); if (v !== undefined) return v;
    const s = this.sid(w), sh = this.shards[s];
    if (!sh) { missing.add(`${this.tag}:${s}`); return undefined; }
    return sh.raw(w);
  }
  async load(ids) { await Promise.all([...ids].filter((i) => !this.shards[i]).map(async (i) => { this.shards[i] = parseLexicon(await this.fetchShard(this.tag, i)); })); }
}
let sharded = null;
// fetchText(name) -> Promise<string> for files of the shard directory (index.json, always.txt, g000.txt ...)
export async function loadShardedLexicon(fetchText) {
  const [index, always] = await Promise.all([fetchText("index.json").then(JSON.parse), fetchText("always.txt").then(parseLexicon)]);
  const shard = (tag, i) => fetchText(`${tag}${String(i).padStart(3, "0")}.txt`);
  gold = new ShardLex("g", index.shards.g, always, shard); silver = new ShardLex("s", index.shards.s, new Lex([], []), shard);
  sharded = { g: gold, s: silver };
}
export function useFullLexicon(goldLex, silverLex) { gold = goldLex; silver = silverLex; sharded = null; }
async function loadMissing() {
  if (!sharded) { missing.clear(); return; }
  const by = { g: new Set(), s: new Set() }; for (const k of missing) { const [t, i] = k.split(":"); by[t].add(+i); }
  await Promise.all([sharded.g.load(by.g), sharded.s.load(by.s)]);
}
// prefetch: the shards of every word of the text and of its simple stems / case forms (one round trip in the common case)
async function prefetch(text) {
  if (!sharded) return; const keys = new Set();
  for (const t of tokenize(text.replace(/\s+/g, " ").trim())) if (!t.punct) {
    const w = t.subs.join("").replaceAll("’", "'"), parts = [w, ...t.subs];
    for (const p of parts) for (const k of [p, p.slice(0, -1), p.slice(0, -2), p.slice(0, -3), p.slice(0, -3) + "y", p.slice(0, -3) + "e", p.slice(0, -4)]) if (/[A-Za-z]/.test(k)) keys.add(k);
  }
  // gold only: silver is consulted only where gold has nothing, so its shards come on demand (an extra round trip when needed)
  for (const k of keys) missing.add(`g:${sharded.g.sid(k)}`);
  await loadMissing(); missing.clear();
}
const has = (d, k) => Object.prototype.hasOwnProperty.call(d, k);
const isAlpha = (w) => /^\p{L}+$/u.test(w), isDigit = (w) => /^[0-9]+$/.test(w);
const upper = (w) => w.toUpperCase(), lower = (w) => w.toLowerCase();

function applyStress(ps, stress) {
  const restress = (ps) => {
    const ips = [...ps].map((p, i) => [i, p]); const moved = {};
    ips.forEach(([i, p]) => { if (STRESSES.includes(p)) { const j = ips.slice(i).find(([, v]) => VOWELS.has(v)); if (j) moved[i] = j[0] - 0.5; } });
    for (const [i, j] of Object.entries(moved)) ips[+i][0] = j;
    return ips.sort((a, b) => a[0] - b[0]).map(([, p]) => p).join("");
  };
  if (stress == null || ps == null) return ps;
  if (stress < -1) return ps.replaceAll(PRIMARY, "").replaceAll(SECONDARY, "");
  if (stress === -1 || ((stress === 0 || stress === -0.5) && ps.includes(PRIMARY))) return ps.replaceAll(SECONDARY, "").replaceAll(PRIMARY, SECONDARY);
  const hasS = [...STRESSES].some((s) => ps.includes(s)), hasV = [...ps].some((c) => VOWELS.has(c));
  if ([0, 0.5, 1].includes(stress) && !hasS) return hasV ? restress(SECONDARY + ps) : ps;
  if (stress >= 1 && !ps.includes(PRIMARY) && ps.includes(SECONDARY)) return ps.replaceAll(SECONDARY, PRIMARY);
  if (stress > 1 && !hasS) return hasV ? restress(PRIMARY + ps) : ps;
  return ps;
}
const stressWeight = (ps) => (ps ? [...ps].reduce((a, c) => a + (DIPHTHONGS.has(c) ? 2 : 1), 0) : 0);

// ---- Lexicon ----
function getNNP(word) {
  const ps = [...word].filter((c) => /\p{L}/u.test(c)).map((c) => gold.get(upper(c)));
  if (ps.some((p) => typeof p !== "string")) return null;
  const s = applyStress(ps.join(""), 0); const k = s.lastIndexOf(SECONDARY);
  return k < 0 ? s : s.slice(0, k) + PRIMARY + s.slice(k + 1);
}
function lookup(word, stress, ctx) {
  if (word === upper(word) && !gold.has(word)) word = lower(word);
  let ps = gold.get(word) ?? null; if (ps == null) ps = silver.get(word) ?? null;
  if (ps && typeof ps === "object") {
    // no tagger: an all-caps word whose noun reading is spelled out (US, IT) is taken as that proper noun
    if (word === upper(word) && word.length > 1 && "NOUN" in ps && ps.NOUN == null) ps = null;
    else ps = ctx && ctx.futureVowel == null && "None" in ps ? ps["None"] : ps["DEFAULT"];
  }
  if (ps == null) return getNNP(word);
  return applyStress(ps, stress);
}
function isKnown(word) {
  if (gold.has(word) || has(SYMBOLS, word) || silver.has(word)) return true;
  if (!/^[A-Za-z]+$/.test(word)) return false;
  if (word.length === 1) return true;
  if (word === upper(word) && gold.has(lower(word))) return true;
  return word.slice(1) === upper(word.slice(1));
}
const _s = (st) => (!st ? null : "ptkfθ".includes(st.at(-1)) ? st + "s" : "szʃʒʧʤ".includes(st.at(-1)) ? st + "ᵻz" : st + "z");
function stemS(w, stress, ctx) {
  if (w.length < 3 || !w.endsWith("s")) return null; let st;
  if (!w.endsWith("ss") && isKnown(w.slice(0, -1))) st = w.slice(0, -1);
  else if ((w.endsWith("'s") || (w.length > 4 && w.endsWith("es") && !w.endsWith("ies"))) && isKnown(w.slice(0, -2))) st = w.slice(0, -2);
  else if (w.length > 4 && w.endsWith("ies") && isKnown(w.slice(0, -3) + "y")) st = w.slice(0, -3) + "y";
  else return null;
  return _s(lookup(st, stress, ctx));
}
function _ed(st) {
  if (!st) return null; const l = st.at(-1);
  if ("pkfθʃsʧ".includes(l)) return st + "t"; if (l === "d") return st + "ᵻd"; if (l !== "t") return st + "d";
  if (st.length < 2) return st + "ɪd"; if (US_TAUS.has(st.at(-2))) return st.slice(0, -1) + "ɾᵻd"; return st + "ᵻd";
}
function stemEd(w, stress, ctx) {
  if (w.length < 4 || !w.endsWith("d")) return null; let st;
  if (!w.endsWith("dd") && isKnown(w.slice(0, -1))) st = w.slice(0, -1);
  else if (w.length > 4 && w.endsWith("ed") && !w.endsWith("eed") && isKnown(w.slice(0, -2))) st = w.slice(0, -2);
  else return null;
  return _ed(lookup(st, stress, ctx));
}
const _ing = (st) => (!st ? null : st.length > 1 && st.at(-1) === "t" && US_TAUS.has(st.at(-2)) ? st.slice(0, -1) + "ɾɪŋ" : st + "ɪŋ");
function stemIng(w, stress, ctx) {
  if (w.length < 5 || !w.endsWith("ing")) return null; let st;
  if (w.length > 5 && isKnown(w.slice(0, -3))) st = w.slice(0, -3);
  else if (isKnown(w.slice(0, -3) + "e")) st = w.slice(0, -3) + "e";
  else if (w.length > 5 && /([bcdgklmnprstvxz])\1ing$|cking$/.test(w) && isKnown(w.slice(0, -4))) st = w.slice(0, -4);
  else return null;
  return _ing(lookup(st, stress, ctx));
}
function specialCase(word, ctx) {
  if (has(SYMBOLS, word)) return lookup(SYMBOLS[word], null, ctx);
  const parts = word.split(".");
  if (word.replace(/^\.+|\.+$/g, "").includes(".") && isAlpha(word.replaceAll(".", "")) && Math.max(...parts.map((p) => p.length)) < 3) return getNNP(word);
  if (word === "a" || word === "A") return ctx.nextIsWord ? "ɐ" : "ˈA";
  if (word === "am" || word === "Am" || word === "AM") return ctx.futureVowel == null || word !== "am" ? gold.get("am") : "ɐm";
  if (word === "an" || word === "An" || word === "AN") return "ɐn";
  if (word === "I") return SECONDARY + "I";
  if (word === "to" || word === "To") return ctx.futureVowel == null ? gold.get("to") : ctx.futureVowel ? "tʊ" : "tə";
  if (word === "in" || word === "In" || word === "IN") return (ctx.futureVowel == null ? PRIMARY : "") + "ɪn";
  if (word === "the" || word === "The" || word === "THE") return ctx.futureVowel === true ? "ði" : "ðə";
  if (/^vs\.?$/i.test(word)) return lookup("versus", null, ctx);
  if (word === "used" || word === "Used" || word === "USED") return gold.get("used").DEFAULT;
  return null;
}
function getWord(word, stress, ctx) {
  const sc = specialCase(word, ctx); if (sc != null) return sc;
  const wl = lower(word);
  if (word.length > 1 && isAlpha(word.replaceAll("'", "")) && word !== wl && !gold.has(word) && !silver.has(word) &&
      (word === upper(word) || word.slice(1) === lower(word.slice(1))) &&
      (gold.has(wl) || silver.has(wl) || stemS(wl, stress, ctx) || stemEd(wl, stress, ctx) || stemIng(wl, stress, ctx))) word = wl;
  if (isKnown(word)) return lookup(word, stress, ctx);
  if (word.endsWith("s'") && isKnown(word.slice(0, -2) + "'s")) return lookup(word.slice(0, -2) + "'s", stress, ctx);
  if (word.endsWith("'") && isKnown(word.slice(0, -1))) return lookup(word.slice(0, -1), stress, ctx);
  return stemS(word, stress, ctx) ?? stemEd(word, stress, ctx) ?? stemIng(word, stress == null ? 0.5 : stress, ctx);
}

// ---- numbers (num2words, English) ----
const ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split(" ");
const TENS = ",,twenty,thirty,forty,fifty,sixty,seventy,eighty,ninety".split(",");
const SCALES = [[1e12, "trillion"], [1e9, "billion"], [1e6, "million"], [1e3, "thousand"]];
function cardinal(n) {   // word list; num2words' "and" and commas are dropped by misaki anyway
  if (n < 20) return [ONES[n]];
  if (n < 100) return n % 10 ? [TENS[Math.floor(n / 10)], ONES[n % 10]] : [TENS[n / 10]];
  if (n < 1000) return [ONES[Math.floor(n / 100)], "hundred", ...(n % 100 ? cardinal(n % 100) : [])];
  if (n < 1e15) for (const [v, w] of SCALES) if (n >= v) { const h = Math.floor(n / v), r = n - h * v; return [...cardinal(h), w, ...(r ? cardinal(r) : [])]; }
  return [...String(n)].map((d) => ONES[+d]);
}
function ordinal(n) {
  const w = cardinal(n), l = w.pop();
  const irr = { one: "first", two: "second", three: "third", five: "fifth", eight: "eighth", nine: "ninth", twelve: "twelfth" };
  return [...w, irr[l] ?? (l.endsWith("y") ? l.slice(0, -1) + "ieth" : l + "th")];
}
function year(n) {
  const hi = Math.floor(n / 100), lo = n % 100;
  if (hi === 0 || (hi % 10 === 0 && lo < 10) || hi >= 100) return cardinal(n);
  return [...cardinal(hi), ...(lo === 0 ? ["hundred"] : lo < 10 ? ["oh", ...cardinal(lo)] : cardinal(lo))];
}
function isNumber(word, isHead) {
  if (![...word].some((c) => c >= "0" && c <= "9")) return false;
  for (const s of ["ing", "'d", "ed", "'s", ...ORDINALS, "s"]) if (word.endsWith(s)) { word = word.slice(0, -s.length); break; }
  return [...word].every((c, i) => (c >= "0" && c <= "9") || c === "," || c === "." || (isHead && i === 0 && c === "-"));
}
function getNumber(word, currency, isHead) {
  const m = /[a-z']+$/.exec(word), suffix = m ? m[0] : null; if (suffix) word = word.slice(0, -suffix.length);
  const res = [];
  if (word.startsWith("-")) { res.push(lookup("minus", null, null)); word = word.slice(1); }
  const ext = (ws, stress) => { for (const w of ws) res.push(lookup(w, w === "point" ? -2 : stress ?? null, null)); };
  const digitsOf = (s) => [...s].forEach((d) => ext(cardinal(+d)));
  if (isDigit(word) && ORDINALS.includes(suffix)) ext(ordinal(+word));
  else if (!res.length && word.length === 4 && !CURRENCIES[currency] && isDigit(word)) ext(year(+word));
  else if (!isHead && !word.includes(".")) {
    const num = word.replaceAll(",", "");
    if (num[0] === "0" || num.length > 3) digitsOf(num);
    else if (num.length === 3 && !num.endsWith("00")) { ext(cardinal(+num[0])); if (num[1] === "0") { res.push(lookup("O", -2, null)); ext(cardinal(+num[2])); } else ext(cardinal(+num.slice(1))); }
    else ext(cardinal(+num));
  } else if ((word.match(/\./g) || []).length > 1 || !isHead) {
    for (const num of word.replaceAll(",", "").split(".")) {
      if (!num) continue;
      if (num[0] === "0" || (num.length !== 2 && [...num.slice(1)].some((d) => d !== "0"))) digitsOf(num); else ext(cardinal(+num));
    }
  } else if (CURRENCIES[currency] && (!word.includes(".") || word.split(".")[1].length < 3)) {
    let pairs = word.replaceAll(",", "").split(".").map((n, i) => [n ? +n : 0, CURRENCIES[currency][i]]).filter(([, u]) => u);
    if (pairs.length > 1) { if (pairs[1][0] === 0) pairs = pairs.slice(0, 1); else if (pairs[0][0] === 0) pairs = pairs.slice(1); }
    pairs.forEach(([n, unit], i) => { if (i > 0) res.push(lookup("and", null, null)); ext(cardinal(n)); res.push(Math.abs(n) !== 1 && unit !== "pence" ? stemS(unit + "s", null, null) : lookup(unit, null, null)); });
  } else if (!word.includes(".")) ext(ORDINALS.includes(suffix) ? ordinal(+word.replaceAll(",", "")) : cardinal(+word.replaceAll(",", "")));
  else {
    const [ip, fp] = String(parseFloat(word.replaceAll(",", ""))).split(".");
    ext([...(word[0] === "." ? [] : cardinal(+ip)), "point", ...[...(word[0] === "." ? word.slice(1) : fp || "0")].flatMap((d) => cardinal(+d))]);
  }
  if (!res.length || res.some((p) => p == null)) return null;
  const ps = res.join(" ");
  if (suffix === "s" || suffix === "'s") return _s(ps);
  if (suffix === "ed" || suffix === "'d") return _ed(ps);
  if (suffix === "ing") return _ing(ps);
  return ps;
}
function lexicon(text, isHead, currency, ctx) {   // Lexicon.__call__
  const w = text.replaceAll("‘", "'").replaceAll("’", "'").normalize("NFKC");
  const stress = w === lower(w) ? null : w === upper(w) ? 2 : 0.5;
  let ps = getWord(w, stress, ctx);
  if (ps != null) return currency && CURRENCIES[currency] ? `${ps} ${stemS(CURRENCIES[currency][0] + "s", null, null)}` : ps;
  if (isNumber(w, isHead)) return getNumber(w, currency, isHead);
  return null;
}

// ---- tokens ----
// spaCy-like split: whitespace chunks; opening quotes / brackets / currency peeled off the front; closing punctuation off the
// back unless the chunk is an abbreviation; dashes and ellipses split out; the rest goes through misaki's subtokenizer into a
// group (sub-tokens without whitespace between them, looked up together first, e.g. 50% or well-known or 1990s).
const PRE = new Set('"“‘([{$£€'), POST = new Set('"”)]}.,;:!?…');
function tokenize(text) {
  const toks = []; let quoteOpen = false;
  const punct = (t, ps) => toks.push({ punct: true, text: t, ps, ws: "" });
  const quote = (open) => { quoteOpen = open; return open ? "“" : "”"; };
  for (const m of text.matchAll(/(\S+)(\s*)/g)) {
    let c = m[1]; const tail = [];
    while (c && PRE.has(c[0])) {
      if (CURRENCIES[c[0]]) toks.push({ punct: true, text: c[0], ps: "", currency: c[0], ws: "" });
      else punct(c[0], c[0] === '"' ? quote(!(quoteOpen && /^"[^\p{L}\d]*$/u.test(c))) : c[0] === "“" || c[0] === "‘" ? quote(true) : "([{".includes(c[0]) ? "(" : "");
      c = c.slice(1);
    }
    while (c && POST.has(c.at(-1))) {
      const l = c.at(-1);
      if (l === "." && (/^(?:[A-Za-z]{1,2}\.)+[A-Za-z]{1,2}$/.test(c.slice(0, -1)) || /^[A-Za-z]$/.test(c.slice(0, -1)) || ABBREVS.has(c.slice(0, -1)))) break;
      if (l === "." && c.endsWith("...")) { tail.unshift(["...", "..."]); c = c.slice(0, -3); continue; }
      tail.unshift([l, l === '"' || l === "”" ? null : ")]}".includes(l) ? ")" : PUNCTS.has(l) ? l : ""]); c = c.slice(0, -1);
    }
    for (const piece of c.split(/(—|–|…|--)/)) {
      if (!piece) continue;
      if (/^(—|–|…|--)$/.test(piece)) { punct(piece, piece === "…" ? "…" : "—"); continue; }
      if (piece === "-") { punct(piece, "—"); continue; }
      const subs = piece.match(SUBTOKEN) || [];
      const last = toks.at(-1);
      const g = last && !last.punct && !last.ws ? last : (toks.push({ subs: [], ws: "" }), toks.at(-1));
      for (const s of subs) g.subs.push(s);
    }
    for (const [t, ps] of tail) punct(t, ps ?? quote(false));
    if (m[2] && toks.length) toks.at(-1).ws = " ";
  }
  // currency: the last number-like token after $ / £ / €
  for (let i = 0; i < toks.length; i++) if (toks[i].punct && toks[i].currency) {
    let j = i + 1; const num = (t) => t && !t.punct && (/\d/.test(t.subs[0]) || ["hundred", "thousand", "million", "billion", "trillion"].includes(lower(t.subs.join(""))));
    while (num(toks[j + 1])) j++;
    if (num(toks[j])) toks[j].currency = toks[i].currency;
  }
  return toks;
}
function nextContext(ctx, ps, text) {   // G2P.token_context
  let fv = ctx.futureVowel;
  if (ps) for (const c of ps) if (VOWELS.has(c) || CONSONANTS.has(c) || NON_QUOTE_PUNCTS.has(c)) { fv = NON_QUOTE_PUNCTS.has(c) ? null : VOWELS.has(c); break; }
  return { futureVowel: fv, futureTo: text === "to" || text === "To", nextIsWord: false };
}
function resolveGroup(subs, ps) {   // G2P.resolve_tokens + merge_tokens
  const text = subs.join("");
  const kinds = new Set([...text].filter((c) => !SUBTOKEN_JUNKS.has(c)).map((c) => (/\p{L}/u.test(c) ? 0 : /\d/.test(c) ? 1 : 2)));
  const prespace = text.includes("/") || kinds.size > 1;
  if (!prespace) {
    const idx = ps.map((p, i) => [p && p.includes(PRIMARY) ? 1 : 0, stressWeight(p), i]).filter(([, , i]) => ps[i]);
    if (idx.length === 2 && subs[idx[0][2]].length === 1) ps[idx[1][2]] = applyStress(ps[idx[1][2]], -0.5);
    else if (idx.length >= 2 && idx.reduce((a, [b]) => a + b, 0) > Math.floor((idx.length + 1) / 2))
      for (const [, , i] of idx.sort((a, b) => a[0] - b[0] || a[1] - b[1] || a[2] - b[2]).slice(0, idx.length >> 1)) ps[i] = applyStress(ps[i], -0.5);
  }
  let out = "";
  ps.forEach((p, i) => { if (i > 0 && prespace && out && !/\s$/.test(out) && p) out += " "; out += p; });
  return out;
}
export const stats = { espeakCalls: 0, passes: 0 };   // words (sub-token groups) sent to the eSpeak fallback; sharded-lexicon passes
async function espeak(text) { stats.espeakCalls++; return (await espeakChain(text)).trim(); }

export async function g2p(text) {
  if (!sharded) return g2pOnce(text);
  await prefetch(text);
  for (;;) {
    missing.clear(); stats.passes++; const ps = await g2pOnce(text);
    if (!missing.size) return ps;
    if (!sharded) { missing.clear(); return g2pOnce(text); }   // the complete lexicon arrived meanwhile
    await loadMissing();
  }
}
async function g2pOnce(text) {
  const toks = tokenize(text.replace(/\s+/g, " ").trim()); let ctx = { futureVowel: null, futureTo: false, nextIsWord: false };
  for (let i = toks.length - 1; i >= 0; i--) {
    const t = toks[i];
    if (t.punct) { ctx = { ...nextContext(ctx, t.ps, t.text), nextIsWord: false }; continue; }
    const w = t.subs, ps = w.map(() => null); let left = 0, right = w.length, fallback = false;
    while (left < right) {   // longest suffix match, right to left
      const merged = w.slice(left, right).join("");
      const p = lexicon(merged, left === 0, right === w.length ? t.currency : null, ctx);
      if (p != null) { ps[left] = p; for (let k = left + 1; k < right; k++) ps[k] = ""; ctx = { ...nextContext(ctx, p, merged), nextIsWord: true }; right = left; left = 0; }
      else if (left + 1 < right) left++;
      else { right--; if (ps[right] == null) { if ([...w[right]].every((c) => SUBTOKEN_JUNKS.has(c))) ps[right] = ""; else { fallback = true; break; } } left = 0; }
    }
    if (fallback && missing.size) { t.ps = ""; continue; }   // a lookup hit an unloaded shard: this pass is redone, skip eSpeak
    if (fallback) { t.ps = await espeak(w.join("")); ctx = { ...nextContext(ctx, t.ps, w.join("")), nextIsWord: true }; }
    else t.ps = w.length === 1 ? ps[0] : resolveGroup(w, ps);
  }
  return toks.map((t) => (t.ps ?? "") + t.ws).join("").trim().replaceAll("ɾ", "T").replaceAll("ʔ", "t");
}
