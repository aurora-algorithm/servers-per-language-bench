// The Go side: Gin, golang-jwt and pgx, the most used library for each job.
package main

import (
	"context"
	"errors"
	"log"
	"net/http"
	"os"
	"strconv"
	"strings"

	"github.com/gin-gonic/gin"
	"github.com/golang-jwt/jwt/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

const query = `SELECT id, status, total_cents, items,
  to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')
  FROM orders WHERE customer_id = $1 ORDER BY created_at DESC LIMIT 20`

type Order struct {
	ID         int32  `json:"id"`
	Status     string `json:"status"`
	TotalCents int32  `json:"total_cents"`
	Items      int32  `json:"items"`
	CreatedAt  string `json:"created_at"`
}

type Response struct {
	CustomerID int     `json:"customer_id"`
	Orders     []Order `json:"orders"`
}

type Claims struct {
	Scope string `json:"scope"`
	jwt.RegisteredClaims
}

func main() {
	secret := []byte(os.Getenv("JWT_SECRET"))
	if len(secret) == 0 {
		log.Fatal("JWT_SECRET is not set")
	}
	cfg, err := pgxpool.ParseConfig(os.Getenv("DATABASE_URL"))
	if err != nil {
		log.Fatal(err)
	}
	cfg.MaxConns = 32
	pool, err := pgxpool.NewWithConfig(context.Background(), cfg)
	if err != nil {
		log.Fatal(err)
	}
	parser := jwt.NewParser(jwt.WithValidMethods([]string{"HS256"}), jwt.WithExpirationRequired())
	keyFunc := func(*jwt.Token) (any, error) { return secret, nil }

	gin.SetMode(gin.ReleaseMode)
	r := gin.New()
	r.GET("/health", func(c *gin.Context) { c.String(http.StatusOK, "ok") })
	r.GET("/customers/:id/orders", func(c *gin.Context) {
		raw, ok := strings.CutPrefix(c.GetHeader("Authorization"), "Bearer ")
		if !ok {
			c.AbortWithStatus(http.StatusUnauthorized)
			return
		}
		var claims Claims
		if _, err := parser.ParseWithClaims(raw, &claims, keyFunc); err != nil || !hasScope(claims.Scope, "orders:read") {
			c.AbortWithStatus(http.StatusUnauthorized)
			return
		}
		id, err := strconv.Atoi(c.Param("id"))
		if err != nil {
			c.AbortWithStatus(http.StatusBadRequest)
			return
		}
		rows, err := pool.Query(c.Request.Context(), query, id)
		if err != nil {
			c.AbortWithStatus(http.StatusInternalServerError)
			return
		}
		defer rows.Close()
		orders := make([]Order, 0, 20)
		for rows.Next() {
			var o Order
			if err := rows.Scan(&o.ID, &o.Status, &o.TotalCents, &o.Items, &o.CreatedAt); err != nil {
				c.AbortWithStatus(http.StatusInternalServerError)
				return
			}
			orders = append(orders, o)
		}
		if err := rows.Err(); err != nil && !errors.Is(err, context.Canceled) {
			c.AbortWithStatus(http.StatusInternalServerError)
			return
		}
		c.JSON(http.StatusOK, Response{CustomerID: id, Orders: orders})
	})
	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}
	log.Fatal(r.Run("127.0.0.1:" + port))
}

func hasScope(scopes, want string) bool {
	for _, s := range strings.Fields(scopes) {
		if s == want {
			return true
		}
	}
	return false
}
