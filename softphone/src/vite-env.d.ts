/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_SIP_SERVER: string
  readonly VITE_SIP_USER: string
  readonly VITE_SIP_PASS: string
  readonly VITE_SIP_DISPLAY: string
  readonly VITE_STUN_URL: string
  readonly VITE_TURN_URL: string
  readonly VITE_TURN_USER: string
  readonly VITE_TURN_PASS: string
  readonly VITE_SEARCH_API_URL: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
