import { afterEach, describe, expect, it, vi } from 'vitest';
import { api, ApiError, errorMessage } from './client';

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

describe('labCancelTask', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('POSTs to the task route of the source, both encoded, and answers {cancelled}', async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ cancelled: true }), { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
    const answer = await api.labCancelTask('exp:e 1', 'a1b2/c3');
    expect(answer).toEqual({ cancelled: true });
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe('/aegis/api/lab/exp%3Ae%201/tasks/a1b2%2Fc3/cancel');
    expect(init.method).toBe('POST');
  });

  it("rejects with the worker's detail for a task the source does not own (404)", async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ detail: "unknown task 'zz'" }), { status: 404 })));
    await expect(api.labCancelTask('exp:e1', 'zz')).rejects.toMatchObject({ status: 404, detail: "unknown task 'zz'" });
  });
});
