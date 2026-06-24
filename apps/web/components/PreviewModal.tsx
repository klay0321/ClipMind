"use client";

import { useEffect } from "react";

import { shotPreviewUrl } from "@/lib/api";

export function PreviewModal({
  shotId,
  onClose,
}: {
  shotId: number | null;
  onClose: () => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  if (shotId == null) return null;

  return (
    <div
      data-testid="preview-modal"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-2xl rounded-lg bg-white p-3 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-2 flex items-center justify-between">
          <span className="text-sm font-medium text-gray-700">镜头预览（代理视频）</span>
          <button
            type="button"
            onClick={onClose}
            className="rounded px-2 py-0.5 text-sm text-gray-500 hover:bg-gray-100"
          >
            关闭 ✕
          </button>
        </div>
        {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
        <video
          data-testid="preview-video"
          className="w-full rounded bg-black"
          src={shotPreviewUrl(shotId)}
          controls
          autoPlay
          preload="metadata"
        />
        <p className="mt-2 text-xs text-gray-400">
          这是该素材首个镜头的代理预览。完整逐镜头浏览请进入「镜头库」。
        </p>
      </div>
    </div>
  );
}
