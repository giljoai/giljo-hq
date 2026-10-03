import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import { reactive } from 'vue'
import ProductTechTab from './ProductTechTab.vue'
import ProductArchTab from './ProductArchTab.vue'

const FIELD_PROPS = [
  'modelValue', 'placeholder', 'hint', 'persistentHint', 'variant', 'density', 'rows', 'autoGrow',
  'value', 'label', 'hideDetails', 'disabled', 'color',
]
const Textarea = {
  name: 'VTextarea',
  props: FIELD_PROPS,
  emits: ['update:modelValue'],
  template: '<div class="ta"><slot name="label" /></div>',
}
const Checkbox = { name: 'VCheckbox', props: FIELD_PROPS, emits: ['update:modelValue'], template: '<div class="cb" />' }
const stubs = { 'v-textarea': Textarea, 'v-checkbox': Checkbox, 'v-chip': { template: '<span><slot /></span>' } }

function form(platforms = ['windows']) {
  return reactive({
    targetPlatforms: platforms,
    techStack: { programming_languages: 'py', frontend_frameworks: 'vue', backend_frameworks: 'fastapi', databases_storage: 'pg', infrastructure: 'docker' },
    architecture: { primary_pattern: 'a', design_patterns: 'b', api_style: 'c', architecture_notes: 'd', coding_conventions: 'e' },
  })
}

const described = (w, C) =>
  w.findAllComponents(C).map((c) => {
    const p = Object.fromEntries(Object.entries(c.props()).filter(([, v]) => v !== undefined))
    return { ...p, slotLabel: c.text(), cls: c.classes() }
  })

describe('ProductTechTab fields', () => {
  it('renders the five textareas and seven platform checkboxes as before', () => {
    const w = mount(ProductTechTab, { props: { form: form() }, global: { stubs } })
    expect(described(w, Textarea)).toMatchInlineSnapshot(`
      [
        {
          "autoGrow": "",
          "cls": [
            "ta",
            "mb-4",
          ],
          "density": "comfortable",
          "hint": "List all programming languages used (comma-separated or line-by-line)",
          "modelValue": "py",
          "persistentHint": "",
          "placeholder": "Python 3.11, JavaScript ES2023, TypeScript 5.2",
          "rows": "3",
          "slotLabel": "Programming Languages",
          "variant": "outlined",
        },
        {
          "autoGrow": "",
          "cls": [
            "ta",
            "mb-4",
          ],
          "density": "comfortable",
          "hint": "List frontend technologies (frameworks, libraries, tools)",
          "modelValue": "vue",
          "persistentHint": "",
          "placeholder": "Vue 3, Vuetify 3, Pinia, Vue Router",
          "rows": "3",
          "slotLabel": "Frontend Frameworks & Libraries",
          "variant": "outlined",
        },
        {
          "autoGrow": "",
          "cls": [
            "ta",
            "mb-4",
          ],
          "density": "comfortable",
          "hint": "List backend technologies (frameworks, ORMs, services)",
          "modelValue": "fastapi",
          "persistentHint": "",
          "placeholder": "FastAPI 0.104, SQLAlchemy 2.0, Alembic, asyncio",
          "rows": "3",
          "slotLabel": "Backend Frameworks & Services",
          "variant": "outlined",
        },
        {
          "autoGrow": "",
          "cls": [
            "ta",
            "mb-4",
          ],
          "density": "comfortable",
          "hint": "List databases and data storage solutions",
          "modelValue": "pg",
          "persistentHint": "",
          "placeholder": "PostgreSQL 16, Redis 7, Vector embeddings (pgvector)",
          "rows": "3",
          "slotLabel": "Databases & Data Storage",
          "variant": "outlined",
        },
        {
          "autoGrow": "",
          "cls": [
            "ta",
            "mb-4",
          ],
          "density": "comfortable",
          "hint": "List infrastructure and deployment tools",
          "modelValue": "docker",
          "persistentHint": "",
          "placeholder": "Docker, Kubernetes, GitHub Actions CI/CD, AWS (EC2, S3, RDS)",
          "rows": "3",
          "slotLabel": "Infrastructure & DevOps",
          "variant": "outlined",
        },
      ]
    `)
    expect(described(w, Checkbox)).toMatchInlineSnapshot(`
      [
        {
          "cls": [
            "cb",
          ],
          "density": "comfortable",
          "disabled": false,
          "hideDetails": "",
          "label": "Windows",
          "modelValue": [
            "windows",
          ],
          "slotLabel": "",
          "value": "windows",
        },
        {
          "cls": [
            "cb",
          ],
          "density": "comfortable",
          "disabled": false,
          "hideDetails": "",
          "label": "Linux",
          "modelValue": [
            "windows",
          ],
          "slotLabel": "",
          "value": "linux",
        },
        {
          "cls": [
            "cb",
          ],
          "density": "comfortable",
          "disabled": false,
          "hideDetails": "",
          "label": "macOS",
          "modelValue": [
            "windows",
          ],
          "slotLabel": "",
          "value": "macos",
        },
        {
          "cls": [
            "cb",
          ],
          "density": "comfortable",
          "disabled": false,
          "hideDetails": "",
          "label": "Android",
          "modelValue": [
            "windows",
          ],
          "slotLabel": "",
          "value": "android",
        },
        {
          "cls": [
            "cb",
          ],
          "density": "comfortable",
          "disabled": false,
          "hideDetails": "",
          "label": "iOS",
          "modelValue": [
            "windows",
          ],
          "slotLabel": "",
          "value": "ios",
        },
        {
          "cls": [
            "cb",
          ],
          "density": "comfortable",
          "disabled": false,
          "hideDetails": "",
          "label": "Web",
          "modelValue": [
            "windows",
          ],
          "slotLabel": "",
          "value": "web",
        },
        {
          "cls": [
            "cb",
          ],
          "color": "primary",
          "density": "comfortable",
          "hideDetails": "",
          "label": "All (Cross-platform)",
          "modelValue": [
            "windows",
          ],
          "slotLabel": "",
          "value": "all",
        },
      ]
    `)
  })

  it('typing writes the matching tech-stack field', async () => {
    const f = form()
    const w = mount(ProductTechTab, { props: { form: f }, global: { stubs } })
    const tas = w.findAllComponents(Textarea)
    const keys = ['programming_languages', 'frontend_frameworks', 'backend_frameworks', 'databases_storage', 'infrastructure']
    for (const [i, key] of keys.entries()) {
      tas[i].vm.$emit('update:modelValue', `new-${key}`)
    }
    expect(Object.values(f.techStack)).toEqual(keys.map((k) => `new-${k}`))
  })

  it('platform checkboxes emit their events and are disabled under All', async () => {
    const f = form(['all'])
    const w = mount(ProductTechTab, { props: { form: f }, global: { stubs } })
    const cbs = w.findAllComponents(Checkbox)
    expect(cbs.map((c) => c.props('disabled'))).toEqual([true, true, true, true, true, true, undefined])
    cbs[1].vm.$emit('update:modelValue', ['all', 'linux'])
    cbs[6].vm.$emit('update:modelValue', ['windows'])
    expect(w.emitted()).toMatchObject({ 'platform-change': [[]], 'all-platform-change': [[['windows']]] })
    expect(f.targetPlatforms).toEqual(['windows'])
  })
})

describe('ProductArchTab fields', () => {
  it('renders the five textareas as before', () => {
    const w = mount(ProductArchTab, { props: { form: form() }, global: { stubs } })
    expect(described(w, Textarea)).toMatchInlineSnapshot(`
      [
        {
          "autoGrow": "",
          "cls": [
            "ta",
            "mb-4",
          ],
          "density": "comfortable",
          "hint": "Describe the overall system architecture approach",
          "modelValue": "a",
          "persistentHint": "",
          "placeholder": "Modular Monolith with Event-Driven components, CQRS for high-traffic modules",
          "rows": "2",
          "slotLabel": "Primary Architecture Pattern",
          "variant": "outlined",
        },
        {
          "autoGrow": "",
          "cls": [
            "ta",
            "mb-4",
          ],
          "density": "comfortable",
          "hint": "List design patterns and architectural principles used",
          "modelValue": "b",
          "persistentHint": "",
          "placeholder": "Repository Pattern, Dependency Injection, Factory Pattern, SOLID principles",
          "rows": "3",
          "slotLabel": "Design Patterns & Principles",
          "variant": "outlined",
        },
        {
          "autoGrow": "",
          "cls": [
            "ta",
            "mb-4",
          ],
          "density": "comfortable",
          "hint": "Describe API communication patterns and protocols",
          "modelValue": "c",
          "persistentHint": "",
          "placeholder": "REST API (OpenAPI 3.0), WebSocket for real-time updates, GraphQL for complex queries",
          "rows": "2",
          "slotLabel": "API Style & Communication",
          "variant": "outlined",
        },
        {
          "autoGrow": "",
          "cls": [
            "ta",
            "mb-4",
          ],
          "density": "comfortable",
          "hint": "Additional architectural decisions, constraints, or context",
          "modelValue": "d",
          "persistentHint": "",
          "rows": "4",
          "slotLabel": "Architecture Notes",
          "variant": "outlined",
        },
        {
          "autoGrow": "",
          "cls": [
            "ta",
            "mb-4",
          ],
          "density": "comfortable",
          "hint": "Define naming conventions, error handling patterns, code style rules, and other standards agents should follow when writing code",
          "modelValue": "e",
          "persistentHint": "",
          "rows": "6",
          "slotLabel": "Coding Conventions & Standards",
          "variant": "outlined",
        },
      ]
    `)
  })

  it('typing writes the matching architecture field', async () => {
    const f = form()
    const w = mount(ProductArchTab, { props: { form: f }, global: { stubs } })
    const keys = ['primary_pattern', 'design_patterns', 'api_style', 'architecture_notes', 'coding_conventions']
    w.findAllComponents(Textarea).forEach((c, i) => c.vm.$emit('update:modelValue', `x-${keys[i]}`))
    expect(Object.values(f.architecture)).toEqual(keys.map((k) => `x-${k}`))
  })
})
