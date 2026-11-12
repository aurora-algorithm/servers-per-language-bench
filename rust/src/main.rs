//! The Rust side: axum on tokio, jsonwebtoken and sqlx, the most used crate for each job.
use axum::{
    extract::{Path, State},
    http::{HeaderMap, StatusCode},
    routing::get,
    Json, Router,
};
use jsonwebtoken::{decode, Algorithm, DecodingKey, Validation};
use serde::{Deserialize, Serialize};
use sqlx::postgres::{PgPool, PgPoolOptions};
use std::sync::Arc;

const QUERY: &str = r#"SELECT id, status, total_cents, items,
  to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')
  FROM orders WHERE customer_id = $1 ORDER BY created_at DESC LIMIT 20"#;

#[derive(Serialize, sqlx::FromRow)]
struct Order {
    id: i32,
    status: String,
    total_cents: i32,
    items: i32,
    #[sqlx(rename = "to_char")]
    created_at: String,
}

#[derive(Serialize)]
struct Response {
    customer_id: i32,
    orders: Vec<Order>,
}

#[derive(Deserialize)]
struct Claims {
    #[allow(dead_code)]
    exp: u64,
    scope: String,
}

struct AppState {
    pool: PgPool,
    key: DecodingKey,
    validation: Validation,
}

async fn orders(
    State(state): State<Arc<AppState>>,
    Path(id): Path<i32>,
    headers: HeaderMap,
) -> Result<Json<Response>, StatusCode> {
    let token = headers
        .get("authorization")
        .and_then(|v| v.to_str().ok())
        .and_then(|v| v.strip_prefix("Bearer "))
        .ok_or(StatusCode::UNAUTHORIZED)?;
    let claims = decode::<Claims>(token, &state.key, &state.validation)
        .map_err(|_| StatusCode::UNAUTHORIZED)?
        .claims;
    if !claims.scope.split_whitespace().any(|s| s == "orders:read") {
        return Err(StatusCode::UNAUTHORIZED);
    }
    let orders = sqlx::query_as::<_, Order>(QUERY)
        .bind(id)
        .fetch_all(&state.pool)
        .await
        .map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?;
    Ok(Json(Response {
        customer_id: id,
        orders,
    }))
}

fn main() {
    let workers: usize = std::env::var("TOKIO_WORKER_THREADS")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or_else(|| {
            std::thread::available_parallelism()
                .map(|n| n.get())
                .unwrap_or(1)
        });
    tokio::runtime::Builder::new_multi_thread()
        .worker_threads(workers)
        .enable_all()
        .build()
        .expect("tokio runtime")
        .block_on(run());
}

async fn run() {
    let secret = std::env::var("JWT_SECRET").expect("JWT_SECRET is not set");
    let url = std::env::var("DATABASE_URL").expect("DATABASE_URL is not set");
    let pool = PgPoolOptions::new()
        .max_connections(32)
        .connect(&url)
        .await
        .expect("connect to postgres");
    let mut validation = Validation::new(Algorithm::HS256);
    validation.validate_exp = true;
    let state = Arc::new(AppState {
        pool,
        key: DecodingKey::from_secret(secret.as_bytes()),
        validation,
    });
    let app = Router::new()
        .route("/health", get(|| async { "ok" }))
        .route("/customers/{id}/orders", get(orders))
        .with_state(state);
    let port = std::env::var("PORT").unwrap_or_else(|_| "8080".into());
    let listener = tokio::net::TcpListener::bind(format!("127.0.0.1:{port}"))
        .await
        .expect("bind");
    axum::serve(listener, app).await.expect("serve");
}
