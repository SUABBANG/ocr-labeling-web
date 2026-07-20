import React, { useEffect, useState } from 'react'
import * as api from './api.js'

export default function ProjectList({ onEnter }) {
  const [projects, setProjects] = useState([])
  const [editing, setEditing] = useState(null) // null | {} (신규) | project (수정)

  const refresh = () => api.listProjects().then(setProjects).catch((e) => alert('목록 로드 실패: ' + e.message))
  useEffect(() => { refresh() }, [])

  const del = async (e, p) => {
    e.stopPropagation()
    if (!confirm(`"${p.title}" 프로젝트를 삭제할까요? (데이터 폴더는 유지)`)) return
    await api.deleteProject(p.id); refresh()
  }

  return (
    <div className="projects-wrap">
      <div className="projects-head">
        <h1>OCR 라벨링 프로젝트</h1>
        <span className="count">{projects.length}개</span>
      </div>

      <div className="grid">
        {projects.map((p) => (
          <div key={p.id} className="card" onClick={() => onEnter(p)}>
            <button className="danger card-del" title="삭제" onClick={(e) => del(e, p)}>삭제</button>
            <h3>{p.title}</h3>
            <div className="desc">{p.description || '설명 없음'}</div>
            <div className="folder">📁 {p.folder}</div>
            <Progress progress={p.progress} />
            <div style={{ marginTop: 12, display: 'flex', gap: 8 }}>
              <button className="primary" onClick={(e) => { e.stopPropagation(); onEnter(p) }}>열기</button>
              <button onClick={(e) => { e.stopPropagation(); setEditing(p) }}>편집</button>
            </div>
          </div>
        ))}

        <div className="card add" onClick={() => setEditing({})}>＋ 새 프로젝트</div>
      </div>

      {editing && (
        <ProjectForm
          project={editing.id ? editing : null}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); refresh() }}
        />
      )}
    </div>
  )
}

function Progress({ progress }) {
  if (!progress || progress.total == null) return <div className="progress-label">폴더 미확인</div>
  const { total, text_done, cell_done } = progress
  const pct = total ? Math.round(((text_done + cell_done) / (total * 2)) * 100) : 0
  return (
    <>
      <div className="progress"><i style={{ width: pct + '%' }} /></div>
      <div className="progress-label">텍스트 {text_done}/{total} · 셀 {cell_done}/{total} ({pct}%)</div>
    </>
  )
}

function ProjectForm({ project, onClose, onSaved }) {
  const [title, setTitle] = useState(project?.title || '')
  const [description, setDescription] = useState(project?.description || '')
  const [folder, setFolder] = useState(project?.folder || '')

  const submit = async () => {
    try {
      const data = { title, description, folder }
      if (project) await api.updateProject(project.id, data)
      else await api.createProject(data)
      onSaved()
    } catch (e) { alert('저장 실패: ' + e.message) }
  }

  return (
    <div className="modal-back" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h3>{project ? '프로젝트 편집' : '새 프로젝트'}</h3>
        <div className="field">
          <label>제목 *</label>
          <input value={title} onChange={(e) => setTitle(e.target.value)} autoFocus placeholder="예: 계약서 OCR" />
        </div>
        <div className="field">
          <label>설명</label>
          <textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={2} placeholder="프로젝트 설명" />
        </div>
        <div className="field">
          <label>데이터 폴더 경로 (서버 기준) *</label>
          <input value={folder} onChange={(e) => setFolder(e.target.value)} placeholder="C:\data\contracts" />
        </div>
        <div className="modal-actions">
          <button onClick={onClose}>취소</button>
          <button className="primary" onClick={submit} disabled={!title.trim() || !folder.trim()}>
            {project ? '저장' : '생성'}
          </button>
        </div>
      </div>
    </div>
  )
}
