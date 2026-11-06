import { describe, expect, it } from 'vitest';
import { ApiError } from '../api/client';
import type { StrategyDocument, StrategySpec } from '../contracts';
import { documentToFetch, saveDocument } from './documents';

describe('document sync decision', () => {
  it('fetches the document named by the strategy id when it is not the loaded one', () => {
    expect(documentToFetch('breakout', null, null)).toBe('breakout');
    expect(documentToFetch('breakout', 'breakout', null)).toBeNull();
    expect(documentToFetch(null, null, null)).toBeNull();
  });

  it('does not refetch an id that just 404ed, but does once the loaded document changed', () => {
    const missing = { strategy: 'breakout', document: null };
    expect(documentToFetch('breakout', null, missing)).toBeNull(); // a 404 must not loop
    expect(documentToFetch('breakout', 'other', missing)).toBe('breakout');
  });

  it('rebinds after a run reload even when that id was fetched before (review finding #1)', () => {
    // run R1 (donchian-rsi) adopted, then "Use in workspace" on my-other, then R1 reloaded:
    expect(documentToFetch('donchian-rsi', 'my-other', null)).toBe('donchian-rsi');
  });
});

describe('saving a document with its precondition (Mission 13 review I3)', () => {
  const spec = { id: 'breakout', name: 'Breakout' } as StrategySpec;
  const document: StrategyDocument = { id: 'breakout', name: 'Breakout', spec, created_at: 't0', updated_at: 't1', strategy_hash: 'h', parent: null, builtin: false };

  it('sends the updated_at the document was loaded at and hands back the saved document', async () => {
    const calls: unknown[] = [];
    const update = async (id: string, patch: unknown) => {
      calls.push([id, patch]);
      return { ...document, name: 'Tab A', updated_at: 't2' };
    };
    const outcome = await saveDocument(document, { name: 'Tab A' }, update);
    expect(calls).toEqual([['breakout', { name: 'Tab A', updated_at: 't1' }]]);
    expect(outcome).toEqual({ kind: 'saved', document: { ...document, name: 'Tab A', updated_at: 't2' } });
  });

  it("turns the worker's 409 into a conflict carrying its message, and any other refusal into a failure", async () => {
    const message = 'strategy breakout was saved elsewhere since you opened it; reload';
    const conflict = await saveDocument(document, { name: 'Tab B' }, async () => {
      throw new ApiError(409, message);
    });
    expect(conflict).toEqual({ kind: 'conflict', message });
    const failed = await saveDocument(document, { name: '' }, async () => {
      throw new ApiError(422, 'name: empty');
    });
    expect(failed).toEqual({ kind: 'failed', message: '422: name: empty' });
  });
});
