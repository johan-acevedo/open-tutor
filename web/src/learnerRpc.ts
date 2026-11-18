import { RpcError } from 'livekit-client';
import type { RpcInvocationData } from 'livekit-client';
import type { Profile } from './db';

/** Worker → browser learner RPCs (see docs/protocol.md). Pure handlers with
 *  injected browser state, so the acknowledgement contract is unit-testable:
 *
 *  - set_learner_grade applies only when the target is still the active
 *    profile; anything else is rejected as stale, and the tool on the worker
 *    leaves the call exactly as it was.
 *  - switch_student resolves or creates the student's profile (serialized,
 *    one profile per name) and arms the end-and-restart; the worker then ends
 *    this lesson exactly like Avsluta and the browser reconnects fresh.
 *  - cancel_switch disarms a switch whose ack never reached the worker.
 */
export type LearnerRpcDeps = {
  applyGrade: (profileId: string, grade: number) => Promise<Profile | undefined>;
  resolveStudent: (name: string) => Promise<Profile>;
  rememberLast: (id: string) => void;
  armSwitch: (profile: Profile | null) => void;
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

export async function handleSwitch(data: RpcInvocationData, deps: LearnerRpcDeps): Promise<string> {
  const msg = parsePayload(data, 'learner.switch');
  const name = String(msg.name ?? '').trim().slice(0, 40);
  if (!name) throw new RpcError(1500, 'learner.switch needs a name');
  const next = await deps.resolveStudent(name);
  deps.rememberLast(next.id);
  deps.armSwitch(next);
  return JSON.stringify({
    ok: true,
    profile: { id: next.id, name: next.name, grade: next.grade },
  });
}

export async function handleCancelSwitch(deps: LearnerRpcDeps): Promise<string> {
  deps.armSwitch(null);
  return '{"ok":true}';
}
