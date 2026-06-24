export function ErrorState({
  message,
  onRetry,
}: {
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div
      data-testid="error"
      className="flex flex-col items-center justify-center gap-3 px-6 py-16 text-center"
    >
      <div className="text-base font-medium text-red-600">加载失败</div>
      <div className="max-w-md text-sm text-gray-500">{message}</div>
      {onRetry ? (
        <button
          type="button"
          onClick={onRetry}
          className="rounded-md border border-gray-300 bg-white px-4 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
        >
          重试
        </button>
      ) : null}
    </div>
  );
}
