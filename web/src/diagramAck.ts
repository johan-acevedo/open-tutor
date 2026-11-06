// Acknowledgements for diagram RPCs. board.show / board.update for a diagram are answered only when
// the card reports that its scene shows that revision (or a later one), or fails with a reason.

export type DiagramAcks = {
  /** Resolves once `id` has been drawn at `rev` or later; rejects on a reported error, a reset or a timeout. */
  wait: (id: string, rev: number) => Promise<void>;
  /** The card's report: revision drawn (no error) or the reason it could not be drawn. */
  rendered: (id: string, rev: number, error?: string) => void;
  /** Reject everything still waiting (session reset or ended). */
  failAll: (reason: string) => void;
};

type Waiter = { rev: number; resolve: () => void; reject: (error: Error) => void; timer: ReturnType<typeof setTimeout> };

export function createDiagramAcks(timeoutMs: number): DiagramAcks {
  const waiters = new Map<string, Waiter[]>();

  const remove = (id: string, waiter: Waiter) => {
    clearTimeout(waiter.timer);
    const rest = (waiters.get(id) ?? []).filter((w) => w !== waiter);
    if (rest.length) waiters.set(id, rest);
    else waiters.delete(id);
  };

  return {
    wait(id, rev) {
      return new Promise<void>((resolve, reject) => {
        const waiter: Waiter = {
          rev,
          resolve,
          reject,
          timer: setTimeout(() => {
            remove(id, waiter);
            reject(new Error('Diagrammet ritades inte i tid.'));
          }, timeoutMs),
        };
        waiters.set(id, [...(waiters.get(id) ?? []), waiter]);
      });
    },
    rendered(id, rev, error) {
      for (const waiter of [...(waiters.get(id) ?? [])]) {
        if (waiter.rev > rev) continue; // a later revision is still being drawn
        remove(id, waiter);
        if (error) waiter.reject(new Error(error));
        else waiter.resolve();
      }
    },
    failAll(reason) {
      for (const [id, list] of [...waiters]) {
        for (const waiter of list) {
          remove(id, waiter);
          waiter.reject(new Error(reason));
        }
      }
    },
  };
}
