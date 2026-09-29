import { describe, it, expect } from 'vitest'
import { parseErrorResponse } from './errorMessages'

describe('parseErrorResponse', () => {
  it('shows the server message for a BaseGiljoError body (error_code + message)', () => {
    const error = {
      response: {
        status: 400,
        data: {
          error_code: 'VALIDATIONERROR',
          message: 'The handover template is 9000 characters, over the 8000-character limit.',
          context: { field: 'handover_template' },
          timestamp: '2026-09-28T00:00:00Z',
        },
      },
    }
    expect(parseErrorResponse(error).message).toBe(
      'The handover template is 9000 characters, over the 8000-character limit.',
    )
    expect(parseErrorResponse(error).isStructured).toBe(true)
  })

  it('never surfaces the raw `detail` list a stock FastAPI 422 carries', () => {
    const error = {
      response: {
        status: 422,
        data: {
          detail: [{ loc: ['body', 'name'], msg: 'field required', type: 'value_error.missing' }],
        },
      },
    }
    const { message } = parseErrorResponse(error)
    expect(message).not.toContain('value_error.missing')
    expect(typeof message).toBe('string')
    expect(message.length).toBeGreaterThan(0)
  })

  it('shows the friendly generic copy for a real network failure, never axios\'s own text', () => {
    const error = new Error('timeout of 5000ms exceeded')
    error.isAxiosError = true
    expect(parseErrorResponse(error).message).toBe(
      'Failed to connect to server. Please check your connection.',
    )
  })

  it('passes through a plain app-thrown Error\'s message (no response, not axios)', () => {
    const error = new Error('implementer is a display name held by agent-7 — address agent-7 instead.')
    expect(parseErrorResponse(error).message).toBe(
      'implementer is a display name held by agent-7 — address agent-7 instead.',
    )
  })

  it('never shows a TypeError\'s raw message -- only a plain app-thrown Error qualifies', () => {
    const error = new TypeError("Cannot read properties of undefined (reading 'foo')")
    expect(parseErrorResponse(error).message).toBe(
      'Failed to connect to server. Please check your connection.',
    )
  })

  it('falls back to a generic message for an empty response body', () => {
    const error = { response: { status: 500, data: {} } }
    const { message, errorCode } = parseErrorResponse(error)
    expect(errorCode).toBe('UNKNOWN_ERROR')
    expect(typeof message).toBe('string')
    expect(message.length).toBeGreaterThan(0)
  })
})
