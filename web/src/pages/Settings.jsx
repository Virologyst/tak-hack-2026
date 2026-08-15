/* Server settings. Slice 4 builds the CRUD, slice 5 the LAN discovery.
 *
 * The schema is already in place (`servers` in web/schema.py), including the
 * per-server `service_id` that backs the vocabulary-preference dropdown — one
 * machine may bridge a police net to one server and an ambulance net to
 * another, and "fire" has to mean different things on each, so the preference
 * belongs to the server rather than being global.
 */
export default function Settings() {
  return (
    <div className="page-inner">
      <h1 className="page-title">Server settings</h1>
      <p className="page-sub">
        Where the constructed CoT gets sent, and which vocabulary it is read with.
      </p>
      <div className="stub">
        <h2>Not wired up yet</h2>
        <p>The database columns exist; the page comes after the live console.</p>
        <ul>
          <li>
            <strong>Scan the LAN</strong> — sweep for open 8087 / 8089 / 8443 /
            8446, infer transport and URL from which ports answer, ask{' '}
            <code style={{ fontFamily: 'var(--mono)' }}>/Marti/api/version</code>{' '}
            for a positive ID, and leave everything we cannot infer blank
          </li>
          <li>
            <strong>One dropdown entry per server found</strong>, plus a manual
            add — so a server discovery cannot see can still be forced in by
            hand
          </li>
          <li>
            <strong>Vocabulary preference per server</strong> — pick which
            service&apos;s dictionary this connection is read with
          </li>
          <li>
            <strong>Every field editable</strong>, including into a broken
            state. A bad URL raises a visible error and keeps the previous
            sender running rather than killing the engine
          </li>
        </ul>
        <p style={{ marginTop: 16 }}>
          Until then the target comes from{' '}
          <code style={{ fontFamily: 'var(--mono)' }}>$COT_URL</code> or{' '}
          <code style={{ fontFamily: 'var(--mono)' }}>config.ini</code>, same as
          the rest of the toolkit.
        </p>
      </div>
    </div>
  )
}
