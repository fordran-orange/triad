import { useCallback, useEffect, useState } from 'react';
import { api, errorMessage, type LearnedPhrase } from '../../api/client';
import { timeLabel } from '../../format';
import { providerName } from '../../builder/reading';

/** The phrases the reader learned from applied AI readings (Mission 14 spec §4.3–4.4): each with
 * the sentence it came from, when, from whom, and Remove. `version` refetches after a learn. */
export function LearnedPhrases({ version }: { version: number }) {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<LearnedPhrase[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    api
      .learned()
      .then((rows) => {
        setItems(rows);
        setError(null);
      })
      .catch((e: unknown) => setError(errorMessage(e)));
  }, []);
  useEffect(() => {
    if (open) refresh();
  }, [open, refresh, version]);

  const remove = async (id: string) => {
    try {
      await api.removeLearned(id);
      refresh();
    } catch (e) {
      setError(errorMessage(e));
    }
  };

  return (
    <div className="learned">
      <button type="button" className="btn" id="learned-open" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        Learned phrases{items ? ` (${items.length})` : ''}
      </button>
      {open && (
        <div className="learned-list" id="learned-list">
          {error && <div className="notice warn">{error}</div>}
          {items === null ? (
            <div className="muted small">Loading…</div>
          ) : items.length === 0 ? (
            <div className="muted small">Nothing learned yet. Applying a reading the AI made teaches the phrase reader its new words.</div>
          ) : (
            items.map((item) => (
              <div className="learned-row" id={`learned-${item.id}`} key={item.id}>
                <span className="learned-pair">
                  {item.from} → {item.to}
                </span>
                <span className="muted small">
                  from “{item.example}” · {timeLabel(item.learned_at)} · {providerName(item.provider)}
                </span>
                <button type="button" className="btn small" id={`learned-remove-${item.id}`} onClick={() => void remove(item.id)}>
                  Remove
                </button>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}
