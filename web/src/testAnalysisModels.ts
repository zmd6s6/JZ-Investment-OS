// Synthetic metadata only; imported by tests, never by application components.
export const syntheticModel = { profile_id: "synthetic-model", name: "合成模型", model_name: "fixture-only", pricing_version: "synthetic-v1", pricing_currency: "USD", input_token_price: "0.000001", output_token_price: "0.000002" };
export const syntheticModelOptions = {
  schema_version: "1.0", configuration_hash: "a".repeat(64), profiles: [syntheticModel],
  default_bindings: ["MACRO", "INDUSTRY", "FUNDAMENTAL", "MARKET_QUANT", "EVENT", "DEVILS_ADVOCATE", "PORTFOLIO", "RISK"].map((role) => ({ role, profile: syntheticModel })), missing_roles: [],
};
