// Browser probe transport only. Production Vite never aliases this module.
export const ConnectionState = { Connected: 'connected', Reconnecting: 'reconnecting' };
export const Track = { Kind: { Audio: 'audio' } };
export const RoomEvent = Object.fromEntries(
  [
    'AudioPlaybackStatusChanged',
    'TrackSubscribed',
    'TrackUnsubscribed',
    'ParticipantAttributesChanged',
    'ParticipantConnected',
    'Reconnecting',
    'ConnectionStateChanged',
    'Disconnected',
  ].map((k) => [k, k]),
);
export class RpcError extends Error {
  constructor(code, message) {
    super(message);
    this.code = code;
  }
}
window.mobileProbe = { rooms: [], events: [], blockAudio: false, failBytes: false };
export class Room {
  constructor(options) {
    this.options = options;
    this.handlers = new Map();
    this.rpc = new Map();
    this.streams = new Map();
    this.remoteParticipants = new Map();
    this.canPlaybackAudio = false;
    this.localParticipant = {
      identity: 'fictional-learner',
      setMicrophoneEnabled: async (on) => {
        window.mobileProbe.events.push(['mic', on]);
      },
      sendText: async (text, options) => {
        window.mobileProbe.events.push(['text', text, options]);
        if (text.includes('"type":"end"')) setTimeout(() => this.emit(RoomEvent.Disconnected), 20);
      },
      sendBytes: async (bytes, options) => {
        if (window.mobileProbe.failBytes) throw new Error('synthetic network failure');
        window.mobileProbe.events.push(['bytes', bytes.length, options]);
      },
    };
    window.mobileProbe.rooms.push(this);
  }
  on(event, fn) {
    const list = this.handlers.get(event) || [];
    list.push(fn);
    this.handlers.set(event, list);
    return this;
  }
  off(event, fn) {
    this.handlers.set(
      event,
      (this.handlers.get(event) || []).filter((x) => x !== fn),
    );
  }
  emit(event, ...args) {
    (this.handlers.get(event) || []).forEach((fn) => fn(...args));
  }
  removeAllListeners() {
    this.handlers.clear();
  }
  async startAudio() {
    window.mobileProbe.events.push(['startAudio']);
    this.canPlaybackAudio = !window.mobileProbe.blockAudio;
    this.emit(RoomEvent.AudioPlaybackStatusChanged, this.canPlaybackAudio);
    if (!this.canPlaybackAudio) throw new Error('synthetic autoplay block');
  }
  async connect() {
    window.mobileProbe.events.push(['connect']);
  }
  async disconnect() {
    this.emit(RoomEvent.Disconnected);
  }
  registerRpcMethod(name, fn) {
    this.rpc.set(name, fn);
  }
  unregisterRpcMethod(name) {
    this.rpc.delete(name);
  }
  registerTextStreamHandler(name, fn) {
    this.streams.set(name, fn);
  }
  unregisterTextStreamHandler(name) {
    this.streams.delete(name);
  }
}
