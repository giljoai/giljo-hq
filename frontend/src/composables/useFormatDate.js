export function useFormatDate() {
  function formatDate(dateString) {
    if (!dateString) return 'N/A'
    try {
      return new Date(dateString).toLocaleDateString('en-US', {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
      })
    } catch {
      return String(dateString)
    }
  }

  function formatDateTime(dateString) {
    if (!dateString) return 'N/A'
    try {
      return new Date(dateString).toLocaleDateString('en-US', {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      })
    } catch {
      return String(dateString)
    }
  }

  function formatDateWithTime(dateString) {
    if (!dateString) return 'N/A'
    try {
      const d = new Date(dateString)
      const date = d.toLocaleDateString('en-US', {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
      })
      const hh = String(d.getHours()).padStart(2, '0')
      const mm = String(d.getMinutes()).padStart(2, '0')
      return `${date} ${hh}:${mm}`
    } catch {
      return String(dateString)
    }
  }

  function formatDateCompactWithTime(dateString) {
    if (!dateString) return '—'
    try {
      const d = new Date(dateString)
      const dd = String(d.getDate()).padStart(2, '0')
      const mo = String(d.getMonth() + 1).padStart(2, '0')
      const yy = String(d.getFullYear()).slice(-2)
      const hh = String(d.getHours()).padStart(2, '0')
      const mm = String(d.getMinutes()).padStart(2, '0')
      return `${dd}/${mo}/${yy} ${hh}:${mm}`
    } catch {
      return String(dateString)
    }
  }

  function formatDateCompact(dateString) {
    if (!dateString) return '—'
    try {
      const d = new Date(dateString)
      const dd = String(d.getDate()).padStart(2, '0')
      const mm = String(d.getMonth() + 1).padStart(2, '0')
      const yy = String(d.getFullYear()).slice(-2)
      return `${dd}/${mm}/${yy}`
    } catch {
      return String(dateString)
    }
  }

  return { formatDate, formatDateTime, formatDateWithTime, formatDateCompactWithTime, formatDateCompact }
}
