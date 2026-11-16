// Phonemes -> Paradee token ids (the model's tokenizer.json: drop characters outside its set, one id per character, '$' (0) at
// both ends). No transformers.js needed: the tokenizer is a character map. Inputs over 512 ids must be split by the caller
// (paradee.mjs splits long sentences at punctuation / word boundaries first).
let tok = null;
export async function loadTokenizer(src) {   // src: URL of tokenizer.json, or the parsed object
  const j = typeof src === "string" || src instanceof URL ? await (await fetch(src)).json() : src;
  tok = { vocab: j.model.vocab, strip: new RegExp(j.normalizer.pattern.Regex, "gu") };
}
export function tokenize(ps) {
  const s = ps.replace(tok.strip, ""); const ids = [0];
  for (const ch of s) { const v = tok.vocab[ch]; if (v !== undefined) ids.push(v); }
  ids.push(0); return Int32Array.from(ids.slice(0, 512));
}
