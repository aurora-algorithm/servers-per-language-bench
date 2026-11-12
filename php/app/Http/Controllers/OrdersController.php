<?php

namespace App\Http\Controllers;

use DomainException;
use Firebase\JWT\JWT;
use Firebase\JWT\Key;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Illuminate\Http\Response;
use Illuminate\Support\Facades\DB;
use InvalidArgumentException;
use UnexpectedValueException;

class OrdersController extends Controller
{
    private const QUERY = <<<'SQL'
        SELECT id, status, total_cents, items,
          to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS created_at
          FROM orders WHERE customer_id = ? ORDER BY created_at DESC LIMIT 20
        SQL;

    public function index(Request $request, int $id): JsonResponse|Response
    {
        $token = $request->bearerToken();
        if ($token === null) {
            return response('', 401);
        }
        try {
            $claims = JWT::decode($token, new Key(config('app.jwt_secret'), 'HS256'));
        } catch (UnexpectedValueException|DomainException|InvalidArgumentException) {
            return response('', 401);
        }
        $scopes = explode(' ', (string) ($claims->scope ?? ''));
        if (! isset($claims->exp) || ! in_array('orders:read', $scopes, true)) {
            return response('', 401);
        }

        return response()->json(['customer_id' => $id, 'orders' => DB::select(self::QUERY, [$id])]);
    }
}
