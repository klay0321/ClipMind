"use client";

import { useEffect, useState } from "react";

import { cn } from "@/lib/cn";

// 统一媒体缩略图：固定画幅 + object-cover + lazy + 加载骨架 + 错误兜底 + 无图占位。
// 竖屏/横屏都塞进固定画幅框，绝不撑破布局。所有镜头/素材缩略图都应走这里。
export type MediaRatio = "video" | "square" | "portrait" | "wide";

const RATIO_CLS: Record<MediaRatio, string> = {
  video: "aspect-video",
  square: "aspect-square",
  portrait: "aspect-[3/4]",
  wide: "aspect-[21/9]",
};

export function MediaThumb({
  src,
  alt,
  ratio = "video",
  rounded = "rounded-md",
  className,
  overlay,
  fallbackText = "无缩略图",
}: {
  src: string | null | undefined;
  alt: string;
  ratio?: MediaRatio;
  rounded?: string;
  className?: string;
  overlay?: React.ReactNode;
  fallbackText?: string;
}) {
  const [errored, setErrored] = useState(false);
  const [loaded, setLoaded] = useState(false);

  // src 变化时重置加载/错误态，避免上一个图片状态残留。
  useEffect(() => {
    setErrored(false);
    setLoaded(false);
  }, [src]);

  const showImg = Boolean(src) && !errored;

  return (
    <div className={cn("relative overflow-hidden bg-gray-100", RATIO_CLS[ratio], rounded, className)}>
      {showImg ? (
        <>
          {!loaded ? <div className="absolute inset-0 animate-pulse bg-gray-200" aria-hidden /> : null}
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={src as string}
            alt={alt}
            loading="lazy"
            onLoad={() => setLoaded(true)}
            onError={() => setErrored(true)}
            className={cn(
              "h-full w-full object-cover transition-opacity duration-200",
              loaded ? "opacity-100" : "opacity-0",
            )}
          />
        </>
      ) : (
        <div
          data-testid="media-fallback"
          className="flex h-full w-full items-center justify-center px-1 text-center text-[10px] leading-tight text-gray-400"
        >
          {errored ? "缩略图加载失败" : fallbackText}
        </div>
      )}
      {overlay}
    </div>
  );
}
