// Suno MV Studio — 공유 타입 · 상수 · 스타일.
// 값 전용 모듈(컴포넌트 없음)이라 "use client" 불필요.

export const API = process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8000";

// ---- 앱 토큰 (백엔드 APP_TOKEN 인증) ----
// 배포 환경에서 백엔드가 X-App-Token 헤더를 요구할 때 사용.
// 로컬 개발(백엔드 APP_TOKEN 미설정)에서는 토큰이 없어도 그대로 동작한다.
const TOKEN_KEY = "mv_app_token";

export function getAppToken(): string {
  if (typeof window === "undefined") return "";
  try {
    return localStorage.getItem(TOKEN_KEY) || "";
  } catch {
    return "";
  }
}

export function setAppToken(t: string) {
  try {
    if (t) localStorage.setItem(TOKEN_KEY, t);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* localStorage 불가 환경 무시 */
  }
}

/** fetch 래퍼: 저장된 앱 토큰을 X-App-Token 헤더로 붙이고,
 *  401 이면 "mv:unauthorized" 이벤트를 쏴서 토큰 입력 모달을 띄운다. */
export async function apiFetch(url: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  const t = getAppToken();
  if (t) headers.set("X-App-Token", t);
  const r = await fetch(url, { ...init, headers });
  if (r.status === 401 && typeof window !== "undefined") {
    window.dispatchEvent(new Event("mv:unauthorized"));
  }
  return r;
}

/** <video>/<img>/<a download> 용 미디어 URL — 헤더를 못 붙이므로 ?token= 쿼리로 인증. */
export function mediaUrl(path: string): string {
  const t = getAppToken();
  if (!t) return `${API}${path}`;
  const sep = path.includes("?") ? "&" : "?";
  return `${API}${path}${sep}token=${encodeURIComponent(t)}`;
}

export type JobStatus = "queued" | "running" | "done" | "error" | "cancelled";

export interface Job {
  id: string;
  status: JobStatus;
  progress: number;
  stage?: string;
  error: string | null;
  log: string;
  video: boolean;
  thumb: boolean;
}

export interface JobSummary {
  id: string;
  status: JobStatus;
  video: boolean;
  thumb: boolean;
  created: number;
  title: string;
  shorts: boolean;
}

export interface ChatMsg {
  role: "user" | "assistant";
  text: string;
}

export interface Settings {
  llm_provider: string;
  llm_model: string;
  llm_key_set: boolean;
  video_provider: string;
  video_key_set: boolean;
}

export interface Toast {
  id: number;
  text: string;
  kind: "info" | "success" | "error";
}

export const BG_PRESETS = [
  { id: "midnight", label: "미드나잇" },
  { id: "plum", label: "플럼" },
  { id: "ocean", label: "오션" },
  { id: "forest", label: "포레스트" },
  { id: "ember", label: "엠버" },
  { id: "dusk", label: "더스크" },
];

// 비주얼라이저 그라데이션 팔레트 (RRGGBB 2색). ""=기본 파스텔.
export const VIZ_PALETTES = [
  { id: "", label: "파스텔 드림", c: ["7DD3FC", "F0ABFC"] },
  { id: "FDA4AF,F9A8D4", label: "핑크 캔디", c: ["FDA4AF", "F9A8D4"] },
  { id: "6EE7B7,67E8F9", label: "민트 소다", c: ["6EE7B7", "67E8F9"] },
  { id: "FCA5A5,FCD34D", label: "선셋", c: ["FCA5A5", "FCD34D"] },
  { id: "A5B4FC,C4B5FD", label: "라벤더", c: ["A5B4FC", "C4B5FD"] },
  { id: "FFFFFF,E5E7EB", label: "모노", c: ["FFFFFF", "E5E7EB"] },
];

export const PRESETS = [
  { name: "포근", emoji: "🧸", viz: "waves", vizColor: "", kenburns: true, bg: "0x1a1424" },
  { name: "Lo-fi", emoji: "🌙", viz: "waves", vizColor: "A5B4FC,C4B5FD", kenburns: true, bg: "0x12101a" },
  { name: "발라드", emoji: "🎹", viz: "line", vizColor: "FFFFFF,E5E7EB", kenburns: true, bg: "0x0a0a14" },
  { name: "EDM", emoji: "⚡", viz: "bars", vizColor: "FCA5A5,FCD34D", kenburns: true, bg: "0x05010f" },
  { name: "미니멀", emoji: "◾", viz: "none", vizColor: "", kenburns: false, bg: "0x000000" },
];

export const MODELS = [
  { id: "claude-opus-4-8", label: "Claude Opus 4.8 (최고 성능)" },
  { id: "claude-sonnet-4-6", label: "Claude Sonnet 4.6 (균형·기본)" },
  { id: "claude-haiku-4-5-20251001", label: "Claude Haiku 4.5 (빠름·저렴)" },
];

export const SUGGESTIONS = [
  "쇼츠 세로형으로 만들어줘",
  "파형을 핑크색으로 바꿔줘",
  "잔잔한 느낌의 미니멀 라인으로",
  "후렴부터 30초만 잘라줘",
];

export const inputCls =
  "w-full rounded-lg border border-[var(--border)] bg-[var(--input-bg)] px-3 py-2 text-sm text-[var(--text)] outline-none transition focus:border-indigo-400 focus:ring-1 focus:ring-indigo-400/40";
