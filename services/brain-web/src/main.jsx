import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
import { initKeycloak } from './keycloak.js'
import './index.css'

// Initialise Keycloak before mounting React.
// onLoad:'login-required' means unauthenticated users are redirected to
// Keycloak before React ever renders — no flash of unauthenticated UI.
initKeycloak()
  .then(() => {
    ReactDOM.createRoot(document.getElementById('root')).render(
      <React.StrictMode>
        <App />
      </React.StrictMode>
    )
  })
  .catch((err) => {
    console.error('Keycloak init failed:', err)
    document.getElementById('root').innerHTML =
      '<div style="padding:2rem;color:red">Authentication service unavailable. Is Keycloak running?</div>'
  })
