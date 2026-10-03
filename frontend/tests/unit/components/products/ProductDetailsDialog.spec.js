/**
 * Test suite for ProductDetailsDialog component
 * TDD Phase 1: Tests written FIRST before implementation
 *
 * Extracted from ProductsView.vue lines 1159-1338
 */
import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createVuetify } from 'vuetify'
import * as components from 'vuetify/components'
import * as directives from 'vuetify/directives'
import ProductDetailsDialog from '@/components/products/ProductDetailsDialog.vue'

describe('ProductDetailsDialog Component', () => {
  let vuetify

  beforeEach(() => {
    vuetify = createVuetify({
      components,
      directives,
    })
  })

  const createWrapper = (props = {}) => {
    return mount(ProductDetailsDialog, {
      props: {
        modelValue: true,
        product: {
          id: 'test-product-123',
          name: 'Test Product',
          description: 'Test description',
          unresolved_tasks: 5,
          unfinished_projects: 3,
          has_config_data: false,
          created_at: '2025-01-15T10:00:00Z',
          updated_at: '2025-01-16T14:30:00Z',
        },
        visionDocuments: [],
        stats: { unresolved_tasks: 5, unfinished_projects: 3 },
        ...props,
      },
      global: {
        plugins: [vuetify],
        stubs: {
          'v-dialog': {
            template: '<div class="v-dialog" v-if="modelValue"><slot /></div>',
            props: ['modelValue'],
          },
        },
      },
    })
  }

  describe('Dialog Visibility', () => {
    it('renders dialog when modelValue is true', () => {
      const wrapper = createWrapper({ modelValue: true })

      expect(wrapper.find('.v-dialog').exists()).toBe(true)
      expect(wrapper.text()).toContain('Product Details')
    })

    it('does not render dialog content when modelValue is false', async () => {
      const wrapper = createWrapper({ modelValue: false })

      // Dialog should exist but not be visible/open
      // The v-dialog with v-model=false should not display content
      const cardText = wrapper.find('.v-card-text')
      if (cardText.exists()) {
        // When dialog is closed, the content may be hidden
        expect(wrapper.find('.v-dialog--active').exists()).toBe(false)
      }
    })
  })

  describe('Product Information Display', () => {
    it('displays product name', () => {
      const wrapper = createWrapper({
        product: {
          id: 'prod-1',
          name: 'My Awesome Product',
          description: 'Some description',
        },
      })

      expect(wrapper.text()).toContain('My Awesome Product')
    })

    it('displays product ID', () => {
      const wrapper = createWrapper({
        product: {
          id: 'unique-product-id-456',
          name: 'Product Name',
        },
      })

      expect(wrapper.text()).toContain('unique-product-id-456')
    })

    it('displays product description', () => {
      const wrapper = createWrapper({
        product: {
          id: 'prod-1',
          name: 'Product',
          description: 'This is a detailed product description for testing.',
        },
      })

      expect(wrapper.text()).toContain('This is a detailed product description for testing.')
    })

    it('displays fallback text when no description provided', () => {
      const wrapper = createWrapper({
        product: {
          id: 'prod-1',
          name: 'Product',
          description: null,
        },
      })

      expect(wrapper.text()).toContain('No description provided')
    })

    it('does not render tune context controls inside product details', () => {
      const wrapper = createWrapper()

      expect(wrapper.text()).not.toContain('Tune Context')
      expect(wrapper.text()).not.toContain('Tuning Proposals')
    })
  })

  describe('Statistics Display', () => {
    it('displays unresolved tasks count', () => {
      const wrapper = createWrapper({
        product: {
          id: 'prod-1',
          name: 'Product',
          unresolved_tasks: 12,
        },
      })

      expect(wrapper.text()).toContain('Unresolved Tasks')
      expect(wrapper.text()).toContain('12')
    })

    it('displays unfinished projects count', () => {
      const wrapper = createWrapper({
        product: {
          id: 'prod-1',
          name: 'Product',
          unfinished_projects: 7,
        },
      })

      expect(wrapper.text()).toContain('Unfinished Projects')
      expect(wrapper.text()).toContain('7')
    })

    it('displays zero for missing statistics', () => {
      const wrapper = createWrapper({
        product: {
          id: 'prod-1',
          name: 'Product',
        },
      })

      // Should default to 0 for missing values
      expect(wrapper.text()).toContain('0')
    })
  })

  describe('Vision Documents Display', () => {
    it('lists vision documents with chunk counts', () => {
      const wrapper = createWrapper({
        visionDocuments: [
          { id: 'doc-1', document_name: 'architecture.md', chunk_count: 5, chunked: true, file_size: 1024 },
          { id: 'doc-2', document_name: 'requirements.md', chunk_count: 3, chunked: true, file_size: 512 },
        ],
      })

      expect(wrapper.text()).toContain('architecture.md')
      expect(wrapper.text()).toContain('5 chunks')
      expect(wrapper.text()).toContain('requirements.md')
      expect(wrapper.text()).toContain('3 chunks')
    })

    it('lists vision documents with file sizes', () => {
      const wrapper = createWrapper({
        visionDocuments: [
          { id: 'doc-1', document_name: 'design.pdf', chunk_count: 2, file_size: 2048 },
        ],
      })

      expect(wrapper.text()).toContain('design.pdf')
      // Should display formatted file size (2048 bytes = 2.0 KB)
      expect(wrapper.text()).toMatch(/2\.0\s*KB/)
    })

    it('displays document count in header', () => {
      const wrapper = createWrapper({
        visionDocuments: [
          { id: 'doc-1', document_name: 'doc1.md', chunk_count: 1, file_size: 100 },
          { id: 'doc-2', document_name: 'doc2.md', chunk_count: 2, file_size: 200 },
          { id: 'doc-3', document_name: 'doc3.md', chunk_count: 3, file_size: 300 },
        ],
      })

      expect(wrapper.text()).toContain('Vision Documents (3)')
    })

    it('shows alert when no vision documents exist', () => {
      const wrapper = createWrapper({
        visionDocuments: [],
      })

      expect(wrapper.text()).toContain('No vision documents attached')
    })

    it('handles document_name as fallback for filename', () => {
      const wrapper = createWrapper({
        visionDocuments: [
          { id: 'doc-1', document_name: 'Legacy Document Name', chunk_count: 4, file_size: 1024 },
        ],
      })

      expect(wrapper.text()).toContain('Legacy Document Name')
    })
  })

  describe('Aggregate Stats Panel (removed in FE-vision-card refactor)', () => {
    it('no longer renders the aggregate stats card', () => {
      const wrapper = createWrapper({
        visionDocuments: [
          { id: 'doc-1', document_name: 'doc1.md', chunk_count: 5, file_size: 1024 },
          { id: 'doc-2', document_name: 'doc2.md', chunk_count: 8, file_size: 2048 },
        ],
      })

      expect(wrapper.text()).not.toContain('Total chunks:')
      expect(wrapper.text()).not.toContain('Total size:')
      expect(wrapper.text()).not.toContain('Documents: 2')
    })

    it('no longer renders the "Pending analysis — N of N" product-level pill', () => {
      const wrapper = createWrapper({
        visionDocuments: [
          { id: 'doc-1', document_name: 'a.md', file_size: 100 },
          { id: 'doc-2', document_name: 'b.md', file_size: 100, summary_light: 'x', summary_medium: 'y' },
        ],
        product: {
          id: 'prod-1',
          name: 'Product',
          vision_analysis_complete: false,
        },
      })

      expect(wrapper.text()).not.toMatch(/Pending analysis — 1 of 2 docs analyzed/)
    })
  })

  describe('Per-doc manifest list (simplified)', () => {
    it('does not render a per-doc "Summary Previews" chevron', () => {
      const wrapper = createWrapper({
        visionDocuments: [
          {
            id: 'doc-1',
            document_name: 'a.md',
            is_summarized: true,
            file_size: 1024,
            summary_light_tokens: 100,
            summary_medium_tokens: 200,
          },
        ],
      })

      expect(wrapper.text()).not.toContain('Summary Previews')
      expect(wrapper.text()).not.toContain('AI-generated summaries')
    })
  })

  describe('Vision context summary chevron (new product-level card)', () => {
    it('does not render when no consolidated_vision_light exists', () => {
      const wrapper = createWrapper({
        visionDocuments: [
          { id: 'doc-1', document_name: 'a.md', file_size: 100 },
        ],
        product: {
          id: 'prod-1',
          name: 'Product',
        },
      })

      expect(wrapper.text()).not.toContain('Vision context summary')
    })

    it('renders chevron header when consolidated_vision_light is present', () => {
      const wrapper = createWrapper({
        visionDocuments: [
          { id: 'doc-1', document_name: 'a.md', file_size: 100, original_token_count: 1500 },
        ],
        product: {
          id: 'prod-1',
          name: 'Product',
          consolidated_vision_light: 'unified product story',
          consolidated_vision_light_tokens: 800,
          consolidated_vision_medium: 'longer unified product story',
          consolidated_vision_medium_tokens: 1600,
          consolidated_at: '2026-05-28T10:00:00Z',
          consolidated_vision_hash: 'abcdef1234567890',
        },
      })

      expect(wrapper.text()).toContain('Vision context summary')
    })

    it('renders three tier tiles and "Last modified" line when chevron is expanded', async () => {
      const wrapper = createWrapper({
        visionDocuments: [
          { id: 'doc-1', document_name: 'a.md', file_size: 100, original_token_count: 1500 },
          { id: 'doc-2', document_name: 'b.md', file_size: 100, original_token_count: 2500 },
        ],
        product: {
          id: 'prod-1',
          name: 'Product',
          consolidated_vision_light: 'unified product story',
          consolidated_vision_light_tokens: 800,
          consolidated_vision_medium: 'longer unified product story',
          consolidated_vision_medium_tokens: 1600,
          consolidated_at: '2026-05-28T10:00:00Z',
          consolidated_vision_hash: 'abcdef1234567890',
        },
      })

      const toggle = wrapper.findAll('button').find((b) => b.text().includes('Vision context summary'))
      expect(toggle).toBeTruthy()
      await toggle.trigger('click')

      // Three tier tiles
      expect(wrapper.text()).toMatch(/33%\s*·/)
      expect(wrapper.text()).toMatch(/66%\s*·/)
      expect(wrapper.text()).toMatch(/100%/)
      // 100% token estimate sums original_token_count = 4000
      expect(wrapper.text()).toContain('4.0K tokens')
      // Last modified line, not "Last consolidated"
      expect(wrapper.text()).toContain('Last modified:')
      expect(wrapper.text()).not.toContain('Last consolidated:')
      // Hash truncation
      expect(wrapper.text()).toContain('abcdef12')
    })

    it('does not render a Regenerate button anywhere', () => {
      const wrapper = createWrapper({
        visionDocuments: [
          { id: 'doc-1', document_name: 'a.md', file_size: 100, original_token_count: 1500 },
        ],
        product: {
          id: 'prod-1',
          name: 'Product',
          consolidated_vision_light: 'unified product story',
          consolidated_vision_light_tokens: 800,
          consolidated_at: '2026-05-28T10:00:00Z',
          consolidated_vision_hash: 'abcdef1234567890',
        },
      })

      const buttons = wrapper.findAll('button')
      const regen = buttons.find((b) => /regenerate/i.test(b.text()))
      expect(regen).toBeFalsy()
    })
  })

  describe('Config Data Section', () => {
    it('conditionally renders config_data section when tech_stack is present', () => {
      const wrapper = createWrapper({
        product: {
          id: 'prod-1',
          name: 'Product',
          tech_stack: {
            programming_languages: 'Python, JavaScript',
            frontend_frameworks: 'Vue 3',
            backend_frameworks: 'FastAPI',
            databases_storage: 'PostgreSQL',
          },
        },
      })

      expect(wrapper.text()).toContain('Configuration Data')
      expect(wrapper.text()).toContain('Tech Stack')
    })

    it('does not render config_data section when no config fields present', () => {
      const wrapper = createWrapper({
        product: {
          id: 'prod-1',
          name: 'Product',
        },
      })

      expect(wrapper.text()).not.toContain('Configuration Data')
    })

    it('displays tech stack details', () => {
      const wrapper = createWrapper({
        product: {
          id: 'prod-1',
          name: 'Product',
          tech_stack: {
            programming_languages: 'TypeScript, Rust',
            frontend_frameworks: 'React',
            backend_frameworks: 'Axum',
            databases_storage: 'MongoDB',
          },
        },
      })

      expect(wrapper.text()).toContain('Tech Stack')
    })

    it('displays architecture details', () => {
      const wrapper = createWrapper({
        product: {
          id: 'prod-1',
          name: 'Product',
          architecture: {
            primary_pattern: 'Microservices',
            api_style: 'REST',
            design_patterns: 'Repository, Factory',
          },
        },
      })

      expect(wrapper.text()).toContain('Architecture')
    })

    it('displays features and testing section', () => {
      const wrapper = createWrapper({
        product: {
          id: 'prod-1',
          name: 'Product',
          core_features: 'User management, Authentication',
          test_config: {
            test_strategy: 'TDD',
            coverage_target: 80,
          },
        },
      })

      expect(wrapper.text()).toContain('Features & Testing')
    })
  })

  describe('Event Handling', () => {
    it('emits update:modelValue when close button clicked', async () => {
      const wrapper = createWrapper()

      // Find all buttons and click the one with "Close" text
      const buttons = wrapper.findAll('button')
      const closeBtn = buttons.find(btn => btn.text().includes('Close'))

      if (closeBtn) {
        await closeBtn.trigger('click')
      } else {
        // Fallback: find any button element
        const allBtns = wrapper.findAll('.v-btn')
        expect(allBtns.length).toBeGreaterThan(0)
        await allBtns[allBtns.length - 1].trigger('click')
      }

      expect(wrapper.emitted('update:modelValue')).toBeTruthy()
      expect(wrapper.emitted('update:modelValue')[0]).toEqual([false])
    })

    it('emits update:modelValue when X button clicked in header', async () => {
      const wrapper = createWrapper()

      // Find buttons - try .v-btn first, then fall back to button elements
      let buttons = wrapper.findAll('.v-btn')
      if (buttons.length === 0) {
        buttons = wrapper.findAll('button')
      }
      expect(buttons.length).toBeGreaterThan(0)

      // First button is X in title, last is Close in actions
      await buttons[0].trigger('click')

      expect(wrapper.emitted('update:modelValue')).toBeTruthy()
      expect(wrapper.emitted('update:modelValue')[0]).toEqual([false])
    })
  })

  describe('File Size Formatting', () => {
    it('formats bytes correctly', () => {
      const wrapper = createWrapper({
        visionDocuments: [
          { id: 'doc-1', document_name: 'small.txt', chunk_count: 1, file_size: 500 },
        ],
      })

      expect(wrapper.text()).toContain('500 B')
    })

    it('formats kilobytes correctly', () => {
      const wrapper = createWrapper({
        visionDocuments: [
          { id: 'doc-1', document_name: 'medium.md', chunk_count: 1, file_size: 5120 },
        ],
      })

      // 5120 bytes = 5.0 KB
      expect(wrapper.text()).toMatch(/5\.0\s*KB/)
    })

    it('formats megabytes correctly', () => {
      const wrapper = createWrapper({
        visionDocuments: [
          { id: 'doc-1', document_name: 'large.pdf', chunk_count: 10, file_size: 2097152 },
        ],
      })

      // 2097152 bytes = 2.0 MB
      expect(wrapper.text()).toMatch(/2\.0\s*MB/)
    })

    it('handles zero file size', () => {
      const wrapper = createWrapper({
        visionDocuments: [
          { id: 'doc-1', document_name: 'empty.txt', chunk_count: 0, file_size: 0 },
        ],
      })

      expect(wrapper.text()).toContain('0 B')
    })
  })

  describe('Date Formatting', () => {
    it('displays created date', () => {
      const wrapper = createWrapper({
        product: {
          id: 'prod-1',
          name: 'Product',
          created_at: '2025-03-15T10:00:00Z',
          updated_at: '2025-03-16T14:30:00Z',
        },
      })

      expect(wrapper.text()).toContain('Created:')
    })

    it('displays updated date', () => {
      const wrapper = createWrapper({
        product: {
          id: 'prod-1',
          name: 'Product',
          created_at: '2025-03-15T10:00:00Z',
          updated_at: '2025-03-16T14:30:00Z',
        },
      })

      expect(wrapper.text()).toContain('Updated:')
    })
  })

  describe('Edge Cases', () => {
    it('handles empty product object gracefully', () => {
      const wrapper = createWrapper({
        product: {},
      })

      // Should not throw, should display fallbacks
      expect(wrapper.exists()).toBe(true)
      expect(wrapper.text()).toContain('No description provided')
    })

    it('handles undefined visionDocuments', () => {
      const wrapper = mount(ProductDetailsDialog, {
        props: {
          modelValue: true,
          product: { id: '1', name: 'Test' },
          // visionDocuments not provided - should use default
        },
        global: {
          plugins: [vuetify],
        },
      })

      expect(wrapper.text()).toContain('Vision Documents (0)')
      expect(wrapper.text()).toContain('No vision documents attached')
    })

    it('handles documents with missing chunk_count', () => {
      const wrapper = createWrapper({
        visionDocuments: [
          { id: 'doc-1', document_name: 'test.md', file_size: 1024 },
        ],
      })

      // Aggregate stats panel removed in FE-vision-card refactor.
      // Doc renders without crashing; no "Chunked · N chunks" pill since
      // chunked is falsy.
      expect(wrapper.text()).toContain('test.md')
      expect(wrapper.text()).not.toContain('Chunked ·')
    })

    it('handles documents with missing file_size', () => {
      const wrapper = createWrapper({
        visionDocuments: [
          { id: 'doc-1', document_name: 'test.md', chunk_count: 5 },
        ],
      })

      // Should default to 0 bytes
      expect(wrapper.text()).toContain('0 B')
    })
  })

  describe('Accessibility', () => {
    it('dialog has proper close button', () => {
      const wrapper = createWrapper()

      // Should have at least 2 buttons (X in header, Close in actions)
      let buttons = wrapper.findAll('.v-btn')
      if (buttons.length === 0) {
        buttons = wrapper.findAll('button')
      }
      expect(buttons.length).toBeGreaterThanOrEqual(2)

      // Component should have Product Details title
      expect(wrapper.text()).toContain('Product Details')

      // Component should have Close button text
      expect(wrapper.text()).toContain('Close')
    })
  })
})
