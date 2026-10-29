-- Reproducible synthetic data. All dates are relative to initialization date.
INSERT INTO sales.departments VALUES (1,'华东事业部'),(2,'华南事业部'),(3,'华北事业部'),(4,'西部事业部');
INSERT INTO sales.customers
SELECT i, '模拟客户' || i, CASE WHEN i % 3 = 0 THEN '企业客户' ELSE '个人客户' END
FROM generate_series(1,200) i;
INSERT INTO sales.orders
SELECT (m-1)*400+(d-1)*100+i,
       1+((d*100+i)%200), d,
       (date_trunc('month', CURRENT_DATE)-make_interval(months=>m))::date + ((i-1)%28),
       CASE WHEN i%20=0 THEN 0 ELSE 100+(i%15)*20 END,
       CASE WHEN i%20=0 THEN 'cancelled' ELSE 'paid' END
FROM generate_series(1,6) m CROSS JOIN generate_series(1,4) d CROSS JOIN generate_series(1,100) i;
INSERT INTO sales.refunds
SELECT order_id*10, order_id, ordered_at+3, paid_amount*CASE WHEN (order_id-1)%100<5 THEN 0.2 ELSE 0.5 END,
       'completed', CASE WHEN department_id=3 THEN '商品质量' ELSE '客户退订' END
FROM sales.orders
WHERE status='paid' AND (order_id-1)%100+1 <= CASE
    WHEN department_id=3 AND ordered_at >= date_trunc('month',CURRENT_DATE)-interval '3 months' THEN 30
    WHEN department_id=1 THEN 12 WHEN department_id=2 THEN 8 ELSE 5 END;
-- Split refunds intentionally exercise deduplication and join fan-out prevention.
INSERT INTO sales.refunds
SELECT order_id*10+1, order_id, ordered_at+5, paid_amount*0.3, 'completed','分次退款'
FROM sales.orders WHERE (order_id-1)%100 < 5 AND status='paid';
INSERT INTO sales.refunds
SELECT order_id*10+2, order_id, ordered_at+2, paid_amount*0.5, 'rejected','审核拒绝'
FROM sales.orders WHERE (order_id-1)%100=60;
