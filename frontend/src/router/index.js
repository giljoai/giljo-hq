// See docs/adr/ADR-002-setup-driven-mode-source-of-truth.md
// Guards must read mode from setupState.mode (setup store), not configService.getGiljoMode().
// @vite-ignore dynamic imports are banned — use import.meta.glob instead.

import { createRouter, createWebHistory } from 'vue-router'
import setupService from '@/services/setupService'
import configService from '@/services/configService'
import { createAuthGuard } from '@/router/authGuard'
import { isChunkLoadError, maybeReloadForChunkError } from '@/utils/chunkReload'

// Route definitions - views will be implemented after analyzer results
// Exported so the route table (e.g. legacy-redirect aliases) can be unit-tested
// without instantiating the router or its auth guard. See tests/unit/router/.
// eslint-disable-next-line giljo-internal/no-orphaned-exports -- consumed by tests/
export const routes = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/Login.vue'),
    meta: {
      layout: 'auth',
      title: 'Login',
      requiresAuth: false, // Public route, no auth required
      requiresSetup: false, // Skip setup check for this route
      requiresPasswordChange: false, // Skip password change check for this route
    },
  },
  {
    path: '/oauth/authorize',
    name: 'OAuthAuthorize',
    component: () => import('@/views/OAuthAuthorize.vue'),
    meta: {
      layout: 'auth',
      title: 'Authorize Application',
      requiresAuth: false, // Page handles its own auth
      requiresSetup: false, // Skip setup check for this route
      requiresPasswordChange: false, // Skip password change check for this route
    },
  },
  {
    path: '/welcome',
    name: 'CreateAdminAccount',
    component: () => import('@/views/CreateAdminAccount.vue'),
    meta: {
      layout: 'auth',
      title: 'Create Administrator Account',
      requiresAuth: false, // Public route - fresh install only
      requiresSetup: false, // Skip setup check for this route
    },
  },
  {
    path: '/first-login',
    name: 'FirstLogin',
    component: () => import('@/views/FirstLogin.vue'),
    meta: {
      layout: 'auth',
      title: 'Complete Account Setup',
      requiresAuth: true, // Requires authentication
      requiresSetup: false, // Skip setup check for this route
      requiresPasswordChange: false, // Skip password change check (this IS the password change page)
    },
  },
  {
    path: '/',
    redirect: '/home',
  },
  {
    path: '/home',
    name: 'Home',
    component: () => import('@/views/WelcomeView.vue'),
    meta: {
      layout: 'default',
      title: 'Home',
      icon: 'mdi-home',
      requiresAuth: true,
    },
  },
  {
    path: '/Dashboard',
    name: 'Dashboard',
    component: () => import('@/views/DashboardView.vue'),
    meta: {
      layout: 'default',
      title: 'Dashboard',
      icon: 'mdi-view-dashboard',
    },
  },
  {
    path: '/Products',
    name: 'Products',
    component: () => import('@/views/ProductsView.vue'),
    meta: {
      layout: 'default',
      title: 'Products',
      icon: 'mdi-package-variant',
    },
  },
  {
    path: '/products/:id',
    name: 'ProductDetail',
    component: () => import('@/views/ProductDetailView.vue'),
    meta: {
      layout: 'default',
      title: 'Product Details',
    },
  },
  {
    path: '/projects',
    name: 'Projects',
    component: () => import('@/views/ProjectsView.vue'),
    meta: {
      layout: 'default',
      title: 'Project Management',
      icon: 'mdi-folder-multiple',
    },
  },
  {
    // FE-5042: searchable 360 Memory browser. Lazy-loaded; registered
    // statically here (before createRouter) so ADR-005 holds. Sits with the
    // Projects cluster — memory is the product's cumulative project history.
    path: '/memory',
    name: 'Memory',
    component: () => import('@/views/MemoryBrowserView.vue'),
    meta: {
      layout: 'default',
      title: '360 Memory',
      icon: 'mdi-brain',
      requiresAuth: true,
    },
  },
  {
    path: '/launch',
    name: 'Launch',
    component: () => import('@/views/LaunchRedirectView.vue'),
    meta: {
      layout: 'default',
      title: 'Launch',
      requiresAuth: true,
    },
  },
  {
    // FE-9525d: the sectioned Jobs viewport -- reached when several projects
    // in the viewed product are in flight at once (single in-flight project
    // still goes straight to /projects/:projectId, unchanged). NOT `/jobs` --
    // that bare path is a pre-existing legacy-redirect alias to
    // /launch?via=jobs (jobsRedirect.spec.js pins it); this route is reached
    // by NAME (router.push({ name: 'JobsViewport' })), never by literal path,
    // so the two never collide.
    path: '/jobs-overview',
    name: 'JobsViewport',
    component: () => import('@/views/JobsViewportView.vue'),
    meta: {
      layout: 'default',
      title: 'Jobs',
      requiresAuth: true,
    },
  },
  {
    path: '/projects/:projectId',
    name: 'ProjectLaunch',
    component: () => import('@/views/ProjectLaunchView.vue'),
    meta: {
      layout: 'default',
      title: 'Project Launch',
      requiresAuth: true,
    },
  },
  {
    path: '/tasks',
    name: 'Tasks',
    component: () => import('@/views/TasksView.vue'),
    meta: {
      layout: 'default',
      title: 'Task Management',
      icon: 'mdi-clipboard-check',
    },
  },
  {
    // FE-6022b: AI-driven Roadmapping pane. Lazy-loaded; registered statically
    // here (before createRouter) so ADR-005 holds.
    path: '/roadmap',
    name: 'Roadmap',
    component: () => import('@/views/RoadmapView.vue'),
    meta: {
      layout: 'default',
      title: 'Roadmap',
      icon: 'mdi-map-marker-path',
      requiresAuth: true,
    },
  },
  {
    // FE-6054e: Agent Message Hub — BBS-style thread board with composer.
    // Registered statically before createRouter so ADR-005 holds.
    path: '/hub',
    name: 'Hub',
    component: () => import('@/views/HubView.vue'),
    meta: {
      layout: 'default',
      title: 'Message Hub',
      icon: 'mdi-forum',
      requiresAuth: true,
    },
  },
  {
    path: '/tools',
    name: 'Tools',
    alias: '/settings', // back-compat: old bookmarks, deep links, and external docs keep resolving
    component: () => import('@/views/ToolsView.vue'),
    meta: {
      layout: 'default',
      title: 'Tools',
      icon: 'mdi-tools',
      requiresAuth: true,
    },
  },
  {
    path: '/guide',
    name: 'UserGuide',
    component: () => import('@/views/UserGuideView.vue'),
    meta: {
      layout: 'default',
      title: 'User Guide',
      requiresAuth: true,
    },
  },
  {
    path: '/admin/settings',
    name: 'SystemSettings',
    component: () => import('@/views/SystemSettings.vue'),
    meta: {
      layout: 'default',
      title: 'System Settings',
      icon: 'mdi-cog-outline',
      requiresAuth: true,
      requiresAdmin: true,
      // IMP-5042: the admin panel is a CE-always surface (self-hosted operator
      // config) and, in SaaS, only meaningful once a Team tier ships. SaaS Solo
      // has no admin panel — the auth guard redirects non-CE users away.
      ceOrTeamOnly: true,
    },
  },
  {
    path: '/admin/users',
    name: 'Users',
    component: () => import('@/views/Users.vue'),
    meta: {
      layout: 'default',
      title: 'User Management',
      icon: 'mdi-account-multiple',
      requiresAuth: true,
      requiresAdmin: true,
      // IMP-5042: admin user-management is CE-always / SaaS-Team-only; the auth
      // guard redirects SaaS (non-Team) users away.
      ceOrTeamOnly: true,
    },
  },
  // Account shell with Profile / Billing / Danger sub-tabs (FE-0023).
  {
    path: '/account',
    // Named so BE-1005's saas/routes.js can nest a SaaS-only "Connected
    // Accounts" tab under this shell via the two-arg router.addRoute('AccountShell', ...)
    // form (ADR-004/005) without CE ever seeing the child route or its component.
    name: 'AccountShell',
    component: () => import('@/views/account/AccountShell.vue'),
    meta: {
      layout: 'default',
      title: 'Account',
      requiresAuth: true,
    },
    children: [
      {
        path: '',
        // Named to silence Vue Router's "empty-path child with no name"
        // warning now that the parent ('AccountShell') has a name too
        // (added for BE-1005's nested Connected-Accounts route).
        name: 'AccountIndex',
        redirect: { name: 'AccountProfile' },
      },
      {
        path: 'profile',
        name: 'AccountProfile',
        component: () => import('@/views/account/ProfilePage.vue'),
        meta: { title: 'Account · Profile', requiresAuth: true },
      },
      {
        path: 'billing',
        name: 'AccountBilling',
        component: () => import('@/views/account/BillingPage.vue'),
        meta: { title: 'Account · Billing', requiresAuth: true },
      },
      {
        path: 'danger',
        name: 'AccountDanger',
        component: () => import('@/views/account/DangerPage.vue'),
        meta: { title: 'Account · Danger Zone', requiresAuth: true },
      },
    ],
  },
  // Organization Routes (Handover 0424d)
  {
    path: '/organizations/:orgId/settings',
    name: 'OrganizationSettings',
    component: () => import('@/views/OrganizationSettings.vue'),
    meta: {
      layout: 'default',
      title: 'Organization Settings',
      icon: 'mdi-office-building',
      requiresAuth: true,
    },
  },
  {
    path: '/privacy',
    name: 'Privacy',
    component: () => import('@/views/Privacy.vue'),
    meta: {
      layout: 'auth',
      title: 'Privacy Policy',
      requiresAuth: false,
      requiresSetup: false,
      requiresPasswordChange: false,
    },
  },
  {
    path: '/terms',
    name: 'Terms',
    component: () => import('@/views/Terms.vue'),
    meta: {
      layout: 'auth',
      title: 'Terms of Service',
      requiresAuth: false,
      requiresSetup: false,
      requiresPasswordChange: false,
    },
  },
  {
    path: '/server-down',
    name: 'ServerDown',
    component: () => import('@/views/ServerDownView.vue'),
    meta: {
      layout: 'auth',
      title: 'Server Unreachable',
      requiresAuth: false,
      requiresSetup: false,
      requiresPasswordChange: false,
    },
  },
  // Legacy deep-link redirects: the Identity tab moved out of /tools to /admin/settings
  // during the FE-0023 IA reshuffle. Old bookmarks and external links to /tools/identity
  // (or its /settings alias) used to 404; redirect them to where the tab actually lives.
  { path: '/tools/identity', redirect: '/admin/settings' },
  { path: '/settings/identity', redirect: '/admin/settings' },
  // The sidebar "Jobs" link routes to /launch?via=jobs (LaunchRedirectView resolves
  // the active project, else shows the empty state); there is no bare /jobs route.
  // A stray bookmark or stale tab on /jobs used to fall to the NotFound catch-all;
  // redirect it to the same destination the nav uses so it resolves instead of 404ing.
  { path: '/jobs', redirect: '/launch?via=jobs' },
  {
    path: '/:pathMatch(.*)*',
    name: 'NotFound',
    component: () => import('@/views/NotFoundView.vue'),
    meta: {
      layout: 'default',
      title: '404 Not Found',
    },
  },
]

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes,
})

// SaaS routes are registered by frontend/src/saas/routes.js
// which calls router.addRoute() after config loads.
// CE router never imports from saas/ -- Deletion Test holds.

// Navigation guard (Handover 0034 - simplified fresh install detection;
// hardened 2026-04-24 to close the route-guard-bypass leak observed on
// mcp.example.com where typing /home in the address bar after logout rendered
// the protected view. The full guard now lives in ./authGuard.js so it can
// be unit-tested in isolation -- see tests/unit/router/authGuard.spec.js).
//
// Option A: every navigation to a protected route re-verifies the session
// by calling /api/auth/me via userStore.checkAuth(). On auth failure the
// store is reset and the user is redirected to /login.
router.beforeEach(createAuthGuard({ setupService, configService }))

// FE-6120: a lazy route component import can reject when this tab is running a
// stale build (the route chunk's hashed filename is gone after a deploy). Detect
// that specific failure and trigger a one-time guarded reload so the fresh
// index.html + new chunk hashes load and the intended route mounts. Non-chunk
// errors propagate unchanged (re-thrown) so real bugs are not swallowed.
router.onError((error, to) => {
  if (isChunkLoadError(error)) {
    maybeReloadForChunkError(to && to.fullPath)
    return
  }
  throw error
})

export default router
