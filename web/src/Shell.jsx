import { useEffect, useState } from 'react'
import './console.css'
import Main from './pages/Main'
import Vocabulary from './pages/Vocabulary'
import Settings from './pages/Settings'
import App from './App'      // Craig's trigger page, rendered unchanged

/* Three pages and a legacy tab, so no router.
 *
 * react-router would be a dependency, a lockfile conflict and an npm install
 * over venue wifi, in exchange for history support nobody needs on a console
 * that lives on one screen. useState is the whole thing.
 *
 * Craig's original trigger page is kept as a tab rather than replaced: his
 * App.jsx is untouched by this work, so he can keep pushing to it without ever
 * conflicting with these files.
 */
const TABS = [
  { id: 'main',     label: 'Live' },
  { id: 'vocab',    label: 'Vocabulary dictionaries' },
  { id: 'settings', label: 'Server settings' },
  { id: 'legacy',   label: 'Triggers (legacy)' },
]

export default function Shell() {
  const [tab, setTab] = useState('vocab')   // vocab first: it is what is ready
  const [health, setHealth] = useState(null)

  useEffect(() => {
    let alive = true
    const poll = () =>
      fetch('/api/health')
        .then((r) => r.json())
        .then((d) => alive && setHealth(d))
        .catch(() => alive && setHealth(null))
    poll()
    const timer = setInterval(poll, 5000)
    return () => { alive = false; clearInterval(timer) }
  }, [])

  return (
    <div className="shell">
      <div className="topbar">
        <div className="brand">TAK <span>Voice Console</span></div>
        {TABS.map((t) => (
          <button
            key={t.id}
            className={`tab${tab === t.id ? ' active' : ''}`}
            onClick={() => setTab(t.id)}>
            {t.label}
          </button>
        ))}
        <div className="topbar-right">
          {health
            ? <><span className="dot">●</span> api up · vocab rev {health.revision}</>
            : <><span className="dot bad">●</span> api unreachable</>}
        </div>
      </div>

      <div className="page">
        {tab === 'main' && <Main />}
        {tab === 'vocab' && <Vocabulary />}
        {tab === 'settings' && <Settings />}
        {tab === 'legacy' && <App />}
      </div>
    </div>
  )
}
