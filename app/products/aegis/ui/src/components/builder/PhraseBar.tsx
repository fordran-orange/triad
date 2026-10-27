import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react';
import { api, ApiError, errorMessage, type ReaderChoice, type ReaderProvider } from '../../api/client';
import { applyReading, type Reading } from '../../builder/apply';
import { providerName, readerSelection, readingLines } from '../../builder/reading';
import { SIDE_KEY, useDispatch, useWorkspace, type Side } from '../../state/workspace';
import type { Snapshot } from './BuilderPage';
import { LearnedPhrases } from './LearnedPhrases';

interface Unread {
  start: number;
  end: number;
  text: string;
}

interface AiRefusal {
  reason: string;
  message: string;
  provider: string;
  rewrite?: string;
}

const EXAMPLE = 'buy when 9 ema crosses 30 sma and price is above 200 sma';
const THINKING_AFTER_MS = 400; // the phrase reader answers well within this; only an AI reading waits longer

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

/** The builder's text line (Mission 13 spec §4.7, Mission 14 spec §4.4): Enter reads the sentence
 * with the phrase reader, or with the chosen provider through Core when the reader cannot; the
 * reading is shown with Apply; nothing changes until Apply. An applied AI reading teaches the
 * reader its substitutions. */
export function PhraseBar({ push, readOnly }: { push: (side: Side, snapshot: Snapshot) => void; readOnly: boolean }) {
  const { strategy } = useWorkspace();
  const dispatch = useDispatch();
  const [text, setText] = useState('');
  const [reading, setReading] = useState<{ text: string; value: Reading } | null>(null);
  const [refused, setRefused] = useState<{ text: string; message: string; spans: Unread[]; ai: AiRefusal | null } | null>(null);
  const [busy, setBusy] = useState(false);
  const [thinking, setThinking] = useState(false);
  const [provider, setProvider] = useState<ReaderProvider>('CLAUDE');
  const [choices, setChoices] = useState<ReaderChoice[] | null>(null);
  const [unavailable, setUnavailable] = useState<string | null>(null);
  const [learned, setLearned] = useState<string | null>(null);
  const [learnedVersion, setLearnedVersion] = useState(0);
  const abort = useRef<AbortController | null>(null);
  const asked = useRef(0);

  // Each provider is offered only while Core can route a reading to it (operator, 2026-10-27);
  // only the newest answer counts when two checks overlap.
  const loadChoices = () => {
    const ask = ++asked.current;
    return api
      .readerProviders()
      .then((r) => {
        if (ask !== asked.current) return;
        setChoices(r.providers);
        setUnavailable(r.message);
      })
      .catch((e: unknown) => {
        if (ask !== asked.current) return;
        setChoices([]);
        setUnavailable(errorMessage(e));
      });
  };

  useEffect(() => {
    api
      .preferences()
      .then((p) => p.reader_provider && setProvider(p.reader_provider))
      .catch(() => undefined);
    void loadChoices();
  }, []);

  const { options, selected, ai } = readerSelection(choices, provider);

  const choose = (next: ReaderProvider) => {
    setProvider(next);
    void api.setReaderProvider(next).catch(() => undefined);
  };

  const read = async (event: FormEvent) => {
    event.preventDefault();
    if (!strategy || !text.trim() || busy) return;
    const controller = new AbortController();
    abort.current = controller;
    setBusy(true);
    setReading(null);
    setRefused(null);
    setLearned(null);
    const timer = window.setTimeout(() => setThinking(true), THINKING_AFTER_MS);
    try {
      setReading({ text, value: await api.readText(text, strategy, selected ?? undefined, controller.signal, ai) });
    } catch (e) {
      if (controller.signal.aborted) return; // cancelled: the text stays, nothing is shown
      const raw = e instanceof ApiError ? (e.raw as { message?: string; unread?: Unread[]; ai?: AiRefusal } | null) : null;
      setRefused({ text, message: raw?.message ?? errorMessage(e), spans: raw?.unread ?? [], ai: raw?.ai ?? null });
    } finally {
      window.clearTimeout(timer);
      setThinking(false);
      setBusy(false);
      abort.current = null;
    }
  };

  const cancel = () => abort.current?.abort();

  const apply = () => {
    if (!strategy || !reading) return;
    const value = reading.value;
    const applied = applyReading(strategy, value);
    const sides = (['long', 'short'] as Side[]).filter((s) => applied.graphs[s]);
    for (const side of sides) {
      const graph = applied.graphs[side]!;
      const spec = applied.strategy[SIDE_KEY[side]];
      dispatch({ type: 'SET_SIDE_GRAPH', side, graph, spec });
      push(side, { graph, spec });
    }
    if (sides.length) dispatch({ type: 'SET_BUILDER_SIDE', side: sides[0] });
    if (value.read_by === 'ai' && value.rewrite) {
      const p = value.provenance ?? {};
      api
        .learn({ text: reading.text, rewrite: value.rewrite, substitutions: value.substitutions ?? [], provider: p.provider ?? null, model: p.model ?? null, run_id: p.run_id ?? null, strategy })
        .then(({ kept }) => {
          if (kept.length) setLearned(`Learned: ${kept.map((k) => `${k.from} → ${k.to}`).join(', ')}`);
          setLearnedVersion((v) => v + 1);
        })
        .catch((e: unknown) => setLearned(`Not learned: ${errorMessage(e)}`));
    }
    setReading(null);
    setText('');
  };

  const lines = reading ? readingLines(reading.value) : null;
  const name = providerName(selected ?? provider);

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
        {selected ? (
          <label className="phrase-provider" title="Who reads a sentence the phrase reader cannot (through Core)">
            AI
            <select
              id="reader-provider"
              className="control"
              value={selected}
              onFocus={() => void loadChoices()}
              onChange={(e) => choose(e.target.value as ReaderProvider)}
            >
              {options.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </label>
        ) : (
          choices && (
            <span className="phrase-provider">
              AI:
              <span className="muted" id="reader-provider-none" title={unavailable ?? 'Core can route a reading to no provider now'}>
                none available
              </span>
              <button type="button" className="btn" id="reader-provider-recheck" onClick={() => void loadChoices()}>
                Recheck
              </button>
            </span>
          )
        )}
        <LearnedPhrases version={learnedVersion} />
      </form>
      {thinking && (
        <div className="phrase-thinking" id="phrase-thinking" role="status">
          <span>Reading with {name}…</span>
          <button type="button" className="btn" id="phrase-cancel-ai" onClick={cancel}>
            Cancel
          </button>
        </div>
      )}
      {reading && lines && (
        <div className="phrase-reading" id="phrase-reading" role="status">
          <div className="phrase-lines">
            {lines.rewrite && (
              <span className="muted" id="phrase-rewrite">
                Read as: {lines.rewrite}
              </span>
            )}
            <span className="phrase-reading-text">{reading.value.reading}</span>
            <span className="muted small" id="phrase-read-by">
              {lines.readBy}
            </span>
            {lines.unsupported && (
              <span className="phrase-unsupported" id="phrase-unsupported">
                Couldn't express: {lines.unsupported}
              </span>
            )}
          </div>
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
          <div>
            {refused.message} · <Underlined text={refused.text} spans={refused.spans} />
          </div>
          {refused.ai && (
            <div className="small" id="phrase-error-ai">
              {refused.ai.message}
              {refused.ai.rewrite ? ` (its rewrite: “${refused.ai.rewrite}”)` : ''}
            </div>
          )}
        </div>
      )}
      {learned && (
        <div className="muted small" id="phrase-learned" role="status">
          {learned}
        </div>
      )}
    </div>
  );
}
