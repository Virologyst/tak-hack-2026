import { useState } from 'react'
import './App.css'

const DEFAULT_PHRASES = [
  { id: 1, phrase: 'mayday', category: 'emergency' },
  { id: 2, phrase: 'officer down', category: 'emergency' },
  { id: 3, phrase: 'on scene', category: 'status' },
  { id: 4, phrase: 'requesting backup', category: 'request' },
  { id: 5, phrase: 'all clear', category: 'status' },
  { id: 6, phrase: 'crowd surge', category: 'incident' },
]

const CATEGORIES = ['emergency', 'status', 'request', 'incident', 'custom']

function App() {
  const [phrases, setPhrases] = useState(DEFAULT_PHRASES)
  const [newPhrase, setNewPhrase] = useState('')
  const [newCategory, setNewCategory] = useState('custom')
  const [filter, setFilter] = useState('all')

  const nextId = () => Math.max(0, ...phrases.map(p => p.id)) + 1

  const addPhrase = (e) => {
    e.preventDefault()
    const trimmed = newPhrase.trim()
    if (!trimmed) return
    if (phrases.some(p => p.phrase.toLowerCase() === trimmed.toLowerCase())) return
    setPhrases([...phrases, { id: nextId(), phrase: trimmed, category: newCategory }])
    setNewPhrase('')
  }

  const removePhrase = (id) => {
    setPhrases(phrases.filter(p => p.id !== id))
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
