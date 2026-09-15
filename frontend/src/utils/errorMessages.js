
const ERROR_MESSAGES = {
  'RESOURCE_NOT_FOUND': 'The requested item was not found',
  'RESOURCENOTFOUNDERROR': 'The requested item was not found',

  'VALIDATION_ERROR': 'Please check your input',
  'SCHEMAVALIDATIONERROR': 'The submitted data does not match the expected format',
  'DATAVALIDATIONERROR': 'One or more fields contain invalid data',

  'AUTHENTICATION_ERROR': 'Please log in again',
  'AUTHENTICATIONERROR': 'Your session has expired. Please log in again',
  'AUTHORIZATION_ERROR': 'You do not have permission to perform this action',
  'AUTHORIZATIONERROR': 'You do not have permission to perform this action',

  'TEMPLATENOTFOUNDERROR': 'The template you requested could not be found',
  'TEMPLATEVALIDATIONERROR': 'The template contains validation errors',
  'TEMPLATERENDERERROR': 'Failed to render the template',
  'TEMPLATEERROR': 'An error occurred with the template',

  'PROJECTSTATEERROR': 'Invalid state for this operation. Please check the project status',
  'PROJECTNOTFOUND': 'The project could not be found',
  'AGENTCREATIONERROR': 'Failed to create agent',
  'AGENTCOMMUNICATIONERROR': 'Failed to communicate with agent',
  'ORCHESTRATIONERROR': 'An orchestration error occurred',
  'HANDOFFERROR': 'Failed to hand off to another agent',

  'CONFIGURATIONERROR': 'A configuration error occurred',
  'CONFIGVALIDATIONERROR': 'Configuration validation failed',

  'DATABASEERROR': 'A database error occurred. Please try again',
  'DATABASECONNECTIONERROR': 'Failed to connect to database',
  'DATABASEMIGRATIONERROR': 'Database migration failed',
  'DATABASEINTEGRITYERROR': 'Database integrity constraint violated',

  'UPLOAD_TOO_LARGE': 'File is too large. Maximum size is 5 MB.',
  'UPLOAD_TYPE_NOT_ALLOWED': 'Only .txt and .md files are accepted.',
  'UPLOAD_CONTENT_NOT_TEXT': 'File does not look like plain text. Please upload a .txt or .md file.',
  'UPLOAD_FILENAME_INVALID': 'Filename contains invalid characters or is too long.',

  'HTTP_ERROR': 'A server error occurred',
  'INTERNAL_SERVER_ERROR': 'An unexpected error occurred. Please try again',

  'GITOPERATIONERROR': 'A git operation failed',
  'GITAUTHENTICATIONERROR': 'Git authentication failed',
  'GITREPOSITORYERROR': 'Git repository operation failed',

  'QUEUEEXCEPTION': 'A message queue error occurred',
  'CONSISTENCYERROR': 'A consistency check failed',
  'MESSAGEDELIVERYERROR': 'Failed to deliver message',

  'RATELIMITERROR': 'Too many requests. Please try again later',

  'CONTEXTERROR': 'A context error occurred',
  'CONTEXTLIMITERROR': 'Context size limit exceeded',
  'SESSIONERROR': 'A session error occurred',
  'SESSIONEXPIREDERROR': 'Your session has expired',

  'FILESYSTEMERROR': 'A file system error occurred',
  'FILENOTFOUNDERROR': 'The requested file was not found',
  'PERMISSIONERROR': 'Permission denied',

  'MCPERROR': 'An MCP protocol error occurred',
  'TOOLERROR': 'Tool execution failed',
  'PROTOCOLERROR': 'Protocol error occurred',

  'VISIONERROR': 'A vision document error occurred',
  'VISIONCHUNKINGERROR': 'Failed to chunk vision document',
  'VISIONPARSINGERROR': 'Failed to parse vision document',

  'RESOURCEEXHAUSTEDERROR': 'Resource limit exceeded',
  'RETRYEXHAUSTEDERROR': 'Maximum retry attempts exceeded',
}

export function getErrorMessage(errorCode, fallbackMessage = null) {
  if (!errorCode) {
    return fallbackMessage || 'An error occurred'
  }

  if (ERROR_MESSAGES[errorCode]) {
    return ERROR_MESSAGES[errorCode]
  }

  const upperCode = String(errorCode).toUpperCase()
  if (ERROR_MESSAGES[upperCode]) {
    return ERROR_MESSAGES[upperCode]
  }

  const lowerCode = String(errorCode).toLowerCase()
  const messageKey = Object.keys(ERROR_MESSAGES).find(
    key => key.toLowerCase() === lowerCode,
  )
  if (messageKey) {
    return ERROR_MESSAGES[messageKey]
  }

  return fallbackMessage || 'An error occurred'
}

export function parseErrorResponse(error) {
  if (error?.response?.data?.error_code) {
    const data = error.response.data
    return {
      errorCode: data.error_code,
      message: data.message || getErrorMessage(data.error_code),
      context: data.context || {},
      timestamp: data.timestamp,
      status: error.response.status,
      isStructured: true,
      errors: data.errors || null,
    }
  }

  if (error?.response?.data?.detail?.error_code) {
    const data = error.response.data.detail
    return {
      errorCode: data.error_code,
      message: data.message || getErrorMessage(data.error_code),
      context: data.context || {},
      timestamp: data.timestamp,
      status: error.response.status,
      isStructured: true,
      errors: data.errors || null,
    }
  }

  if (error?.response?.status === 422) {
    return {
      errorCode: 'VALIDATION_ERROR',
      message: getErrorMessage('VALIDATION_ERROR'),
      errors: error.response.data?.errors || null,
      status: 422,
      isStructured: false,
    }
  }

  if (error?.response?.data?.message) {
    return {
      errorCode: 'HTTP_ERROR',
      message: error.response.data.message,
      status: error.response?.status,
      isStructured: false,
    }
  }

  if (!error?.response) {
    return {
      errorCode: 'NETWORK_ERROR',
      message: 'Failed to connect to server. Please check your connection.',
      isStructured: false,
    }
  }

  return {
    errorCode: 'UNKNOWN_ERROR',
    message: 'An unexpected error occurred',
    isStructured: false,
  }
}

export default {
  getErrorMessage,
  parseErrorResponse,
  ERROR_MESSAGES,
}
