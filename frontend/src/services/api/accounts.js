
export const createUsersApi = (apiClient) => ({
  update: (userId, updates) => apiClient.patch(`/api/v1/users/${userId}`, updates),
  getFieldToggleConfig: () => apiClient.get('/api/v1/users/me/field-priority'),
})

export const createAccountApi = (apiClient) => ({
  exportMyData: () => apiClient.post('/api/v1/account/export'),
})

export const createAuthApi = (apiClient) => ({
  login: (username, password) => apiClient.post('/api/auth/login', { username, password }),
  logout: () => apiClient.post('/api/auth/logout'),
  me: () => apiClient.get('/api/auth/me'),
  register: (data) => apiClient.post('/api/auth/register', data),
  createFirstAdmin: (data) => apiClient.post('/api/auth/create-first-admin', data),
  listUsers: () => apiClient.get('/api/v1/users/'),
  updateUser: (userId, data) => apiClient.put(`/api/v1/users/${userId}`, data),
  changePassword: (userId, data) => apiClient.put(`/api/v1/users/${userId}/password`, data),
  checkFirstLogin: (username) => apiClient.post('/api/auth/check-first-login', { username }),
  completeFirstLogin: (data) => apiClient.post('/api/auth/complete-first-login', data),
  verifyPin: (data) => apiClient.post('/api/auth/verify-pin', data),
  verifyPinAndResetPassword: (data) =>
    apiClient.post('/api/auth/verify-pin-and-reset-password', data),
  updateSetupState: (payload) => apiClient.patch('/api/auth/me/setup-state', payload),
})

export const createApiKeysApi = (apiClient) => ({
  list: () => apiClient.get('/api/auth/api-keys'),
  getActive: () => apiClient.get('/api/auth/api-keys/active'),
  create: (name) => apiClient.post('/api/auth/api-keys', { name }),
  delete: (keyId) => apiClient.delete(`/api/auth/api-keys/${keyId}`),
})

export const createConnectedAppsApi = (apiClient) => ({
  list: () => apiClient.get('/api/auth/connected-apps'),
  logOut: (loginId) => apiClient.delete(`/api/auth/connected-apps/${loginId}`),
  logOutAll: () => apiClient.delete('/api/auth/connected-apps'),
})

export const createConnectApi = (apiClient) => ({
  credentialStatus: () => apiClient.get('/api/connect/credential-status'),
  removeConnection: (harness) => apiClient.delete(`/api/connect/connections/${harness}`),
})

export const createOrganizationsApi = (apiClient) => ({
  list: () => apiClient.get('/api/organizations'),
  get: (orgId) => apiClient.get(`/api/organizations/${orgId}`),
  create: (data) => apiClient.post('/api/organizations', data),
  update: (orgId, data) => apiClient.put(`/api/organizations/${orgId}`, data),
  delete: (orgId) => apiClient.delete(`/api/organizations/${orgId}`),
  listMembers: (orgId) => apiClient.get(`/api/organizations/${orgId}/members`),
  inviteMember: (orgId, data) => apiClient.post(`/api/organizations/${orgId}/members`, data),
  changeMemberRole: (orgId, userId, data) =>
    apiClient.put(`/api/organizations/${orgId}/members/${userId}`, data),
  removeMember: (orgId, userId) =>
    apiClient.delete(`/api/organizations/${orgId}/members/${userId}`),
  transferOwnership: (orgId, data) =>
    apiClient.post(`/api/organizations/${orgId}/transfer`, data),
})
