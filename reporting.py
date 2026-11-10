"""Render measured values without claiming clinical acceptance from demos."""
import csv
import json


def render_report(output_dir, manifest, summaries, comparisons):
    with (output_dir/'summary.csv').open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['variant'] + list(next(iter(summaries.values()))))
        writer.writeheader()
        writer.writerows(dict(variant=k, **v) for k, v in summaries.items())
    (output_dir/'comparisons.json').write_text(json.dumps(comparisons, ensure_ascii=False, indent=2), encoding='utf-8')
    with (output_dir/'comparisons.csv').open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['comparison', 'metric', 'baseline', 'candidate',
            'difference', 'relative_improvement_percent', 'difference_ci95'])
        writer.writeheader()
        for name, metrics in comparisons.items():
            for metric, values in metrics.items():
                writer.writerow(dict(comparison=name, metric=metric, **values))
    lines = ['# 优化验收记录', '', '结论：证据不足。演示流程或未审核标签不能证明医学提升。', '',
             '每项原始值与配对差值见 summary.csv、comparisons.json；未知 token 为 null。', '',
             '| 变体 | 尝试 | 动作正确率 | 自动完成覆盖率 | 平均 token |', '|---|---:|---:|---:|---:|']
    for name, row in summaries.items():
        lines.append(f"| {name} | {row['attempts']} | {row['accuracy']} | {row['coverage']} | {row['mean_tokens']} |")
    lines += ['', '## 单项、融合与移除模块对照', '', '```json', json.dumps(comparisons, ensure_ascii=False, indent=2), '```', '',
              '未实施：S3 采样基线、审核冻结意见挑战集、正式医学标注评估、微调、并行化。',
              '未测指标：独立证据支持率、挑战集纠错率、费用与完整主验收置信区间。',
              '本记录不将路由匹配率视为医学动作正确率。']
    (output_dir/'acceptance.md').write_text('\n'.join(lines), encoding='utf-8')
