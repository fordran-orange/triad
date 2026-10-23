import { Handle, Position, type Node, type NodeProps } from '@xyflow/react';
import { INDICATOR_KINDS, type IndicatorSpec } from '../../contracts';
import type { Block, BlockSettings, BlockType } from '../../builder/graph';
import { BAND_OPERATORS, OPERATORS } from '../../rules';

/** What the canvas hands each block: the block, its ports, which inputs are wired, and how to
 * change its settings. */
export interface BlockData extends Record<string, unknown> {
  block: Block;
  inputs: string[];
  outputs: string[];
  wired: string[];
  loose: boolean;
  readOnly: boolean;
  onSettings: (id: string, patch: BlockSettings) => void;
}

export type BlockNode = Node<BlockData>;

const OPERATOR_LABELS: Record<string, string> = {
  crosses_above: 'crosses above',
  crosses_below: 'crosses below',
  greater_than: 'greater than',
  less_than: 'less than',
  inside_band: 'inside band',
  outside_band: 'outside band',
};
const TITLES: Record<BlockType, string> = {
  price: 'Price',
  indicator: '',
  condition: 'Condition',
  and: 'AND',
  or: 'OR',
  stop_loss: 'Stop loss',
  take_profit: 'Take profit',
  entry: 'Entry',
  exit: 'Exit',
};
const PORT_LABELS: Record<string, string> = { rule: 'rule', stop: 'stop loss', target: 'take profit', left: 'left', right: 'right', value: 'value', band: 'band', out: '' };

function number(value: string): number | null {
  const parsed = Number(value);
  return value.trim() === '' || !Number.isFinite(parsed) ? null : parsed;
}

function IndicatorFields({ block, readOnly, onSettings }: { block: Block; readOnly: boolean; onSettings: BlockData['onSettings'] }) {
  const spec = block.settings.indicator as IndicatorSpec;
  const info = INDICATOR_KINDS[spec.kind.toUpperCase()];
  const set = (patch: Partial<IndicatorSpec>) => onSettings(block.id, { indicator: { ...spec, ...patch } });
  return (
    <>
      <label className="block-field">
        length
        <input
          className="nodrag"
          id={`${block.id}-length`}
          type="number"
          min={1}
          step={1}
          value={spec.length}
          disabled={readOnly}
          onChange={(e) => {
            const value = number(e.target.value);
            if (value !== null && value >= 1) set({ length: Math.round(value) });
          }}
        />
      </label>
      {Object.entries(info?.params ?? {}).map(([name, fallback]) => (
        <label className="block-field" key={name}>
          {name}
          <input
            className="nodrag"
            id={`${block.id}-${name}`}
            type="number"
            step={info.integer_params.includes(name) ? 1 : 0.1}
            value={spec.params?.[name] ?? fallback}
            disabled={readOnly}
            onChange={(e) => {
              const value = number(e.target.value);
              if (value !== null && value > 0) set({ params: { ...(spec.params ?? {}), [name]: value } });
            }}
          />
        </label>
      ))}
    </>
  );
}

/** One block on the canvas: a title, input ports on the left, output ports on the right, and its
 * settings in between. */
export function BlockView({ data, selected }: NodeProps<BlockNode>) {
  const { block, inputs, outputs, wired, loose, readOnly, onSettings } = data;
  const settings = block.settings;
  const title = block.type === 'indicator' ? `${settings.indicator?.kind ?? ''} · ${block.id}` : TITLES[block.type];
  const band = BAND_OPERATORS.includes(settings.operator ?? '');
  return (
    <div className={`block ${block.type}${loose ? ' loose' : ''}${selected ? ' selected' : ''}`} title={loose ? 'Not wired to Entry or Exit: backtests ignore it' : undefined}>
      <div className="block-head">
        {title}
        {settings.badge === 'default' && (
          <span className="badge raw block-badge" title="Added as the default exit; edit it to keep it as your own">
            default
          </span>
        )}
      </div>
      {inputs.map((port) => (
        <div className="block-row in" key={`in-${port}`}>
          <Handle type="target" position={Position.Left} id={port} isConnectable={!readOnly} />
          <span className="port-label">{PORT_LABELS[port] ?? port}</span>
          {block.type === 'condition' && !wired.includes(port) && !(port === 'right' && band) && (
            <input
              className="nodrag constant"
              id={`${block.id}-${port}`}
              type="text"
              inputMode="decimal"
              placeholder="number"
              value={(port === 'left' ? settings.left : settings.right) ?? ''}
              disabled={readOnly}
              onChange={(e) => {
                const value = e.target.value.trim() || undefined;
                onSettings(block.id, port === 'left' ? { left: value } : { right: value });
              }}
            />
          )}
        </div>
      ))}
      {block.type === 'indicator' && <IndicatorFields block={block} readOnly={readOnly} onSettings={onSettings} />}
      {block.type === 'condition' && (
        <label className="block-field">
          <select className="nodrag" id={`${block.id}-operator`} value={settings.operator ?? 'crosses_above'} disabled={readOnly} onChange={(e) => onSettings(block.id, { operator: e.target.value })}>
            {OPERATORS.map((operator) => (
              <option key={operator} value={operator}>
                {OPERATOR_LABELS[operator]}
              </option>
            ))}
          </select>
        </label>
      )}
      {(block.type === 'stop_loss' || block.type === 'take_profit') && (
        <label className="block-field">
          %
          <input
            className="nodrag"
            id={`${block.id}-pct`}
            type="number"
            min={0}
            step={0.1}
            value={settings.pct ?? ''}
            disabled={readOnly}
            onChange={(e) => onSettings(block.id, { pct: number(e.target.value) })}
          />
        </label>
      )}
      {outputs.map((port) => (
        <div className="block-row out" key={`out-${port}`}>
          <span className="port-label">{PORT_LABELS[port] ?? port}</span>
          <Handle type="source" position={Position.Right} id={port} isConnectable={!readOnly} />
        </div>
      ))}
    </div>
  );
}

export const NODE_TYPES = {
  price: BlockView,
  indicator: BlockView,
  condition: BlockView,
  and: BlockView,
  or: BlockView,
  stop_loss: BlockView,
  take_profit: BlockView,
  entry: BlockView,
  exit: BlockView,
};
