/* The three-pane operator console. Slice 2 fills this in.
 *
 * Left: live transcript off the radio. Middle: the same text with each
 * service's trigger words substituted for their TAK words. Right: the CoT XML
 * actually put on the wire, or the "not detected" message.
 *
 * Deliberately a stub rather than a mock: an empty frame that says what is
 * coming is honest, whereas fake scrolling text in the panes would look
 * finished and mislead anyone walking past the screen.
 */
export default function Main() {
  return (
    <div className="page-inner">
      <h1 className="page-title">Live</h1>
      <p className="page-sub">
        Radio chatter in, CoT on the shared map out. Eyes on the job, not on the
        interface.
      </p>
      <div className="stub">
        <h2>Not wired up yet</h2>
        <p>
          The vocabulary tables come first so terms can be entered while the
          rest is built. This page arrives in the next slice and will show three
          panes, all rendered from one event so they cannot drift apart:
        </p>
        <ul>
          <li><strong>Left</strong> — the raw transcript, growing as someone speaks</li>
          <li><strong>Middle</strong> — the sanitised version, trigger words replaced with TAK words</li>
          <li><strong>Right</strong> — the constructed CoT XML, exactly as sent, or
            <em> “Not detected as a Tak command entry”</em></li>
        </ul>
        <p style={{ marginTop: 16 }}>
          The map itself already exists and is not being rebuilt here — run{' '}
          <code style={{ fontFamily: 'var(--mono)' }}>python tak.py dashboard</code>{' '}
          for the judge-facing second screen.
        </p>
      </div>
    </div>
  )
}
