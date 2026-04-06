/**
 * Registers the Auth0 token-getter with the API client.
 *
 * Must be rendered inside Auth0Provider.  When auth is disabled this
 * component is never mounted, so the hook is never called outside context.
 */

import { useAuth0 } from '@auth0/auth0-react'
import { useEffect } from 'react'
import { setTokenProvider } from '../api'

export function TokenProviderBridge() {
  const { getAccessTokenSilently } = useAuth0()

  useEffect(() => {
    setTokenProvider(async () => {
      try {
        return await getAccessTokenSilently()
      } catch {
        return null
      }
    })
  }, [getAccessTokenSilently])

  return null
}
