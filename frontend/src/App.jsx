import React, { useState } from 'react'
import ProjectList from './ProjectList.jsx'
import Labeler from './Labeler.jsx'

// 프로젝트 목록 ↔ 라벨러 전환.
export default function App() {
  const [project, setProject] = useState(null)
  return project
    ? <Labeler project={project} onExit={() => setProject(null)} />
    : <ProjectList onEnter={setProject} />
}
