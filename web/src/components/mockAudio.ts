// Test helper: minimal Audio stand-in. Records instances, resolves play(),
// emits events on demand. Stub it as the global Audio in tests that touch
// the greeting clip.

export class MockAudio {
  static instances: MockAudio[] = [];
  src: string;
  paused = true;
  currentTime = 0;
  private handlers = new Map<string, (() => void)[]>();

  constructor(src?: string) {
    this.src = src ?? '';
    MockAudio.instances.push(this);
  }

  play(): Promise<void> {
    this.paused = false;
    return Promise.resolve();
  }

  pause(): void {
    this.paused = true;
    this.emit('pause');
  }

  addEventListener(type: string, fn: () => void): void {
    const list = this.handlers.get(type) ?? [];
    list.push(fn);
    this.handlers.set(type, list);
  }

  removeEventListener(): void {
    /* not needed */
  }

  emit(type: string): void {
    for (const fn of this.handlers.get(type) ?? []) fn();
  }
}
