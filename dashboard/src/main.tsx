import { Auth0Provider } from '@auth0/auth0-react';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import './index.css';
import App from './App';
import { AuthGuard } from './components/AuthGuard';

const domain   = import.meta.env.VITE_AUTH0_DOMAIN   as string | undefined;
const clientId = import.meta.env.VITE_AUTH0_CLIENT_ID as string | undefined;
const audience = import.meta.env.VITE_AUTH0_AUDIENCE  as string | undefined;

const authEnabled = Boolean(domain && clientId);

const app = <App />;

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {authEnabled ? (
      <Auth0Provider
        domain={domain!}
        clientId={clientId!}
        authorizationParams={{
          redirect_uri: window.location.origin + '/app/',
          audience,
          scope: 'openid profile email',
          connection: 'google-oauth2',
        }}
      >
        <AuthGuard>{app}</AuthGuard>
      </Auth0Provider>
    ) : (
      app
    )}
  </StrictMode>,
);
