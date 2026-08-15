import { useEffect, useState, useCallback } from 'react'

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

/* One editable cell. Commits on blur or Enter, reverts on Escape.
   No save button anywhere: at hackathon pace, people type and move on, and a
   row that needed an extra click would silently lose edits. */
function Cell({ value, placeholder, mono, onCommit }) {
  const [draft, setDraft] = useState(value ?? '')
  useEffect(() => { setDraft(value ?? '') }, [value])
  const dirty = draft !== (value ?? '')

  const commit = () => { if (dirty) onCommit(draft) }

  return (
    <input
      className={`cell${mono ? ' mono' : ''}${dirty ? ' dirty' : ''}`}
      value={draft}
      placeholder={placeholder}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === 'Enter') { e.currentTarget.blur() }
        if (e.key === 'Escape') { setDraft(value ?? ''); e.currentTarget.blur() }
      }}
    />
  )
}

function ServiceTable({ service, terms, teams, onChanged, onError }) {
  const [newTrigger, setNewTrigger] = useState('')
  const [newTak, setNewTak] = useState('')
  const [newComments, setNewComments] = useState('')
  const isCore = !!service.is_core

  const addTerm = async () => {
    if (!newTrigger.trim()) return
    try {
      await api('/api/terms', {
        method: 'POST',
        body: JSON.stringify({
          service_id: service.id, trigger: newTrigger,
          tak_word: newTak, comments: newComments,
        }),
      })
      setNewTrigger(''); setNewTak(''); setNewComments('')
      onChanged()
    } catch (e) { onError(e.message) }
  }

  const patch = async (id, field, value) => {
    try {
      await api(`/api/terms/${id}`, {
        method: 'PATCH', body: JSON.stringify({ [field]: value }),
      })
      onChanged()
    } catch (e) { onError(e.message) }
  }

  const removeTerm = async (id) => {
    try { await api(`/api/terms/${id}`, { method: 'DELETE' }); onChanged() }
    catch (e) { onError(e.message) }
  }

  const removeService = async () => {
    if (!confirm(`Delete ${service.name} and its ${terms.length} term(s)?`)) return
    try { await api(`/api/services/${service.id}`, { method: 'DELETE' }); onChanged() }
    catch (e) { onError(e.message) }
  }

  return (
    <div className={`svc${isCore ? ' core' : ''}`}>
      <div className="svc-head">
        <span className="svc-name">{service.name}</span>
        <span className="team-chip">
          <span className="swatch"
                style={{ background: TEAM_HEX[service.team] || '#8fa89b' }} />
          {service.team}
        </span>
        <span className="count">{terms.length} term{terms.length === 1 ? '' : 's'}</span>
        {isCore && <span className="count">— applies to every service</span>}
        <span className="svc-head-right">
          {!isCore && (
            <>
              <select
                className="btn small"
                value={service.team}
                onChange={async (e) => {
                  try {
                    await api(`/api/services/${service.id}`, {
                      method: 'PATCH',
                      body: JSON.stringify({ team: e.target.value }),
                    })
                    onChanged()
                  } catch (err) { onError(err.message) }
                }}>
                {teams.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
              <button className="btn small danger" onClick={removeService}>
                Delete service
              </button>
            </>
          )}
        </span>
      </div>

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
          {terms.map((t) => (
            <tr key={t.id}>
              <td className="id">{t.id}</td>
              <td>
                <Cell value={t.trigger} mono
                      onCommit={(v) => patch(t.id, 'trigger', v)} />
              </td>
              <td>
                <Cell value={t.tak_word} mono placeholder="(not mapped)"
                      onCommit={(v) => patch(t.id, 'tak_word', v)} />
              </td>
              <td>
                <Cell value={t.comments} placeholder="why, or who says it"
                      onCommit={(v) => patch(t.id, 'comments', v)} />
              </td>
              <td>
                <button className="x" title="Remove"
                        onClick={() => removeTerm(t.id)}>×</button>
              </td>
            </tr>
          ))}

          <tr className="newrow">
            <td className="id">+</td>
            <td>
              <input className="cell mono" value={newTrigger}
                     placeholder="what they say"
                     onChange={(e) => setNewTrigger(e.target.value)}
                     onKeyDown={(e) => e.key === 'Enter' && addTerm()} />
            </td>
            <td>
              <input className="cell mono" value={newTak}
                     placeholder="what TAK calls it"
                     onChange={(e) => setNewTak(e.target.value)}
                     onKeyDown={(e) => e.key === 'Enter' && addTerm()} />
            </td>
            <td>
              <input className="cell" value={newComments}
                     placeholder="optional"
                     onChange={(e) => setNewComments(e.target.value)}
                     onKeyDown={(e) => e.key === 'Enter' && addTerm()} />
            </td>
            <td>
              <button className="btn small" onClick={addTerm}
                      disabled={!newTrigger.trim()}>Add</button>
            </td>
          </tr>

          {terms.length === 0 && (
            <tr><td colSpan={5} className="empty">
              No terms yet — type one in the row above.
            </td></tr>
          )}
        </tbody>
      </table>
    </div>
  )
}

export default function Vocabulary() {
  const [services, setServices] = useState([])
  const [teams, setTeams] = useState([])
  const [terms, setTerms] = useState([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [newService, setNewService] = useState('')
  const [newTeam, setNewTeam] = useState('Blue')

  const reload = useCallback(async () => {
    try {
      const [s, t] = await Promise.all([
        api('/api/services'), api('/api/terms'),
      ])
      setServices(s.services); setTeams(s.teams); setTerms(t.terms)
      setError('')
    } catch (e) {
      setError(`Cannot reach the API — is web/app.py running? (${e.message})`)
    } finally { setLoading(false) }
  }, [])

  useEffect(() => { reload() }, [reload])

  const addService = async () => {
    if (!newService.trim()) return
    try {
      await api('/api/services', {
        method: 'POST',
        body: JSON.stringify({ name: newService, team: newTeam }),
      })
      setNewService('')
      reload()
    } catch (e) { setError(e.message) }
  }

  const core = services.filter((s) => s.is_core)
  const rest = services.filter((s) => !s.is_core)
  const termsFor = (id) => terms.filter((t) => t.service_id === id)

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
        overrides the core one. Edits save when you leave the field or press
        Enter; Escape reverts.
      </p>

      {error && <div className="banner">{error}</div>}
      {loading && <p className="note">Loading…</p>}

      {core.map((s) => (
        <ServiceTable key={s.id} service={s} terms={termsFor(s.id)}
                      teams={teams} onChanged={reload} onError={setError} />
      ))}

      {rest.map((s) => (
        <ServiceTable key={s.id} service={s} terms={termsFor(s.id)}
                      teams={teams} onChanged={reload} onError={setError} />
      ))}

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
