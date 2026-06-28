// 极简 className 合并工具（不引入 clsx 依赖，保持前端零额外依赖）。
export type ClassValue = string | number | false | null | undefined;

export function cn(...parts: ClassValue[]): string {
  return parts.filter(Boolean).join(" ");
}
