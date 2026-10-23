import type { DragEvent } from 'react';
import { INDICATOR_KINDS } from '../../contracts';
import type { Block, BlockType, SideGraph } from '../../builder/graph';
import { newIndicator } from '../../state/workspace';

/** What a palette item drops: a block type and, for an indicator, its kind. */
export interface PaletteItem {
  type: BlockType;
  kind?: string;
}

export const DRAG_TYPE = 'application/aegis-block';

const ITEMS: { item: PaletteItem; label: string; id: string }[] = [
  { item: { type: 'price' }, label: 'Price', id: 'palette-price' },
  ...Object.keys(INDICATOR_KINDS).map((kind) => ({ item: { type: 'indicator' as const, kind }, label: kind === 'BB' ? 'Bollinger' : kind, id: `palette-indicator-${kind}` })),
  { item: { type: 'condition' }, label: 'Condition', id: 'palette-condition' },
  { item: { type: 'and' }, label: 'AND', id: 'palette-and' },
  { item: { type: 'or' }, label: 'OR', id: 'palette-or' },
  { item: { type: 'stop_loss' }, label: 'Stop loss', id: 'palette-stop_loss' },
  { item: { type: 'take_profit' }, label: 'Take profit', id: 'palette-take_profit' },
];

function nextNumber(graph: SideGraph, type: string): number {
  const used = graph.blocks.map((b) => b.id).filter((id) => id.startsWith(`${type}-`)).map((id) => Number(id.slice(type.length + 1)));
  return 1 + Math.max(0, ...used.filter(Number.isFinite));
}

/** A new block for a dropped palette item at (x, y): an indicator takes the id and default length
 * an indicator added by hand takes; a stop and a target start at the 2% / 5% defaults. */
export function newBlock(graph: SideGraph, item: PaletteItem, x: number, y: number): Block {
  const at = { x: Math.round(x), y: Math.round(y) };
  switch (item.type) {
    case 'indicator': {
      const spec = newIndicator(item.kind ?? 'EMA', graph.blocks.map((b) => b.id));
      return { id: spec.id, type: 'indicator', ...at, settings: { indicator: spec } };
    }
    case 'price':
      return { id: graph.blocks.some((b) => b.id === 'price') ? `price-${nextNumber(graph, 'price')}` : 'price', type: 'price', ...at, settings: {} };
    case 'condition':
      return { id: `condition-${nextNumber(graph, 'condition')}`, type: 'condition', ...at, settings: { operator: 'crosses_above' } };
    case 'stop_loss':
      return { id: `stop_loss-${nextNumber(graph, 'stop_loss')}`, type: 'stop_loss', ...at, settings: { pct: 2 } };
    case 'take_profit':
      return { id: `take_profit-${nextNumber(graph, 'take_profit')}`, type: 'take_profit', ...at, settings: { pct: 5 } };
    default:
      return { id: `${item.type}-${nextNumber(graph, item.type)}`, type: item.type, ...at, settings: {} };
  }
}

/** The blocks to drag onto the canvas (spec §4.6). */
export function Palette({ readOnly }: { readOnly: boolean }) {
  const start = (event: DragEvent, item: PaletteItem) => {
    event.dataTransfer.setData(DRAG_TYPE, JSON.stringify(item));
    event.dataTransfer.effectAllowed = 'move';
  };
  return (
    <div className="palette" id="palette" aria-label="Blocks">
      <div className="section-label">Blocks</div>
      {ITEMS.map(({ item, label, id }) => (
        <div key={id} id={id} className={'palette-item ' + item.type} draggable={!readOnly} onDragStart={(e) => start(e, item)} title={readOnly ? 'The built-in strategy is read-only; duplicate it to edit' : `Drag ${label} onto the canvas`}>
          {label}
        </div>
      ))}
    </div>
  );
}
