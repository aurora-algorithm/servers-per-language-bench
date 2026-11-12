<?php

use App\Http\Controllers\OrdersController;
use Illuminate\Support\Facades\Route;

Route::get('/customers/{id}/orders', [OrdersController::class, 'index'])->whereNumber('id');
Route::get('/health', fn () => 'ok');
