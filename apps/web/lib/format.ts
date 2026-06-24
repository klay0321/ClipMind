// 纯展示格式化工具（无副作用，便于单测）。

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null || bytes < 0) return "—";
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  const idx = Math.min(i, units.length - 1);
  const value = bytes / Math.pow(1024, idx);
  return `${value.toFixed(idx === 0 ? 0 : 1)} ${units[idx]}`;
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || seconds < 0) return "—";
  const total = Math.round(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const pad = (n: number) => n.toString().padStart(2, "0");
  return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`;
}

export function formatResolution(
  width: number | null | undefined,
  height: number | null | undefined,
  orientation: string | null | undefined,
): string {
  if (!width || !height) return "—";
  const label =
    orientation === "portrait"
      ? "竖屏"
      : orientation === "landscape"
        ? "横屏"
        : orientation === "square"
          ? "方形"
          : "";
  return label ? `${width}×${height} · ${label}` : `${width}×${height}`;
}

export function formatCodec(
  video: string | null | undefined,
  audio: string | null | undefined,
): string {
  if (!video && !audio) return "—";
  return [video ?? "—", audio ?? "无音频"].join(" / ");
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const pad = (n: number) => n.toString().padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
