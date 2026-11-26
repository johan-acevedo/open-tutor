import { useCallback, useEffect, useRef, useState } from 'react';
import { ConnectionState, Room, RoomEvent, RpcError, Track, TrackEvent } from 'livekit-client';
import type { RpcInvocationData } from 'livekit-client';
import type { BandId } from './bands';
import type { BoardFocusPayload, BoardItem, HomeworkAttributes, Note, SessionResponse } from './protocol';
import type { PageShellMessage } from './components/PageCard';
import {
  ATTR_AGENT_STATE,
  ATTR_TUTOR_MODE,
  BOARD_RPC_FOCUS,
  BOARD_RPC_LOADING,
  BOARD_RPC_PATCH,
  BOARD_RPC_POINT,
  BOARD_RPC_REVEAL,
  BOARD_RPC_SHOW,
  BOARD_RPC_UPDATE,
  TOPIC_CHAT,
  TOPIC_HOMEWORK,
  TOPIC_HOMEWORK_TEXT,
  TOPIC_NOTE,
  TOPIC_SESSION_EVENT,
  TOPIC_TRANSCRIPTION,
  TOPIC_TUTOR_EVENT,
  LEARNER_RPC_SET_GRADE,
  LEARNER_RPC_SET_NAME,
  LEARNER_RPC_SWITCH,
} from './protocol';
import { enqueueNote, enqueueProfileGrade, enqueueProfileName, enqueueProfileSwitch, rememberLastProfileId, updateProfile } from './db';
import type { NamingSession } from './db';
import { handleNote, handleSetGrade, handleSetName, handleSwitch } from './learnerRpc';
import { createEndGate, routeAfterDisconnect, routeAfterEnd } from './lessonEnd';
import { localeId, t } from './locales/sv';
import type { Profile } from './db';
import {
  getDeviceId,
  homeworkShared,
  identifyLearner,
  micPermission,
  resourceOpened,
  sessionEnded,
  sessionFailed,
  sessionStarted,
  sessionStartRequested,
  turnSent,
} from './analytics';
import { AgentGate } from './agentGate';
import { validateBoardFocus, validateBoardItem, validateBoardLoading, validateBoardPageOp } from './validate';
import { dataUrlToBytes, downscaleImage } from './image';
import { useWakeLock } from './useWakeLock';
import { audioElementBusy } from './audioTracks';
import { createDiagLog, initialVisibilityState, observeMicTrack, type DiagLog } from './callDiagnostics';
import type { HomeworkDraft } from './components/HomeworkTray';

export type Phase = 'profiles' | 'connecting' | 'live' | 'ending' | 'ended';
export type ConnBanner = 'reconnecting' | 'disconnected' | null;

const MOUNT_TIMEOUT_MS = 4500;
// Board pane size reporting: the board model needs the real pane size
// (window minus avatar panel etc.), not the window size. Clamped server-side too.
const BOARD_MIN = 320;
const BOARD_MAX = 3840;
const BOARD_RESIZE_DEBOUNCE_MS = 400;
// How long a typed message waits for the agent participant before we send anyway
// (the worker queues anything that arrives before its session can answer).
const AGENT_WAIT_MS = 15000;

function boardDevice(): string {
  try {
    return window.matchMedia('(max-width: 600px), (max-width: 950px) and (max-height: 500px) and (pointer: coarse)').matches
      ? 'mobile'
      : 'desktop';
  } catch {
    return 'desktop';
  }
}

function clampBoard(n: number, fallback: number): number {
  if (!Number.isFinite(n)) return fallback;
  return Math.max(BOARD_MIN, Math.min(Math.round(n), BOARD_MAX));
}

/** Await the pane transition, excluding the pending card's infinite animation. */
async function waitForBoardLayout(): Promise<void> {
  const board = document.querySelector('.ot-board');
  if (!board || typeof board.getAnimations !== 'function') return;
  const running = board.getAnimations({ subtree: false }).filter(
    (animation) => (animation.playState === 'running' || animation.pending)
      && Number.isFinite(Number(animation.effect?.getComputedTiming().endTime)),
  );
  await Promise.allSettled(running.map((animation) => animation.finished));
  await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
}

/** Measure the real board surface: the visible .ot-board-scroll content box
 *  where the frame sits. The outer .ot-board also holds the phone nav and the
 *  follow button, and its width includes the scroller padding, so measuring
 *  it overstates the space the board model can use. Falls back to the window
 *  when the surface is not mounted yet (profiles/connecting). */
export function readBoardSize(): { w: number; h: number; device: string } {
  const device = boardDevice();
  try {
    const scroller = document.querySelector('.ot-board-scroll');
    if (scroller) {
      const el = scroller as HTMLElement;
      const style = window.getComputedStyle(el);
      const padX = (parseFloat(style.paddingLeft) || 0) + (parseFloat(style.paddingRight) || 0);
      const padY = (parseFloat(style.paddingTop) || 0) + (parseFloat(style.paddingBottom) || 0);
      const w = el.clientWidth - padX;
      const h = el.clientHeight - padY;
      if (w >= 1 && h >= 1) {
        return { w: clampBoard(w, window.innerWidth), h: clampBoard(h, window.innerHeight), device };
      }
      const r = el.getBoundingClientRect();
      if (r.width >= 1 && r.height >= 1) {
        return {
          w: clampBoard(r.width - padX, window.innerWidth),
          h: clampBoard(r.height - padY, window.innerHeight),
          device,
        };
      }
    }
  } catch {
    /* fall through to window size */
  }
  return { w: clampBoard(window.innerWidth, 1920), h: clampBoard(window.innerHeight, 1080), device };
}
// The tutor saves a note and says goodbye before it closes the room (which disconnects us);
// this is only the fallback if that never happens. 8 s cut goodbyes off mid-sentence.
const END_WAIT_MS = 25000;
const IMAGE_EXT = ['png', 'jpg', 'jpeg', 'webp'];
const PDF_EXT = ['pdf'];

function uid(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID();
  return `id-${Date.now()}-${Math.floor(Math.random() * 1e9)}`;
}

function extOf(name: string): string {
  const i = name.lastIndexOf('.');
  return i >= 0 ? name.slice(i + 1).toLowerCase() : '';
}

async function sendHomeworkBytes(room: Room, bytes: Uint8Array, attrs: HomeworkAttributes): Promise<void> {
  const attributes: Record<string, string> = {
    kind: attrs.kind,
    source: attrs.source,
    itemId: attrs.itemId,
  };
  if (attrs.page !== undefined) attributes.page = attrs.page;
  if (attrs.pages !== undefined) attributes.pages = attrs.pages;
  const local = room.localParticipant;
  if (typeof local.sendBytes === 'function') {
    await local.sendBytes(bytes, {
      topic: TOPIC_HOMEWORK,
      attributes,
      mimeType: 'image/jpeg',
      name: attrs.source,
    });
    return;
  }
  // Fallback for older clients: incremental byte stream.
  const stream = await (
    local as unknown as {
      streamBytes: (o: Record<string, unknown>) => Promise<WritableStream<Uint8Array>>;
    }
  ).streamBytes({ topic: TOPIC_HOMEWORK, attributes, mimeType: 'image/jpeg', name: attrs.source });
  const writer = stream.getWriter();
  try {
    const chunk = 16384;
    for (let i = 0; i < bytes.length; i += chunk) {
      await writer.write(bytes.subarray(i, i + chunk));
    }
  } finally {
    await writer.close();
  }
}

/** Register an RPC method on the room (falls back to the deprecated local-participant API). */
function registerRpc(room: Room, method: string, handler: (d: RpcInvocationData) => Promise<string>): void {
  if (typeof room.registerRpcMethod === 'function') {
    room.registerRpcMethod(method, handler);
  } else {
    room.localParticipant.registerRpcMethod(method, handler);
  }
}

function unregisterRpc(room: Room, method: string): void {
  try {
    if (typeof room.unregisterRpcMethod === 'function') room.unregisterRpcMethod(method);
    else room.localParticipant.unregisterRpcMethod(method);
  } catch {
    /* ignore */
  }
}

export function useSession(mobile = false, band: BandId = 'primary') {
  const [phase, setPhase] = useState<Phase>('profiles');
  const [profile, setProfile] = useState<Profile | null>(null);
  const [items, setItems] = useState<BoardItem[]>([]);
  const [focused, setFocused] = useState<BoardFocusPayload | null>(null);
  const [sessionNotes, setSessionNotes] = useState<Note[]>([]);
  const [caption, setCaption] = useState('');
  const [captionFading, setCaptionFading] = useState(false);
  const [agentState, setAgentState] = useState<string | null>(null);
  const [tutorMode, setTutorMode] = useState<string | null>(null);
  const [hasSpokenFirst, setHasSpokenFirst] = useState(false);
  const [micEnabled, setMicEnabled] = useState(false);
  const [micBlocked, setMicBlocked] = useState(false);
  const [connBanner, setConnBanner] = useState<ConnBanner>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [lastSent, setLastSent] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [sending, setSending] = useState(false);
  const [activeItemId, setActiveItemId] = useState<string | null>(null);
  // Bumped whenever the tutor puts something in front of the child (a new
  // item, a focus, or a patch to the visible page). The phone turns from the
  // fox to the item on every bump, so the child never misses what was shown.
  const [boardSignal, setBoardSignal] = useState(0);
  const [homeworkDraft, setHomeworkDraft] = useState<HomeworkDraft | null>(null);
  const [homeworkSending, setHomeworkSending] = useState(false);
  const [audioBlocked, setAudioBlocked] = useState(false);
  const [resumeNeeded, setResumeNeeded] = useState(false);
  // Keep the screen awake only while the lesson is live. Releases on end/unmount
  // and re-requests on foreground return; denied or unsupported browsers run on.
  useWakeLock(phase === 'live');

  const roomRef = useRef<Room | null>(null);
  // The age band for sessions started from this page load. Ref so the
  // session request always sends the current band without re-wiring start.
  const bandRef = useRef<BandId>(band);
  bandRef.current = band;
  // In-call switch (learner.switch RPC): the student the start page is
  // prefilled for after this lesson ends. Consumed once, when the lesson
  // ends; a failed tool call never arms it, and B is remembered as active
  // only when B's session actually starts.
  const pendingPrefillRef = useRef<Profile | null>(null);
  const [prefillId, setPrefillId] = useState<string | null>(null);
  // Why the worker ended the call (TOPIC_TUTOR_EVENT, before the room was
  // deleted): today only 'idle_timeout' after a long learner silence. The
  // ref steers the disconnect handler; the state renders the end card line.
  const endReasonRef = useRef<string | null>(null);
  const [endReason, setEndReason] = useState<string | null>(null);
  // Session generation: handlers capture the generation they were registered
  // in and never touch UI or profile state from an old one (delayed note or
  // grade callbacks from A must not land on B). A name RPC from an ended or
  // previous session writes nothing: the generation is checked before its
  // persistence, and every end path bumps it.
  const sessionGenRef = useRef(0);
  // Lesson generation: bumped only when a new lesson starts. The end-of-lesson
  // note arrives after Avsluta has already bumped sessionGenRef, and it must
  // still reach this lesson's end card; only a newer lesson replaces it.
  const lessonGenRef = useRef(0);
  // Voice-naming state for this session: which profile this session's naming
  // created, if any. Reset when a session starts; the store uses it to tell a
  // temporary profile this session created (safe to rename or supersede)
  // from a stored profile from an earlier visit.
  const namingRef = useRef<NamingSession>({ createdId: null });
  // One end transition per lesson: double leave, Avsluta during goodbye, or
  // tutor switch plus menu at once all share it — exactly one end, the note
  // saved once, cleanup touching only its own room. See lessonEnd.ts.
  const endGateRef = useRef(createEndGate());
  // Menu "leave" flow: end this lesson properly, then open the name entry.
  const goProfilesAfterEndRef = useRef(false);
  const [profilesOpen, setProfilesOpen] = useState(false);
  const pageSendsRef = useRef(new Map<string, (msg: PageShellMessage) => void>());
  const preparedRoomRef = useRef<Room | null>(null);
  const profileRef = useRef<Profile | null>(null);
  const intentionalEndRef = useRef(false);
  const mountResolvers = useRef(
    new Map<string, Array<{ resolve: () => void; reject: (err: unknown) => void; timer: number }>>(),
  );
  const audioRef = useRef<HTMLAudioElement | null>(null);
  // Extra elements for a second agent audio track (the fox's filler sounds).
  const extraAudioRef = useRef<HTMLAudioElement[]>([]);
  const audioContextRef = useRef<AudioContext | null>(null);
  const micWantedRef = useRef(true);
  // Bounded browser-side call diagnostics (visibility, connection, mic-track
  // reality vs wanted state, playback, resume outcomes). Fresh per session.
  const diagRef = useRef<DiagLog | null>(null);
  const diagStopRef = useRef<(() => void) | null>(null);
  const toastTimer = useRef<number>(0);
  const sentTimer = useRef<number>(0);
  const captionTimer = useRef<number>(0);
  // Session wall-clock for the session_ended duration (seconds, one decimal).
  const sessionStartAtRef = useRef(0);
  const sessionEndTrackedRef = useRef(false);
  const boardWatchStopRef = useRef<(() => void) | null>(null);
  const boardLastSentRef = useRef<string>('');
  // A data message published before the agent participant is in the room is dropped
  // by the room, so everything the page sends to the tutor waits for the agent first.
  const agentGateRef = useRef<AgentGate>(new AgentGate());

  /** Report the session end once, from whichever path ends it first. */
  const trackSessionEnd = useCallback((reason: string) => {
    if (sessionEndTrackedRef.current) return;
    sessionEndTrackedRef.current = true;
    const durationS = sessionStartAtRef.current
      ? Math.round((Date.now() - sessionStartAtRef.current) / 100) / 10
      : 0;
    sessionEnded(reason, durationS);
  }, []);

  const showToast = useCallback((msg: string) => {
    setToast(msg);
    window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(null), 4000);
  }, []);

  const noteAgentPresent = useCallback(() => {
    agentGateRef.current.markPresent();
    // The agent is here now: queued diagnostics have somewhere to go.
    void diagRef.current?.flush();
  }, []);

  /** Send one text stream message to the tutor, waiting for the agent to be there. */
  const sendToAgent = useCallback(
    async (text: string, topic: string, attributes?: Record<string, string>) => {
      await agentGateRef.current.wait(AGENT_WAIT_MS);
      const room = roomRef.current;
      if (!room) return;
      await room.localParticipant.sendText(text, { topic, ...(attributes ? { attributes } : {}) });
    },
    [],
  );

  // Page frames register their shell mailbox here; patch/reveal/point RPCs
  // deliver through it. A frame that is mounted but not ready yet holds the
  // message and passes it to the shell on ready (see PageCard).
  const registerPageFrame = useCallback(
    (id: string, send: ((msg: PageShellMessage) => void) | null) => {
      if (send) pageSendsRef.current.set(id, send);
      else pageSendsRef.current.delete(id);
    },
    [],
  );

  // A submitted answer from ot-answer, ot-choice or ot-gap reaches the tutor
  // on the session-event text stream.
  const sendPageAnswer = useCallback(
    (answer: { page: string; part: string; value: string; kind: string }) => {
      const room = roomRef.current;
      if (!room) return;
      void sendToAgent(JSON.stringify({ type: 'page-answer', ...answer }), TOPIC_SESSION_EVENT)
        .catch(() => undefined);
    },
    [sendToAgent],
  );

  const resolveMounted = useCallback((id: string) => {
    const list = mountResolvers.current.get(id);
    if (list) {
      mountResolvers.current.delete(id);
      for (const w of list) {
        window.clearTimeout(w.timer);
        w.resolve();
      }
    }
  }, []);

  // A card reports a terminal render failure (e.g. a page frame that never
  // loaded). Reject now so the board RPC answers with an error instead of
  // timing out — a failed render is never acknowledged.
  const rejectMounted = useCallback((id: string, message: string) => {
    const list = mountResolvers.current.get(id);
    if (list) {
      mountResolvers.current.delete(id);
      for (const w of list) {
        window.clearTimeout(w.timer);
        w.reject(new RpcError(1500, message));
      }
    }
  }, []);

  const waitForMounted = useCallback((id: string, timeoutMs = MOUNT_TIMEOUT_MS) => {
    return new Promise<void>((resolve, reject) => {
      const waiter: { resolve: () => void; reject: (err: unknown) => void; timer: number } = {
        resolve,
        reject,
        timer: 0,
      };
      const list = mountResolvers.current.get(id) ?? [];
      list.push(waiter);
      mountResolvers.current.set(id, list);
      waiter.timer = window.setTimeout(() => {
        const pending = mountResolvers.current.get(id);
        if (pending) {
          const remaining = pending.filter((w) => w !== waiter);
          if (remaining.length) mountResolvers.current.set(id, remaining);
          else mountResolvers.current.delete(id);
          reject(new RpcError(1501, 'The browser did not confirm rendering this board item'));
        }
      }, timeoutMs);
    });
  }, []);

  const readParticipantStates = useCallback((room: Room) => {
    for (const p of room.remoteParticipants.values()) {
      const st = p.attributes?.[ATTR_AGENT_STATE];
      const mode = p.attributes?.[ATTR_TUTOR_MODE];
      if (typeof st === 'string' && st) setAgentState(st);
      if (typeof mode === 'string' && mode) setTutorMode(mode);
    }
  }, []);

  const cleanupRoom = useCallback(() => {
    const stop = boardWatchStopRef.current;
    boardWatchStopRef.current = null;
    if (stop) {
      try {
        stop();
      } catch {
        /* ignore */
      }
    }
    const stopDiag = diagStopRef.current;
    diagStopRef.current = null;
    if (stopDiag) {
      try {
        stopDiag();
      } catch {
        /* ignore */
      }
    }
    // Only delivered events survive session cleanup. Overflow is counted,
    // but a lost final tail cannot be detected by sequence gaps.
    diagRef.current = null;
    // The room is gone: no learner RPC still in flight from it may persist.
    // Bumping here covers every end path (Avsluta, menu leave, in-call
    // switch, unmount); start() bumps again for the new session.
    sessionGenRef.current += 1;
    const room = roomRef.current;
    roomRef.current = null;
    preparedRoomRef.current = null;
    for (const extra of extraAudioRef.current) {
      extra.srcObject = null;
    }
    extraAudioRef.current = [];
    const context = audioContextRef.current;
    audioContextRef.current = null;
    if (context) void context.close().catch(() => undefined);
    if (!room) return;
    for (const m of [
      BOARD_RPC_SHOW,
      BOARD_RPC_UPDATE,
      BOARD_RPC_FOCUS,
      BOARD_RPC_PATCH,
      BOARD_RPC_REVEAL,
      BOARD_RPC_POINT,
      BOARD_RPC_LOADING,
      LEARNER_RPC_SET_GRADE,
      LEARNER_RPC_SET_NAME,
      LEARNER_RPC_SWITCH,
        ])
      unregisterRpc(room, m);
    try {
      room.unregisterTextStreamHandler(TOPIC_TRANSCRIPTION);
    } catch {
      /* ignore */
    }
    try {
      room.unregisterTextStreamHandler(TOPIC_NOTE);
    } catch {
      /* ignore */
    }
    try {
      room.unregisterTextStreamHandler(TOPIC_TUTOR_EVENT);
    } catch {
      /* ignore */
    }
    room.removeAllListeners();
    void room.disconnect().catch(() => undefined);
  }, []);

  // Called directly by Starta, before profile persistence or the session request.
  const prepareStart = useCallback(() => {
    cleanupRoom();
    let context: AudioContext | undefined;
    try {
      context = new AudioContext();
      audioContextRef.current = context;
      void context.resume().catch(() => {
        if (audioContextRef.current === context) setAudioBlocked(true);
      });
    } catch {
      /* Playback recovery remains available if Web Audio is unavailable. */
    }
    const room = new Room({
      audioCaptureDefaults: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      ...(context ? { webAudioMix: { audioContext: context } } : {}),
    });
    roomRef.current = room;
    preparedRoomRef.current = room;
    room.on(RoomEvent.AudioPlaybackStatusChanged, (enabled) => {
      if (roomRef.current === room) setAudioBlocked(!enabled);
    });
    void room.startAudio().catch(() => {
      if (roomRef.current === room) setAudioBlocked(true);
    });
  }, [cleanupRoom]);

  const clearProfilesOpen = useCallback(() => {
    setProfilesOpen(false);
  }, []);

  const start = useCallback(
    async (p: Profile, bandOverride?: BandId) => {
      // A chooser card starts the call in its own band: the UI theme and
      // the session request must agree in the same tick, before React
      // re-renders, so the override is applied directly.
      if (bandOverride) bandRef.current = bandOverride;
      if (!preparedRoomRef.current) prepareStart();
      const room = roomRef.current;
      if (!room) return;
      preparedRoomRef.current = null;
      intentionalEndRef.current = false;
      pendingPrefillRef.current = null;
      goProfilesAfterEndRef.current = false;
      setPrefillId(null);
      setProfilesOpen(false);
      // A new generation: callbacks from the previous session (delayed
      // notes, grades, names) never touch this one's UI or profile.
      sessionGenRef.current += 1;
      lessonGenRef.current += 1;
      namingRef.current = { createdId: null };
      profileRef.current = p;
      setProfile(p);
      // Stamp the call's band on a stored profile so the household picker
      // can show which companion each remembered learner belongs to. Old
      // profiles without a band stay valid; the stamp just fills it in.
      if (p.name.trim() !== '' && p.band !== bandRef.current) {
        const callBand = bandRef.current;
        const stampId = p.id;
        void updateProfile(stampId, { band: callBand })
          .then((stamped) => {
            if (stamped && profileRef.current?.id === stamped.id) {
              profileRef.current = stamped;
              setProfile(stamped);
            }
          })
          .catch(() => undefined);
      }
      setItems([]);
      setActiveItemId(null);
      setHomeworkDraft(null);
      setResumeNeeded(false);
      micWantedRef.current = true;
      setFocused(null);
      setSessionNotes([]);
      setCaption('');
      setCaptionFading(false);
      setAgentState(null);
      setTutorMode(null);
      setHasSpokenFirst(false);
      setMicEnabled(false);
      setMicBlocked(false);
      setConnBanner(null);
      setDragOver(false);
      mountResolvers.current.clear();
      setPhase('connecting');
      sessionStartAtRef.current = 0;
      sessionEndTrackedRef.current = false;
      endReasonRef.current = null;
      setEndReason(null);
      sessionStartRequested();
      agentGateRef.current.reset();
      // Fresh per-session diagnostics: seq/dropped restart so journals never mix rooms.
      const diag = createDiagLog({
        send: (text) => room.localParticipant.sendText(text, { topic: TOPIC_SESSION_EVENT }),
        isReady: () =>
          roomRef.current === room && agentGateRef.current.isReady() && room.state === ConnectionState.Connected,
      });
      diagRef.current = diag;
      {
        const init = initialVisibilityState();
        diag.note('visibility', { state: init.state, via: 'init', precise: init.precise });
      }

      const notes = p.notes.slice(-5).reverse(); // newest first
      let session: SessionResponse;
      let failStatus: string | number = 'request-failed';
      try {
        const request = () => {
          const board = readBoardSize();
          boardLastSentRef.current = `${board.w}x${board.h}:${board.device}`;
          return fetch('/api/session', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ learner: { id: p.id, name: p.name, grade: p.grade, notes, band: bandRef.current, locale: localeId },
              board, device_id: getDeviceId() }),
          });
        };
        const res = await request();
        if (res.status === 429) {
          sessionFailed(429);
          showToast(t('toast.full'));
          cleanupRoom();
          setPhase('profiles');
          return;
        }
        if (!res.ok) {
          failStatus = res.status;
          throw new Error(`session ${res.status}`);
        }
        session = (await res.json()) as SessionResponse;
        // Attribute the session to this browser's anonymous device id. The
        // name (if any) stays local: identify carries the grade only.
        identifyLearner(p.grade);
      } catch {
        sessionFailed(failStatus);
        showToast(t('toast.startFailed'));
        setPhase('profiles');
        cleanupRoom();
        return;
      }

      room.on(RoomEvent.TrackSubscribed, (track, _pub, participant) => {
        if (track.kind === Track.Kind.Audio && participant.identity !== room.localParticipant.identity) {
          const el = audioRef.current;
          if (el && !audioElementBusy(el)) {
            track.attach(el);
            void el.play().catch(() => setAudioBlocked(true));
            return;
          }
          // The agent already publishes speech on one track; its filler sounds arrive
          // on a second one, and one element carries one stream. Give it its own.
          const extra = track.attach() as HTMLAudioElement;
          extra.setAttribute('aria-hidden', 'true');
          extraAudioRef.current.push(extra);
          void extra.play().catch(() => undefined);
        }
      });
      room.on(RoomEvent.TrackUnsubscribed, (track) => {
        try {
          track.detach();
        } catch {
          /* ignore */
        }
      });
      room.on(RoomEvent.ParticipantAttributesChanged, (changed) => {
        const st = (changed as Record<string, string>)[ATTR_AGENT_STATE];
        const mode = (changed as Record<string, string>)[ATTR_TUTOR_MODE];
        if (typeof st === 'string' && st) {
          setAgentState(st);
          if (st === 'speaking') setHasSpokenFirst(true);
        }
        if (typeof mode === 'string' && mode) setTutorMode(mode);
      });
      room.on(RoomEvent.ParticipantConnected, () => {
        noteAgentPresent();
        readParticipantStates(room);
      });
      room.on(RoomEvent.Reconnecting, () => {
        if (!intentionalEndRef.current) setConnBanner('reconnecting');
        diag.note('connection', { kind: 'reconnecting' });
      });
      room.on(RoomEvent.Reconnected, () => {
        diag.note('connection', { kind: 'reconnected' });
        void diag.flush();
      });
      room.on(RoomEvent.ConnectionStateChanged, (state: ConnectionState) => {
        if (state === ConnectionState.Connected) setConnBanner(null);
        else if (state === ConnectionState.Reconnecting && !intentionalEndRef.current) {
          setConnBanner('reconnecting');
        }
        diag.note('connection', { kind: 'state', state: String(state) });
      });
      room.on(RoomEvent.Disconnected, (reason) => {
        // In-call switch: the worker ended A's lesson after the learner.switch
        // ack. Show the start page prefilled for B — no automatic reconnect,
        // no continuation session. B is remembered only when B's session starts.
        const prefill = pendingPrefillRef.current;
        if (prefill) {
          pendingPrefillRef.current = null;
          // The switch prefill wins over a simultaneous menu leave: consume
          // that flag too, or B's own later Avsluta would skip B's end card.
          goProfilesAfterEndRef.current = false;
          trackSessionEnd('switched');
          diag.note('connection', { kind: 'disconnected-switch', reason: String(reason ?? '') });
          cleanupRoom();
          setPrefillId(prefill.id);
          setProfilesOpen(false);
          setProfile(null);
          setPhase('profiles');
          return;
        }
        const route = routeAfterDisconnect({
          prefillId: null,
          goProfiles: goProfilesAfterEndRef.current,
          intentional: intentionalEndRef.current,
          endReason: endReasonRef.current,
        });
        // Our own end path already handled the landing: stand down.
        if (route.kind === 'ignore') return;
        if (route.kind === 'banner') {
          trackSessionEnd('disconnected');
          setConnBanner('disconnected');
          diag.note('connection', { kind: 'disconnected', reason: String(reason ?? '') });
          return;
        }
        // The worker ended the call itself (idle timeout): the lesson ended
        // properly, so land like a local end — the end card, not the banner.
        goProfilesAfterEndRef.current = false;
        trackSessionEnd('idle_timeout');
        diag.note('connection', { kind: 'disconnected-idle', reason: String(reason ?? '') });
        cleanupRoom();
        if (route.kind === 'open') {
          setProfilesOpen(true);
          setProfile(null);
          setPhase('profiles');
        } else {
          setPhase('ended');
        }
      });
      // Local microphone reality vs the wanted state (micWantedRef): the SDK
      // reacquires ended tracks on its own, so this only observes and logs.
      const audioCtxState = () => {
        try {
          return audioContextRef.current?.state ?? 'unavailable';
        } catch {
          return 'unavailable';
        }
      };
      room.on(RoomEvent.AudioPlaybackStatusChanged, (enabled) => {
        diag.note('playback', { allowed: enabled, ctx: audioCtxState(), via: 'event' });
      });
      room.on(RoomEvent.TrackMuted, (pub, participant) => {
        if (participant === room.localParticipant && pub.kind === Track.Kind.Audio) {
          diag.note('mic-track', { change: 'muted', wanted: micWantedRef.current, via: 'publication' });
        }
      });
      room.on(RoomEvent.TrackUnmuted, (pub, participant) => {
        if (participant === room.localParticipant && pub.kind === Track.Kind.Audio) {
          diag.note('mic-track', { change: 'unmuted', wanted: micWantedRef.current, via: 'publication' });
        }
      });
      const diagCleanups: Array<() => void> = [];
      let watchedMedia: MediaStreamTrack | null = null;
      let stopMicMedia: (() => void) | null = null;
      diagCleanups.push(() => stopMicMedia?.());
      const watchMicMediaTrack = (media: MediaStreamTrack | undefined) => {
        if (!media || watchedMedia === media) return;
        stopMicMedia?.();
        watchedMedia = media;
        stopMicMedia = observeMicTrack(media, diag, () => micWantedRef.current);
      };
      const context = audioContextRef.current;
      if (context) {
        const onContextState = () => diag.note('playback', {
          allowed: room.canPlaybackAudio, ctx: context.state, via: 'context',
        });
        context.addEventListener('statechange', onContextState);
        diagCleanups.push(() => context.removeEventListener('statechange', onContextState));
      }
      room.on(RoomEvent.LocalTrackPublished, (pub) => {
        if (pub.kind !== Track.Kind.Audio) return;
        diag.note('mic-track', { change: 'published', wanted: micWantedRef.current, via: 'publication' });
        watchMicMediaTrack(pub.track?.mediaStreamTrack);
        const local = pub.track;
        if (local && typeof local.on === 'function' && typeof local.off === 'function') {
          const onRestarted = () => {
            diag.note('mic-track', { change: 'restarted', wanted: micWantedRef.current, via: 'track' });
            // A restart can swap the underlying MediaStreamTrack: re-observe it.
            watchMicMediaTrack(pub.track?.mediaStreamTrack);
          };
          local.on(TrackEvent.Restarted, onRestarted);
          diagCleanups.push(() => {
            try {
              local.off(TrackEvent.Restarted, onRestarted);
            } catch {
              /* ignore */
            }
          });
        }
      });
      room.on(RoomEvent.LocalTrackUnpublished, (pub) => {
        if (pub.kind !== Track.Kind.Audio) return;
        diag.note('mic-track', { change: 'unpublished', wanted: micWantedRef.current, via: 'publication' });
      });
      diagStopRef.current = () => {
        for (const fn of diagCleanups) {
          try {
            fn();
          } catch {
            /* ignore */
          }
        }
      };

      registerRpc(room, BOARD_RPC_SHOW, async (data) => {
        let parsed: unknown;
        try {
          parsed = JSON.parse(data.payload);
        } catch {
          throw new RpcError(1500, 'board.show payload is not JSON');
        }
        const v = validateBoardItem(parsed);
        if (!v.ok) throw new RpcError(1500, v.error);
        setItems((prev) => {
          const i = prev.findIndex((b) => b.id === v.item.id);
          if (i >= 0) {
            const next = [...prev];
            next[i] = v.item;
            return next;
          }
          return [...prev, v.item];
        });
        setFocused(null);
        setActiveItemId(v.item.id);
        setBoardSignal((n) => n + 1);
        await waitForMounted(v.item.id);
        // For the first pending item this mount flips arrival->teaching:
        // report the size only once that transition has settled, so the
        // tutor commissions the finished pane, not the arrival one.
        await waitForBoardLayout();
        // Resources the tutor puts in front of the child (funnel step).
        try {
          if ((v.item as { kind: string }).kind === 'resource') resourceOpened();
        } catch {
          /* analytics must never break the board */
        }
        return JSON.stringify({ ok: true, board: readBoardSize() });
      });

      registerRpc(room, BOARD_RPC_UPDATE, async (data) => {
        let parsed: unknown;
        try {
          parsed = JSON.parse(data.payload);
        } catch {
          throw new RpcError(1500, 'board.update payload is not JSON');
        }
        const v = validateBoardItem(parsed);
        if (!v.ok) throw new RpcError(1500, v.error);
        setItems((prev) => {
          const i = prev.findIndex((b) => b.id === v.item.id);
          if (i >= 0) {
            const next = [...prev];
            next[i] = v.item;
            return next;
          }
          return [...prev, v.item];
        });
        setActiveItemId(v.item.id);
        setBoardSignal((n) => n + 1);
        await waitForMounted(v.item.id);
        await waitForBoardLayout();
        return JSON.stringify({ ok: true, board: readBoardSize() });
      });

      const pageOp = (field: 'patch' | 'part', method: string) => async (data: RpcInvocationData) => {
        let parsed: unknown;
        try {
          parsed = JSON.parse(data.payload);
        } catch {
          throw new RpcError(1500, `${method} payload is not JSON`);
        }
        const v = validateBoardPageOp(parsed, field);
        if (!v.ok) throw new RpcError(1500, v.error);
        const send = pageSendsRef.current.get(v.id);
        if (!send) throw new RpcError(1501, `no page frame is mounted for id ${v.id}`);
        if (field === 'patch') send({ ot: 'patch', html: v.arg });
        else if (method === BOARD_RPC_REVEAL) send({ ot: 'reveal', id: v.arg });
        else send({ ot: 'point', id: v.arg });
        // A patch changes what is on the page; the phone shows the page again.
        if (field === 'patch') setBoardSignal((n) => n + 1);
        return '{"ok":true}';
      };
      registerRpc(room, BOARD_RPC_PATCH, pageOp('patch', BOARD_RPC_PATCH));
      registerRpc(room, BOARD_RPC_REVEAL, pageOp('part', BOARD_RPC_REVEAL));
      registerRpc(room, BOARD_RPC_POINT, pageOp('part', BOARD_RPC_POINT));

      // Learner RPCs for the tutor's set_learner_name / set_learner_grade /
      // switch_student tools. Acknowledged: the tool returns only after the
      // browser answers, so a failed call leaves the call exactly as it was.
      // Handlers are pure (learnerRpc.ts); this only wires real browser
      // state. Profile writes run through one serialized queue (db.ts);
      // stale targets are rejected. The generation is captured here: a
      // callback from an old session (delayed grade after a restart) never
      // touches the current UI, and a grade update never changes which
      // profile is active. Naming a voice-first call does change it: the
      // session started with no stored profile, and the name either creates
      // it or attaches to an existing one with the same name.
      const myGen = sessionGenRef.current;
      const isCurrent = () => myGen === sessionGenRef.current;
      // The profile this session's notes belong to: the start profile, or
      // the named one once a voice-first call learns the name (applyName).
      let noteProfileId = p.id;
      const learnerDeps = {
        applyName: async (profileId: string, name: string) => {
          // A name RPC from an ended or previous session writes nothing:
          // reject before the serialized write, not after it.
          if (!isCurrent()) return undefined;
          const updated = await enqueueProfileName(
            profileId, name, () => profileRef.current?.id ?? null,
            { isCurrentSession: isCurrent, naming: namingRef.current },
          );
          if (updated && isCurrent()) {
            // The session's note binding follows the naming: notes saved
            // before the name was known would otherwise land nowhere.
            // Stamp the call's band so the household picker can show which
            // companion each remembered learner belongs to.
            let stamped = updated;
            const callBand = bandRef.current;
            if (updated.band !== callBand) {
              stamped = (await updateProfile(updated.id, { band: callBand })) ?? updated;
            }
            noteProfileId = stamped.id;
            profileRef.current = stamped;
            setProfile(stamped);
            rememberLastProfileId(stamped.id, callBand);
            identifyLearner(stamped.grade);
          }
          return isCurrent() ? updated : undefined;
        },
        applyGrade: async (profileId: string, grade: number) => {
          const updated = await enqueueProfileGrade(
            profileId, grade, () => profileRef.current?.id ?? null,
          );
          // Re-check before applying: the restart may have landed while the
          // queue was working. The grade keeps the right profile by id; the
          // UI follows only when this session is still current and the same
          // profile is still active.
          if (updated && isCurrent() && profileRef.current?.id === updated.id) {
            profileRef.current = updated;
            setProfile(updated);
          }
          return isCurrent() ? updated : undefined;
        },
        resolveStudent: (name: string) => enqueueProfileSwitch(name),
        armPrefill: (next: Profile) => {
          pendingPrefillRef.current = next;
        },
      };
      registerRpc(room, LEARNER_RPC_SET_NAME, (data) => handleSetName(data, learnerDeps));
      registerRpc(room, LEARNER_RPC_SET_GRADE, (data) => handleSetGrade(data, learnerDeps));
      registerRpc(room, LEARNER_RPC_SWITCH, (data) => handleSwitch(data, learnerDeps));

      registerRpc(room, BOARD_RPC_LOADING, async (data) => {
        let parsed: unknown;
        try {
          parsed = JSON.parse(data.payload);
        } catch {
          throw new RpcError(1500, 'board.loading payload is not JSON');
        }
        const v = validateBoardLoading(parsed);
        if (!v.ok) throw new RpcError(1500, v.error);
        const send = pageSendsRef.current.get(v.id);
        if (!send) throw new RpcError(1501, `no page frame is mounted for id ${v.id}`);
        // An empty topic clears: the shell removes the veil again.
        send({ ot: 'loading', topic: v.topic });
        return '{"ok":true}';
      });

      registerRpc(room, BOARD_RPC_FOCUS, async (data) => {
        let parsed: unknown;
        try {
          parsed = JSON.parse(data.payload);
        } catch {
          throw new RpcError(1500, 'board.focus payload is not JSON');
        }
        const v = validateBoardFocus(parsed);
        if (!v.ok) throw new RpcError(1500, v.error);
        setFocused(v.focus);
        setActiveItemId(v.focus.id);
        setBoardSignal((n) => n + 1);
        return '{"ok":true}';
      });

      room.registerTextStreamHandler(TOPIC_TRANSCRIPTION, async (reader, participantInfo) => {
        try {
          if (participantInfo.identity === room.localParticipant.identity) return;
          // The agent streams captions in step with its audio: show the words as they are spoken.
          let text = '';
          for await (const chunk of reader) {
            text += chunk;
            if (!text.trim()) continue;
            setCaption(captionTail(text));
            setCaptionFading(false);
            setHasSpokenFirst(true);
          }
        } catch {
          /* ignore */
        }
      });

      // Notes are bound to the profile id (and generation) this session
      // started with: a delayed note from lesson A is stored under A but
      // never touches B's UI or live profile. A voice-first naming updates
      // the binding (see applyName): the session started with no stored
      // profile, and the named one owns the notes from then on.
      const noteGen = lessonGenRef.current;
      room.registerTextStreamHandler(TOPIC_NOTE, async (reader) => {
        try {
          await handleNote(await reader.readAll(), {
            getSessionProfileId: () => noteProfileId,
            isCurrentSession: () => noteGen === lessonGenRef.current,
            getActiveId: () => profileRef.current?.id ?? null,
            onNote: (note, updated) => {
              setSessionNotes((prev) => [...prev, note]);
              if (updated) {
                profileRef.current = updated;
                setProfile(updated);
              }
            },
            saveNote: (profileId, note) => enqueueNote(profileId, note),
          });
        } catch {
          /* ignore */
        }
      });

      // The worker ends idle calls itself: { type: 'ended', reason } arrives
      // on this stream just before the room is deleted. Remember it so the
      // disconnect below lands on the end card with the reason, not the
      // reconnect banner.
      room.registerTextStreamHandler(TOPIC_TUTOR_EVENT, async (reader) => {
        try {
          const event = JSON.parse(await reader.readAll()) as {
            type?: unknown;
            reason?: unknown;
          };
          // The read is async: a stream from an older room must not write
          // its reason into a newer session.
          if (myGen !== sessionGenRef.current || roomRef.current !== room) return;
          if (event?.type === 'ended' && typeof event.reason === 'string') {
            endReasonRef.current = event.reason;
            setEndReason(event.reason);
          }
        } catch {
          /* ignore */
        }
      });

      try {
        await room.connect(session.url, session.token);
        sessionStarted(session.room);
        sessionStartAtRef.current = Date.now();
      } catch {
        sessionFailed('connect-failed');
        showToast(t('toast.connectFailed'));
        cleanupRoom();
        setPhase('profiles');
        return;
      }
      readParticipantStates(room);
      if (room.remoteParticipants.size > 0) noteAgentPresent();
      // A publication that predates the wiring above (defensive): observe it.
      for (const pub of room.localParticipant.audioTrackPublications.values()) {
        if (pub.kind === Track.Kind.Audio && pub.track) watchMicMediaTrack(pub.track.mediaStreamTrack);
      }
      // The session request only knew the window size (the board pane is not
      // mounted until we go live). Watch the real pane and report resizes,
      // rotation and layout changes over the existing session-event channel;
      // the tutor uses the latest size when commissioning a board.
      // Sends only on change, debounced.
      {
        const sendBoardSize = () => {
          const cur = roomRef.current;
          if (!cur) return;
          const b = readBoardSize();
          const key = `${b.w}x${b.h}:${b.device}`;
          if (key === boardLastSentRef.current) return;
          boardLastSentRef.current = key;
          void sendToAgent(JSON.stringify({ type: 'board-size', ...b }), TOPIC_SESSION_EVENT)
            .catch(() => undefined);
        };
        let debounce = 0;
        const scheduleSend = () => {
          window.clearTimeout(debounce);
          debounce = window.setTimeout(sendBoardSize, BOARD_RESIZE_DEBOUNCE_MS);
        };
        const onWindowChange = () => scheduleSend();
        window.addEventListener('resize', onWindowChange);
        window.addEventListener('orientationchange', onWindowChange);
        let ro: ResizeObserver | null = null;
        let observed: Element | null = null;
        const attachPane = () => {
          // Observe the scroll surface itself: nav/follow-button layout
          // changes alter its size, which is what the board is commissioned for.
          const pane = document.querySelector('.ot-board-scroll');
          if (pane && pane !== observed) {
            if (!ro && typeof ResizeObserver !== 'undefined') {
              ro = new ResizeObserver(() => scheduleSend());
            }
            observed = pane;
            if (ro) ro.observe(pane);
            scheduleSend();
          }
        };
        attachPane();
        // The pane mounts when we go live; retry until it is there.
        const retry1 = window.setTimeout(attachPane, 500);
        const retry2 = window.setTimeout(attachPane, 2000);
        const mo = new MutationObserver(attachPane);
        try {
          mo.observe(document.body, { childList: true, subtree: true });
        } catch {
          /* observer unavailable: window events still report resizes */
        }
        sendBoardSize();
        boardWatchStopRef.current = () => {
          window.clearTimeout(debounce);
          window.clearTimeout(retry1);
          window.clearTimeout(retry2);
          window.removeEventListener('resize', onWindowChange);
          window.removeEventListener('orientationchange', onWindowChange);
          mo.disconnect();
          if (ro) ro.disconnect();
        };
      }
      try {
        await room.startAudio();
        diag.note('playback', { allowed: room.canPlaybackAudio, ctx: audioCtxState(), via: 'start' });
      } catch {
        setAudioBlocked(true);
        diag.note('playback', { allowed: false, ctx: audioCtxState(), via: 'start' });
      }
      try {
        await room.localParticipant.setMicrophoneEnabled(true);
        setMicEnabled(true);
        setMicBlocked(false);
        micPermission(true);
        // The log needs the starting state, not only later button presses.
        void sendToAgent(JSON.stringify({ type: 'mic', on: true, why: 'start' }), TOPIC_SESSION_EVENT);
      } catch {
        // Mic denied: stay connected, banner + text field instead.
        setMicEnabled(false);
        setMicBlocked(true);
        micPermission(false);
        void sendToAgent(JSON.stringify({ type: 'mic', on: false, why: 'blocked' }), TOPIC_SESSION_EVENT);
      }
      setPhase('live');
    },
    [cleanupRoom, prepareStart, readParticipantStates, showToast, trackSessionEnd, waitForMounted],
  );

  const sendChat = useCallback(
    async (text: string) => {
      const room = roomRef.current;
      if (!room || phase !== 'live') return;
      setSending(true);
      // Say it at once: delivering it is ours to do, even if the tutor joins late.
      setLastSent(text);
      try {
        await sendToAgent(text, TOPIC_CHAT);
        turnSent();
        window.clearTimeout(sentTimer.current);
        sentTimer.current = window.setTimeout(() => setLastSent(null), 4000);
      } catch {
        setLastSent(null);
        showToast(t('toast.sendFailed'));
      } finally {
        setSending(false);
      }
    },
    [phase, sendToAgent, showToast],
  );

  const toggleMic = useCallback(async () => {
    const room = roomRef.current;
    if (!room) return;
    const next = !micEnabled;
    micWantedRef.current = next;
    try {
      await room.localParticipant.setMicrophoneEnabled(next);
      setMicEnabled(next);
      if (next) setMicBlocked(false);
      // Logged so a quiet stretch in a session can be told apart from a muted one.
      void sendToAgent(JSON.stringify({ type: 'mic', on: next, why: 'button' }), TOPIC_SESSION_EVENT);
    } catch {
      setMicEnabled(false);
      setMicBlocked(true);
    }
  }, [micEnabled, sendToAgent]);

  const retryMic = useCallback(async () => {
    const room = roomRef.current;
    if (!room) return;
    micWantedRef.current = true;
    try {
      await room.localParticipant.setMicrophoneEnabled(true);
      setMicEnabled(true);
      setMicBlocked(false);
      micPermission(true);
      void sendToAgent(JSON.stringify({ type: 'mic', on: true, why: 'retry' }), TOPIC_SESSION_EVENT);
    } catch {
      setMicEnabled(false);
      setMicBlocked(true);
      micPermission(false);
    }
  }, [sendToAgent]);

  const resumeMedia = useCallback(async () => {
    const room = roomRef.current;
    if (!room) return;
    // Outcome codes only — never raw exception text. Behavior unchanged.
    const diag = diagRef.current;
    diag?.note('resume', { step: 'attempt', ok: true, code: 'attempt' });
    // Both calls begin in the tap handler; neither waits for a network operation.
    const playback = room.startAudio();
    const context = audioContextRef.current;
    if (context?.state === 'suspended') void context.resume().catch(() => setAudioBlocked(true));
    try {
      await playback;
      const allowed = room.canPlaybackAudio;
      setAudioBlocked(!allowed);
      diag?.note('resume', { step: 'audio', ok: allowed, code: allowed ? 'ok' : 'audio-failed' });
    } catch {
      setAudioBlocked(true);
      diag?.note('resume', { step: 'audio', ok: false, code: 'audio-failed' });
    }
    if (resumeNeeded && micWantedRef.current) {
      try {
        await room.localParticipant.setMicrophoneEnabled(false);
        await room.localParticipant.setMicrophoneEnabled(true);
        setMicEnabled(true);
        setMicBlocked(false);
        diag?.note('resume', { step: 'mic', ok: true, code: 'ok' });
      } catch {
        setMicEnabled(false);
        setMicBlocked(true);
        diag?.note('resume', { step: 'mic', ok: false, code: 'mic-failed' });
      }
    }
    setResumeNeeded(false);
  }, [resumeNeeded]);

  useEffect(() => {
    if (phase !== 'live') return;
    let hidden = false;
    const onVisibility = () => {
      if (document.hidden) {
        hidden = true;
        diagRef.current?.note('visibility', { state: 'hidden', via: 'visibilitychange' });
      } else if (hidden) {
        hidden = false;
        if (mobile) setResumeNeeded(true);
        diagRef.current?.note('visibility', { state: 'visible', via: 'visibilitychange' });
      }
    };
    // pagehide/pageshow bracket what visibilitychange alone cannot: on iOS
    // a hidden page means lock-screen or app-switch, never diagnosed here.
    const onPageHide = () => {
      diagRef.current?.note('visibility', { state: 'hidden', via: 'pagehide' });
    };
    const onPageShow = () => {
      diagRef.current?.note('visibility', {
        state: document.visibilityState === 'visible' ? 'visible' : 'hidden',
        via: 'pageshow',
      });
    };
    document.addEventListener('visibilitychange', onVisibility);
    window.addEventListener('pagehide', onPageHide);
    window.addEventListener('pageshow', onPageShow);
    return () => {
      document.removeEventListener('visibilitychange', onVisibility);
      window.removeEventListener('pagehide', onPageHide);
      window.removeEventListener('pageshow', onPageShow);
    };
  }, [phase, mobile]);

  const resourceClosed = useCallback(
    async (id: string) => {
      const room = roomRef.current;
      if (!room) return;
      try {
        await sendToAgent(JSON.stringify({ type: 'resource-closed', id }), TOPIC_SESSION_EVENT);
      } catch {
        showToast(t('toast.notifyFailed'));
      }
    },
    [showToast],
  );

  // The single end transition for a room: claiming it twice (double menu
  // leave, Avsluta during goodbye, menu leave plus in-call switch) runs the
  // end exactly once. Cleanup touches only the room it started with.
  const endSession = useCallback(async () => {
    const room = roomRef.current;
    if (!room || phase !== 'live') return;
    if (!endGateRef.current.claim()) return;
    // Ending invalidates the generation at once: a late learner RPC from
    // this room is rejected before it persists, even before disconnect.
    sessionGenRef.current += 1;
    try {
      intentionalEndRef.current = true;
      trackSessionEnd('ended_by_child');
      setPhase('ending');
      setConnBanner(null);
      void diagRef.current?.flush();
      const disconnected = new Promise<void>((resolve) => {
        const onDisc = () => {
          room.off(RoomEvent.Disconnected, onDisc);
          resolve();
        };
        room.on(RoomEvent.Disconnected, onDisc);
        window.setTimeout(resolve, END_WAIT_MS);
      });
      try {
        await sendToAgent(JSON.stringify({ type: 'end' }), TOPIC_SESSION_EVENT);
      } catch {
        /* agent may already be gone; still show the end card */
      }
      await disconnected;
      // Only this room's disconnect ends the lesson: a newer session (or a
      // switch prefill) already replaced it, so leave that one alone.
      if (roomRef.current !== room) return;
      cleanupRoom();
      // A switch prefill always wins over a simultaneous menu leave.
      const route = routeAfterEnd({
        prefillId: pendingPrefillRef.current?.id ?? null,
        goProfiles: goProfilesAfterEndRef.current,
      });
      pendingPrefillRef.current = null;
      goProfilesAfterEndRef.current = false;
      if (route.kind === 'prefill') {
        // In-call switch: the start page for B, prefilled. B is remembered
        // only when B's session actually starts.
        setPrefillId(route.id);
        setProfilesOpen(false);
        setProfile(null);
        setPhase('profiles');
      } else if (route.kind === 'open') {
        // Menu leave: the lesson ended properly (note saved); open the name
        // entry directly instead of the end card.
        setProfilesOpen(true);
        setProfile(null);
        setPhase('profiles');
      } else {
        setPhase('ended');
      }
    } finally {
      endGateRef.current.release();
    }
  }, [cleanupRoom, phase, trackSessionEnd]);

  const backToProfiles = useCallback(() => {
    intentionalEndRef.current = true;
    // No lesson is running, but invalidate anyway: a learner RPC still in
    // flight from a dying room must not persist into the profiles page.
    sessionGenRef.current += 1;
    cleanupRoom();
    setProfilesOpen(false);
    setPhase('profiles');
    setProfile(null);
    setConnBanner(null);
  }, [cleanupRoom]);

  /** Pre-call menu switch entry: forget any in-call switch prefill and show
   *  the nameless first-visit page. */
  const showFirstVisit = useCallback(() => {
    pendingPrefillRef.current = null;
    setPrefillId(null);
    setProfilesOpen(true);
  }, []);

  /** Menu "leave": send `end` so the worker saves the note, then open the
   *  nameless start page directly (no second click). The end transition itself owns
   *  idempotency (see endSession): a second call while one is in flight
   *  stands down, and an end already running is only steered to the name
   *  entry — never cut short. */
  const leaveToProfiles = useCallback(async () => {
    if (phase !== 'live') {
      goProfilesAfterEndRef.current = true;
      setProfilesOpen(true);
      return;
    }
    goProfilesAfterEndRef.current = true;
    setProfilesOpen(true);
    await endSession();
  }, [phase, endSession]);

  // ---- Homework intake ----

  const addImageFile = useCallback(
    async (file: File, kind: 'photo' | 'screenshot') => {
      const room = roomRef.current;
      const itemId = uid();
      try {
        const down = await downscaleImage(file);
        const title = file.name || t('tray.fallbackImageTitle');
        setItems((prev) => [...prev, { id: itemId, kind: 'homework', title, images: [down.dataUrl] }]);
        setActiveItemId(itemId);
        homeworkShared('image');
        if (room) {
          await sendHomeworkBytes(room, down.bytes, { kind, source: file.name || t('tray.fallbackImageSource'), itemId });
        }
        return true;
      } catch {
        showToast(t('toast.imageFailed'));
        return false;
      }
    },
    [showToast],
  );

  const addPdfFile = useCallback(
    async (file: File) => {
      const room = roomRef.current;
      const itemId = uid();
      try {
        // Load the PDF engine only when a PDF actually arrives.
        const { renderPdfPages } = await import('./pdf');
        const pages = await renderPdfPages(file, 10, 1600);
        if (pages.length === 0) {
          showToast(t('toast.pdfEmpty'));
          return false;
        }
        const images = pages.map((pg) => pg.dataUrl);
        setItems((prev) => [...prev, { id: itemId, kind: 'homework', title: file.name || t('tray.fallbackPdfTitle'), images }]);
        setActiveItemId(itemId);
        homeworkShared('pdf');
        if (room) {
          const total = String(pages.length);
          for (let i = 0; i < pages.length; i++) {
            const bytes = dataUrlToBytes(pages[i].dataUrl);
            await sendHomeworkBytes(room, bytes, {
              kind: 'pdf-page',
              source: file.name || t('tray.fallbackPdfSource'),
              page: String(i + 1),
              pages: total,
              itemId,
            });
          }
        }
        return true;
      } catch {
        showToast(t('toast.pdfFailed'));
        return false;
      }
    },
    [showToast],
  );

  const addText = useCallback(
    async (text: string) => {
      const room = roomRef.current;
      const trimmed = text.trim();
      if (!trimmed) return;
      const itemId = uid();
      setItems((prev) => [...prev, { id: itemId, kind: 'homework', title: t('tray.pastedTitle'), text: trimmed }]);
      setActiveItemId(itemId);
      homeworkShared('text');
      if (room) {
        try {
          await sendToAgent(trimmed, TOPIC_HOMEWORK_TEXT, { itemId });
        } catch {
          showToast(t('toast.textFailed'));
          return false;
        }
      }
      return true;
    },
    [sendToAgent, showToast],
  );

  const addFiles = useCallback(
    async (files: File[] | FileList, fallbackKind: 'photo' | 'screenshot' = 'photo') => {
      for (const file of Array.from(files)) {
        const ext = extOf(file.name);
        const isImage = file.type.startsWith('image/') || IMAGE_EXT.includes(ext);
        const isPdf = file.type === 'application/pdf' || PDF_EXT.includes(ext);
        if (isImage) {
          await addImageFile(file, fallbackKind);
        } else if (isPdf) {
          await addPdfFile(file);
        } else {
          showToast(t('toast.fileType'));
        }
      }
    },
    [addImageFile, addPdfFile, showToast],
  );

  const queueFiles = useCallback((files: File[] | FileList, source: 'photo' | 'screenshot' = 'photo') => {
    if (files.length) setHomeworkDraft({ kind: 'files', files: Array.from(files), source });
  }, []);

  const sendHomework = useCallback(async () => {
    const draft = homeworkDraft;
    if (!draft || draft.kind === 'picker' || homeworkSending || phase !== 'live') return;
    setHomeworkSending(true);
    try {
      if (draft.kind === 'text') {
        if (await addText(draft.text)) setHomeworkDraft(null);
      } else {
        const failed: File[] = [];
        for (const file of draft.files) {
          const ext = extOf(file.name);
          const ok =
            file.type.startsWith('image/') || IMAGE_EXT.includes(ext)
              ? await addImageFile(file, draft.source)
              : file.type === 'application/pdf' || PDF_EXT.includes(ext)
                ? await addPdfFile(file)
                : false;
          if (!ok) failed.push(file);
        }
        setHomeworkDraft(failed.length ? { ...draft, files: failed } : null);
        if (failed.length) showToast(t('toast.allFailed'));
      }
    } finally {
      setHomeworkSending(false);
    }
  }, [homeworkDraft, homeworkSending, phase, addText, addImageFile, addPdfFile, showToast]);

  useEffect(() => {
    return () => {
      window.clearTimeout(toastTimer.current);
      window.clearTimeout(sentTimer.current);
      window.clearTimeout(captionTimer.current);
    };
  }, []);

  useEffect(() => () => cleanupRoom(), [cleanupRoom]);

  // Caption fades out 3 s after speech stops.
  useEffect(() => {
    window.clearTimeout(captionTimer.current);
    if (agentState === 'speaking') {
      setCaptionFading(false);
      return;
    }
    if (!caption) return;
    captionTimer.current = window.setTimeout(() => setCaptionFading(true), 3000);
  }, [agentState, caption]);

  useEffect(() => {
    if (phase !== 'live' && phase !== 'ending') return;
    const onPaste = (e: ClipboardEvent) => {
      const target = e.target as HTMLElement | null;
      const items = e.clipboardData?.items;
      if (!items) return;
      const files: File[] = [];
      let text = '';
      for (const it of Array.from(items)) {
        if (it.type.startsWith('image/')) {
          const f = it.getAsFile();
          if (f) files.push(f);
        } else if (it.type === 'text/plain') {
          // read via clipboardData string below
        }
      }
      if (files.length > 0) {
        e.preventDefault();
        if (mobile) queueFiles(files, 'screenshot');
        else void addFiles(files, 'screenshot');
        return;
      }
      if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA')) return;
      text = e.clipboardData?.getData('text/plain') ?? '';
      if (text.trim()) {
        e.preventDefault();
        if (mobile) setHomeworkDraft({ kind: 'text', text });
        else void addText(text);
      }
    };
    const onDragOver = (e: DragEvent) => {
      e.preventDefault();
      setDragOver(true);
    };
    const onDragLeave = (e: DragEvent) => {
      if (e.relatedTarget === null) setDragOver(false);
    };
    const onDrop = (e: DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      if (e.dataTransfer?.files && e.dataTransfer.files.length > 0) {
        if (mobile) queueFiles(e.dataTransfer.files);
        else void addFiles(e.dataTransfer.files, 'photo');
      }
    };
    window.addEventListener('paste', onPaste);
    window.addEventListener('dragover', onDragOver);
    window.addEventListener('dragleave', onDragLeave);
    window.addEventListener('drop', onDrop);
    return () => {
      window.removeEventListener('paste', onPaste);
      window.removeEventListener('dragover', onDragOver);
      window.removeEventListener('dragleave', onDragLeave);
      window.removeEventListener('drop', onDrop);
    };
  }, [phase, mobile, addFiles, addText, queueFiles]);

  return {
    phase,
    profile,
    items,
    activeItemId,
    boardSignal,
    homeworkDraft,
    homeworkSending,
    queueFiles,
    setHomeworkDraft,
    sendHomework,
    audioBlocked,
    resumeNeeded,
    resumeMedia,
    prepareStart,
    focused,
    sessionNotes,
    caption,
    captionFading,
    agentState,
    tutorMode,
    hasSpokenFirst,
    micEnabled,
    micBlocked,
    connBanner,
    toast,
    lastSent,
    dragOver,
    sending,
    audioRef,
    start,
    sendChat,
    toggleMic,
    retryMic,
    resourceClosed,
    endSession,
    backToProfiles,
    leaveToProfiles,
    showFirstVisit,
    profilesOpen,
    clearProfilesOpen,
    prefillId,
    endReason,
    addFiles,
    addText,
    onItemMounted: resolveMounted,
    registerPageFrame,
    sendPageAnswer,
    onItemFailed: rejectMounted,
  };
}

/** The sentence being spoken now (plus the previous one if it is short), for a 2-line caption. */
export function captionTail(text: string, max = 140): string {
  const clean = text
    .replace(/[$*#`]/g, '')
    .replace(/\s+/g, ' ')
    .trim();
  if (clean.length <= max) return clean;
  const sentences = clean.match(/[^.!?]+[.!?]*\s*/g) ?? [clean];
  let out = '';
  for (let i = sentences.length - 1; i >= 0; i--) {
    const next = sentences[i] + out;
    if (next.trim().length > max && out) break;
    out = next;
  }
  out = out.trim();
  return out.length > max ? '…' + out.slice(out.length - max + 1) : out;
}
