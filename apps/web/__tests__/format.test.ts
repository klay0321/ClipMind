import { describe, expect, it } from "vitest";

import {
  formatBytes,
  formatCodec,
  formatDateTime,
  formatDuration,
  formatResolution,
} from "@/lib/format";

describe("formatBytes", () => {
  it("处理边界与单位", () => {
    expect(formatBytes(0)).toBe("0 B");
    expect(formatBytes(1024)).toBe("1.0 KB");
    expect(formatBytes(95_000_000)).toContain("MB");
    expect(formatBytes(null)).toBe("—");
    expect(formatBytes(-1)).toBe("—");
  });
});

describe("formatDuration", () => {
  it("mm:ss 与 h:mm:ss", () => {
    expect(formatDuration(0)).toBe("00:00");
    expect(formatDuration(27)).toBe("00:27");
    expect(formatDuration(3661)).toBe("1:01:01");
    expect(formatDuration(null)).toBe("—");
  });
});

describe("formatResolution", () => {
  it("含横竖屏标注", () => {
    expect(formatResolution(1920, 1080, "landscape")).toBe("1920×1080 · 横屏");
    expect(formatResolution(1080, 1920, "portrait")).toBe("1080×1920 · 竖屏");
    expect(formatResolution(null, null, null)).toBe("—");
  });
});

describe("formatCodec", () => {
  it("视频/音频组合", () => {
    expect(formatCodec("h264", "aac")).toBe("h264 / aac");
    expect(formatCodec("h264", null)).toBe("h264 / 无音频");
    expect(formatCodec(null, null)).toBe("—");
  });
});

describe("formatDateTime", () => {
  it("非法/空返回占位", () => {
    expect(formatDateTime(null)).toBe("—");
    expect(formatDateTime("not-a-date")).toBe("—");
  });
});
