import { afterEach, describe, expect, it, vi } from 'vitest';
import { api, ApiError, errorMessage, isRefusal } from './client';

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

describe('isRefusal', () => {
  it('is a worker that read the request and said no: a 4xx with its message, which asking again cannot change', () => {
    expect(isRefusal(new ApiError(422, 'long_side.stop_loss_pct has 201 values; a matrix axis holds at most 200'))).toBe(true);
    expect(isRefusal(new ApiError(400, 'bad request'))).toBe(true);
    expect(isRefusal(new ApiError(404, 'unknown source'))).toBe(true);
    expect(isRefusal(new ApiError(409, 'conflict'))).toBe(true);
  });

  it('is not a failure that may pass: a server error, a timeout or throttle, or a network error', () => {
    expect(isRefusal(new ApiError(500, 'internal'))).toBe(false);
    expect(isRefusal(new ApiError(503, 'busy'))).toBe(false);
    expect(isRefusal(new ApiError(408, 'timeout'))).toBe(false);
    expect(isRefusal(new ApiError(429, 'slow down'))).toBe(false);
    expect(isRefusal(new TypeError('Failed to fetch'))).toBe(false);
    expect(isRefusal('boom')).toBe(false);
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

describe('labTaskStatus (the read-only status of one task, Ruling P21)', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('GETs the task route of the source, both encoded, and answers the task', async () => {
    const task = { id: 'a1b2c3', label: 'importance', state: 'running', stage: 1, stages: 3, progress: 1 / 3, error: null, started_at: null, finished_at: null, sharing_cpu: false };
    const fetchMock = vi.fn(async () => new Response(JSON.stringify(task), { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
    const answer = await api.labTaskStatus('exp:e 1', 'a1b2/c3');
    expect(answer).toEqual(task);
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit | undefined];
    expect(url).toBe('/aegis/api/lab/exp%3Ae%201/tasks/a1b2%2Fc3');
    expect(init?.method ?? 'GET').toBe('GET'); // a read: it never posts, so it can never ask for work
    expect(init?.body).toBeUndefined();
  });

  it("rejects with the worker's detail for an unknown task or another source's (404)", async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ detail: "unknown task 'zz'" }), { status: 404 })));
    await expect(api.labTaskStatus('exp:e1', 'zz')).rejects.toMatchObject({ status: 404, detail: "unknown task 'zz'" });
  });
});
