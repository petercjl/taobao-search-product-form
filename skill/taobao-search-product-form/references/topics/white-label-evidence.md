# From product observations to opportunity cards

## Question and candidate grain

The goal is to help a user decide what to research next, not to declare that a product can or cannot be sold. Begin with the image-grounded **whole-product style prototypes**: each is a coherent, sourceable merchandise option. Structural form, product-design cues and image-supported use tasks explain why a prototype is distinct and provide optional comparison cuts; a task becomes meaningful only when it implies a physical product difference, not merely new copy or a hero-image theme. An image-supported use task is not a verified buyer demographic.

Compare each prototype against its closest real-product alternatives and, where useful, the broader structural parent. Form–style and form–task intersections are secondary cuts when their member IDs and shop spread support interpretation. Candidate groups overlap, including listings that display more than one product style; their counts cannot be summed. Do not impose a permanent minimum count across categories. For sparse groups, report the observed products and roll the commercial comparison back to a better-supported comparable group. An unclassified task means insufficient image evidence, not absence of task demand. Preserve uncertain/non-target products outside candidate traction calculations until their boundary is reviewed.

## Five evidence questions

1. **Observed traction.** Examine distinct natural products and shops, the distribution of displayed `付款人数`, representative high-payment and ordinary products, and whether the group's apparent strength survives removal of its leading shop or product. A sum across product records is a descriptive index, not distinct buyers, monthly sales, units, conversion or GMV. A single search export cannot establish a growth trend or full-market share.
2. **Comparable price structure.** Use the run's fitted price bands to locate supply, then compare like products within the same structure and the closest observable configuration. Report price median and spread, not only an average. Search-page current price may select a different SKU or discount; a higher displayed price is not proven willingness to pay or margin.
3. **Merchant-line configuration.** For representative shops, contrast the candidate products with the same shop's other visible forms, versions and price tiers; identify natural-position strong products separately from products appearing in advertising positions. Describe the observed assortment. SKU roles, intentional product strategy and brand ownership remain hypotheses until separately verified. A multi-shop pattern has different implications from a group carried mainly by one shop.
4. **Competitive exposure.** Keep ad appearances, distinct ad products and distinct advertiser shops separate. Connect natural products to ads by product ID and exact shop name; preserve cross-shop name conflicts and ad-only products as unknown-form or unknown-payment cases. Advertising can indicate both seller attention and acquisition pressure; it does not measure spend, exposure or ROI.
5. **Product-side opening.** State which visible structural, material-appearance, color-system, handle, size or task-fit variation could make the proposed product different. Check whether existing merchants already cover it. Title roots are seller claims and discovery clues; image labels are visible observations; reviews, specifications, supplier quotes and tests are needed to establish user benefit, material truth, manufacturability and defects. Listing address may guide sourcing questions but does not identify a factory.

Compare competing explanations explicitly. For example, a candidate may show high displayed payment because of one established shop, a lower price, stronger natural ranking, a different underlying product configuration, or multiple shops independently selling it. Where the current export cannot distinguish these, present the alternatives and the discriminating next check. Do not smooth contradictions into an opaque score or infer that low ad presence means low competition.

## Opportunity-card contract

Create `opportunity_cards.json` with `schema_version: 2`, `source_evidence_sha256` (the current comparison JSON file's exact SHA-256), selected strategy/version and an array of cards. Each card's `candidate_id` resolves to a `product_style` candidate. Secondary form/style/task candidate IDs may appear as evidence references or comparison context. A readable Markdown rendering carries the same content.

| Field | Required meaning |
| --- | --- |
| `candidate_id`, `definition`, `parent_comparison` | Exact whole-product style member set and concrete product-side proposition, with the closest comparable prototype or broader structural form used for context. |
| `scope` | Source population, tagged/uncertain coverage, member product/shop counts, missing modules and search-snapshot limitations. |
| `observations` | Numeric traction, price, merchant-line, advertising, title and location facts, each linked to the compare artifact's field or product IDs. |
| `supporting_evidence`, `counterevidence` | Separate, traceable items; an empty side must say evidence is unavailable, not imply proof. |
| `interpretation` | A bounded explanation that considers shop, price and product-configuration alternatives. |
| `unknowns` | Missing facts that could reverse the current research priority. |
| `next_checks` | Specific review, SKU/price, cost, supplier or small-test questions; indicate what result would change the judgment. |
| `research_order` | Optional reasoned research sequence relative to other cards, never a binary market-entry decision or composite score. |

Every card should be readable without opening the raw JSON, while every named number and shop claim must trace back to the compare artifact. Keep observation, inference and proposed test visibly distinct. Include at least one representative product and one ordinary or counterexample product when available; show if the sample is too small for that comparison. The cards are complete when the user can inspect both the reason to investigate and the strongest reason that it may be misleading.

## Handoff boundary

The card may suggest a profit calculation or supplier investigation because those checks resolve uncertainty. It cannot conclude net margin, a verified unmet need, factory access, or an entry decision from a search snapshot. The broader product-development method separates demand, product differentiation, net profit, supplier standards and low-risk testing. Defer the last three to their own evidence-gathering stages; do not represent a request for research as authorization to buy, stock or publish.
