import { useState, useEffect } from 'react'
import './App.css'

const CATEGORIES = ['emergency', 'status', 'request', 'incident', 'custom']

function App() {
  const [phrases, setPhrases] = useState([])
  const [newPhrase, setNewPhrase] = useState('')
  const [newCategory, setNewCategory] = useState('custom')
  const [filter, setFilter] = useState('all')
  const [error, setError] = useState(null)

  useEffect(() => {
    fetch('/api/triggers')
      .then(r => r.json())
      .then(setPhrases)
      .catch(() => setError('Cannot reach API — is api.py running?'))
  }, [])

  const addPhrase = async (e) => {
    e.preventDefault()
    const trimmed = newPhrase.trim()
    if (!trimmed) return
    setError(null)
    const res = await fetch('/api/triggers', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ phrase: trimmed, category: newCategory }),
    })
    if (res.status === 201) {
      const created = await res.json()
      setPhrases([...phrases, created])
      setNewPhrase('')
    } else if (res.status === 409) {
      setError('Phrase already exists')
    }
  }

  const removePhrase = async (id) => {
    const res = await fetch(`/api/triggers/${id}`, { method: 'DELETE' })
    if (res.ok) {
      setPhrases(phrases.filter(p => p.id !== id))
    }
  }

  const filtered = filter === 'all'
    ? phrases
    : phrases.filter(p => p.category === filter)

  return (
    <div className="app">
      <header>
        <h1>TAK Voice Triggers</h1>
        <p className="subtitle">Words and phrases that trigger actions from voice input</p>
      </header>

      {error && <div className="error">{error}</div>}

      <form className="add-form" onSubmit={addPhrase}>
        <input
          type="text"
          placeholder="Add a trigger phrase..."
          value={newPhrase}
          onChange={(e) => setNewPhrase(e.target.value)}
          autoFocus
        />
        <select value={newCategory} onChange={(e) => setNewCategory(e.target.value)}>
          {CATEGORIES.map(c => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
        <button type="submit">Add</button>
      </form>

      <div className="filter-bar">
        <button
          className={filter === 'all' ? 'active' : ''}
          onClick={() => setFilter('all')}
        >
          All ({phrases.length})
        </button>
        {CATEGORIES.map(c => {
          const count = phrases.filter(p => p.category === c).length
          if (count === 0) return null
          return (
            <button
              key={c}
              className={filter === c ? 'active' : ''}
              onClick={() => setFilter(c)}
            >
              {c} ({count})
            </button>
          )
        })}
      </div>

      <ul className="phrase-list">
        {filtered.map(p => (
          <li key={p.id}>
            <span className={`category-badge ${p.category}`}>{p.category}</span>
            <span className="phrase-text">{p.phrase}</span>
            <button className="remove-btn" onClick={() => removePhrase(p.id)} title="Remove">
              x
            </button>
          </li>
        ))}
        {filtered.length === 0 && (
          <li className="empty">No phrases in this category</li>
        )}
      </ul>
    </div>
  )
}

export default App
