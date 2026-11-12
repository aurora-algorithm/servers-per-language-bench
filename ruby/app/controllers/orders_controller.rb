class OrdersController < ApplicationController
  QUERY = <<~SQL.freeze
    SELECT id, status, total_cents, items,
      to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS created_at
      FROM orders WHERE customer_id = $1 ORDER BY created_at DESC LIMIT 20
  SQL

  def index
    return head :unauthorized unless authorized?

    id = Integer(params[:customer_id], 10)
    rows = ActiveRecord::Base.connection.select_all(QUERY, "orders", [ id ]).to_a
    render json: { customer_id: id, orders: rows }
  end

  private

  def authorized?
    header = request.authorization.to_s
    return false unless header.start_with?("Bearer ")

    claims, = JWT.decode(header.delete_prefix("Bearer "), ENV.fetch("JWT_SECRET"), true,
                         algorithm: "HS256", required_claims: [ "exp" ])
    claims["scope"].to_s.split.include?("orders:read")
  rescue JWT::DecodeError
    false
  end
end
