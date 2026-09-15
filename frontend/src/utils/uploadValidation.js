
// eslint-disable-next-line giljo-internal/no-orphaned-exports -- imported in tests/unit/utils/uploadValidation.spec.js (outside src/)
export const MAX_UPLOAD_BYTES = 5 * 1024 * 1024
// eslint-disable-next-line giljo-internal/no-orphaned-exports -- imported in tests/unit/utils/uploadValidation.spec.js (outside src/)
export const ALLOWED_UPLOAD_EXTENSIONS = ['.txt', '.md', '.markdown']

function getExtension(filename) {
  if (!filename || typeof filename !== 'string') return ''
  const dotIndex = filename.lastIndexOf('.')
  if (dotIndex === -1 || dotIndex === filename.length - 1) return ''
  return filename.slice(dotIndex).toLowerCase()
}

// eslint-disable-next-line giljo-internal/no-orphaned-exports -- imported in tests/unit/utils/uploadValidation.spec.js (outside src/)
export function validateUploadFile(file) {
  if (!file || typeof file.name !== 'string' || file.name.trim() === '') {
    return {
      valid: false,
      errorCode: 'UPLOAD_FILENAME_INVALID',
      message: 'Filename contains invalid characters or is empty.',
    }
  }

  const ext = getExtension(file.name)
  if (!ALLOWED_UPLOAD_EXTENSIONS.includes(ext)) {
    return {
      valid: false,
      errorCode: 'UPLOAD_TYPE_NOT_ALLOWED',
      message: 'Only .txt and .md files are accepted.',
    }
  }

  if (typeof file.size === 'number' && file.size > MAX_UPLOAD_BYTES) {
    return {
      valid: false,
      errorCode: 'UPLOAD_TOO_LARGE',
      message: 'File is too large. Maximum size is 5 MB.',
    }
  }

  return { valid: true, errorCode: null, message: null }
}

export function validateUploadFiles(files) {
  if (!files || files.length === 0) {
    return { valid: true, invalid: [] }
  }

  const invalid = []
  for (const file of files) {
    const result = validateUploadFile(file)
    if (!result.valid) {
      invalid.push({
        file,
        errorCode: result.errorCode,
        message: result.message,
      })
      break
    }
  }

  return { valid: invalid.length === 0, invalid }
}
