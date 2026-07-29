import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import * as api from './api.js'
import Editor from './Editor.jsx'
import { loadShortcuts, matchAction, ShortcutSettings } from './shortcuts.jsx'

export default function Labeler({ project, onExit }) {
  const folder = project.folder
  const [images, setImages] = useState([])
  const [name, setName] = useState(null)
  const [label, setLabel] = useState(null)
  const [selectedId, setSelectedId] = useState(null)
  const [newMode, setNewMode] = useState(false)
  const [mode, setMode] = useState('text')   // 'text' | 'cell' — 라벨링 종류
  const [editShape, setEditShape] = useState('bbox') // 'bbox'(사각형 유지) | 'poly'(꼭짓점)
  const [panMode, setPanMode] = useState(false)
  const [engine, setEngine] = useState('llm')
  const [busy, setBusy] = useState('')
  const [dirty, setDirty] = useState(false)
  const [autoSave, setAutoSave] = useState(() => localStorage.getItem('autoSave') === '1')
  const [showSettings, setShowSettings] = useState(false)
  const [keys, setKeys] = useState(loadShortcuts)
  const [leftW, setLeftW] = useState(232)     // 좌 사이드바 폭
  const [rightW, setRightW] = useState(280)   // 우 사이드바 폭
  const editorRef = useRef(null)
  const wordInputs = useRef({})
  const rowRefs = useRef({})                  // 우 패널 각 행 (선택 시 자동 스크롤)
  const dragId = useRef(null)                 // 드래그 중인 워드 id

  // 현재 모드가 쓰는 라벨 배열 키: 텍스트='words', 테이블셀='cells'
  const wkey = mode === 'cell' ? 'cells' : 'words'

  // 순서 변경: fromId를 toId 위치로 이동 (현재 모드 배열 기준)
  const moveWord = (fromId, toId) => {
    if (!fromId || fromId === toId) return
    pushHistory(); endTextSession()
    setLabel((l) => {
      const arr = [...(l[wkey] || [])]
      const fi = arr.findIndex((w) => w.id === fromId)
      if (fi < 0) return l
      const [item] = arr.splice(fi, 1)
      const ti = arr.findIndex((w) => w.id === toId)
      if (ti < 0) return l
      arr.splice(ti, 0, item)
      return { ...l, [wkey]: arr }
    })
    setDirty(true)
  }

  // 박스 선택 시 우측 단어 패널을 해당 행으로 스크롤
  useEffect(() => {
    if (selectedId) rowRefs.current[selectedId]?.scrollIntoView({ block: 'nearest' })
  }, [selectedId])

  // 사이드바 리사이즈 (드래그)
  const startResize = (which) => (e) => {
    e.preventDefault()
    const onMove = (ev) => {
      if (which === 'left') setLeftW(Math.max(150, Math.min(500, ev.clientX)))
      else setRightW(Math.max(180, Math.min(600, window.innerWidth - ev.clientX)))
    }
    const onUp = () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
      document.body.style.cursor = ''
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    document.body.style.cursor = 'col-resize'
  }
  const historyRef = useRef([])       // 실행취소 스택 (label JSON 스냅샷)
  const labelRef = useRef(null)       // 최신 label (stale closure 방지)
  const textSession = useRef(null)    // 연속 텍스트 편집 1스텝으로 묶기
  labelRef.current = label

  const pushHistory = useCallback(() => {
    if (!labelRef.current) return
    historyRef.current.push(JSON.stringify(labelRef.current))
    if (historyRef.current.length > 100) historyRef.current.shift()
  }, [])
  const endTextSession = () => { textSession.current = null }
  const undo = useCallback(() => {
    const prev = historyRef.current.pop()
    if (prev == null) return
    setLabel(JSON.parse(prev)); setSelectedId(null); setNewMode(false)
    setDirty(true); textSession.current = null
  }, [])

  const textDone = useMemo(() => images.filter((i) => i.text_done).length, [images])
  const cellDone = useMemo(() => images.filter((i) => i.cell_done).length, [images])
  // 현재 모드의 박스만 표시/편집 (텍스트=words, 셀=cells)
  const visibleWords = useMemo(() => label?.[wkey] || [], [label, wkey])

  useEffect(() => {
    api.listImages(folder).then(setImages).catch((e) => alert('폴더 조회 실패: ' + e.message))
  }, [folder])

  const save = useCallback(async () => {
    if (!label || !name) return
    // id를 배열 순서대로 재번호(words=w1.., cells=c1..) → JSON id가 순서를 반영
    const idMap = {}
    const words = (label.words || []).map((w, i) => { idMap[w.id] = `w${i + 1}`; return { ...w, id: `w${i + 1}` } })
    const cells = (label.cells || []).map((c, i) => { idMap[c.id] = `c${i + 1}`; return { ...c, id: `c${i + 1}` } })
    const next = { ...label, words, cells }
    try {
      await api.putLabel(folder, name, next)
      setLabel(next)
      setSelectedId((sid) => (sid ? idMap[sid] || null : null))
      setDirty(false)
      setImages((xs) => xs.map((i) => i.name === name
        ? { ...i, has_label: true, text_done: !!next.text_done, cell_done: !!next.cell_done } : i))
    } catch (e) { alert('저장 실패: ' + e.message) }
  }, [folder, name, label])

  const selectImage = useCallback(async (n) => {
    if (autoSave && dirty) await save()   // 자동저장 ON: 페이지 전환 전 현재 라벨 저장
    setName(n); setSelectedId(null); setNewMode(false)
    historyRef.current = []; textSession.current = null   // 이미지 넘어가면 히스토리 초기화
    try { setLabel(await api.getLabel(folder, n)); setDirty(false) }
    catch (e) { alert('라벨 로드 실패: ' + e.message) }
  }, [folder, autoSave, dirty, save])

  const runModel = useCallback(async () => {
    if (!name) return
    setBusy('모델 실행 중…')
    pushHistory(); endTextSession()   // 모델 결과로 덮기 전 상태 저장 → 취소 가능
    try {
      // 테이블셀 탭은 로컬 모델만 지원 → 셀 검출로 라우팅(engine 무시)
      const draft = await api.runModel(folder, name, engine, mode)
      setLabel(draft); setDirty(true); setSelectedId(null)
      setImages((xs) => xs.map((i) => i.name === name ? { ...i, has_label: true } : i))
    } catch (e) { alert('모델 실행 실패: ' + e.message) }
    finally { setBusy('') }
  }, [folder, name, engine, mode])

  const changeWord = (id, poly) => {
    // 히스토리는 드래그 시작(onEditStart)에서 1회 저장 — 여기선 저장하지 않음
    setLabel((l) => ({ ...l, [wkey]: (l[wkey] || []).map((w) => w.id === id ? { ...w, poly } : w) }))
    setDirty(true)
  }
  const changeText = (id, text) => {
    if (textSession.current !== id) { pushHistory(); textSession.current = id } // 연속 입력 1스텝
    setLabel((l) => ({ ...l, words: l.words.map((w) => w.id === id ? { ...w, text } : w) }))
    setDirty(true)
  }
  const deleteWord = (id) => {
    pushHistory(); endTextSession()
    setLabel((l) => ({ ...l, [wkey]: (l[wkey] || []).filter((w) => w.id !== id) }))
    setSelectedId(null); setDirty(true)
  }
  const addWord = (poly) => {
    pushHistory(); endTextSession()
    const id = (mode === 'cell' ? 'c' : 'w') + Date.now()
    const item = mode === 'cell'
      ? { id, kind: 'cell', poly }
      : { id, text: '', poly, script: 'printed' }   // 기본 인쇄
    setLabel((l) => ({ ...l, [wkey]: [...(l[wkey] || []), item] }))
    setSelectedId(id); setNewMode(false); setDirty(true)
  }
  const toggleScript = (id) => {   // 인쇄 ↔ 필기
    pushHistory(); endTextSession()
    setLabel((l) => ({
      ...l,
      words: l.words.map((w) => w.id === id
        ? { ...w, script: w.script === 'handwriting' ? 'printed' : 'handwriting' } : w),
    }))
    setDirty(true)
  }
  const toggleType = (id) => {   // 없음 → key → value → 없음
    const next = { undefined: 'key', key: 'value', value: undefined }
    pushHistory(); endTextSession()
    setLabel((l) => ({
      ...l,
      words: l.words.map((w) => w.id === id ? { ...w, type: next[w.type] } : w),
    }))
    setDirty(true)
  }
  const deleteAllVisible = () => {
    if (!visibleWords.length) return
    if (!confirm(`현재 모드(${mode === 'cell' ? '테이블셀' : '텍스트'}) 박스 ${visibleWords.length}개를 모두 삭제할까요?`)) return
    pushHistory(); endTextSession()
    setLabel((l) => ({ ...l, [wkey]: [] }))
    setSelectedId(null); setDirty(true)
  }
  const switchMode = (m) => { setMode(m); setSelectedId(null); setNewMode(false); endTextSession() }

  const deleteImg = async (e, n) => {
    e.stopPropagation()
    if (!confirm(`${n} 이미지와 라벨을 삭제할까요?`)) return
    try {
      await api.deleteImage(folder, n)
      setImages((xs) => xs.filter((i) => i.name !== n))
      if (name === n) { setName(null); setLabel(null); setSelectedId(null) }
    } catch (e2) { alert('삭제 실패: ' + e2.message) }
  }

  const toggleDone = useCallback(async (kind) => {   // kind: 'text' | 'cell'
    if (!label || !name) return
    const k = kind === 'cell' ? 'cell_done' : 'text_done'
    const next = { ...label, [k]: !label[k] }
    setLabel(next)
    try {
      await api.putLabel(folder, name, next)
      setImages((xs) => xs.map((i) => i.name === name ? { ...i, [k]: next[k] } : i))
    } catch (e) { alert('저장 실패: ' + e.message) }
  }, [folder, name, label])

  const moveImage = useCallback((delta) => {
    if (!images.length) return
    const idx = images.findIndex((i) => i.name === name)
    const next = images[Math.max(0, Math.min(images.length - 1, idx + delta))]
    if (next) selectImage(next.name)
  }, [images, name, selectImage])

  useEffect(() => {
    const editing = () => ['INPUT', 'TEXTAREA'].includes(document.activeElement?.tagName)
    const onKeyDown = (e) => {
      if (e.code === 'Space' && !editing()) { e.preventDefault(); setPanMode(true); return }
      const action = matchAction(keys, e)
      if (editing()) {
        // 입력 중에도 저장은 동작 + 브라우저 기본동작(다른 이름으로 저장) 차단
        if (action === 'save') { e.preventDefault(); save(); return }
        if (action === 'cancel') document.activeElement.blur()
        return
      }
      if (!action) return
      const handlers = {
        prevImage: () => moveImage(-1),
        nextImage: () => moveImage(1),
        editText: () => selectedId && wordInputs.current[selectedId]?.focus(),
        cancel: () => { setSelectedId(null); setNewMode(false) },
        deleteBox: () => selectedId && deleteWord(selectedId),
        newBox: () => setNewMode((v) => !v),
        save,
        runModel,
        fit: () => editorRef.current?.fit(),
        reset100: () => editorRef.current?.reset100(),
        toggleDone: () => toggleDone(mode),   // 현재 모드(text/cell) 완료 토글
        toggleEditShape: () => setEditShape((s) => (s === 'bbox' ? 'poly' : 'bbox')),
        advance: () => moveImage(1),
        cycleType: () => mode === 'text' && selectedId && toggleType(selectedId),
        undo,
      }
      if (handlers[action]) { e.preventDefault(); handlers[action]() }
    }
    const onKeyUp = (e) => { if (e.code === 'Space') setPanMode(false) }
    window.addEventListener('keydown', onKeyDown)
    window.addEventListener('keyup', onKeyUp)
    return () => {
      window.removeEventListener('keydown', onKeyDown)
      window.removeEventListener('keyup', onKeyUp)
    }
  }, [keys, selectedId, newMode, mode, moveImage, save, runModel, toggleDone, undo])

  return (
    <div className="labeler">
      <div className="appbar">
        <button onClick={onExit}>← 프로젝트</button>
        <span className="brand">{project.title}</span>
        <span className="sub">{name || '이미지를 선택하세요'}</span>
        <span className="spacer" />
        <div className="toolbar">
          <div className="mode-tabs">
            <button className={mode === 'text' ? 'active' : ''} onClick={() => switchMode('text')}>텍스트</button>
            <button className={mode === 'cell' ? 'active cell' : ''} onClick={() => switchMode('cell')}>테이블셀</button>
          </div>
          <select value={engine} onChange={(e) => setEngine(e.target.value)}>
            <option value="llm">LLM</option>
            <option value="local">로컬 모델</option>
          </select>
          <button onClick={runModel} disabled={!name || busy}
            title={`모델 실행 (단축키 ${keys.runModel})`}>모델 실행</button>
          <button className="primary" onClick={save} disabled={!dirty}
            title={`저장 (단축키 ${keys.save})`}>저장{dirty ? ' *' : ''}</button>
          <label className="autosave" title="ON이면 다른 이미지로 넘어갈 때 자동 저장">
            <input type="checkbox" checked={autoSave}
              onChange={(e) => { setAutoSave(e.target.checked); localStorage.setItem('autoSave', e.target.checked ? '1' : '0') }} />
            자동저장
          </label>
          <button className={newMode ? (mode === 'cell' ? 'toggle-cell' : 'toggle-on') : ''}
            title={`박스 그리기/선택 전환 (단축키 ${keys.newBox})`}
            onClick={() => setNewMode((v) => !v)}>＋{mode === 'cell' ? '셀' : '텍스트'} 그리기</button>
          <button className="edit-shape" title="편집 모드 전환 (단축키 B)"
            onClick={() => setEditShape((s) => (s === 'bbox' ? 'poly' : 'bbox'))}>
            편집: {editShape === 'bbox' ? '□ bbox' : '◇ poly'}
          </button>
          <button onClick={undo} title="실행 취소 (Ctrl+Z)">↶ 취소</button>
          <button className="danger" onClick={deleteAllVisible} title="현재 모드 박스 모두 삭제">모두 삭제</button>
          <button onClick={() => setShowSettings(true)}>⌨ 단축키</button>
        </div>
      </div>

      <div className="workspace">
        <div className="side left" style={{ width: leftW }}>
          <div className="side-head">완료 텍스트 {textDone} · 셀 {cellDone} / {images.length}</div>
          {images.map((im) => (
            <div key={im.name} className={'img-row' + (im.name === name ? ' active' : '')}
              onClick={() => selectImage(im.name)}>
              <input className="chk-text" type="checkbox" title="텍스트박스 완료" checked={im.text_done} readOnly
                onClick={(e) => { e.stopPropagation(); if (im.name === name) toggleDone('text') }} />
              <input className="chk-cell" type="checkbox" title="테이블셀 완료" checked={im.cell_done} readOnly
                onClick={(e) => { e.stopPropagation(); if (im.name === name) toggleDone('cell') }} />
              <span className="name">{im.name}</span>
              {im.has_label && <span className="dot">●</span>}
              <button className="danger" title="삭제" onClick={(e) => deleteImg(e, im.name)}>×</button>
            </div>
          ))}
        </div>

        <div className="resizer" onMouseDown={startResize('left')} />

        <div className="canvas-area">
          {name && (
            <Editor
              ref={editorRef}
              imageUrl={api.imageUrl(folder, name)}
              words={visibleWords}
              selectedId={selectedId}
              onSelect={setSelectedId}
              onChangeWord={changeWord}
              onEditStart={() => { pushHistory(); endTextSession() }}
              onNewBox={addWord}
              newMode={newMode}
              panMode={panMode}
              editShape={editShape}
            />
          )}
          {busy && <div className="badge">{busy}</div>}
        </div>

        <div className="resizer" onMouseDown={startResize('right')} />

        <div className="side right" style={{ width: rightW }}>
          <div className="side-head">
            {mode === 'cell' ? '테이블 셀' : '텍스트'} {visibleWords.length}개{label?.source ? ` · ${label.source}` : ''}
          </div>
          <div style={{ padding: 6 }}>
            {visibleWords.map((w) => (
              <div key={w.id} ref={(el) => { rowRefs.current[w.id] = el }}
                className={'word-row' + (w.id === selectedId ? ' active' : '')}
                onClick={() => setSelectedId(w.id)}
                onDragOver={(e) => e.preventDefault()}
                onDrop={() => moveWord(dragId.current, w.id)}>
                <span className="drag-handle" draggable
                  onDragStart={() => { dragId.current = w.id }}
                  onClick={(e) => e.stopPropagation()} title="드래그로 순서 변경">⠿</span>
                {w.kind === 'cell' ? (
                  <span className="cell-tag">［테이블 셀］</span>
                ) : (
                  <>
                    <button className={'script-btn' + (w.script === 'handwriting' ? ' hw' : '')}
                      title="인쇄/필기 전환" onClick={(e) => { e.stopPropagation(); toggleScript(w.id) }}>
                      {w.script === 'handwriting' ? '필' : '인'}
                    </button>
                    <button className={'kv-btn' + (w.type ? ' ' + w.type : '')}
                      title="key/value 전환" onClick={(e) => { e.stopPropagation(); toggleType(w.id) }}>
                      {w.type === 'key' ? 'K' : w.type === 'value' ? 'V' : '·'}
                    </button>
                    <input ref={(el) => { wordInputs.current[w.id] = el }}
                      className={w.type ? 'kv-' + w.type : ''} value={w.text}
                      onChange={(e) => changeText(w.id, e.target.value)}
                      onFocus={() => setSelectedId(w.id)} />
                  </>
                )}
                <button className="danger" onClick={() => deleteWord(w.id)}>×</button>
              </div>
            ))}
          </div>
        </div>
      </div>

      {showSettings && (
        <ShortcutSettings map={keys} onChange={setKeys} onClose={() => setShowSettings(false)} />
      )}
    </div>
  )
}
