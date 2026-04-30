import { useAuth0 } from '@auth0/auth0-react';

export function LoginPage() {
  const { loginWithRedirect, isLoading } = useAuth0();

  return (
    <div style={{
      minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center',
      background: 'var(--bg)',
    }}>
      <div style={{
        display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 32,
        padding: '48px 40px',
        border: '1px solid var(--line-2)', borderRadius: 12,
        background: 'var(--bg-2)',
        boxShadow: '0 20px 60px oklch(0.22 0.01 260 / 0.06)',
        width: 360,
      }}>
        {/* Logo */}
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8 }}>
          <div className="mono" style={{ fontSize: 22, fontWeight: 600, letterSpacing: '-0.02em', color: 'var(--ink)', display: 'flex', alignItems: 'center', gap: 10 }}>
            <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none">
              <path d="M8 3.5 C5.5 3.5 5.5 6 5.5 8 C5.5 10.5 4 11 3 12 C4 13 5.5 13.5 5.5 16 C5.5 18 5.5 20.5 8 20.5" stroke="var(--ink)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
              <path d="M16 3.5 C18.5 3.5 18.5 6 18.5 8 C18.5 10.5 20 11 21 12 C20 13 18.5 13.5 18.5 16 C18.5 18 18.5 20.5 16 20.5" stroke="var(--ink)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
              <path d="M10 6 Q14 12 10 18" stroke="#c97a3a" strokeWidth="2" strokeLinecap="round"/>
              <path d="M14 6 Q10 12 14 18" stroke="#3f8a5e" strokeWidth="2" strokeLinecap="round"/>
            </svg>
            helix
          </div>
          <p style={{ margin: 0, fontSize: 13, color: 'var(--ink-3)', textAlign: 'center', lineHeight: 1.5 }}>
            Autonomous crash-to-PR pipeline
          </p>
        </div>

        <hr style={{ width: '100%', border: 0, borderTop: '1px solid var(--line)' }} />

        <div style={{ width: '100%', display: 'flex', flexDirection: 'column', gap: 12 }}>
          <button
            onClick={() => loginWithRedirect()}
            disabled={isLoading}
            style={{
              width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 10,
              padding: '10px 16px', borderRadius: 6,
              border: '1px solid var(--line-2)',
              background: 'var(--bg)', color: 'var(--ink)',
              fontFamily: 'var(--sans)', fontSize: 13.5, fontWeight: 500,
              cursor: isLoading ? 'default' : 'pointer',
              opacity: isLoading ? 0.6 : 1,
              transition: 'background 120ms, border-color 120ms',
            }}
            onMouseEnter={e => { (e.currentTarget.style.background = 'var(--bg-3)'); }}
            onMouseLeave={e => { (e.currentTarget.style.background = 'var(--bg)'); }}
          >
            <GoogleIcon />
            {isLoading ? 'loading…' : 'Sign in with Google'}
          </button>
        </div>

        <p style={{ margin: 0, fontSize: 11, color: 'var(--ink-3)', textAlign: 'center', lineHeight: 1.6 }}>
          Access is restricted to authorised team members.
        </p>
      </div>
    </div>
  );
}

function GoogleIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18">
      <path fill="#4285F4" d="M17.64 9.2c0-.637-.057-1.251-.164-1.84H9v3.481h4.844c-.209 1.125-.843 2.078-1.796 2.716v2.259h2.908c1.702-1.567 2.684-3.875 2.684-6.615z"/>
      <path fill="#34A853" d="M9 18c2.43 0 4.467-.806 5.956-2.184l-2.908-2.259c-.806.54-1.837.86-3.048.86-2.344 0-4.328-1.584-5.036-3.711H.957v2.332A8.997 8.997 0 0 0 9 18z"/>
      <path fill="#FBBC05" d="M3.964 10.706A5.41 5.41 0 0 1 3.682 9c0-.593.102-1.17.282-1.706V4.962H.957A8.996 8.996 0 0 0 0 9c0 1.452.348 2.827.957 4.038l3.007-2.332z"/>
      <path fill="#EA4335" d="M9 3.58c1.321 0 2.508.454 3.44 1.345l2.582-2.58C13.463.891 11.426 0 9 0A8.997 8.997 0 0 0 .957 4.962L3.964 7.294C4.672 5.163 6.656 3.58 9 3.58z"/>
    </svg>
  );
}
