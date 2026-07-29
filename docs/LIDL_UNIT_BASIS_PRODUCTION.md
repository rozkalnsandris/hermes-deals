# Lidl unit-basis production contract

Variable-weight Lidl offers are explicitly separated from ordinary fixed-package offers.

Supported `pricing_mode` values:
- `fixed_package`
- `unit_price_only`
- `example_total_plus_unit`
- `app_example_total_plus_unit`

For unit-basis rows, `unit_price_eur` and `unit_label` preserve the actual sale basis.
`example_weight_g` identifies advertised example-total prices.
`regular_unit_price_eur` preserves an advertised reference unit price.

Variable-weight Review approval fails closed until this truth is explicit.
Unit-basis offers are deliberately excluded from canonical fixed-package price comparison and basket logic until those layers become unit-aware.
