# Sample-derived price-band analysis

Source classes: U for the user-confirmed dynamic Jenks method and clean-stage eligibility boundary; E for the observed workbook and the documented Jenks algorithm; A for the declared model-complexity and interpretation policy. Apply this method anew to each search export. Never carry over a previous run's numeric boundaries or conclusions.

## Population and price meaning

The fitted population is every unique product ID in the cleaned `自然位` sheet. This module does not decide whether a listing is the target product: if a future search term returns multiple incompatible product types, resolve the intended population in the upstream clean stage and record that decision there. On the current flat-pan test, every cleaned natural product participates. The `广告位` sheet contains display appearances, including repeats and ad-only IDs; fit no boundaries with those rows. Map their observed prices to the natural-derived bands solely for competitive context, preserving both appearance and unique-ad-product counts.

Fit `现价`, the source's displayed current price. A search result may advertise its cheapest SKU, promotion or a specification unlike another listing. `原价` is not a transaction price. The module requires positive finite current prices and unique natural IDs; fail visibly if those contracts are broken rather than silently dropping rows. Preserve all assignments by ID.

## Derive bands

Use one-dimensional weighted Jenks natural breaks on the logarithm of positive current prices. Repeated identical prices remain in one band. The log scale makes relative price changes comparable across low and high parts of a category; this is an analysis choice, not a universal consumer-psychology law. Optimize within-band squared log-price deviation; do not use equal-width or equal-count buckets.

Evaluate feasible band counts, each with a minimum sample support of 2% (at least two products) and a maximum candidate count of ten. Start with one band and accept an additional band while its marginal explained-variance gain reaches the declared 0.03 complexity penalty. These are method parameters to be audited and adjusted during Skill development, not fixed yuan thresholds. Publish the full candidate-fit curve and the chosen count. Probe penalties 0.02/0.03/0.04 and perform reproducible bootstrap resampling; if band count or boundaries move substantially, report the result as provisional and examine the source rather than asserting a sharp market boundary. The deterministic script implements and records the exact parameters.

The boundary is the first observed price in the next band. Intervals are lower-inclusive and upper-exclusive, with an open upper end for the final band. Present actual source-price min/median/max and counts so users can see how the fitted ranges relate to the listings. Avoid cosmetically rounding a fitted boundary to a familiar number unless a later, separately tested consumer-price rule supports it.

## Interpret for selection

For each band, compare natural product count/share, distinct shop count, observed median `付款人数`, and advertising appearance/unique-product presence under the same boundaries. A large band means many visible listings, not automatically more buyer demand. `付款人数` has no verified observation window or exposure denominator, so it is a traction clue, not conversion rate, units, GMV or estimated demand. Ads are placement evidence, not spend, auction pressure or ROI. Explain differences among bands in ordinary language, identify where follow-up SKU/price and visual-form checks would change the selection decision, and do not infer a white-label entry price from the distribution alone.

## Output and QA

Run `scripts/analyze_price_bands.py --input CLEANED.xlsx --output-dir NEW_DIR`. It creates `price_band_detail.json` (one product-band row per natural ID and ad-appearance rows) and `price_band_summary.json` (source hash, method, candidate models, selected boundaries, sensitivity, bootstrap stability, band metrics and reconciliations). Write a separate Markdown conclusion that can stand without the JSON and cite the actual sample figures. Register all three artifacts in the ledger under `classify/price`.

Verify workbook hash, all natural IDs assigned exactly once, band counts summing to the natural population, advertising appearances summing to the ad sheet, no duplicate-price splits, and boundary intervals covering every displayed current price. Inspect the 0.02/0.03/0.04 sensitivity and bootstrap intervals before phrasing boundaries as stable. If a later visual product-form module finds materially different populations, refit the price bands only after the user approves a new upstream eligibility choice or a distinct within-form analysis; preserve this run's original result.
