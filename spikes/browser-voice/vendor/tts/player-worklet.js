// Streaming player: a queue of Float32Array chunks played at the context rate (24 kHz). Reports when sound starts, underruns
// (queue empty before the producer said it was done), and samples played.
class StreamPlayer extends AudioWorkletProcessor {
  constructor() {
    super(); this.q = []; this.off = 0; this.playing = false; this.ended = true; this.played = 0; this.underruns = 0; this.starved = false;
    this.port.onmessage = (e) => {
      const d = e.data;
      if (d.reset) { this.q = []; this.off = 0; this.playing = false; this.ended = false; this.played = 0; this.underruns = 0; this.starved = false; }
      else if (d.end) this.ended = true;
      else this.q.push(d.samples);
    };
  }
  process(_, outputs) {
    const out = outputs[0][0]; let i = 0;
    while (i < out.length && this.q.length) {
      const b = this.q[0], n = Math.min(out.length - i, b.length - this.off);
      out.set(b.subarray(this.off, this.off + n), i); i += n; this.off += n;
      if (this.off >= b.length) { this.q.shift(); this.off = 0; }
    }
    out.fill(0, i);
    if (i > 0) {
      if (!this.playing) { this.playing = true; this.port.postMessage({ started: true }); }
      if (this.starved) { this.starved = false; }
      this.played += i;
    } else if (this.playing) {
      if (!this.ended && !this.starved) { this.starved = true; this.underruns++; }
      if (this.ended && !this.q.length) { this.playing = false; this.port.postMessage({ finished: true, played: this.played, underruns: this.underruns }); }
    }
    if (i > 0 && this.ended && !this.q.length && this.off === 0) { this.playing = false; this.port.postMessage({ finished: true, played: this.played, underruns: this.underruns }); }
    return true;
  }
}
registerProcessor("stream-player", StreamPlayer);
