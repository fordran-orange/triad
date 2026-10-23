/** Undo and redo for the builder (Mission 13): every canvas edit and an applied sentence push a
 * snapshot; Ctrl+Z / Ctrl+Y move through them. Bounded so a long session stays small. */
export class History<T> {
  private past: T[] = [];
  private future: T[] = [];
  current: T;

  constructor(first: T, private readonly limit = 200) {
    this.current = first;
  }

  push(next: T): void {
    this.past.push(this.current);
    if (this.past.length > this.limit) this.past.shift();
    this.current = next;
    this.future = [];
  }

  undo(): T | null {
    const previous = this.past.pop();
    if (previous === undefined) return null;
    this.future.push(this.current);
    this.current = previous;
    return previous;
  }

  redo(): T | null {
    const next = this.future.pop();
    if (next === undefined) return null;
    this.past.push(this.current);
    this.current = next;
    return next;
  }
}
