import { useEffect, useState, useCallback, useRef } from 'react'

// ATAK renders these team names as distinct colours on the map, so the swatch
// here is a genuine preview of what an operator will see - not decoration.
const TEAM_HEX = {
  'White': '#e6efe9', 'Yellow': '#f2c14e', 'Orange': '#e08b3a',
  'Magenta': '#d060b0', 'Red': '#f0736a', 'Maroon': '#9c4a44',
  'Purple': '#9a7fd0', 'Dark Blue': '#3b5f9e', 'Blue': '#79b8ff',
  'Cyan': '#5fd0c8', 'Teal': '#3f9188', 'Green': '#5fd08a',
  'Dark Green': '#3f8757', 'Brown': '#8a6a4a',
}

const api = async (path, opts) => {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' }, ...opts,
  })
  const body = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(body.error || `${res.status} ${res.statusText}`)
  return body
}

/* Show which part of a suggestion matched. The match can be anywhere in the
   term, so without this it is not obvious why "precisionlocation" appears when
   you typed "loc". */
function highlight(word, query) {
  const q = (query || '').trim().toLowerCase()
  if (!q) return word
  const at = word.toLowerCase().indexOf(q)
  if (at === -1) return word
  return (
    <>
      {word.slice(0, at)}
      <mark>{word.slice(at, at + q.length)}</mark>
      {word.slice(at + q.length)}
    </>
  )
}

let keySeq = 0
const blankRow = () => ({
  key: `r${++keySeq}`, id: null, trigger: '', tak_word: '', comments: '',
  saving: false, saved: false, error: '',
})
const toRow = (t) => ({
  key: `r${++keySeq}`, id: t.id, trigger: t.trigger, tak_word: t.tak_word,
  comments: t.comments, saving: false, saved: false, error: '',
})

/* A table that behaves like a spreadsheet.
 *
 * Two rules drive the whole design:
 *
 *  - Typing the first character of a trigger CREATES the row immediately, and
 *    a fresh blank row appears beneath it. No Add button.
 *  - Leaving any field saves it. No Save button.
 *
 * Both mean the list must never be re-fetched mid-edit. A refetch re-renders
 * the table, React swaps the DOM nodes, and the caret jumps out of the field
 * the operator is typing into - which is exactly the thing that must not
 * happen. So local state owns the rows after the first load, and every
 * mutation patches that state in place from the server's own response.
 *
 * React keys stay stable for a row's whole life (`r7` before it is saved and
 * after), so acquiring a database id never remounts the input and never costs
 * focus.
 */
function ServiceTable({ service, initialTerms, teams, onError, onDeleted,
                       openAll, onCount, catalogue }) {
  const [open, setOpen] = useState(false)
  const [rows, setRows] = useState(() => [...initialTerms.map(toRow), blankRow()])
  const isCore = !!service.is_core
  // Edits made while a create is still in flight - flushed when the id lands.
  const pending = useRef({})

  useEffect(() => { if (openAll !== null) setOpen(openAll.value) }, [openAll])

  const saved = rows.filter((r) => r.id !== null)
  useEffect(() => { onCount(service.id, saved.length) }, [saved.length])

  const patchRow = (key, changes) =>
    setRows((rs) => rs.map((r) => (r.key === key ? { ...r, ...changes } : r)))

  const flash = (key) => {
    patchRow(key, { saved: true, error: '' })
    setTimeout(() => patchRow(key, { saved: false }), 900)
  }

  /* First keystroke in an unsaved row's trigger: create it now. */
  const createRow = async (row, trigger) => {
    patchRow(row.key, { saving: true, error: '' })
    // The blank row appears immediately, not after the round trip, so the
    // table never visibly stalls while the network is slow.
    setRows((rs) => (rs.some((r) => r.id === null && r.key !== row.key)
      ? rs : [...rs, blankRow()]))
    try {
      const created = await api('/api/terms', {
        method: 'POST',
        body: JSON.stringify({
          service_id: service.id, trigger,
          tak_word: row.tak_word, comments: row.comments,
        }),
      })
      const late = pending.current[row.key]
      delete pending.current[row.key]
      patchRow(row.key, { id: created.id, saving: false })
      flash(row.key)
      // Anything typed while the POST was in flight.
      if (late) {
        for (const [field, value] of Object.entries(late)) {
          await api(`/api/terms/${created.id}`, {
            method: 'PATCH', body: JSON.stringify({ [field]: value }),
          }).catch(() => {})
        }
      }
    } catch (e) {
      patchRow(row.key, { saving: false, error: e.message })
      onError(e.message)
    }
  }

  const commit = async (row, field, value) => {
    if (value === row[field]) return
    patchRow(row.key, { [field]: value })

    if (row.id === null) {
      if (field === 'trigger' && value.trim()) return createRow(row, value)
      // Typed into tak/comments before the trigger exists: hold it locally and
      // it goes up with the create. Nothing to save yet - an empty trigger is
      // not a term.
      if (row.saving) pending.current[row.key] = {
        ...(pending.current[row.key] || {}), [field]: value }
      return
    }

    try {
      await api(`/api/terms/${row.id}`, {
        method: 'PATCH', body: JSON.stringify({ [field]: value }),
      })
      flash(row.key)
    } catch (e) {
      patchRow(row.key, { error: e.message })
      onError(e.message)
    }
  }

  const removeRow = async (row) => {
    if (row.id === null) return
    try {
      await api(`/api/terms/${row.id}`, { method: 'DELETE' })
      setRows((rs) => rs.filter((r) => r.key !== row.key))
    } catch (e) { onError(e.message) }
  }

  const removeService = async () => {
    if (!confirm(`Delete ${service.name} and its ${saved.length} term(s)?`)) return
    try {
      await api(`/api/services/${service.id}`, { method: 'DELETE' })
      onDeleted()
    } catch (e) { onError(e.message) }
  }

  return (
    <div className={`svc${isCore ? ' core' : ''}${open ? ' open' : ''}`}>
      <div className="svc-head">
        <button className="disclose" aria-expanded={open}
                onClick={() => setOpen((o) => !o)}
                title={open ? 'Collapse' : 'Expand'}>
          <span className="caret">{open ? '▾' : '▸'}</span>
          <span className="svc-name">{service.name}</span>
          <span className="team-chip">
            <span className="swatch"
                  style={{ background: TEAM_HEX[service.team] || '#8fa89b' }} />
            {service.team}
          </span>
          <span className="count">
            {saved.length} term{saved.length === 1 ? '' : 's'}
          </span>
          {isCore && <span className="count">— applies to every service</span>}
        </button>
        {!isCore && (
          <span className="svc-head-right">
            <select className="btn small" value={service.team}
                    onChange={async (e) => {
                      try {
                        await api(`/api/services/${service.id}`, {
                          method: 'PATCH',
                          body: JSON.stringify({ team: e.target.value }),
                        })
                        onDeleted()   // cheap re-read; no row is being edited
                      } catch (err) { onError(err.message) }
                    }}>
              {teams.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
            <button className="btn small danger" onClick={removeService}>
              Delete service
            </button>
          </span>
        )}
      </div>

      {open && (
        <table className="terms">
          <colgroup>
            <col className="c-id" /><col className="c-trigger" />
            <col className="c-tak" /><col /><col className="c-act" />
          </colgroup>
          <thead>
            <tr>
              <th>Id</th><th>Trigger word</th><th>Tak word</th>
              <th>Comments</th><th />
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.key}
                  className={`${row.id === null ? 'newrow' : ''}${row.error ? ' bad' : ''}`}>
                <td className="id">
                  {row.saving ? '…' : row.id === null ? '+'
                    : <span className={row.saved ? 'flash' : ''}>{row.id}</span>}
                </td>
                <td>
                  <Cell row={row} field="trigger" mono
                        placeholder={row.id === null ? 'what they say' : ''}
                        onCommit={commit} catalogue={catalogue} />
                </td>
                <td>
                  <Cell row={row} field="tak_word" mono
                        placeholder={row.id === null ? 'a TAK term'
                                                     : '(not mapped)'}
                        onCommit={commit} catalogue={catalogue} />
                </td>
                <td>
                  <Cell row={row} field="comments"
                        placeholder={row.id === null ? '' : 'why, or who says it'}
                        onCommit={commit} catalogue={catalogue} />
                </td>
                <td>
                  {row.id !== null && (
                    <button className="x" title="Remove"
                            onClick={() => removeRow(row)}>×</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

/* One cell. Local draft while focused, committed on blur or Enter, reverted on
   Escape. Deliberately does NOT re-sync from props on every render - that would
   fight the user mid-keystroke.

   The Tak word column additionally predicts against the catalogue, and colours
   itself red the moment the text is not a real term - before you leave the
   field, because finding out on blur is finding out too late. */
function Cell({ row, field, placeholder, mono, onCommit, catalogue }) {
  const value = row[field] ?? ''
  const [draft, setDraft] = useState(value)
  // Focus is STATE, not a ref: the prediction list is rendered from it, and a
  // ref neither triggers a re-render nor is safe to read during one.
  const [isFocused, setIsFocused] = useState(false)
  const focused = useRef(false)     // for the effect below, which must not re-run
  const isTak = field === 'tak_word'

  useEffect(() => { if (!focused.current) setDraft(value) }, [value])

  // Valid means "does something", which a multi-word phrase can do without
  // being a catalogue entry - "requesting backup" is not listed but both of
  // its words match. So the client only greys a phrase it cannot verify; the
  // server has the final say and rejects with a suggestion.
  const known = !isTak || !catalogue || !draft.trim()
    || catalogue.byWord.has(draft.trim().toLowerCase())
    || draft.trim().split(/\s+/).some((w) => catalogue.byWord.has(w.toLowerCase()))

  // Shown whenever the field is focused and has text - NOT only when the text
  // is invalid. Once you have typed something recognisable is exactly when you
  // may still want a longer term ("fire" -> "fire incident"), and hiding the
  // list there means the only way to discover it is to already know it.
  const matches = isTak && catalogue && isFocused && draft.trim()
    ? catalogue.search(draft, 10) : []

  // Open upward when there is not enough room below. Rows near the bottom of
  // the table are exactly where you are most likely to be typing - it is the
  // new-term row - so a list that always drops downward is invisible precisely
  // when it is most needed.
  const wrap = useRef(null)
  const [above, setAbove] = useState(false)
  useEffect(() => {
    if (!matches.length || !wrap.current) return
    const box = wrap.current.getBoundingClientRect()
    const needed = Math.min(300, matches.length * 30 + 12)
    setAbove(box.bottom + needed > window.innerHeight - 8
             && box.top - needed > 8)
  }, [matches.length, draft])

  const pick = (word) => {
    setDraft(word)
    onCommit(row, field, word)
  }

  return (
    <div className={isTak ? 'takcell' : undefined} ref={wrap}>
      <input
        className={`cell${mono ? ' mono' : ''}${draft !== value ? ' dirty' : ''}`
                   + (known ? '' : ' invalid')}
        value={draft}
        placeholder={placeholder}
        list={undefined}
        autoComplete="off"
        title={known && isTak && draft.trim()
          ? (catalogue?.byWord.get(draft.trim().toLowerCase())?.effect || '')
          : undefined}
        onFocus={() => { focused.current = true; setIsFocused(true) }}
        onChange={(e) => {
          const v = e.target.value
          setDraft(v)
          if (row.id === null && field === 'trigger' && !row.saving && v.trim()) {
            onCommit(row, 'trigger', v)
          }
        }}
        onBlur={() => {
          focused.current = false
          setIsFocused(false)
          // A mousedown on a suggestion fires before blur, so the pick
          // still lands even though the list unmounts here.
          onCommit(row, field, draft)
        }}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            if (matches.length && !known) { e.preventDefault(); pick(matches[0].word); return }
            e.currentTarget.blur()
          }
          if (e.key === 'Escape') { setDraft(value); e.currentTarget.blur() }
        }}
      />
      {isTak && matches.length > 0 && (
        <ul className={`predict${above ? ' above' : ''}`}>
          {matches.map((m) => (
            <li key={m.word}>
              <button onMouseDown={(e) => { e.preventDefault(); pick(m.word) }}>
                <span className="pw">{highlight(m.word, draft)}</span>
                <span className={`pc ${m.category}`}>{m.category}</span>
                <span className="pe">{m.effect}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export default function Vocabulary() {
  const [services, setServices] = useState([])
  const [teams, setTeams] = useState([])
  const [termsByService, setTermsByService] = useState({})
  const [counts, setCounts] = useState({})
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [newService, setNewService] = useState('')
  const [newTeam, setNewTeam] = useState('Blue')
  const [openAll, setOpenAll] = useState(null)
  const [epoch, setEpoch] = useState(0)

  const [catalogue, setCatalogue] = useState(null)

  // The whole catalogue once, up front. It is ~150 entries, so prediction and
  // validation happen locally - no round trip on a keystroke, and the field
  // can go red the moment the word stops being real rather than on blur.
  useEffect(() => {
    api('/api/takwords').then((d) => {
      const byWord = new Map(d.words.map((w) => [w.word.toLowerCase(), w]))
      setCatalogue({
        all: d.words,
        byWord,
        ignore: d.ignore,
        search: (q, limit = 8) => {
          const s = q.trim().toLowerCase()
          if (!s) return []
          const starts = d.words.filter((w) => w.word.toLowerCase().startsWith(s))
          const rest = d.words.filter((w) => w.word.toLowerCase().includes(s)
                                          && !w.word.toLowerCase().startsWith(s))
          return [...starts, ...rest].slice(0, limit)
        },
      })
    }).catch(() => setCatalogue(null))
  }, [])

  const load = useCallback(async () => {
    try {
      const [s, t] = await Promise.all([api('/api/services'), api('/api/terms')])
      const grouped = {}
      for (const term of t.terms) {
        (grouped[term.service_id] ||= []).push(term)
      }
      setServices(s.services); setTeams(s.teams); setTermsByService(grouped)
      setCounts(Object.fromEntries(
        s.services.map((x) => [x.id, (grouped[x.id] || []).length])))
      setError('')
    } catch (e) {
      setError(`Cannot reach the API — is web/app.py running? (${e.message})`)
    } finally { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load, epoch])

  const addService = async () => {
    if (!newService.trim()) return
    try {
      await api('/api/services', {
        method: 'POST',
        body: JSON.stringify({ name: newService, team: newTeam }),
      })
      setNewService('')
      setEpoch((e) => e + 1)
    } catch (e) { setError(e.message) }
  }

  const onCount = useCallback(
    (id, n) => setCounts((c) => (c[id] === n ? c : { ...c, [id]: n })), [])

  const core = services.filter((s) => s.is_core)
  const rest = services.filter((s) => !s.is_core)
  const total = Object.values(counts).reduce((a, b) => a + b, 0)

  const table = (s) => (
    // epoch in the key forces a clean remount after a service add/delete,
    // which is the only time discarding local row state is correct.
    <ServiceTable key={`${s.id}-${epoch}`} service={s} teams={teams}
                  initialTerms={termsByService[s.id] || []}
                  onError={setError} onDeleted={() => setEpoch((e) => e + 1)}
                  openAll={openAll} onCount={onCount} catalogue={catalogue} />
  )

  return (
    <div className="page-inner">
      <h1 className="page-title">Vocabulary dictionaries</h1>
      <p className="page-sub">
        What each service actually says on the radio, and what it means in TAK.
      </p>

      <p className="note">
        A trigger word belongs to <strong>one service</strong>, so the same word
        can mean different things to different teams — <code>fire</code> to the
        firefighters is an incident, <code>fire</code> to SAS is weapons free.
        Core terms apply to everyone, and a service term of the same name
        overrides the core one. <strong>Just type</strong> — a row is created as
        soon as you start a trigger word, and every field saves when you leave
        it. Escape reverts.
      </p>

      {error && <div className="banner">{error}</div>}
      {loading && <p className="note">Loading…</p>}

      {!loading && (
        <div className="listbar">
          <span className="count">
            {services.length} dictionar{services.length === 1 ? 'y' : 'ies'} ·{' '}
            {total} term{total === 1 ? '' : 's'}
          </span>
          <span style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
            <button className="btn small"
                    onClick={() => setOpenAll({ value: true })}>Expand all</button>
            <button className="btn small"
                    onClick={() => setOpenAll({ value: false })}>Collapse all</button>
          </span>
        </div>
      )}

      {core.map(table)}
      {rest.map(table)}

      <div className="addsvc">
        <strong style={{ fontSize: '0.9rem' }}>Add service</strong>
        <input value={newService} placeholder="e.g. TRANSPORT"
               onChange={(e) => setNewService(e.target.value)}
               onKeyDown={(e) => e.key === 'Enter' && addService()} />
        <select value={newTeam} onChange={(e) => setNewTeam(e.target.value)}>
          {teams.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
        <button className="btn primary" onClick={addService}
                disabled={!newService.trim()}>Create</button>
        <span className="count">
          team colour is how this service appears on the map
        </span>
      </div>
    </div>
  )
}
