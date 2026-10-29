"""Reviewed business semantics and sample queries; not an NL-to-SQL substitute."""
SCHEMA = {
    'sales.departments': {'department_id': 'INT', 'department_name': 'TEXT'},
    'sales.customers': {'customer_id': 'INT', 'customer_name': 'TEXT', 'segment': 'TEXT'},
    'sales.orders': {'order_id': 'INT', 'customer_id': 'INT', 'department_id': 'INT',
                     'ordered_at': 'DATE', 'paid_amount': 'DECIMAL', 'status': 'TEXT'},
    'sales.refunds': {'refund_id': 'INT', 'order_id': 'INT', 'refunded_at': 'DATE',
                      'refund_amount': 'DECIMAL', 'refund_status': 'TEXT', 'reason': 'TEXT'},
    'sales.order_metrics': {'order_id': 'INT', 'customer_id': 'INT', 'department_id': 'INT',
                            'department_name': 'TEXT', 'ordered_at': 'DATE', 'paid_amount': 'DECIMAL',
                            'status': 'TEXT', 'refund_amount': 'DECIMAL', 'refund_count': 'BIGINT',
                            'is_refunded': 'BOOLEAN'},
}
TERMS = {
    '订单退款率': '成功退款的去重订单数 / 已支付订单数 × 100%，按订单下单日期归属期间，排除取消订单。',
    '退款金额率': '成功退款金额 / 已支付金额 × 100%，与订单退款率不同；分次退款金额求和。',
    '最近三个月': '默认最近三个完整自然月，起点包含、终点不包含；不包含当前未结束月份。',
    '退款状态': '仅 refund_status=completed 计入退款，rejected 不计入。',
    '关联规则': 'orders.customer_id → customers.customer_id；orders.department_id → departments.department_id；refunds.order_id → orders.order_id。',
    '防止重复计算': '优先使用 sales.order_metrics 视图。该视图先按订单汇总退款，再关联订单与部门，每订单一行。',
    '异常口径': '部门至少30个已支付订单，订单退款率超过20%且超过本次部门中位数的2倍，标记为待核查；不是因果结论。',
    '数据性质': '本库全部为合成演示数据，退款原因仅为模拟标签。时间基准为数据库 CURRENT_DATE。',
}
DESCRIPTIONS = {
    'departments': '部门事业部维度，每部门一行；部门销售退款率分布关联 orders。',
    'customers': '客户维度，包含合成客户名称与个人/企业客户分群。',
    'orders': '订单事实表，每订单一行，paid为已支付，cancelled为取消；按ordered_at筛选时间。',
    'refunds': '退款流水，每订单可能有多次退款；仅completed计入，关联订单前应先汇总。',
    'order_metrics': '订单经营分析视图，每订单一行，包含部门、金额与去重退款标记。优先用于销售、订单退款率、趋势与部门对比。',
}
LABELS = {
    'order_id': '订单编号', 'customer_id': '客户编号', 'department_id': '部门编号',
    'department_name': '部门', 'customer_name': '客户名称', 'segment': '客户分群',
    'ordered_at': '下单日期', 'paid_amount': '支付金额', 'status': '订单状态',
    'refund_id': '退款流水编号', 'refunded_at': '退款日期', 'refund_amount': '退款金额',
    'refund_status': '退款状态', 'reason': '退款原因', 'refund_count': '成功退款次数',
    'is_refunded': '是否成功退款', 'month': '月份', 'order_count': '支付订单数',
    'refunded_orders': '退款订单数', 'refund_rate': '订单退款率（%）', 'sales_amount': '销售额（元）',
}
WINDOW = "ordered_at >= date_trunc('month', CURRENT_DATE) - interval '3 months' AND ordered_at < date_trunc('month', CURRENT_DATE)"
CASES = {
    'refund-trend': {
        'question': '分析最近三个完整自然月各部门的订单退款率，标记异常部门并展示趋势',
        'sql': f"""SELECT to_char(ordered_at, 'YYYY-MM') AS month, department_name,
COUNT(*) AS order_count, COUNT(*) FILTER (WHERE is_refunded) AS refunded_orders,
ROUND(100.0 * COUNT(*) FILTER (WHERE is_refunded) / NULLIF(COUNT(*),0),2) AS refund_rate
FROM sales.order_metrics WHERE status='paid' AND {WINDOW}
GROUP BY 1,2 ORDER BY 1,2""",
    },
    'sales-trend': {
        'question': '最近三个完整自然月各部门销售额趋势',
        'sql': f"""SELECT to_char(ordered_at,'YYYY-MM') AS month, department_name,
COUNT(*) AS order_count, SUM(paid_amount) AS sales_amount
FROM sales.order_metrics WHERE status='paid' AND {WINDOW}
GROUP BY 1,2 ORDER BY 1,2""",
    },
    'refund-reasons': {
        'question': '最近三个完整自然月的订单，其成功退款金额按原因如何分布',
        'sql': f"""SELECT r.reason, COUNT(DISTINCT r.order_id) AS refunded_orders,
SUM(r.refund_amount) AS refund_amount
FROM sales.refunds r JOIN sales.orders o ON o.order_id=r.order_id
WHERE o.status='paid' AND r.refund_status='completed' AND {WINDOW}
GROUP BY r.reason ORDER BY refund_amount DESC""",
    },
}
