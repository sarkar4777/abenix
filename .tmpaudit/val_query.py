import asyncio, os, json
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

async def go():
    url = os.environ['DATABASE_URL']
    e = create_async_engine(url)
    async with e.connect() as c:
        r = await c.execute(text(
            "select id::text, scope, status, portfolio_mtm, portfolio_mtm_ccy, "
            "left(error_message,200) as err, "
            "payload->>'narrative_summary' as narr_sum, "
            "payload->>'narrative' as narr, "
            "payload->'per_contract' as per_c, "
            "payload->'fx_used' as fx, "
            "payload->'top_risks' as risks, "
            "payload->'greeks' as greeks, "
            "created_at "
            "from contractiq_valuations where valuation_type='mtm' "
            "order by created_at desc limit 12"
        ))
        for row in r:
            d = dict(row._mapping)
            d['created_at'] = str(d['created_at'])
            print(json.dumps(d, default=str))

asyncio.run(go())
