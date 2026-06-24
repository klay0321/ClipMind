export function Loading({ rows = 5 }: { rows?: number }) {
  return (
    <div data-testid="loading" className="animate-pulse space-y-3 p-4">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="h-12 rounded bg-gray-100" />
      ))}
    </div>
  );
}
