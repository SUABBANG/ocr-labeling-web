// KEY별 고정 색. KEY 리스트 순서(index) 기준으로 팔레트를 배정 → 각 KEY가 서로 다른 색.
// 캔버스 박스·KEY 배지·리스트 스와치·선택창이 모두 같은 색을 쓰도록 공유한다.
export const KEY_PALETTE = [
  '#e11d48', '#9333ea', '#0d9488', '#2563eb', '#ea580c',
  '#16a34a', '#db2777', '#0891b2', '#ca8a04', '#7c3aed',
  '#dc2626', '#0284c7', '#65a30d', '#c026d3', '#f59e0b',
]

// keyList에서 name의 인덱스로 색 결정. 없으면(삭제/개명된 KEY) 회색.
export const colorForKey = (keyList, name) => {
  const i = keyList.findIndex((k) => k.name === name)
  return i >= 0 ? KEY_PALETTE[i % KEY_PALETTE.length] : '#8a94a6'
}

// hex → rgba(투명). 박스 채움색 등 옅은 배경용.
export const hexA = (hex, a) => {
  const n = parseInt(hex.slice(1), 16)
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`
}
