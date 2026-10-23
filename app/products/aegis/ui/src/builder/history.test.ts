import { describe, expect, it } from 'vitest';
import { History } from './history';

describe('History', () => {
  it('undoes and redoes in order', () => {
    const history = new History('a');
    history.push('b');
    history.push('c');
    expect(history.undo()).toBe('b');
    expect(history.undo()).toBe('a');
    expect(history.redo()).toBe('b');
    expect(history.current).toBe('b');
  });

  it('clears redo after a new push, and returns null at either end', () => {
    const history = new History(1);
    expect(history.undo()).toBeNull();
    history.push(2);
    history.undo();
    history.push(3);
    expect(history.redo()).toBeNull();
    expect(history.current).toBe(3);
  });
});
