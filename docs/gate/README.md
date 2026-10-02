# Phase 2 gate: moving-average crossover checked by hand

`phase2-ma-crossover-gate.xlsx` replays the moving-average crossover (20/50, stop 2 × ATR 14) on
1,500 daily candles using only spreadsheet formulas: averages, ATR, crossings, fills with spread
and slippage, 1%-risk sizing with the 30:1 cap, stop-losses (including gaps), commission and
overnight financing. The **Trades** sheet puts the app's figures beside the spreadsheet's and
the **Summary** sheet (last tab) shows the result.

Result (2 October 2026): 17 of 17 trades match to the penny; final balance £892.97 in both. **Gate passed.**

Regenerate after changing the backtester:

```bash
cd backend
python scripts/gate_ma_cross.py ../docs/gate/phase2-ma-crossover-gate.xlsx --bars 1500
# then open it in Excel (recalculates automatically), or with LibreOffice:
SC_NO_THREADED_CALCULATION=1 SC_FORCE_CALCULATION=core soffice --headless --convert-to xlsx ...
```

LibreOffice's multi-threaded calculation mis-evaluates long row-to-row chains; the two
environment variables above switch it to plain sequential calculation. Excel needs nothing.
