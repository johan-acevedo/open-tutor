// Streaming playback for Paradee's chunks: an AudioWorklet queue player in a 24 kHz AudioContext (no resampling; Chrome,
// Firefox and Safari honour the sampleRate option). Create it from a user gesture (autoplay policy), then push chunks as they
// arrive (from the same thread, or transferred from a Worker).
//   const player = await createPlayer();
//   player.reset(); for await (const c of tts.stream(text)) player.push(c); player.end();
//   player.onstart = () => ...; player.onfinish = ({ played, underruns }) => ...;
export async function createPlayer(ctx = new AudioContext({ sampleRate: 24000, latencyHint: "interactive" })) {
  if (ctx.sampleRate !== 24000) throw new Error(`AudioContext runs at ${ctx.sampleRate} Hz; Paradee needs 24000`);
  await ctx.audioWorklet.addModule(new URL("./player-worklet.js", import.meta.url));
  const node = new AudioWorkletNode(ctx, "stream-player", { outputChannelCount: [1] }); node.connect(ctx.destination);
  const p = {
    ctx, node, onstart: null, onfinish: null,
    push(samples) { node.port.postMessage({ samples }, [samples.buffer]); },   // transfers the buffer
    end() { node.port.postMessage({ end: true }); },                            // no more chunks for this utterance
    reset() { node.port.postMessage({ reset: true }); },                        // drop queued audio, start a new utterance
    resume: () => (ctx.state === "suspended" ? ctx.resume() : Promise.resolve()),
  };
  node.port.onmessage = (e) => { if (e.data.started) p.onstart?.(); if (e.data.finished) p.onfinish?.(e.data); };
  return p;
}
