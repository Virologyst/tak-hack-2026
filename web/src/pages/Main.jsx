import { useEffect, useRef, useState } from 'react'

/* The operator console. Radio in on the left, meaning in the middle, what went
 * on the wire on the right.
 *
 * All three panes render from the SAME utterance event, keyed by id, so they
 * cannot drift apart - the one thing that would make the screen a liar. The
 * right-hand pane shows the exact bytes the engine transmitted, or the server's
 * own not-a-command wording. The browser never decides that text.
 */

const api = async (path, opts) => {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' }, ...opts,
  })
  const body = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(body.error || `${res.status} ${res.statusText}`)
  return body
}

/* Underline the spans the vocabulary rewrote, so it is visible WHY the middle
   pane differs from the left. Offsets are into the raw text. */
function marked(raw, hits) {
  if (!hits || !hits.length) return raw
  const out = []
  let at = 0
  for (const h of [...hits].sort((a, b) => a.start - b.start)) {
    if (h.start < at) continue
    out.push(raw.slice(at, h.start))
    out.push(
      <span key={`${h.start}-${h.term_id}`}
            className={`hit${h.shadows_core ? ' shadow' : ''}`}
            title={`${h.service}: "${h.trigger}" -> ${h.tak_word || '(removed)'}`
                   + (h.shadows_core ? ' (overrides a core term)' : '')}>
        {raw.slice(h.start, h.end)}
      </span>)
    at = h.end
  }
  out.push(raw.slice(at))
  return out
}

function Report({ report }) {
  if (!report) return null
  const cell = (k, v) => (
    <div className="rfield" key={k}>
      <span className="rk">{k}</span>
      <span className={`rv${v == null || v === 'other' || v === 'unknown'
                             ? ' dim' : ''}`}>{v == null ? '—' : String(v)}</span>
    </div>
  )
  return (
    <div className="report">
      {cell('intent', report.intent)}
      {cell('agency', report.agency)}
      {cell('unit', report.unit)}
      {cell('count', report.count)}
      {cell('location', report.location)}
      {cell('priority', report.priority)}
    </div>
  )
}

export default function Main({ events, engine, services, notACommand }) {
  const [selected, setSelected] = useState(null)
  const [text, setText] = useState('')
  const [service, setService] = useState('')
  const [devices, setDevices] = useState([])
  const [device, setDevice] = useState('')
  const [gain, setGain] = useState('1')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const leftRef = useRef(null)

  const [backends, setBackends] = useState(null)

  useEffect(() => {
    api('/api/devices').then((d) => setDevices(d.devices || [])).catch(() => {})
    api('/api/backends').then(setBackends).catch(() => {})
  }, [])

  // Newest first. On a radio feed the latest transmission is the one that
  // matters, and it should be under your eye without scrolling.
  const ordered = [...events].reverse()
  const newest = ordered[0]

  // Follow the newest unless the operator has clicked back to an older one -
  // moving the page away from what someone is reading is infuriating.
  useEffect(() => {
    if (selected === null && leftRef.current) leftRef.current.scrollTop = 0
  }, [events.length, selected])

  const current = selected
    ? events.find((e) => e.id === selected) || newest
    : newest

  /* The panes reveal left to right as a transmission lands: heard, then what
   * we made of it, then what went on the wire. It makes the direction of
   * travel obvious to someone watching over a shoulder.
   *
   * Done with a CSS animation-delay per pane, keyed on the event id, and NOT
   * with a stage counter. The counter version was measurably wrong: with
   * utterances arriving about a second apart - which is just normal radio
   * traffic - each new one reset the sequence before it finished, and the
   * Cursor-on-Target pane sat permanently dimmed. An animation cannot get
   * stuck like that. Every pane is always fully readable; only the entrance
   * is staggered, and a new event simply restarts its own.
   */

  // Restart the header sweep on each new transmission by toggling a class.
  // Nothing about the CONTENT depends on this, so a burst of traffic can at
  // worst cut an animation short - it can never hide the text.
  const [pulseOn, setPulseOn] = useState(false)
  useEffect(() => {
    if (!newest?.id) return
    setPulseOn(false)
    const on = requestAnimationFrame(() => setPulseOn(true))
    const off = setTimeout(() => setPulseOn(false), 900)
    return () => { cancelAnimationFrame(on); clearTimeout(off) }
  }, [newest?.id])
  const pulse = pulseOn ? ' pulse' : ''

  const running = engine?.state === 'running'

  const send = async () => {
    if (!text.trim()) return
    setBusy(true); setErr('')
    try {
      await api('/api/simulate', {
        method: 'POST',
        body: JSON.stringify({ text, service: service || null }),
      })
      setText('')
      setSelected(null)
    } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }

  const toggleEngine = async () => {
    setBusy(true); setErr('')
    try {
      if (running) {
        await api('/api/engine/stop', { method: 'POST' })
      } else {
        await api('/api/engine/start', {
          method: 'POST',
          body: JSON.stringify({
            source: 'mic',
            device: device === '' ? null : Number(device),
            gain: Number(gain) || 1,
            service: service || null,
          }),
        })
      }
    } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }

  return (
    <div className="live">
      <div className="controls">
        <button className={`btn ${running ? 'danger' : 'primary'}`}
                onClick={toggleEngine}
                disabled={busy || (backends && !backends.any && !running)}
                title={backends && !backends.any
                  ? 'No speech backend on the interpreter running this server'
                  : 'listen on the selected input'}>
          {running ? 'Stop listening' : 'Start listening'}
        </button>

        <select value={device} onChange={(e) => setDevice(e.target.value)}
                disabled={running} title="the radio's audio-out goes here">
          <option value="">default input</option>
          {devices.filter((d) => !d.error).map((d) => (
            <option key={d.index} value={d.index}>
              [{d.index}] {d.name.slice(0, 34)}
            </option>
          ))}
        </select>

        <label className="ctl">gain
          <input value={gain} onChange={(e) => setGain(e.target.value)}
                 disabled={running} size={3}
                 title="line level from a radio wants ~1; a quiet laptop mic wants more" />
        </label>

        <label className="ctl">service
          <select value={service} onChange={(e) => setService(e.target.value)}>
            <option value="">core only</option>
            {(services || []).filter((s) => s !== 'CORE').map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </label>

        <span className={`estate ${engine?.state || 'stopped'}`}>
          {engine?.state || 'stopped'}
          {engine?.model ? ` · ${engine.model}` : ''}
          {engine?.threshold ? ` · vad ${engine.threshold}` : ''}
        </span>

        <span className="controls-right">
          <input className="say" value={text} placeholder="or type a transmission…"
                 onChange={(e) => setText(e.target.value)}
                 onKeyDown={(e) => e.key === 'Enter' && send()} />
          <button className="btn" onClick={send} disabled={busy || !text.trim()}>
            Send
          </button>
        </span>
      </div>

      {backends && !backends.any && (
        <div className="banner warn">
          <strong>No speech backend on this server.</strong> Every page works and
          you can still type transmissions above, but listening needs Moonshine —
          which is installed in the project venv, not the system Python.
          {backends.venv_python && (
            <> Restart with:{' '}
              <code>{backends.venv_python} web/app.py --host 0.0.0.0</code></>
          )}
        </div>
      )}

      {(err || engine?.error) && (
        <div className="banner">{err || engine.error}</div>
      )}

      <div className="panes">
        <section className={`pane p1${pulse}`}>
          <header>Heard<span className="pcount">{events.length}</span></header>
          <div className="pane-body list" ref={leftRef}>
            {events.length === 0 && (
              <p className="empty">
                Nothing yet. Start listening, or type a transmission above to
                run one through without a microphone.
              </p>
            )}
            {ordered.map((e, i) => (
              <button key={e.id}
                      className={`heard${current && e.id === current.id ? ' on' : ''}`
                                 + (i === 0 && selected === null ? ' fresh' : '')}
                      onClick={() => setSelected(e.id)}>
                <span className="hid">{e.id}</span>
                <span className="htext">{e.raw}</span>
                <span className="hmeta">
                  {e.cot ? <em className="ok">CoT</em> : <em className="no">—</em>}
                  {e.audio?.duration ? ` ${e.audio.duration}s` : ''}
                  {e.audio?.realtime ? ` ${e.audio.realtime}×` : ''}
                </span>
              </button>
            ))}
          </div>
        </section>

        <section className={`pane p2${pulse}`}>
          <header>
            Sanitised
            {current?.service && <span className="pcount">{current.service}</span>}
          </header>
          <div className="pane-body">
            {!current ? <p className="empty">—</p> : (
              <>
                <p className="sanitised">
                  {current.sanitised || <span className="empty">(nothing)</span>}
                </p>
                {current.hits?.length > 0 && (
                  <p className="rawline">
                    from: {marked(current.raw, current.hits)}
                  </p>
                )}
                <Report report={current.report} />
              </>
            )}
          </div>
        </section>

        <section className={`pane p3${pulse}`}>
          <header>
            Cursor-on-Target
            {current?.sent?.sa && <span className="pcount sent">sent</span>}
          </header>
          <div className="pane-body">
            {!current ? <p className="empty">—</p>
              : current.cot ? (
                <>
                  <pre className="xml">{current.cot_pretty || current.cot}</pre>
                  <p className="wire">
                    {current.sent?.sa
                      ? `on the wire → ${current.sent.url}`
                      : current.sent?.error || 'not transmitted'}
                  </p>
                </>
              ) : (
                <p className="nocot">{current.cot_reason || notACommand}</p>
              )}
          </div>
        </section>
      </div>
    </div>
  )
}
