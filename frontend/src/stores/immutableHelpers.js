
export function immutableMapSet(map, key, value) {
  const next = new Map(map)
  next.set(key, value)
  return next
}

export function immutableMapDelete(map, key) {
  if (!map.has(key)) return map
  const next = new Map(map)
  next.delete(key)
  return next
}

export function immutableObjectPatch(obj, patch) {
  return { ...(obj || {}), ...(patch || {}) }
}

export function immutableObjectDelete(obj, key) {
  if (!obj || !(key in obj)) return obj || {}
  const next = { ...obj }
  delete next[key]
  return next
}
