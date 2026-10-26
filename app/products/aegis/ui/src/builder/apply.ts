/** Applying the phrase reader's answer and filling in ranges (Mission 13 spec §4.7, §9.3). */
import type { OptimizationParameter, StrategySide, StrategySpec } from '../contracts';
import { defaultRanges, SIDE_KEY, type Side } from '../state/workspace';
import { graphFromSide, type SideGraph } from './graph';

/** What `POST /strategies/read` answers: whole replacement sides, a reading back, default paths. */
export interface Reading {
  sides: Partial<Record<'long_side' | 'short_side', StrategySide>>;
  reading: string;
  defaults: string[];
  // Mission 14: who read it; an AI reading's rewrite, substitutions, what it could not express and Core's provenance
  read_by?: 'phrases' | 'ai';
  rewrite?: string | null;
  substitutions?: { from: string; to: string }[];
  unsupported?: string;
  provenance?: { provider?: string; model?: string; input_tokens?: number; output_tokens?: number; run_id?: string; [key: string]: unknown } | null;
}

const LEVELS = ['stop_loss_pct', 'take_profit_pct'] as const;

/** A disabled range around a stop or target, as a new indicator gets one around its length. */
export function levelRange(path: (typeof LEVELS)[number], pct: number): OptimizationParameter {
  const stop = path === 'stop_loss_pct' ? Math.min(99, pct * 2) : pct * 2;
  return { path, enabled: false, start: Math.max(0.5, Math.round(pct * 5) / 10), stop, step: 0.5 };
}

/** The side with default (disabled) ranges for each indicator and level `isNew` accepts, as an
 * indicator added by hand gets them; ranges already there are kept. */
export function addDefaultRanges(side: StrategySide, isNew: (key: string) => boolean): StrategySide {
  const ranges = [...(side.optimization ?? [])];
  const add = (range: OptimizationParameter) => {
    if (!ranges.some((r) => r.path === range.path)) ranges.push(range);
  };
  for (const spec of side.indicators ?? []) if (isNew(spec.id)) defaultRanges(spec).forEach(add);
  for (const path of LEVELS) {
    const pct = side[path];
    if (pct != null && isNew(path)) add(levelRange(path, pct));
  }
  return { ...side, optimization: ranges };
}

/** A side read back from the canvas: indicators and levels it did not have before get defaults. */
export function withDefaultRanges(next: StrategySide, before: StrategySide): StrategySide {
  const had = new Set([...(before.indicators ?? []).map((i) => i.id), ...LEVELS.filter((p) => before[p] != null)]);
  return addDefaultRanges(next, (key) => !had.has(key));
}

/** The strategy with the reading's sides in place, each new indicator and level given its default
 * ranges (a reused one keeps its own), and each side's graph laid out with the default levels
 * badged. */
export function applyReading(strategy: StrategySpec, reading: Reading): { strategy: StrategySpec; graphs: Partial<Record<Side, SideGraph>> } {
  let next = strategy;
  const graphs: Partial<Record<Side, SideGraph>> = {};
  for (const which of ['long', 'short'] as Side[]) {
    const key = SIDE_KEY[which];
    const side = reading.sides[key];
    if (!side) continue;
    const ranged = new Set((side.optimization ?? []).map((r) => (r.path.startsWith('indicators.') ? r.path.split('.')[1] : r.path)));
    const filled = addDefaultRanges(side, (k) => !ranged.has(k));
    next = { ...next, [key]: filled };
    const graph = graphFromSide(filled);
    graph.blocks = graph.blocks.map((b) =>
      (b.type === 'stop_loss' && reading.defaults.includes(`${key}.stop_loss_pct`)) || (b.type === 'take_profit' && reading.defaults.includes(`${key}.take_profit_pct`))
        ? { ...b, settings: { ...b.settings, badge: 'default' } }
        : b,
    );
    graphs[which] = graph;
  }
  return { strategy: next, graphs };
}
