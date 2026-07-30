import React, { useEffect, useState } from 'react'
import ProjectList from './ProjectList.jsx'
import Labeler from './Labeler.jsx'
import { onLoading } from './api.js'

// 프로젝트 목록 ↔ 라벨러 전환.
export default function App() {
  const [project, setProject] = useState(null)
  return (
    <>
      <LoadingBar />
      {project
        ? <Labeler project={project} onExit={() => setProject(null)} />
        : <ProjectList onEnter={setProject} />}
    </>
  )
}

// 진행 중 API 요청이 있으면 상단에 채워지는 로딩 바 표시.
function LoadingBar() {
  const [active, setActive] = useState(0)
  useEffect(() => onLoading(setActive), [])
  return <div className={'loadbar' + (active > 0 ? ' on' : '')}><i /></div>
}
