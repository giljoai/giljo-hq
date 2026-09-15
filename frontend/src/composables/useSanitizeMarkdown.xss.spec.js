
import { describe, it, expect } from 'vitest'
import { useSanitizeMarkdown, sanitizeHtml } from './useSanitizeMarkdown'

const { sanitizeMarkdown } = useSanitizeMarkdown()

function parseFragment(html) {
  const doc = new DOMParser().parseFromString(`<!doctype html><body>${html}`, 'text/html')
  return doc.body
}

function assertNoExecutableNodes(html) {
  const body = parseFragment(html)
  expect(body.querySelectorAll('script').length, 'script elements').toBe(0)
  expect(body.querySelectorAll('iframe').length, 'iframe elements').toBe(0)
  expect(body.querySelectorAll('object').length, 'object elements').toBe(0)
  expect(body.querySelectorAll('embed').length, 'embed elements').toBe(0)
  expect(body.querySelectorAll('style').length, 'style elements').toBe(0)
  expect(body.querySelectorAll('form').length, 'form elements').toBe(0)
  expect(body.querySelectorAll('svg').length, 'svg elements').toBe(0)

  const all = body.querySelectorAll('*')
  for (const el of all) {
    for (const attr of el.attributes) {
      expect(
        /^on/i.test(attr.name),
        `inline handler surfaced: <${el.tagName.toLowerCase()} ${attr.name}=...>`,
      ).toBe(false)
    }
  }

  for (const el of all) {
    for (const attr of el.attributes) {
      const v = (attr.value || '').trim().toLowerCase()
      expect(v.startsWith('javascript:'), `javascript: scheme on ${attr.name}`).toBe(false)
      expect(v.startsWith('data:'), `data: scheme on ${attr.name}`).toBe(false)
    }
  }
}

describe('sanitizeHtml — raw HTML XSS payloads', () => {
  it('strips raw <script>alert(1)</script>', () => {
    const out = sanitizeHtml('<script>alert(1)</script>')
    expect(out).not.toMatch(/<script\b/i)
    expect(out).not.toContain('alert(1)')
    assertNoExecutableNodes(out)
  })

  it('strips inline event handler on <img onerror>', () => {
    const out = sanitizeHtml('<img src=x onerror="alert(1)">')
    expect(out).not.toMatch(/\son\w+=/i)
    expect(out).not.toContain('alert(1)')
    assertNoExecutableNodes(out)
  })

  it('blocks javascript: URI on <a href>', () => {
    const out = sanitizeHtml('<a href="javascript:alert(1)">click</a>')
    expect(out).not.toMatch(/href\s*=\s*["']?javascript:/i)
    assertNoExecutableNodes(out)
  })

  it('blocks data: URI on <a href>', () => {
    const out = sanitizeHtml('<a href="data:text/html,<script>alert(1)</script>">click</a>')
    expect(out).not.toMatch(/href\s*=\s*["']?data:/i)
    expect(out).not.toMatch(/<script\b/i)
    assertNoExecutableNodes(out)
  })

  it('strips <iframe> entirely', () => {
    const out = sanitizeHtml('<iframe src="https://evil.example/"></iframe>')
    expect(out).not.toMatch(/<iframe\b/i)
    expect(out).not.toContain('evil.example')
    assertNoExecutableNodes(out)
  })

  it('strips <object>', () => {
    const out = sanitizeHtml('<object data="evil.swf"></object>')
    expect(out).not.toMatch(/<object\b/i)
    expect(out).not.toContain('evil.swf')
    assertNoExecutableNodes(out)
  })

  it('strips <svg> wrappers carrying a <script>', () => {
    const out = sanitizeHtml('<svg><script>alert(1)</script></svg>')
    expect(out).not.toMatch(/<svg\b/i)
    expect(out).not.toMatch(/<script\b/i)
    expect(out).not.toContain('alert(1)')
    assertNoExecutableNodes(out)
  })

  it('strips less-obvious handler <input type=image onerror>', () => {
    const out = sanitizeHtml('<input type="image" src=x onerror="alert(1)">')
    expect(out).not.toMatch(/\son\w+=/i)
    expect(out).not.toContain('alert(1)')
    assertNoExecutableNodes(out)
    expect(parseFragment(out).querySelectorAll('input').length).toBe(0)
  })

  it('strips <style> (no CSS-import exfiltration)', () => {
    const out = sanitizeHtml("<style>@import 'evil.css';</style>")
    expect(out).not.toMatch(/<style\b/i)
    expect(out).not.toContain('@import')
    expect(out).not.toContain('evil.css')
    assertNoExecutableNodes(out)
  })

  it('strips <form> with javascript: action', () => {
    const out = sanitizeHtml('<form action="javascript:alert(1)"><button>x</button></form>')
    expect(out).not.toMatch(/<form\b/i)
    expect(out).not.toMatch(/action\s*=\s*["']?javascript:/i)
    assertNoExecutableNodes(out)
  })

  it('neutralises attribute-break payload "><script>alert(1)</script>', () => {
    const out = sanitizeHtml('"><script>alert(1)</script>')
    expect(out).not.toMatch(/<script\b/i)
    expect(out).not.toContain('alert(1)')
    assertNoExecutableNodes(out)
  })
})

describe('useSanitizeMarkdown — markdown-layer XSS payloads', () => {
  it('strips raw <script> embedded in markdown text', () => {
    const out = sanitizeMarkdown('Hello <script>alert(1)</script> world')
    expect(out).not.toMatch(/<script\b/i)
    expect(out).not.toContain('alert(1)')
    assertNoExecutableNodes(out)
  })

  it('blocks [link](javascript:alert(1)) markdown link', () => {
    const out = sanitizeMarkdown('[xss](javascript:alert(1))')
    expect(out).not.toMatch(/href\s*=\s*["']?javascript:/i)
    assertNoExecutableNodes(out)
  })

  it('blocks ![img](javascript:alert(1)) markdown image', () => {
    const out = sanitizeMarkdown('![xss](javascript:alert(1))')
    expect(out).not.toMatch(/src\s*=\s*["']?javascript:/i)
    assertNoExecutableNodes(out)
  })

  it('strips inline <img onerror> when mixed with markdown', () => {
    const out = sanitizeMarkdown('Paragraph\n\n<img src=x onerror="alert(1)">')
    expect(out).not.toMatch(/\son\w+=/i)
    expect(out).not.toContain('alert(1)')
    assertNoExecutableNodes(out)
  })

  it('strips <iframe> embedded in markdown', () => {
    const out = sanitizeMarkdown('Before\n\n<iframe src="https://evil.example/"></iframe>\n\nAfter')
    expect(out).not.toMatch(/<iframe\b/i)
    expect(out).not.toContain('evil.example')
    assertNoExecutableNodes(out)
  })

  it('neutralises combined script + markdown-link javascript: payload', () => {
    const out = sanitizeMarkdown('<script>alert(1)</script>\n\n[xss](javascript:alert(1))')
    expect(out).not.toMatch(/<script\b/i)
    expect(out).not.toMatch(/href\s*=\s*["']?javascript:/i)
    expect(out).not.toContain('alert(1)')
    assertNoExecutableNodes(out)
  })
})
