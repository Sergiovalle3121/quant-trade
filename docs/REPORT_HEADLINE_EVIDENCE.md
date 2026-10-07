# Evidence on report headline figures

The HTML headline tiles and the PDF executive cover retain the evidence of each
figure, using the existing ES/EN/PT labels: measured, declared or not measured.
In particular, a platform's declared open-position drawdown remains declared
beside the measured drawdown calculated from the uploaded curve.

Compound tiles use every numeric component that is actually printed. Trade count
includes win rate; break-even includes pips only when pips appear; stress tiles
include the original result when their explanatory line prints that result.
Any declared component makes the tile declared. Missing, unknown or invalid
provenance withholds a measured label. A reference cost used only to select a
color does not change the evidence of the displayed figure.

This is a presentation change. The numeric KPI list, stored reports, thresholds,
verdicts and JSON contracts are unchanged. Values are not recomputed or upgraded
from declared evidence. The paywall still conceals figures and badges. Its
break-even tile now uses a fixed generic label: the previous dynamic label could
reveal the numeric pips threshold or the sign of the result while locked, including
through the accessibility label.

Regression tests in `tests/test_audit_kpi_evidence.py` cover all headline families,
compound sources, unknown provenance, the four PDF cover figures, and locked
positive/zero/negative thresholds in all three locales. Existing report, math,
skill, language, purchase-path and actual PDF tests were also exercised. Synthetic
A4 covers and strategy summaries were rendered with the application's own PDF
engine and visually inspected in ES/EN/PT. These checks do not use customer data
or establish production performance.
