import { useState, type FormEvent, type ReactNode } from 'react';
import { api, ApiError, errorMessage } from '../../api/client';
import { applyReading, type Reading } from '../../builder/apply';
import { SIDE_KEY, useDispatch, useWorkspace, type Side } from '../../state/workspace';
import type { Snapshot } from './BuilderPage';

interface Unread {
  start: number;
  end: number;
  text: string;
}

const EXAMPLE = 'buy when 9 ema crosses 30 sma and price is above 200 sma';

/** The text with the words the reader could not read underlined. */
function Underlined({ text, spans }: { text: string; spans: Unread[] }) {
  const parts: ReactNode[] = [];
  let at = 0;
  for (const span of [...spans].sort((a, b) => a.start - b.start)) {
    if (span.start > at) parts.push(text.slice(at, span.start));
    parts.push(<u key={span.start}>{text.slice(span.start, span.end)}</u>);
    at = span.end;
  }
  parts.push(text.slice(at));
  return <span className="phrase-text">{parts}</span>;
}

/** The builder's text line (Mission 13 spec §4.7): Enter reads the sentence, the reading is shown
 * with Apply, and nothing changes until Apply; a refusal names the unread words. */
export function PhraseBar({ push, readOnly }: { push: (side: Side, snapshot: Snapshot) => void; readOnly: boolean }) {
  const { strategy } = useWorkspace();
  const dispatch = useDispatch();
  const [text, setText] = useState('');
  const [reading, setReading] = useState<Reading | null>(null);
  const [refused, setRefused] = useState<{ text: string; message: string; spans: Unread[] } | null>(null);
  const [busy, setBusy] = useState(false);

  const read = async (event: FormEvent) => {
    event.preventDefault();
    if (!strategy || !text.trim()) return;
    setBusy(true);
    setReading(null);
    setRefused(null);
    try {
      setReading(await api.readText(text, strategy));
    } catch (e) {
      const raw = e instanceof ApiError ? (e.raw as { message?: string; unread?: Unread[] } | null) : null;
      setRefused({ text, message: raw?.message ?? errorMessage(e), spans: raw?.unread ?? [] });
    } finally {
      setBusy(false);
    }
  };

  const apply = () => {
    if (!strategy || !reading) return;
    const applied = applyReading(strategy, reading);
    const sides = (['long', 'short'] as Side[]).filter((s) => applied.graphs[s]);
    for (const side of sides) {
      const graph = applied.graphs[side]!;
      const spec = applied.strategy[SIDE_KEY[side]];
      dispatch({ type: 'SET_SIDE_GRAPH', side, graph, spec });
      push(side, { graph, spec });
    }
    if (sides.length) dispatch({ type: 'SET_BUILDER_SIDE', side: sides[0] });
    setReading(null);
    setText('');
  };

  return (
    <div className="phrase-bar">
      <form onSubmit={read} className="phrase-form">
        <input
          id="phrase-input"
          className="control phrase-input"
          value={text}
          placeholder={`Describe a strategy, e.g. "${EXAMPLE}"`}
          aria-label="Describe a strategy"
          disabled={readOnly || busy}
          title={readOnly ? 'The built-in strategy is read-only; duplicate it to edit' : 'Press Enter to read it'}
          onChange={(e) => setText(e.target.value)}
        />
      </form>
      {reading && (
        <div className="phrase-reading" id="phrase-reading" role="status">
          <span>{reading.reading}</span>
          <button type="button" className="btn btn-green" id="phrase-apply" onClick={apply}>
            Apply
          </button>
          <button type="button" className="btn" id="phrase-cancel" onClick={() => setReading(null)}>
            Cancel
          </button>
        </div>
      )}
      {refused && (
        <div className="notice warn phrase-error" id="phrase-error" role="status">
          {refused.message} · <Underlined text={refused.text} spans={refused.spans} />
        </div>
      )}
    </div>
  );
}
