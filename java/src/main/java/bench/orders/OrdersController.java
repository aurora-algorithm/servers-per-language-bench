package bench.orders;

import io.jsonwebtoken.Claims;
import io.jsonwebtoken.JwtException;
import io.jsonwebtoken.JwtParser;
import io.jsonwebtoken.Jwts;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.List;
import javax.crypto.spec.SecretKeySpec;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RestController;

@RestController
class OrdersController {
  static final String QUERY =
      """
      SELECT id, status, total_cents, items,
        to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')
        FROM orders WHERE customer_id = ? ORDER BY created_at DESC LIMIT 20\
      """;

  record Order(int id, String status, int totalCents, int items, String createdAt) {}

  record Reply(int customerId, List<Order> orders) {}

  private final JdbcClient jdbc;
  private final JwtParser parser;

  OrdersController(JdbcClient jdbc, @Value("${JWT_SECRET}") String secret) {
    this.jdbc = jdbc;
    var key = new SecretKeySpec(secret.getBytes(StandardCharsets.UTF_8), "HmacSHA256");
    this.parser = Jwts.parser().verifyWith(key).build();
  }

  @GetMapping("/customers/{id}/orders")
  ResponseEntity<Reply> orders(
      @PathVariable int id,
      @RequestHeader(name = "Authorization", required = false) String authorization) {
    if (authorization == null || !authorization.startsWith("Bearer ")) {
      return ResponseEntity.status(HttpStatus.UNAUTHORIZED).build();
    }
    Claims claims;
    try {
      claims = parser.parseSignedClaims(authorization.substring(7)).getPayload();
    } catch (JwtException | IllegalArgumentException e) {
      return ResponseEntity.status(HttpStatus.UNAUTHORIZED).build();
    }
    if (claims.getExpiration() == null || !hasScope(claims.get("scope", String.class))) {
      return ResponseEntity.status(HttpStatus.UNAUTHORIZED).build();
    }
    List<Order> orders =
        jdbc.sql(QUERY)
            .param(id)
            .query((rs, n) ->
                new Order(
                    rs.getInt(1), rs.getString(2), rs.getInt(3), rs.getInt(4), rs.getString(5)))
            .list();
    return ResponseEntity.ok(new Reply(id, orders));
  }

  @GetMapping("/health")
  String health() {
    return "ok";
  }

  private static boolean hasScope(String scopes) {
    return scopes != null && Arrays.asList(scopes.split(" ")).contains("orders:read");
  }
}
