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
  // KEY/VALUE 그리기: null=다음 박스는 새 item의 key, <itemId>=다음 박스는 그 item의 value
  const [pendingValue, setPendingValue] = useState(null)
  const [mode, setMode] = useState('text')   // 'text' | 'cell' | 'item' — 라벨링 종류
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

  // 현재 모드가 쓰는 라벨 배열 키: 텍스트='words', 테이블셀='cells', KEY/VALUE='item'
  const wkey = mode === 'cell' ? 'cells' : mode === 'item' ? 'item' : 'words'
  // id 접두어로 소속 배열 판별 (w=words, c=cells, i=item)
  const keyOf = (id) => (id?.[0] === 'i' ? 'item' : id?.[0] === 'c' ? 'cells' : 'words')

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
  const itemDone = useMemo(() => images.filter((i) => i.item_done).length, [images])
  // 현재 모드의 박스만 표시/편집 (텍스트=words, 셀=cells, KEY/VALUE=item)
  const visibleWords = useMemo(() => label?.[wkey] || [], [label, wkey])
  const items = useMemo(() => label?.item || [], [label])   // KEY/VALUE 쌍 목록
  // 캔버스용: item(key+value 중첩)을 개별 박스로 평탄화. 박스 id = <itemId>k | <itemId>v<idx>
  const editorBoxes = useMemo(() => {
    if (mode !== 'item') return visibleWords
    return items.flatMap((it) => {
      const boxes = it.key?.poly ? [{ id: it.id + 'k', type: 'key', poly: it.key.poly }] : []
      ;(it.value || []).forEach((v, i) => boxes.push({ id: it.id + 'v' + i, type: 'value', poly: v.poly }))
      return boxes
    })
  }, [mode, visibleWords, items])
  // 평탄화 박스 id 파싱 → { itemId, part:'key'|'value', vi }
  const parseItemBox = (id) => {
    const mv = /^(i\d+)v(\d+)$/.exec(id)
    if (mv) return { itemId: mv[1], part: 'value', vi: +mv[2] }
    const mk = /^(i\d+)k$/.exec(id)
    if (mk) return { itemId: mk[1], part: 'key' }
    return null
  }

  useEffect(() => {
    api.listImages(folder).then(setImages).catch((e) => alert('폴더 조회 실패: ' + e.message))
  }, [folder])

  const save = useCallback(async () => {
    const label = labelRef.current   // 최신 label(완료 토글 등)을 stale 클로저 대신 ref로 읽음
    if (!label || !name) return
    // id를 배열 순서대로 재번호(words=w1.., cells=c1..) → JSON id가 순서를 반영
    const idMap = {}
    const words = (label.words || []).map((w, i) => { idMap[w.id] = `w${i + 1}`; return { ...w, id: `w${i + 1}` } })
    const cells = (label.cells || []).map((c, i) => { idMap[c.id] = `c${i + 1}`; return { ...c, id: `c${i + 1}` } })
    const item = (label.item || []).map((t, i) => { idMap[t.id] = `i${i + 1}`; return { ...t, id: `i${i + 1}` } })
    const next = { ...label, words, cells, item }
    try {
      await api.putLabel(folder, name, next)
      setLabel(next); labelRef.current = next
      setSelectedId((sid) => (sid ? idMap[sid] || null : null))
      setDirty(false)
      setImages((xs) => xs.map((i) => i.name === name
        ? { ...i, has_label: true, text_done: !!next.text_done, cell_done: !!next.cell_done, item_done: !!next.item_done } : i))
    } catch (e) { alert('저장 실패: ' + e.message) }
  }, [folder, name])

  const selectImage = useCallback(async (n) => {
    if (autoSave && dirty) await save()   // 자동저장 ON: 페이지 전환 전 현재 라벨 저장
    setName(n); setSelectedId(null); setNewMode(false); setPendingValue(null)
    historyRef.current = []; textSession.current = null   // 이미지 넘어가면 히스토리 초기화
    try { setLabel(await api.getLabel(folder, n)); setDirty(false) }
    catch (e) { alert('라벨 로드 실패: ' + e.message) }
  }, [folder, autoSave, dirty, save])

  const runModel = useCallback(async () => {
    if (!name || mode === 'item') return   // KEY/VALUE 탭은 모델 미지원(수동)
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
    // 히스토리는 드래그 시작(onEditStart)에서 1회 저장 — 여기선 저장하지 않음.
    const b = id[0] === 'i' ? parseItemBox(id) : null
    if (b) {   // KEY/VALUE 박스: item 내부 key/value의 poly 갱신
      setLabel((l) => ({ ...l, item: l.item.map((it) => it.id !== b.itemId ? it
        : b.part === 'key' ? { ...it, key: { ...it.key, poly } }
          : { ...it, value: it.value.map((v, i) => i === b.vi ? { ...v, poly } : v) }) }))
      setDirty(true); return
    }
    const k = keyOf(id)
    setLabel((l) => ({ ...l, [k]: (l[k] || []).map((w) => w.id === id ? { ...w, poly } : w) }))
    setDirty(true)
  }
  const changeText = (id, text) => {
    if (textSession.current !== id) { pushHistory(); textSession.current = id } // 연속 입력 1스텝
    setLabel((l) => {
      const words = l.words.map((w) => w.id === id ? { ...w, text } : w)
      // 이 word를 포함하는 key/value 박스의 text 재수집(그 word를 쓰는 KEY/VALUE도 함께 갱신)
      const w = words.find((x) => x.id === id)
      const c = w && boxCenter(w.poly)
      const item = c ? (l.item || []).map((it) => ({
        ...it,
        key: it.key && contains(it.key.poly, c) ? { ...it.key, text: collectFrom(words, it.key.poly) } : it.key,
        value: (it.value || []).map((v) => contains(v.poly, c) ? { ...v, text: collectFrom(words, v.poly) } : v),
      })) : l.item
      return { ...l, words, item }
    })
    setDirty(true)
  }
  const deleteWord = (id) => {
    const b = id[0] === 'i' ? parseItemBox(id) : null
    if (b) { b.part === 'key' ? deleteItem(b.itemId) : deleteValue(b.itemId, b.vi); return }
    pushHistory(); endTextSession()
    const k = keyOf(id)
    setLabel((l) => ({ ...l, [k]: (l[k] || []).filter((w) => w.id !== id) }))
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
  // poly(사각형) 바운딩박스 [x1,y1,x2,y2] 와 중심 [cx,cy]
  const rectOf = (poly) => {
    const xs = poly.map((p) => p[0]); const ys = poly.map((p) => p[1])
    return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)]
  }
  const boxCenter = (poly) => { const [x1, y1, x2, y2] = rectOf(poly); return [(x1 + x2) / 2, (y1 + y2) / 2] }
  const contains = (poly, [cx, cy]) => { const [x1, y1, x2, y2] = rectOf(poly); return cx >= x1 && cx <= x2 && cy >= y1 && cy <= y2 }
  // poly 안에 중심이 들어오는 word들의 text를 왼→오로 이어붙임
  const collectFrom = (words, poly) => words
    .map((w) => ({ text: w.text, c: boxCenter(w.poly) }))
    .filter((w) => contains(poly, w.c))
    .sort((a, b) => a.c[0] - b.c[0])
    .map((w) => w.text).filter(Boolean).join(' ')
  const collectText = (poly) => collectFrom(labelRef.current?.words || [], poly)
  // KEY/VALUE 그리기 흐름: pendingValue 없으면 새 item의 key 생성(→다음 박스는 value 대기),
  // 있으면 그 item에 value 추가.
  const onDrawItem = (poly) => {
    if (pendingValue) { appendValue(pendingValue, poly); setPendingValue(null) }
    else {
      const id = 'i' + Date.now()
      pushHistory(); endTextSession()
      setLabel((l) => ({ ...l, item: [...(l.item || []), { id, key: { poly, text: collectText(poly) }, value: [] }] }))
      setSelectedId(id + 'k'); setDirty(true)
      setPendingValue(id)   // 다음 박스는 이 item의 value(필수 2번째)
    }
  }
  const appendValue = (itemId, poly) => {
    pushHistory(); endTextSession()
    setLabel((l) => ({ ...l, item: l.item.map((it) => it.id !== itemId ? it
      : { ...it, value: [...(it.value || []), { poly, text: collectText(poly) }] }) }))
    setSelectedId(itemId + 'v' + (items.find((it) => it.id === itemId)?.value.length || 0))
    setDirty(true)
  }
  // 오른쪽 바 '＋value 박스 추가' → 다음 박스를 이 item의 value로
  const startAddValue = (itemId) => { setPendingValue(itemId); setNewMode(true); setSelectedId(itemId + 'k') }
  const setKeyText = (itemId, text) => {
    if (textSession.current !== itemId + 'k') { pushHistory(); textSession.current = itemId + 'k' }
    setLabel((l) => ({ ...l, item: l.item.map((it) => it.id === itemId ? { ...it, key: { ...it.key, text } } : it) }))
    setDirty(true)
  }
  const setValueText = (itemId, vi, text) => {
    const sess = itemId + 'v' + vi
    if (textSession.current !== sess) { pushHistory(); textSession.current = sess }
    setLabel((l) => ({ ...l, item: l.item.map((it) => it.id !== itemId ? it
      : { ...it, value: it.value.map((v, i) => i === vi ? { ...v, text } : v) }) }))
    setDirty(true)
  }
  const deleteItem = (itemId) => {
    pushHistory(); endTextSession()
    setLabel((l) => ({ ...l, item: (l.item || []).filter((it) => it.id !== itemId) }))
    if (pendingValue === itemId) setPendingValue(null)
    setSelectedId(null); setDirty(true)
  }
  const deleteValue = (itemId, vi) => {
    pushHistory(); endTextSession()
    setLabel((l) => ({ ...l, item: l.item.map((it) => it.id !== itemId ? it
      : { ...it, value: it.value.filter((_, i) => i !== vi) }) }))
    setSelectedId(null); setDirty(true)
  }
  const deleteAllVisible = () => {
    if (!visibleWords.length) return
    const modeName = mode === 'cell' ? '테이블셀' : mode === 'item' ? 'KEY/VALUE' : '텍스트'
    if (!confirm(`현재 모드(${modeName}) 박스 ${visibleWords.length}개를 모두 삭제할까요?`)) return
    pushHistory(); endTextSession()
    setLabel((l) => ({ ...l, [wkey]: [] }))
    setSelectedId(null); setDirty(true)
  }
  const switchMode = (m) => { setMode(m); setSelectedId(null); setNewMode(false); setPendingValue(null); endTextSession() }

  const deleteImg = async (e, n) => {
    e.stopPropagation()
    if (!confirm(`${n} 이미지와 라벨을 삭제할까요?`)) return
    try {
      await api.deleteImage(folder, n)
      setImages((xs) => xs.filter((i) => i.name !== n))
      if (name === n) { setName(null); setLabel(null); setSelectedId(null) }
    } catch (e2) { alert('삭제 실패: ' + e2.message) }
  }

  const toggleDone = useCallback(async (kind) => {   // kind: 'text' | 'cell' | 'item'
    const cur = labelRef.current   // 최신 label을 ref로(자동저장과 stale 클로저 충돌 방지)
    if (!cur || !name || !['text', 'cell', 'item'].includes(kind)) return
    const k = kind === 'cell' ? 'cell_done' : kind === 'item' ? 'item_done' : 'text_done'
    const next = { ...cur, [k]: !cur[k] }
    setLabel(next); labelRef.current = next
    try {
      await api.putLabel(folder, name, next)
      setImages((xs) => xs.map((i) => i.name === name ? { ...i, [k]: next[k] } : i))
    } catch (e) { alert('저장 실패: ' + e.message) }
  }, [folder, name])

  const moveImage = useCallback((delta) => {
    if (!images.length) return
    const idx = images.findIndex((i) => i.name === name)
    const next = images[Math.max(0, Math.min(images.length - 1, idx + delta))]
    if (next) selectImage(next.name)
  }, [images, name, selectImage])

  useEffect(() => {
    const editing = () => ['INPUT', 'TEXTAREA'].includes(document.activeElement?.tagName)
    const onKeyDown = (e) => {
      // Ctrl/Cmd+S: 물리 키(KeyS)로 잡아 IME(한글)·포커스와 무관하게 저장.
      // (e.key는 한글 IME/레이아웃에서 's'가 아니어서 matchAction이 놓쳐 브라우저 '다른 이름으로 저장'이 떴음)
      if ((e.ctrlKey || e.metaKey) && e.code === 'KeyS') { e.preventDefault(); save(); return }
      if (e.code === 'Space' && !editing()) { e.preventDefault(); setPanMode(true); return }
      const action = matchAction(keys, e)
      if (editing()) {
        if (action === 'cancel') document.activeElement.blur()
        return
      }
      if (!action) return
      const handlers = {
        prevImage: () => moveImage(-1),
        nextImage: () => moveImage(1),
        editText: () => selectedId && wordInputs.current[selectedId]?.focus(),
        // KEY/VALUE에서 value 대기 중이면 ESC는 value 없이 key만 저장(대기 해제), 아니면 일반 취소
        cancel: () => { if (pendingValue) { setPendingValue(null); return } setSelectedId(null); setNewMode(false) },
        deleteBox: () => selectedId && deleteWord(selectedId),
        newBox: () => setNewMode((v) => !v),
        save,
        runModel,
        fit: () => editorRef.current?.fit(),
        reset100: () => editorRef.current?.reset100(),
        toggleDone: () => toggleDone(mode),   // 현재 모드(text/cell) 완료 토글
        toggleEditShape: () => setEditShape((s) => (s === 'bbox' ? 'poly' : 'bbox')),
        advance: () => moveImage(1),
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
  }, [keys, selectedId, newMode, mode, pendingValue, moveImage, save, runModel, toggleDone, undo])

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
            <button className={mode === 'item' ? 'active item' : ''} onClick={() => switchMode('item')}>KEY/VALUE</button>
          </div>
          <select value={engine} onChange={(e) => setEngine(e.target.value)}>
            <option value="llm">LLM</option>
            <option value="local">로컬 모델</option>
          </select>
          <button onClick={runModel} disabled={!name || busy || mode === 'item'}
            title={`모델 실행 (단축키 ${keys.runModel})`}>모델 실행</button>
          <button className="primary" onClick={save} disabled={!dirty}
            title={`저장 (단축키 ${keys.save})`}>저장{dirty ? ' *' : ''}</button>
          <label className="autosave" title="ON이면 다른 이미지로 넘어갈 때 자동 저장">
            <input type="checkbox" checked={autoSave}
              onChange={(e) => { setAutoSave(e.target.checked); localStorage.setItem('autoSave', e.target.checked ? '1' : '0') }} />
            자동저장
          </label>
          <button className={newMode ? (mode === 'cell' ? 'toggle-cell' : mode === 'item' ? 'toggle-kv ' + (pendingValue ? 'value' : 'key') : 'toggle-on') : ''}
            title={`박스 그리기/선택 전환 (단축키 ${keys.newBox})`}
            onClick={() => setNewMode((v) => !v)}>＋{mode === 'item' ? (pendingValue ? 'VALUE' : 'KEY') : mode === 'cell' ? '셀' : '텍스트'} 그리기</button>
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
          <div className="side-head">완료 텍스트 {textDone} · 셀 {cellDone} · K/V {itemDone} / {images.length}</div>
          {images.map((im) => (
            <div key={im.name} className={'img-row' + (im.name === name ? ' active' : '')}
              onClick={() => selectImage(im.name)}>
              <input className="chk-text" type="checkbox" title="텍스트박스 완료" checked={!!im.text_done} readOnly
                onClick={(e) => { e.stopPropagation(); if (im.name === name) toggleDone('text') }} />
              <input className="chk-cell" type="checkbox" title="테이블셀 완료" checked={!!im.cell_done} readOnly
                onClick={(e) => { e.stopPropagation(); if (im.name === name) toggleDone('cell') }} />
              <input className="chk-item" type="checkbox" title="KEY/VALUE 완료" checked={!!im.item_done} readOnly
                onClick={(e) => { e.stopPropagation(); if (im.name === name) toggleDone('item') }} />
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
              words={editorBoxes}
              selectedId={selectedId}
              onSelect={setSelectedId}
              onChangeWord={changeWord}
              onEditStart={() => { pushHistory(); endTextSession() }}
              onNewBox={(poly) => (mode === 'item' ? onDrawItem(poly) : addWord(poly))}
              newMode={newMode}
              panMode={panMode}
              editShape={editShape}
            />
          )}
          {busy && <div className="badge">{busy}</div>}
          {mode === 'item' && pendingValue && !busy &&
            <div className="badge">VALUE 박스를 그리세요 · ESC = 값 없이 저장</div>}
        </div>

        <div className="resizer" onMouseDown={startResize('right')} />

        <div className="side right" style={{ width: rightW }}>
          <div className="side-head">
            {mode === 'cell' ? `테이블 셀 ${visibleWords.length}개`
              : mode === 'item' ? `KEY/VALUE ${visibleWords.length}개` : `텍스트 ${visibleWords.length}개`}
            {label?.source ? ` · ${label.source}` : ''}
          </div>
          <div style={{ padding: 6 }}>
            {mode === 'item' ? (
              items.map((it) => (
                <div key={it.id} className={'item-card' + (parseItemBox(selectedId || '')?.itemId === it.id ? ' active' : '')}>
                  <div className="word-row" onClick={() => setSelectedId(it.id + 'k')}>
                    <button className="kv-btn key" title="KEY">KEY</button>
                    <input ref={(el) => { wordInputs.current[it.id + 'k'] = el }} className="kv-key" value={it.key?.text || ''}
                      onChange={(e) => setKeyText(it.id, e.target.value)}
                      onFocus={() => setSelectedId(it.id + 'k')} />
                    <button className="danger" title="쌍 삭제" onClick={() => deleteItem(it.id)}>×</button>
                  </div>
                  {(it.value || []).map((v, vi) => (
                    <div className="word-row val" key={vi} onClick={() => setSelectedId(it.id + 'v' + vi)}>
                      <button className="kv-btn value" title="VALUE">VAL</button>
                      <input ref={(el) => { wordInputs.current[it.id + 'v' + vi] = el }} className="kv-value" value={v.text}
                        onChange={(e) => setValueText(it.id, vi, e.target.value)}
                        onFocus={() => setSelectedId(it.id + 'v' + vi)} />
                      <button className="danger" title="value 삭제" onClick={() => deleteValue(it.id, vi)}>×</button>
                    </div>
                  ))}
                  <button className="add-value" onClick={() => startAddValue(it.id)}>＋ value 박스 추가</button>
                </div>
              ))
            ) : (
              visibleWords.map((w) => (
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
                      <input ref={(el) => { wordInputs.current[w.id] = el }} value={w.text}
                        onChange={(e) => changeText(w.id, e.target.value)}
                        onFocus={() => setSelectedId(w.id)} />
                    </>
                  )}
                  <button className="danger" onClick={() => deleteWord(w.id)}>×</button>
                </div>
              ))
            )}
          </div>
        </div>
      </div>

      {showSettings && (
        <ShortcutSettings map={keys} onChange={setKeys} onClose={() => setShowSettings(false)} />
      )}
    </div>
  )
}
