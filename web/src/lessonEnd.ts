// One end transition per lesson. Double "Byt elev", Avsluta pressed during
// the goodbye, or a menu leave landing on top of an in-call switch all share
// it: exactly one `end` goes out, the worker saves the note once, and cleanup
// touches only its own room.

export type EndRoute =
  | { kind: 'prefill'; id: string }
  | { kind: 'open' }
  | { kind: 'end' };

/** Where the page goes after the room closes. A switch prefill always wins
 *  over a menu leave: the tutor already ended A's lesson for B. */
export function routeAfterEnd(opts: { prefillId: string | null; goProfiles: boolean }): EndRoute {
  if (opts.prefillId) return { kind: 'prefill', id: opts.prefillId };
  if (opts.goProfiles) return { kind: 'open' };
  return { kind: 'end' };
}

export type DisconnectOutcome =
  | { kind: 'prefill'; id: string }
  | { kind: 'open' }
  | { kind: 'end'; reason: string | null }
  | { kind: 'banner' }
  | { kind: 'ignore' };

/** Where the page goes when the room disconnects without a local end.
 *  An in-call switch still wins; an intentional local end is already handled
 *  by its own path. An idle-timeout notice from the worker (TOPIC_TUTOR_EVENT)
 *  lands on the normal end card with the reason — never the error banner.
 *  Anything else unexpected keeps today's reconnect banner. */
export function routeAfterDisconnect(opts: {
  prefillId: string | null;
  goProfiles: boolean;
  intentional: boolean;
  endReason: string | null;
}): DisconnectOutcome {
  if (opts.prefillId) return { kind: 'prefill', id: opts.prefillId };
  if (opts.intentional) return { kind: 'ignore' };
  if (opts.endReason === 'idle_timeout') {
    if (opts.goProfiles) return { kind: 'open' };
    return { kind: 'end', reason: 'idle_timeout' };
  }
  return { kind: 'banner' };
}

/** Claim the end transition. The first caller owns it; every later caller
 *  while it is in flight stands down. */
export function createEndGate() {
  let inFlight = false;
  return {
    claim: (): boolean => {
      if (inFlight) return false;
      inFlight = true;
      return true;
    },
    release: (): void => {
      inFlight = false;
    },
  };
}
