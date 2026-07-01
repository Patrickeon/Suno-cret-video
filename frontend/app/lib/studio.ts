// Suno MV Studio — 공유 타입 · 상수 · 스타일.
// 값 전용 모듈(컴포넌트 없음)이라 "use client" 불필요.

export const API = process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8000";

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

export const PRESETS = [
  { name: "Lo-fi", emoji: "🌙", viz: "waves", kenburns: true, bg: "0x12101a" },
  { name: "발라드", emoji: "🎹", viz: "spectrum", kenburns: true, bg: "0x0a0a14" },
  { name: "EDM", emoji: "⚡", viz: "cqt", kenburns: true, bg: "0x05010f" },
  { name: "미니멀", emoji: "◾", viz: "none", kenburns: false, bg: "0x000000" },
];

export const MODELS = [
  { id: "claude-opus-4-8", label: "Claude Opus 4.8 (최고 성능)" },
  { id: "claude-sonnet-4-6", label: "Claude Sonnet 4.6 (균형·기본)" },
  { id: "claude-haiku-4-5-20251001", label: "Claude Haiku 4.5 (빠름·저렴)" },
];

export const SUGGESTIONS = [
  "쇼츠 세로형으로 만들어줘",
  "막대 스펙트럼으로 바꿔줘",
  "배경 켄번스 꺼줘",
  "후렴부터 30초만 잘라줘",
];

export const inputCls =
  "w-full rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm outline-none transition focus:border-indigo-400 focus:ring-1 focus:ring-indigo-400/40";
