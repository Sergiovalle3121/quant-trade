# Account histories from Myfxbook, MQL5 signals and FX Blue

Checked on 2026-09-25. Investors who want to check a trader before copying
them usually hold a Myfxbook, FX Blue or MQL5.com signal link, not a
MetaTrader file. Each of these sites lets the account's owner (or, for an
MQL5 signal, a logged-in visitor) download the trade history as CSV.

The files below were downloaded from public GitHub repositories to a scratch
directory outside the repository and are **not committed**. The tests in
`tests/test_audit_tracking_exports.py` use synthetic files with the same
layout.

## Files

| Source | Files | Layout |
|---|---|---|
| Myfxbook | 6 exports and 2 copies of the history page | `Tags,Ticket,Open Date,Close Date,Symbol,Action,Units/Lots,SL,TP,Open Price,Close Price,Commission,Swap,Pips,Profit,Gain,...`, comma, `MM/DD/YYYY HH:MM`; an "Open Trades" section with its own header at the end |
| MQL5 signal | 3 positions files and 2 history files, plus 1 more positions file | `Time;Type;Volume;Symbol;Price;[S/L;T/P;|Volume;]Time;Price;Commission;Swap;Profit[;Comment]`, semicolon, `YYYY.MM.DD HH:MM:SS`, a space as thousands separator in history files |
| FX Blue | 1 | `sep=,` line, then `Type,Ticket,Symbol,Lots,Buy/sell,Open price,Close price,Open time,Close time,...,Profit,Swap,Commission,Net profit,...,Account`, `YYYY/MM/DD HH:MM:SS` |

What each row means:

- Myfxbook `Profit` is net of commission and swap, in the account's currency. Checked on
  two trades: 0.47 lots USDJPY, 26.7 pips, gross 88.00 USD, commission -1.69,
  Profit 86.31. A EUR account's EURUSD trade matches the same way once converted.
- MQL5 `Profit` is gross, as MetaTrader prints it (0.02 lots AUDUSD, 16 pips, Profit 3.20,
  swap -0.02 apart).
- FX Blue `Net profit` = `Profit` + `Swap` + `Commission`.
- Deposits and withdrawals: Myfxbook and FX Blue `Deposit`/`Withdrawal` rows;
  MQL5 `Balance` rows (including small balance adjustments).

## Result

All 15 files import with no crash and no row dropped as unreadable. The
trade counts match the files' closed-trade rows, and the deposits appear as
cash flows (for example 20 deposits and withdrawals in one Myfxbook
account). A full audit of four of them produces the "El dinero real de la
cuenta" section.

## Limits

- The Myfxbook help page was not reachable (HTTP 403), so the column list
  comes from real files, not documentation. Only US month-first dates were
  seen; a day-first file is read when a day above 12 decides the order, and
  refused as ambiguous otherwise.
- Only one public FX Blue export was found, with no withdrawal row.
- No file stated a time zone; times are read as UTC and the report says so.
- The two Myfxbook "copies" (a `History` title line, `DD.MM.YYYY` dates,
  `Gain` with `%`) look pasted from the web page; they are read too, but
  their `Profit` may be gross or net and no costs are itemised.
