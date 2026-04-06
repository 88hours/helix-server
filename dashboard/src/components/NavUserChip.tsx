/**
 * Nav bar user chip — shows avatar, name, and sign-out button.
 *
 * Must be rendered inside Auth0Provider.  When auth is disabled this
 * component is never mounted.
 */

import { useAuth0 } from '@auth0/auth0-react'

export function NavUserChip() {
  const { user, logout } = useAuth0()

  return (
    <div className="flex items-center gap-3">
      {user?.picture && (
        <img src={user.picture} alt={user.name ?? ''} className="w-7 h-7 rounded-full" />
      )}
      <span className="text-sm text-gray-500 hidden sm:block">{user?.name}</span>
      <button
        onClick={() => logout({ logoutParams: { returnTo: window.location.origin + '/app/' } })}
        className="text-xs text-gray-400 hover:text-gray-600 transition-colors"
      >
        Sign out
      </button>
    </div>
  )
}
