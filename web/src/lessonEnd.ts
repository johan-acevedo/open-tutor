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
