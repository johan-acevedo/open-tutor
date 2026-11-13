import { describe, expect, it, vi } from 'vitest';
import { AgentGate } from './agentGate';

describe('AgentGate', () => {
  it('lets nothing through until the agent participant is seen', async () => {
    const gate = new AgentGate();
    let sent = false;
    const send = gate.wait(15000).then(() => {
      sent = true;
    });

    await Promise.resolve();
    expect(sent).toBe(false);
    expect(gate.isReady()).toBe(false);

    gate.markPresent();
    await send;
    expect(sent).toBe(true);
    expect(gate.isReady()).toBe(true);
  });

  it('sends straight away once the agent is there', async () => {
    const gate = new AgentGate();
    gate.markPresent();
    await expect(gate.wait(15000)).resolves.toBeUndefined();
  });

  it('releases a waiting message once, never twice', async () => {
    const gate = new AgentGate();
    const first = vi.fn();
    const second = vi.fn();
    void gate.wait(15000).then(first);
    void gate.wait(15000).then(second);

    gate.markPresent();
    await Promise.resolve();
    await Promise.resolve();

    expect(first).toHaveBeenCalledTimes(1);
    expect(second).toHaveBeenCalledTimes(1);
  });

  it('gives up after the timeout so a message is never stuck in the page', async () => {
    vi.useFakeTimers();
    try {
      const gate = new AgentGate();
      const ready = vi.fn();
      void gate.wait(1000).then(ready);
      await vi.advanceTimersByTimeAsync(999);
      expect(ready).not.toHaveBeenCalled();
      await vi.advanceTimersByTimeAsync(1);
      expect(ready).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it('closes again for the next session', async () => {
    const gate = new AgentGate();
    gate.markPresent();
    gate.reset();
    expect(gate.isReady()).toBe(false);

    const ready = vi.fn();
    void gate.wait(15000).then(ready);
    await Promise.resolve();
    expect(ready).not.toHaveBeenCalled();
    gate.markPresent();
  });
});
