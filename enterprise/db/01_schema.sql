CREATE SCHEMA sales;
CREATE TABLE sales.departments (
    department_id integer PRIMARY KEY,
    department_name text NOT NULL UNIQUE
);
CREATE TABLE sales.customers (
    customer_id integer PRIMARY KEY,
    customer_name text NOT NULL,
    segment text NOT NULL
);
CREATE TABLE sales.orders (
    order_id integer PRIMARY KEY,
    customer_id integer NOT NULL REFERENCES sales.customers,
    department_id integer NOT NULL REFERENCES sales.departments,
    ordered_at date NOT NULL,
    paid_amount numeric(12,2) NOT NULL CHECK (paid_amount >= 0),
    status text NOT NULL CHECK (status IN ('paid', 'cancelled'))
);
CREATE TABLE sales.refunds (
    refund_id integer PRIMARY KEY,
    order_id integer NOT NULL REFERENCES sales.orders,
    refunded_at date NOT NULL,
    refund_amount numeric(12,2) NOT NULL CHECK (refund_amount >= 0),
    refund_status text NOT NULL CHECK (refund_status IN ('completed', 'rejected')),
    reason text NOT NULL
);
CREATE INDEX ON sales.orders (ordered_at, department_id);
CREATE INDEX ON sales.refunds (order_id);

-- Cohort is defined by order date; successful refunds are aggregated per order.
CREATE VIEW sales.order_metrics AS
SELECT o.*, d.department_name, COALESCE(r.refund_amount, 0)::numeric AS refund_amount,
       COALESCE(r.refund_count, 0) AS refund_count,
       COALESCE(r.refund_count, 0) > 0 AS is_refunded
FROM sales.orders o
JOIN sales.departments d USING (department_id)
LEFT JOIN (
    SELECT order_id, SUM(refund_amount) AS refund_amount, COUNT(*) AS refund_count
    FROM sales.refunds WHERE refund_status = 'completed' GROUP BY order_id
) r USING (order_id);
