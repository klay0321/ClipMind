"use client";

import { useState } from "react";

import { Empty } from "@/components/states/Empty";
import { ErrorState } from "@/components/states/ErrorState";
import { Loading } from "@/components/states/Loading";
import { Button, Chip, Dialog, SelectInput, TextInput } from "@/components/ui";
import { ApiError } from "@/lib/api";
import {
  useCreateLegacyRule,
  useLegacyRuleAction,
  useLegacyRules,
  useSourceDirectories,
  useUpdateLegacyRule,
} from "@/lib/hooks";
import type {
  LegacyMatchOperator,
  LegacyMatchTarget,
  LegacyUsageRule,
} from "@/lib/types";

import { MATCH_OPERATOR_LABELS, MATCH_TARGET_LABELS } from "./legacyShared";

// 受控白名单（与后端一致；本阶段不支持任意正则）
const TARGETS = Object.keys(MATCH_TARGET_LABELS) as LegacyMatchTarget[];
const OPERATORS = Object.keys(MATCH_OPERATOR_LABELS) as LegacyMatchOperator[];

export function RulesPanel() {
  const [includeArchived, setIncludeArchived] = useState(false);
  const [editing, setEditing] = useState<LegacyUsageRule | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const query = useLegacyRules(includeArchived);
  const action = useLegacyRuleAction();

  return (
    <section aria-label="规则管理">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <label className="flex items-center gap-1.5 text-xs text-gray-500">
          <input
            type="checkbox"
            checked={includeArchived}
            onChange={(e) => setIncludeArchived(e.target.checked)}
          />
          显示已归档规则
        </label>
        <Button data-testid="create-rule-button" onClick={() => setShowCreate(true)}>
          + 新建规则
        </Button>
      </div>
      <p className="mb-3 text-xs text-gray-500">
        规则只支持受控匹配（目录名 / 文件名等 + 等于 / 包含 / 前后缀），不支持自由正则表达式。
        匹配输入来自系统已索引的路径记录，创建/修改规则不会扫描或改动任何文件。
      </p>

      {query.isLoading ? (
        <Loading rows={4} />
      ) : query.isError ? (
        <ErrorState message={(query.error as Error).message} onRetry={() => void query.refetch()} />
      ) : !query.data || query.data.items.length === 0 ? (
        <Empty
          title="还没有匹配规则"
          description='新建一条规则（例如 目录名 等于 某个历史标记）后，再运行只读预览。'
        />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white">
          <table className="w-full min-w-[820px] text-sm" data-testid="rules-table">
            <thead>
              <tr className="border-b border-gray-100 text-left text-xs text-gray-500">
                <th className="px-3 py-2 font-medium">规则名</th>
                <th className="px-3 py-2 font-medium">匹配条件</th>
                <th className="px-3 py-2 font-medium">范围</th>
                <th className="px-3 py-2 font-medium">状态</th>
                <th className="px-3 py-2 font-medium">证据数</th>
                <th className="px-3 py-2 font-medium">操作</th>
              </tr>
            </thead>
            <tbody>
              {query.data.items.map((rule) => (
                <tr
                  key={rule.id}
                  data-testid={`rule-row-${rule.id}`}
                  className="border-b border-gray-50 last:border-0 hover:bg-gray-50"
                >
                  <td className="max-w-[200px] px-3 py-2">
                    <div className="truncate font-medium text-gray-800" title={rule.name}>
                      {rule.name}
                    </div>
                    {rule.description ? (
                      <div className="truncate text-xs text-gray-400" title={rule.description}>
                        {rule.description}
                      </div>
                    ) : null}
                  </td>
                  <td className="px-3 py-2 text-gray-600">
                    {MATCH_TARGET_LABELS[rule.match_target]}{" "}
                    {MATCH_OPERATOR_LABELS[rule.match_operator]}{" "}
                    <code className="rounded bg-gray-100 px-1 py-0.5 text-xs">{rule.pattern}</code>
                    {rule.case_sensitive ? (
                      <span className="ml-1 text-xs text-gray-400">（区分大小写）</span>
                    ) : null}
                  </td>
                  <td className="px-3 py-2 text-xs text-gray-500">
                    {rule.source_directory_name ?? "全部源目录"}
                  </td>
                  <td className="px-3 py-2">
                    {rule.archived_at ? (
                      <Chip tone="muted">已归档</Chip>
                    ) : rule.enabled ? (
                      <Chip tone="success" dot>
                        启用
                      </Chip>
                    ) : (
                      <Chip tone="neutral">停用</Chip>
                    )}
                  </td>
                  <td className="px-3 py-2 text-gray-600">{rule.evidence_count}</td>
                  <td className="px-3 py-2">
                    <div className="flex flex-wrap gap-1.5">
                      {rule.archived_at ? (
                        <Button
                          size="sm"
                          variant="secondary"
                          disabled={action.isPending}
                          onClick={() => action.mutate({ id: rule.id, action: "restore" })}
                        >
                          恢复
                        </Button>
                      ) : (
                        <>
                          <Button
                            size="sm"
                            variant="secondary"
                            data-testid={`edit-rule-${rule.id}`}
                            onClick={() => setEditing(rule)}
                          >
                            编辑
                          </Button>
                          <Button
                            size="sm"
                            variant="secondary"
                            disabled={action.isPending}
                            data-testid={`toggle-rule-${rule.id}`}
                            onClick={() =>
                              action.mutate({
                                id: rule.id,
                                action: rule.enabled ? "disable" : "enable",
                              })
                            }
                          >
                            {rule.enabled ? "停用" : "启用"}
                          </Button>
                          <Button
                            size="sm"
                            variant="secondary"
                            disabled={action.isPending}
                            onClick={() => action.mutate({ id: rule.id, action: "archive" })}
                          >
                            归档
                          </Button>
                        </>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showCreate ? <RuleFormDialog onClose={() => setShowCreate(false)} /> : null}
      {editing ? <RuleFormDialog rule={editing} onClose={() => setEditing(null)} /> : null}
    </section>
  );
}

function RuleFormDialog({
  rule,
  onClose,
}: {
  rule?: LegacyUsageRule;
  onClose: () => void;
}) {
  const [name, setName] = useState(rule?.name ?? "");
  const [description, setDescription] = useState(rule?.description ?? "");
  const [target, setTarget] = useState<LegacyMatchTarget>(rule?.match_target ?? "directory_segment");
  const [operator, setOperator] = useState<LegacyMatchOperator>(rule?.match_operator ?? "equals");
  const [pattern, setPattern] = useState(rule?.pattern ?? "");
  const [caseSensitive, setCaseSensitive] = useState(rule?.case_sensitive ?? false);
  const [sourceDirId, setSourceDirId] = useState<string>(
    rule?.source_directory_id != null ? String(rule.source_directory_id) : "",
  );
  const create = useCreateLegacyRule();
  const update = useUpdateLegacyRule();
  const dirs = useSourceDirectories();
  const mutation = rule ? update : create;

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim() || !pattern.trim()) return;
    const payload = {
      name: name.trim(),
      description: description.trim() || undefined,
      match_target: target,
      match_operator: operator,
      pattern: pattern.trim(),
      case_sensitive: caseSensitive,
      source_directory_id: sourceDirId ? Number(sourceDirId) : undefined,
    };
    if (rule) {
      update.mutate(
        {
          id: rule.id,
          payload: { ...payload, source_directory_id: sourceDirId ? Number(sourceDirId) : null },
        },
        { onSuccess: onClose },
      );
    } else {
      create.mutate(payload, { onSuccess: onClose });
    }
  };

  return (
    <Dialog open title={rule ? "编辑规则" : "新建历史标记规则"} onClose={onClose}>
      <form onSubmit={submit} className="flex flex-col gap-3" data-testid="rule-form">
        <TextInput
          label="规则名"
          value={name}
          onChange={(e) => setName(e.target.value)}
          maxLength={200}
          placeholder='例如：历史"已使用"目录标记'
          data-testid="rule-name-input"
        />
        <div className="grid grid-cols-2 gap-3">
          <SelectInput
            label="匹配对象"
            value={target}
            onChange={(e) => setTarget(e.target.value as LegacyMatchTarget)}
            data-testid="rule-target-select"
          >
            {TARGETS.map((t) => (
              <option key={t} value={t}>
                {MATCH_TARGET_LABELS[t]}
              </option>
            ))}
          </SelectInput>
          <SelectInput
            label="匹配方式"
            value={operator}
            onChange={(e) => setOperator(e.target.value as LegacyMatchOperator)}
            data-testid="rule-operator-select"
          >
            {OPERATORS.map((o) => (
              <option key={o} value={o}>
                {MATCH_OPERATOR_LABELS[o]}
              </option>
            ))}
          </SelectInput>
        </div>
        <TextInput
          label="匹配值（不支持正则）"
          value={pattern}
          onChange={(e) => setPattern(e.target.value)}
          maxLength={256}
          placeholder="例如：已使用"
          data-testid="rule-pattern-input"
        />
        <div className="grid grid-cols-2 gap-3">
          <SelectInput
            label="限定源目录（可选）"
            value={sourceDirId}
            onChange={(e) => setSourceDirId(e.target.value)}
          >
            <option value="">全部源目录</option>
            {dirs.data?.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </SelectInput>
          <label className="flex items-end gap-1.5 pb-2 text-xs text-gray-600">
            <input
              type="checkbox"
              checked={caseSensitive}
              onChange={(e) => setCaseSensitive(e.target.checked)}
            />
            区分大小写
          </label>
        </div>
        <TextInput
          label="说明（可选）"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          maxLength={500}
          placeholder="这个历史标记的来历…"
        />
        {mutation.isError ? (
          <p className="text-xs text-red-600" data-testid="rule-form-error">
            {mutation.error instanceof ApiError ? mutation.error.message : "保存失败"}
          </p>
        ) : null}
        <div className="flex justify-end gap-2">
          <Button variant="secondary" type="button" onClick={onClose}>
            取消
          </Button>
          <Button
            type="submit"
            disabled={!name.trim() || !pattern.trim() || mutation.isPending}
            data-testid="rule-form-submit"
          >
            {mutation.isPending ? "保存中…" : rule ? "保存修改" : "创建规则"}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
