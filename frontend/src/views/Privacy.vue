<template>
  <v-container class="legal-container py-8" max-width="900">
    <v-card class="legal-card smooth-border pa-6 pa-md-8">
      <header class="mb-6">
        <h1 class="text-headline-large font-weight-bold mb-2">Privacy Policy</h1>
        <p class="legal-meta mb-0">
          Last updated: 2026-08-07 · GiljoAI LLC
        </p>
      </header>

      <section class="mb-6">
        <h2 class="text-title-large mb-2">1. Who we are</h2>
        <p class="legal-body">
          This service is operated by GiljoAI LLC ("we", "us"). It is licensed
          under the {{ licenseName }}. This Privacy Policy describes what data
          the hosted service collects, why, and how it is stored.
        </p>
      </section>

      <section class="mb-6">
        <h2 class="text-title-large mb-2">2. What we collect</h2>
        <ul class="legal-list">
          <li><strong>Account data</strong>: your email, display name, and authentication metadata (password hashes, session tokens).</li>
          <li><strong>Billing data</strong>: when you subscribe to a hosted paid edition, our billing provider collects payment details, billing address, and tax ID directly. We receive only your customer ID, subscription status, current period end, and invoice references, never card numbers or full payment details.</li>
          <li><strong>Product data</strong>: projects, tasks, agent missions, and messages you create inside the platform.</li>
          <li><strong>Operational logs</strong>: request logs, error traces, and audit events.</li>
          <li><strong>Browser metadata</strong>: IP address and user-agent, used for rate-limiting and security.</li>
        </ul>
      </section>

      <section class="mb-6">
        <h2 class="text-title-large mb-2">3. Where data is stored</h2>
        <component :is="saasDataHosting" v-if="saasDataHosting" />
        <p v-else class="legal-body">
          Your product data lives in a managed <strong>PostgreSQL</strong>
          database hosted on SOC 2 Type 2 infrastructure in the United
          States (US East region), encrypted at rest. Encrypted database
          backup archives are stored on managed object storage, also in the
          United States. Data is scoped per tenant: each account's records
          are isolated by tenant key on every query.
        </p>
      </section>

      <section class="mb-6">
        <h2 class="text-title-large mb-2">4. Sub-processors</h2>
        <p class="legal-body">We use the following third parties to operate the service:</p>
        <component :is="saasSubprocessorList" v-if="saasSubprocessorList" />
        <ul v-else class="legal-list">
          <li><strong>Billing provider</strong>: payment processing and Merchant of Record for paid hosted subscriptions. Handles payment collection, billing addresses, tax (VAT/sales tax/GST) calculation, invoices, refunds, and payment method storage on PCI-compliant infrastructure. The billing provider is an independent Data Controller for transaction records and retains them as required for VAT, AML, and fraud-prevention obligations.</li>
          <li><strong>Transactional email provider</strong>: registration, password reset, billing notifications, and account-deletion confirmation emails.</li>
          <li><strong>Error monitoring provider</strong>: receives stack traces and anonymized request metadata when errors occur, so we can diagnose and fix bugs.</li>
          <li><strong>Network edge provider</strong>: DNS, CDN, and reverse proxy in front of the hosted edition. Sees the IP addresses, request headers, and request URLs of traffic to our domains.</li>
          <li><strong>Hosting provider</strong>: application and database hosting for the hosted service, in the United States.</li>
          <li><strong>Object storage provider</strong>: storage for our encrypted database backup archives and point-in-time recovery archives, in the United States.</li>
        </ul>
        <p class="legal-body">
          We will update this list when sub-processors change, and reflect any
          change in the date at the top of this page.
        </p>
      </section>

      <section class="mb-6">
        <h2 class="text-title-large mb-2">5. How we use your data</h2>
        <p class="legal-body">
          We use account and product data only to operate the service you have
          asked us to operate. We do not sell your data and we do not use it
          for advertising. Aggregated, anonymized usage statistics may be used
          to improve the platform.
        </p>
      </section>

      <section class="mb-6">
        <h2 class="text-title-large mb-2">6. How long we keep your data</h2>
        <ul class="legal-list">
          <li><strong>While your subscription is active</strong>: we keep your data for as long as your subscription is active.</li>
          <li><strong>If you cancel or your subscription lapses</strong>: your account becomes read-only. You can still sign in to view your data, export it, or resubscribe. We keep it for one year from the date your paid access ended, then delete it permanently. We email you a reminder about 30 days before that happens.</li>
          <li><strong>If you ask us to delete your account</strong>: you choose immediate deletion, or a 30-day grace period in which you can change your mind. An erasure request made under GDPR Article 17 is completed within the one-month period the law requires.</li>
          <li><strong>What deletion removes</strong>: your database records and your stored backup archives are both erased, and your subscription with our payment processor is cancelled as part of the same process.</li>
          <li><strong>Backups</strong>: we keep your 7 most recent daily archives, 4 weekly archives, and up to 5 manual archives; older ones are removed automatically. Our hosting provider also takes daily platform snapshots of the database, kept for about 6 days, and maintains a continuous point-in-time recovery archive covering up to approximately the last four weeks. Deleted data can persist in these provider-side backups until they age out on those schedules.</li>
          <li><strong>Deletion receipts</strong>: retained for 7 years, then deleted. A receipt contains no personal data: a cryptographic hash of your tenant identifier, the timestamps of each deletion step, and the payment processor's cancellation confirmation, signed with HMAC-SHA256.</li>
        </ul>
      </section>

      <section class="mb-6">
        <h2 class="text-title-large mb-2">7. Your rights</h2>
        <p class="legal-body">
          You can request export or permanent deletion of your account data
          at any time from <em>Account → Danger Zone</em> inside the app, or
          by emailing
          <a class="legal-link" href="mailto:admin@giljo.ai">admin@giljo.ai</a>.
          Deletion always requires email confirmation. At confirmation you
          choose the pace: immediate deletion, or an optional 30-day grace
          period during which you can still cancel the request. If you have
          an active paid subscription, confirming deletion cancels it; your
          access ends with deletion and no further charges occur; any
          remaining paid time is forfeited and is not refunded. Your data is
          then permanently purged (immediately when you waive the grace
          period, otherwise at the end of the 30-day grace). Residual copies
          in encrypted disaster-recovery backups and the hosting provider's
          point-in-time recovery archive expire on the schedules described in
          section 6.
        </p>
      </section>

      <section class="mb-6">
        <h2 class="text-title-large mb-2">8. Self-hosted (CE) users</h2>
        <p class="legal-body">
          If you run {{ productName }} on your own infrastructure under the
          {{ licenseName }}, this Privacy Policy does not apply: your data
          stays on your hardware and we have no access to it. This document
          covers only the hosted demo and SaaS editions.
        </p>
      </section>

      <section class="mb-6">
        <h2 class="text-title-large mb-2">9. Contact</h2>
        <p class="legal-body">
          Questions about this policy:
          <a class="legal-link" href="mailto:admin@giljo.ai">admin@giljo.ai</a>.
        </p>
      </section>

      <footer class="legal-footer mt-6 pt-4">
        <router-link class="legal-link" to="/terms">Terms of Service</router-link>
        <span class="mx-2">·</span>
        <router-link class="legal-link" to="/login">Back to sign in</router-link>
      </footer>
    </v-card>
  </v-container>
</template>

<script setup>
import { onMounted, shallowRef } from 'vue'
import { LICENSE_NAME_FULL } from '@/i18n/licenseCopy'
import { PRODUCT_NAME } from '@/branding'
import configService from '@/services/configService'
import { isNonCeModeValue } from '@/composables/useGiljoMode'

const productName = PRODUCT_NAME

const licenseName = LICENSE_NAME_FULL

// FE-9374b: the hosted editions name their billing and infrastructure
// vendors in these sections, but the CE export gate bans provider names in
// CE-shipped source (comments and tests included). The vendor-naming copy
// lives under saas/ (stripped from every CE export) and loads via the
// ADR-004 import.meta.glob pattern; CE renders the vendor-neutral fallback
// copy inline above.
const saasDataHosting = shallowRef(null)
const saasSubprocessorList = shallowRef(null)

onMounted(async () => {
  let mode = 'ce'
  try {
    await configService.fetchConfig()
    mode = configService.getGiljoMode()
  } catch {
    // Config unavailable: keep the CE fallback copy.
  }
  if (!isNonCeModeValue(mode)) return
  const sections = [
    [import.meta.glob('@/saas/components/policy/SaasDataHosting.vue'), saasDataHosting],
    [import.meta.glob('@/saas/components/policy/SaasSubprocessorList.vue'), saasSubprocessorList],
  ]
  for (const [loaders, target] of sections) {
    const [loader] = Object.values(loaders)
    if (!loader) continue
    try {
      const mod = await loader()
      target.value = mod.default
    } catch (error) {
      console.warn('[Privacy] SaaS policy section failed to load:', error)
    }
  }
})
</script>

<style lang="scss" scoped>
@use '@/styles/legal-typography' as legal;
@include legal.legal-typography-page;
</style>
