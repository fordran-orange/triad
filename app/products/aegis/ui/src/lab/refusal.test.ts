// A worker's refusal is not a failure that may pass. A pair whose axis has over 200 values makes the worker refuse the matrix
// (422, "a matrix axis holds at most 200"); asking again changes nothing, so the pair shows the message and no Retry. A network
// error or a 5xx may pass, and keeps its Retry.
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { ApiError } from '../api/client';
import { askFailure } from './labQuery';
import { LabError } from './NotBuilt';

describe('what a failed ask shows', () => {
  it('keeps the message, and marks a worker\'s refusal as one', () => {
    const refusal = askFailure(new ApiError(422, 'long_side.stop_loss_pct has 201 values; a matrix axis holds at most 200'));
    expect(refusal).toEqual({ message: '422: long_side.stop_loss_pct has 201 values; a matrix axis holds at most 200', refused: true });
  });

  it('marks a network error and a server error as passing: they keep their Retry', () => {
    expect(askFailure(new TypeError('Failed to fetch'))).toEqual({ message: 'Failed to fetch', refused: false });
    expect(askFailure(new ApiError(500, 'internal error'))).toEqual({ message: '500: internal error', refused: false });
    expect(askFailure(new ApiError(503, 'the worker is busy')).refused).toBe(false);
  });
});

describe('the X state', () => {
  it('offers Retry for a failure that may pass', () => {
    const html = renderToStaticMarkup(createElement(LabError, { message: 'Failed to fetch', onRetry: () => undefined }));
    expect(html).toContain('Retry');
    expect(html).toContain('lab-retry');
  });

  it('offers none for a refusal: the message alone', () => {
    const html = renderToStaticMarkup(createElement(LabError, { message: '422: a matrix axis holds at most 200' }));
    expect(html).toContain('422: a matrix axis holds at most 200');
    expect(html).not.toContain('Retry');
    expect(html).not.toContain('<button');
    expect(html).toContain('role="alert"');
  });
});
