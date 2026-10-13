import { describe, expect, it } from 'vitest';
import { ApiError, errorMessage } from './client';

describe('errorMessage', () => {
  it('renders a 422 list detail as the Value error messages joined by "; "', () => {
    const detail = [
      { type: 'value_error', loc: ['body', 'settings'], msg: 'Value error, settings.evaluate_from is set by the job itself; leave it unset' },
      { type: 'value_error', loc: ['body', 'in_sample_bars'], msg: 'Value error, in_sample_bars 3 below 35' },
    ];
    expect(errorMessage(new ApiError(422, detail))).toBe('422: settings.evaluate_from is set by the job itself; leave it unset; in_sample_bars 3 below 35');
  });

  it("falls back to the last entry's msg when no entry is a Value error", () => {
    const detail = [
      { type: 'missing', loc: ['body', 'side'], msg: 'Field required' },
      { type: 'int_parsing', loc: ['body', 'in_sample_bars'], msg: 'Input should be a valid integer' },
    ];
    expect(errorMessage(new ApiError(422, detail))).toBe('422: Input should be a valid integer');
  });

  it('keeps a string detail and a transport error as they are', () => {
    expect(errorMessage(new ApiError(404, "unknown strategy 'x'"))).toBe("404: unknown strategy 'x'");
    expect(errorMessage(new Error('Failed to fetch'))).toBe('Failed to fetch');
  });
});
