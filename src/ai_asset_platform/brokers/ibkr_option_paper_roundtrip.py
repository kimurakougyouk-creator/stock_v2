"""Controlled one-contract SPY option Paper round-trip.

Paper-only verification. Requires an exact confirmation string, resolves the
same explicit option candidate proven by the What-If flow, requires a flat
starting position and no matching open order, then BUY 1 and SELL 1 to flat.
No retry after uncertain order outcome. Live Trading is never enabled.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from threading import Event, Thread

from ibapi.client import EClient
from ibapi.contract import Contract
from ibapi.order import Order
from ibapi.wrapper import EWrapper

from ai_asset_platform.brokers.ibkr_config import create_ibkr_paper_config
from ai_asset_platform.brokers.ibkr_option_whatif import _resolve_target
from ai_asset_platform.brokers.ibkr_thread_runner import run_ibapi_message_loop_safely
from ai_asset_platform.core.settings import SETTINGS

CONFIRMATION_TEXT = "YES_BUY_AND_SELL_ONE_SPY_OPTION_PAPER_TO_FLAT"

@dataclass(frozen=True)
class OptionPaperRoundTripResult:
    attempted: bool
    reason: str
    endpoint_port: int | None
    local_symbol: str | None
    start_quantity: float | None
    buy_order_id: int | None
    buy_filled: float
    buy_avg_price: float | None
    sell_order_id: int | None
    sell_filled: float
    sell_avg_price: float | None
    end_quantity: float | None
    broker_flat_after: bool
    errors: tuple[str, ...] = field(default_factory=tuple)
    real_paper_order_sent: bool = False
    live_order_sent: bool = False

class _Probe(EWrapper, EClient):
    def __init__(self):
        EWrapper.__init__(self); EClient.__init__(self, self)
        self.ready=Event(); self.position_ready=Event(); self.open_ready=Event(); self.done=Event()
        self.next_id=None; self.positions=[]; self.open_orders=[]; self.statuses={}; self.errors=[]
    def nextValidId(self, orderId): self.next_id=int(orderId); self.ready.set()
    def position(self, account, contract, pos, avgCost):
        self.positions.append((str(getattr(contract,'localSymbol','')).upper(),str(getattr(contract,'secType','')).upper(),float(pos)))
    def positionEnd(self): self.position_ready.set()
    def openOrder(self, orderId, contract, order, orderState):
        self.open_orders.append((str(getattr(contract,'localSymbol','')).upper(),str(getattr(contract,'secType','')).upper(),int(orderId)))
    def openOrderEnd(self): self.open_ready.set()
    def orderStatus(self, orderId, status, filled, remaining, avgFillPrice, *args):
        avg=float(avgFillPrice) if float(avgFillPrice or 0)>0 else None
        self.statuses[int(orderId)]=(str(status).upper(),float(filled),avg)
        if str(status).upper() in {'FILLED','CANCELLED','INACTIVE'}: self.done.set()
    def error(self, reqId, *args):
        if len(args)>=3: code,text=args[-2],args[-1]
        elif len(args)>=2: code,text=args[0],args[1]
        else: return
        self.errors.append(f'{code}: {text}')
        try: ci=int(code)
        except Exception: ci=0
        if ci in {201,202,321,322,323,326,502,503,504,1100}: self.done.set(); self.ready.set()

def _contract(c):
    x=Contract(); x.conId=int(c.con_id); x.symbol='SPY'; x.secType='OPT'; x.exchange='SMART'; x.currency='USD'
    x.localSymbol=str(c.local_symbol); x.lastTradeDateOrContractMonth=str(c.expiry); x.strike=float(c.strike); x.right=str(c.right); x.multiplier=str(c.multiplier)
    return x

def _qty(p, local):
    m=[q for l,s,q in p.positions if l==local.upper() and s=='OPT']
    if len(m)>1: raise RuntimeError('multiple matching option positions')
    return 0.0 if not m else float(m[0])

def _refresh(p, local, timeout):
    p.positions.clear(); p.position_ready.clear(); p.reqPositions()
    if not p.position_ready.wait(timeout): return None
    try: return _qty(p,local)
    finally: p.cancelPositions()

def _open(p, local, timeout):
    p.open_orders.clear(); p.open_ready.clear(); p.reqOpenOrders()
    if not p.open_ready.wait(timeout): raise RuntimeError('open-order verification timed out')
    return any(l==local.upper() and s=='OPT' for l,s,_ in p.open_orders)

def _order(side, ref):
    o=Order(); o.action=side; o.orderType='MKT'; o.totalQuantity=1; o.tif='DAY'; o.whatIf=False; o.transmit=True; o.orderRef=ref; return o

def run_option_paper_roundtrip(*, timeout=25.0):
    empty=lambda reason: OptionPaperRoundTripResult(False,reason,None,None,None,None,0,None,None,0,None,None,False)
    if not SETTINGS.enable_ibkr_paper: return empty('IBKR Paper is not explicitly enabled')
    if SETTINGS.enable_live_trading or SETTINGS.live_trading_unlocked: return empty('Live Trading safety lock is not intact')
    if os.getenv('IBKR_OPTION_E2E_CONFIRM','').strip()!=CONFIRMATION_TEXT: return empty('exact SPY option Paper E2E confirmation is missing')
    port,candidate,discovery_errors=_resolve_target()
    if candidate is None: return OptionPaperRoundTripResult(False,'option target resolution failed',port,None,None,None,0,None,None,0,None,None,False,tuple(discovery_errors))
    local=str(candidate.local_symbol); cfg=create_ibkr_paper_config(use_gateway=(port==4002)); p=_Probe(); sent=False
    try:
        p.connect(cfg.host,cfg.port,cfg.client_id+296); Thread(target=run_ibapi_message_loop_safely,kwargs={'client':p,'errors':p.errors},daemon=True).start()
        if not p.ready.wait(timeout) or p.next_id is None: return OptionPaperRoundTripResult(False,'IBKR Paper handshake failed',cfg.port,local,None,None,0,None,None,0,None,None,False,tuple(discovery_errors)+tuple(p.errors))
        start=_refresh(p,local,timeout)
        if start is None or abs(start)>1e-9: return OptionPaperRoundTripResult(False,f'option broker position must start flat; found {start}',cfg.port,local,start,None,0,None,None,0,None,start,False,tuple(discovery_errors)+tuple(p.errors))
        if _open(p,local,timeout): return OptionPaperRoundTripResult(False,'matching option open order already exists',cfg.port,local,start,None,0,None,None,0,None,start,False,tuple(discovery_errors)+tuple(p.errors))
        c=_contract(candidate); buy=int(p.next_id); p.done.clear(); p.placeOrder(buy,c,_order('BUY','stock_v2-option-paper-e2e-buy')); sent=True; p.done.wait(timeout); bs=p.statuses.get(buy)
        if bs is None or bs[0]!='FILLED' or abs(bs[1]-1)>1e-9:
            end=_refresh(p,local,timeout); return OptionPaperRoundTripResult(True,'BUY outcome is not a confirmed full fill; no automatic resend/SELL performed',cfg.port,local,start,buy,0 if bs is None else bs[1],None if bs is None else bs[2],None,0,None,end,bool(end is not None and abs(end)<=1e-9),tuple(discovery_errors)+tuple(p.errors),True,False)
        held=_refresh(p,local,timeout)
        if held is None or abs(held-1)>1e-9: return OptionPaperRoundTripResult(True,'BUY filled but broker position did not verify exactly +1; close not sent',cfg.port,local,start,buy,bs[1],bs[2],None,0,None,held,False,tuple(discovery_errors)+tuple(p.errors),True,False)
        if _open(p,local,timeout): return OptionPaperRoundTripResult(True,'unexpected matching open order after BUY; close not sent',cfg.port,local,start,buy,bs[1],bs[2],None,0,None,held,False,tuple(discovery_errors)+tuple(p.errors),True,False)
        sell=buy+1; p.done.clear(); p.placeOrder(sell,c,_order('SELL','stock_v2-option-paper-e2e-flat')); p.done.wait(timeout); ss=p.statuses.get(sell); end=None
        for _ in range(4):
            end=_refresh(p,local,timeout)
            if end is not None and abs(end)<=1e-9: break
            time.sleep(1)
        flat=bool(end is not None and abs(end)<=1e-9)
        return OptionPaperRoundTripResult(True,'option Paper round-trip completed and broker is flat' if flat else 'SELL sent but broker flat state is not confirmed; no automatic resend',cfg.port,local,start,buy,bs[1],bs[2],sell,0 if ss is None else ss[1],None if ss is None else ss[2],end,flat,tuple(discovery_errors)+tuple(p.errors),sent,False)
    finally:
        if p.isConnected(): p.disconnect()

def main():
    r=run_option_paper_roundtrip(); print('===== IBKR PAPER SPY OPTION ROUND-TRIP E2E =====')
    for k,v in [('ATTEMPTED',r.attempted),('REASON',r.reason),('ENDPOINT PORT',r.endpoint_port),('LOCAL SYMBOL',r.local_symbol),('START QTY',r.start_quantity),('BUY ORDER ID',r.buy_order_id),('BUY FILLED',r.buy_filled),('BUY AVG PRICE',r.buy_avg_price),('SELL ORDER ID',r.sell_order_id),('SELL FILLED',r.sell_filled),('SELL AVG PRICE',r.sell_avg_price),('END QTY',r.end_quantity),('BROKER FLAT AFTER',r.broker_flat_after),('ERRORS',list(r.errors)),('REAL PAPER ORDER SENT',r.real_paper_order_sent),('LIVE ORDER SENT',r.live_order_sent)]: print(f'{k:22}:',v)
    return 0 if r.attempted and r.broker_flat_after and not r.live_order_sent else 2
if __name__=='__main__': raise SystemExit(main())
