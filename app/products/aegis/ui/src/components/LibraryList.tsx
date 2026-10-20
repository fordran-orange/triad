import { DASH, timeLabel } from '../format';
import { headlineText, kindLabel } from '../library';
import type { LibraryEntry } from '../results';

export const entryKey = (e: Pick<LibraryEntry, 'kind' | 'id'>) => `${e.kind}:${e.id}`;
const domId = (prefix: string, e: Pick<LibraryEntry, 'kind' | 'id'>) => `${prefix}-${e.kind}-${e.id}`;

function range(e: LibraryEntry): string {
  if (!e.start && !e.end) return DASH;
  return `${e.start ?? DASH} → ${e.end ?? DASH}`;
}

interface Props {
  entries: LibraryEntry[];
  selected: string | null;
  checked: Record<string, LibraryEntry>;
  onSelect: (entry: LibraryEntry) => void;
  onCheck: (entry: LibraryEntry, checked: boolean) => void;
  onStar: (entry: LibraryEntry) => void;
}

/** One row per saved result: kind, name or label, data, headline numbers and status (spec §8). */
export function LibraryList({ entries, selected, checked, onSelect, onCheck, onStar }: Props) {
  return (
    <div className="library-list" id="library-list" role="list">
      {entries.map((e) => {
        const key = entryKey(e);
        const preparing = Object.keys(e.headline ?? {}).length === 0;
        const unfinished = e.status && e.status !== 'done' && e.status !== 'ok';
        return (
          <div
            key={key}
            id={domId('lib', e)}
            role="listitem"
            className={'library-row' + (selected === key ? ' selected' : '')}
            aria-selected={selected === key}
            onClick={() => onSelect(e)}
          >
            <input
              type="checkbox"
              id={domId('lib-check', e)}
              aria-label={`Tick ${kindLabel(e.kind)} ${e.label || e.name}`}
              checked={key in checked}
              onClick={(ev) => ev.stopPropagation()}
              onChange={(ev) => onCheck(e, ev.target.checked)}
            />
            <button
              type="button"
              id={domId('lib-star', e)}
              className={'library-star' + (e.starred ? ' on' : '')}
              aria-pressed={e.starred}
              aria-label={e.starred ? 'Unstar' : 'Star'}
              title={e.starred ? 'Starred: click to unstar' : 'Star this result'}
              onClick={(ev) => {
                ev.stopPropagation();
                onStar(e);
              }}
            >
              {e.starred ? '★' : '☆'}
            </button>
            <div className="library-row-body">
              <div className="library-row-title">
                <span className={`badge kind-${e.kind}`}>{kindLabel(e.kind)}</span>
                <b>{e.label || e.name}</b>
                {e.label && <span className="muted small">{e.name}</span>}
                {unfinished && <span className="badge">{String(e.status).toUpperCase()}</span>}
                {e.decision?.verdict && <span className="badge">{e.decision.verdict}</span>}
              </div>
              <div className="small muted">
                {e.symbols.length ? e.symbols.join(', ') : DASH} · {e.timeframe ?? DASH} · {range(e)} · {e.deleted_at ? `deleted ${timeLabel(e.deleted_at)}` : timeLabel(e.created_at)}
              </div>
              <div className={'small' + (preparing ? ' muted' : '')}>{headlineText(e)}</div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
