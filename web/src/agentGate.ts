/**
 * Wait for the tutor's participant before sending anything to it.
 *
 * LiveKit drops a data message that is published while the agent participant is not
 * in the room: the server has nobody to deliver it to, the browser's `sendText` still
 * resolves, and the worker never sees the message. On 2026-11-13 a child typing just
 * as the app went live lost the message this way: no answer, no trace in the session
 * log. Everything the page sends to the tutor waits for the agent participant first
 * (briefly — the worker queues whatever arrives before its session can answer).
 */
export class AgentGate {
  private present = false;
  private waiters = new Set<() => void>();

  /** True once the agent participant has been seen in this session's room. */
  isReady(): boolean {
    return this.present;
  }

  /** The agent participant is in the room: release everything waiting for it. */
  markPresent(): void {
    this.present = true;
    for (const wake of [...this.waiters]) wake();
    this.waiters.clear();
  }

  /** A new session starts with the gate closed. */
  reset(): void {
    this.present = false;
  }

  /** Resolve when the agent is present, or after `timeoutMs`, whichever comes first. */
  wait(timeoutMs: number): Promise<void> {
    if (this.present) return Promise.resolve();
    return new Promise<void>((resolve) => {
      const done = () => {
        clearTimeout(timer);
        this.waiters.delete(done);
        resolve();
      };
      const timer = setTimeout(done, timeoutMs);
      this.waiters.add(done);
    });
  }
}
