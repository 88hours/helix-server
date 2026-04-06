/**
 * AuthGuard — wraps protected routes.
 *
 * When Auth0 is configured (VITE_AUTH0_DOMAIN is set), redirects unauthenticated
 * users to the Auth0 login page.  While loading the auth state, shows a spinner.
 *
 * When Auth0 is not configured (demo / local-dev mode), renders children
 * immediately without any auth check.
 */

import { useAuth0 } from '@auth0/auth0-react'

interface AuthGuardProps {
  children: React.ReactNode
}

const authEnabled = Boolean(import.meta.env.VITE_AUTH0_DOMAIN)

export function AuthGuard({ children }: AuthGuardProps) {
  if (!authEnabled) {
    return <>{children}</>
  }

  return <Auth0Gate>{children}</Auth0Gate>
}

function Auth0Gate({ children }: AuthGuardProps) {
  const { isLoading, isAuthenticated, loginWithRedirect } = useAuth0()

  if (isLoading) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="text-sm text-gray-400">Loading…</div>
      </div>
    )
  }

  if (!isAuthenticated) {
    loginWithRedirect()
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="text-sm text-gray-400">Redirecting to login…</div>
      </div>
    )
  }

  return <>{children}</>
}
