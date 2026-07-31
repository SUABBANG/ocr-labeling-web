import React, { useEffect, useRef, useState } from 'react'
import * as api from './api.js'
import { colorForKey } from './keycolors.js'

export default function ProjectList({ onEnter }) {
  const [projects, setProjects] = useState([])
  const [groups, setGroups] = useState([])
  const [editing, setEditing] = useState(null)       // null | {} (신규) | project (수정)
  const [editingGroup, setEditingGroup] = useState(null) // null | {} (신규) | group (수정)
  const [dropTarget, setDropTarget] = useState(undefined) // 드롭 하이라이트 대상(그룹 id | null=미분류)
  const [loading, setLoading] = useState(true)        // 첫 로드 완료 전까지 로딩 표시
  const [showKeys, setShowKeys] = useState(false)     // KEY 리스트 관리 모달
  const [expanded, setExpanded] = useState({})        // 펼친 폴더 id (기본 접힘 = 내부 숨김)
  const dragPid = useRef(null)                        // 드래그 중인 프로젝트 id

  // 일시적 실패(백엔드 --reload 재시작 등) 시 재시도 → 목록이 "0개"에 갇히지 않게.
  const refresh = (tries = 4) => Promise.all([api.listProjects(), api.listGroups()])
    .then(([ps, gs]) => { setProjects(ps); setGroups(gs); setLoading(false) })
    .catch((e) => {
      if (tries > 1) setTimeout(() => refresh(tries - 1), 600)
      else { alert('목록 로드 실패: ' + e.message); setLoading(false) }
    })
  useEffect(() => { refresh() }, [])

  const del = async (e, p) => {
    e.stopPropagation()
    if (!confirm(`"${p.title}" 프로젝트를 삭제할까요? (데이터 폴더는 유지)`)) return
    await api.deleteProject(p.id); refresh()
  }
  const delGroup = async (e, g) => {
    e.stopPropagation()
    if (!confirm(`"${g.name}" 폴더를 삭제할까요? (안의 프로젝트는 미분류로 남습니다)`)) return
    await api.deleteGroup(g.id); refresh()
  }

  // 드롭 → 프로젝트를 해당 폴더(group=null이면 미분류)로 이동
  const onDrop = async (group) => {
    setDropTarget(undefined)
    const pid = dragPid.current; dragPid.current = null
    if (!pid) return
    const cur = projects.find((p) => p.id === pid)
    if (!cur || (cur.group || null) === group) return
    try { await api.moveProject(pid, group); refresh() }
    catch (e) { alert('이동 실패: ' + e.message) }
  }
  const dropProps = (group) => ({
    onDragOver: (e) => { e.preventDefault(); if (dropTarget !== group) setDropTarget(group) },
    onDragLeave: (e) => { if (e.currentTarget === e.target) setDropTarget(undefined) },
    onDrop: () => onDrop(group),
  })

  const inGroup = (gid) => projects.filter((p) => (p.group || null) === gid)
  const ungrouped = projects.filter((p) => !p.group || !groups.some((g) => g.id === p.group))

  const card = (p) => (
    <div key={p.id} className="card" draggable
      onDragStart={() => { dragPid.current = p.id }}
      onDragEnd={() => { dragPid.current = null; setDropTarget(undefined) }}
      onClick={() => onEnter(p)}>
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
  )

  return (
    <div className="projects-wrap">
      <div className="projects-head">
        <h1>OCR 라벨링 프로젝트</h1>
        <span className="count">{loading ? '로딩 중…' : `${projects.length}개 · 폴더 ${groups.length}`}</span>
        <span style={{ flex: 1 }} />
        <button onClick={() => setShowKeys(true)}>🔑 KEY 리스트</button>
        {!loading && <button onClick={() => setEditingGroup({})}>＋ 새 폴더</button>}
      </div>

      {loading && <div className="loading">프로젝트 불러오는 중…</div>}

      {!loading && groups.map((g) => (
        <div key={g.id} className={'group-section' + (dropTarget === g.id ? ' drop-active' : '')
          + (expanded[g.id] ? ' open' : '')} {...dropProps(g.id)}>
          <div className="group-head" onClick={() => setExpanded((s) => ({ ...s, [g.id]: !s[g.id] }))}
            title={expanded[g.id] ? '접기' : '펼치기'} style={{ cursor: 'pointer' }}>
            <span className="caret">{expanded[g.id] ? '▾' : '▸'}</span>
            <span className="group-name">{expanded[g.id] ? '📂' : '📁'} {g.name}</span>
            <span className="group-count">{inGroup(g.id).length}</span>
            {g.description && <span className="group-desc">{g.description}</span>}
            <span className="group-date">{fmtDate(g.created)}</span>
            <span style={{ flex: 1 }} />
            <button onClick={(e) => { e.stopPropagation(); setEditingGroup(g) }}>편집</button>
            <button className="danger" onClick={(e) => delGroup(e, g)}>삭제</button>
          </div>
          {expanded[g.id] && (
            <div className="grid">
              {inGroup(g.id).map(card)}
              {!inGroup(g.id).length && <div className="drop-hint">여기로 프로젝트를 끌어다 놓으세요</div>}
            </div>
          )}
        </div>
      ))}

      {!loading && (
        <div className={'group-section' + (dropTarget === null ? ' drop-active' : '')} {...dropProps(null)}>
          <div className="group-head"><span className="group-name">미분류</span>
            <span className="group-count">{ungrouped.length}</span></div>
          <div className="grid">
            {ungrouped.map(card)}
            <div className="card add" onClick={() => setEditing({})}>＋ 새 프로젝트</div>
          </div>
        </div>
      )}

      {editing && (
        <ProjectForm
          project={editing.id ? editing : null}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); refresh() }}
        />
      )}
      {editingGroup && (
        <GroupForm
          group={editingGroup.id ? editingGroup : null}
          onClose={() => setEditingGroup(null)}
          onSaved={() => { setEditingGroup(null); refresh() }}
        />
      )}
      {showKeys && <KeyListManager onClose={() => setShowKeys(false)} />}
    </div>
  )
}

const KEY_TYPES = [
  { id: 'deid', label: '비식별화 대상' },
  { id: 'extract', label: 'VALUE 추출' },
]

// KEY 리스트 관리: 타입별(비식별화/VALUE추출) 추가·수정·삭제
function KeyListManager({ onClose }) {
  const [keys, setKeys] = useState(null)
  const [name, setName] = useState('')
  const [type, setType] = useState('deid')
  const [editId, setEditId] = useState(null)   // 수정 중인 key id

  const load = () => api.listKeys().then(setKeys).catch((e) => alert('KEY 로드 실패: ' + e.message))
  useEffect(() => { load() }, [])

  const submit = async () => {
    if (!name.trim()) return
    try {
      if (editId) await api.updateKey(editId, { name, type })
      else await api.createKey({ name, type })
      setName(''); setEditId(null); load()
    } catch (e) { alert('저장 실패: ' + e.message) }
  }
  const edit = (k) => { setEditId(k.id); setName(k.name); setType(k.type) }
  const del = async (k) => {
    if (!confirm(`KEY "${k.name}" 삭제할까요?`)) return
    try { await api.deleteKey(k.id); if (editId === k.id) { setEditId(null); setName('') }; load() }
    catch (e) { alert('삭제 실패: ' + e.message) }
  }

  return (
    <div className="modal-back" onClick={onClose}>
      <div className="modal keylist" onClick={(e) => e.stopPropagation()}>
        <h3>KEY 리스트</h3>
        {keys == null ? <div>불러오는 중…</div> : KEY_TYPES.map((t) => (
          <div key={t.id} className="key-group">
            <div className={'key-type-head ' + t.id}>{t.label}</div>
            {keys.filter((k) => k.type === t.id).map((k) => (
              <div key={k.id} className="key-row">
                <span className="key-dot" style={{ background: colorForKey(keys, k.name) }} />
                <span className="key-name">{k.name}</span>
                <span style={{ flex: 1 }} />
                <button onClick={() => edit(k)}>편집</button>
                <button className="danger" onClick={() => del(k)}>×</button>
              </div>
            ))}
            {!keys.some((k) => k.type === t.id) && <div className="key-empty">없음</div>}
          </div>
        ))}
        <div className="key-add">
          <select value={type} onChange={(e) => setType(e.target.value)}>
            {KEY_TYPES.map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}
          </select>
          <input value={name} onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && submit()}
            placeholder="KEY 이름" />
          <button className="primary" onClick={submit} disabled={!name.trim()}>
            {editId ? '저장' : '추가'}
          </button>
          {editId && <button onClick={() => { setEditId(null); setName('') }}>취소</button>}
        </div>
        <div className="modal-actions">
          <button onClick={onClose}>닫기</button>
        </div>
      </div>
    </div>
  )
}

const fmtDate = (iso) => (iso ? new Date(iso).toLocaleDateString() : '')

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

function GroupForm({ group, onClose, onSaved }) {
  const [name, setName] = useState(group?.name || '')
  const [description, setDescription] = useState(group?.description || '')

  const submit = async () => {
    try {
      const data = { name, description }
      if (group) await api.updateGroup(group.id, data)
      else await api.createGroup(data)
      onSaved()
    } catch (e) { alert('저장 실패: ' + e.message) }
  }

  return (
    <div className="modal-back" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h3>{group ? '폴더 편집' : '새 폴더'}</h3>
        <div className="field">
          <label>폴더명 *</label>
          <input value={name} onChange={(e) => setName(e.target.value)} autoFocus placeholder="예: 2026 계약서" />
        </div>
        <div className="field">
          <label>설명</label>
          <textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={2} placeholder="폴더 설명" />
        </div>
        <div className="modal-actions">
          <button onClick={onClose}>취소</button>
          <button className="primary" onClick={submit} disabled={!name.trim()}>
            {group ? '저장' : '생성'}
          </button>
        </div>
      </div>
    </div>
  )
}
