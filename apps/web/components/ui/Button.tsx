"use client";

import { forwardRef } from "react";

import { cn } from "@/lib/cn";

// 统一按钮：每个区域只允许一个 primary；危险操作用 danger；次级用 secondary/ghost。
export type ButtonVariant = "primary" | "secondary" | "outline" | "ghost" | "danger";
export type ButtonSize = "sm" | "md";

const VARIANTS: Record<ButtonVariant, string> = {
  primary: "bg-brand text-white border border-transparent hover:bg-brand-dark",
  secondary: "bg-white text-gray-700 border border-gray-300 hover:bg-gray-50",
  outline: "bg-transparent text-brand-dark border border-brand/40 hover:bg-brand-light",
  ghost: "bg-transparent text-gray-600 border border-transparent hover:bg-gray-100",
  danger: "bg-white text-red-600 border border-red-300 hover:bg-red-50",
};

const SIZES: Record<ButtonSize, string> = {
  sm: "px-2.5 py-1 text-xs gap-1",
  md: "px-3.5 py-1.5 text-sm gap-1.5",
};

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
}

function Spinner() {
  return (
    <span
      aria-hidden
      className="h-3 w-3 animate-spin rounded-full border-2 border-current border-r-transparent opacity-70"
    />
  );
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  {
    variant = "secondary",
    size = "md",
    loading = false,
    disabled,
    className,
    children,
    type = "button",
    ...rest
  },
  ref,
) {
  return (
    <button
      ref={ref}
      // eslint-disable-next-line react/button-has-type
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={cn(
        "inline-flex items-center justify-center whitespace-nowrap rounded-md font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/40 disabled:cursor-not-allowed disabled:opacity-50",
        VARIANTS[variant],
        SIZES[size],
        className,
      )}
      {...rest}
    >
      {loading ? <Spinner /> : null}
      {children}
    </button>
  );
});
