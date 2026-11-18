
const DEFAULT_SCOPE = 'mcp:read mcp:write'

const SCOPE_COPY = {
  'mcp:read': {
    label: 'See your work',
    description: 'Read your products, projects, tasks, memory and agent activity.',
    icon: 'mdi-eye-outline',
  },
  'mcp:write': {
    label: 'Change your work',
    description: 'Create and update your products, projects, tasks and memory.',
    icon: 'mdi-pencil-outline',
  },
  'mcp:agent': {
    label: 'Run agents for you',
    description: 'Start and coordinate agents, send messages in threads, and move projects and jobs through their steps.',
    icon: 'mdi-robot-outline',
  },
  mcp: {
    label: 'Use tools',
    description: 'Run tools and read resources in your account.',
    icon: 'mdi-connection',
  },
  read: {
    label: 'See your work',
    description: 'Read data in your account.',
    icon: 'mdi-eye-outline',
  },
  write: {
    label: 'Change your work',
    description: 'Change data in your account.',
    icon: 'mdi-pencil-outline',
  },
}

export function describeScopes(scopeString) {
  const scopes = (scopeString || DEFAULT_SCOPE).split(' ').filter(Boolean)
  return scopes.map((scope) => {
    const copy = SCOPE_COPY[scope]
    if (copy) return { scope, ...copy }
    return { scope, label: scope, description: `Access: ${scope}`, icon: 'mdi-key-outline' }
  })
}
