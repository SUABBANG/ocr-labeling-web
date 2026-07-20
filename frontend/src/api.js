// 백엔드 API 래퍼. folder는 서버 로컬 경로.
const q = (o) => new URLSearchParams(o).toString()

async function j(url, opts) {
  const r = await fetch(url, opts)
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText)
  return r.json()
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
