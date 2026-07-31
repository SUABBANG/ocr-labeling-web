// 백엔드 API 래퍼. folder는 서버 로컬 경로.
const q = (o) => new URLSearchParams(o).toString()

// 진행 중 요청 수를 구독 → 지연 시 상단 로딩 바 표시(모든 API 호출이 j를 거침)
let _active = 0
const _subs = new Set()
export const onLoading = (cb) => { _subs.add(cb); return () => _subs.delete(cb) }
const _emit = () => _subs.forEach((cb) => cb(_active))

async function j(url, opts) {
  _active++; _emit()
  try {
    const r = await fetch(url, opts)
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText)
    return await r.json()
  } finally { _active--; _emit() }
}

export const listImages = (folder) => j(`/api/images?${q({ folder })}`)
export const getLabel = (folder, name) => j(`/api/label?${q({ folder, name })}`)
export const imageUrl = (folder, name) => `/api/image?${q({ folder, name })}`

export const putLabel = (folder, name, data) =>
  j(`/api/label?${q({ folder, name })}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })

export const runModel = (folder, name, engine, mode) =>
  j(`/api/model?${q({ folder, name, engine, mode })}`, { method: 'POST' })

export const deleteImage = (folder, name) =>
  j(`/api/image?${q({ folder, name })}`, { method: 'DELETE' })

// --- 프로젝트 ---
const jbody = (url, method, data) =>
  j(url, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) })

export const listProjects = () => j('/api/projects')
export const createProject = (data) => jbody('/api/projects', 'POST', data)
export const updateProject = (id, data) => jbody(`/api/projects/${id}`, 'PUT', data)
export const deleteProject = (id) => j(`/api/projects/${id}`, { method: 'DELETE' })
export const moveProject = (id, group) => jbody(`/api/projects/${id}/group`, 'PUT', { group })

// --- KEY 리스트 (KEY/VALUE 라벨링용) ---
export const listKeys = () => j('/api/keylist')
export const createKey = (data) => jbody('/api/keylist', 'POST', data)
export const updateKey = (id, data) => jbody(`/api/keylist/${id}`, 'PUT', data)
export const deleteKey = (id) => j(`/api/keylist/${id}`, { method: 'DELETE' })

// --- 프로젝트 폴더(그룹) ---
export const listGroups = () => j('/api/groups')
export const createGroup = (data) => jbody('/api/groups', 'POST', data)
export const updateGroup = (id, data) => jbody(`/api/groups/${id}`, 'PUT', data)
export const deleteGroup = (id) => j(`/api/groups/${id}`, { method: 'DELETE' })
