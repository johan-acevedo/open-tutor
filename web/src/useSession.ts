import { useCallback, useEffect, useRef, useState } from 'react';
import { ConnectionState, Room, RoomEvent, RpcError, Track } from 'livekit-client';
import type { RpcInvocationData } from 'livekit-client';
import type { BoardFocusPayload, BoardItem, HomeworkAttributes, Note, SessionResponse } from './protocol';
import {
  ATTR_AGENT_STATE,
  ATTR_TUTOR_MODE,
  BOARD_RPC_FOCUS,
  BOARD_RPC_SHOW,
  BOARD_RPC_UPDATE,
  TOPIC_CHAT,
  TOPIC_HOMEWORK,
  TOPIC_HOMEWORK_TEXT,
  TOPIC_NOTE,
  TOPIC_SESSION_EVENT,
  TOPIC_TRANSCRIPTION,
} from './protocol';
import { appendNote } from './db';
import type { Profile } from './db';
import { isNoteLike, validateBoardFocus, validateBoardItem } from './validate';
import { dataUrlToBytes, downscaleImage } from './image';
import type { HomeworkDraft } from './components/HomeworkTray';

export type Phase = 'profiles' | 'connecting' | 'live' | 'ending' | 'ended';
export type ConnBanner = 'reconnecting' | 'disconnected' | null;

const MOUNT_TIMEOUT_MS = 4500;
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

export function useSession(mobile = false) {
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
  const [homeworkDraft, setHomeworkDraft] = useState<HomeworkDraft | null>(null);
  const [homeworkSending, setHomeworkSending] = useState(false);
  const [audioBlocked, setAudioBlocked] = useState(false);
  const [resumeNeeded, setResumeNeeded] = useState(false);

  const roomRef = useRef<Room | null>(null);
  const preparedRoomRef = useRef<Room | null>(null);
  const profileRef = useRef<Profile | null>(null);
  const intentionalEndRef = useRef(false);
  const mountResolvers = useRef(new Map<string, Array<() => void>>());
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const micWantedRef = useRef(true);
  const toastTimer = useRef<number>(0);
  const sentTimer = useRef<number>(0);
  const captionTimer = useRef<number>(0);

  const showToast = useCallback((msg: string) => {
    setToast(msg);
    window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(null), 4000);
  }, []);

  const resolveMounted = useCallback((id: string) => {
    const list = mountResolvers.current.get(id);
    if (list) {
      mountResolvers.current.delete(id);
      for (const fn of list) fn();
    }
  }, []);

  const waitForMounted = useCallback((id: string) => {
    return new Promise<void>((resolve, reject) => {
      const list = mountResolvers.current.get(id) ?? [];
      const finish = () => {
        window.clearTimeout(timer);
        resolve();
      };
      list.push(finish);
      mountResolvers.current.set(id, list);
      const timer = window.setTimeout(() => {
        const pending = mountResolvers.current.get(id);
        if (pending) {
          const remaining = pending.filter((fn) => fn !== finish);
          if (remaining.length) mountResolvers.current.set(id, remaining);
          else mountResolvers.current.delete(id);
          reject(new RpcError(1501, 'The browser did not confirm rendering this board item'));
        }
      }, MOUNT_TIMEOUT_MS);
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
    const room = roomRef.current;
    roomRef.current = null;
    preparedRoomRef.current = null;
    const context = audioContextRef.current;
    audioContextRef.current = null;
    if (context) void context.close().catch(() => undefined);
    if (!room) return;
    for (const m of [BOARD_RPC_SHOW, BOARD_RPC_UPDATE, BOARD_RPC_FOCUS]) unregisterRpc(room, m);
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

  const start = useCallback(
    async (p: Profile) => {
      if (!preparedRoomRef.current) prepareStart();
      const room = roomRef.current;
      if (!room) return;
      preparedRoomRef.current = null;
      intentionalEndRef.current = false;
      profileRef.current = p;
      setProfile(p);
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

      const notes = p.notes.slice(-5).reverse(); // newest first
      let session: SessionResponse;
      try {
        const request = () =>
          fetch('/api/session', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'x-tutor-code': familyCode() },
            body: JSON.stringify({ learner: { name: p.name, grade: p.grade, notes } }),
          });
        let res = await request();
        if (res.status === 401) {
          // The owner can protect the instance with a family code; asked once per browser.
          const code = window.prompt('Skriv familjekoden:') ?? '';
          rememberFamilyCode(code.trim());
          res = await request();
        }
        if (res.status === 429) {
          showToast('Det är fullt just nu. Försök igen om en stund.');
          cleanupRoom();
          setPhase('profiles');
          return;
        }
        if (!res.ok) throw new Error(`session ${res.status}`);
        session = (await res.json()) as SessionResponse;
      } catch {
        showToast('Kunde inte starta sessionen. Kontrollera anslutningen och försök igen.');
        setPhase('profiles');
        cleanupRoom();
        return;
      }

      room.on(RoomEvent.TrackSubscribed, (track, _pub, participant) => {
        if (track.kind === Track.Kind.Audio && participant.identity !== room.localParticipant.identity) {
          const el = audioRef.current;
          if (el) {
            track.attach(el);
            void el.play().catch(() => setAudioBlocked(true));
          }
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
      room.on(RoomEvent.ParticipantConnected, () => readParticipantStates(room));
      room.on(RoomEvent.Reconnecting, () => {
        if (!intentionalEndRef.current) setConnBanner('reconnecting');
      });
      room.on(RoomEvent.ConnectionStateChanged, (state: ConnectionState) => {
        if (state === ConnectionState.Connected) setConnBanner(null);
        else if (state === ConnectionState.Reconnecting && !intentionalEndRef.current) {
          setConnBanner('reconnecting');
        }
      });
      room.on(RoomEvent.Disconnected, () => {
        if (intentionalEndRef.current) return;
        setConnBanner('disconnected');
      });

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
        await waitForMounted(v.item.id);
        return '{"ok":true}';
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
        await waitForMounted(v.item.id);
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

      room.registerTextStreamHandler(TOPIC_NOTE, async (reader) => {
        try {
          const text = await reader.readAll();
          const data: unknown = JSON.parse(text);
          if (!isNoteLike(data)) return;
          const note: Note = {
            at: typeof data.at === 'string' ? data.at : new Date().toISOString(),
            topic: String(data.topic ?? ''),
            ...(typeof data.clicked === 'string' ? { clicked: data.clicked } : {}),
            ...(typeof data.tricky === 'string' ? { tricky: data.tricky } : {}),
            ...(typeof data.next === 'string' ? { next: data.next } : {}),
          };
          setSessionNotes((prev) => [...prev, note]);
          const prof = profileRef.current;
          if (prof) {
            const updated = await appendNote(prof.id, note);
            if (updated) {
              profileRef.current = updated;
              setProfile(updated);
            }
          }
        } catch {
          /* ignore */
        }
      });

      try {
        await room.connect(session.url, session.token);
      } catch {
        showToast('Kunde inte ansluta till samtalet. Försök igen.');
        cleanupRoom();
        setPhase('profiles');
        return;
      }
      readParticipantStates(room);
      try {
        await room.startAudio();
      } catch {
        setAudioBlocked(true);
      }
      try {
        await room.localParticipant.setMicrophoneEnabled(true);
        setMicEnabled(true);
        setMicBlocked(false);
      } catch {
        // Mic denied: stay connected, banner + text field instead.
        setMicEnabled(false);
        setMicBlocked(true);
      }
      setPhase('live');
    },
    [cleanupRoom, prepareStart, readParticipantStates, showToast, waitForMounted],
  );

  const sendChat = useCallback(
    async (text: string) => {
      const room = roomRef.current;
      if (!room || phase !== 'live') return;
      setSending(true);
      try {
        await room.localParticipant.sendText(text, { topic: TOPIC_CHAT });
        setLastSent(text);
        window.clearTimeout(sentTimer.current);
        sentTimer.current = window.setTimeout(() => setLastSent(null), 4000);
      } catch {
        showToast('Kunde inte skicka meddelandet. Försök igen.');
      } finally {
        setSending(false);
      }
    },
    [phase, showToast],
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
    } catch {
      setMicEnabled(false);
      setMicBlocked(true);
    }
  }, [micEnabled]);

  const retryMic = useCallback(async () => {
    const room = roomRef.current;
    if (!room) return;
    micWantedRef.current = true;
    try {
      await room.localParticipant.setMicrophoneEnabled(true);
      setMicEnabled(true);
      setMicBlocked(false);
    } catch {
      setMicEnabled(false);
      setMicBlocked(true);
    }
  }, []);

  const resumeMedia = useCallback(async () => {
    const room = roomRef.current;
    if (!room) return;
    // Both calls begin in the tap handler; neither waits for a network operation.
    const playback = room.startAudio();
    const context = audioContextRef.current;
    if (context?.state === 'suspended') void context.resume().catch(() => setAudioBlocked(true));
    try {
      await playback;
      setAudioBlocked(!room.canPlaybackAudio);
    } catch {
      setAudioBlocked(true);
    }
    if (resumeNeeded && micWantedRef.current) {
      try {
        await room.localParticipant.setMicrophoneEnabled(false);
        await room.localParticipant.setMicrophoneEnabled(true);
        setMicEnabled(true);
        setMicBlocked(false);
      } catch {
        setMicEnabled(false);
        setMicBlocked(true);
      }
    }
    setResumeNeeded(false);
  }, [resumeNeeded]);

  useEffect(() => {
    if (phase !== 'live' || !mobile) return;
    let hidden = false;
    const onVisibility = () => {
      if (document.hidden) hidden = true;
      else if (hidden) {
        hidden = false;
        setResumeNeeded(true);
      }
    };
    document.addEventListener('visibilitychange', onVisibility);
    return () => document.removeEventListener('visibilitychange', onVisibility);
  }, [phase, mobile]);

  const resourceClosed = useCallback(
    async (id: string) => {
      const room = roomRef.current;
      if (!room) return;
      try {
        await room.localParticipant.sendText(JSON.stringify({ type: 'resource-closed', id }), {
          topic: TOPIC_SESSION_EVENT,
        });
      } catch {
        showToast('Kunde inte meddela tutorn. Försök igen.');
      }
    },
    [showToast],
  );

  const endSession = useCallback(async () => {
    const room = roomRef.current;
    if (!room || phase !== 'live') return;
    intentionalEndRef.current = true;
    setPhase('ending');
    setConnBanner(null);
    const disconnected = new Promise<void>((resolve) => {
      const onDisc = () => {
        room.off(RoomEvent.Disconnected, onDisc);
        resolve();
      };
      room.on(RoomEvent.Disconnected, onDisc);
      window.setTimeout(resolve, END_WAIT_MS);
    });
    try {
      await room.localParticipant.sendText(JSON.stringify({ type: 'end' }), { topic: TOPIC_SESSION_EVENT });
    } catch {
      /* agent may already be gone; still show the end card */
    }
    await disconnected;
    cleanupRoom();
    setPhase('ended');
  }, [cleanupRoom, phase]);

  const backToProfiles = useCallback(() => {
    intentionalEndRef.current = true;
    cleanupRoom();
    setPhase('profiles');
    setProfile(null);
    setConnBanner(null);
  }, [cleanupRoom]);

  // ---- Homework intake ----

  const addImageFile = useCallback(
    async (file: File, kind: 'photo' | 'screenshot') => {
      const room = roomRef.current;
      const itemId = uid();
      try {
        const down = await downscaleImage(file);
        const title = file.name || 'Bild';
        setItems((prev) => [...prev, { id: itemId, kind: 'homework', title, images: [down.dataUrl] }]);
        setActiveItemId(itemId);
        if (room) {
          await sendHomeworkBytes(room, down.bytes, { kind, source: file.name || 'bild', itemId });
        }
        return true;
      } catch {
        showToast('Bilden kunde inte läsas eller skickas. Prova JPG, PNG eller PDF och kontrollera anslutningen.');
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
          showToast('PDF:en verkar vara tom.');
          return false;
        }
        const images = pages.map((pg) => pg.dataUrl);
        setItems((prev) => [...prev, { id: itemId, kind: 'homework', title: file.name || 'PDF', images }]);
        setActiveItemId(itemId);
        if (room) {
          const total = String(pages.length);
          for (let i = 0; i < pages.length; i++) {
            const bytes = dataUrlToBytes(pages[i].dataUrl);
            await sendHomeworkBytes(room, bytes, {
              kind: 'pdf-page',
              source: file.name || 'pdf',
              page: String(i + 1),
              pages: total,
              itemId,
            });
          }
        }
        return true;
      } catch {
        showToast('Kunde inte läsa PDF:en. Prova en annan fil.');
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
      setItems((prev) => [...prev, { id: itemId, kind: 'homework', title: 'Inklistrad text', text: trimmed }]);
      setActiveItemId(itemId);
      if (room) {
        try {
          await room.localParticipant.sendText(trimmed, {
            topic: TOPIC_HOMEWORK_TEXT,
            attributes: { itemId },
          });
        } catch {
          showToast('Kunde inte skicka texten. Försök igen.');
          return false;
        }
      }
      return true;
    },
    [showToast],
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
          showToast('Den filtypen stöds inte ännu. Prova PDF, PNG eller JPG.');
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
        if (failed.length) showToast('Alla filer kunde inte skickas. Prova JPG, PNG eller PDF.');
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
    addFiles,
    addText,
    onItemMounted: resolveMounted,
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

const CODE_KEY = 'open-tutor-code';

function rememberFamilyCode(code: string): void {
  try {
    localStorage.setItem(CODE_KEY, code);
  } catch {
    /* storage blocked: ask again next time */
  }
}

/** Family code from a shared link (?kod=…), remembered in this browser. */
export function familyCode(): string {
  try {
    const fromUrl = new URLSearchParams(window.location.search).get('kod');
    if (fromUrl) {
      localStorage.setItem(CODE_KEY, fromUrl);
      window.history.replaceState(null, '', window.location.pathname);
      return fromUrl;
    }
    return localStorage.getItem(CODE_KEY) ?? '';
  } catch {
    return '';
  }
}
