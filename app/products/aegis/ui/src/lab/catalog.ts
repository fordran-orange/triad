// The parameter catalog: a strategy's ranged parameters grouped into families (one per indicator, plus one for the
// stop-loss / take-profit levels) per side, with the value count of each range and a search over them. Pure
// functions, nothing React. Paths follow the backend's surface.py convention:
//   <side>_side.indicators.<id>.length | <side>_side.indicators.<id>.params.<name>
//   <side>_side.stop_loss_pct | <side>_side.take_profit_pct

import type { StrategySpec, Surface } from '../contracts';

export interface CatalogEntry {
  path: string;
  side: 'long' | 'short';
  /** The key of the family this entry belongs to. */
  family: string;
  /** `length`, `params.<name>`, `stop_loss_pct` or `take_profit_pct`. */
  field: string;
  start: number;
  stop: number;
  step: number;
  /** How many values the range holds. */
  count: number;
}

export interface Family {
  /** `<side>:<indicator id>`, or `<side>:levels` for the stop-loss / take-profit pair. */
  key: string;
  label: string;
  side: 'long' | 'short';
  entries: CatalogEntry[];
}

const LEVEL_FIELDS = new Set(['stop_loss_pct', 'take_profit_pct']);

/** How many values a range holds, both ends included: the Python `Parameter.values()` count. The 1e-9 absorbs the
 *  representation error of a decimal step (0.1 to 0.7 in steps of 0.1 divides to 5.999999999999999). */
export function parameterCount(p: { start: number; stop: number; step: number }): number {
  return Math.floor((p.stop - p.start) / p.step + 1e-9) + 1;
}

/** Splits a parameter path into its side, indicator id ('levels' for the level fields) and field, or null when the
 *  path does not follow the convention. */
function parsePath(path: string): { side: 'long' | 'short'; id: string; field: string } | null {
  const parts = path.split('.');
  const side = parts[0] === 'long_side' ? 'long' : parts[0] === 'short_side' ? 'short' : null;
  if (side === null) return null;
  if (parts.length === 2 && LEVEL_FIELDS.has(parts[1])) return { side, id: 'levels', field: parts[1] };
  if (parts.length >= 4 && parts[1] === 'indicators' && parts[2] !== '') {
    const field = parts.slice(3).join('.');
    if (field === 'length' || (parts[3] === 'params' && parts.length >= 5)) return { side, id: parts[2], field };
  }
  return null;
}

/** The surface's parameters grouped by side and then indicator id (or 'levels'), in the order the surface first
 *  shows them. A family's label names the indicator's kind and length when `spec` holds it ('long · ema (EMA 9)')
 *  and only its id otherwise. A path that does not follow the convention is skipped: the backend validated the
 *  surface, so it cannot happen in practice, and throwing would only break the page. */
export function families(surface: Surface, spec: StrategySpec | null): Family[] {
  const byKey = new Map<string, Family>();
  for (const p of surface.parameters) {
    const parsed = parsePath(p.path);
    if (parsed === null) continue;
    const key = `${parsed.side}:${parsed.id}`;
    let family = byKey.get(key);
    if (family === undefined) {
      family = { key, label: familyLabel(parsed.side, parsed.id, spec), side: parsed.side, entries: [] };
      byKey.set(key, family);
    }
    family.entries.push({
      path: p.path,
      side: parsed.side,
      family: key,
      field: parsed.field,
      start: p.start,
      stop: p.stop,
      step: p.step,
      count: parameterCount(p),
    });
  }
  return [...byKey.values()];
}

function familyLabel(side: 'long' | 'short', id: string, spec: StrategySpec | null): string {
  const base = `${side} · ${id}`;
  if (id === 'levels') return base;
  const indicator = (side === 'long' ? spec?.long_side : spec?.short_side)?.indicators?.find((i) => i.id === id);
  return indicator === undefined ? base : `${base} (${indicator.kind.toUpperCase()} ${indicator.length})`;
}

/** The families that match `text` case-insensitively: its trimmed form is a substring of the family label or of
 *  any entry's path or field. Empty or whitespace-only text returns `list` itself. */
export function searchFamilies(list: Family[], text: string): Family[] {
  const needle = text.trim().toLowerCase();
  if (needle === '') return list;
  return list.filter(
    (f) =>
      f.label.toLowerCase().includes(needle) ||
      f.entries.some((e) => e.path.toLowerCase().includes(needle) || e.field.toLowerCase().includes(needle)),
  );
}
