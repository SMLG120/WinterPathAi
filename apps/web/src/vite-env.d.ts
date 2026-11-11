/// <reference types="vite/client" />
interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_USE_MOCKS?: string;
  readonly VITE_MAP_STYLE_URL?: string;
  readonly VITE_PUBLIC_WRITES?: string;
  readonly VITE_API_TIMEOUT_MS?: string;
}
interface ImportMeta {
  readonly env: ImportMetaEnv;
}
declare module '*.geojson?raw' {
  const content: string;
  export default content;
}
