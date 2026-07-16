// Konva 캔버스: 이미지 + poly 박스 오버레이. 줌/팬, 박스 이동/꼭짓점 리사이즈, 신규 생성.
import React, {
  forwardRef, useEffect, useImperativeHandle, useLayoutEffect, useRef, useState,
} from 'react'
import { Stage, Layer, Image as KImage, Line, Circle, Rect } from 'react-konva'

const MIN_SCALE = 0.1
const MAX_SCALE = 10

function useHtmlImage(url) {
  const [img, setImg] = useState(null)
  useEffect(() => {
    if (!url) return setImg(null)
    const im = new window.Image()
    im.src = url
    im.onload = () => setImg(im)
    return () => { im.onload = null }
  }, [url])
  return img
}

const Editor = forwardRef(function Editor(
  { imageUrl, words, selectedId, onSelect, onChangeWord, onEditStart, onNewBox, newMode, panMode, editShape },
  ref,
) {
  const wrapRef = useRef(null)
  const stageRef = useRef(null)
  const [size, setSize] = useState({ w: 800, h: 600 })
  const [view, setView] = useState({ scale: 1, x: 0, y: 0 })
  const [draft, setDraft] = useState(null) // 신규 박스 그리는 중 {x,y,w,h}
  const [ctrlDown, setCtrlDown] = useState(false) // Ctrl 누름 → 드래그로 팬
  const img = useHtmlImage(imageUrl)

  useEffect(() => {
    const down = (e) => { if (e.key === 'Control') setCtrlDown(true) }
    const up = (e) => { if (e.key === 'Control') setCtrlDown(false) }
    const clear = () => setCtrlDown(false)
    window.addEventListener('keydown', down)
    window.addEventListener('keyup', up)
    window.addEventListener('blur', clear)
    return () => {
      window.removeEventListener('keydown', down)
      window.removeEventListener('keyup', up)
      window.removeEventListener('blur', clear)
    }
  }, [])

  const canPan = panMode || ctrlDown

  // 컨테이너 크기 추적
  useLayoutEffect(() => {
    const el = wrapRef.current
    if (!el) return
    const ro = new ResizeObserver(() => setSize({ w: el.clientWidth, h: el.clientHeight }))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const fit = () => {
    if (!img) return
    const s = Math.min(size.w / img.width, size.h / img.height)
    setView({ scale: s, x: (size.w - img.width * s) / 2, y: (size.h - img.height * s) / 2 })
  }
  const reset100 = () => {
    if (!img) return
    setView({ scale: 1, x: (size.w - img.width) / 2, y: (size.h - img.height) / 2 })
  }
  useImperativeHandle(ref, () => ({ fit, reset100 }))
  useEffect(() => { fit() /* 이미지 바뀌면 맞춤 */ }, [img, size.w, size.h]) // eslint-disable-line

  const onWheel = (e) => {
    e.evt.preventDefault()
    const stage = stageRef.current
    const p = stage.getPointerPosition()
    const s0 = view.scale
    const s1 = Math.min(MAX_SCALE, Math.max(MIN_SCALE, s0 * (e.evt.deltaY < 0 ? 1.1 : 1 / 1.1)))
    // 커서 위치 고정 줌
    const mx = (p.x - view.x) / s0
    const my = (p.y - view.y) / s0
    setView({ scale: s1, x: p.x - mx * s1, y: p.y - my * s1 })
  }

  // 신규 박스 그리기 (이미지 좌표)
  const relPoint = () => stageRef.current.getRelativePointerPosition()
  const onDown = (e) => {
    if (canPan) return // 팬 중 — Stage 드래그가 처리
    if (!newMode) {
      if (e.target === e.target.getStage() || e.target.className === 'Image') onSelect(null)
      return
    }
    const p = relPoint()
    setDraft({ x: p.x, y: p.y, w: 0, h: 0 })
  }
  const onMove = () => {
    if (!newMode || !draft) return
    const p = relPoint()
    setDraft((d) => ({ ...d, w: p.x - d.x, h: p.y - d.y }))
  }
  const onUp = () => {
    if (!newMode || !draft) return
    const x1 = Math.min(draft.x, draft.x + draft.w)
    const y1 = Math.min(draft.y, draft.y + draft.h)
    const x2 = Math.max(draft.x, draft.x + draft.w)
    const y2 = Math.max(draft.y, draft.y + draft.h)
    setDraft(null)
    if (x2 - x1 > 3 && y2 - y1 > 3) {
      onNewBox([[x1, y1], [x2, y1], [x2, y2], [x1, y2]].map((p) => p.map(Math.round)))
    }
  }

  const sw = 2 / view.scale // 화면상 일정한 선 두께

  return (
    <div ref={wrapRef} style={{ width: '100%', height: '100%', background: '#333', cursor: canPan ? 'grab' : 'default' }}>
      <Stage
        ref={stageRef}
        width={size.w}
        height={size.h}
        scaleX={view.scale}
        scaleY={view.scale}
        x={view.x}
        y={view.y}
        draggable={canPan}
        onWheel={onWheel}
        onMouseDown={onDown}
        onMouseMove={onMove}
        onMouseUp={onUp}
        onDragEnd={(e) => {
          // 스테이지 팬 종료 → view 갱신
          if (e.target === stageRef.current) setView((v) => ({ ...v, x: e.target.x(), y: e.target.y() }))
        }}
      >
        <Layer>
          {img && <KImage image={img} />}
          {words.map((w) => (
            <WordShape
              key={w.id}
              word={w}
              selected={w.id === selectedId}
              strokeWidth={sw}
              editable={!newMode && !canPan}
              editShape={editShape}
              onSelect={() => onSelect(w.id)}
              onEditStart={onEditStart}
              onChange={(poly) => onChangeWord(w.id, poly)}
            />
          ))}
          {draft && (
            <Rect x={draft.x} y={draft.y} width={draft.w} height={draft.h}
              stroke="lime" strokeWidth={sw} dash={[4 / view.scale, 4 / view.scale]} />
          )}
        </Layer>
      </Stage>
    </div>
  )
})

// 축정렬 사각형 poly 재구성: 드래그 코너 p 와 반대 코너 q 로 TL,TR,BR,BL 생성
function rectFrom(p, q) {
  const x1 = Math.round(Math.min(p[0], q[0])); const x2 = Math.round(Math.max(p[0], q[0]))
  const y1 = Math.round(Math.min(p[1], q[1])); const y2 = Math.round(Math.max(p[1], q[1]))
  return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]
}

function WordShape({ word, selected, strokeWidth, editable, editShape, onSelect, onEditStart, onChange }) {
  const flat = word.poly.flat()
  const cell = word.kind === 'cell'
  const base = cell ? '#ffa000' : '#00b0ff'   // 셀=주황, 텍스트=파랑
  const fill = cell ? 'rgba(255,160,0,0.06)' : 'rgba(0,176,255,0.05)'
  return (
    <>
      <Line
        points={flat}
        closed
        stroke={selected ? '#ff3b30' : base}
        strokeWidth={strokeWidth}
        fill={selected ? 'rgba(255,59,48,0.08)' : fill}
        draggable={editable && selected}
        onMouseDown={(e) => { if (!editable) return; e.cancelBubble = true; onSelect() }}
        onDragStart={() => onEditStart && onEditStart()}
        onDragEnd={(e) => {
          const dx = e.target.x(); const dy = e.target.y()
          e.target.position({ x: 0, y: 0 })
          onChange(word.poly.map(([x, y]) => [Math.round(x + dx), Math.round(y + dy)]))
        }}
      />
      {selected && editable && word.poly.map(([x, y], i) => (
        <Circle
          key={i}
          x={x}
          y={y}
          radius={strokeWidth * 3}
          fill="#fff"
          stroke="#ff3b30"
          strokeWidth={strokeWidth}
          draggable
          onMouseDown={(e) => { e.cancelBubble = true }}
          onDragStart={() => onEditStart && onEditStart()}
          onDragMove={(e) => {
            const p = [e.target.x(), e.target.y()]
            if (editShape === 'bbox') {
              // 사각형 유지: 반대 코너를 고정하고 두 점으로 사각형 재구성
              onChange(rectFrom(p, word.poly[(i + 2) % 4]))
            } else {
              // poly: 이 꼭짓점만 이동
              onChange(word.poly.map((q, j) => (j === i ? [Math.round(p[0]), Math.round(p[1])] : q)))
            }
          }}
        />
      ))}
    </>
  )
}

export default Editor
