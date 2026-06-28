"use client";

import { useId } from "react";

import { cn } from "@/lib/cn";

// label + 控件 配对原语：保证每个输入都有可点击 label 与 htmlFor 绑定（可访问性）。

const CONTROL_CLS =
  "w-full rounded-md border border-gray-300 bg-white px-2.5 py-1.5 text-sm text-gray-800 focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand/40 disabled:cursor-not-allowed disabled:bg-gray-50";

export function Field({
  label,
  htmlFor,
  hint,
  className,
  children,
}: {
  label: React.ReactNode;
  htmlFor?: string;
  hint?: React.ReactNode;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <div className={cn("space-y-1", className)}>
      <label htmlFor={htmlFor} className="block text-xs font-medium text-gray-600">
        {label}
      </label>
      {children}
      {hint ? <p className="text-[11px] text-gray-400">{hint}</p> : null}
    </div>
  );
}

export function TextInput({
  label,
  hint,
  id,
  className,
  ...rest
}: React.InputHTMLAttributes<HTMLInputElement> & { label: React.ReactNode; hint?: React.ReactNode }) {
  const autoId = useId();
  const inputId = id ?? autoId;
  return (
    <Field label={label} htmlFor={inputId} hint={hint} className={className}>
      <input id={inputId} className={CONTROL_CLS} {...rest} />
    </Field>
  );
}

export function SelectInput({
  label,
  hint,
  id,
  className,
  children,
  ...rest
}: React.SelectHTMLAttributes<HTMLSelectElement> & { label: React.ReactNode; hint?: React.ReactNode }) {
  const autoId = useId();
  const selectId = id ?? autoId;
  return (
    <Field label={label} htmlFor={selectId} hint={hint} className={className}>
      <select id={selectId} className={CONTROL_CLS} {...rest}>
        {children}
      </select>
    </Field>
  );
}

export function TextArea({
  label,
  hint,
  id,
  className,
  ...rest
}: React.TextareaHTMLAttributes<HTMLTextAreaElement> & {
  label: React.ReactNode;
  hint?: React.ReactNode;
}) {
  const autoId = useId();
  const taId = id ?? autoId;
  return (
    <Field label={label} htmlFor={taId} hint={hint} className={className}>
      <textarea id={taId} className={cn(CONTROL_CLS, "resize-y")} {...rest} />
    </Field>
  );
}
