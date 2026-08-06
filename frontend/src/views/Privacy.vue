<template>
  <v-container class="legal-container py-8" max-width="900">
    <v-card class="legal-card smooth-border pa-6 pa-md-8">
      <header class="mb-6">
        <h1 class="text-headline-large font-weight-bold mb-2">Privacy Policy</h1>
        <p class="legal-meta mb-0">
          Last updated: 2026-05-24 — GiljoAI LLC
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
          <li><strong>Account data</strong> — your email, display name, and authentication metadata (password hashes, session tokens).</li>
          <li><strong>Billing data</strong> — when you subscribe to a hosted paid edition, our billing provider collects payment details, billing address, and tax ID directly. We receive only your customer ID, subscription status, current period end, and invoice references — never card numbers or full payment details.</li>
          <li><strong>Product data</strong> — projects, tasks, agent missions, and messages you create inside the platform.</li>
          <li><strong>Operational logs</strong> — request logs, error traces, and audit events.</li>
          <li><strong>Browser metadata</strong> — IP address and user-agent, used for rate-limiting and security.</li>
        </ul>
      </section>

      <section class="mb-6">
        <h2 class="text-title-large mb-2">3. Where data is stored</h2>
        <p class="legal-body">
          All product data is stored in <strong>PostgreSQL</strong> on
          infrastructure operated by GiljoAI LLC. Data is scoped per tenant —
          each organization's records are isolated by tenant key on every query.
        </p>
      </section>

      <section class="mb-6">
        <h2 class="text-title-large mb-2">4. Sub-processors</h2>
        <p class="legal-body">We use the following third parties to operate the service:</p>
        <ul class="legal-list">
          <li><strong>Billing provider</strong> — Merchant of Record for paid hosted subscriptions. Handles payment collection, billing addresses, tax (VAT/sales tax/GST) calculation, invoices, refunds, and payment method storage. Billing processors are independent Data Controllers for transaction records and retain them as required for VAT, AML, and fraud-prevention obligations.</li>
          <li><strong>Resend</strong> — transactional email (registration, password reset, account-deletion confirmation).</li>
          <li><strong>Cloudflare</strong> — DNS, CDN, and DDoS protection in front of the hosted edition.</li>
          <li><strong>PostgreSQL</strong> — primary data store, hosted on GiljoAI LLC infrastructure.</li>
        </ul>
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
        <h2 class="text-title-large mb-2">6. Your rights</h2>
        <p class="legal-body">
          You can request export or permanent deletion of your account data
          at any time from <em>Account → Danger Zone</em> inside the app, or
          by emailing
          <a class="legal-link" href="mailto:admin@giljo.ai">admin@giljo.ai</a>.
          Deletion always requires email confirmation. At confirmation you
          choose the pace: immediate deletion, or an optional 30-day grace
          period during which you can still cancel the request. If you have
          an active paid subscription, confirming deletion cancels it — your
          access ends with deletion and no further charges occur; any
          remaining paid time is forfeited and is not refunded. Your data is
          then permanently purged (immediately when you waive the grace
          period, otherwise at the end of the 30-day grace), and any residual
          copy in short-lived disaster-recovery backups expires within six
          days.
        </p>
      </section>

      <section class="mb-6">
        <h2 class="text-title-large mb-2">7. Self-hosted (CE) users</h2>
        <p class="legal-body">
          If you run {{ productName }} on your own infrastructure under the
          {{ licenseName }}, this Privacy Policy does not apply — your data
          stays on your hardware and we have no access to it. This document
          covers only the hosted demo and SaaS editions.
        </p>
      </section>

      <section class="mb-6">
        <h2 class="text-title-large mb-2">8. Contact</h2>
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
import { LICENSE_NAME_FULL } from '@/i18n/licenseCopy'
import { PRODUCT_NAME } from '@/branding'

const productName = PRODUCT_NAME

const licenseName = LICENSE_NAME_FULL
</script>

<style lang="scss" scoped>
@use '@/styles/legal-typography' as legal;
@include legal.legal-typography-page;
</style>
