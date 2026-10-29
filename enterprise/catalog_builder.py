"""Build the upstream file-system catalog from the reviewed business policy."""
import csv
import json
from pathlib import Path

import yaml

from enterprise.business import CASES, DESCRIPTIONS, LABELS, SCHEMA, TERMS

CATALOG_PATH = Path(__file__).resolve().parent / 'catalog'


def build_catalog():
    CATALOG_PATH.mkdir(exist_ok=True)
    info, columns, common = {}, [], {}
    for full_name, fields in SCHEMA.items():
        namespace, name = full_name.split('.')
        info.setdefault(namespace, {})[name] = {
            'description': DESCRIPTIONS[name],
            'selection_rule': DESCRIPTIONS[name],
            'sql_rule': '\n'.join(TERMS.values()),
        }
        for column, kind in fields.items():
            columns.append({'db_name': namespace, 'table_name': name, 'column_name': column})
            common[column] = {'column_name': column, 'type': kind,
                              'display_name': LABELS[column], 'alias': LABELS[column],
                              'category': 'metric' if 'amount' in column or 'count' in column else 'dimension',
                              'description': LABELS[column] + ' ' + column}
    (CATALOG_PATH / 'table_info.yaml').write_text(yaml.safe_dump(info, allow_unicode=True), encoding='utf-8')
    for filename, rows in [('table_columns.csv', columns), ('common_columns.csv', list(common.values()))]:
        with (CATALOG_PATH / filename).open('w', newline='', encoding='utf-8') as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    examples = '\n\n'.join('Q: ' + case['question'] + '\nA: ' + case['sql']
                           for key, case in CASES.items() if key != 'refund-reasons')
    reason = CASES['refund-reasons']
    (CATALOG_PATH / 'sql_example.yaml').write_text(
        yaml.safe_dump({'sales': {'order_metrics': examples,
                                 'refunds': 'Q: ' + reason['question'] + '\nA: ' + reason['sql']}},
                       allow_unicode=True), encoding='utf-8')
    with (CATALOG_PATH / 'table_selection_example.csv').open('w', newline='', encoding='utf-8') as handle:
        writer = csv.writer(handle)
        writer.writerow(['question', 'selected_tables'])
        for key, case in CASES.items():
            tables = ['sales.refunds', 'sales.orders'] if key == 'refund-reasons' else ['sales.order_metrics']
            writer.writerow([case['question'], json.dumps(tables)])
    bi = {
        'basic_knowledge_glossary': '\n'.join(f'{k}: {v}' for k, v in TERMS.items()),
        'text2sql_extra_rule': '仅生成一个PostgreSQL SELECT。使用sales限定表名。禁止DDL/DML。'
            '必须显式列出查询字段，不得使用SELECT *或table.*；COUNT(*)可用于统计行数。'
            '订单退款率用refund_rate，支付订单数用order_count，退款订单数用refunded_orders，'
            '月份用month，部门用department_name。需要趋势时同时保留月份和部门维度。'
            '退款原因用reason，成功退款金额用refund_amount，销售额用sales_amount。'
            '以上英文名是结果接口字段名，必须使用；中文展示由前端完成，不要以中文展示名替换输出别名。'
            '异常标记由应用基于返回的订单计数统一计算；SQL只返回所需粒度的事实指标，不额外生成异常标记、部门总计或中位数列。'
            '不要对已计算的退款率取平均，应使用去重退款订单数除以支付订单数。',
        'table_selection_extra_rule': '销售、退款率、部门趋势优先使用sales.order_metrics；原因分析需sales.refunds关联sales.orders。',
    }
    (CATALOG_PATH / 'bi.yaml').write_text(yaml.safe_dump(bi, allow_unicode=True), encoding='utf-8')


if __name__ == '__main__':
    build_catalog()
    print('Business catalog generated.')
