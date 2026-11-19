import { RpcError } from 'livekit-client';
import type { RpcInvocationData } from 'livekit-client';
import type { Note } from './protocol';
import type { Profile } from './db';

/** Worker → browser learner RPCs (see docs/protocol.md). Pure handlers with
 *  injected browser state, so the acknowledgement contract is unit-testable:
 *
 *  - set_learner_name creates the local profile (or attaches to an existing
 *    one with the same name) and applies only when the target is still the
 *    active profile; anything else is rejected as stale, and the tool on the
 *    worker leaves the call exactly as it was. A correction is the same call.
 *  - set_learner_grade applies only when the target is still the active
 *    profile; anything else is rejected as stale, and the tool on the worker
 *    leaves the call exactly as it was. Grade updates never change which
 *    profile is active.
 *  - switch_student resolves or creates the student's profile (serialized,
 *    one profile per name) and arms the post-lesson prefill: after this
 *    lesson ends exactly like Avsluta, the browser shows the start page for
 *    the new student. The profile is remembered as active only when the new
 *    student's session actually starts.
 */
export type LearnerRpcDeps = {
  applyName: (profileId: string, name: string) => Promise<Profile | undefined>;
  applyGrade: (profileId: string, grade: number) => Promise<Profile | undefined>;
  resolveStudent: (name: string) => Promise<Profile>;
  armPrefill: (profile: Profile) => void;
};

function parsePayload(data: RpcInvocationData, method: string): Record<string, unknown> {
  let parsed: unknown;
  try {
    parsed = JSON.parse(data.payload);
  } catch {
    throw new RpcError(1500, `${method} payload is not JSON`);
  }
  if (typeof parsed !== 'object' || parsed === null) throw new RpcError(1500, `${method} payload is not an object`);
  return parsed as Record<string, unknown>;
}

export async function handleSetName(data: RpcInvocationData, deps: LearnerRpcDeps): Promise<string> {
  const msg = parsePayload(data, 'learner.setName');
  const name = typeof msg.name === 'string' ? msg.name.trim().slice(0, 40) : '';
  const updated = await deps.applyName(
    typeof msg.profileId === 'string' ? msg.profileId : '',
    name,
  );
  if (!updated) throw new RpcError(1501, 'name target is stale or invalid');
  return JSON.stringify({
    ok: true,
    profile: { id: updated.id, name: updated.name, grade: updated.grade },
  });
}

export async function handleSetGrade(data: RpcInvocationData, deps: LearnerRpcDeps): Promise<string> {
  const msg = parsePayload(data, 'learner.setGrade');
  const grade = typeof msg.grade === 'number' ? msg.grade : NaN;
  const updated = await deps.applyGrade(
    typeof msg.profileId === 'string' ? msg.profileId : '',
    grade,
  );
  if (!updated) throw new RpcError(1501, 'grade target is stale or invalid');
  return JSON.stringify({ ok: true, grade: updated.grade });
}

export type NoteDeps = {
  /** The profile id this session's notes belong to: the start profile, or the
   *  named profile once a voice-first call learns the name. Read late (inside
   *  the queue) so a naming that lands first is honoured. */
  getSessionProfileId: () => string;
  /** False once a newer session started: old callbacks touch nothing. */
  isCurrentSession: () => boolean;
  /** The live profile is updated only when it is still the note's target. */
  getActiveId: () => string | null;
  onNote: (note: Note, updated: Profile | undefined) => void;
  saveNote: (profileId: string, note: Note) => Promise<Profile | undefined>;
};

export async function handleNote(text: string, deps: NoteDeps): Promise<void> {
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    return;
  }
  if (typeof parsed !== 'object' || parsed === null) return;
  const data = parsed as Record<string, unknown>;
  const note: Note = {
    at: typeof data.at === 'string' ? data.at : new Date().toISOString(),
    topic: String(data.topic ?? ''),
    ...(typeof data.clicked === 'string' ? { clicked: data.clicked } : {}),
    ...(typeof data.tricky === 'string' ? { tricky: data.tricky } : {}),
    ...(typeof data.next === 'string' ? { next: data.next } : {}),
  };
  if (!note.topic) return;
  const updated = await deps.saveNote(deps.getSessionProfileId(), note);
  // A delayed note from lesson A is stored under A but never touches B's UI.
  if (!deps.isCurrentSession()) return;
  if (updated && deps.getActiveId() !== updated.id) return;
  deps.onNote(note, updated);
}

export async function handleSwitch(data: RpcInvocationData, deps: LearnerRpcDeps): Promise<string> {
  const msg = parsePayload(data, 'learner.switch');
  const name = String(msg.name ?? '').trim().slice(0, 40);
  if (!name) throw new RpcError(1500, 'learner.switch needs a name');
  const next = await deps.resolveStudent(name);
  deps.armPrefill(next);
  return JSON.stringify({
    ok: true,
    profile: { id: next.id, name: next.name, grade: next.grade },
  });
}
