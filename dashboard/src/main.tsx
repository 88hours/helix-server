import { Auth0Provider } from '@auth0/auth0-react'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App'

const domain = import.meta.env.VITE_AUTH0_DOMAIN as string | undefined
const clientId = import.meta.env.VITE_AUTH0_CLIENT_ID as string | undefined
const audience = import.meta.env.VITE_AUTH0_AUDIENCE as string | undefined

// Auth is optional — if VITE_AUTH0_DOMAIN is not set, the app runs in demo
// mode with no login required (mirrors the backend's AUTH0_DOMAIN check).
const authEnabled = Boolean(domain && clientId)

const root = (
  <StrictMode>
    <App />
  </StrictMode>
)

createRoot(document.getElementById('root')!).render(
  authEnabled ? (
    <Auth0Provider
      domain={domain!}
      clientId={clientId!}
      authorizationParams={{
        redirect_uri: window.location.origin + '/app/',
        audience: audience,
        scope: 'openid profile email',
      }}
    >
      {root}
    </Auth0Provider>
  ) : (
    root
  ),
)
