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
  const [tab, setTab] = useState('main')
  const [health, setHealth] = useState(null)
  const [live, setLive] = useState(false)
  const [events, setEvents] = useState([])
  const [engine, setEngine] = useState(null)
  const [services, setServices] = useState([])
  const [notACommand, setNotACommand] = useState('Not detected as a Tak command entry')

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

  /* EXACTLY ONE EventSource, and it lives here rather than on the Live page.
   *
   * HTTP/1.1 allows about six connections per origin. A stream opened per page
   * would mean a few stale tabs exhaust the pool, after which every fetch on
   * the site hangs - which looks identical to a dead server and is miserable to
   * diagnose. One connection in the shell also means events keep arriving while
   * you are editing vocabulary, so switching to Live shows history rather than
   * an empty screen.
   */
  useEffect(() => {
    const es = new EventSource('/api/stream')
    es.addEventListener('open', () => setLive(true))
    es.addEventListener('error', () => setLive(false))
    es.addEventListener('hello', (m) => {
      const d = JSON.parse(m.data)
      setLive(true)
      setEngine(d.engine)
      setServices(d.services || [])
      setEvents(d.recent || [])
      if (d.not_a_command) setNotACommand(d.not_a_command)
    })
    es.addEventListener('engine', (m) => setEngine(JSON.parse(m.data)))
    es.addEventListener('utterance', (m) => {
      const ev = JSON.parse(m.data)
      // Keyed by id so a reconnect replaying `recent` cannot duplicate rows.
      setEvents((prev) => (prev.some((p) => p.id === ev.id)
        ? prev : [...prev, ev].slice(-200)))
    })
    return () => es.close()
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
          {live
            ? <><span className="dot">●</span> live</>
            : <><span className="dot bad">●</span> reconnecting</>}
          {health ? ` · vocab rev ${health.revision}` : ' · api unreachable'}
        </div>
      </div>

      <div className={`page${tab === 'main' ? ' nopad' : ''}`}>
        {tab === 'main' && <Main events={events} engine={engine}
                                 services={services} notACommand={notACommand} />}
        {tab === 'vocab' && <Vocabulary />}
        {tab === 'settings' && <Settings />}
        {tab === 'legacy' && <App />}
      </div>
    </div>
  )
}
