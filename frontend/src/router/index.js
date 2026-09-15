// @vite-ignore dynamic imports are banned — use import.meta.glob instead.

import { createRouter, createWebHistory } from 'vue-router'
import setupService from '@/services/setupService'
import configService from '@/services/configService'
import { createAuthGuard } from '@/router/authGuard'
import { isChunkLoadError, maybeReloadForChunkError } from '@/utils/chunkReload'

// eslint-disable-next-line giljo-internal/no-orphaned-exports -- consumed by tests/
export const routes = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/Login.vue'),
    meta: {
      layout: 'auth',
      title: 'Login',
      requiresAuth: false,
      requiresSetup: false,
      requiresPasswordChange: false,
    },
  },
  {
    path: '/oauth/authorize',
    name: 'OAuthAuthorize',
    component: () => import('@/views/OAuthAuthorize.vue'),
    meta: {
      layout: 'auth',
      title: 'Authorize Application',
      requiresAuth: false,
      requiresSetup: false,
      requiresPasswordChange: false,
    },
  },
  {
    path: '/welcome',
    name: 'CreateAdminAccount',
    component: () => import('@/views/CreateAdminAccount.vue'),
    meta: {
      layout: 'auth',
      title: 'Create Administrator Account',
      requiresAuth: false,
      requiresSetup: false,
    },
  },
  {
    path: '/first-login',
    name: 'FirstLogin',
    component: () => import('@/views/FirstLogin.vue'),
    meta: {
      layout: 'auth',
      title: 'Complete Account Setup',
      requiresAuth: true,
      requiresSetup: false,
      requiresPasswordChange: false,
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
    alias: '/settings',
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
      ceOrTeamOnly: true,
    },
  },
  {
    path: '/account',
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
  { path: '/tools/identity', redirect: '/admin/settings' },
  { path: '/settings/identity', redirect: '/admin/settings' },
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


router.beforeEach(createAuthGuard({ setupService, configService }))

router.onError((error, to) => {
  if (isChunkLoadError(error)) {
    maybeReloadForChunkError(to && to.fullPath)
    return
  }
  throw error
})

export default router
