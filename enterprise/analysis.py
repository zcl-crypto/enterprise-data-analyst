"""Evidence-based summaries and ECharts options; never execute model-generated JS."""
import json
from io import StringIO

import pandas as pd

from enterprise.business import LABELS, TERMS


def _chart(frame, x, y, group=None, kind='bar', title=None):
    if frame.empty or x not in frame or y not in frame:
        return None
    # Duplicate x coordinates must not silently disappear in a dict mapping.
    keys = [x] + ([group] if group else [])
    if frame.duplicated(keys).any():
        return None
    categories = sorted(frame[x].astype(str).unique()) if kind == 'line' else frame[x].astype(str).unique().tolist()
    parts = frame.groupby(group, dropna=False) if group else [(LABELS.get(y, y), frame)]
    series = []
    for name, part in parts:
        mapping = dict(zip(part[x].astype(str), part[y]))
        series.append({'name': str(name), 'type': kind,
                       'data': [None if pd.isna(mapping.get(k)) else float(mapping[k]) for k in categories],
                       'connectNulls': False, 'smooth': False})
    return {'title': title or LABELS.get(y, y), 'option': {
        'tooltip': {'trigger': 'axis', 'renderMode': 'richText'},
        'legend': {'type': 'scroll', 'bottom': 0},
        'grid': {'left': 60, 'right': 24, 'top': 30, 'bottom': 70, 'containLabel': True},
        'xAxis': {'type': 'category', 'data': categories},
        'yAxis': {'type': 'value', 'name': LABELS.get(y, y)},
        'series': series,
    }}


def analyze(csv_data, *, sql='', question='', truncated=False, dsl=None):
    df = pd.read_csv(StringIO(csv_data)) if csv_data.strip() else pd.DataFrame()
    records = json.loads(df.to_json(orient='records', date_format='iso', force_ascii=False))
    charts, insights, anomalies, kpis = [], [], [], []
    if df.empty:
        insights.append('当前查询没有返回数据，请检查时间范围、筛选条件与数据覆盖区间。')
    elif {'department_name', 'order_count', 'refunded_orders'}.issubset(df.columns):
        totals = df.groupby('department_name', as_index=False)[['order_count', 'refunded_orders']].sum()
        totals['refund_rate'] = 100 * totals.refunded_orders / totals.order_count.replace(0, float('nan'))
        denominator = int(totals.order_count.sum())
        numerator = int(totals.refunded_orders.sum())
        rate = 100*numerator/denominator if denominator else 0
        kpis = [{'label': '支付订单数', 'value': denominator}, {'label': '退款订单数', 'value': numerator},
                {'label': '订单退款率', 'value': f'{rate:.2f}%'}]
        totals = totals.sort_values('refund_rate', ascending=False)
        top = totals.iloc[0]
        insights.append(f'本次查询范围内订单退款率为 {rate:.2f}%（{numerator}/{denominator}）。最高为{top.department_name}，{top.refund_rate:.2f}%。')
        median = float(totals.refund_rate.median())
        for row in totals.itertuples():
            if row.order_count >= 30 and row.refund_rate > 20 and row.refund_rate > median * 2:
                anomalies.append({'dimension': row.department_name, 'value': round(row.refund_rate, 2),
                                  'evidence': f'{int(row.refunded_orders)}/{int(row.order_count)} 个订单；部门中位数 {median:.2f}%。'})
        charts.append(_chart(totals, 'department_name', 'refund_rate', title='各部门订单退款率'))
        if 'month' in df and 'refund_rate' in df:
            charts.append(_chart(df, 'month', 'refund_rate', 'department_name', 'line', '订单退款率月度趋势'))
        insights.append('部门汇总使用退款订单数 / 支付订单数重新计算，未对各月百分比直接取平均。')
    else:
        insights.append(f'查询返回 {len(df)} 行、{len(df.columns)} 列。')
        numeric = [c for c in df.select_dtypes(include='number').columns if not c.endswith('_id')]
        categorical = [c for c in df if c not in numeric and not c.endswith('_id')]
        # Honor the upstream DSL only when its referenced columns really exist.
        hints = (dsl or {}).get('config', {})
        x = 'month' if 'month' in df else hints.get('x_column')
        if x not in df:
            x = categorical[0] if categorical else None
        preferred = [c for c in ['sales_amount', 'refund_amount', 'refund_rate'] if c in numeric]
        y = preferred[0] if preferred else hints.get('y_column')
        if y not in numeric:
            y = numeric[0] if numeric else None
        if len(df) == 1 and numeric:
            kpis = [{'label': LABELS.get(c, c), 'value': None if pd.isna(df[c].iloc[0]) else float(df[c].iloc[0])} for c in numeric]
        if x and y:
            group = 'department_name' if x == 'month' and 'department_name' in df else None
            chart = _chart(df, x, y, group, 'line' if x == 'month' else 'bar')
            if chart:
                charts.append(chart)
            else:
                insights.append('结果包含重复坐标，已保留明细；请明确聚合口径后生成图表。')
            if x == 'month':
                for name, part in (df.groupby(group) if group else [('当前范围', df)]):
                    ordered = part.sort_values(x)
                    if len(ordered) >= 2 and not ordered[x].duplicated().any():
                        first, last = float(ordered[y].iloc[0]), float(ordered[y].iloc[-1])
                        change = f'{(last-first)/abs(first)*100:+.2f}%' if first else '基期为零，不能计算变化率'
                        insights.append(f'{name}：{ordered[x].iloc[0]} → {ordered[x].iloc[-1]}，{LABELS.get(y,y)}从 {first:,.2f} 到 {last:,.2f}，变化 {change}。')
    if truncated:
        insights.insert(0, '结果超过行数上限：以下图表与统计仅基于已返回行，不能作为完整总体结论。请缩小范围或在 SQL 中聚合。')
        anomalies = []
    return {'columns': list(df.columns), 'rows': records, 'row_count': len(df),
            'charts': [c for c in charts if c], 'insights': insights, 'anomalies': anomalies,
            'kpis': kpis, 'truncated': truncated, 'sql': sql, 'question': question,
            'definitions': TERMS, 'anomaly_note': TERMS['异常口径']}


def markdown_report(result):
    lines = ['# 经营数据分析报告', '', result['question'], '', '## 分析摘要', '']
    lines += ['- ' + text for text in result['insights']]
    if result['anomalies']:
        lines += ['', '## 待核查异常', '']
        lines += [f"- {item['dimension']}：{item['value']}%；{item['evidence']}" for item in result['anomalies']]
    lines += ['', result['anomaly_note'], '', '## 指标口径', '']
    lines += [f'- {k}：{v}' for k, v in result['definitions'].items()]
    lines += ['', '## 查询 SQL', '', '```sql', result['sql'], '```', '', '## 结果明细', '']
    columns = result['columns']
    def cell(value):
        return str(value).replace('|', '\\|').replace('\n', ' ')
    lines += ['| ' + ' | '.join(columns) + ' |', '| ' + ' | '.join(['---'] * len(columns)) + ' |'] if columns else []
    lines += ['| ' + ' | '.join(cell(row.get(c, '')) for c in columns) + ' |' for row in result['rows']]
    lines += ['', '数据为合成演示数据。统计异常表示待核查线索，不代表已证明的业务原因。']
    return '\n'.join(lines)
