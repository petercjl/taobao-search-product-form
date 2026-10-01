# Natural-position title-root analysis

Source classes: U for the user-confirmed product-to-root evidence table and exploratory statistics; A for the following analysis and dictionary-maintenance design. Apply this method to each input without carrying over one product's sample-specific counts or opportunity conclusion.

## Purpose and boundary

Use only the cleaned `自然位` sheet, one first-seen row per `商品ID`. The input search phrase is an observed buyer query; the words inside product titles are seller-supplied descriptions, claims and search-optimization language. Title-root coverage is therefore **not** buyer query volume. A title-stated form or material is a claim to be checked against images, product details or other evidence, not a verified physical attribute.

Keep two grains: one product row per unique ID, and one product–canonical-root row per `(商品ID, facet, root)`. The latter retains original title, image URL, price, source `付款人数`, shop and every matching surface/span for convenient filtering. Product fields are duplicated only for viewability; aggregate across distinct product IDs, never by summing the entire exploded root table. A product can belong to several roots and root-level payment sums cannot be added together.

## Dictionary lifecycle

Use a versioned, shareable base lexicon at `references/title-lexicon.json` for phrase protection, aliases and semantic facets. A reviewed optional project lexicon may extend it. At the start of **each run**, merge these read-only lexicons, reject conflicting surface meanings, and save the exact source hashes, entries and tokenizer version in `lexicon_snapshot.json`. Do not rewrite the shared or project lexicon as a side effect of analyzing new titles.

Build a fresh per-run `lexicon_candidates.json` from frequent unclassified `jieba` segments, with product and shop coverage plus example product IDs. These are candidate additions, not automatic rules. In development mode, inspect candidate phrases, segmentation examples and semantic ambiguity with the user; approved improvements may be added to a reviewed project lexicon or a later separately authorized base-lexicon version. In ordinary run mode, keep candidates in the output for later review while the existing reviewed lexicon supports a low-interaction run. Re-running with an updated lexicon produces a new output directory and records the new dictionary hash.

The extractor uses a local `jieba` tokenizer for candidate segmentation, while longest protected lexicon phrases preserve domain expressions such as material and form claims. The same title may carry overlapping labels from different facets; within one facet a longer phrase takes precedence over an embedded shorter phrase. `jieba` segmentation is lexical evidence, not a trustworthy semantic category on its own. Preserve original surfaces and normalized-title character spans. Numeric sizes such as `24cm` are separately recognized as size claims. Brand and promotion words remain tagged or unclassified for audit; they are not silently removed from the source.

## Statistics and interpretation

For each root, calculate distinct-product coverage, shop coverage, price quartiles, median and upper-quartile displayed `付款人数`, and the fraction of products above the current dataset's 90th-percentile payment threshold. Show the actual threshold and count because ties can make the fraction differ from exactly 10%. Retain the product ID evidence and leading shops. For each shop, identify both its most common mapped roots and roots whose within-shop product coverage exceeds their corpus-wide coverage. The latter ratio is descriptive and needs a minimum of two shop products and five corpus products; it is not evidence of ad budget or intentional strategy. Show the corresponding visible-product payment values. For cross-facet root pairs, count distinct products carrying both claims; use these combinations to discover product propositions, not to assert a consumer segment.

Prioritize interpretation questions over a raw frequency list:

1. Which roots are nearly universal seller language and therefore weak product differentiators?
2. Which material/structure/use combinations occupy distinct price ranges and have actual natural-position payment records?
3. Is an apparent strong root spread across many shops, or concentrated in a few named sellers or brands?
4. What does one shop emphasize across its assortment, and which of those listings account for its visible payment evidence?
5. Which roots point to different possible physical forms or off-target products and need image review before comparing them?

Compare roots within plausible product-form and price groups where possible. A single search snapshot does not establish growth, elasticity, advertising return or unmet demand. Source `付款人数` has an unspecified period; do not rename it sales units or GMV. An observed price/traction contrast may be explained by brand, form, assortment width, search rank or other unobserved factors. Later visual classification is the authority for actual form.

## Output and QA

Run `scripts/analyze_title_roots.py --input CLEANED.xlsx --output-dir NEW_DIR` with optional `--project-lexicon REVIEWED.json`. The new directory contains `product_roots.json`, `root_summary.json`, `lexicon_snapshot.json` and `lexicon_candidates.json`; then write a separate evidence-backed human conclusion for the later report. Use counts and representative product IDs from the JSON, state the selected denominator, and mark proposed product-form or demand interpretations as hypotheses pending image or buyer-search evidence.

Check that the product count equals the cleaned natural sheet, every product ID is unique, each product–facet–root key appears once, price/payment values trace to the source row, and sampled long phrases, aliases, sizes and promotional words preserve expected boundaries. Inspect high-payment listings, rare forms and candidate terms manually before treating a root as a market signal. A failure of a required dependency or source field stops this module with a specific error; it must not fall back to unrecorded ad hoc segmentation.
