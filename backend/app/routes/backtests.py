"""Strategies and backtests."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..backtest import basket_service, service
from ..backtest.costs import default_costs
from ..db import get_session
from ..deps import current_user
from ..market.providers.base import ProviderError
from ..models import BacktestRun, User
from ..strategies.library import STRATEGIES

router = APIRouter(prefix="/api", tags=["backtests"])
KEEP_RUNS = 100


@router.get("/strategies")
def strategies(_: User = Depends(current_user)) -> dict:
    return {
        "strategies": [s.to_dict() for s in STRATEGIES.values()],
        "defaultCosts": {
            cls: {mode: default_costs(cls, mode).to_dict() for mode in ("cash", "cfd")}
            for cls in ("forex", "metal", "commodity", "index", "bond", "stock", "etf", "ukstock")
        },
        "defaultModes": {cls: service.default_mode(cls) for cls in
                         ("forex", "metal", "commodity", "index", "bond", "stock", "etf", "ukstock")},
    }


class BacktestBody(BaseModel):
    symbol: str = Field(max_length=32)
    timeframe: str = Field("1d", max_length=4)
    strategy: str = Field("ma_cross", max_length=40)
    params: dict[str, float] = Field(default_factory=dict)
    start_balance: float = Field(200, ge=10, le=10_000_000)
    risk_pct: float = Field(1.0, ge=0.1, le=2.0)
    mode: str = Field("", max_length=8)
    direction: str = Field("long", max_length=8)
    years: float = Field(0, ge=0, le=50)
    daily_loss_pct: float = Field(3.0, ge=0.5, le=20)
    max_drawdown_pct: float = Field(20.0, ge=2, le=60)
    keep_going: bool = False
    costs: dict[str, float] = Field(default_factory=dict)


class BasketBody(BaseModel):
    markets: list[str] = Field(min_length=1, max_length=basket_service.MAX_MARKETS)
    timeframe: str = Field("1d", max_length=4)
    strategy: str = Field("breakout", max_length=40)
    params: dict[str, float] = Field(default_factory=dict)
    start_balance: float = Field(200, ge=10, le=10_000_000)
    risk_pct: float = Field(1.0, ge=0.1, le=2.0)
    mode: str = Field("cfd", max_length=8)
    direction: str = Field("long", max_length=8)
    max_open_risk_pct: float = Field(10.0, ge=1, le=10)
    years: float = Field(0, ge=0, le=50)
    daily_loss_pct: float = Field(3.0, ge=0.5, le=20)
    max_drawdown_pct: float = Field(20.0, ge=2, le=60)
    keep_going: bool = False


@router.post("/backtests/basket")
def run_basket(body: BasketBody, db: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    try:
        return basket_service.run(db, basket_service.Request(**body.model_dump()))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


def _summary(run: BacktestRun) -> dict:
    return {"id": run.id, "createdAt": run.created_at.isoformat(), "symbol": run.symbol,
            "timeframe": run.timeframe, "strategy": run.strategy, **run.summary}


@router.post("/backtests")
def run_backtest(body: BacktestBody, db: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    try:
        result = service.run(db, service.Request(**body.model_dump()))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    m, bh = result["metrics"], result["buyHold"]
    run = BacktestRun(
        user_id=user.id, symbol=result["symbol"]["code"], timeframe=result["timeframe"],
        strategy=result["strategy"]["key"],
        summary={"strategyName": result["strategy"]["name"], "symbolName": result["symbol"]["name"],
                 "returnPct": m["returnPct"], "annualPct": m["annualPct"], "trades": m["trades"],
                 "maxDrawdownPct": m["maxDrawdownPct"], "buyHoldPct": bh["returnPct"],
                 "years": m["years"], "sample": result["sample"], "mode": result["assumptions"]["mode"]},
        result=result,
    )
    db.add(run)
    db.flush()
    old = db.scalars(select(BacktestRun.id).where(BacktestRun.user_id == user.id)
                     .order_by(BacktestRun.created_at.desc(), BacktestRun.id.desc()).offset(KEEP_RUNS)).all()
    if old:
        db.execute(delete(BacktestRun).where(BacktestRun.id.in_(old)))
    db.commit()
    return {"id": run.id, **result}


@router.get("/backtests")
def list_backtests(db: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    runs = db.scalars(select(BacktestRun).where(BacktestRun.user_id == user.id)
                      .order_by(BacktestRun.created_at.desc(), BacktestRun.id.desc()).limit(KEEP_RUNS)).all()
    return {"runs": [_summary(r) for r in runs]}


@router.get("/backtests/{run_id}")
def get_backtest(run_id: int, db: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    run = db.get(BacktestRun, run_id)
    if run is None or run.user_id != user.id:
        raise HTTPException(status_code=404, detail="Backtest not found.")
    return {"id": run.id, **run.result}


@router.delete("/backtests/{run_id}")
def delete_backtest(run_id: int, db: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    db.execute(delete(BacktestRun).where(BacktestRun.id == run_id, BacktestRun.user_id == user.id))
    db.commit()
    return {"ok": True}
