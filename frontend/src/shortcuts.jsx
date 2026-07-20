// 단축키: 액션→키 매핑 하나 + localStorage 저장 + 설정 UI. 라이브러리 불필요.
import React, { useState, useRef, useEffect } from 'react'

export const ACTIONS = {
  prevImage: '이전 이미지',
  nextImage: '다음 이미지',
  editText: '텍스트 편집',
  cancel: '취소/선택해제',
  deleteBox: '박스 삭제',
  newBox: '박스 그리기/선택 전환',
  save: '저장',
  runModel: '모델 실행',
  fit: '화면 맞춤',
  reset100: '100% 배율',
  toggleDone: '완료 토글(현재 모드)',
  toggleEditShape: '편집모드(bbox/poly)',
  undo: '실행 취소',
}

const DEFAULTS = {
  prevImage: 'ArrowUp',
  nextImage: 'ArrowDown',
  editText: 'Enter',
  cancel: 'Escape',
  deleteBox: 'Delete',
  newBox: 'n',
  save: 'Ctrl+s',
  runModel: 'r',
  fit: 'f',
  reset100: '1',
  toggleDone: 'c',
  toggleEditShape: 'b',
  undo: 'Ctrl+z',
}

const KEY = 'shortcuts'

export function loadShortcuts() {
  try {
    return { ...DEFAULTS, ...JSON.parse(localStorage.getItem(KEY) || '{}') }
  } catch {
    return { ...DEFAULTS }
  }
}

export function saveShortcuts(map) {
  localStorage.setItem(KEY, JSON.stringify(map))
}

// KeyboardEvent → 정규화 키 문자열. 단일 문자는 소문자.
export function eventToKey(e) {
  const k = e.key.length === 1 ? e.key.toLowerCase() : e.key
  return (e.ctrlKey || e.metaKey ? 'Ctrl+' : '') + k
}

// 현재 이벤트에 매칭되는 액션명 반환(없으면 null).
export function matchAction(map, e) {
  const key = eventToKey(e)
  return Object.keys(map).find((a) => map[a] === key) || null
}

export function ShortcutSettings({ map, onChange, onClose }) {
  const [waiting, setWaiting] = useState(null) // 키 입력 대기 중인 액션
  const rootRef = useRef(null)
  useEffect(() => { if (waiting) rootRef.current?.focus() }, [waiting])

  const capture = (e) => {
    if (!waiting) return
    e.preventDefault()
    if (e.key === 'Escape') return setWaiting(null)
    const key = eventToKey(e)
    const clash = Object.keys(map).find((a) => a !== waiting && map[a] === key)
    const next = { ...map, [waiting]: key }
    onChange(next)
    saveShortcuts(next)
    setWaiting(null)
    if (clash) alert(`경고: "${key}"가 [${ACTIONS[clash]}]와 중복됩니다.`)
  }

  return (
    <div ref={rootRef} className="modal-back" tabIndex={0} onKeyDown={capture} onClick={onClose}
      style={{ outline: 'none' }}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h3>단축키 설정</h3>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}><tbody>
          {Object.keys(ACTIONS).map((a) => (
            <tr key={a}>
              <td style={{ padding: '5px 12px 5px 0' }}>{ACTIONS[a]}</td>
              <td><code style={{ background: '#f1f3f7', padding: '2px 7px', borderRadius: 5 }}>{map[a]}</code></td>
              <td style={{ textAlign: 'right' }}>
                <button className={waiting === a ? 'toggle-on' : ''} onClick={() => setWaiting(a)}>
                  {waiting === a ? '키 입력…' : '변경'}
                </button>
              </td>
            </tr>
          ))}
        </tbody></table>
        <div className="modal-actions">
          <button onClick={() => { onChange({ ...DEFAULTS }); saveShortcuts(DEFAULTS) }}>기본값 복원</button>
          <button className="primary" onClick={onClose}>닫기</button>
        </div>
      </div>
    </div>
  )
}
