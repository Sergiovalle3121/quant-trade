# File-reading evidence

“How your file was read” reconciles available totals printed in a platform summary
with totals calculated from the uploaded file. It is available before payment,
as before; it does not expose additional paid report sections or raw metadata.

Each compared platform figure carries `DECLARED`, and each calculated row figure
carries `MEASURED`. A comparison requires the calculated metric to be explicitly
`MEASURED` and finite. Trade counts must also be whole, non-negative numbers;
negative net P/L is valid. Unknown evidence, malformed containers, booleans,
non-finite values and overflowing numbers do not create a comparison. Older
reports without the relevant metadata simply have no reconciliation section.

The existing checks and tolerances are preserved: 0.5 for trade counts and 0.011
for net P/L, with the existing half-cent-per-trade rounding allowance. That
allowance uses only a valid measured trade count; otherwise its count is zero.
The public `_reading_rows` return value remains a list of four-element tuples.
No metric calculation, audit verdict, statistical criterion or access gate changes.

For MT5 partial closes, the importer records `closing_deals` by counting closing
rows of the Deals table. This is distinct from the number of closed positions:
one position can have several closing rows. The existing override is retained
only when the measured position count is valid and the finite whole closing-row
count equals the declared platform count. When those counts differ, the section
explains which count it shows; the original measured position metric is unchanged.
The platform summary is still declared evidence. This check does not authenticate
the uploaded file or the trading history.

Success is limited to the figures actually compared, within the reading tolerance.
It never certifies that missing totals agree. Spanish, English and Portuguese show
the same evidence tags and scope explanation. Data and stored evidence are not
modified during rendering, and arbitrary metadata is not displayed.

Regression coverage: `test_audit_reading.py`, `test_audit_reading_evidence.py` and
the existing MT language controls for partial closes and rounding.

Synthetic HTML was visually checked at desktop and 390 px mobile widths in all
three locales, without page overflow. The changed section of the application's
actual A4 PDFs was rendered and inspected in ES/EN/PT. Print styles use block
flow inside each figure to keep the evidence text within its badge: nested grid
alignment previously displaced the measured label in the PDF renderer. The
adjustment is confined to printing and does not change screen layout.
