"use client";

import { useState } from "react";
import { Field } from "./ui";
import { MODELS, Settings, inputCls } from "../lib/studio";

export function SettingsModal({
  settings,
  onClose,
  onSave,
}: {
  settings: Settings | null;
  onClose: () => void;
  onSave: (patch: Record<string, string>) => Promise<void>;
}) {
  const [llmProvider, setLlmProvider] = useState(settings?.llm_provider ?? "claude");
  const [llmModel, setLlmModel] = useState(settings?.llm_model ?? "claude-sonnet-4-6");
  const [custom, setCustom] = useState(
    !MODELS.some((m) => m.id === (settings?.llm_model ?? "claude-sonnet-4-6"))
  );
  const [llmKey, setLlmKey] = useState("");
  const [videoProvider, setVideoProvider] = useState(settings?.video_provider ?? "replicate");
  const [videoKey, setVideoKey] = useState("");
  const [saving, setSaving] = useState(false);

  async function save() {
    setSaving(true);
    const patch: Record<string, string> = {
      llm_provider: llmProvider,
      llm_model: llmModel,
      video_provider: videoProvider,
    };
    if (llmKey.trim()) patch.llm_api_key = llmKey.trim();
    if (videoKey.trim()) patch.video_api_key = videoKey.trim();
    await onSave(patch);
    setLlmKey("");
    setVideoKey("");
    setSaving(false);
    onClose();
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm" onClick={onClose}>
      <div className="w-full max-w-lg space-y-5 rounded-2xl border border-white/10 bg-neutral-900 p-6 shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between">
          <h2 className="text-base font-semibold">⚙️ API 키 설정 (BYOK)</h2>
          <button onClick={onClose} className="text-neutral-400 hover:text-neutral-200">✕</button>
        </div>
        <p className="text-xs text-neutral-400">키는 백엔드 로컬에만 저장되고 화면엔 다시 표시되지 않습니다(설정 여부만 표시). provider는 언제든 교체 가능.</p>

        <div className="space-y-3 rounded-xl border border-white/10 bg-white/5 p-4">
          <h3 className="text-sm font-medium">AI 편집 (LLM)</h3>
          <Field label="Provider">
            <select value={llmProvider} onChange={(e) => setLlmProvider(e.target.value)} className={inputCls}>
              <option value="claude">Claude (Anthropic)</option>
            </select>
          </Field>
          <Field label="모델">
            {custom ? (
              <input
                value={llmModel}
                onChange={(e) => setLlmModel(e.target.value)}
                placeholder="모델 ID 직접 입력"
                className={inputCls}
              />
            ) : (
              <select
                value={MODELS.some((m) => m.id === llmModel) ? llmModel : "__custom__"}
                onChange={(e) => {
                  if (e.target.value === "__custom__") setCustom(true);
                  else setLlmModel(e.target.value);
                }}
                className={inputCls}
              >
                {MODELS.map((m) => (
                  <option key={m.id} value={m.id}>{m.label}</option>
                ))}
                <option value="__custom__">직접 입력…</option>
              </select>
            )}
          </Field>
          <Field label={`API 키 ${settings?.llm_key_set ? "(설정됨 ✓ — 바꿀 때만 입력)" : "(미설정)"}`}>
            <input type="password" value={llmKey} onChange={(e) => setLlmKey(e.target.value)} placeholder="sk-ant-..." className={inputCls} />
          </Field>
        </div>

        <div className="space-y-3 rounded-xl border border-white/10 bg-white/5 p-4">
          <h3 className="text-sm font-medium">AI 영상 생성 (배경)</h3>
          <Field label="Provider">
            <select value={videoProvider} onChange={(e) => setVideoProvider(e.target.value)} className={inputCls}>
              <option value="replicate">Replicate (권장)</option>
              <option value="kaiber">Kaiber</option>
              <option value="higgsfield">Higgsfield</option>
            </select>
          </Field>
          <Field label={`API 키 ${settings?.video_key_set ? "(설정됨 ✓)" : "(미설정)"}`}>
            <input type="password" value={videoKey} onChange={(e) => setVideoKey(e.target.value)} placeholder="키 입력" className={inputCls} />
          </Field>
        </div>

        <div className="flex justify-end">
          <button onClick={save} disabled={saving} className="rounded-lg bg-indigo-500 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-400 disabled:opacity-50">
            {saving ? "저장 중…" : "저장"}
          </button>
        </div>
      </div>
    </div>
  );
}
