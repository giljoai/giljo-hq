<template>
  <div class="guide-layout">
    <div class="guide-inner">
      <aside class="guide-sidebar">
        <div class="guide-sidebar-header">
          <div class="guide-sidebar-title">Contents</div>
          <div class="guide-search-box">
            <v-icon size="16" class="guide-search-icon">mdi-magnify</v-icon>
            <input
              v-model="searchQuery"
              type="text"
              placeholder="Search..."
              class="guide-search-input"
              @keydown.escape="searchQuery = ''"
            />
            <button v-if="searchQuery" class="guide-search-clear" @click="searchQuery = ''">
              <v-icon size="14">mdi-close</v-icon>
            </button>
          </div>
        </div>

        <div v-if="searchQuery && searchResults.length" class="guide-search-results">
          <button
            v-for="result in searchResults"
            :key="result.anchor"
            class="guide-search-result"
            @click="goToSearchResult(result)"
          >
            <span class="guide-search-result-section">{{ result.section }}</span>
            <span class="guide-search-result-snippet" v-html="result.snippet" />
          </button>
        </div>
        <div v-else-if="searchQuery" class="guide-search-empty">
          No results
        </div>

        <nav v-else class="guide-toc" aria-label="Table of contents">
          <button
            v-for="entry in tocEntries"
            :key="entry.anchor"
            class="guide-toc-item"
            :class="{ 'guide-toc-item--active': activeTocAnchor === entry.anchor }"
            @click="scrollToAnchor(entry.anchor)"
          >
            {{ entry.text }}
          </button>
        </nav>
      </aside>

      <main ref="contentRef" class="guide-content">
        <div class="guide-prose" v-html="renderedMarkdown" />
      </main>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, nextTick, watch } from 'vue'
import { useRoute } from 'vue-router'
import { marked } from 'marked'
import { sanitizeHtml } from '@/composables/useSanitizeMarkdown'
import configService from '@/services/configService'
import { useGiljoMode } from '@/composables/useGiljoMode'
import { installGuideCalloutRenderer } from '@/utils/guideCalloutRenderer'
import { slugify } from '@/utils/escapeHtml'
import './userGuideProse.scss'
import overviewMd from '../../../docs/PRODUCT_OVERVIEW.md?raw'
import gettingStartedMd from '../../../docs/GETTING_STARTED.md?raw'
import userGuideMd from '../../../docs/USER_GUIDE.md?raw'
import decisionGuideMd from '../content/guide/decision-guide.md?raw'
import chainsMd from '../content/guide/chains.md?raw'
import headlessFlowMd from '../content/guide/headless-flow.md?raw'
import glossaryMd from '../content/guide/glossary.md?raw'

const saasMdModules = import.meta.glob('../saas/docs/*.md', { query: '?raw', import: 'default', eager: true })

const route = useRoute()
const isSaas = ref(false)
const { isSaasMode } = useGiljoMode()

const contentRef = ref(null)
const activeTocAnchor = ref('')
const searchQuery = ref('')

const combinedMarkdown = computed(() => {
  const parts = [overviewMd]
  if (gettingStartedMd) {
    parts.push(gettingStartedMd)
  }
  parts.push(decisionGuideMd)
  parts.push(chainsMd)
  parts.push(headlessFlowMd)
  parts.push(userGuideMd)
  parts.push(glossaryMd)

  if (isSaas.value) {
    const sortedKeys = Object.keys(saasMdModules).sort()
    for (const key of sortedKeys) {
      const md = saasMdModules[key]
      if (md) parts.push(md)
    }
  }

  return parts.join('\n\n---\n\n')
})

installGuideCalloutRenderer(marked)

const renderedMarkdown = computed(() => {
  const html = marked.parse(combinedMarkdown.value)
  return sanitizeHtml(html)
})

const tocEntries = computed(() => {
  const entries = []
  const lines = combinedMarkdown.value.split('\n')
  for (const line of lines) {
    const match = line.match(/^## (.+)$/)
    if (match) {
      const text = match[1].trim()
      entries.push({ text, anchor: slugify(text) })
    }
  }
  return entries
})


const searchableSections = computed(() => {
  const sections = []
  const lines = combinedMarkdown.value.split('\n')
  let currentSection = null

  for (const line of lines) {
    const match = line.match(/^## (.+)$/)
    if (match) {
      if (currentSection) sections.push(currentSection)
      currentSection = {
        title: match[1].trim(),
        anchor: slugify(match[1].trim()),
        text: '',
      }
    } else if (currentSection) {
      currentSection.text += `${line  }\n`
    }
  }
  if (currentSection) sections.push(currentSection)
  return sections
})

const searchResults = computed(() => {
  const q = searchQuery.value.trim().toLowerCase()
  if (!q || q.length < 2) return []

  const results = []
  for (const section of searchableSections.value) {
    const plainText = section.text
      .replace(/[#*_`|[\]()>-]/g, '')
      .replace(/\n+/g, ' ')
      .trim()

    const idx = plainText.toLowerCase().indexOf(q)
    if (idx === -1 && !section.title.toLowerCase().includes(q)) continue

    let snippet = ''
    if (idx !== -1) {
      const start = Math.max(0, idx - 30)
      const end = Math.min(plainText.length, idx + q.length + 50)
      const raw = (start > 0 ? '...' : '') + plainText.slice(start, end) + (end < plainText.length ? '...' : '')
      snippet = sanitizeHtml(raw.replace(
        new RegExp(`(${q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi'),
        '<mark>$1</mark>'
      ))
    }

    results.push({
      section: section.title,
      anchor: section.anchor,
      snippet,
    })
  }
  return results.slice(0, 10)
})

function goToSearchResult(result) {
  searchQuery.value = ''
  nextTick(() => scrollToAnchor(result.anchor))
}


function scrollToAnchor(anchor) {
  const el = document.getElementById(anchor)
  if (el) {
    el.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }
}

let observer = null

function setupObserver() {
  if (observer) {
    observer.disconnect()
  }
  if (!contentRef.value) return

  const headings = contentRef.value.querySelectorAll('h2[id]')
  if (!headings.length) return

  observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting) {
          activeTocAnchor.value = entry.target.id
        }
      }
    },
    {
      root: null,
      rootMargin: '-10% 0px -75% 0px',
      threshold: 0,
    }
  )

  headings.forEach((h) => observer.observe(h))
}

function handleUrlAnchor() {
  const hash = route.hash?.replace('#', '')
  if (hash) {
    nextTick(() => {
      setTimeout(() => scrollToAnchor(hash), 100)
    })
  }
}

onMounted(async () => {
  await configService.fetchConfig()
  isSaas.value = isSaasMode()
  await nextTick()
  setupObserver()
  handleUrlAnchor()
})

watch(renderedMarkdown, async () => {
  await nextTick()
  setupObserver()
})

onBeforeUnmount(() => {
  if (observer) {
    observer.disconnect()
    observer = null
  }
})
</script>

<style scoped lang="scss">
@use '../styles/design-tokens' as *;
@use '../styles/variables' as *;

.guide-layout {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 64px); // subtract app bar height
  background: var(--color-bg-primary);
  overflow: hidden;
}

// ─── DESKTOP TWO-COLUMN LAYOUT ───

.guide-inner {
  display: flex;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

// ─── SIDEBAR (fixed to viewport, scrolls independently) ───

.guide-sidebar {
  width: 220px;
  flex-shrink: 0;
  background: var(--color-bg-secondary);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-shadow: inset -1px 0 0 rgba(255, 255, 255, 0.08);
}

.guide-sidebar-header {
  padding: 20px 16px 12px;
  flex-shrink: 0;
}

.guide-sidebar-title {
  font-size: 0.7rem;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-muted);
  margin-bottom: 12px;
}

// ─── SEARCH BOX ───

.guide-search-box {
  display: flex;
  align-items: center;
  gap: 6px;
  background: rgba(255, 255, 255, 0.05);
  border-radius: 6px;
  padding: 6px 10px;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.08);
  transition: box-shadow 0.15s ease;

  &:focus-within {
    box-shadow: inset 0 0 0 1px rgba($yellow, 0.4);
  }
}

.guide-search-icon {
  color: var(--text-muted);
  flex-shrink: 0;
}

.guide-search-input {
  border: none;
  outline: none;
  background: transparent;
  color: var(--color-text-primary);
  font-size: 0.8rem;
  font-family: inherit;
  width: 100%;
  min-width: 0;

  &::placeholder {
    color: var(--text-muted);
  }
}

.guide-search-clear {
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  background: transparent;
  cursor: pointer;
  color: var(--text-muted);
  padding: 2px;
  border-radius: 4px;
  flex-shrink: 0;

  &:hover {
    color: var(--color-text-primary);
  }
}

// ─── SEARCH RESULTS ───

.guide-search-results {
  overflow-y: auto;
  flex: 1;
  padding: 0 12px 12px;
}

.guide-search-result {
  display: flex;
  flex-direction: column;
  width: 100%;
  text-align: left;
  padding: 8px 10px;
  border: none;
  background: transparent;
  cursor: pointer;
  border-radius: 6px;
  transition: background 0.15s ease;

  &:hover {
    background: rgba(255, 255, 255, 0.05);
  }
}

.guide-search-result-section {
  font-size: 0.8rem;
  font-weight: 600;
  color: $yellow;
  margin-bottom: 2px;
}

.guide-search-result-snippet {
  font-size: 0.75rem;
  color: var(--text-muted);
  line-height: 1.4;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;

  :deep(mark) {
    background: rgba($yellow, 0.25);
    color: var(--color-text-primary);
    border-radius: 2px;
    padding: 0 2px;
  }
}

.guide-search-empty {
  padding: 16px;
  font-size: 0.8rem;
  color: var(--text-muted);
  text-align: center;
}

// ─── TOC (below search, scrolls independently) ───

.guide-toc {
  display: flex;
  flex-direction: column;
  gap: 2px;
  overflow-y: auto;
  flex: 1;
  padding: 0 12px 16px;
}

.guide-toc-item {
  display: block;
  width: 100%;
  text-align: left;
  padding: 6px 8px;
  border: none;
  background: transparent;
  cursor: pointer;
  font-size: 0.875rem;
  line-height: 1.4;
  color: var(--text-muted);
  border-radius: 6px;
  transition: color 0.15s ease, background 0.15s ease;

  &:hover {
    color: var(--color-text-primary);
    background: rgba(255, 255, 255, 0.05);
  }

  &--active {
    color: $yellow;
    background: rgba($yellow, 0.08);
  }
}

// ─── CONTENT AREA (scrolls independently) ───

.guide-content {
  flex: 1;
  overflow-y: auto;
  padding: 32px 24px;
  background: var(--color-bg-primary);
}

.guide-prose {
  max-width: 800px;
  margin: 0 auto;
  color: var(--text-secondary);
  line-height: 1.7;
  font-size: 0.95rem;
}
</style>
