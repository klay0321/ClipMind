// 匹配理由 / 不匹配项 / 风险提示：全部直接展示后端规则派生结果。
// 视觉区分：理由=正向(绿)，不匹配=警告(琥珀)，风险=高优先(红)。前端绝不推测画面对象/产品/风险/场景/动作。

function ReasonGroup({
  testid,
  label,
  items,
  icon,
  tone,
  max,
}: {
  testid: string;
  label: string;
  items: string[];
  icon: string;
  tone: string;
  max?: number;
}) {
  if (!items || items.length === 0) return null;
  const shown = max != null ? items.slice(0, max) : items;
  const rest = items.length - shown.length;
  return (
    <div className="space-y-1" data-testid={testid}>
      <div className="flex items-center gap-1 text-[11px] font-medium text-gray-600">
        <span aria-hidden>{icon}</span>
        <span>
          {label}
          <span className="ml-1 text-gray-400">({items.length})</span>
        </span>
      </div>
      <ul className="flex flex-wrap gap-1">
        {shown.map((x, i) => (
          <li key={`${x}-${i}`} className={`rounded px-1.5 py-0.5 text-[11px] ${tone}`}>
            {x}
          </li>
        ))}
        {rest > 0 ? (
          <li className="rounded px-1.5 py-0.5 text-[11px] text-gray-400">+{rest}</li>
        ) : null}
      </ul>
    </div>
  );
}

export function MatchExplanation({
  matchedReasons,
  unmatched,
  riskWarnings,
  max,
}: {
  matchedReasons: string[];
  unmatched: string[];
  riskWarnings: string[];
  max?: number;
}) {
  if (
    (!matchedReasons || matchedReasons.length === 0) &&
    (!unmatched || unmatched.length === 0) &&
    (!riskWarnings || riskWarnings.length === 0)
  ) {
    return null;
  }
  return (
    <div className="space-y-2" data-testid="match-explanation">
      <ReasonGroup
        testid="matched-reasons"
        label="匹配理由"
        items={matchedReasons}
        icon="✓"
        tone="bg-emerald-50 text-emerald-700"
        max={max}
      />
      <ReasonGroup
        testid="unmatched-requirements"
        label="不匹配项"
        items={unmatched}
        icon="!"
        tone="bg-amber-50 text-amber-700"
        max={max}
      />
      <ReasonGroup
        testid="risk-warnings"
        label="风险提示"
        items={riskWarnings}
        icon="⚠"
        tone="bg-red-100 text-red-700"
      />
    </div>
  );
}
