// Avatar pose + status pill mapping.
// Input: LiveKit agent state (lk.agent.state), tutor mode (tutor.mode),
// whether a pending ("Ritar…") board item exists, and session flags.
// Waveform/bars only ever in the speaking state.

import type { AgentState, TutorMode } from './protocol';

export type Pose = 'greeting' | 'listening' | 'speaking' | 'thinking' | 'waiting' | 'pointing';

export type PillTone = 'cyan' | 'violet' | 'grey';

export type Pill = {
  label: string;
  icon: 'bars' | 'ear' | 'sparkle' | 'pencil' | 'circle';
  tone: PillTone;
  animateBars: boolean;
};

export type AvatarInput = {
  agentState: AgentState | string | null;
  tutorMode: TutorMode | string | null;
  hasPending: boolean;
  hasSpokenFirst: boolean;
  isTeaching: boolean;
  micBlocked: boolean;
};

export type AvatarOutput = {
  pose: Pose;
  pill: Pill;
};

/**
 * Pure mapping used by the Avatar component and covered by unit tests.
 * Priority: speaking > quiet/resource mode > pending > thinking > listening.
 * (The tutor may say one short sentence when quiet work starts; it is shown as speaking.)
 * Before the first agent speech the greeting pose is used.
 */
export function mapAvatarState(input: AvatarInput): AvatarOutput {
  const { agentState, tutorMode, hasPending, hasSpokenFirst, isTeaching, micBlocked } = input;

  if (agentState === 'speaking') {
    return {
      pose: isTeaching ? 'pointing' : 'speaking',
      pill: { label: 'Pratar', icon: 'bars', tone: 'cyan', animateBars: true },
    };
  }
  if (tutorMode === 'quiet') {
    return {
      pose: 'waiting',
      pill: { label: 'Jag väntar', icon: 'circle', tone: 'grey', animateBars: false },
    };
  }
  if (tutorMode === 'resource') {
    return {
      pose: 'waiting',
      pill: { label: 'Väntar medan du tittar', icon: 'circle', tone: 'grey', animateBars: false },
    };
  }
  if (hasPending) {
    return {
      pose: 'thinking',
      pill: { label: 'Ritar…', icon: 'pencil', tone: 'violet', animateBars: false },
    };
  }
  if (agentState === 'thinking') {
    return {
      pose: 'thinking',
      pill: { label: 'Tänker…', icon: 'sparkle', tone: 'violet', animateBars: false },
    };
  }
  if (micBlocked) {
    return {
      pose: 'waiting',
      pill: { label: 'Väntar på text', icon: 'circle', tone: 'grey', animateBars: false },
    };
  }
  if (agentState === 'listening') {
    if (!hasSpokenFirst) {
      return {
        pose: 'greeting',
        pill: { label: 'Lyssnar', icon: 'ear', tone: 'cyan', animateBars: false },
      };
    }
    return {
      pose: 'listening',
      pill: { label: 'Lyssnar', icon: 'ear', tone: 'cyan', animateBars: false },
    };
  }
  if (!hasSpokenFirst) {
    return {
      pose: 'greeting',
      pill: { label: 'Hej!', icon: 'ear', tone: 'cyan', animateBars: false },
    };
  }
  return {
    pose: 'waiting',
    pill: { label: 'Jag väntar', icon: 'circle', tone: 'grey', animateBars: false },
  };
}

/** Layout mode: arrival until the first board item, then teaching. */
export function layoutMode(itemCount: number): 'arrival' | 'teaching' {
  return itemCount > 0 ? 'teaching' : 'arrival';
}
