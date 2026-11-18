import { describe, it, expect } from 'vitest'
import { useSanitizeMarkdown, sanitizeHtml } from './useSanitizeMarkdown'

const { sanitizeMarkdown } = useSanitizeMarkdown()
const trusted = useSanitizeMarkdown({ trusted: true })

function render(html) {
  const host = document.createElement('div')
  host.innerHTML = html
  return host
}

describe('untrusted markdown (default)', () => {
  it('turns a remote markdown image into a link that shows its URL', () => {
    const url = 'https://evil.example/pixel.png?d=secret'
    const host = render(sanitizeMarkdown(`Status ![chart](${url})`))
    expect(host.querySelector('img')).toBeNull()
    const link = host.querySelector('a')
    expect(link).not.toBeNull()
    expect(link.getAttribute('href')).toBe(url)
    expect(link.textContent).toBe(url)
    expect(link.getAttribute('rel')).toContain('noopener')
  })

  it('turns a raw-HTML and a protocol-relative remote image into links too', () => {
    const host = render(sanitizeMarkdown('<img src="https://a.example/x.gif"> <img src="//b.example/y.gif">'))
    expect(host.querySelector('img')).toBeNull()
    expect([...host.querySelectorAll('a')].map((a) => a.getAttribute('href'))).toEqual([
      'https://a.example/x.gif',
      '//b.example/y.gif',
    ])
  })

  it('keeps a data:image image', () => {
    const host = render(sanitizeMarkdown('![dot](data:image/png;base64,iVBORw0KGgo=)'))
    const img = host.querySelector('img')
    expect(img).not.toBeNull()
    expect(img.getAttribute('src')).toBe('data:image/png;base64,iVBORw0KGgo=')
  })

  it('drops a non-image data: source entirely', () => {
    const host = render(sanitizeMarkdown('<img src="data:text/html,hi">'))
    expect(host.querySelector('img[src]')).toBeNull()
    expect(host.querySelector('a')).toBeNull()
  })

  it('drops class and id so content cannot borrow app layout', () => {
    const host = render(sanitizeMarkdown('<div class="v-navigation-drawer" id="app">x</div>'))
    const div = host.querySelector('div')
    expect(div.hasAttribute('class')).toBe(false)
    expect(div.hasAttribute('id')).toBe(false)
  })

  it('leaves ordinary markdown and links alone', () => {
    const out = sanitizeMarkdown('**bold** and [docs](https://giljo.ai/docs)')
    expect(out).toContain('<strong>bold</strong>')
    expect(out).toContain('href="https://giljo.ai/docs"')
  })
})

describe('trusted first-party content', () => {
  it('keeps remote images, class and id', () => {
    const host = render(trusted.sanitizeMarkdown('![x](https://giljo.ai/a.png)\n\n<div class="k" id="h">y</div>'))
    expect(host.querySelector('img').getAttribute('src')).toBe('https://giljo.ai/a.png')
    expect(host.querySelector('div').getAttribute('class')).toBe('k')
    expect(host.querySelector('div').getAttribute('id')).toBe('h')
  })

  it('sanitizeHtml (user guide, database messages) keeps images', () => {
    const host = render(sanitizeHtml('<h2 id="intro">Intro</h2><img src="https://giljo.ai/a.png">'))
    expect(host.querySelector('img')).not.toBeNull()
    expect(host.querySelector('h2').id).toBe('intro')
  })
})
