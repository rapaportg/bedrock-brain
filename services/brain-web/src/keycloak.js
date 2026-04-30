/**
 * Keycloak singleton.
 *
 * The brain-ui public client is already registered in keycloak/realm-export.json
 * with PKCE + standard flow and redirectUris: ["http://localhost:*"].
 *
 * Usage:
 *   import kc from './keycloak'
 *   await kc.init(...)
 *   kc.token          // raw JWT for Authorization: Bearer
 *   kc.tokenParsed    // decoded payload
 *   kc.logout()
 */

import Keycloak from 'keycloak-js'

const keycloak = new Keycloak({
  url:      import.meta.env.VITE_KEYCLOAK_URL      || 'http://localhost:8080',
  realm:    import.meta.env.VITE_KEYCLOAK_REALM    || 'bedrock',
  clientId: import.meta.env.VITE_KEYCLOAK_CLIENT_ID || 'brain-ui',
})

/**
 * Initialise Keycloak and return whether the user is already authenticated.
 * Calling this twice is safe — Keycloak-js guards against re-init.
 */
export async function initKeycloak() {
  const authenticated = await keycloak.init({
    onLoad: 'login-required',   // redirect to KC login if not authenticated
    checkLoginIframe: false,    // avoid iframe CSP issues in dev
    pkceMethod: 'S256',
  })
  return authenticated
}

/**
 * Return a fresh token string, refreshing silently if it expires in <30 s.
 */
export async function getToken() {
  await keycloak.updateToken(30)
  return keycloak.token
}

export default keycloak
