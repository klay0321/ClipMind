export function Empty({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: React.ReactNode;
}) {
  return (
    <div
      data-testid="empty"
      className="flex flex-col items-center justify-center gap-2 px-6 py-16 text-center"
    >
      <div className="text-base font-medium text-gray-700">{title}</div>
      {description ? <div className="max-w-md text-sm text-gray-500">{description}</div> : null}
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  );
}
