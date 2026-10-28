// The Lab's keyboard model (plan §5.2): arrows move the heatmap cursor, Enter selects the square under it, 1 / 2 / 3
// pin the selected trial into A / B / C, Esc clears the brush and then the maximize. Typing in a field never
// triggers any of it, and the trials table keeps its own arrow keys.
import type { KeyboardEvent } from 'react';
import { selectSquareAction, type CursorDims } from './labHeatmapModel';
import { useLab, useLabDispatch } from './labState';
import type { PinSlot } from './labStore';

const PIN_KEYS: Record<string, PinSlot> = { '1': 'A', '2': 'B', '3': 'C' };
const ARROWS: Record<string, [number, number]> = { ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1] };

/** An input, a select, a textarea or editable content: its keys are text, not commands. */
export function isEditable(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.tagName === 'INPUT' || target.tagName === 'SELECT' || target.tagName === 'TEXTAREA') return true;
  return target.isContentEditable || target.closest('[contenteditable]:not([contenteditable="false"])') !== null;
}

/** The key handler for `#optlab-page`. `matrix` is `cursorDims` of the matrix the Heatmap tab shows (its row and
 *  column values and its axes), else null: only then do the arrows and Enter act, and the reducer places the cursor
 *  itself. Enter selects through `selectSquareAction`, the action a click on a square dispatches. */
export function useLabKeys(matrix: CursorDims | null) {
  const lab = useLab();
  const dispatch = useLabDispatch();
  return (e: KeyboardEvent<HTMLElement>) => {
    if (e.defaultPrevented || e.altKey || e.ctrlKey || e.metaKey) return;
    if (isEditable(e.target)) return;
    const target = e.target instanceof HTMLElement ? e.target : null;
    const shown = matrix !== null && matrix.rows.length > 0 && matrix.cols.length > 0 ? matrix : null;
    const arrow = ARROWS[e.key];
    if (arrow) {
      if (shown === null || target?.closest('.trial-table')) return; // the table's rows own their arrows
      e.preventDefault();
      dispatch({ type: 'MOVE_CURSOR', dr: arrow[0], dc: arrow[1], rows: shown.rows.length, cols: shown.cols.length });
      return;
    }
    if (e.key === 'Enter') {
      if (shown === null || lab.cursor === null) return;
      // Other buttons and the rows keep their own Enter; on a heatmap square, and on the heatmap's own mode toggles
      // (pressed with a click or Space), it selects the cursor's square instead.
      if (target?.closest('button, a, [role=button], tr[data-trial]') && !target.closest('.heat-grid, .heat-toolbar')) return;
      e.preventDefault();
      dispatch(selectSquareAction(shown, lab.cursor.r, lab.cursor.c));
      return;
    }
    const slot = PIN_KEYS[e.key];
    if (slot) {
      const selected = lab.selected;
      if (selected !== null && 'trials' in selected && selected.trials.length === 1) {
        e.preventDefault();
        dispatch({ type: 'PIN', slot, trialId: selected.trials[0] });
      }
      return;
    }
    if (e.key === 'Escape') dispatch({ type: 'ESCAPE' });
  };
}
