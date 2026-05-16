/// <reference types="vite/client" />

declare module 'dagre';

interface ImportMetaEnv {
	readonly VITE_API_URL?: string;
	readonly VITE_API_TIMEOUT?: string;
	readonly VITE_WS_URL?: string;
	readonly VITE_COMMUNITY_API_URL?: string;
}

interface ImportMeta {
	readonly env: ImportMetaEnv;
}
