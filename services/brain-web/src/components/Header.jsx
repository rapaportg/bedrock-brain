import './Header.css'

export default function Header({ user, onLogout }) {
  const name  = user?.name  || user?.preferred_username || user?.email || 'User'
  const email = user?.email || ''
  const initials = name
    .split(' ')
    .map(w => w[0])
    .join('')
    .slice(0, 2)
    .toUpperCase()

  return (
    <header className="header">
      <div className="header-brand">
        <span className="brand-icon">🧠</span>
        <span className="brand-name">Bedrock Brain</span>
      </div>

      <div className="header-user">
        <div className="user-avatar" title={email}>{initials}</div>
        <span className="user-name">{name}</span>
        <button className="btn-ghost" onClick={onLogout}>Sign out</button>
      </div>
    </header>
  )
}
