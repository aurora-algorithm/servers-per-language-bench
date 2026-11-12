// The Node side: Fastify, jsonwebtoken and pg (node-postgres), the most used package for each job.
// One process per core through node:cluster, because one Node process runs JavaScript on one thread.
import cluster from "node:cluster";
import Fastify from "fastify";
import jwt from "jsonwebtoken";
import pg from "pg";

const WORKERS = Number(process.env.WORKERS || 1);
const PORT = Number(process.env.PORT || 8080);
const SECRET = process.env.JWT_SECRET;
if (!SECRET) {
	throw new Error("JWT_SECRET is not set");
}

const QUERY = `SELECT id, status, total_cents, items,
  to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS created_at
  FROM orders WHERE customer_id = $1 ORDER BY created_at DESC LIMIT 20`;

async function startWorker() {
	const pool = new pg.Pool({
		connectionString: process.env.DATABASE_URL,
		max: 32,
	});
	const verify = (token) =>
		jwt.verify(token, SECRET, { algorithms: ["HS256"] });
	const app = Fastify({ logger: false });
	app.get("/health", async () => "ok");
	app.get("/customers/:id/orders", async (request, reply) => {
		const header = request.headers.authorization || "";
		if (!header.startsWith("Bearer ")) {
			return reply.code(401).send();
		}
		let claims;
		try {
			claims = verify(header.slice(7));
		} catch {
			return reply.code(401).send();
		}
		if (
			typeof claims.exp !== "number" ||
			!String(claims.scope || "")
				.split(" ")
				.includes("orders:read")
		) {
			return reply.code(401).send();
		}
		const id = Number.parseInt(request.params.id, 10);
		if (!Number.isInteger(id)) {
			return reply.code(400).send();
		}
		const { rows } = await pool.query({
			name: "orders",
			text: QUERY,
			values: [id],
		});
		return { customer_id: id, orders: rows };
	});
	await app.listen({ host: "127.0.0.1", port: PORT });
}

if (cluster.isPrimary && WORKERS > 1) {
	for (let i = 0; i < WORKERS; i += 1) {
		cluster.fork();
	}
	cluster.on("exit", (worker, code) => {
		console.error(`worker ${worker.process.pid} exited with ${code}`);
		process.exit(1);
	});
} else {
	startWorker().catch((err) => {
		console.error(err);
		process.exit(1);
	});
}
