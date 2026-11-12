Rails.application.routes.draw do
  get "up" => "rails/health#show", as: :rails_health_check
  get "health" => "rails/health#show"
  get "customers/:customer_id/orders" => "orders#index", constraints: { customer_id: /\d+/ }
end
