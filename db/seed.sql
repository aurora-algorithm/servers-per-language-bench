-- 100,000 customers with 20 orders each (2,000,000 rows), the same rows on every run.
DROP TABLE IF EXISTS orders;
CREATE TABLE orders (
  id integer PRIMARY KEY,
  customer_id integer NOT NULL,
  status text NOT NULL,
  total_cents integer NOT NULL,
  items integer NOT NULL,
  created_at timestamptz NOT NULL
);
INSERT INTO orders
SELECT i,
       (i - 1) / 20 + 1,
       (ARRAY['paid', 'shipped', 'delivered', 'refunded'])[i % 4 + 1],
       500 + (i::bigint * 7919) % 50000,
       1 + (i * 31) % 9,
       timestamptz '2026-01-01 00:00:00+00' + ((i::bigint * 104729) % 26000000) * interval '1 second'
FROM generate_series(1, 2000000) AS i;
CREATE INDEX orders_customer_created ON orders (customer_id, created_at DESC);
VACUUM ANALYZE orders;
