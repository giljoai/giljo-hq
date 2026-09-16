import { describe, it, expect } from 'vitest'
import { Marked } from 'marked'
import { installGuideCalloutRenderer } from '@/utils/guideCalloutRenderer'
import { sanitizeHtml } from '@/composables/useSanitizeMarkdown'

/**
 * TSK-9609 -- every heading in the guide carries an anchor id, not just H2.
 *
 * AgentExport.vue deep-links `#installing-skills-giljo_setup`, and the guide's
 * "Installing Skills (`giljo_setup`)" is an H3. The renderer emitted `id=` only
 * for `depth === 2`, so no element with that id existed and the link went
 * nowhere -- a broken deep link that read perfectly well in the source.
 *
 * Museum rule: the change is purely additive, so the H2 case must come out
 * byte-identical to what it produced before.
 */

function render(markdown) {
  const marked = new Marked()
  installGuideCalloutRenderer(marked)
  return marked.parse(markdown)
}

describe('guide heading anchors', () => {
  it('emits the H2 anchor exactly as before', () => {
    expect(render('## Home Page')).toBe('<h2 id="home-page">Home Page</h2>\n')
  })

  it.each([
    ['#', 1, '# Giljo HQ: User Guide', '<h1 id="giljo-hq-user-guide">Giljo HQ: User Guide</h1>\n'],
    ['###', 3, '### Quick Launch Cards', '<h3 id="quick-launch-cards">Quick Launch Cards</h3>\n'],
    ['####', 4, '#### The Welcome Tour', '<h4 id="the-welcome-tour">The Welcome Tour</h4>\n'],
  ])('gives depth %s (h%i) an anchor too', (_hashes, _depth, markdown, expected) => {
    expect(render(markdown)).toBe(expected)
  })

  it('anchors the real H3 that AgentExport deep-links to', () => {
    const html = render('### Installing Skills (`giljo_setup`)')
    expect(html).toContain('id="installing-skills-giljo_setup"')
  })

  it('still escapes heading text rather than trusting it (SEC-0003)', () => {
    const html = render('### <img src=x onerror=alert(1)>')
    expect(html).not.toContain('<img')
    expect(html).toContain('&lt;img')
  })

  it('survives the hardened sanitizer with the id intact at every depth', () => {
    for (const markdown of ['## Two', '### Three', '#### Four']) {
      const clean = sanitizeHtml(render(markdown))
      expect(clean).toMatch(/<h[234] id="(two|three|four)">/)
    }
  })
})
